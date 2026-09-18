from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TIER_A_DOMAINS = {
    "canada.ca",
    "gc.ca",
    "justice.gc.ca",
    "canlii.org",
    "laws-lois.justice.gc.ca",
    "rcmp-grc.gc.ca",
    "quebec.ca",
    "ontario.ca",
    "scc-csc.ca",
    "scc-csc.gc.ca",
    "sec.gov",
    "justice.gov",
    "fbi.gov",
    "courtlistener.com",
    "supremecourt.gov",
    "europa.eu",
    "un.org",
}

TIER_B_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "ap.org",
    "bbc.com",
    "bbc.co.uk",
    "cbc.ca",
    "theglobeandmail.com",
    "nytimes.com",
    "washingtonpost.com",
    "theguardian.com",
    "wsj.com",
    "ft.com",
    "latimes.com",
    "npr.org",
    "pbs.org",
    "bloomberg.com",
    "economist.com",
    "csmonitor.com",
    "lapresse.ca",
    "montrealgazette.com",
    "nationalpost.com",
    "ctvnews.ca",
    "globalnews.ca",
    "associatedpress.com",
}

TIER_C_DOMAINS = {
    "wikipedia.org",
    "britannica.com",
    "smithsonianmag.com",
    "theatlantic.com",
    "newyorker.com",
    "time.com",
    "nationalgeographic.com",
    "history.com",
    "vanityfair.com",
    "wired.com",
}

LOW_DOMAINS = {
    "buzzfeed.com",
    "ranker.com",
    "listverse.com",
    "medium.com",
    "quora.com",
    "pinterest.com",
    "tumblr.com",
    "blogspot.com",
    "wordpress.com",
    "weebly.com",
    "wixsite.com",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "reddit.com",
    "fandom.com",
}


def extract_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    netloc = (parsed.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    path = parsed.path.rstrip("/") or "/"
    cleaned = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=netloc,
        path=path,
        query=urlencode(query),
        fragment="",
    )
    return urlunparse(cleaned)


def _suffix_match(domain: str, known: set[str]) -> bool:
    return any(domain == item or domain.endswith("." + item) for item in known)


def classify_source_quality(url: str, *, title: str = "") -> tuple[str, str]:
    """Heuristic classification. Domain is evidence, not a reputation oracle."""
    domain = extract_domain(url)
    haystack = f"{url} {title}".lower()
    if (
        _suffix_match(domain, TIER_A_DOMAINS)
        or domain.endswith(".gov")
        or domain.endswith(".gc.ca")
    ):
        return (
            "A",
            f"Domain {domain} matches a government, court, or primary-institution pattern.",
        )
    if _suffix_match(domain, TIER_B_DOMAINS):
        return (
            "B",
            f"Domain {domain} matches a major established news organization list.",
        )
    if _suffix_match(domain, LOW_DOMAINS):
        return (
            "low",
            f"Domain {domain} matches a low-quality / social / content-farm pattern.",
        )
    if any(token in haystack for token in ("listicle", "things you won't believe", "sponsored")):
        return "low", "Title/URL language resembles unsourced listicle or sponsored content."
    if _suffix_match(domain, TIER_C_DOMAINS):
        return (
            "C",
            f"Domain {domain} matches an established magazine or reference source list.",
        )
    if domain.endswith(".edu") or domain.endswith(".org"):
        return (
            "C",
            f"Domain {domain} is an .edu/.org host not on the primary news/court lists.",
        )
    return (
        "low",
        f"Domain {domain} is unclassified; treated as low quality until independently verified.",
    )
