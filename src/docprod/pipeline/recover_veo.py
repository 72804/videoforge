from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from docprod.audio.veo_media import extract_provider_audio, qc_sync_audio
from docprod.pipeline.produce_episode import _shot_request
from docprod.providers.google_veo import build_veo_prompt, download_generated_file, request_digest
from docprod.providers.paid_cache import PaidArtifactCache
from docprod.providers.pricing import HIGH_VALUE_VIDEO_UNITS, VEO_SECONDS_PER_REQUEST, veo_cost_usd
from docprod.providers.veo_journal import CACHE_COMMITTED, write_journal
from docprod.providers.veo_mapping import (
    assign_videos,
    extract_frame,
    similarity_matrix,
    write_contact_sheet,
)
from docprod.providers.video_capabilities import capabilities_for
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import save_json
from docprod.storage.paths import ProjectPaths

UNITS = tuple(HIGH_VALUE_VIDEO_UNITS)


def list_generated_videos(client: Any) -> list[Any]:
    found: list[Any] = []
    for file in client.files.list():
        source = str(getattr(getattr(file, "source", None), "value", None) or file.source or "")
        mime = str(getattr(file, "mime_type", "") or "")
        if source.endswith("GENERATED") and mime.startswith("video/"):
            found.append(file)
    found.sort(key=lambda item: str(getattr(item, "create_time", "")), reverse=True)
    return found


def file_metadata(file: Any) -> dict[str, str | int | None]:
    source = getattr(file, "source", None)
    return {
        "name": getattr(file, "name", None),
        "display_name": getattr(file, "display_name", None),
        "mime_type": getattr(file, "mime_type", None),
        "source": getattr(source, "value", None) or str(source),
        "create_time": str(getattr(file, "create_time", "") or ""),
        "update_time": str(getattr(file, "update_time", "") or ""),
        "expiration_time": str(getattr(file, "expiration_time", "") or ""),
        "size_bytes": getattr(file, "size_bytes", None),
        "video_metadata": str(getattr(file, "video_metadata", "") or ""),
        "has_uri": bool(getattr(file, "uri", None)),
        "has_download_uri": bool(getattr(file, "download_uri", None)),
        "state": str(getattr(file, "state", "") or ""),
    }


def _validate_recovered(path: Path) -> dict[str, object]:
    probe = probe_media(path)
    if not probe.has_video:
        raise RuntimeError(f"Recovered file is not decodable video: {path}")
    duration_ok = 6.5 <= probe.duration <= 9.5
    ratio_ok = True
    if probe.width and probe.height:
        ratio_ok = abs((probe.width / probe.height) - (16 / 9)) < 0.08
    return {
        "duration": probe.duration,
        "width": probe.width,
        "height": probe.height,
        "has_audio": probe.has_audio,
        "video_codec": probe.video_codec,
        "duration_ok": duration_ok,
        "ratio_ok": ratio_ok,
    }


def recover_generated_videos(
    paths: ProjectPaths,
    *,
    client: Any,
    cache: PaidArtifactCache,
    model: str,
    units: tuple[str, ...] = UNITS,
) -> dict[str, object]:
    files = list_generated_videos(client)
    recovery_dir = paths.artifacts_dir / "video" / "veo_recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    downloaded: dict[str, Path] = {}
    meta_rows: list[dict[str, str | int | None]] = []
    for file in files[:8]:
        info = file_metadata(file)
        meta_rows.append(info)
        name = str(info["name"] or "unknown").replace("/", "_")
        dest = recovery_dir / f"{name}.mp4"
        download_generated_file(client, file, dest)
        downloaded[str(info["name"])] = dest
    if len(downloaded) < 1:
        return {
            "recovered": 0,
            "files": meta_rows,
            "assigned": {},
            "ambiguous": True,
            "reason": "no generated videos",
        }
    keyframes = {unit: _shot_request(paths, unit).image_path for unit in units}
    frames: dict[str, Path] = {}
    for name, video in downloaded.items():
        frame = recovery_dir / f"{name.replace('/', '_')}_frame0.jpg"
        extract_frame(video, frame)
        frames[name] = frame
    matrix = similarity_matrix(frames, keyframes)
    assigned = assign_videos(matrix)
    report: dict[str, object] = {
        "files": meta_rows,
        "matrix": matrix,
        "assigned": assigned or {},
        "ambiguous": assigned is None,
        "recovered": 0,
        "units": {},
    }
    if assigned is None:
        sheets = []
        for name, video in downloaded.items():
            sheet = recovery_dir / f"{name.replace('/', '_')}_sheet.jpg"
            write_contact_sheet(video, sheet)
            sheets.append(str(sheet))
        report["contact_sheets"] = sheets
        return report
    caps = capabilities_for(model)
    committed = 0
    for resource, unit_id in assigned.items():
        video = downloaded[resource]
        checks = _validate_recovered(video)
        raw = paths.veo_raw_dir() / f"{unit_id}.mp4"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(video.read_bytes())
        wav = paths.veo_candidate_wav(unit_id)
        if checks["has_audio"]:
            extract_provider_audio(raw, wav)
            qc = qc_sync_audio(wav, speech_detector=lambda _p: False)
        else:
            qc = None
        request = _shot_request(paths, unit_id)
        prompt = build_veo_prompt(request, caps)
        digest = request_digest(request, model=model, capabilities=caps, prompt=prompt)
        payload = raw.read_bytes()
        cache.put(
            "veo",
            digest,
            payload,
            suffix=".mp4",
            meta={
                "provider": "google",
                "model": model,
                "unit_id": unit_id,
                "request_hash": digest,
                "input_keyframe_hash": file_sha256(request.image_path),
                "compiled_prompt_hash": content_hash(prompt),
                "duration": VEO_SECONDS_PER_REQUEST,
                "resolution": request.resolution,
                "aspect_ratio": request.aspect_ratio,
                "remote_generation_succeeded": True,
                "recovered_after_download_failure": True,
                "generated_file_name": resource,
                "provider_create_time": next(
                    (
                        str(row.get("create_time") or "")
                        for row in meta_rows
                        if row.get("name") == resource
                    ),
                    "",
                ),
                "native_audio_present": bool(checks["has_audio"]),
                "cost_usd": veo_cost_usd(VEO_SECONDS_PER_REQUEST),
                "status": CACHE_COMMITTED,
            },
        )
        write_journal(
            cache.root,
            digest,
            {
                "provider": "google",
                "model": model,
                "unit_id": unit_id,
                "state": CACHE_COMMITTED,
                "generated_file_name": resource,
                "remote_generated": True,
                "recovered_after_download_failure": True,
            },
        )
        ops = paths.artifacts_dir / "video" / "veo_ops" / f"{unit_id}.json"
        save_json(
            ops,
            {
                "unit_id": unit_id,
                "request_hash": digest,
                "generated_file_name": resource,
                "state": CACHE_COMMITTED,
            },
        )
        report["units"][unit_id] = {  # type: ignore[index]
            "resource": resource,
            "raw": str(raw),
            "probe": checks,
            "qc": None if qc is None else {"accepted": qc.accepted, "reasons": qc.reasons},
            "request_hash": digest,
            "score": matrix[resource][unit_id],
        }
        committed += 1
    report["recovered"] = committed
    _write_review_sheet(paths, assigned, downloaded, matrix)
    report["contact_sheet"] = str(paths.review_dir / "recovered_veo_contact_sheet.jpg")
    report["written_at"] = datetime.now(UTC).isoformat()
    save_json(paths.review_dir / "recovered_veo_mapping.json", report)
    return report


def _write_review_sheet(
    paths: ProjectPaths,
    assigned: dict[str, str],
    downloaded: dict[str, Path],
    matrix: dict[str, dict[str, float]],
) -> None:
    dest = paths.review_dir / "recovered_veo_contact_sheet.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows: list[Path] = []
    work = dest.parent / ".recovered_veo_rows"
    work.mkdir(parents=True, exist_ok=True)
    try:
        for resource, unit_id in assigned.items():
            sheet = work / f"{unit_id}.jpg"
            write_contact_sheet(downloaded[resource], sheet)
            labeled = work / f"{unit_id}_labeled.jpg"
            image = Image.open(sheet).convert("RGB")
            canvas = Image.new("RGB", (image.width, image.height + 28), (12, 12, 12))
            canvas.paste(image, (0, 28))
            draw = ImageDraw.Draw(canvas)
            score = matrix[resource][unit_id]
            draw.text(
                (8, 6),
                f"{unit_id}  {resource}  conf={score:.3f}",
                fill=(240, 240, 240),
                font=ImageFont.load_default(),
            )
            canvas.save(labeled, "JPEG", quality=90)
            rows.append(labeled)
        if len(rows) == 1:
            rows[0].replace(dest)
            return
        args: list[str] = []
        for row in rows:
            args.extend(["-i", str(row)])
        stack = "".join(f"[{i}:v]" for i in range(len(rows))) + f"vstack=inputs={len(rows)}[v]"
        run_ffmpeg([*args, "-filter_complex", stack, "-map", "[v]", str(dest)], timeout=40)
    finally:
        for path in work.glob("*"):
            path.unlink(missing_ok=True)
        if work.is_dir():
            work.rmdir()
