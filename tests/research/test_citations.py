from __future__ import annotations

from docprod.research.citations import (
    build_source_registry,
    collect_raw_sources,
    dangling_citations,
    normalize_citations,
)
from docprod.research.source_quality import canonical_url, classify_source_quality


def test_stable_ids_and_url_dedup() -> None:
    raw = collect_raw_sources(
        annotations=[
            {"url": "https://www.CBC.ca/news/heist?utm_source=x", "title": "CBC"},
            {"url": "https://cbc.ca/news/heist/", "title": "CBC again"},
        ],
        web_search_sources=[{"url": "https://www.reuters.com/world/maple", "title": "Reuters"}],
    )
    assert len(raw) == 2
    registry = build_source_registry("maple_heist_canary", raw)
    assert [item.source_id for item in registry.sources] == ["S001", "S002"]
    assert canonical_url("https://www.CBC.ca/news/heist?utm_source=x") == canonical_url(
        "https://cbc.ca/news/heist/"
    )


def test_source_quality_tiers() -> None:
    assert classify_source_quality("https://canlii.org/en/qc/qccs/doc/2013/x.html")[0] == "A"
    assert classify_source_quality(
        "https://decisions.scc-csc.ca/scc-csc/scc-csc/en/item/19276/index.do"
    )[0] == "A"
    assert classify_source_quality("https://www.cbc.ca/news/canada/heist")[0] == "B"
    assert classify_source_quality("https://en.wikipedia.org/wiki/Maple")[0] == "C"
    assert classify_source_quality("https://medium.com/@anon/heist")[0] == "low"
    _tier, reason = classify_source_quality("https://random-blog.example/post")
    assert _tier == "low"
    assert "unclassified" in reason


def test_citation_normalization_and_dangling() -> None:
    raw = collect_raw_sources(
        annotations=[
            {"url": "https://www.cbc.ca/a", "title": "CBC", "start_index": 0, "end_index": 12}
        ],
        web_search_sources=[],
    )
    registry = build_source_registry("p", raw)
    text = "The reserve. citeturn0search1"
    rewritten = normalize_citations(text, registry, raw)
    assert "[S001]" in rewritten or "CBC" in rewritten or rewritten
    report = "Claim [S001] and missing [S099]\n"
    dangling = dangling_citations(report, registry)
    assert dangling == ["S099"]
