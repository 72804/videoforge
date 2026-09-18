from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from docprod.config import Settings, get_settings, require_pexels_api_key
from docprod.exceptions import StockProviderError
from docprod.logging_utils import get_logger
from docprod.stock import PEXELS_VIDEO_SEARCH_URL
from docprod.stock.models import StockSearchPage, StockVideoCandidate, StockVideoFile

_LOG = get_logger("stock.pexels")


@dataclass
class HttpResponse:
    status: int
    body: bytes
    headers: dict[str, str]


class UrllibTransport:
    def get(self, url: str, headers: dict[str, str], *, timeout: int = 30) -> HttpResponse:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status=getattr(response, "status", 200),
                    body=response.read(),
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp is not None else b""
            return HttpResponse(
                status=exc.code,
                body=body,
                headers={
                    key.lower(): value
                    for key, value in (exc.headers.items() if exc.headers else [])
                },
            )
        except urllib.error.URLError as exc:
            raise StockProviderError("Pexels request failed (network error)") from exc


def _safe_error(status: int) -> str:
    if status in {401, 403}:
        return "Pexels authentication failed (details omitted)"
    return f"Pexels request failed (HTTP {status})"


def _parse_video(item: dict, query: str) -> StockVideoCandidate | None:
    video_id = item.get("id")
    if video_id is None:
        return None
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    files: list[StockVideoFile] = []
    for raw in item.get("video_files") or []:
        if not isinstance(raw, dict):
            continue
        width = int(raw.get("width") or 0)
        height = int(raw.get("height") or 0)
        link = str(raw.get("link") or "")
        if width < 2 or height < 2 or not link:
            continue
        fps = raw.get("fps")
        files.append(
            StockVideoFile(
                file_id=int(raw["id"]) if raw.get("id") is not None else None,
                quality=str(raw.get("quality") or "") or None,
                file_type=str(raw.get("file_type") or "") or None,
                width=width,
                height=height,
                link=link,
                fps=float(fps) if fps not in (None, "") else None,
            )
        )
    return StockVideoCandidate(
        provider="pexels",
        provider_video_id=str(video_id),
        source_page_url=str(item.get("url") or ""),
        creator_name=str(user.get("name") or "Unknown"),
        creator_url=str(user.get("url")) if user.get("url") else None,
        duration=float(item.get("duration") or 0.0),
        width=int(item.get("width") or 0),
        height=int(item.get("height") or 0),
        preview_image_url=str(item.get("image") or "") or None,
        query=query,
        video_files=files,
        extra={"title": str(item.get("url") or "")},
        fps=next((file.fps for file in files if file.fps), None),
    )


class PexelsStockVideoProvider:
    name = "pexels"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: UrllibTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport or UrllibTransport()
        self.last_ratelimit: dict[str, str | None] = {
            "limit": None,
            "remaining": None,
            "reset": None,
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": require_pexels_api_key(self._settings),
            "User-Agent": "docprod/0.1",
            "Accept": "application/json",
        }

    def search(
        self,
        query: str,
        *,
        orientation: str = "landscape",
        size: str = "medium",
        per_page: int = 20,
        locale: str = "en-US",
        page: int = 1,
    ) -> StockSearchPage:
        params = urllib.parse.urlencode(
            {
                "query": query,
                "orientation": orientation,
                "size": size,
                "per_page": str(per_page),
                "locale": locale,
                "page": str(page),
            }
        )
        url = f"{PEXELS_VIDEO_SEARCH_URL}?{params}"
        _LOG.info("Pexels search query=%r", query)
        response = self._transport.get(url, self._headers())
        self.last_ratelimit = {
            "limit": response.headers.get("x-ratelimit-limit"),
            "remaining": response.headers.get("x-ratelimit-remaining"),
            "reset": response.headers.get("x-ratelimit-reset"),
        }
        _LOG.info(
            "Pexels ratelimit limit=%s remaining=%s reset=%s",
            self.last_ratelimit["limit"],
            self.last_ratelimit["remaining"],
            self.last_ratelimit["reset"],
        )
        if response.status >= 400:
            raise StockProviderError(_safe_error(response.status))
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StockProviderError("Pexels returned invalid JSON") from exc
        videos: list[StockVideoCandidate] = []
        for item in payload.get("videos") or []:
            if not isinstance(item, dict):
                continue
            parsed = _parse_video(item, query)
            if parsed is not None:
                videos.append(parsed)
        return StockSearchPage(
            query=query,
            videos=videos,
            ratelimit_limit=self.last_ratelimit["limit"],
            ratelimit_remaining=self.last_ratelimit["remaining"],
            ratelimit_reset=self.last_ratelimit["reset"],
        )

    def fetch_bytes(self, url: str) -> bytes:
        headers = {"User-Agent": "docprod/0.1", "Accept": "*/*"}
        if "api.pexels.com" in url.lower():
            headers = self._headers()
        response = self._transport.get(url, headers)
        if response.status >= 400:
            raise StockProviderError(_safe_error(response.status))
        return response.body
