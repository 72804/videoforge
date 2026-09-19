from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene, ScenePlan
from docprod.planning.visual_policy import _fold
from docprod.production import AssetPlan, AssetUnit
from docprod.storage.paths import ProjectPaths

REUSE_TOTAL_WARN = 3
REUSE_NEARBY_SECONDS = 60.0
REUSE_NEARBY_WARN = 2
REUSE_WINDOWS = (30.0, 60.0, 120.0)

CONTINUITY_FLAGS = frozenset({"reuse_allowed", "establishing_motif", "continuity_asset"})

WAREHOUSE_FAMILIES = frozenset(
    {
        "warehouse_barrels",
        "warehouse_exterior",
        "empty_storage",
        "industrial_closeup",
        "storage_security",
    }
)

POLICE_FAMILIES: dict[str, tuple[str, ...]] = {
    "investigators_files": (
        "detective reviewing documents office desk",
        "investigator examining paperwork files",
        "hands sorting case files table",
    ),
    "police_exterior": (
        "police officers walking building exterior",
        "law enforcement entering courthouse",
        "canada police car parked street daytime",
    ),
    "evidence_handling": (
        "evidence bags investigation table",
        "forensic boxes warehouse inspection",
        "gloved hands evidence envelope",
    ),
    "warehouse_search": (
        "industrial warehouse inspection flashlight",
        "inspectors checking barrels warehouse",
        "empty warehouse aisle inspection",
    ),
    "police_vehicle": (
        "parked police vehicle rural road",
        "patrol car winter canada",
        "law enforcement vehicle exterior",
    ),
    "interview_room": (
        "empty interrogation room two chairs",
        "interview room table chairs",
        "sparse questioning room interior",
    ),
    "seizure_transport": (
        "warehouse pallets seized goods",
        "loading dock cargo pallets",
        "industrial goods being loaded truck",
    ),
}

COURT_QUERIES = (
    "canadian courthouse exterior columns",
    "stone courthouse facade winter",
    "law books legal files courthouse",
)
SCC_QUERIES = (
    "Supreme Court of Canada building Ottawa",
    "Supreme Court of Canada west facade",
)
MAPLE_VARIETY_QUERIES: dict[str, tuple[str, ...]] = {
    "quebec_countryside": ("quebec countryside rural village", "rural quebec farmland autumn"),
    "maple_harvesting": ("maple syrup tapping forest", "maple sap buckets trees"),
    "pallet_storage": ("warehouse pallet storage industrial", "stacked pallets warehouse"),
    "rural_road": ("rural canadian road winter trees", "country road quebec"),
}

FAMILY_POSITIVE: dict[str, tuple[str, ...]] = {
    "investigators_files": ("file", "document", "paper", "office", "desk", "folder"),
    "police_exterior": ("police", "officer", "patrol", "uniform"),
    "evidence_handling": ("evidence", "forensic", "bag", "glove"),
    "warehouse_search": ("warehouse", "inspect", "barrel", "industrial"),
    "police_vehicle": ("police", "patrol", "vehicle", "car"),
    "interview_room": ("interview", "interrogation", "chair", "room"),
    "seizure_transport": ("pallet", "cargo", "loading", "warehouse"),
    "court": ("court", "courthouse", "columns", "justice", "law"),
    "scc": ("supreme", "canada", "ottawa", "court"),
}

FAMILY_NEGATIVE: dict[str, tuple[str, ...]] = {
    "investigators_files": ("siren", "chase", "nypd", "flashing", "swat"),
    "court": ("warehouse", "barrel", "maple", "syrup"),
    "scc": ("warehouse", "barrel", "nypd"),
    "police_exterior": ("nypd", "berlin", "tokyo"),
}


@dataclass
class SourceUse:
    unit_id: str
    scene_ids: list[str]
    start: float
    duration: float
    source_id: str
    path: str
    strategy: str
    visual_need: str
    narration: str
    query: str = ""
    exempt: bool = False


@dataclass
class RepetitionWarning:
    source_id: str
    kind: str
    unit_ids: list[str]
    detail: str


@dataclass
class DiversityItem:
    unit_id: str
    scene_ids: list[str]
    reason: str
    family: str
    action: str
    query: str = ""
    reuse_path: str | None = None
    sequence_paths: list[str] = field(default_factory=list)
    old_source_id: str = ""
    narration_snippet: str = ""
    provider: str = ""
    priority: str = "P5"


@dataclass
class DiversityReport:
    uses: list[SourceUse]
    warnings: list[RepetitionWarning]
    items: list[DiversityItem]
    unique_sources: int
    max_reuse: int
    sources_reused_over_2: int
    nearby_warnings: int
    police_duplicate_max: int
    court_mismatch: int
    paid_api_calls: int = 0
    notes: list[str] = field(default_factory=list)


def narration_blob(scene: Scene) -> str:
    return _fold(scene.narration)


def is_intentional_continuity(unit: AssetUnit) -> bool:
    extra = unit.extra or {}
    if any(extra.get(flag) for flag in CONTINUITY_FLAGS):
        return True
    if unit.reuse_mode == "shared_continue" and unit.continuity_group:
        return True
    return False


def is_court_legal_narration(text: str) -> bool:
    blob = _fold(text)
    tokens = (
        "mahkeme",
        "juri",
        "jüri",
        "hapis",
        "tazminat",
        "temyiz",
        "beraat",
        "mahkum",
        "mahkûm",
        "yargi",
        "yargı",
        "sucuklu",
    )
    if any(token in blob for token in tokens):
        return True
    if "sucu bul" in blob or "suçlu" in blob or "para ceza" in blob:
        return True
    return False


def is_supreme_court_narration(text: str) -> bool:
    blob = _fold(text)
    return "yuksek mahkeme" in blob or "yüksek mahkeme" in blob or "supreme court" in blob


def is_inventory_not_chase(text: str) -> bool:
    blob = _fold(text)
    return "takibi degil" in blob or "takibi değil" in blob or (
        "envanter" in blob and "polis" in blob
    )


def police_family_for_narration(text: str) -> str | None:
    blob = _fold(text)
    if is_inventory_not_chase(blob):
        return None
    if is_supreme_court_narration(blob) or "beraat" in blob:
        return None
    if is_court_legal_narration(blob) and not any(
        token in blob for token in ("polis", "tutukla", "sorustur", "soruştur")
    ):
        return None
    if any(token in blob for token in ("gozden gecir", "gözden geçir")) and any(
        token in blob for token in ("kayit", "kayıt", "belge", "sevkiyat")
    ):
        return "investigators_files"
    police_ctx = any(
        token in blob
        for token in ("polis", "sorustur", "soruştur", "tutukla", "arama", "el koy", "operasyon")
    )
    if not police_ctx:
        return None
    if any(
        token in blob
        for token in ("kayit", "kayıt", "belge", "gozden gecir", "gözden geçir")
    ):
        return "investigators_files"
    if any(token in blob for token in ("tutukla", "supheli", "şüpheli")):
        return "police_exterior"
    if any(token in blob for token in ("el koy", "operasyon", "kedgwick")):
        return "seizure_transport"
    if "polise basvur" in blob or "polise başvur" in blob or "polis belgeler" in blob:
        return "investigators_files"
    return "warehouse_search"


def visual_need(scene: Scene) -> str:
    blob = narration_blob(scene)
    if is_supreme_court_narration(blob):
        return "scc"
    if is_inventory_not_chase(blob):
        return "empty_storage"
    family = police_family_for_narration(blob)
    if family:
        return family
    if is_court_legal_narration(blob):
        return "court"
    if any(token in blob for token in ("kamyon", "tasindi", "taşınd", "ontario", "abd")):
        return "truck_transport"
    if any(token in blob for token in ("orman", "akcaagac", "akçaağaç", "quebec")):
        return "maple_forest"
    return "warehouse_barrels"


def family_from_query(query: str, path: str = "") -> str:
    hay = _fold(f"{query} {path}")
    if any(token in hay for token in ("police", "detect", "interrog", "patrol", "officer")):
        return "police"
    if any(token in hay for token in ("court", "mahkeme", "law book", "supreme")):
        return "court"
    if any(token in hay for token in ("barrel", "warehouse", "depo", "pallet")):
        return "warehouse_barrels"
    if "maple" in hay or "syrup" in hay or "forest" in hay:
        return "maple_forest"
    if "truck" in hay or "highway" in hay:
        return "truck_transport"
    return "other"


def court_warehouse_mismatch(scene: Scene, family: str) -> bool:
    if visual_need(scene) not in {"court", "scc"}:
        return False
    return family in WAREHOUSE_FAMILIES or family == "warehouse_barrels"


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def resolve_unit_media(paths: ProjectPaths, unit: AssetUnit, scene: Scene) -> Path | None:
    strategy = unit.source_strategy

    def archive_file() -> Path | None:
        for suffix in (".jpg", ".jpeg", ".png"):
            archive = paths.archive_source_path(unit.asset_unit_id, suffix)
            if archive.is_file():
                return archive
        return None

    def stock_file() -> Path | None:
        stock = paths.stock_source_mp4(scene.id)
        return stock if stock.is_file() else None

    def still_file() -> Path | None:
        still = paths.ai_unit_still_path(unit.asset_unit_id)
        if still.is_file():
            return still
        key = paths.ai_keyframe_path(unit.asset_unit_id)
        if key.is_file():
            return key
        return None

    if strategy in {AssetStrategy.archive_image, AssetStrategy.archive_video}:
        return archive_file() or stock_file() or still_file()
    if strategy in {AssetStrategy.ai_image, AssetStrategy.ai_image_to_video}:
        return still_file() or archive_file() or stock_file()
    if strategy is AssetStrategy.stock_video:
        return stock_file() or archive_file() or still_file()
    return stock_file() or archive_file() or still_file()


def collect_source_uses(
    paths: ProjectPaths, plan: ScenePlan, asset_plan: AssetPlan
) -> list[SourceUse]:
    scenes = {scene.id: scene for scene in plan.scenes}
    uses: list[SourceUse] = []
    for unit in asset_plan.units:
        first = scenes[unit.scene_ids[0]]
        media = resolve_unit_media(paths, unit, first)
        source_id = "missing"
        path_s = ""
        if media is not None:
            source_id = file_fingerprint(media)
            path_s = media.as_posix()
        uses.append(
            SourceUse(
                unit_id=unit.asset_unit_id,
                scene_ids=list(unit.scene_ids),
                start=first.start,
                duration=float(unit.continuous_duration),
                source_id=source_id,
                path=path_s,
                strategy=unit.source_strategy.value,
                visual_need=visual_need(first),
                narration=first.narration,
                exempt=is_intentional_continuity(unit),
            )
        )
    return uses


def detect_repetition(uses: list[SourceUse]) -> list[RepetitionWarning]:
    warnings: list[RepetitionWarning] = []
    by_source: dict[str, list[SourceUse]] = defaultdict(list)
    for use in uses:
        if use.source_id == "missing":
            continue
        by_source[use.source_id].append(use)
    for source_id, group in by_source.items():
        group = sorted(group, key=lambda item: item.start)
        if all(item.exempt for item in group):
            continue
        if len(group) > REUSE_TOTAL_WARN and not all(item.exempt for item in group):
            warnings.append(
                RepetitionWarning(
                    source_id=source_id,
                    kind="UNWANTED_REPETITION",
                    unit_ids=[item.unit_id for item in group],
                    detail=f"used {len(group)} times",
                )
            )
        needs = {item.visual_need for item in group}
        if len(group) > 1 and len(needs) > 1:
            warnings.append(
                RepetitionWarning(
                    source_id=source_id,
                    kind="SEMANTIC_MISMATCH_REUSE",
                    unit_ids=[item.unit_id for item in group],
                    detail=f"needs={sorted(needs)}",
                )
            )
        for window in REUSE_WINDOWS:
            for index, current in enumerate(group):
                cluster = [
                    item
                    for item in group
                    if abs(item.start - current.start) <= window
                ]
                if len(cluster) > REUSE_NEARBY_WARN:
                    warnings.append(
                        RepetitionWarning(
                            source_id=source_id,
                            kind="NEARBY_REUSE",
                            unit_ids=[item.unit_id for item in cluster],
                            detail=f">{REUSE_NEARBY_WARN} uses within {int(window)}s",
                        )
                    )
                    break
            else:
                continue
            break
    return warnings


def police_duplicate_max(uses: list[SourceUse]) -> int:
    police_ids = [
        item.source_id
        for item in uses
        if item.visual_need in POLICE_FAMILIES and item.source_id != "missing"
    ]
    if not police_ids:
        return 0
    return max(Counter(police_ids).values())


def metrics_from_uses(uses: list[SourceUse], warnings: list[RepetitionWarning]) -> dict[str, int]:
    counts = Counter(item.source_id for item in uses if item.source_id != "missing")
    return {
        "unique_sources": len(counts),
        "max_reuse": max(counts.values()) if counts else 0,
        "sources_reused_over_2": sum(1 for value in counts.values() if value > 2),
        "nearby_warnings": sum(1 for item in warnings if item.kind == "NEARBY_REUSE"),
        "police_duplicate_max": police_duplicate_max(uses),
    }


def supreme_court_archive_preferred(narration: str, archive_available: bool) -> bool:
    return is_supreme_court_narration(narration) and archive_available


def court_rejects_warehouse_when_court_exists(
    narration: str, current_family: str, court_asset_exists: bool
) -> bool:
    return (
        is_court_legal_narration(narration)
        and current_family in WAREHOUSE_FAMILIES.union({"warehouse_barrels"})
        and court_asset_exists
    )
