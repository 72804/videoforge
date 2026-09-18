from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from docprod.config import Settings, get_settings
from docprod.models.project import Project
from docprod.research.citations import (
    annotations_from_response,
    build_source_registry,
    collect_raw_sources,
    normalize_citations,
    source_index_markdown,
    web_search_sources_from_response,
)
from docprod.research.models import (
    MAX_WEB_TOOL_CALLS,
    RESEARCH_PROMPT_VERSION,
    QualityGateResult,
    ResearchRawResponse,
    SourceRegistry,
    TopicSpec,
)
from docprod.research.openai_web import (
    OpenAIResponsesProvider,
    count_web_search_calls,
    default_max_tool_calls,
    dump_response,
    extract_output_text,
    extract_usage,
    web_search_include,
    web_search_tools,
)
from docprod.research.validation import evaluate_research_quality
from docprod.storage.hashing import content_hash
from docprod.storage.json_store import atomic_write_text, load_model, save_model
from docprod.storage.paths import ProjectPaths

RESEARCH_INSTRUCTIONS = (
    "You are a documentary researcher. Investigate the assigned topic using web search.\n"
    "\nCover, with citations:\n"
    "- exact timeline and locations\n"
    "- organizations involved\n"
    "- how the historical theft worked at a high documentary level (no crime how-to)\n"
    "- estimated quantity/value stolen\n"
    "- discovery of the theft\n"
    "- investigation\n"
    "- people charged/convicted\n"
    "- court outcomes where reliably available\n"
    "- recovery of stolen property/money\n"
    "- unusual verified details\n"
    "- aftermath\n"
    "- disputed or inconsistent figures between sources\n"
    "\nAlso note visual/documentary opportunities (warehouses, barrels, maps, "
    "court records, police/investigation, archival news) without writing visual prompts.\n"
    "\nHard rules:\n"
    "- Never invent a quote, dialogue, date, motive, thought, or emotion.\n"
    "- Never infer guilt beyond documented legal outcomes.\n"
    "- Distinguish charged / accused / convicted and allegation vs established fact.\n"
    "- When sources disagree, preserve the disagreement. Do not pick the dramatic number.\n"
    "- Every significant factual statement must be supported by cited web evidence.\n"
    "- Prefer court/government sources and major news organizations.\n"
)


@dataclass
class ResearchDryRun:
    topic: TopicSpec
    provider: str
    model: str
    max_tool_calls: int
    instructions: str
    expected_paths: list[str]


@dataclass
class ResearchStageResult:
    topic: TopicSpec
    report: str
    registry: SourceRegistry
    raw: ResearchRawResponse
    quality: QualityGateResult
    cache_hit: bool
    request_count: int


def research_request_hash(topic: TopicSpec, *, model: str, max_tool_calls: int) -> str:
    return content_hash(
        {
            "stage": "research_topic",
            "model": model,
            "prompt_version": RESEARCH_PROMPT_VERSION,
            "max_tool_calls": max_tool_calls,
            "tools": web_search_tools(),
            "include": web_search_include(),
            "topic": topic.model_dump(mode="json"),
        }
    )


def prepare_research(
    paths: ProjectPaths,
    *,
    settings: Settings | None = None,
) -> ResearchDryRun:
    cfg = settings or get_settings()
    topic = load_model(paths.topic_json(), TopicSpec)
    return ResearchDryRun(
        topic=topic,
        provider=cfg.research_provider,
        model=cfg.research_model,
        max_tool_calls=cfg.research_max_tool_calls or default_max_tool_calls(),
        instructions=RESEARCH_INSTRUCTIONS,
        expected_paths=[
            str(paths.research_report_md()),
            str(paths.research_response_json()),
            str(paths.sources_json()),
        ],
    )


def _persist_report(paths: ProjectPaths, report: str, registry: SourceRegistry) -> None:
    body = report.rstrip() + "\n" + source_index_markdown(registry)
    atomic_write_text(paths.research_report_md(), body)


def run_research_topic(
    paths: ProjectPaths,
    *,
    project: Project,
    confirm_paid: bool,
    settings: Settings | None = None,
    client: OpenAIResponsesProvider | None = None,
) -> ResearchStageResult:
    _ = project
    cfg = settings or get_settings()
    topic = load_model(paths.topic_json(), TopicSpec)
    model = cfg.research_model
    max_calls = cfg.research_max_tool_calls or MAX_WEB_TOOL_CALLS
    request_hash = research_request_hash(topic, model=model, max_tool_calls=max_calls)
    if paths.research_response_json().is_file() and paths.sources_json().is_file():
        raw = load_model(paths.research_response_json(), ResearchRawResponse)
        if raw.request_hash == request_hash and raw.generation_status == "success":
            registry = load_model(paths.sources_json(), SourceRegistry)
            report = paths.research_report_md().read_text(encoding="utf-8")
            quality = evaluate_research_quality(report, registry, require=True)
            return ResearchStageResult(
                topic=topic,
                report=report,
                registry=registry,
                raw=raw.model_copy(update={"cache_hit": True}),
                quality=quality,
                cache_hit=True,
                request_count=0,
            )
    provider = client or OpenAIResponsesProvider(settings=cfg)
    before = provider.request_count
    started = datetime.now(UTC)
    user_input = (
        f"Project: {topic.project_id}\n"
        f"Topic: {topic.topic}\n"
        f"Language of later narration: {topic.language}\n"
        f"Target runtime minutes: {topic.target_runtime_minutes}\n"
        f"Content type: {topic.content_type}\n"
        f"Audience: {topic.target_audience}\n"
        f"Notes: {topic.research_notes_optional}\n"
        "Write a sourced research report in English with inline evidence. "
        "The later script will be Turkish; research may stay English."
    )
    response = provider.create(
        model=model,
        instructions=RESEARCH_INSTRUCTIONS,
        input_text=user_input,
        confirm_paid=confirm_paid,
        tools=web_search_tools(),
        include=web_search_include(),
        max_tool_calls=max_calls,
    )
    elapsed = (datetime.now(UTC) - started).total_seconds()
    payload = dump_response(response)
    output_text = extract_output_text(response, payload)
    annotations = annotations_from_response(payload)
    search_sources = web_search_sources_from_response(payload)
    web_calls = count_web_search_calls(payload)
    raw_sources = collect_raw_sources(
        annotations=annotations,
        web_search_sources=search_sources,
    )
    registry = build_source_registry(topic.project_id, raw_sources)
    report = normalize_citations(output_text, registry, annotations)
    usage = extract_usage(
        response,
        model=model,
        web_search_calls=web_calls,
        elapsed=elapsed,
        request_count=provider.request_count - before,
    )
    raw = ResearchRawResponse(
        project_id=topic.project_id,
        response_id=str(getattr(response, "id", None) or payload.get("id") or "") or None,
        model=model,
        request_hash=request_hash,
        usage=usage,
        web_search_calls=[
            item
            for item in payload.get("output", [])
            if isinstance(item, dict) and item.get("type") == "web_search_call"
        ],
        sources=[
            {"url": item.url, "title": item.title, "source_id": item.source_id}
            for item in registry.sources
        ],
        output_text=output_text,
        citation_annotations=annotations,
        sanitized_response=payload,
        generation_status="success",
    )
    save_model(paths.research_response_json(), raw)
    save_model(paths.sources_json(), registry)
    _persist_report(paths, report, registry)
    full_report = paths.research_report_md().read_text(encoding="utf-8")
    quality = evaluate_research_quality(full_report, registry, require=True)
    return ResearchStageResult(
        topic=topic,
        report=full_report,
        registry=registry,
        raw=raw,
        quality=quality,
        cache_hit=False,
        request_count=provider.request_count - before,
    )
