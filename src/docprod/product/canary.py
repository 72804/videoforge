from __future__ import annotations


def parse_telegram_allowlist(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        token = part.strip()
        if not token:
            continue
        ids.add(int(token))
    return frozenset(ids)


def canary_allows(telegram_user_id: int, allowlist: frozenset[int], *, required: bool) -> bool:
    if not required:
        return True
    return telegram_user_id in allowlist
