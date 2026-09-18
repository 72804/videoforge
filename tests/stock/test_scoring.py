from __future__ import annotations

from tests.stock.helpers import stock_scene

from docprod.stock.models import StockVideoCandidate, StockVideoFile
from docprod.stock.scoring import choose_rendition, score_candidate


def _candidate(**kwargs: object) -> StockVideoCandidate:
    payload = {
        "provider": "pexels",
        "provider_video_id": "1",
        "source_page_url": "https://www.pexels.com/video/train-station-1/",
        "creator_name": "Jane",
        "duration": 12.0,
        "width": 1920,
        "height": 1080,
        "query": "train station",
        "video_files": [],
    }
    payload.update(kwargs)
    return StockVideoCandidate.model_validate(payload)


def test_duration_and_resolution_and_landscape() -> None:
    scene = stock_scene("scene_0001", "empty station", duration=4.0)
    good = score_candidate(_candidate(), scene, "train station")
    assert "landscape" in good.score_reasons
    assert "hd_or_better" in good.score_reasons
    assert "duration_ok" in good.score_reasons
    assert good.rejected is False
    short = score_candidate(_candidate(duration=2.0), scene, "train station")
    assert short.rejected is True
    assert short.reject_reason == "too_short_for_scene"
    portrait = score_candidate(
        _candidate(width=720, height=1280, duration=20.0), scene, "train station"
    )
    assert "portrait_penalty" in portrait.score_reasons
    low = score_candidate(_candidate(width=640, height=360, duration=20.0), scene, "train")
    assert "low_resolution" in low.score_reasons


def test_choose_rendition_prefers_full_hd_over_4k() -> None:
    files = [
        StockVideoFile(
            file_id=1,
            quality="uhd",
            file_type="video/mp4",
            width=3840,
            height=2160,
            link="https://example.test/4k.mp4",
        ),
        StockVideoFile(
            file_id=2,
            quality="hd",
            file_type="video/mp4",
            width=1920,
            height=1080,
            link="https://example.test/1080.mp4",
        ),
    ]
    chosen = choose_rendition(files)
    assert chosen is not None
    assert chosen.width == 1920
    assert chosen.height == 1080
    assert "1080" in chosen.link
