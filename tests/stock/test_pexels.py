from __future__ import annotations

import pytest
from tests.stock.helpers import TEST_KEY, FakeTransport, settings_with_key

from docprod.config import Settings, require_pexels_api_key
from docprod.exceptions import MissingApiKeyError
from docprod.stock import PEXELS_VIDEO_SEARCH_URL
from docprod.stock.pexels import PexelsStockVideoProvider


def test_missing_key_rejected() -> None:
    settings = Settings(_env_file=None, pexels_api_key=None)
    with pytest.raises(MissingApiKeyError, match="PEXELS_API_KEY"):
        require_pexels_api_key(settings)
    with pytest.raises(MissingApiKeyError):
        PexelsStockVideoProvider(settings=settings, transport=FakeTransport()).search("train")


def test_key_not_logged_or_serialized(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = FakeTransport()
    settings = settings_with_key(monkeypatch)
    dumped = settings.model_dump_json()
    assert TEST_KEY not in dumped
    with caplog.at_level("INFO"):
        page = PexelsStockVideoProvider(settings=settings, transport=transport).search(
            "train station"
        )
    assert page.videos
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert TEST_KEY not in joined
    assert TEST_KEY not in str(page.model_dump())


def test_search_endpoint_and_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    PexelsStockVideoProvider(
        settings=settings_with_key(monkeypatch), transport=transport
    ).search("railway station")
    assert transport.calls
    url, headers = transport.calls[0]
    assert url.startswith(PEXELS_VIDEO_SEARCH_URL)
    assert "/v1/videos/search" in url
    assert not url.startswith("https://api.pexels.com/videos/")
    assert headers["Authorization"] == TEST_KEY
    assert "orientation=landscape" in url
    assert "size=medium" in url


def test_fetch_video_uses_v1_videos_id(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    video = PexelsStockVideoProvider(
        settings=settings_with_key(monkeypatch), transport=transport
    ).fetch_video("101")
    url, headers = transport.calls[0]
    assert url == "https://api.pexels.com/v1/videos/101"
    assert headers["Authorization"] == TEST_KEY
    assert video.provider_video_id == "101"
