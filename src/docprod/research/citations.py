from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from docprod.research.models import SourceRecord, SourceRegistry
from docprod.research.source_quality import canonical_url, classify_source_quality, extract_domain

_SOURCE_REF_RE = re.compile(r"\[S(\d{3,})\]")
_OPAQUE_CITE_RE = re.compile(r"(?:cite[^]*)|(?:【[^】]*】)|(?:\[\d+:\d+†[^\]]+\])")


def next_source_id(index: int) -> str:
    return f"S{index:03d}"


def collect_raw_sources(
    *,
    annotations: list[dict[str, Any]],
    web_search_sources: list[dict[str, Any]],
    extra_urls: list[str] | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    blobs: list[dict[str, Any]] = []
    blobs.extend(annotations)
    blobs.extend(web_search_sources)
    for url in extra_urls or []:
        blobs.append({"url": url})
    for item in blobs:
        url = str(item.get("url") or item.get("uri") or "").strip()
        if not url:
            continue
        key = canonical_url(url)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "url": url,
                "title": str(item.get("title") or ""),
                "canonical_url": key,
            }
        )
    return rows


def build_source_registry(
    project_id: str,
    raw_sources: list[dict[str, str]],
    *,
    accessed_at: datetime | None = None,
) -> SourceRegistry:
    now = accessed_at or datetime.now(UTC)
    records: list[SourceRecord] = []
    for index, item in enumerate(raw_sources, start=1):
        url = item["url"]
        title = item.get("title") or ""
        tier, reason = classify_source_quality(url, title=title)
        domain = extract_domain(url)
        records.append(
            SourceRecord(
                source_id=next_source_id(index),
                url=url,
                title=title,
                domain=domain,
                publisher=domain,
                accessed_at=now,
                quality_tier=tier,  # type: ignore[arg-type]
                quality_reason=reason,
                canonical_url=item.get("canonical_url") or canonical_url(url),
            )
        )
    return SourceRegistry(project_id=project_id, sources=records)


def reclassify_registry(registry: SourceRegistry) -> SourceRegistry:
    records: list[SourceRecord] = []
    for source in registry.sources:
        tier, reason = classify_source_quality(source.url, title=source.title)
        records.append(
            source.model_copy(update={"quality_tier": tier, "quality_reason": reason})
        )
    return registry.model_copy(update={"sources": records})


def url_to_source_id(registry: SourceRegistry) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for source in registry.sources:
        mapping[canonical_url(source.url)] = source.source_id
        if source.canonical_url:
            mapping[source.canonical_url] = source.source_id
    return mapping


def annotations_from_response(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if str(node.get("type") or "") in {"url_citation", "citation"} and node.get("url"):
                found.append(
                    {
                        "type": "url_citation",
                        "url": str(node.get("url")),
                        "title": str(node.get("title") or ""),
                        "start_index": node.get("start_index"),
                        "end_index": node.get("end_index"),
                    }
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def web_search_sources_from_response(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if str(node.get("type") or "") == "web_search_call":
                action = node.get("action") or {}
                sources = []
                if isinstance(action, dict):
                    sources = action.get("sources") or []
                if isinstance(sources, list):
                    for item in sources:
                        if isinstance(item, dict) and item.get("url"):
                            found.append(
                                {
                                    "url": str(item.get("url")),
                                    "title": str(item.get("title") or ""),
                                }
                            )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def normalize_citations(
    text: str, registry: SourceRegistry, annotations: list[dict[str, Any]]
) -> str:
    mapping = url_to_source_id(registry)
    pieces = list(text)
    indexed = [
        item for item in annotations if isinstance(item.get("end_index"), int) and item.get("url")
    ]
    indexed.sort(key=lambda item: int(item["end_index"]), reverse=True)
    for item in indexed:
        url = canonical_url(str(item["url"]))
        source_id = mapping.get(url)
        if source_id is None:
            continue
        end = int(item["end_index"])
        if 0 <= end <= len(pieces):
            marker = f" [{source_id}]"
            pieces[end:end] = list(marker)
    rewritten = "".join(pieces)
    rewritten = _OPAQUE_CITE_RE.sub("", rewritten)
    for source in registry.sources:
        if source.url and source.url in rewritten:
            rewritten = rewritten.replace(source.url, f"[{source.source_id}]")
    rewritten = re.sub(r"[ \t]+\n", "\n", rewritten)
    rewritten = re.sub(r"\n{3,}", "\n\n", rewritten)
    return rewritten.strip() + "\n"


def dangling_citations(text: str, registry: SourceRegistry) -> list[str]:
    known = {item.source_id for item in registry.sources}
    dangling: list[str] = []
    for match in _SOURCE_REF_RE.finditer(text):
        ref = f"S{match.group(1)}"
        if ref not in known and ref not in dangling:
            dangling.append(ref)
    return dangling


def source_index_markdown(registry: SourceRegistry) -> str:
    lines = ["", "## Source index", ""]
    for source in registry.sources:
        title = source.title or source.domain
        lines.append(f"- [{source.source_id}] {title} ({source.quality_tier}) — {source.url}")
    return "\n".join(lines) + "\n"
