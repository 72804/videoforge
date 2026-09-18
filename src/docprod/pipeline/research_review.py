from __future__ import annotations

from docprod.audio.script import tokenize_display
from docprod.research.models import (
    DossierValidationSummary,
    ResearchDossier,
    SourceRegistry,
    TopicSpec,
)
from docprod.research.validation import evaluate_research_quality
from docprod.storage.json_store import atomic_write_text, load_model
from docprod.storage.paths import ProjectPaths
from docprod.writing.models import NarrationScript


def write_research_review(paths: ProjectPaths) -> str:
    topic = load_model(paths.topic_json(), TopicSpec)
    report = (
        paths.research_report_md().read_text(encoding="utf-8")
        if paths.research_report_md().is_file()
        else ""
    )
    registry = (
        load_model(paths.sources_json(), SourceRegistry) if paths.sources_json().is_file() else None
    )
    dossier = (
        load_model(paths.research_dossier_json(), ResearchDossier)
        if paths.research_dossier_json().is_file()
        else None
    )
    validation = (
        load_model(paths.dossier_validation_json(), DossierValidationSummary)
        if paths.dossier_validation_json().is_file()
        else None
    )
    script = (
        load_model(paths.story_script_json(), NarrationScript)
        if paths.story_script_json().is_file()
        else None
    )
    lines: list[str] = ["# Research and script review", ""]
    lines += ["## Topic", "", topic.topic, ""]
    lines += [
        f"- Language: {topic.language}",
        f"- Target runtime: {topic.target_runtime_minutes} minutes",
        f"- Content type: {topic.content_type}",
        "",
    ]
    if registry:
        lines += ["## Source summary", ""]
        tiers = {"A": 0, "B": 0, "C": 0, "low": 0}
        for item in registry.sources:
            tiers[item.quality_tier] = tiers.get(item.quality_tier, 0) + 1
        lines.append(
            f"{len(registry.sources)} sources retained. "
            f"Tiers A={tiers['A']} B={tiers['B']} C={tiers['C']} low={tiers['low']}."
        )
        lines.append("")
        useful = [item for item in registry.sources if item.quality_tier != "low"]
        for item in useful:
            lines.append(
                f"- {item.source_id} [{item.quality_tier}] {item.title or item.domain} — {item.url}"
            )
        low_count = sum(1 for item in registry.sources if item.quality_tier == "low")
        if low_count:
            lines.append(
                f"- Plus {low_count} low-quality or unclassified URLs omitted from this review."
            )
        lines.append("")
        quality = evaluate_research_quality(report, registry, require=False)
        lines += ["## Research summary", "", report.strip()[:4000], ""]
        if len(report) > 4000:
            lines += [
                "_(Report truncated in this review file; full text is in 01_research_report.md.)_",
                "",
            ]
        lines += [f"Quality gate: {'PASS' if quality.passed else 'FAIL'}", ""]
    if dossier:
        lines += ["## Key verified facts", ""]
        for fact in dossier.facts:
            if fact.status == "uncertain":
                continue
            refs = ", ".join(fact.source_ids)
            lines.append(
                f"- {fact.fact_id} ({fact.status}/{fact.confidence}) {fact.claim} [{refs}]"
            )
        lines += ["", "## Timeline", ""]
        for event in dossier.timeline_events:
            refs = ", ".join(event.source_ids)
            lines.append(f"- {event.date_or_range}: {event.description} [{refs}]")
        lines += ["", "## Uncertainties / disagreements", ""]
        if not dossier.uncertainties and not dossier.contradictions:
            lines.append("None recorded.")
        for item in dossier.uncertainties:
            lines.append(f"- Uncertainty: {item.description}")
        for item in dossier.contradictions:
            lines.append(f"- Disagreement: {item.description}")
        lines.append("")
        if validation:
            lines.append(
                f"Dossier facts used: {validation.fact_count}. "
                f"Unsupported/demoted: {validation.unsupported_fact_count}."
            )
            lines.append("")
    if script:
        lines += ["## Story outline", ""]
        if script.outline.logline:
            lines += [script.outline.logline, ""]
        for chapter in script.outline.chapters:
            lines.append(f"- {chapter.chapter_id}: {chapter.title} — {chapter.purpose}")
        lines += ["", "## Full Turkish narration script", ""]
        for beat in script.beats:
            lines += [beat.narration.strip(), ""]
        words = script.word_count or len(tokenize_display(script.full_narration))
        lines += [
            f"**Script word count:** {words}",
            f"**Estimated runtime:** {script.estimated_runtime_minutes:.2f} minutes",
            "",
            "## Claim/source coverage",
            "",
        ]
        if script.validation:
            cov = script.validation
            lines.append(
                f"Beats {cov.beat_count}, chapters {cov.chapter_count}, "
                f"claims {cov.claims_referenced}, sources {cov.sources_referenced}, "
                f"unsupported beats {cov.unsupported_beat_count}."
            )
    text = "\n".join(lines).rstrip() + "\n"
    atomic_write_text(paths.research_review_md(), text)
    return text
