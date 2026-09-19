from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from statistics import mean

from docprod.audio.cues import chunk_alignment_cues
from docprod.audio.integrity import evaluate_master_duration
from docprod.audio.join import detect_edge_silence
from docprod.audio.mix import measure_loudnorm
from docprod.audio.models import AlignmentReport, NarrationChunkManifest, RuntimeTimeline
from docprod.audio.script import build_canonical_script, tokenize_display
from docprod.models.enums import AssetStrategy
from docprod.models.scene import ScenePlan
from docprod.pipeline.narration_gates import (
    build_whisper_preflight,
    inspect_chunk_integrity,
    record_historical_maple_repair,
)
from docprod.production import AssetPlan
from docprod.render.ffmpeg import ffmpeg_path, probe_media
from docprod.storage.json_store import load_model, save_json
from docprod.storage.paths import ProjectPaths

SORA_USD_PER_SEC = 0.10

_HIGH_MOTION = (
    "numune",
    "örnek",
    "ornek",
    "dök",
    "dok",
    "pour",
    "sampling",
    "el ",
    "kapa",
    "aç",
    "ac ",
    "manipulation",
    "denetim",
    "inspection",
    "sakla",
    "conceal",
)
_LOW_MOTION = (
    "depo",
    "warehouse",
    "sıra",
    "sira",
    "rows",
    "montaj",
    "establishment",
    "fıçı sıral",
    "barrel row",
    "rezerv",
)


def _ffmpeg_log(path: Path, filters: str) -> str:
    completed = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path), "-vf", filters, "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return (completed.stderr or "") + (completed.stdout or "")


def _audio_log(path: Path, filters: str) -> str:
    completed = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path), "-af", filters, "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return (completed.stderr or "") + (completed.stdout or "")


def _classify_ai_video(concept: str, movement: str, duration: float) -> str:
    text = f"{concept} {movement}".casefold()
    high = any(token in text for token in _HIGH_MOTION)
    low = any(token in text for token in _LOW_MOTION)
    if high and not low:
        return "HIGH_VALUE"
    if high and duration >= 7:
        return "HIGH_VALUE"
    if low and not high:
        return "LOW_VALUE"
    if movement in {"high", "medium"} and high:
        return "HIGH_VALUE"
    if movement in {"none", "low"}:
        return "LOW_VALUE"
    return "MEDIUM_VALUE"


def _chapter_mood(chapter: str, index: int) -> str:
    name = chapter.casefold()
    if index == 0 or "hook" in name or "açılış" in name:
        return "mystery"
    if "legal" in name or "mahkeme" in name or "temyiz" in name or "c008" in name:
        return "legal"
    if "soruş" in name or "investig" in name or "polis" in name:
        return "investigation"
    if "kapan" in name or "resolution" in name or "son" in name:
        return "resolution"
    if index < 2:
        return "tension"
    return "investigation"


def audit_episode(paths: ProjectPaths, *, paid_calls: int = 0) -> dict:
    if paid_calls:
        raise RuntimeError("audit-episode must not make paid API calls")
    plan = load_model(paths.scene_plan_json, ScenePlan)
    asset = load_model(paths.asset_plan_json(), AssetPlan)
    timeline = load_model(paths.runtime_timeline_json(), RuntimeTimeline)
    alignment = load_model(paths.narration_alignment_json(), AlignmentReport)
    script = build_canonical_script(plan)
    historical = load_model(paths.narration_chunk_manifest(), NarrationChunkManifest)
    proposed = _proposed_chunk_plan(paths, plan, script)
    repair = record_historical_maple_repair(paths)
    integrity = inspect_chunk_integrity(paths, historical, run_acoustic=True)
    chunk1 = next((item for item in integrity if item.chunk_id == "chunk_001"), None)
    observed = chunk1.wpm if chunk1 else 115.0
    preflight = build_whisper_preflight(
        paths, canonical_word_count=len(tokenize_display(script.text)), observed_wpm=observed
    )
    raw_master = evaluate_master_duration(
        canonical_word_count=len(tokenize_display(script.text)),
        actual_duration=616.31,
        observed_wpm=observed,
    )
    mp4 = paths.preview_narrated_mp4()
    probe = probe_media(mp4)
    master = probe_media(paths.narration_master_wav())
    loud = measure_loudnorm(paths.narration_master_wav())
    cues = chunk_alignment_cues(alignment)
    scene_unit = {}
    for unit in asset.units:
        for scene_id in unit.scene_ids:
            scene_unit[scene_id] = unit
    durs = [item.duration for item in timeline.scenes]
    short = [item for item in timeline.scenes if item.duration < 2.0]
    long = [item for item in timeline.scenes if item.duration > 8.0]
    very_long = [item for item in timeline.scenes if item.duration > 10.0]
    strategies = Counter()
    for scene in plan.scenes:
        strategies[scene.asset_strategy.value] += 1
    streaks = _streaks(plan, timeline)
    sub_flags = _subtitle_flags(cues)
    black = re.findall(r"black_duration:([0-9.]+)", _ffmpeg_log(mp4, "blackdetect=d=0.4"))
    silences = re.findall(
        r"silence_duration: ([0-9.]+)",
        _audio_log(paths.narration_master_wav(), "silencedetect=noise=-35dB:d=0.6"),
    )
    join = _join_qc(paths, timeline)
    ai_rows = _ai_video_rows(plan, asset, timeline)
    costs = _cost_preview(ai_rows)
    sound = _sound_plan(plan, timeline)
    qc_md = _qc_markdown(
        probe=probe,
        master=master,
        loud=loud,
        timeline=timeline,
        asset=asset,
        cues=cues,
        short=short,
        long=long,
        very_long=very_long,
        strategies=strategies,
        streaks=streaks,
        sub_flags=sub_flags,
        black=black,
        silences=silences,
        join=join,
        durs=durs,
        plan=plan,
        scene_unit=scene_unit,
    )
    paths.review_dir.mkdir(parents=True, exist_ok=True)
    paths.full_episode_qc_md().write_text(qc_md, encoding="utf-8")
    paths.ai_video_decision_md().write_text(_ai_markdown(ai_rows, costs), encoding="utf-8")
    paths.sound_design_plan_md().write_text(sound, encoding="utf-8")
    save_json(paths.next_phase_cost_preview_json(), costs)
    save_json(paths.narration_proposed_chunk_plan(), proposed.model_dump())
    return {
        "paid_calls": 0,
        "proposed_chunks": proposed.chunk_count,
        "proposed": proposed,
        "historical_integrity": [item.__dict__ for item in integrity],
        "raw_master_would_block": raw_master.blocks_whisper(),
        "raw_master": raw_master.__dict__,
        "preflight": preflight,
        "repair": repair,
        "ai_rows": ai_rows,
        "costs": costs,
        "short": short,
        "long": long,
        "sub_flags": sub_flags,
        "join": join,
        "cues": len(cues),
    }


def _proposed_chunk_plan(paths, plan, script):
    from docprod.audio.chunks import NarrationChunkPlanner, validate_chunk_manifest

    proposed = NarrationChunkPlanner().plan(script, plan)
    validate_chunk_manifest(proposed, script)
    save_json(paths.narration_proposed_chunk_plan(), proposed.model_dump())
    return proposed


def _streaks(plan: ScenePlan, timeline: RuntimeTimeline) -> list[str]:
    order = {scene.id: scene for scene in plan.scenes}
    flags: list[str] = []
    run_kind = None
    run_len = 0
    groups = {
        AssetStrategy.generated_graphic: "graphics",
        AssetStrategy.document: "documents",
        AssetStrategy.map: "maps",
        AssetStrategy.archive_image: "archive_stills",
        AssetStrategy.ai_image: "ai_stills",
    }
    for timing in timeline.scenes:
        scene = order[timing.scene_id]
        kind = groups.get(scene.asset_strategy)
        if kind == run_kind:
            run_len += 1
        else:
            if run_kind and run_len >= 4:
                flags.append(f"{run_len} consecutive {run_kind}")
            run_kind = kind
            run_len = 1 if kind else 0
    if run_kind and run_len >= 4:
        flags.append(f"{run_len} consecutive {run_kind}")
    return flags


def _subtitle_flags(cues: list[tuple[float, float, str]]) -> list[str]:
    flags: list[str] = []
    for start, end, text in cues:
        dur = max(end - start, 0.04)
        cps = len(text) / dur
        lines = 1 + text.count("\n")
        if len(text) > 42:
            lines = max(lines, 2)
        label = f"{start:.2f}-{end:.2f} {text[:40]!r}"
        if dur < 0.8:
            flags.append(f"flash {label}")
        if cps > 20:
            flags.append(f"too_fast {cps:.1f}c/s {label}")
        if dur > 6.0 or len(text) > 84:
            flags.append(f"too_long {label}")
        if lines >= 2 and cps > 15:
            flags.append(f"dense_two_line {label}")
    return flags


def _join_qc(paths: ProjectPaths, timeline: RuntimeTimeline) -> dict:
    left = next(item for item in timeline.scenes if item.scene_id == "scene_0039")
    right = next(item for item in timeline.scenes if item.scene_id == "scene_0040")
    chunk1 = paths.narration_chunk_wav(1)
    chunk2 = paths.narration_chunk_wav(2)
    trail = lead = None
    if chunk1.is_file() and chunk2.is_file():
        _, trail = detect_edge_silence(chunk1)
        lead, _ = detect_edge_silence(chunk2)
    return {
        "scene_join": [left.end, right.start],
        "chunk1_trailing_silence": trail,
        "chunk2_leading_silence": lead,
        "target_join_s": 0.36,
    }


def _ai_video_rows(plan: ScenePlan, asset: AssetPlan, timeline: RuntimeTimeline) -> list[dict]:
    scenes = {item.scene_id: item for item in timeline.scenes}
    plan_scenes = {scene.id: scene for scene in plan.scenes}
    rows = []
    for unit in asset.units:
        if unit.source_strategy is not AssetStrategy.ai_image_to_video:
            continue
        real = sum(scenes[sid].duration for sid in unit.scene_ids if sid in scenes)
        movement = str(plan_scenes[unit.scene_ids[0]].metadata.get("movement_need") or "")
        klass = _classify_ai_video(unit.visual_concept, movement, real)
        rows.append(
            {
                "asset_unit_id": unit.asset_unit_id,
                "runtime": round(real, 4),
                "planned": unit.continuous_duration,
                "movement_need": movement,
                "motion_concept": unit.visual_concept,
                "value": klass,
                "sora2_720p_usd": round(real * SORA_USD_PER_SEC, 4),
            }
        )
    return rows


def _cost_preview(rows: list[dict]) -> dict:
    all_usd = round(sum(item["sora2_720p_usd"] for item in rows), 4)
    high = [item for item in rows if item["value"] == "HIGH_VALUE"]
    high_usd = round(sum(item["sora2_720p_usd"] for item in high), 4)
    return {
        "scenario_a_no_ai_video_usd": 0.0,
        "scenario_b_high_value_only_usd": high_usd,
        "scenario_c_all_four_usd": all_usd,
        "music_sfx": "unresolved/free depending future source",
        "provider_price_reference": "Sora 2 standard 720p $0.10/sec — not a vendor lock",
        "units": rows,
    }


def _sound_plan(plan: ScenePlan, timeline: RuntimeTimeline) -> str:
    chapters: list[tuple[str, float, float]] = []
    current = None
    start = 0.0
    scenes = {scene.id: scene for scene in plan.scenes}
    for item in timeline.scenes:
        chapter = str(scenes[item.scene_id].metadata.get("chapter") or "BODY")
        if chapter != current:
            if current is not None:
                chapters.append((current, start, item.start))
            current = chapter
            start = item.start
    if current is not None:
        chapters.append((current, start, timeline.total_duration))
    lines = [
        "# Sound design plan",
        "",
        "Narration remains primary. Plan long beds, not a new cue every scene.",
        "Future ducking: music substantially below voice. Mixing not implemented.",
        "",
    ]
    sfx_cycle = [
        "warehouse ambience",
        "barrel handling",
        "paper/document",
        "truck/road",
        "police ambience",
        "court transition",
        "map transition",
    ]
    for index, (chapter, begin, end) in enumerate(chapters):
        mood = _chapter_mood(chapter, index)
        sfx = sfx_cycle[index % len(sfx_cycle)]
        lines.append(f"## {chapter} ({begin:.1f}–{end:.1f}s)")
        lines.append(f"- music mood: {mood}")
        lines.append(f"- optional sparse SFX: {sfx}")
        lines.append("")
    return "\n".join(lines)


def _visual_kind(strategy: AssetStrategy) -> str:
    mapping = {
        AssetStrategy.stock_video: "stock/native motion",
        AssetStrategy.ai_image_to_video: "keyframe animation",
        AssetStrategy.ai_image: "AI still",
        AssetStrategy.archive_image: "archive still",
        AssetStrategy.generated_graphic: "graphic",
        AssetStrategy.map: "map",
        AssetStrategy.document: "document",
        AssetStrategy.text_card: "text card",
    }
    return mapping.get(strategy, strategy.value)


def _qc_markdown(**kwargs) -> str:
    probe = kwargs["probe"]
    master = kwargs["master"]
    loud = kwargs["loud"]
    timeline = kwargs["timeline"]
    asset = kwargs["asset"]
    cues = kwargs["cues"]
    short = kwargs["short"]
    long = kwargs["long"]
    very_long = kwargs["very_long"]
    strategies = kwargs["strategies"]
    streaks = kwargs["streaks"]
    sub_flags = kwargs["sub_flags"]
    black = kwargs["black"]
    silences = kwargs["silences"]
    join = kwargs["join"]
    durs = kwargs["durs"]
    plan = kwargs["plan"]
    scene_unit = kwargs["scene_unit"]
    lines = [
        "# Full episode QC",
        "",
        f"- duration_video: {probe.duration:.3f}s",
        f"- duration_master: {master.duration:.3f}s",
        f"- scene_count: {len(timeline.scenes)}",
        f"- asset_unit_count: {len(asset.units)}",
        f"- subtitle_cues: {len(cues)}",
        f"- video: {probe.width}x{probe.height} {probe.video_codec} "
        f"{probe.pixel_format} {probe.fps}fps",
        f"- audio: {probe.audio_codec} {probe.sample_rate}Hz {probe.channels}ch",
        f"- loudness I={loud.get('input_i')} TP={loud.get('input_tp')}",
        f"- black_spans>0.4s: {len(black)} {black[:8]}",
        f"- silences>0.6s: {len(silences)} {silences[:8]}",
        f"- scene duration min/avg/max: {min(durs):.2f} / {mean(durs):.2f} / {max(durs):.2f}",
        f"- visual_source_distribution: {dict(strategies)}",
        "",
        "## Short scenes <2.0s (tight)",
    ]
    if not short:
        lines.append("- none")
    for item in short:
        scene = next(s for s in plan.scenes if s.id == item.scene_id)
        unit = scene_unit.get(item.scene_id)
        lines.append(
            f"- {item.scene_id} {item.duration:.2f}s {_visual_kind(scene.asset_strategy)} "
            f"unit={getattr(unit, 'asset_unit_id', '')}"
        )
    lines += ["", "## Long scenes >8.0s"]
    if not long:
        lines.append("- none")
    for item in long:
        scene = next(s for s in plan.scenes if s.id == item.scene_id)
        extra = " VERY_LONG" if item.duration > 10 else ""
        lines.append(
            f"- {item.scene_id} {item.duration:.2f}s{extra} {_visual_kind(scene.asset_strategy)}"
        )
    lines += ["", "## Shared-unit continuity"]
    for unit in asset.units:
        if len(unit.scene_ids) > 1:
            lines.append(f"- {unit.asset_unit_id}: {' + '.join(unit.scene_ids)} OK/continuity")
    lines += ["", "## Visual repetition"]
    if not streaks:
        lines.append("- no 4+ graphics/document/map/still streaks")
    for flag in streaks:
        lines.append(f"- WARNING {flag}")
    lines += ["", "## Subtitle density"]
    lines.append(f"- warnings: {len(sub_flags)}")
    for flag in sub_flags[:40]:
        lines.append(f"- {flag}")
    lines += ["", "## Chunk join ~ scene_0039 → scene_0040"]
    lines.append(json.dumps(join, indent=2))
    _ = very_long
    return "\n".join(lines) + "\n"


def _ai_markdown(rows: list[dict], costs: dict) -> str:
    lines = [
        "# AI video decision",
        "",
        "Mechanical production-value classification. No generation. No provider lock.",
        "",
    ]
    for row in rows:
        native = "important" if row["value"] == "HIGH_VALUE" else "still/keyframe often enough"
        help_why = (
            "Action is only clear if we see physical manipulation over time."
            if row["value"] == "HIGH_VALUE"
            else "Mostly establishment or repeated industrial context."
        )
        lines += [
            f"## {row['asset_unit_id']}",
            f"- runtime: {row['runtime']}s (planned {row['planned']})",
            "- current: AI keyframe + local camera motion",
            f"- movement concept: {row['motion_concept']}",
            f"- movement_need: {row['movement_need'] or 'unspecified'}",
            f"- why motion may help: {help_why}",
            f"- native motion important: {native}",
            f"- Sora 2 720p reference: ${row['sora2_720p_usd']:.3f}",
            f"- recommendation: {row['value']}",
            "",
        ]
    lines += [
        "## Cost scenarios (reference)",
        f"- A no AI video: ${costs['scenario_a_no_ai_video_usd']}",
        f"- B HIGH_VALUE only: ${costs['scenario_b_high_value_only_usd']}",
        f"- C all 4 units: ${costs['scenario_c_all_four_usd']}",
        f"- music/SFX: {costs['music_sfx']}",
        "",
    ]
    return "\n".join(lines)
