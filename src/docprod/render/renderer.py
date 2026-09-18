from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from docprod.models.enums import TransitionType
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.render.effects import (
    camera_motion_needed,
    effect_params,
    motion_filter,
    oversampled_size,
)
from docprod.render.ffmpeg import (
    FFmpegError,
    discover_font,
    escape_filter_path,
    ffmpeg_version_line,
    ffprobe_version_line,
    probe_media,
    require_perspective_filter,
    require_subtitles_filter,
    run_ffmpeg,
)
from docprod.render.models import (
    PreviewRenderProfile,
    RenderManifest,
    SegmentRecord,
)
from docprod.render.placeholders import placeholder_filter
from docprod.render.stats import duration_ok, frame_count_for_span, probe_looks_valid
from docprod.render.still import resolve_ai_image_still, still_fit_filter
from docprod.render.subtitles import write_captions
from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import atomic_write_text, load_model, save_model
from docprod.storage.paths import ProjectPaths

ProgressFn = Callable[[str], None]


def _ass_font_name(font: Path) -> str:
    stem = font.stem.lower()
    if "unicode" in stem:
        return "Arial Unicode MS"
    if "arial" in stem:
        return "Arial"
    if "dejavu" in stem:
        return "DejaVu Sans"
    if "liberation" in stem:
        return "Liberation Sans"
    return font.stem


def segment_input_hash(
    scene: Scene,
    *,
    project: Project,
    profile: PreviewRenderProfile,
    params_rendered: str,
    still_sha256: str | None = None,
) -> str:
    return content_hash(
        {
            "scene": scene.model_dump(mode="json"),
            "seed": project.random_seed,
            "profile": profile.model_dump(mode="json"),
            "renderer_version": profile.renderer_version,
            "effect_rendered": params_rendered,
            "still_sha256": still_sha256,
        }
    )


def render_input_hash(
    plan: ScenePlan,
    project: Project,
    profile: PreviewRenderProfile,
) -> str:
    return content_hash(
        {
            "scene_plan": plan.model_dump(mode="json"),
            "seed": project.random_seed,
            "profile": profile.model_dump(mode="json"),
            "renderer_version": profile.renderer_version,
        }
    )


def _transition_rendered(requested: TransitionType) -> tuple[TransitionType, bool]:
    if requested is TransitionType.cut:
        return TransitionType.cut, False
    return TransitionType.cut, True


def _write_concat(path: Path, segments: list[Path]) -> None:
    lines = []
    for item in segments:
        posix = item.resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{posix}'")
    atomic_write_text(path, "\n".join(lines) + "\n")


def _render_one_segment(
    scene: Scene,
    *,
    project: Project,
    profile: PreviewRenderProfile,
    paths: ProjectPaths,
    font: Path,
    use_cache: bool,
) -> SegmentRecord:
    params = effect_params(
        scene.effect,
        seed=project.random_seed,
        scene_id=scene.id,
        renderer_version=profile.renderer_version,
    )
    trans_rendered, trans_fallback = _transition_rendered(scene.transition)
    frames = frame_count_for_span(scene.start, scene.end, profile.fps)
    duration = frames / profile.fps
    still = resolve_ai_image_still(paths, scene)
    still_sha = still[1] if still else None
    input_hash = segment_input_hash(
        scene,
        project=project,
        profile=profile,
        params_rendered=params.rendered.value,
        still_sha256=still_sha,
    )
    mp4 = paths.preview_segments_dir / f"{scene.id}.mp4"
    meta_path = paths.preview_segments_dir / f"{scene.id}.meta.json"
    if use_cache and mp4.is_file() and meta_path.is_file():
        try:
            existing = load_model(meta_path, SegmentRecord)
            probe = probe_media(mp4)
            if (
                existing.input_hash == input_hash
                and existing.frame_count == frames
                and probe_looks_valid(
                    probe, width=profile.width, height=profile.height, fps=profile.fps
                )
            ):
                existing.cache_hit = True
                existing.output_sha256 = file_sha256(mp4)
                return existing
        except (OSError, FFmpegError, ValueError):
            pass

    category = str(scene.metadata.get("primary_category") or "generic")
    oversample = (
        profile.motion_oversample_factor if camera_motion_needed(params) else 1
    )
    canvas_w, canvas_h = oversampled_size(profile.width, profile.height, oversample)
    motion = motion_filter(
        params,
        duration=duration,
        width=profile.width,
        height=profile.height,
        fps=profile.fps,
        frame_count=frames,
        oversample=oversample,
    )
    tmp = mp4.with_suffix(".tmp.mp4")
    try:
        if still is None:
            base = placeholder_filter(
                strategy=scene.asset_strategy,
                scene_id=scene.id,
                category=category,
                width=canvas_w,
                height=canvas_h,
                duration=duration + 0.25,
                fps=profile.fps,
                font=font,
            )
            vf = base if motion == "null" else f"{base},{motion}"
            run_ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    vf,
                    "-frames:v",
                    str(frames),
                    "-an",
                    "-c:v",
                    profile.video_codec,
                    "-pix_fmt",
                    profile.pixel_format,
                    "-preset",
                    profile.preset,
                    "-crf",
                    str(profile.crf),
                    str(tmp),
                ],
                timeout=180,
            )
            summary = "lavfi-placeholder+perspective-cubic,libx264,no-audio"
        else:
            image_path, _digest = still
            try:
                probe = probe_media(image_path)
                src_w = probe.width or canvas_w
                src_h = probe.height or canvas_h
            except FFmpegError:
                src_w, src_h = canvas_w, canvas_h
            fit = still_fit_filter(src_w, src_h, canvas_w, canvas_h)
            vf = fit if motion == "null" else f"{fit},{motion}"
            vf = f"{vf},format={profile.pixel_format}"
            run_ffmpeg(
                [
                    "-loop",
                    "1",
                    "-framerate",
                    str(profile.fps),
                    "-i",
                    str(image_path),
                    "-frames:v",
                    str(frames),
                    "-an",
                    "-vf",
                    vf,
                    "-c:v",
                    profile.video_codec,
                    "-pix_fmt",
                    profile.pixel_format,
                    "-preset",
                    profile.preset,
                    "-crf",
                    str(profile.crf),
                    str(tmp),
                ],
                timeout=180,
            )
            summary = "still-image-cover+perspective-cubic,libx264,no-audio"
        tmp.replace(mp4)
    finally:
        tmp.unlink(missing_ok=True)
    record = SegmentRecord(
        scene_id=scene.id,
        input_hash=input_hash,
        duration=duration,
        frame_count=frames,
        strategy=scene.asset_strategy,
        effect_requested=params.requested,
        effect_rendered=params.rendered,
        fallback_used=params.fallback,
        transition_requested=scene.transition,
        transition_rendered=trans_rendered,
        transition_fallback=trans_fallback,
        cache_hit=False,
        ffmpeg_command_summary=summary,
        output_sha256=file_sha256(mp4),
    )
    save_model(meta_path, record)
    return record


@dataclass
class PreviewRenderResult:
    manifest: RenderManifest
    skipped: bool
    rendered_segments: int
    cache_hits: int


def render_preview(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    profile: PreviewRenderProfile,
    workers: int | None = None,
    use_cache: bool = True,
    progress: ProgressFn | None = None,
) -> PreviewRenderResult:
    require_perspective_filter()
    if profile.burn_subtitles:
        require_subtitles_filter()
    font = discover_font()
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    write_captions(
        plan,
        srt_path=paths.captions_srt,
        ass_path=paths.captions_ass,
        play_res_x=profile.width,
        play_res_y=profile.height,
        font_name=_ass_font_name(font),
    )
    worker_count = workers or profile.segment_workers
    records: dict[str, SegmentRecord] = {}
    lock = Lock()
    total = len(plan.scenes)

    def work(scene: Scene) -> SegmentRecord:
        return _render_one_segment(
            scene,
            project=project,
            profile=profile,
            paths=paths,
            font=font,
            use_cache=use_cache,
        )

    if worker_count == 1 or total <= 1:
        for index, scene in enumerate(plan.scenes, start=1):
            record = work(scene)
            records[scene.id] = record
            if progress:
                kind = "cache hit" if record.cache_hit else "rendered"
                progress(f"[{index}/{total}] {scene.id} {kind}")
    else:
        done = 0
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {pool.submit(work, scene): scene for scene in plan.scenes}
            for future in as_completed(futures):
                scene = futures[future]
                record = future.result()
                with lock:
                    records[scene.id] = record
                    done += 1
                    if progress:
                        kind = "cache hit" if record.cache_hit else "rendered"
                        progress(f"[{done}/{total}] {scene.id} {kind}")

    ordered = [records[scene.id] for scene in plan.scenes]
    segment_files = [paths.preview_segments_dir / f"{scene.id}.mp4" for scene in plan.scenes]
    _write_concat(paths.preview_concat, segment_files)

    concat_tmp = paths.preview_dir / ".concat_video.mp4"
    final_tmp = paths.preview_dir / ".documentary_preview.tmp.mp4"
    try:
        run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(paths.preview_concat),
                "-c",
                "copy",
                str(concat_tmp),
            ],
            timeout=180,
        )
        vf_parts = []
        if profile.burn_subtitles:
            vf_parts.append(
                f"subtitles={escape_filter_path(paths.captions_ass)}:"
                f"fontsdir={escape_filter_path(font.parent)}"
            )
        expected = sum(item.frame_count for item in ordered) / profile.fps
        args = [
            "-i",
            str(concat_tmp),
            "-f",
            "lavfi",
            "-t",
            f"{expected + 1.0:.4f}",
            "-i",
            f"anullsrc=r={profile.audio_sample_rate}:cl=stereo",
        ]
        if vf_parts:
            args.extend(["-vf", ",".join(vf_parts)])
        args.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                profile.video_codec,
                "-pix_fmt",
                profile.pixel_format,
                "-preset",
                profile.preset,
                "-crf",
                str(profile.crf),
                "-c:a",
                profile.audio_codec,
                "-b:a",
                profile.audio_bitrate,
                "-ar",
                str(profile.audio_sample_rate),
                "-ac",
                "2",
                "-t",
                f"{expected:.6f}",
                "-movflags",
                "+faststart",
                str(final_tmp),
            ]
        )
        run_ffmpeg(args, timeout=300)
        final_tmp.replace(paths.preview_mp4)
    finally:
        concat_tmp.unlink(missing_ok=True)
        final_tmp.unlink(missing_ok=True)

    probe = probe_media(paths.preview_mp4)
    expected = sum(item.frame_count for item in ordered) / profile.fps
    manifest = RenderManifest(
        renderer_version=profile.renderer_version,
        project_id=project.id,
        scene_plan_hash=content_hash(plan),
        input_hash=render_input_hash(plan, project, profile),
        render_profile=profile,
        scene_count=len(plan.scenes),
        expected_duration=expected,
        actual_duration=probe.duration,
        width=profile.width,
        height=profile.height,
        fps=profile.fps,
        subtitle_srt=str(paths.captions_srt),
        subtitle_ass=str(paths.captions_ass),
        final_output=str(paths.preview_mp4),
        ffmpeg_version=ffmpeg_version_line(),
        ffprobe_version=ffprobe_version_line(),
        font_path=str(font),
        fallback_count=sum(1 for item in ordered if item.fallback_used),
        segments=ordered,
        final_output_sha256=file_sha256(paths.preview_mp4),
    )
    save_model(paths.preview_manifest, manifest)
    if not probe.has_video or not probe.has_audio:
        raise FFmpegError("Final preview is missing video or audio stream")
    if probe.width != profile.width or probe.height != profile.height:
        raise FFmpegError(
            f"Final preview resolution {probe.width}x{probe.height} != "
            f"{profile.width}x{profile.height}"
        )
    if not duration_ok(expected, probe.duration, profile.fps):
        raise FFmpegError(
            f"Final duration {probe.duration:.3f}s differs from expected {expected:.3f}s"
        )
    cache_hits = sum(1 for item in ordered if item.cache_hit)
    return PreviewRenderResult(
        manifest=manifest,
        skipped=False,
        rendered_segments=len(ordered) - cache_hits,
        cache_hits=cache_hits,
    )


def render_debug_scene(
    paths: ProjectPaths,
    *,
    project: Project,
    plan: ScenePlan,
    scene_id: str,
    profile: PreviewRenderProfile,
) -> Path:
    scene = next((item for item in plan.scenes if item.id == scene_id), None)
    if scene is None:
        raise ValueError(f"Unknown scene id {scene_id!r}")
    paths.preview_debug_dir.mkdir(parents=True, exist_ok=True)
    font = discover_font()
    record = _render_one_segment(
        scene,
        project=project,
        profile=profile,
        paths=paths,
        font=font,
        use_cache=True,
    )
    source = paths.preview_segments_dir / f"{scene.id}.mp4"
    dest = paths.preview_debug_dir / f"{scene.id}.mp4"
    payload = source.read_bytes()
    dest.write_bytes(payload)
    smooth = paths.preview_debug_dir / f"{scene.id}_smooth.mp4"
    smooth.write_bytes(payload)
    if still_used := resolve_ai_image_still(paths, scene):
        real = paths.preview_debug_dir / f"{scene.id}_real_image.mp4"
        real.write_bytes(payload)
        _ = still_used
    _ = record
    return dest
