from __future__ import annotations

from docprod.models.scene import ScenePlan
from docprod.planning.semantic_models import StoryPlanDiagnostics
from docprod.research.models import TopicSpec
from docprod.storage.json_store import atomic_write_text
from docprod.storage.paths import ProjectPaths
from docprod.writing.models import NarrationScript


def write_scene_plan_review(
    paths: ProjectPaths,
    *,
    topic: TopicSpec,
    script: NarrationScript,
    plan: ScenePlan,
    diagnostics: StoryPlanDiagnostics,
) -> str:
    lines = ["# Scene plan review", "", "## Topic", "", topic.topic, ""]
    lines += [
        f"- Script words: {script.word_count}",
        f"- Estimated runtime: {diagnostics.estimated_runtime_seconds / 60:.2f} min "
        f"({diagnostics.estimated_runtime_seconds:.1f}s)",
        f"- Scenes: {diagnostics.scene_count}",
        f"- Avg/min/max duration: {diagnostics.average_scene_duration:.2f} / "
        f"{diagnostics.min_scene_duration:.2f} / {diagnostics.max_scene_duration:.2f} s",
        "",
        "## Strategy distribution",
        "",
    ]
    for key, value in diagnostics.strategy_counts.items():
        lines.append(f"- {key}: {value}")
    lines += [
        "",
        f"- AI-video seconds: {diagnostics.ai_video_seconds:.2f} "
        f"(fraction {diagnostics.ai_video_fraction:.4f})",
        f"- Archive opportunities: {diagnostics.archive_opportunities}",
        f"- Named-person archive opportunities: {diagnostics.named_person_archive_opportunities}",
        f"- Maps: {diagnostics.map_scenes}",
        f"- Document/newspaper/court: {diagnostics.document_scenes}",
        f"- Data/infographic/text: {diagnostics.graphic_scenes}",
        f"- Reenactments: {diagnostics.reenactment_count}",
        f"- Claims referenced: {diagnostics.claims_referenced}",
        f"- Sources referenced: {diagnostics.sources_referenced}",
        "",
        "## Warnings",
        "",
    ]
    warnings = (
        diagnostics.hallucination_warnings
        + diagnostics.repetition_warnings
        + diagnostics.diversity_warnings
    )
    if not warnings:
        lines.append("None.")
    for item in warnings:
        lines.append(f"- `{item.code}` {item.scene_id}: {item.message}")
    lines += [
        "",
        "## Scene table",
        "",
        "| scene | time | narration | visual | strategy | movement | claim/source | notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for scene in plan.scenes:
        meta = scene.metadata
        narr = _cell(scene.narration, 80)
        visual = _cell(str(meta.get("visual_subject") or scene.visual_intent), 60)
        claims = ",".join(meta.get("claim_ids") or [])
        sources = ",".join(meta.get("source_ids") or [])
        notes = _cell(str(meta.get("reasoning_summary") or ""), 50)
        if scene.asset_strategy.value in {"archive_image", "archive_video"}:
            notes = notes or "archive unresolved"
        lines.append(
            f"| {scene.id} | {scene.start:.1f}–{scene.end:.1f}s | {narr} | {visual} | "
            f"{scene.asset_strategy.value} | {meta.get('movement_need', '')} | "
            f"{claims}/{sources} | {notes} |"
        )
    text = "\n".join(lines).rstrip() + "\n"
    atomic_write_text(paths.scene_plan_review_md(), text)
    return text


def _cell(text: str, limit: int) -> str:
    compact = " ".join(text.split()).replace("|", "/")
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"
