from __future__ import annotations

import json
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image
from pydantic import SecretStr

from docprod.config import Settings
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import Scene, ScenePlan
from docprod.stock.pexels import HttpResponse

TEST_KEY = "unit-test-pexels-key-not-real"


def jpeg_bytes(color: tuple[int, int, int] = (40, 90, 140)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (320, 180), color).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def settings_with_key(monkeypatch: pytest.MonkeyPatch | None = None) -> Settings:
    if monkeypatch is not None:
        monkeypatch.setenv("PEXELS_API_KEY", TEST_KEY)
    return Settings(_env_file=None, pexels_api_key=SecretStr(TEST_KEY))


def stock_scene(
    scene_id: str,
    narration: str,
    *,
    duration: float = 2.0,
    category: str = "location_establishing",
) -> Scene:
    return Scene(
        id=scene_id,
        start=0.0,
        end=duration,
        duration=duration,
        narration=narration,
        visual_intent=narration,
        asset_strategy=AssetStrategy.stock_video,
        effect=VisualEffect.slow_push_in,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        metadata={"primary_category": category},
    )


def stock_plan(*scenes: Scene) -> ScenePlan:
    items = list(scenes)
    return ScenePlan(
        project_id="tiny",
        scenes=items,
        total_duration=items[-1].end if items else 0.0,
    )


def video_payload(
    video_id: int,
    *,
    duration: float = 12.0,
    width: int = 1920,
    height: int = 1080,
    slug: str = "train-station",
    extra_files: list[dict] | None = None,
) -> dict:
    files = extra_files or [
        {
            "id": video_id * 10 + 1,
            "quality": "hd",
            "file_type": "video/mp4",
            "width": 1920,
            "height": 1080,
            "fps": 25.0,
            "link": f"https://example.test/videos/{video_id}_1080.mp4",
        },
        {
            "id": video_id * 10 + 2,
            "quality": "uhd",
            "file_type": "video/mp4",
            "width": 3840,
            "height": 2160,
            "fps": 25.0,
            "link": f"https://example.test/videos/{video_id}_4k.mp4",
        },
    ]
    return {
        "id": video_id,
        "url": f"https://www.pexels.com/video/{slug}-{video_id}/",
        "image": f"https://images.pexels.com/videos/{video_id}/preview.jpg",
        "duration": duration,
        "width": width,
        "height": height,
        "user": {"name": "Jane Doe", "url": "https://www.pexels.com/@jane"},
        "video_files": files,
    }


class FakeTransport:
    def __init__(self, videos: list[dict] | None = None, mp4_bytes: bytes = b"") -> None:
        self.videos = videos or [video_payload(101), video_payload(102, slug="railway-station")]
        self.mp4_bytes = mp4_bytes
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.jpeg = jpeg_bytes()

    def get(self, url: str, headers: dict[str, str], *, timeout: int = 30) -> HttpResponse:
        self.calls.append((url, dict(headers)))
        parsed = urlparse(url)
        if "/v1/videos/search" in parsed.path:
            query = parse_qs(parsed.query).get("query", [""])[0]
            payload = {"videos": list(self.videos)}
            if "portrait-only" in query:
                payload = {
                    "videos": [
                        video_payload(201, width=720, height=1280, duration=8.0, extra_files=[
                            {
                                "id": 1,
                                "quality": "hd",
                                "file_type": "video/mp4",
                                "width": 720,
                                "height": 1280,
                                "link": "https://example.test/p.mp4",
                            }
                        ])
                    ]
                }
            return HttpResponse(
                status=200,
                body=json.dumps(payload).encode("utf-8"),
                headers={
                    "x-ratelimit-limit": "200",
                    "x-ratelimit-remaining": "199",
                    "x-ratelimit-reset": "3600",
                },
            )
        if url.endswith(".mp4"):
            return HttpResponse(status=200, body=self.mp4_bytes, headers={})
        return HttpResponse(status=200, body=self.jpeg, headers={})
