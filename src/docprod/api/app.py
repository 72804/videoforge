from __future__ import annotations

import hmac
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
    stars,
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
from docprod.telegram.client import FakeTelegramClient, HttpxTelegramClient, TelegramClient


def _secrets_match(given: str, expected: str) -> bool:
    if not expected:
        return False
    left = given.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def create_app(
    *,
    service: ProductService | None = None,
    sessions: SessionIssuer | None = None,
    env: str = "test",
    cors_origins: list[str] | None = None,
    persist_path: Path | None = None,
    session_secret: str = "dev-session-secret-not-for-production",
    telegram: TelegramClient | None = None,
    payment_mode: str = "simulated",
    generation_mode: str = "mock",
    webhook_secret: str = "",
    mini_app_url: str = "",
    allow_paid_generation: bool = False,
    job_execution_mode: str = "worker",
    internal_job_secret: str = "",
    notifier=None,
) -> FastAPI:
    if service is None:
        repo = load_repository_file(persist_path) if persist_path else None
        storage = MemoryStorageBackend()
        if persist_path:
            blob_root = persist_path.parent / "blobs"
            storage = LocalStorageBackend(blob_root)
        service = ProductService(repo, storage=storage)
    worker = MockGenerationWorker(
        service,
        generation_mode=generation_mode,
        allow_paid_generation=allow_paid_generation,
    )
    origins = list(cors_origins or [])
    if env in {"development", "test"} and not origins:
        origins = ["http://127.0.0.1:3000", "http://localhost:3000"]
    ctx = AppContext(
        service=service,
        sessions=sessions or SessionIssuer(session_secret),
        env=env,
        worker=worker,
        cors_origins=origins,
        telegram=telegram or FakeTelegramClient(),
        payment_mode=payment_mode,
        generation_mode=generation_mode,
        webhook_secret=webhook_secret,
        mini_app_url=mini_app_url,
        job_execution_mode=job_execution_mode,
        internal_job_secret=internal_job_secret,
        notifier=notifier,
    )
    app = FastAPI(
        title="Docprod Telegram Mini App API",
        version="0.1.0",
        description="Local Telegram Mini App backend. No paid providers.",
    )
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
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
        return JSONResponse(
            content=ReadyResponse(
                status="ok",
                database=body.database,
                payment_mode=ctx.payment_mode,
                generation_mode=ctx.generation_mode,
                allow_paid_generation=False,
            ).model_dump()
        )

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
    app.include_router(stars.router, prefix=prefix)
    if env in {"development", "test"}:
        app.include_router(payments_dev.router, prefix=prefix)

    @app.post("/telegram/webhook", tags=["telegram"], operation_id="telegramWebhook")
    async def telegram_webhook(request: Request) -> dict[str, bool]:
        from docprod.telegram.updates import dispatch_update

        secret = ctx.webhook_secret
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if ctx.env == "production" and not secret:
            raise HTTPException(status_code=401, detail="webhook secret required")
        if secret and not _secrets_match(header, secret):
            raise HTTPException(status_code=401, detail="invalid webhook secret")
        try:
            payload = await request.json()
        except Exception:
            return {"ok": True}
        if not isinstance(payload, dict):
            return {"ok": True}
        try:
            dispatch_update(ctx.service, ctx.telegram, payload, mini_app_url=ctx.mini_app_url)
        except Exception:
            return {"ok": True}
        return {"ok": True}

    @app.post("/internal/jobs/run", tags=["internal"], operation_id="runQueuedJobs")
    def run_queued_jobs(request: Request) -> dict[str, int]:
        from docprod.product.durable import DurableGenerationWorker
        from docprod.product.notifications import MockNotificationSender

        expected = ctx.internal_job_secret
        header = request.headers.get("X-Internal-Job-Secret", "")
        if not _secrets_match(header, expected):
            raise HTTPException(status_code=401, detail="invalid internal job secret")
        ran = DurableGenerationWorker(
            ctx.service,
            worker_id="serverless",
            sender=ctx.notifier or MockNotificationSender(),
            generation_mode=ctx.generation_mode,
            allow_paid_generation=False,
        ).run_bounded(max_jobs=1)
        return {"ran": ran}

    @app.post("/api/v1/dev/jobs/{job_id}/run", tags=["dev-payments"], operation_id="devRunJob")
    def run_job(job_id: str) -> dict[str, str]:
        if ctx.env not in {"development", "test"}:
            return {"status": "disabled"}
        ctx.worker.run_job(job_id)
        job = service.repo.jobs[job_id]
        return {"job_id": job.id, "status": job.status.value}

    return app


def app_from_settings() -> FastAPI:
    from docprod.config import (
        cors_origin_list,
        get_settings,
        resolve_job_execution_mode,
        validate_runtime_settings,
    )
    from docprod.logging_utils import get_logger
    from docprod.product.notifications import MockNotificationSender, TelegramNotificationSender

    settings = get_settings()
    validate_runtime_settings(settings, role="api")
    env = getattr(settings, "app_env", "development")
    secret = "dev-session-secret-not-for-production"
    if settings.api_session_secret is not None:
        value = settings.api_session_secret.get_secret_value().strip()
        if value:
            secret = value
    origins = cors_origin_list(settings.api_cors_origins)
    default_store = Path("product_data/store.json")
    store = Path(settings.product_store_path) if settings.product_store_path else default_store
    persist = store if persistence_mode(settings) == "json" else None
    service = build_product_service(settings, store=store)
    token = ""
    if settings.telegram_bot_token is not None:
        token = settings.telegram_bot_token.get_secret_value().strip()
    webhook_secret = ""
    if settings.telegram_webhook_secret is not None:
        webhook_secret = settings.telegram_webhook_secret.get_secret_value().strip()
    payment_mode = settings.payment_mode.strip().lower() or "simulated"
    if payment_mode in {"telegram", "fake"} and token:
        telegram: TelegramClient = HttpxTelegramClient(token)
    else:
        telegram = FakeTelegramClient()
    notifier = MockNotificationSender()
    if token:
        notifier = TelegramNotificationSender(
            telegram,
            mini_app_url=settings.telegram_mini_app_url.strip(),
        )
    internal = ""
    if settings.internal_job_secret is not None:
        internal = settings.internal_job_secret.get_secret_value().strip()
    log = get_logger("api")
    log.info(
        "Payment mode: %s | Generation mode: %s | ALLOW_PAID_GENERATION=%s",
        payment_mode,
        settings.generation_mode,
        settings.allow_paid_generation,
    )
    return create_app(
        service=service,
        env=env,
        cors_origins=origins,
        persist_path=persist,
        session_secret=secret,
        telegram=telegram,
        payment_mode=payment_mode,
        generation_mode=settings.generation_mode.strip().lower() or "mock",
        webhook_secret=webhook_secret,
        mini_app_url=settings.telegram_mini_app_url.strip(),
        allow_paid_generation=settings.allow_paid_generation,
        job_execution_mode=resolve_job_execution_mode(settings),
        internal_job_secret=internal,
        notifier=notifier,
    )


app = None  # Vercel Services loads services/api/app.py, not this module-level name.


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
