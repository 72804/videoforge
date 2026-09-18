from __future__ import annotations

import pytest

from docprod.exceptions import ResearchQualityError
from docprod.research.citations import build_source_registry, collect_raw_sources
from docprod.research.validation import evaluate_research_quality


def _registry(*urls: str):
    raw = collect_raw_sources(
        annotations=[],
        web_search_sources=[{"url": url, "title": url} for url in urls],
    )
    return build_source_registry("p", raw)


def test_insufficient_sources_and_domains_fail() -> None:
    report = "In 2011 and 2012 thieves took 3000 barrels worth millions and were convicted."
    few = _registry("https://www.cbc.ca/one")
    with pytest.raises(ResearchQualityError, match="useful sources"):
        evaluate_research_quality(report, few, require=True)
    same_domain = _registry(
        "https://www.cbc.ca/a",
        "https://www.cbc.ca/b",
        "https://www.cbc.ca/c",
        "https://www.cbc.ca/d",
        "https://www.cbc.ca/e",
    )
    with pytest.raises(ResearchQualityError, match="independent domains"):
        evaluate_research_quality(report, same_domain, require=True)


def test_quality_gate_passes_with_primary_and_news() -> None:
    report = (
        "In 2011-2012 the Federation found thousands of barrels missing, "
        "worth millions CAD. Convictions followed."
    )
    registry = _registry(
        "https://canlii.org/en/qc/doc/2013/x",
        "https://www.cbc.ca/news/heist",
        "https://www.reuters.com/world/maple",
        "https://www.theglobeandmail.com/news/heist",
        "https://www.bbc.com/news/heist",
    )
    result = evaluate_research_quality(report, registry, require=True)
    assert result.passed
    assert result.useful_source_count >= 5
    assert result.independent_domains >= 2
    assert result.has_tier_a_or_strong_b
