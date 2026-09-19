from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from docprod.archive.licensing import normalize_license_decision, strip_html
from docprod.archive.models import ArchiveCandidate
from docprod.exceptions import ArchiveProviderError

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "docprod/0.1 (https://github.com/local/video_generator; maple-heist research)"
_MAX_429 = 5


@dataclass
class HttpResponse:
    status: int
    body: bytes


class UrllibTransport:
    def get(self, url: str, headers: dict[str, str], *, timeout: int = 30) -> HttpResponse:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(status=getattr(response, "status", 200), body=response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp is not None else b""
            return HttpResponse(status=exc.code, body=body)
        except urllib.error.URLError as exc:
            raise ArchiveProviderError("Wikimedia request failed (network error)") from exc


def _meta(ext: dict, key: str) -> str:
    item = ext.get(key)
    if isinstance(item, dict):
        return strip_html(str(item.get("value") or ""))
    if item is None:
        return ""
    return strip_html(str(item))


def _bool_meta(ext: dict, key: str) -> bool:
    value = _meta(ext, key).casefold()
    return value in {"1", "true", "yes"}


class WikimediaCommonsProvider:
    name = "wikimedia_commons"

    def __init__(self, *, transport: UrllibTransport | None = None) -> None:
        self._transport = transport or UrllibTransport()
        self._search_cache: dict[str, list[ArchiveCandidate]] = {}

    def _get(self, params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode({**params, "format": "json"})
        url = f"{COMMONS_API}?{query}"
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        last_status = 0
        response = HttpResponse(status=0, body=b"{}")
        for attempt in range(_MAX_429):
            response = self._transport.get(url, headers)
            last_status = response.status
            if response.status != 429:
                break
            time.sleep(min(2**attempt, 16))
        if last_status >= 400:
            raise ArchiveProviderError(f"Wikimedia request failed (HTTP {last_status})")
        payload = json.loads(response.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ArchiveProviderError("Wikimedia response was not an object")
        return payload

    def search_files(self, query: str, *, limit: int = 12) -> list[ArchiveCandidate]:
        cached = self._search_cache.get(query)
        if cached is not None:
            return [item.model_copy(update={"query": query}) for item in cached]
        payload = self._get(
            {
                "action": "query",
                "list": "search",
                "srnamespace": "6",
                "srsearch": query,
                "srlimit": str(limit),
            }
        )
        rows = (((payload.get("query") or {}).get("search")) or [])
        titles: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "")
            if title and title not in titles:
                titles.append(title)
        infos = {item.title: item for item in self.files_info(titles)}
        out: list[ArchiveCandidate] = []
        for title in titles:
            info = infos.get(title)
            if info is None:
                info = ArchiveCandidate(
                    title=title,
                    query=query,
                    decision="REVIEW_REQUIRED",
                    decision_reason="metadata not loaded",
                )
            else:
                info = info.model_copy(update={"query": query})
            out.append(info)
        self._search_cache[query] = out
        return out

    def file_info(self, title: str) -> ArchiveCandidate | None:
        rows = self.files_info([title])
        return rows[0] if rows else None

    def files_info(self, titles: list[str]) -> list[ArchiveCandidate]:
        if not titles:
            return []
        payload = self._get(
            {
                "action": "query",
                "titles": "|".join(titles),
                "prop": "imageinfo",
                "iiprop": "url|size|mime|mediatype|extmetadata",
            }
        )
        pages = ((payload.get("query") or {}).get("pages")) or {}
        if not isinstance(pages, dict):
            return []
        out: list[ArchiveCandidate] = []
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            parsed = self._candidate_from_page(page)
            if parsed is not None:
                out.append(parsed)
        return out

    def _candidate_from_page(self, page: dict) -> ArchiveCandidate | None:
        title = str(page.get("title") or "")
        if not title:
            return None
        infos = page.get("imageinfo") or []
        info = infos[0] if infos and isinstance(infos[0], dict) else {}
        ext = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
        artist = _meta(ext, "Artist")
        credit = _meta(ext, "Credit")
        license_short = _meta(ext, "LicenseShortName")
        permission = _meta(ext, "Permission")
        usage = _meta(ext, "UsageTerms")
        restrictions = _meta(ext, "Restrictions")
        non_free = _bool_meta(ext, "NonFree")
        decision, reason = normalize_license_decision(
            license_short_name=license_short,
            permission=permission,
            usage_terms=usage,
            non_free=non_free,
            restrictions=restrictions,
            artist=artist,
        )
        return ArchiveCandidate(
            page_id=int(page["pageid"]) if page.get("pageid") is not None else None,
            title=title,
            description_url=str(info.get("descriptionurl") or ""),
            file_url=str(info.get("url") or ""),
            thumb_url=str(info.get("thumburl") or ""),
            mime=str(info.get("mime") or ""),
            media_type=str(info.get("mediatype") or ""),
            width=int(info.get("width") or 0),
            height=int(info.get("height") or 0),
            size_bytes=int(info.get("size") or 0),
            artist=artist,
            credit=credit,
            description=_meta(ext, "ImageDescription"),
            date_original=_meta(ext, "DateTimeOriginal"),
            license_short_name=license_short,
            license_url=_meta(ext, "LicenseUrl"),
            usage_terms=usage,
            copyrighted=_meta(ext, "Copyrighted"),
            attribution=_meta(ext, "Attribution"),
            attribution_required=_bool_meta(ext, "AttributionRequired") or bool(license_short),
            non_free=non_free,
            restrictions=restrictions,
            decision=decision,
            decision_reason=reason,
            raw_extmetadata=ext,
        )

    def fetch_bytes(self, url: str) -> bytes:
        response = self._transport.get(url, {"User-Agent": USER_AGENT})
        if response.status >= 400:
            raise ArchiveProviderError(f"Wikimedia download failed (HTTP {response.status})")
        return response.body
