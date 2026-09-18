from __future__ import annotations

from datetime import UTC, datetime

from docprod.config import Settings, get_settings
from docprod.exceptions import DossierValidationError
from docprod.research.models import ResearchDossier, TopicSpec
from docprod.research.openai_web import (
    OpenAIResponsesProvider,
    dump_response,
    extract_output_text,
    extract_usage,
)
from docprod.storage.hashing import content_hash
from docprod.storage.json_store import load_json, load_model, save_json, save_model
from docprod.storage.paths import ProjectPaths
from docprod.writing.documentary import (
    WRITER_INSTRUCTIONS,
    WRITER_PROMPT_VERSION,
    parse_script_json,
    writer_input_text,
    writer_json_schema,
)
from docprod.writing.models import NarrationScript
from docprod.writing.validation import validate_script


def script_request_hash(topic: TopicSpec, dossier: ResearchDossier, *, model: str) -> str:
    return content_hash(
        {
            "stage": "write_script",
            "model": model,
            "prompt_version": WRITER_PROMPT_VERSION,
            "topic": topic.model_dump(mode="json"),
            "dossier_hash": content_hash(dossier.model_dump(mode="json")),
        }
    )


def run_write_script(
    paths: ProjectPaths,
    *,
    confirm_paid: bool,
    settings: Settings | None = None,
    client: OpenAIResponsesProvider | None = None,
    word_min: int | None = None,
    word_max: int | None = None,
) -> tuple[NarrationScript, bool, int]:
    cfg = settings or get_settings()
    topic = load_model(paths.topic_json(), TopicSpec)
    if not paths.research_dossier_json().is_file():
        raise DossierValidationError("Dossier missing. Run build-dossier first.")
    dossier = load_model(paths.research_dossier_json(), ResearchDossier)
    model = cfg.writer_model
    request_hash = script_request_hash(topic, dossier, model=model)
    if paths.story_script_json().is_file():
        existing = load_model(paths.story_script_json(), NarrationScript)
        if existing.request_hash == request_hash:
            kwargs = {}
            if word_min is not None:
                kwargs["word_min"] = word_min
            if word_max is not None:
                kwargs["word_max"] = word_max
            script, _summary = validate_script(existing, dossier, require=True, **kwargs)
            return script.model_copy(update={"cache_hit": True}), True, 0
    raw_path = paths.stages_dir / "04_script_raw.json"
    if raw_path.is_file():
        raw = load_json(raw_path)
        text = ""
        if isinstance(raw, dict):
            text = str(raw.get("output_text") or "")
        if text.strip():
            kwargs = {}
            if word_min is not None:
                kwargs["word_min"] = word_min
            if word_max is not None:
                kwargs["word_max"] = word_max
            script = parse_script_json(
                text,
                project_id=topic.project_id,
                language=topic.language,
                model=model,
                request_hash=request_hash,
            )
            script, _summary = validate_script(script, dossier, require=True, **kwargs)
            usage = None
            resp = raw.get("response") if isinstance(raw, dict) else None
            if isinstance(resp, dict) and resp.get("usage"):
                from types import SimpleNamespace

                usage = extract_usage(
                    SimpleNamespace(usage=resp["usage"]),
                    model=model,
                    web_search_calls=0,
                    elapsed=0.0,
                    request_count=1,
                )
            script = script.model_copy(update={"usage": usage, "cache_hit": True})
            save_model(paths.story_script_json(), script)
            return script, True, 0
    provider = client or OpenAIResponsesProvider(settings=cfg)
    before = provider.request_count
    started = datetime.now(UTC)
    response = provider.create(
        model=model,
        instructions=WRITER_INSTRUCTIONS,
        input_text=writer_input_text(topic, dossier),
        confirm_paid=confirm_paid,
        text_format={"format": writer_json_schema()},
    )
    elapsed = (datetime.now(UTC) - started).total_seconds()
    payload = dump_response(response)
    text = extract_output_text(response, payload)
    save_json(paths.stages_dir / "04_script_raw.json", {"output_text": text, "response": payload})
    script = parse_script_json(
        text,
        project_id=topic.project_id,
        language=topic.language,
        model=model,
        request_hash=request_hash,
    )
    kwargs = {}
    if word_min is not None:
        kwargs["word_min"] = word_min
    if word_max is not None:
        kwargs["word_max"] = word_max
    script, _summary = validate_script(script, dossier, require=True, **kwargs)
    made = provider.request_count - before
    usage = extract_usage(
        response,
        model=model,
        web_search_calls=0,
        elapsed=elapsed,
        request_count=made,
    )
    script = script.model_copy(update={"usage": usage, "cache_hit": False})
    save_model(paths.story_script_json(), script)
    return script, False, made
