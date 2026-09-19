from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from docprod.exceptions import ZeroPlaceholderError
from docprod.models.enums import AssetStrategy, TransitionType, VisualEffect
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
from docprod.render.still import (
    resolve_scene_still,
    resolve_scene_visual,
    still_fit_filter,
    still_pixel_normalize_filter,
)
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
            "still_pix_fmt": "yuv420p",
            "unit_progress_start": scene.metadata.get("unit_progress_start"),
            "unit_progress_end": scene.metadata.get("unit_progress_end"),
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
    allow_placeholders: bool = True,
) -> SegmentRecord:
    trans_rendered, trans_fallback = _transition_rendered(scene.transition)
    frames = frame_count_for_span(scene.start, scene.end, profile.fps)
    duration = frames / profile.fps
    visual = resolve_scene_visual(paths, scene)
    effect = scene.effect
    effect_override_reason = None
    if visual is not None and visual.kind in {"stock_video", "ai_video"}:
        effect = VisualEffect.none
        effect_override_reason = "native_video_motion"
    params = effect_params(
        effect,
        seed=project.random_seed,
        scene_id=scene.id,
        renderer_version=profile.renderer_version,
    )
    still_sha = visual.sha256 if visual else None
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
    progress_start = float(scene.metadata.get("unit_progress_start") or 0.0)
    progress_end = float(scene.metadata.get("unit_progress_end") or 1.0)
    motion = motion_filter(
        params,
        duration=duration,
        width=profile.width,
        height=profile.height,
        fps=profile.fps,
        frame_count=frames,
        oversample=oversample,
        progress_start=progress_start,
        progress_end=progress_end,
    )
    if visual is None:
        if not allow_placeholders:
            raise ZeroPlaceholderError(f"No visual resolved for {scene.id}")
        source_asset = "placeholder"
        strategy_rendered = (
            "placeholder"
            if scene.asset_strategy
            in {
                AssetStrategy.ai_image,
                AssetStrategy.ai_image_to_video,
            }
            else scene.asset_strategy.value
        )
    else:
        source_asset = visual.kind
        strategy_rendered = visual.strategy_rendered
    tmp = mp4.with_suffix(".tmp.mp4")
    try:
        if visual is None:
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
            map_layers = (
                visual.kind == "local_map"
                and scene.effect is VisualEffect.map_route
                and visual.map_bg is not None
                and visual.map_route is not None
                and visual.map_mask is not None
                and visual.map_ring is not None
                and visual.dest is not None
                and visual.map_bg.is_file()
                and visual.map_route.is_file()
                and visual.map_mask.is_file()
                and visual.map_ring.is_file()
            )
            if visual.kind in {"stock_video", "ai_video"}:
                try:
                    probe = probe_media(visual.path)
                    src_w = probe.width or canvas_w
                    src_h = probe.height or canvas_h
                except FFmpegError:
                    src_w, src_h = canvas_w, canvas_h
                fit = still_fit_filter(src_w, src_h, canvas_w, canvas_h)
                vf = f"{fit},fps={profile.fps},format=yuv420p"
                run_ffmpeg(
                    [
                        "-i",
                        str(visual.path),
                        "-t",
                        f"{duration:.4f}",
                        "-frames:v",
                        str(frames),
                        "-an",
                        "-vf",
                        vf,
                        "-c:v",
                        profile.video_codec,
                        "-pix_fmt",
                        "yuv420p",
                        "-preset",
                        profile.preset,
                        "-crf",
                        str(profile.crf),
                        str(tmp),
                    ],
                    timeout=180,
                )
                summary = "stock-video-cover,libx264,yuv420p,no-audio"
            elif map_layers:
                from PIL import Image

                from docprod.graphics.map import composite_map_frame
                from docprod.render.effects import motion_progress

                try:
                    probe = probe_media(visual.map_bg)
                    src_w = probe.width or canvas_w
                    src_h = probe.height or canvas_h
                except FFmpegError:
                    src_w, src_h = canvas_w, canvas_h
                fit = still_fit_filter(src_w, src_h, canvas_w, canvas_h)
                motion_part = "" if motion == "null" else f",{motion}"
                frame_dir = paths.preview_segments_dir / f".{scene.id}_mapframes"
                frame_dir.mkdir(parents=True, exist_ok=True)
                try:
                    background = Image.open(visual.map_bg)
                    overlay = Image.open(visual.map_route)
                    mask = Image.open(visual.map_mask)
                    for index in range(frames):
                        progress = motion_progress(index, frames)
                        progress = progress_start + (progress_end - progress_start) * progress
                        frame = composite_map_frame(
                            background, overlay, mask, progress=progress
                        )
                        frame.save(frame_dir / f"frame_{index:04d}.png")
                    vf = f"{fit}{motion_part},{still_pixel_normalize_filter()}"
                    run_ffmpeg(
                        [
                            "-framerate",
                            str(profile.fps),
                            "-i",
                            str(frame_dir / "frame_%04d.png"),
                            "-frames:v",
                            str(frames),
                            "-an",
                            "-vf",
                            vf,
                            "-c:v",
                            profile.video_codec,
                            "-pix_fmt",
                            "yuv420p",
                            "-preset",
                            profile.preset,
                            "-crf",
                            str(profile.crf),
                            str(tmp),
                        ],
                        timeout=180,
                    )
                finally:
                    import shutil

                    shutil.rmtree(frame_dir, ignore_errors=True)
                summary = "map-route-frames+perspective-cubic,libx264,yuv420p,no-audio"
            elif visual.sequence and str(scene.metadata.get("photo_sequence_split") or "") == "1":
                parts: list[Path] = []
                n = max(1, len(visual.sequence))
                remaining_frames = frames
                for idx, still_path in enumerate(visual.sequence):
                    chunk_frames = remaining_frames // (n - idx)
                    remaining_frames -= chunk_frames
                    if chunk_frames < 1:
                        continue
                    part = tmp.with_name(f"{scene.id}_seq{idx}.mp4")
                    try:
                        probe = probe_media(still_path)
                        src_w = probe.width or canvas_w
                        src_h = probe.height or canvas_h
                    except FFmpegError:
                        src_w, src_h = canvas_w, canvas_h
                    fit = still_fit_filter(src_w, src_h, canvas_w, canvas_h)
                    vf = fit if motion == "null" else f"{fit},{motion}"
                    vf = f"{vf},{still_pixel_normalize_filter()}"
                    run_ffmpeg(
                        [
                            "-loop",
                            "1",
                            "-framerate",
                            str(profile.fps),
                            "-i",
                            str(still_path),
                            "-frames:v",
                            str(chunk_frames),
                            "-an",
                            "-vf",
                            vf,
                            "-c:v",
                            profile.video_codec,
                            "-pix_fmt",
                            "yuv420p",
                            "-preset",
                            profile.preset,
                            "-crf",
                            str(profile.crf),
                            str(part),
                        ],
                        timeout=180,
                    )
                    parts.append(part)
                concat_list = tmp.with_name(f"{scene.id}_seq.txt")
                concat_list.write_text(
                    "".join(f"file '{item.resolve().as_posix()}'\n" for item in parts),
                    encoding="utf-8",
                )
                run_ffmpeg(
                    [
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        str(concat_list),
                        "-c",
                        "copy",
                        str(tmp),
                    ],
                    timeout=180,
                )
                for item in parts:
                    item.unlink(missing_ok=True)
                concat_list.unlink(missing_ok=True)
                summary = "photo-sequence-stills,libx264,yuv420p,no-audio"
            else:
                image_path = visual.path
                try:
                    probe = probe_media(image_path)
                    src_w = probe.width or canvas_w
                    src_h = probe.height or canvas_h
                except FFmpegError:
                    src_w, src_h = canvas_w, canvas_h
                fit = still_fit_filter(src_w, src_h, canvas_w, canvas_h)
                vf = fit if motion == "null" else f"{fit},{motion}"
                vf = f"{vf},{still_pixel_normalize_filter()}"
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
                        "yuv420p",
                        "-color_range",
                        "tv",
                        "-colorspace",
                        "bt709",
                        "-color_primaries",
                        "bt709",
                        "-color_trc",
                        "bt709",
                        "-preset",
                        profile.preset,
                        "-crf",
                        str(profile.crf),
                        str(tmp),
                    ],
                    timeout=180,
                )
                summary = "still-image-cover+perspective-cubic,libx264,yuv420p,no-audio"
        tmp.replace(mp4)
    finally:
        tmp.unlink(missing_ok=True)
    record = SegmentRecord(
        scene_id=scene.id,
        input_hash=input_hash,
        duration=duration,
        frame_count=frames,
        strategy=scene.asset_strategy,
        effect_requested=scene.effect,
        effect_rendered=params.rendered,
        fallback_used=params.fallback,
        transition_requested=scene.transition,
        transition_rendered=trans_rendered,
        transition_fallback=trans_fallback,
        cache_hit=False,
        ffmpeg_command_summary=summary,
        output_sha256=file_sha256(mp4),
        source_asset=source_asset,
        strategy_requested=scene.asset_strategy,
        strategy_rendered=strategy_rendered,
        effect_override_reason=effect_override_reason,
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
    output_mp4: Path | None = None,
    manifest_path: Path | None = None,
    captions_srt: Path | None = None,
    captions_ass: Path | None = None,
    narration_wav: Path | None = None,
    allow_placeholders: bool = True,
    alignment=None,
    write_caption_files: bool = True,
) -> PreviewRenderResult:
    require_perspective_filter()
    if profile.burn_subtitles:
        require_subtitles_filter()
    font = discover_font()
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    srt_path = captions_srt or paths.captions_srt
    ass_path = captions_ass or paths.captions_ass
    if write_caption_files:
        write_captions(
            plan,
            srt_path=srt_path,
            ass_path=ass_path,
            play_res_x=profile.width,
            play_res_y=profile.height,
            font_name=_ass_font_name(font),
            alignment=alignment,
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
            allow_placeholders=allow_placeholders,
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
            timeout=600,
        )
        vf_parts = []
        if profile.burn_subtitles:
            vf_parts.append(
                f"subtitles={escape_filter_path(ass_path)}:"
                f"fontsdir={escape_filter_path(font.parent)}"
            )
        expected = sum(item.frame_count for item in ordered) / profile.fps
        args = [
            "-i",
            str(concat_tmp),
        ]
        if narration_wav is not None:
            args.extend(["-i", str(narration_wav)])
        else:
            args.extend(
                [
                    "-f",
                    "lavfi",
                    "-t",
                    f"{expected + 1.0:.4f}",
                    "-i",
                    f"anullsrc=r={profile.audio_sample_rate}:cl=stereo",
                ]
            )
        if vf_parts:
            args.extend(["-vf", ",".join(vf_parts)])
        encode = [
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
        ]
        if narration_wav is not None:
            encode.extend(
                [
                    "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11,aformat=channel_layouts=stereo",
                ]
            )
        encode.extend(
            [
                "-t",
                f"{expected:.6f}",
                "-movflags",
                "+faststart",
                str(final_tmp),
            ]
        )
        args.extend(encode)
        run_ffmpeg(args, timeout=1800)
        dest = output_mp4 or paths.preview_mp4
        dest.parent.mkdir(parents=True, exist_ok=True)
        final_tmp.replace(dest)
    finally:
        concat_tmp.unlink(missing_ok=True)
        final_tmp.unlink(missing_ok=True)

    dest = output_mp4 or paths.preview_mp4
    probe = probe_media(dest)
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
        subtitle_srt=str(srt_path),
        subtitle_ass=str(ass_path),
        final_output=str(dest),
        ffmpeg_version=ffmpeg_version_line(),
        ffprobe_version=ffprobe_version_line(),
        font_path=str(font),
        fallback_count=sum(1 for item in ordered if item.fallback_used),
        segments=ordered,
        final_output_sha256=file_sha256(dest),
    )
    save_model(manifest_path or paths.preview_manifest, manifest)
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
    if still_used := resolve_scene_still(paths, scene):
        real = paths.preview_debug_dir / f"{scene.id}_real_image.mp4"
        real.write_bytes(payload)
        _ = still_used
    _ = record
    return dest
