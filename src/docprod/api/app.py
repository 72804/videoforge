from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from docprod.api.dependencies import AppContext
from docprod.api.errors import map_product_error
from docprod.api.routes import (
    auth,
    characters,
    jobs,
    models,
    payments_dev,
    plans,
    projects,
    renders,
    scenes,
    usage,
)
from docprod.api.schemas import HealthResponse, ReadyResponse
from docprod.api.session import SessionIssuer
from docprod.db.postgres_repo import PostgresRepository
from docprod.observability import bind_request_id
from docprod.product.errors import ProductError
from docprod.product.factory import build_product_service, persistence_mode
from docprod.product.persist import load_repository_file, save_repository
from docprod.product.services import ProductService
from docprod.product.storage import LocalStorageBackend, MemoryStorageBackend
from docprod.product.worker import MockGenerationWorker


def create_app(
    *,
    service: ProductService | None = None,
    sessions: SessionIssuer | None = None,
    env: str = "test",
    cors_origins: list[str] | None = None,
    persist_path: Path | None = None,
    session_secret: str = "dev-session-secret-not-for-production",
) -> FastAPI:
    if service is None:
        repo = load_repository_file(persist_path) if persist_path else None
        storage = MemoryStorageBackend()
        if persist_path:
            blob_root = persist_path.parent / "blobs"
            storage = LocalStorageBackend(blob_root)
        service = ProductService(repo, storage=storage)
    worker = MockGenerationWorker(service)
    origins = list(cors_origins or [])
    if env in {"development", "test"} and not origins:
        origins = ["http://127.0.0.1:3000", "http://localhost:3000"]
    ctx = AppContext(
        service=service,
        sessions=sessions or SessionIssuer(session_secret),
        env=env,
        worker=worker,
        cors_origins=origins,
    )
    app = FastAPI(
        title="Docprod Telegram Mini App API",
        version="0.1.0",
        description="Local Telegram Mini App backend. No paid providers.",
    )
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ctx.cors_origins or ["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "HTTP", "message": str(exc.detail), "details": {}}},
        )

    @app.exception_handler(ProductError)
    async def product_error(_request: Request, exc: ProductError) -> JSONResponse:
        mapped = map_product_error(exc)
        return JSONResponse(status_code=mapped.status_code, content=mapped.detail)

    @app.exception_handler(SQLAlchemyError)
    async def db_error(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "Unexpected error.", "details": {}}},
        )

    @app.middleware("http")
    async def request_and_persist(request: Request, call_next):
        rid = bind_request_id(request.headers.get("x-request-id"))
        repo = service.repo
        postgres = isinstance(repo, PostgresRepository)
        if postgres:
            repo.open()
            repo.hydrate()
            repo.snapshot()
        try:
            response = await call_next(request)
            if postgres:
                if response.status_code < 500:
                    repo.commit()
                else:
                    repo.rollback()
            elif persist_path is not None:
                save_repository(persist_path, service.repo)
            response.headers["X-Request-ID"] = rid
            return response
        except Exception:
            if postgres:
                repo.rollback()
            raise
        finally:
            if postgres:
                repo.close()

    def _health_body() -> HealthResponse:
        kind = service.repo.persistence_kind()
        database = kind
        try:
            if isinstance(service.repo, PostgresRepository):
                opened = service.repo.session is not None
                if not opened:
                    service.repo.open()
                service.repo.ping()
                if not opened:
                    service.repo.close()
                database = "ok"
        except Exception:
            database = "unavailable"
        worker_state = None
        beat = service.repo.latest_worker_heartbeat()
        if beat is not None:
            worker_state = "ok"
        elif kind == "postgres":
            worker_state = "unknown"
        return HealthResponse(status="ok", database=database, worker=worker_state)

    @app.get("/health", response_model=HealthResponse, tags=["system"], operation_id="health")
    def health() -> HealthResponse:
        return _health_body()

    @app.get("/ready", response_model=ReadyResponse, tags=["system"], operation_id="ready")
    def ready() -> JSONResponse:
        body = _health_body()
        if body.database == "unavailable":
            return JSONResponse(
                status_code=503,
                content=ReadyResponse(status="unavailable", database="unavailable").model_dump(),
            )
        return JSONResponse(content=ReadyResponse(status="ok", database=body.database).model_dump())

    prefix = "/api/v1"
    app.include_router(auth.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(characters.router, prefix=prefix)
    app.include_router(plans.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)
    app.include_router(scenes.router, prefix=prefix)
    app.include_router(renders.router, prefix=prefix)
    app.include_router(models.router, prefix=prefix)
    app.include_router(usage.router, prefix=prefix)
    if env in {"development", "test"}:
        app.include_router(payments_dev.router, prefix=prefix)

    @app.post("/api/v1/dev/jobs/{job_id}/run", tags=["dev-payments"], operation_id="devRunJob")
    def run_job(job_id: str) -> dict[str, str]:
        if ctx.env not in {"development", "test"}:
            return {"status": "disabled"}
        ctx.worker.run_job(job_id)
        job = service.repo.jobs[job_id]
        return {"job_id": job.id, "status": job.status.value}

    return app


def app_from_settings() -> FastAPI:
    from docprod.config import get_settings

    settings = get_settings()
    env = getattr(settings, "app_env", "development")
    secret = "dev-session-secret-not-for-production"
    if settings.api_session_secret is not None:
        value = settings.api_session_secret.get_secret_value().strip()
        if value:
            secret = value
    origins = [p.strip() for p in settings.api_cors_origins.split(",") if p.strip()]
    default_store = Path("product_data/store.json")
    store = Path(settings.product_store_path) if settings.product_store_path else default_store
    persist = store if persistence_mode(settings) == "json" else None
    service = build_product_service(settings, store=store)
    return create_app(
        service=service,
        env=env,
        cors_origins=origins,
        persist_path=persist,
        session_secret=secret,
    )


app = None


def factory() -> FastAPI:
    """Uvicorn factory: `uvicorn docprod.api.app:factory --factory`."""
    return app_from_settings()


def export_openapi(path: Path | None = None) -> dict:
    application = create_app(env="test")
    payload = application.openapi()
    dest = path or Path("docs/openapi.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
