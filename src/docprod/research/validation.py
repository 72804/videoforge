from __future__ import annotations

import re

from docprod.exceptions import ResearchQualityError
from docprod.research.citations import dangling_citations
from docprod.research.models import QualityGateResult, SourceRegistry

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_VALUE_RE = re.compile(
    r"(barrel|varil|litre|liter|gallon|million|milyon|cad|usd|\$|tonne|ton)",
    re.IGNORECASE,
)
_LEGAL_RE = re.compile(
    r"(charg|convict|sentence|plea|accused|suçlu|mahkeme|ceza|tutuk|beraat|guilty)",
    re.IGNORECASE,
)
STRONG_B = {"reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "cbc.ca", "ap.org"}


def evaluate_research_quality(
    report: str,
    registry: SourceRegistry,
    *,
    require: bool = True,
) -> QualityGateResult:
    useful = [item for item in registry.sources if item.quality_tier != "low"]
    domains = {item.domain for item in useful}
    tier_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0, "low": 0}
    for item in registry.sources:
        tier_counts[item.quality_tier] = tier_counts.get(item.quality_tier, 0) + 1
    has_primary = any(item.quality_tier == "A" for item in registry.sources) or any(
        item.domain in STRONG_B or item.domain.endswith("." + domain)
        for item in registry.sources
        for domain in STRONG_B
    )
    dangling = dangling_citations(report, registry)
    chronology = len(set(_YEAR_RE.findall(report))) >= 2
    value_ok = bool(_VALUE_RE.search(report)) and len(useful) >= 1
    legal_mentioned = bool(_LEGAL_RE.search(report))
    legal_ok = (not legal_mentioned) or len(useful) >= 1
    failures: list[str] = []
    if len(useful) < 5:
        failures.append(f"Need >=5 useful sources, found {len(useful)}")
    if len(domains) < 2:
        failures.append(f"Need >=2 independent domains, found {len(domains)}")
    if not has_primary:
        failures.append("Need at least one Tier A or strong Tier B source")
    if not chronology:
        failures.append("Core chronology is not evidenced by multiple years in the report")
    if not value_ok:
        failures.append("Quantity/value claims are missing or unsourced")
    if not legal_ok:
        failures.append("Legal outcomes are mentioned without sourced support")
    if dangling:
        failures.append("Unresolved citation references: " + ", ".join(dangling))
    result = QualityGateResult(
        passed=not failures,
        useful_source_count=len(useful),
        independent_domains=len(domains),
        tier_counts=tier_counts,
        has_tier_a_or_strong_b=has_primary,
        chronology_supported=chronology,
        value_claims_sourced=value_ok,
        legal_outcomes_sourced=legal_ok,
        dangling_citations=dangling,
        failures=failures,
    )
    if require and not result.passed:
        raise ResearchQualityError("; ".join(failures))
    return result
