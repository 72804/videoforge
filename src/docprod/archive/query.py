from __future__ import annotations

from docprod.models.scene import Scene


def archive_queries(scene: Scene, *, max_queries: int = 3) -> list[str]:
    seed = str(scene.metadata.get("archive_search_seed") or "").strip()
    queries: list[str] = []
    if seed:
        queries.append(seed)
    extras = [
        "Great Canadian Maple Syrup Heist Quebec warehouse",
        "maple syrup barrels Quebec warehouse",
        "Federation of Quebec Maple Syrup Producers",
    ]
    blob = f"{scene.narration} {scene.visual_intent}".casefold()
    if "kedgwick" in blob:
        extras.insert(0, "Kedgwick New Brunswick")
    if "laurierville" in blob:
        extras.insert(0, "Laurierville Quebec maple")
    if "supreme" in blob or "yüksek mahkeme" in blob:
        extras.insert(0, "Supreme Court of Canada building")
    for item in extras:
        if item not in queries:
            queries.append(item)
        if len(queries) >= max_queries:
            break
    return queries[:max_queries]
