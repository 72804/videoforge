from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from docprod.audio.script import tokenize_display
from docprod.config import Settings, get_settings
from docprod.exceptions import SemanticPlannerError
from docprod.models.scene import ScenePlan
from docprod.planning.semantic_compiler import compile_semantic_plan
from docprod.planning.semantic_models import (
    SEMANTIC_PLANNER_PROMPT_VERSION,
    SemanticIntentSet,
    StoryPlanDiagnostics,
)
from docprod.planning.semantic_planner import (
    SEMANTIC_PLANNER_INSTRUCTIONS,
    evidence_rows_for_planner,
    parse_semantic_intents,
    planner_input_text,
    semantic_planner_json_schema,
)
from docprod.providers.request_budget import ModelRequestBudget
from docprod.research.evidence import apply_evidence_set
from docprod.research.models import ResearchDossier, SourceRegistry, TopicSpec
from docprod.research.openai_web import (
    OpenAIResponsesProvider,
    dump_response,
    extract_output_text,
    extract_usage,
)
from docprod.storage.hashing import content_hash
from docprod.storage.json_store import load_json, load_model, save_json, save_model
from docprod.storage.paths import ProjectPaths
from docprod.writing.models import NarrationScript


@dataclass
class StoryPlanDryRun:
    topic: str
    model: str
    script_word_count: int
    chapters: int
    estimated_runtime_minutes: float
    max_model_requests: int
    web_search: bool
    expected_paths: list[str]


@dataclass
class StoryPlanResult:
    intents: SemanticIntentSet
    plan: ScenePlan
    diagnostics: StoryPlanDiagnostics
    cache_hit: bool
    request_count: int


def semantic_plan_request_hash(
    topic: TopicSpec,
    script: NarrationScript,
    dossier: ResearchDossier,
    *,
    model: str,
    evidence_ids: list[str],
) -> str:
    return content_hash(
        {
            "stage": "plan_story_scenes",
            "model": model,
            "prompt_version": SEMANTIC_PLANNER_PROMPT_VERSION,
            "topic": topic.model_dump(mode="json"),
            "script_hash": content_hash(script.model_dump(mode="json")),
            "dossier_hash": content_hash(dossier.model_dump(mode="json")),
            "evidence_source_ids": evidence_ids,
        }
    )


def prepare_story_plan(paths: ProjectPaths, *, settings: Settings | None = None) -> StoryPlanDryRun:
    cfg = settings or get_settings()
    topic = load_model(paths.topic_json(), TopicSpec)
    script = load_model(paths.story_script_json(), NarrationScript)
    words = tokenize_display(script.full_narration)
    return StoryPlanDryRun(
        topic=topic.topic,
        model=cfg.scene_planner_model,
        script_word_count=len(words),
        chapters=len(script.outline.chapters),
        estimated_runtime_minutes=script.estimated_runtime_minutes or round(len(words) / 145.0, 2),
        max_model_requests=1,
        web_search=False,
        expected_paths=[
            str(paths.semantic_intents_json()),
            str(paths.scene_plan_json),
            str(paths.scene_plan_review_md()),
        ],
    )


def persist_evidence_registry(paths: ProjectPaths) -> SourceRegistry:
    registry = load_model(paths.sources_json(), SourceRegistry)
    dossier = (
        load_model(paths.research_dossier_json(), ResearchDossier)
        if paths.research_dossier_json().is_file()
        else None
    )
    script = (
        load_model(paths.story_script_json(), NarrationScript)
        if paths.story_script_json().is_file()
        else None
    )
    updated = apply_evidence_set(registry, dossier=dossier, script=script)
    save_model(paths.sources_json(), updated)
    return updated


def run_plan_story_scenes(
    paths: ProjectPaths,
    *,
    confirm_paid: bool,
    settings: Settings | None = None,
    client: OpenAIResponsesProvider | None = None,
) -> StoryPlanResult:
    cfg = settings or get_settings()
    if not paths.story_script_json().is_file() or not paths.research_dossier_json().is_file():
        raise SemanticPlannerError("Missing story script or dossier. Finish Phase 8 first.")
    topic = load_model(paths.topic_json(), TopicSpec)
    script = load_model(paths.story_script_json(), NarrationScript)
    dossier = load_model(paths.research_dossier_json(), ResearchDossier)
    registry = persist_evidence_registry(paths)
    model = cfg.scene_planner_model
    request_hash = semantic_plan_request_hash(
        topic,
        script,
        dossier,
        model=model,
        evidence_ids=registry.evidence_source_ids,
    )
    if paths.semantic_intents_json().is_file() and paths.scene_plan_json.is_file():
        existing = load_model(paths.semantic_intents_json(), SemanticIntentSet)
        if existing.request_hash == request_hash:
            plan = load_model(paths.scene_plan_json, ScenePlan)
            compiled, diagnostics = compile_semantic_plan(existing, script=script, dossier=dossier)
            save_model(paths.scene_plan_json, compiled)
            return StoryPlanResult(existing, compiled, diagnostics, True, 0)

    words = tokenize_display(script.full_narration)
    raw_path = paths.semantic_planner_raw_json()
    if raw_path.is_file() and not paths.semantic_intents_json().is_file():
        raw = load_json(raw_path)
        text = str((raw or {}).get("output_text") or "") if isinstance(raw, dict) else ""
        if text.strip():
            try:
                intents = parse_semantic_intents(
                    text,
                    project_id=topic.project_id,
                    model=model,
                    request_hash=request_hash,
                    word_count=len(words),
                )
                plan, diagnostics = compile_semantic_plan(intents, script=script, dossier=dossier)
                intents = intents.model_copy(update={"cache_hit": True})
                save_model(paths.semantic_intents_json(), intents)
                save_model(paths.scene_plan_json, plan)
                return StoryPlanResult(intents, plan, diagnostics, True, 0)
            except SemanticPlannerError:
                pass

    provider = client or OpenAIResponsesProvider(settings=cfg)
    budget = ModelRequestBudget(max_requests=1)
    started = datetime.now(UTC)
    response = provider.create(
        model=model,
        instructions=SEMANTIC_PLANNER_INSTRUCTIONS,
        input_text=planner_input_text(
            topic,
            script,
            dossier,
            evidence_rows_for_planner(dossier, registry),
        ),
        confirm_paid=confirm_paid,
        text_format={"format": semantic_planner_json_schema()},
        budget=budget,
        stage="scene_planner",
        allow_retry=False,
    )
    elapsed = (datetime.now(UTC) - started).total_seconds()
    payload = dump_response(response)
    text = extract_output_text(response, payload)
    save_json(raw_path, {"output_text": text, "response": payload})
    try:
        intents = parse_semantic_intents(
            text,
            project_id=topic.project_id,
            model=model,
            request_hash=request_hash,
            word_count=len(words),
        )
        usage = extract_usage(
            response,
            model=model,
            web_search_calls=0,
            elapsed=elapsed,
            request_count=1,
        )
        intents = intents.model_copy(update={"usage": usage, "cache_hit": False})
        plan, diagnostics = compile_semantic_plan(intents, script=script, dossier=dossier)
    except Exception as exc:
        raise SemanticPlannerError(
            f"Semantic planner parse/compile failed; raw saved to {raw_path}. STOP. {exc}"
        ) from exc
    save_model(paths.semantic_intents_json(), intents)
    save_model(paths.scene_plan_json, plan)
    return StoryPlanResult(intents, plan, diagnostics, False, 1)
