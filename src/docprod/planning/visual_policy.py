from __future__ import annotations

from dataclasses import dataclass, field

from docprod.models.enums import AssetStrategy
from docprod.models.scene import Scene
from docprod.planning.models import ContentCategory
from docprod.planning.semantic_models import SemanticSceneIntent

VISUAL_POLICY = (
    "Prefer photographic/filmic visual storytelling over explanatory generated "
    "graphics. Facts are primarily conveyed by narration/subtitles. Generated "
    "infographics, fake documents, fake maps, and data cards are disabled by default."
)

STRATEGY_AVAILABILITY: dict[AssetStrategy, str] = {
    AssetStrategy.generated_graphic: "manual_or_explicit_only",
    AssetStrategy.document: "manual_or_explicit_only",
    AssetStrategy.map: "manual_or_explicit_only",
    AssetStrategy.text_card: "manual_or_explicit_only",
}

EXPLAINER_STRATEGIES = frozenset(
    {
        AssetStrategy.generated_graphic,
        AssetStrategy.document,
        AssetStrategy.map,
        AssetStrategy.text_card,
    }
)

CINEMATIC_PREFERRED: dict[ContentCategory, AssetStrategy] = {
    ContentCategory.location_establishing: AssetStrategy.stock_video,
    ContentCategory.time_establishing: AssetStrategy.stock_video,
    ContentCategory.person: AssetStrategy.archive_image,
    ContentCategory.money: AssetStrategy.stock_video,
    ContentCategory.police: AssetStrategy.stock_video,
    ContentCategory.crime: AssetStrategy.ai_image,
    ContentCategory.vehicle: AssetStrategy.stock_video,
    ContentCategory.building: AssetStrategy.stock_video,
    ContentCategory.document: AssetStrategy.archive_image,
    ContentCategory.news: AssetStrategy.archive_image,
    ContentCategory.map_or_travel: AssetStrategy.stock_video,
    ContentCategory.technology: AssetStrategy.stock_video,
    ContentCategory.phone_or_computer: AssetStrategy.stock_video,
    ContentCategory.court_or_legal: AssetStrategy.stock_video,
    ContentCategory.nature: AssetStrategy.stock_video,
    ContentCategory.crowd: AssetStrategy.stock_video,
    ContentCategory.interior: AssetStrategy.ai_image,
    ContentCategory.action: AssetStrategy.ai_image,
    ContentCategory.danger: AssetStrategy.ai_image,
    ContentCategory.generic: AssetStrategy.ai_image,
}

CONCEPT_ORDER = (
    "warehouse_exterior",
    "maple_harvesting",
    "warehouse_barrels",
    "industrial_closeup",
    "truck_transport",
    "archive_evidence",
    "police_investigation",
    "highway_aerial",
    "courthouse",
    "maple_forest",
    "storage_security",
    "anonymous_worker",
    "syrup_closeup",
    "empty_storage",
)

_CONCEPT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("courthouse", ("mahkeme", "yargı", "yuksek mahkeme", "temyiz", "juri", "hapis", "tazminat")),
    ("police_investigation", ("polis", "tutukla", "soruştur", "sorustur", "arama", "el koy")),
    ("truck_transport", ("kamyon", "taşınd", "tasind", "sevkiyat", "ihracat", "ontario", "abd")),
    (
        "highway_aerial",
        ("güzergah", "guzergah", "harita", "quebec city", "kedgwick", "laurierville"),
    ),
    ("maple_harvesting", ("orman", "sap", "üretim", "uretim", "federasyon", "kota", "yüzde 80")),
    ("maple_forest", ("akçaağaç", "akcaagac", "kırsal", "kirsal", "quebec")),
    ("syrup_closeup", ("şurup", "surup", "numune", "su alın")),
    ("industrial_closeup", ("işleme", "isleme", "pompa", "tartı", "tartı")),
    ("storage_security", ("güvenlik", "guvenlik", "kamera", "çit", "cit")),
    ("warehouse_exterior", ("depo çev", "kiralık depo", "saint-louis", "blandford")),
    ("empty_storage", ("eksik", "kayıp", "kayip", "boş", "bos kalan")),
    ("warehouse_barrels", ("fıçı", "fici", "depo", "rezerv", "varil")),
    ("anonymous_worker", ("işçi", "isci", "denetim", "envanter")),
    ("archive_evidence", ("karar", "dosya", "kayıt", "kayit", "belge")),
)

STOCK_QUERIES: dict[str, tuple[str, ...]] = {
    "maple_harvesting": ("maple syrup tapping forest", "maple sap harvest quebec"),
    "maple_forest": ("maple forest aerial canada", "autumn maple woods canada"),
    "warehouse_exterior": (
        "rural industrial warehouse exterior winter",
        "steel warehouse building snow",
    ),
    "warehouse_barrels": ("steel barrels warehouse interior", "industrial barrel storage"),
    "industrial_closeup": ("factory processing tanks", "industrial food processing plant"),
    "truck_transport": ("freight truck highway canada", "warehouse loading dock truck"),
    "highway_aerial": ("aerial rural highway canada", "canadian road winter aerial"),
    "police_investigation": ("police investigation hallway", "detectives reviewing case files"),
    "courthouse": ("courthouse exterior columns", "supreme court building canada"),
    "storage_security": ("warehouse security cameras fence", "industrial loading gate"),
    "anonymous_worker": ("warehouse worker anonymous hard hat", "inspector checking barrels"),
    "syrup_closeup": ("maple syrup pour close up", "amber syrup in glass"),
    "empty_storage": ("empty warehouse aisle", "sparse industrial storage"),
    "archive_evidence": ("historical newspaper archive desk", "legal files stacked courthouse"),
}

ARCHIVE_QUERIES: dict[str, tuple[str, ...]] = {
    "courthouse": ("Supreme Court of Canada building Ottawa",),
    "archive_evidence": ("historical maple syrup barrels Quebec",),
    "maple_forest": ("Quebec maple forest historical photograph",),
}

AI_STILL_PROMPTS: dict[str, str] = {
    "warehouse_exterior": (
        "Documentary photograph of a rural Quebec industrial warehouse exterior, "
        "corrugated steel, winter light, no readable signage or logos."
    ),
    "warehouse_barrels": (
        "Documentary photograph of rows of sealed steel barrels in a dim warehouse, "
        "natural practical lighting, no labels with readable text."
    ),
    "industrial_closeup": (
        "Close documentary still of industrial food-processing pipes and valves, "
        "credible metal and condensation, no diagrams or UI."
    ),
    "anonymous_worker": (
        "Anonymous warehouse inspector from behind, checking barrel lids, "
        "no identifiable face, documentary photography."
    ),
    "syrup_closeup": (
        "Close documentary photograph of dark amber maple syrup texture in a steel drum, "
        "no infographic styling."
    ),
    "empty_storage": (
        "Mostly empty industrial warehouse aisle with a few remaining barrels, "
        "restrained documentary lighting."
    ),
    "police_investigation": (
        "Anonymous investigators at a table of unlabeled folders in a municipal office, "
        "faces turned away, no fake stamps or readable case numbers."
    ),
    "courthouse": (
        "Documentary photograph of a grand stone courthouse exterior in Canada, "
        "overcast daylight, no superimposed text."
    ),
    "truck_transport": (
        "Freight truck leaving an industrial warehouse loading dock, documentary still, "
        "no readable license plates or company names."
    ),
}


def explicit_explainer_requested(scene: Scene | SemanticSceneIntent | None) -> bool:
    if scene is None:
        return False
    if isinstance(scene, SemanticSceneIntent):
        return bool(getattr(scene, "explicit_explainer", False))
    meta = scene.metadata or {}
    return bool(meta.get("explicit_explainer") or meta.get("allow_generated_graphic"))


def is_explainer_strategy(strategy: AssetStrategy, *, explicit: bool = False) -> bool:
    if strategy not in EXPLAINER_STRATEGIES:
        return False
    return not explicit


PREFERRED_EXPLICIT: dict[ContentCategory, AssetStrategy] = {
    ContentCategory.location_establishing: AssetStrategy.stock_video,
    ContentCategory.time_establishing: AssetStrategy.generated_graphic,
    ContentCategory.person: AssetStrategy.ai_image,
    ContentCategory.money: AssetStrategy.stock_video,
    ContentCategory.police: AssetStrategy.archive_video,
    ContentCategory.crime: AssetStrategy.ai_image,
    ContentCategory.vehicle: AssetStrategy.stock_video,
    ContentCategory.building: AssetStrategy.stock_video,
    ContentCategory.document: AssetStrategy.document,
    ContentCategory.news: AssetStrategy.document,
    ContentCategory.map_or_travel: AssetStrategy.map,
    ContentCategory.technology: AssetStrategy.stock_video,
    ContentCategory.phone_or_computer: AssetStrategy.stock_video,
    ContentCategory.court_or_legal: AssetStrategy.document,
    ContentCategory.nature: AssetStrategy.stock_video,
    ContentCategory.crowd: AssetStrategy.stock_video,
    ContentCategory.interior: AssetStrategy.ai_image,
    ContentCategory.action: AssetStrategy.ai_image,
    ContentCategory.danger: AssetStrategy.ai_image,
    ContentCategory.generic: AssetStrategy.ai_image,
}


def cinematic_strategy_for_category(
    category: ContentCategory, *, visual_bridge: bool, explicit: bool = False
) -> AssetStrategy:
    if visual_bridge:
        return AssetStrategy.placeholder
    if explicit:
        return PREFERRED_EXPLICIT[category]
    return CINEMATIC_PREFERRED[category]


def cinematic_strategy_for_intent(intent: SemanticSceneIntent) -> AssetStrategy:
    pref = intent.preferred_source_type
    movement = intent.movement_need
    if intent.historical_specificity == "exact_person_or_event":
        return AssetStrategy.archive_image
    if pref == "archive" or pref == "photograph":
        return (
            AssetStrategy.archive_video
            if movement in {"medium", "high"}
            else AssetStrategy.archive_image
        )
    if pref == "stock_video":
        return AssetStrategy.stock_video
    if pref in {"document", "newspaper", "infographic", "text_card", "map"}:
        if movement in {"medium", "high"} or pref == "map":
            return AssetStrategy.stock_video
        if pref in {"document", "newspaper"}:
            return AssetStrategy.archive_image
        return AssetStrategy.stock_video
    if pref == "ai_reenactment":
        if intent.reenactment_freedom == "avoid":
            return AssetStrategy.stock_video
        return AssetStrategy.ai_image
    return AssetStrategy.stock_video


def statistics_do_not_imply_chart(text: str) -> AssetStrategy:
    _ = text
    return AssetStrategy.stock_video


def dates_do_not_imply_document(text: str) -> AssetStrategy:
    _ = text
    return AssetStrategy.archive_image


def geography_does_not_imply_map(text: str) -> AssetStrategy:
    _ = text
    return AssetStrategy.stock_video


def legal_outcome_does_not_imply_court_graphic(text: str) -> AssetStrategy:
    _ = text
    return AssetStrategy.stock_video


def _fold(text: str) -> str:
    return text.replace("İ", "i").replace("I", "i").replace("ı", "i").casefold()


def concept_for_scene(scene: Scene, recent: list[str]) -> str:
    blob = _fold(
        " ".join(
            [
                scene.narration,
                scene.visual_intent,
                str(scene.metadata.get("visual_subject") or ""),
                str(scene.metadata.get("visual_purpose") or ""),
            ]
        )
    )
    ranked: list[str] = []
    for concept, keys in _CONCEPT_KEYWORDS:
        if any(key in blob for key in keys):
            ranked.append(concept)
    if not ranked:
        ranked = ["warehouse_barrels"]
    for concept in ranked:
        if concept not in recent[-2:]:
            return concept
    for concept in CONCEPT_ORDER:
        if concept not in recent[-2:]:
            return concept
    return ranked[0]


def still_prompt_for_concept(concept: str, scene: Scene) -> str:
    base = AI_STILL_PROMPTS.get(
        concept,
        (
            "Restrained documentary photograph of a Quebec industrial maple-syrup warehouse, "
            "natural light, anonymous figures only."
        ),
    )
    extra = str(scene.metadata.get("visual_environment") or scene.visual_intent or "")[:80]
    return (
        f"{base} Context: {extra}. Realistic documentary photography, natural lighting, "
        "credible materials, restrained composition, period-appropriate 2011-2012 Quebec. "
        "No readable fake text, no infographic styling, no UI, no diagram, no split panel, "
        "no labels, no fake documents, no invented likeness of a named person."
    )


@dataclass
class ReplacementItem:
    unit_id: str
    scene_ids: list[str]
    old_strategy: str
    concept: str
    source_type: str
    query: str = ""
    reuse_path: str | None = None
    sequence_paths: list[str] = field(default_factory=list)
    estimated_image_calls: int = 0
    duration: float = 0.0


@dataclass
class ReplacementReport:
    bad_units: list[ReplacementItem]
    existing_stock: int = 0
    new_stock: int = 0
    archive: int = 0
    reuse_photo: int = 0
    ai_stills: int = 0
    image_calls: int = 0
    affected_scenes: int = 0
    estimated_cost_usd: float = 0.0
    grouping_ok: bool = True
    notes: list[str] = field(default_factory=list)
