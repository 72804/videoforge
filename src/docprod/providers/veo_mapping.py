from __future__ import annotations

from pathlib import Path

from PIL import Image

from docprod.render.ffmpeg import probe_media, run_ffmpeg

HASH_SIZE = 16
AMBIGUOUS_MIN_SCORE = 0.58
AMBIGUOUS_MIN_MARGIN = 0.08


def _pixels(image: Image.Image) -> list[object]:
    flat = getattr(image, "get_flattened_data", None)
    if callable(flat):
        return list(flat())
    return list(image.getdata())


def extract_frame(video: Path, dest: Path, *, time_s: float = 0.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-ss",
            f"{time_s:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dest),
        ],
        timeout=30,
    )


def average_hash(path: Path, *, size: int = HASH_SIZE) -> list[int]:
    image = Image.open(path).convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pixels = _pixels(image)
    mean = sum(pixels) / max(1, len(pixels))
    return [1 if pixel >= mean else 0 for pixel in pixels]


def hash_similarity(left: list[int], right: list[int]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    same = sum(a == b for a, b in zip(left, right, strict=True))
    return same / len(left)


def mean_rgb(path: Path) -> tuple[float, float, float]:
    image = Image.open(path).convert("RGB").resize((32, 32), Image.Resampling.LANCZOS)
    pixels = _pixels(image)
    count = max(1, len(pixels))
    red = sum(pixel[0] for pixel in pixels) / count
    green = sum(pixel[1] for pixel in pixels) / count
    blue = sum(pixel[2] for pixel in pixels) / count
    return red, green, blue


def color_similarity(left: Path, right: Path) -> float:
    a = mean_rgb(left)
    b = mean_rgb(right)
    dist = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5
    return max(0.0, 1.0 - dist / (255 * (3**0.5)))


def grayscale_correlation(left: Path, right: Path, *, size: int = 32) -> float:
    a = Image.open(left).convert("L").resize((size, size), Image.Resampling.LANCZOS)
    b = Image.open(right).convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pa = _pixels(a)
    pb = _pixels(b)
    mean_a = sum(pa) / len(pa)
    mean_b = sum(pb) / len(pb)
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(pa, pb, strict=True))
    den_a = sum((x - mean_a) ** 2 for x in pa) ** 0.5
    den_b = sum((y - mean_b) ** 2 for y in pb) ** 0.5
    if den_a == 0 or den_b == 0:
        return 0.0
    return max(-1.0, min(1.0, num / (den_a * den_b)))


def similarity_matrix(
    video_frames: dict[str, Path],
    keyframes: dict[str, Path],
) -> dict[str, dict[str, float]]:
    hashes = {key: average_hash(path) for key, path in {**video_frames, **keyframes}.items()}
    matrix: dict[str, dict[str, float]] = {}
    for vid, frame in video_frames.items():
        matrix[vid] = {}
        for unit, key in keyframes.items():
            ah = hash_similarity(hashes[vid], hashes[unit])
            corr = (grayscale_correlation(frame, key) + 1.0) / 2.0
            color = color_similarity(frame, key)
            matrix[vid][unit] = round(0.35 * ah + 0.25 * corr + 0.4 * color, 4)
    return matrix


def assign_videos(
    matrix: dict[str, dict[str, float]],
) -> dict[str, str] | None:
    used_units: set[str] = set()
    assigned: dict[str, str] = {}
    for vid, scores in matrix.items():
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return None
        best_unit, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if best < AMBIGUOUS_MIN_SCORE or (best - second) < AMBIGUOUS_MIN_MARGIN:
            return None
        if best_unit in used_units:
            return None
        used_units.add(best_unit)
        assigned[vid] = best_unit
    if len(assigned) != len(matrix):
        return None
    return assigned


def write_contact_sheet(video: Path, dest: Path, *, times: tuple[float, ...] | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    probe = probe_media(video)
    duration = max(probe.duration, 0.1)
    stamps = times or tuple(round(duration * frac, 3) for frac in (0.0, 0.25, 0.5, 0.75, 0.99))
    work = dest.parent / f".{dest.stem}_frames"
    work.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    try:
        for index, stamp in enumerate(stamps):
            frame = work / f"{index:02d}.jpg"
            extract_frame(video, frame, time_s=stamp)
            frames.append(frame)
        inputs: list[str] = []
        for frame in frames:
            inputs.extend(["-i", str(frame)])
        scaled = "".join(
            f"[{i}:v]scale=256:144,setsar=1[s{i}];" for i in range(len(frames))
        )
        stack = "".join(f"[s{i}]" for i in range(len(frames))) + f"hstack=inputs={len(frames)}[v]"
        run_ffmpeg(
            [*inputs, "-filter_complex", scaled + stack, "-map", "[v]", str(dest)],
            timeout=40,
        )
    finally:
        for frame in frames:
            frame.unlink(missing_ok=True)
        if work.is_dir():
            for leftover in work.glob("*"):
                leftover.unlink(missing_ok=True)
            work.rmdir()
