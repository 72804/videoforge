from __future__ import annotations

from datetime import UTC, datetime

from docprod.config import Settings, get_settings
from docprod.exceptions import ResearchQualityError
from docprod.research.dossier import (
    DOSSIER_INSTRUCTIONS,
    dossier_input_text,
    dossier_json_schema,
    parse_dossier_json,
    validate_dossier,
)
from docprod.research.models import (
    DOSSIER_PROMPT_VERSION,
    DossierValidationSummary,
    ResearchDossier,
    SourceRegistry,
    TopicSpec,
)
from docprod.research.openai_web import (
    OpenAIResponsesProvider,
    dump_response,
    extract_output_text,
    extract_usage,
)
from docprod.research.validation import evaluate_research_quality
from docprod.storage.hashing import content_hash
from docprod.storage.json_store import load_model, save_json, save_model
from docprod.storage.paths import ProjectPaths


def dossier_request_hash(report: str, registry: SourceRegistry, *, model: str) -> str:
    return content_hash(
        {
            "stage": "build_dossier",
            "model": model,
            "prompt_version": DOSSIER_PROMPT_VERSION,
            "report": report,
            "sources": [item.model_dump(mode="json") for item in registry.sources],
        }
    )


def run_build_dossier(
    paths: ProjectPaths,
    *,
    confirm_paid: bool,
    settings: Settings | None = None,
    client: OpenAIResponsesProvider | None = None,
) -> tuple[ResearchDossier, DossierValidationSummary, bool, int]:
    cfg = settings or get_settings()
    topic = load_model(paths.topic_json(), TopicSpec)
    if not paths.research_report_md().is_file() or not paths.sources_json().is_file():
        raise ResearchQualityError("Research report/sources missing. Run research-topic first.")
    report = paths.research_report_md().read_text(encoding="utf-8")
    registry = load_model(paths.sources_json(), SourceRegistry)
    evaluate_research_quality(report, registry, require=True)
    model = cfg.dossier_model
    request_hash = dossier_request_hash(report, registry, model=model)
    if paths.research_dossier_json().is_file():
        existing = load_model(paths.research_dossier_json(), ResearchDossier)
        if existing.request_hash == request_hash:
            dossier, summary = validate_dossier(existing, registry, require=True)
            save_model(paths.dossier_validation_json(), summary)
            return dossier.model_copy(update={"cache_hit": True}), summary, True, 0
    provider = client or OpenAIResponsesProvider(settings=cfg)
    before = provider.request_count
    started = datetime.now(UTC)
    response = provider.create(
        model=model,
        instructions=DOSSIER_INSTRUCTIONS,
        input_text=dossier_input_text(report, registry),
        confirm_paid=confirm_paid,
        text_format={"format": dossier_json_schema()},
    )
    elapsed = (datetime.now(UTC) - started).total_seconds()
    payload = dump_response(response)
    text = extract_output_text(response, payload)
    save_json(paths.stages_dir / "03_dossier_raw.json", {"output_text": text, "response": payload})
    dossier = parse_dossier_json(
        text,
        project_id=topic.project_id,
        model=model,
        request_hash=request_hash,
    )
    dossier, summary = validate_dossier(dossier, registry, require=True)
    made = provider.request_count - before
    usage = extract_usage(
        response,
        model=model,
        web_search_calls=0,
        elapsed=elapsed,
        request_count=made,
    )
    dossier = dossier.model_copy(update={"usage": usage, "cache_hit": False})
    save_model(paths.research_dossier_json(), dossier)
    save_model(paths.dossier_validation_json(), summary)
    return dossier, summary, False, made
