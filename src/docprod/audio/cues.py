from __future__ import annotations

from docprod.audio.models import AlignedToken, AlignmentReport


def chunk_alignment_cues(
    report: AlignmentReport,
    *,
    max_chars: int = 42,
    max_lines: int = 2,
    max_seconds: float = 5.5,
) -> list[tuple[float, float, str]]:
    """Phrase-level subtitle cues from aligned words. Turkish text is kept exact."""
    timed = [token for token in report.tokens if token.start is not None and token.end is not None]
    if not timed:
        return []
    cues: list[tuple[float, float, str]] = []
    bucket: list[AlignedToken] = []

    def flush() -> None:
        if not bucket:
            return
        text = " ".join(item.text for item in bucket)
        start = float(bucket[0].start or 0.0)
        end = float(bucket[-1].end or start)
        if end <= start:
            end = start + 0.04
        cues.append((start, end, text))
        bucket.clear()

    for token in timed:
        joined = " ".join(item.text for item in bucket)
        candidate = token.text if not bucket else f"{joined} {token.text}"
        duration = float(token.end or 0) - float(bucket[0].start or 0) if bucket else 0.0
        too_long = len(candidate) > max_chars * max_lines
        too_slow = duration > max_seconds
        punct = token.text.endswith((".", ",", ";", ":", "!", "?"))
        if bucket and (too_long or too_slow):
            flush()
            bucket.append(token)
            if punct:
                flush()
            continue
        bucket.append(token)
        if punct and len(" ".join(item.text for item in bucket)) >= max_chars // 2:
            flush()
    flush()
    return cues
