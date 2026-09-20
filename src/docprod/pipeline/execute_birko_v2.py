from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docprod.audio.models import AlignmentReport, RuntimeTimeline
from docprod.audio.veo_media import mute_fit_to_window
from docprod.config import Settings, get_settings
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.pipeline.migrate_character_stills import i2v_start_image_path
from docprod.pipeline.produce_custom_drama import _strip_audio_copy_or_encode, _visual_qc
from docprod.providers.google_veo import GoogleVeoProvider
from docprod.providers.pricing import (
    CUSTOM_STILL_MIGRATION_USD,
    VEO_LITE_720P_USD_PER_SEC,
    veo_cost_usd,
)
from docprod.providers.video_base import VideoShotRequest
from docprod.quality.character import character_set_for_drama
from docprod.quality.locked import (
    B07_I2V_NEGATIVE,
    BIRKO_V2_BALANCED_ROUTES,
    V2_BILLABLE_SECONDS,
    V2_EXPECTED_USD,
    V2_GEN45_BILLABLE_SECONDS,
    V2_GEN45_USD,
    V2_HARD_CAP_USD,
    V2_NEGATIVE,
    V2_PRIORITY,
    V2_PROMPTS,
    V2_VEO_BILLABLE_SECONDS,
    V2_VEO_USD,
    VEO_LITE,
    apply_runtime_durations,
)
from docprod.quality.substitution import V1_EPISODE, V2_EPISODE, upgrade_clip_path
from docprod.render.contact_sheet import build_contact_sheet
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.render.models import FinalRenderProfile
from docprod.render.mux import mux_audio_copy_video
from docprod.render.renderer import render_preview
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import load_model, save_json
from docprod.storage.paths import ProjectPaths

EXPECTED_WIDTH = 1280
EXPECTED_HEIGHT = 720
MATERIAL_PRICE_EPS = 0.005


@dataclass
class PreflightResult:
    ok: bool
    stop_reason: str = ""
    veo_seconds: float = V2_VEO_BILLABLE_SECONDS
    gen45_seconds: float = V2_GEN45_BILLABLE_SECONDS
    veo_usd: float = V2_VEO_USD
    gen45_usd: float = V2_GEN45_USD
    expected_usd: float = V2_EXPECTED_USD
    hard_cap: float = V2_HARD_CAP_USD
    lines: list[str] = field(default_factory=list)


@dataclass
class ClipOutcome:
    beat_id: str
    scene_id: str
    provider: str
    model: str
    billable_seconds: float
    visible_duration: float
    cost: float
    accepted: bool
    cached: bool
    recovered: bool
    paid_call: bool
    qc_notes: list[str] = field(default_factory=list)
    human_flags: list[str] = field(default_factory=list)
    path: str = ""
    old_visual_type: str = "still-motion"
    source_path: str = ""
    source_sha256: str = ""
    request_hash: str = ""
    operation_id: str = ""
    identities: str = ""


@dataclass
class V2ExecuteResult:
    stopped: bool
    stop_reason: str
    preflight: PreflightResult
    clips: list[ClipOutcome] = field(default_factory=list)
    v1_duration: float = 0.0
    v2_duration: float = 0.0
    v2_path: str = ""
    report_path: str = ""
    contact_sheet_path: str = ""
    veo_calls: int = 0
    veo_cache_hits: int = 0
    veo_spend: float = 0.0
    runway_calls: int = 0
    runway_cache_hits: int = 0
    runway_spend: float = 0.0
    recovered: int = 0
    failed_calls: int = 0
    narration_regenerated: bool = False
    images_regenerated: bool = False
    music_regenerated: bool = False
    audio_reused: bool = True


def preflight_v2(
    settings: Settings | None = None,
    *,
    paths: ProjectPaths | None = None,
) -> PreflightResult:
    cfg = settings or get_settings()
    veo_rate = VEO_LITE_720P_USD_PER_SEC
    veo_usd = round(V2_VEO_BILLABLE_SECONDS * veo_rate, 4)
    gen_usd = 0.0
    expected = round(veo_usd + gen_usd, 4)
    lines = [
        "COST PREFLIGHT — BIRKO V2 VEO LITE ONLY",
        f"Veo Lite: {V2_VEO_BILLABLE_SECONDS:.0f} billable seconds expected ${veo_usd:.2f}",
        "Runway Gen-4.5: off (0 seconds, $0.00)",
        "Act-Two: off",
        f"Expected video total: ${expected:.2f}",
        f"Hard video cap: ${V2_HARD_CAP_USD:.2f}",
        f"Prior custom-still spend (separate): ${CUSTOM_STILL_MIGRATION_USD}",
        f"allow_paid_apis={str(cfg.allow_paid_apis).lower()}",
        f"gemini_configured={str(cfg.gemini_key_configured()).lower()}",
        "runway_required=false",
    ]

    def fail(reason: str) -> PreflightResult:
        return PreflightResult(
            False,
            reason,
            veo_usd=veo_usd,
            gen45_usd=gen_usd,
            expected_usd=expected,
            lines=lines,
        )

    if abs(veo_rate - 0.05) > MATERIAL_PRICE_EPS:
        return fail(f"Veo pricing differs materially from locked plan (${veo_rate}/s).")
    if abs(expected - V2_EXPECTED_USD) > 0.02:
        return fail(
            f"Expected spend ${expected:.2f} differs from locked ${V2_EXPECTED_USD:.2f}."
        )
    if expected > V2_HARD_CAP_USD:
        return fail(f"Expected ${expected:.2f} exceeds hard cap ${V2_HARD_CAP_USD:.2f}.")
    if not cfg.allow_paid_apis:
        return fail("ALLOW_PAID_APIS is not true.")
    if not cfg.gemini_key_configured():
        return fail("GEMINI_API_KEY is not configured.")
    if paths is not None:
        v1 = paths.production_dir() / V1_EPISODE
        mix = paths.production_mix_wav()
        if not v1.is_file():
            return fail(f"Missing V1 episode {v1}")
        if not mix.is_file():
            return fail(f"Missing production mix {mix}")
        missing = _missing_stills(paths)
        if missing:
            return fail(f"Missing approved custom_v2 stills: {', '.join(missing)}")
        from docprod.quality.character_refs import detect_identity_mismatch

        try:
            plan = _load_runtime_plan(paths)
        except (OSError, ValueError):
            plan = None
        mismatch = detect_identity_mismatch(paths, plan)
        if mismatch:
            return fail(mismatch.message)
        if plan is not None:
            lines.append("SOURCE MAP (custom_v2 → Veo Lite)")
            for beat in V2_PRIORITY:
                scene = next(
                    (s for s in plan.scenes if (s.metadata or {}).get("beat_id") == beat),
                    None,
                )
                if scene is None:
                    return fail(f"Missing upgrade beat {beat}")
                still = paths.custom_v2_scene_image(scene.id)
                if not still.is_file():
                    return fail(f"{beat}/{scene.id} missing custom_v2 still")
                lines.append(
                    f"{beat} {scene.id} {still.relative_to(paths.root).as_posix()} "
                    f"sha256={file_sha256(still)[:16]} chars="
                    f"{','.join((scene.metadata or {}).get('characters') or [])}"
                )
    return PreflightResult(
        True,
        "",
        veo_usd=veo_usd,
        gen45_usd=gen_usd,
        expected_usd=expected,
        lines=lines,
    )


def execute_birko_v2(
    paths: ProjectPaths,
    project: Project,
    *,
    confirm_paid: bool,
    settings: Settings | None = None,
    progress: Any | None = None,
) -> V2ExecuteResult:
    cfg = settings or get_settings()
    log = progress or (lambda _msg: None)
    pre = preflight_v2(cfg, paths=paths)
    for line in pre.lines:
        log(line)
    plan = _load_runtime_plan(paths)
    report_path = paths.review_dir / "birko_v1_v2_upgrade_report.md"
    sheet_path = paths.review_dir / "birko_v2_upgrade_contact_sheet.jpg"
    v1 = paths.production_dir() / V1_EPISODE
    v1_dur = probe_media(v1).duration if v1.is_file() else 0.0
    result = V2ExecuteResult(
        stopped=not pre.ok,
        stop_reason=pre.stop_reason,
        preflight=pre,
        v1_duration=v1_dur,
        report_path=str(report_path),
        contact_sheet_path=str(sheet_path),
    )
    if not pre.ok:
        log(f"STOP={pre.stop_reason}")
        try:
            _write_contact_sheet(paths, plan, result.clips, sheet_path)
        except Exception as exc:  # noqa: BLE001
            log(f"contact_sheet_skipped={exc}")
        _write_report(paths, result, plan)
        return result
    if not confirm_paid:
        result.stopped = True
        result.stop_reason = "--confirm-paid is required for live generation."
        _write_report(paths, result, plan)
        return result

    scenes = _upgrade_scenes(plan)
    remaining = V2_HARD_CAP_USD
    for beat_id in V2_PRIORITY:
        scene = scenes[beat_id]
        model = BIRKO_V2_BALANCED_ROUTES[beat_id]
        if model != VEO_LITE:
            result.stopped = True
            result.stop_reason = f"{beat_id} is not Veo Lite; refusing non-Veo provider {model}"
            break
        billable = V2_BILLABLE_SECONDS[beat_id]
        cost = veo_cost_usd(billable)
        if cost - 1e-9 > remaining:
            result.stopped = True
            result.stop_reason = (
                f"Remaining budget ${remaining:.2f} cannot cover {beat_id} ${cost:.2f}."
            )
            break
        try:
            outcome = _generate_one(
                paths,
                scene,
                beat_id=beat_id,
                model=model,
                billable=billable,
                cost=cost,
                confirm_paid=True,
                settings=cfg,
                log=log,
            )
        except Exception as exc:  # noqa: BLE001
            result.failed_calls += 1
            message = str(exc)
            empty = "no video" in message.casefold() or "will not resubmit" in message.casefold()
            result.clips.append(
                ClipOutcome(
                    beat_id=beat_id,
                    scene_id=scene.id,
                    provider="google",
                    model=model,
                    billable_seconds=billable,
                    visible_duration=scene.duration,
                    cost=cost if empty else 0.0,
                    accepted=False,
                    cached=False,
                    recovered=False,
                    paid_call=empty,
                    qc_notes=[message],
                )
            )
            if empty:
                remaining = round(remaining - cost, 4)
                result.veo_calls += 1
                result.veo_spend = round(result.veo_spend + cost, 4)
                log(f"{beat_id} empty Veo output; not retrying; continuing")
                continue
            result.stopped = True
            result.stop_reason = f"{beat_id} failed: {exc}"
            break
        result.clips.append(outcome)
        if outcome.paid_call:
            remaining = round(remaining - outcome.cost, 4)
            result.veo_calls += 1
            result.veo_spend = round(result.veo_spend + outcome.cost, 4)
        elif outcome.recovered and not outcome.cached:
            remaining = round(remaining - outcome.cost, 4)
            result.veo_spend = round(result.veo_spend + outcome.cost, 4)
            result.recovered += 1
        elif outcome.cached:
            remaining = round(remaining - outcome.cost, 4)
            result.veo_spend = round(result.veo_spend + outcome.cost, 4)
            result.veo_cache_hits += 1
        elif outcome.recovered:
            result.recovered += 1
        if not outcome.accepted:
            log(f"{beat_id} rejected by local QC; keeping still-motion")

    accepted = {c.beat_id for c in result.clips if c.accepted}
    log(f"accepted_upgrades={sorted(accepted)}")
    if not result.stopped and accepted:
        try:
            result.v2_path, result.v2_duration = _render_v2(paths, project, plan, log=log)
            try:
                _write_shot_comparison(paths, plan, result.clips, log=log)
            except Exception as exc:  # noqa: BLE001
                log(f"comparison_skipped={exc}")
        except Exception as exc:  # noqa: BLE001
            result.stopped = True
            result.stop_reason = f"V2 render failed: {exc}"
    _write_contact_sheet(paths, plan, result.clips, sheet_path)
    _write_report(paths, result, plan)
    return result


def _load_runtime_plan(paths: ProjectPaths) -> ScenePlan:
    plan = load_model(paths.scene_plan_json, ScenePlan)
    if paths.runtime_timeline_json().is_file():
        timeline = load_model(paths.runtime_timeline_json(), RuntimeTimeline)
        plan = apply_runtime_durations(plan, timeline)
    return plan


def _upgrade_scenes(plan: ScenePlan) -> dict[str, Scene]:
    found: dict[str, Scene] = {}
    for scene in plan.scenes:
        beat = str((scene.metadata or {}).get("beat_id") or "")
        if beat in BIRKO_V2_BALANCED_ROUTES:
            found[beat] = scene
    missing = [beat for beat in V2_PRIORITY if beat not in found]
    if missing:
        raise RuntimeError(f"Scene plan missing upgrade beats: {missing}")
    return found


def _missing_stills(paths: ProjectPaths) -> list[str]:
    plan = _load_runtime_plan(paths)
    missing: list[str] = []
    for beat, scene in _upgrade_scenes(plan).items():
        try:
            still = i2v_start_image_path(paths, scene, require_custom=True)
        except RuntimeError:
            still = None
        if still is None or not still.is_file():
            missing.append(f"{beat}:{scene.id}")
    return missing


def _generate_one(
    paths: ProjectPaths,
    scene: Scene,
    *,
    beat_id: str,
    model: str,
    billable: int,
    cost: float,
    confirm_paid: bool,
    settings: Settings,
    log: Any,
) -> ClipOutcome:
    if model != VEO_LITE:
        raise RuntimeError(f"Refusing non-Veo model {model}")
    still = i2v_start_image_path(paths, scene, require_custom=True)
    source_sha = file_sha256(still)
    charset = character_set_for_drama(paths)
    ref_note = [p.character_id for p in charset.profiles if p.canonical_refs]
    from docprod.quality.character_refs import resolve_character_references

    identities: list[str] = []
    for cid in (scene.metadata or {}).get("characters") or []:
        resolved = resolve_character_references(
            paths,
            str(cid),
            provider="google",
            task="i2v",
        )
        identities.append(f"{resolved.character_id}:{resolved.identity_version}")
    prompt = V2_PROMPTS[beat_id]
    negative = B07_I2V_NEGATIVE if beat_id == "b07" else V2_NEGATIVE
    log(
        f"SOURCE {beat_id} {scene.id} still={still} sha256={source_sha} "
        f"identities={','.join(identities)}"
    )
    log(f"generate {beat_id} {model} {billable}s refs={ref_note}")
    cached = False
    recovered = False
    paid = False
    provider = GoogleVeoProvider(settings=settings)
    provider.model = VEO_LITE
    request = VideoShotRequest(
        prompt=prompt,
        negative_prompt=negative,
        image_path=still,
        duration_seconds=billable,
        asset_unit_id=scene.id,
        identity_key=",".join(identities),
    )
    shot = provider.generate_shot(request, confirm_paid=confirm_paid, use_cache=True)
    meta = shot.metadata or {}
    cached = meta.get("cache_hit") == "true"
    recovered = meta.get("download_only") == "true"
    paid = meta.get("billed_this_run") == "true"
    raw = paths.visuals_dir / "upgrades" / f".{beat_id}.raw.mp4"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(shot.video_bytes)
    source = raw
    dest = upgrade_clip_path(paths, scene.id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    mute_fit_to_window(source, dest, duration=scene.duration, generated_seconds=float(billable))
    alias = paths.visuals_dir / "upgrades" / f"{beat_id}.mp4"
    if alias.resolve() != dest.resolve():
        shutil.copy2(dest, alias)
    qc_notes, flags, ok = _qc_clip(dest, scene, still)
    qc_notes.append(f"source_still={still}")
    qc_notes.append(f"source_sha256={source_sha}")
    qc_notes.append(f"character_refs={','.join(ref_note) or 'none'}")
    qc_notes.append(f"identities={','.join(identities) or 'none'}")
    qc_notes.append(f"request_hash={meta.get('request_hash') or ''}")
    billed_cost = cost if paid or recovered or cached else 0.0
    save_json(
        dest.with_suffix(".meta.json"),
        {
            "beat_id": beat_id,
            "scene_id": scene.id,
            "provider": "google",
            "model": model,
            "billable_seconds": billable,
            "visible_duration": scene.duration,
            "source_path": str(still),
            "source_sha256": source_sha,
            "identities": identities,
            "request_hash": meta.get("request_hash") or "",
            "operation_id": meta.get("operation_name") or "",
            "cost_usd": billed_cost,
            "cache_hit": cached,
            "recovered": recovered,
            "paid_call": paid,
        },
    )
    return ClipOutcome(
        beat_id=beat_id,
        scene_id=scene.id,
        provider="google",
        model=model,
        billable_seconds=billable,
        visible_duration=scene.duration,
        cost=billed_cost,
        accepted=ok,
        cached=cached,
        recovered=recovered,
        paid_call=paid,
        qc_notes=qc_notes,
        human_flags=flags,
        path=str(dest),
        source_path=str(still),
        source_sha256=source_sha,
        request_hash=str(meta.get("request_hash") or ""),
        operation_id=str(meta.get("operation_name") or ""),
        identities=",".join(identities),
    )


def _qc_clip(clip: Path, scene: Scene, still: Path) -> tuple[list[str], list[str], bool]:
    notes: list[str] = []
    flags: list[str] = [
        "human_review: possible face drift",
        "human_review: unexpected extra person / wrong character count",
        "human_review: extreme hand deformation",
        "human_review: scene/location mismatch",
    ]
    if not clip.is_file() or clip.stat().st_size == 0:
        return ["missing_or_zero_byte"], flags, False
    probe = probe_media(clip)
    notes.append(f"duration={probe.duration:.3f}")
    notes.append(f"size={probe.width}x{probe.height}")
    notes.append(f"codec={probe.video_codec}")
    if probe.has_audio:
        notes.append("provider_audio_present")
        return notes, flags, False
    if (probe.width, probe.height) != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        notes.append("resolution_mismatch")
        return notes, flags, False
    if probe.duration + 0.12 < scene.duration:
        notes.append("too_short_after_fit")
        return notes, flags, False
    thumbs = clip.parent / f".qc_{scene.id}"
    thumbs.mkdir(parents=True, exist_ok=True)
    hashes: list[str] = []
    times = (0.05, max(0.1, probe.duration / 2), max(0.1, probe.duration - 0.08))
    for index, stamp in enumerate(times):
        frame = thumbs / f"frame_{index}.jpg"
        run_ffmpeg(
            [
                "-ss",
                f"{stamp:.3f}",
                "-i",
                str(clip),
                "-frames:v",
                "1",
                "-q:v",
                "4",
                str(frame),
            ],
            timeout=30,
        )
        if not frame.is_file() or frame.stat().st_size < 400:
            notes.append(f"blank_frame_{index}")
            return notes, flags, False
        hashes.append(file_sha256(frame))
    if len(set(hashes)) == 1:
        notes.append("frozen_entire_clip")
        return notes, flags, False
    still_hash = file_sha256(still) if still.is_file() else ""
    if still_hash and file_sha256(clip) == still_hash:
        notes.append("duplicate_of_source_still_hash")
        return notes, flags, False
    notes.append("technical_qc_ok")
    return notes, flags, True


def _render_v2(
    paths: ProjectPaths,
    project: Project,
    plan: ScenePlan,
    *,
    log: Any,
) -> tuple[str, float]:
    alignment = None
    if paths.narration_alignment_json().is_file():
        alignment = load_model(paths.narration_alignment_json(), AlignmentReport)
    profile = FinalRenderProfile(motion_oversample_factor=2, burn_subtitles=True, preset="medium")
    visual_preview = paths.production_dir() / "visual_master_drama_v2_preview.mp4"
    log("render V2 visual master (upgrade clips + reused still-motion)")
    render_preview(
        paths,
        project=project,
        plan=plan,
        profile=profile,
        use_cache=True,
        allow_placeholders=False,
        alignment=alignment,
        write_caption_files=False,
        captions_srt=paths.captions_srt,
        captions_ass=paths.captions_ass,
        output_mp4=visual_preview,
        progress=log,
    )
    visual_master = paths.production_dir() / "visual_master_drama_v2.mp4"
    _strip_audio_copy_or_encode(visual_preview, visual_master)
    dest = paths.production_dir() / V2_EPISODE
    if dest.resolve() == (paths.production_dir() / V1_EPISODE).resolve():
        raise RuntimeError("Refusing to overwrite V1")
    mux_audio_copy_video(visual_master, paths.production_mix_wav(), dest)
    probe = probe_media(dest)
    timeline = load_model(paths.runtime_timeline_json(), RuntimeTimeline)
    qc = _visual_qc(paths, plan, timeline, dest)
    if qc["title_cards"] != 3:
        raise RuntimeError(f"Expected 3 title cards, got {qc['title_cards']}")
    if qc["duplicate_timeline"] != 0:
        raise RuntimeError(f"Duplicate timeline visuals: {qc['duplicate_timeline']}")
    if not probe.has_audio or not probe.has_video:
        raise RuntimeError("V2 missing audio or video")
    log(f"v2_written={dest} duration={probe.duration:.3f}")
    return str(dest), float(probe.duration)


def _write_shot_comparison(
    paths: ProjectPaths,
    plan: ScenePlan,
    clips: list[ClipOutcome],
    *,
    log: Any,
) -> Path | None:
    v1 = paths.production_dir() / V1_EPISODE
    v2 = paths.production_dir() / V2_EPISODE
    dest = paths.review_dir / "birko_v1_v2_shot_comparison.mp4"
    if not v1.is_file() or not v2.is_file():
        log("comparison skipped: missing V1 or V2 episode")
        return None
    work = paths.review_dir / ".v1v2_compare"
    work.mkdir(parents=True, exist_ok=True)
    pairs: list[Path] = []
    by_id = {scene.id: scene for scene in plan.scenes}
    for clip in clips:
        if not clip.accepted or clip.beat_id not in V2_PRIORITY:
            continue
        scene = by_id.get(clip.scene_id)
        if scene is None:
            continue
        left = work / f"{clip.beat_id}_v1.mp4"
        right = work / f"{clip.beat_id}_v2.mp4"
        stacked = work / f"{clip.beat_id}_pair.mp4"
        window = min(float(scene.duration), 8.0)
        for source, out in ((v1, left), (v2, right)):
            run_ffmpeg(
                [
                    "-y",
                    "-ss",
                    f"{scene.start:.3f}",
                    "-i",
                    str(source),
                    "-t",
                    f"{window:.3f}",
                    "-an",
                    "-vf",
                    "scale=640:360:force_original_aspect_ratio=decrease,"
                    "pad=640:360:(ow-iw)/2:(oh-ih)/2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(out),
                ],
                timeout=120,
            )
        run_ffmpeg(
            [
                "-y",
                "-i",
                str(left),
                "-i",
                str(right),
                "-filter_complex",
                "hstack=inputs=2",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(stacked),
            ],
            timeout=120,
        )
        pairs.append(stacked)
    if not pairs:
        return None
    concat = work / "concat.txt"
    concat.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in pairs),
        encoding="utf-8",
    )
    run_ffmpeg(
        ["-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(dest)],
        timeout=120,
    )
    log(f"comparison={dest}")
    return dest


def _write_contact_sheet(
    paths: ProjectPaths,
    plan: ScenePlan,
    clips: list[ClipOutcome],
    dest: Path,
) -> None:
    entries: list[tuple[str, str, Path]] = []
    by_beat = {c.beat_id: c for c in clips}
    for beat in V2_PRIORITY:
        scene = next(s for s in plan.scenes if (s.metadata or {}).get("beat_id") == beat)
        still = i2v_start_image_path(paths, scene, require_custom=True)
        entries.append((beat, "start-still", still))
        outcome = by_beat.get(beat)
        if outcome and outcome.path:
            frame = Path(outcome.path).parent / f".qc_{scene.id}" / "frame_1.jpg"
            if frame.is_file():
                entries.append((beat, "v2-mid", frame))
    dest.parent.mkdir(parents=True, exist_ok=True)
    if any(path.is_file() for _, _, path in entries):
        build_contact_sheet(paths, entries, columns=4, output=dest)


def _write_report(paths: ProjectPaths, result: V2ExecuteResult, plan: ScenePlan) -> None:
    paths.review_dir.mkdir(parents=True, exist_ok=True)
    accepted = [c.beat_id for c in result.clips if c.accepted]
    rejected = [c.beat_id for c in result.clips if not c.accepted]
    lines = [
        "# Birko V1 vs V2 upgrade report",
        "",
        f"Stopped: {str(result.stopped).lower()}",
        f"Stop reason: {result.stop_reason or 'none'}",
        "",
        "## Preflight",
        "",
        *[f"- {line}" for line in result.preflight.lines],
        "",
        "## Spend (this upgrade only; excludes V1 episode spend)",
        "",
        f"- Veo successful calls: {result.veo_calls}",
        f"- Veo cache hits: {result.veo_cache_hits}",
        f"- Veo spend: ${result.veo_spend:.2f}",
        f"- Runway calls: {result.runway_calls} (must be 0)",
        f"- Runway spend: ${result.runway_spend:.2f}",
        f"- Custom-still migration (prior, separate): ${CUSTOM_STILL_MIGRATION_USD}",
        f"- Total new V2 transformation: "
        f"${round(CUSTOM_STILL_MIGRATION_USD + result.veo_spend + result.runway_spend, 6)}",
        f"- Recovered remote generations: {result.recovered}",
        f"- Failed calls: {result.failed_calls}",
        "",
        "## Beats",
        "",
    ]
    by_beat = {c.beat_id: c for c in result.clips}
    for beat in V2_PRIORITY:
        scene = next((s for s in plan.scenes if (s.metadata or {}).get("beat_id") == beat), None)
        clip = by_beat.get(beat)
        lines.append(f"### {beat}")
        if scene is None:
            lines.append("- missing from scene plan")
            lines.append("")
            continue
        if clip is None:
            lines.append(f"- scene id: {scene.id}")
            lines.append("- old visual type: still-motion")
            lines.append(f"- new provider/model: {BIRKO_V2_BALANCED_ROUTES[beat]}")
            lines.append(f"- billable duration: {V2_BILLABLE_SECONDS[beat]}s")
            lines.append(f"- visible duration: {scene.duration:.2f}s")
            lines.append("- cost: $0.00 (not generated)")
            lines.append("- accepted into final V2: no")
            lines.append(f"- QC notes: {result.stop_reason or 'not generated'}")
            lines.append("")
            continue
        lines.extend(
            [
                f"- scene id: {clip.scene_id}",
                f"- old visual type: {clip.old_visual_type}",
                f"- new provider/model: {clip.provider}/{clip.model}",
                f"- billable duration: {clip.billable_seconds:.0f}s",
                f"- visible duration: {clip.visible_duration:.2f}s",
                f"- source still: {clip.source_path}",
                f"- source sha256: {clip.source_sha256}",
                f"- identities: {clip.identities or 'none'}",
                f"- request hash: {clip.request_hash}",
                f"- operation id: {clip.operation_id or 'n/a'}",
                f"- cost: ${clip.cost:.2f}",
                f"- accepted into final V2: {str(clip.accepted).lower()}",
                f"- cached: {str(clip.cached).lower()} recovered: {str(clip.recovered).lower()}",
                f"- QC notes: {'; '.join(clip.qc_notes)}",
                f"- human-review flags: {'; '.join(clip.human_flags)}",
                "",
            ]
        )
    lines.extend(
        [
            "## Final",
            "",
            f"- accepted upgraded scenes: {', '.join(accepted) or 'none'}",
            f"- rejected upgraded scenes: {', '.join(rejected) or 'none'}",
            f"- V1 duration: {result.v1_duration:.3f}s",
            f"- V2 duration: {result.v2_duration:.3f}s",
            f"- audio reused: {str(result.audio_reused).lower()}",
            f"- narration regenerated: {str(result.narration_regenerated).lower()}",
            f"- images regenerated: {str(result.images_regenerated).lower()}",
            f"- music regenerated: {str(result.music_regenerated).lower()}",
            f"- final V2 path: {result.v2_path or 'not written'}",
            f"- contact sheet: {result.contact_sheet_path}",
            "",
        ]
    )
    report = paths.review_dir / "birko_v1_v2_upgrade_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    save_json(
        paths.review_dir / "birko_v1_v2_upgrade_report.json",
        {
            "stopped": result.stopped,
            "stop_reason": result.stop_reason,
            "expected_usd": result.preflight.expected_usd,
            "actual_new_spend": round(result.veo_spend + result.runway_spend, 4),
            "veo_calls": result.veo_calls,
            "runway_calls": result.runway_calls,
            "veo_cache_hits": result.veo_cache_hits,
            "runway_cache_hits": result.runway_cache_hits,
            "recovered": result.recovered,
            "failed_calls": result.failed_calls,
            "accepted": accepted,
            "rejected": rejected,
            "v1_duration": result.v1_duration,
            "v2_duration": result.v2_duration,
            "v2_path": result.v2_path,
        },
    )


def sync_notes(paths: ProjectPaths) -> list[str]:
    notes: list[str] = []
    if not paths.narration_alignment_json().is_file():
        return ["alignment.json missing"]
    alignment = load_model(paths.narration_alignment_json(), AlignmentReport)
    plan = _load_runtime_plan(paths)
    scenes = _upgrade_scenes(plan)
    b07 = scenes["b07"]
    b17 = scenes["b17"]
    b18 = scenes["b18"]
    for word in alignment.tokens:
        if word.start is None:
            continue
        text = (word.text or "").casefold()
        if "kemal" in text or "yaz" in text:
            if b07.start - 0.05 <= word.start <= b07.end + 0.05:
                notes.append(f"b07 Cedar word {word.text!r} at {word.start:.3f}s inside shot")
    notes.append(f"b17 window {b17.start:.3f}-{b17.end:.3f}s for ledger-close SFX coincidence")
    notes.append(f"b18 window {b18.start:.3f}-{b18.end:.3f}s for pocket motion")
    return notes
