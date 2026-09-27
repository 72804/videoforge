from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from docprod.product.episode import (
    EpisodeBrief,
    EpisodeProductionPlan,
    EpisodeShotPlan,
    LocationBible,
    ShotProductionLine,
    ShotRequirement,
)
from docprod.product.friend_group import FriendGroupStorySpec, SceneBeatSpec
from docprod.providers.pricing import (
    ELEVEN_SFX_USD_PER_MINUTE,
    ELEVEN_V3_USD_PER_1K_CHARS,
    LYRIA_35_USD_PER_SONG,
    estimated_image_migration_usd,
)
from docprod.quality.catalog import get_model
from docprod.quality.enums import ModelReadiness, QualityProfile, SceneProductionClass
from docprod.quality.profiles import policy_for
from docprod.quality.registry import auto_route_allowed
from docprod.quality.router import estimate_model_cost, fallback_chain, preferred_video_model

PRODUCTION_DIRECTOR_STAGE = "PRODUCTION_DIRECTOR"

_EVENT_FAMILIES: tuple[tuple[str, str], ...] = (
    ("consume", r"tüket|bitmiş|boştur|yuva"),
    ("bill", r"hesap|fiş|fatura"),
    ("gather", r"eğil|yaklaş"),
    ("exit", r"sıyrıl|çıkar|kaç|dışarı"),
    ("notice", r"görür|fark|bakar|bakış"),
    ("slide", r"kaydır|uzat|işaret"),
    ("pay", r"okut|öder|kart|pos"),
    ("call", r"\barar\b|telefon"),
    ("bite", r"ısır|donut"),
)

_PROP_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("receipt", ("fiş", "hesap")),
    ("premium donut box", ("kutu", "kutunun", "kutular", "özel kutu")),
    ("water bottle", ("su şişe", "su şişesi")),
    ("POS", ("pos", "kart")),
    ("phone", ("telefon", "mesaj", "arar")),
    ("last donut", ("son donut", "son yuva", "donut")),
)

_LOCAL_MODELS = {"local-camera", "local-title", "narration-over-image"}
_TERMINAL = tuple(".!?…\"”'")


def fold_character_id(name: str) -> str:
    raw = unicodedata.normalize("NFKD", name or "")
    mapped = (
        raw.replace("ı", "i")
        .replace("İ", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    ascii_only = "".join(ch for ch in mapped if ch.isascii())
    return re.sub(r"[^a-z0-9]+", "", ascii_only.casefold())


def unique_keep(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        token = (item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def unique_ids(values: list[str]) -> list[str]:
    return unique_keep([fold_character_id(item) for item in values if item])


def incomplete_generated_text(text: str) -> bool:
    blob = (text or "").strip()
    if not blob:
        return False
    if re.search(r"\b(?:da|de|ve|ile|ki)\s*$", blob, re.I) and not blob.endswith(_TERMINAL):
        return True
    return False


def model_status_label(model_id: str) -> str:
    if model_id in _LOCAL_MODELS:
        return ModelReadiness.ADAPTER_IMPLEMENTED.value.upper()
    spec = get_model(model_id)
    if spec is None:
        return "UNKNOWN"
    return spec.readiness.name


def first_executable(chain: list[str]) -> str:
    for model_id in chain:
        if auto_route_allowed(model_id):
            if model_status_label(model_id) == ModelReadiness.CATALOG_ONLY.name:
                continue
            return model_id
    return "local-camera"


def split_action_units(action: str) -> list[str]:
    blob = re.sub(r"\s+", " ", (action or "").strip())
    if not blob:
        return []
    parts = [
        item.strip().rstrip(";").strip()
        for item in re.split(r"(?<=[.!?])\s+|(?<=;)\s+", blob)
        if item.strip().rstrip(";").strip()
    ]
    units: list[str] = []
    for part in parts:
        families = [name for name, pattern in _EVENT_FAMILIES if re.search(pattern, part, re.I)]
        if len(families) >= 3:
            clauses = [item.strip() for item in re.split(r",\s+", part) if item.strip()]
            units.extend(clauses if len(clauses) > 1 else [part])
        else:
            units.append(part)
    merged: list[str] = []
    for unit in units:
        if merged and len(unit) < 28 and not re.search(
            r"sıyrıl|çıkar|görür|kaydır|okut|ısır", unit, re.I
        ):
            merged[-1] = f"{merged[-1]} {unit}".strip()
        else:
            merged.append(unit)
    return merged or [blob]


def _cast_index(names: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for name in names:
        folded = fold_character_id(name)
        if folded:
            index[folded] = folded
            index[name.casefold()] = folded
    return index


def mentioned_cast(text: str, cast_names: list[str]) -> list[str]:
    index = _cast_index(cast_names)
    found: list[str] = []
    lower = text or ""
    for name in sorted(cast_names, key=len, reverse=True):
        folded = fold_character_id(name)
        if folded in found:
            continue
        if re.search(rf"\b{re.escape(name)}\b", lower, re.I):
            found.append(folded)
            continue
        if folded and re.search(rf"\b{re.escape(folded)}\b", fold_character_id(lower)):
            found.append(folded)
    extras = []
    for token in ("hg", "erni", "musti"):
        if token in index and re.search(rf"\b{token}\b", lower, re.I) and token not in found:
            extras.append(token)
    return unique_ids(found + extras)


def props_in_text(text: str) -> list[str]:
    blob = (text or "").casefold()
    found: list[str] = []
    for prop, keys in _PROP_KEYWORDS:
        if any(key in blob for key in keys) and prop not in found:
            found.append(prop)
    return found


def phone_overlay_copy(on_screen_text: Any) -> list[str]:
    if not isinstance(on_screen_text, dict):
        return []
    lines: list[str] = []
    shared = on_screen_text.get("shared_message")
    if shared:
        lines.append(str(shared))
    for item in list(on_screen_text.get("private_messages") or []):
        if not isinstance(item, dict):
            continue
        recipient = str(item.get("recipient") or "").strip()
        body = str(item.get("text") or "").strip()
        if recipient or body:
            lines.append(f"{recipient}: {body}".strip(": "))
    return lines


def classify_coverage(
    action: str,
    *,
    dialogue: list[dict[str, Any]],
    on_screen_text: Any,
    scene_location: str,
    index_in_scene: int,
    scene_shot_count: int,
) -> tuple[str, SceneProductionClass]:
    blob = f"{action} {scene_location}".casefold()
    if phone_overlay_copy(on_screen_text) or "mesaj" in blob:
        return "insert", SceneProductionClass.POST_PRODUCTION_MOTION_GRAPHICS
    if re.search(r"dış|bankta|bank |outside|exterior", blob) and "ısır" in blob:
        return "payoff", SceneProductionClass.HERO_CINEMATIC
    if re.search(r"dış|bankta|outside|exterior", blob):
        return "wide", SceneProductionClass.HERO_CINEMATIC
    if re.search(r"sıyrıl|çıkar|kaç", blob):
        return "wide", SceneProductionClass.CINEMATIC_MOTION
    if re.search(r"herkes|masa geneli|grup masası", blob) and not dialogue:
        return "wide", SceneProductionClass.MULTI_REFERENCE_SCENE
    if re.search(r"fiş|hesap|kart|pos|kapağını|yuva|kutu detay", blob) and len(action) < 140:
        return "prop_insert", SceneProductionClass.STATIC_KEYFRAME
    if re.search(r"bakış|bakar|yaslanır|sırıt|gülümse|fark|görür", blob) and not dialogue:
        return "reaction", SceneProductionClass.REACTION_SHOT
    if index_in_scene == 0 and scene_shot_count <= 2 and "masa" in blob:
        return "establishing", SceneProductionClass.ESTABLISHING_SHOT
    if dialogue:
        if re.search(r"omz|arkasından|eğilir", blob):
            return "over-the-shoulder", SceneProductionClass.DIALOGUE_COVERAGE
        if len(dialogue) == 1:
            return "medium", SceneProductionClass.REACTION_SHOT
        return "two-shot", SceneProductionClass.DIALOGUE_COVERAGE
    if re.search(r"herkes|masa geneli|grup", blob) or len(action) > 80:
        return "wide", SceneProductionClass.MULTI_REFERENCE_SCENE
    return "medium", SceneProductionClass.SIMPLE_MOTION


def _weight_for(coverage: str, action: str, dialogue: list[dict[str, Any]]) -> float:
    chars = sum(len(str(item.get("line") or "")) for item in dialogue)
    base = {
        "establishing": 2.2,
        "insert": 1.6,
        "prop_insert": 1.8,
        "reaction": 2.4,
        "over-the-shoulder": 3.2,
        "two-shot": 4.0,
        "medium": 3.4,
        "wide": 3.0,
        "cutaway": 1.7,
        "payoff": 5.6,
    }.get(coverage, 3.0)
    if coverage == "payoff":
        return base
    folded = action.casefold()
    if "mesaj" in folded:
        return max(base, 4.2)
    if dialogue:
        return min(6.2, 2.0 + 0.045 * chars)
    return base


def scale_durations(weights: list[float], target: tuple[float, float]) -> list[float]:
    lo, hi = target
    raw = sum(weights) or 1.0
    mid = min(hi, max(lo, raw if lo <= raw <= hi else (lo + hi) / 2))
    scaled = [max(1.0, round(weight / raw * mid, 1)) for weight in weights]
    drift = mid - sum(scaled)
    if scaled:
        scaled[-1] = round(max(1.0, scaled[-1] + drift), 1)
    total = sum(scaled)
    if total > hi and scaled:
        factor = hi / total
        scaled = [max(1.0, round(item * factor, 1)) for item in scaled]
        scaled[-1] = round(max(1.0, scaled[-1] + (hi - sum(scaled))), 1)
    if total < lo and scaled:
        scaled[-1] = round(scaled[-1] + (lo - total), 1)
    return scaled


def location_slot_for(scene_location: str, action: str) -> str:
    blob = f"{scene_location} {action}".casefold()
    if re.search(r"dış|bank|outside|exterior", blob):
        return "exterior_bench"
    return "interior_table"


def spatial_layout_for(location: LocationBible) -> dict[str, str]:
    layout = dict(location.spatial_layout)
    layout.setdefault("table", location.tables or "Same occupied group table.")
    layout.setdefault("counter", location.counter or "Counter behind the table.")
    layout.setdefault("window", location.windows or "Street-facing window wall.")
    layout.setdefault("door", location.entrance or "Entrance behind the table sightline.")
    layout.setdefault("exterior_bench", location.exterior or "Bench outside the same window.")
    layout.setdefault("lighting", location.lighting or "Warm interior, cooler exterior.")
    layout.setdefault("time_of_day", location.time_of_day or "evening")
    return layout


def locked_ref_for(character_id: str, refs: list[dict[str, object]]) -> str:
    wanted = fold_character_id(character_id)
    for row in refs:
        slug = fold_character_id(str(row.get("slug") or row.get("name") or ""))
        if slug != wanted:
            continue
        path = str(row.get("resolved_path") or "")
        return path or f"ref_{wanted}.jpg"
    return f"ref_{wanted}.jpg" if wanted else ""


def synthesize_final_story(payload: dict[str, Any], brief: EpisodeBrief) -> str:
    explicit = str(payload.get("final_story") or payload.get("synopsis") or "").strip()
    sentences: list[str] = []
    for scene in list(payload.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        for shot in list(scene.get("shots") or []):
            if not isinstance(shot, dict):
                continue
            action = str(shot.get("action") or "").strip()
            if action:
                sentences.append(action)
            for item in list(shot.get("dialogue") or []):
                if not isinstance(item, dict):
                    continue
                line = str(item.get("line") or "").strip()
                speaker = str(item.get("character") or "").strip()
                if line and speaker and len(sentences) < 14:
                    sentences.append(f'{speaker}: "{line}"')
    assembled = " ".join(sentences).strip()
    story = explicit if explicit and explicit != brief.premise.strip() else assembled
    if not story:
        story = brief.premise
    if incomplete_generated_text(story) and assembled and not incomplete_generated_text(assembled):
        story = assembled
    return story


def evaluate_role_coverage(
    spec: FriendGroupStorySpec,
    role_hints: dict[str, str],
) -> dict[str, str]:
    spoken = {fold_character_id(line.speaker_character_id) for line in spec.dialogue_lines}
    visuals = " ".join(beat.visual for beat in spec.scene_beats).casefold()
    out: dict[str, str] = {}
    for name, hint in role_hints.items():
        cid = fold_character_id(name)
        present = cid in spoken or name.casefold() in visuals or cid in visuals
        out[cid or name] = "expressed" if present else f"under-expressed:{hint}"
    return out


def _ideal_for(klass: SceneProductionClass, profile: QualityProfile) -> tuple[str, str]:
    if klass is SceneProductionClass.POST_PRODUCTION_MOTION_GRAPHICS:
        return "local-title", model_status_label("local-title")
    if klass is SceneProductionClass.STATIC_KEYFRAME:
        policy = policy_for(profile)
        return policy.timeline_image_model, model_status_label(policy.timeline_image_model)
    if klass is SceneProductionClass.MULTI_REFERENCE_SCENE:
        return "seedance-2.5-reference-to-video", model_status_label(
            "seedance-2.5-reference-to-video"
        )
    model = preferred_video_model(klass, profile)
    return model, model_status_label(model)


def route_shot(
    klass: SceneProductionClass,
    profile: QualityProfile,
    *,
    overlay: bool,
) -> tuple[str, str, str, list[str], str]:
    ideal, ideal_status = _ideal_for(klass, profile)
    chain = fallback_chain(klass, profile)
    if overlay:
        executable = "local-title"
        plate = first_executable(
            fallback_chain(SceneProductionClass.MULTI_REFERENCE_SCENE, profile)
        )
        gfx_chain = ["local-title", "higgsfield-motion-designer"]
        return ideal, ideal_status, executable, gfx_chain, plate
    executable = first_executable([ideal, *chain])
    if not auto_route_allowed(executable) or model_status_label(executable) == (
        ModelReadiness.CATALOG_ONLY.name
    ):
        executable = first_executable(chain)
    cleaned = []
    for item in [executable, *chain, "local-camera"]:
        if item not in cleaned:
            cleaned.append(item)
    return ideal, ideal_status, executable, cleaned, ""


@dataclass
class DirectedEpisode:
    spec: FriendGroupStorySpec
    shot_plan: EpisodeShotPlan
    old_shot_count: int


def _parent_dialogue(
    shot: dict[str, Any],
    units: list[str],
    unit_index: int,
) -> list[dict[str, Any]]:
    dialogue = [item for item in list(shot.get("dialogue") or []) if isinstance(item, dict)]
    if not dialogue:
        return []
    if len(units) == 1:
        return dialogue
    unit = units[unit_index]
    matched = [
        item
        for item in dialogue
        if fold_character_id(str(item.get("character") or "")) in mentioned_cast(unit, [
            str(item.get("character") or "")
        ])
        or fold_character_id(str(item.get("character") or "")) in fold_character_id(unit)
    ]
    if matched and unit_index < len(units) - 1:
        return matched
    if unit_index == len(units) - 1:
        return dialogue
    return []


def _donut_notes(shots: list[ShotRequirement]) -> None:
    payoff = next(
        (item for item in reversed(shots) if "last donut" in item.props or "ısır" in item.action),
        None,
    )
    if payoff is None:
        return
    for item in shots:
        if item.shot_id == payoff.shot_id:
            continue
        empty = "boştur" in item.action.casefold() or "tüketilmiştir" in item.action.casefold()
        if empty:
            item.prop_notes = (
                "Box cavity can read empty only after the last donut left with the "
                "character who already exited; do not show a finished empty box before that exit."
            )
            if "tüketilmiştir" in item.action.casefold() and "last donut" not in item.prop_notes:
                item.action = (
                    item.action.rstrip(".")
                    + "; remaining donuts look gone, last donut is not shown on the table."
                )


def direct_friend_group_episode(
    payload: dict[str, Any],
    spec: FriendGroupStorySpec,
    brief: EpisodeBrief,
    location: LocationBible,
    *,
    locked_refs: list[dict[str, object]] | None = None,
    profile: QualityProfile = QualityProfile.PREMIUM,
    role_hints: dict[str, str] | None = None,
) -> DirectedEpisode:
    refs = locked_refs or []
    cast_names = list(spec.cast or payload.get("cast") or brief.cast_names)
    layout = spatial_layout_for(location)
    location.spatial_layout = layout
    drafts: list[dict[str, Any]] = []
    old_count = 0
    for scene in list(payload.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or "")
        scene_location = str(scene.get("location") or "")
        raw_shots = [item for item in list(scene.get("shots") or []) if isinstance(item, dict)]
        old_count += len(raw_shots)
        for raw in raw_shots:
            action = str(raw.get("action") or "").strip()
            if incomplete_generated_text(action):
                raise ValueError(f"incomplete shot action in {raw.get('shot_id')}: {action[-40:]}")
            units = split_action_units(action)
            overlay_lines = phone_overlay_copy(raw.get("on_screen_text"))
            for index, unit in enumerate(units):
                dialogue = _parent_dialogue(raw, units, index)
                coverage, klass = classify_coverage(
                    unit,
                    dialogue=dialogue,
                    on_screen_text=raw.get("on_screen_text") if index == 0 else None,
                    scene_location=scene_location,
                    index_in_scene=index,
                    scene_shot_count=len(units),
                )
                if overlay_lines and index == 0:
                    coverage = "insert"
                    klass = SceneProductionClass.POST_PRODUCTION_MOTION_GRAPHICS
                speaking = unique_ids(
                    [str(item.get("character") or "") for item in dialogue]
                )
                visible = mentioned_cast(unit, cast_names)
                call = re.search(r"(\S+)\s+telefonundan\s+(\S+)", unit, re.I)
                if call:
                    callers = mentioned_cast(call.group(1), cast_names)
                    callees = mentioned_cast(call.group(2), cast_names)
                    if callers:
                        visible = callers
                    speaking = unique_ids(speaking + callees)
                if coverage == "payoff" or location_slot_for(scene_location, unit) == (
                    "exterior_bench"
                ):
                    offscreen = [item for item in speaking if item not in visible]
                else:
                    offscreen = [item for item in speaking if item not in visible]
                    if overlay_lines:
                        visible = unique_ids(visible + mentioned_cast(action, cast_names))
                drafts.append(
                    {
                        "parent_id": str(raw.get("shot_id") or f"{scene_id}_{index + 1:02d}"),
                        "scene_id": scene_id,
                        "unit": unit,
                        "framing": str(raw.get("framing") or ""),
                        "coverage": coverage,
                        "klass": klass,
                        "dialogue": dialogue,
                        "speaking": speaking,
                        "visible": visible,
                        "offscreen": offscreen,
                        "overlay": overlay_lines if index == 0 else [],
                        "location": scene_location,
                    }
                )
    if not drafts:
        raise ValueError("production director received no shots")
    weights = [
        _weight_for(item["coverage"], item["unit"], item["dialogue"]) for item in drafts
    ]
    durations = scale_durations(weights, brief.target_duration_seconds)
    shots: list[ShotRequirement] = []
    used_ids: dict[str, int] = {}
    for item, duration in zip(drafts, durations, strict=True):
        parent = item["parent_id"] or item["scene_id"]
        used_ids[parent] = used_ids.get(parent, 0) + 1
        shot_id = parent if used_ids[parent] == 1 and len(
            [row for row in drafts if row["parent_id"] == parent]
        ) == 1 else f"{parent}_{used_ids[parent]:02d}"
        overlay = bool(item["overlay"])
        klass = item["klass"]
        if (
            duration <= 2.5
            and klass
            in {
                SceneProductionClass.SIMPLE_MOTION,
                SceneProductionClass.ESTABLISHING_SHOT,
            }
            and not item["dialogue"]
            and not overlay
        ):
            klass = SceneProductionClass.STATIC_KEYFRAME
        ideal, ideal_status, executable, chain, plate = route_shot(
            klass, profile, overlay=overlay
        )
        visible = unique_ids(item["visible"])
        speaking = unique_ids(item["speaking"])
        offscreen = unique_ids(item["offscreen"])
        if item["coverage"] == "payoff":
            offscreen = unique_ids([cid for cid in speaking if cid not in visible])
        locked = [locked_ref_for(cid, refs) for cid in visible]
        props = props_in_text(item["unit"])
        if overlay:
            props = unique_keep(props + ["phone"])
        voice = bool(speaking)
        shots.append(
            ShotRequirement(
                shot_id=shot_id,
                scene_id=item["scene_id"],
                production_class=klass.value,
                cast_refs=visible,
                visible_cast=visible,
                speaking_cast=speaking,
                offscreen_speakers=offscreen,
                action=item["unit"],
                framing=item["framing"] or item["coverage"],
                coverage=item["coverage"],
                duration_seconds=duration,
                props=props,
                overlay_kind="phone_ui" if overlay else "",
                overlay_copy=list(item["overlay"]),
                preferred_model=executable,
                fallback_model=chain[1] if len(chain) > 1 else "local-camera",
                implementation_status=model_status_label(executable),
                ideal_model=ideal,
                ideal_status=ideal_status,
                executable_model=executable,
                fallback_chain=chain,
                plate_model=plate,
                estimated_usd=estimate_model_cost(executable, seconds=duration)[0],
                voice_required=voice,
                sfx_required=True,
                music_required=item["coverage"] == "payoff",
                motion_graphics_required=overlay,
                location_slot=location_slot_for(item["location"], item["unit"]),
                locked_refs=[path for path in locked if path],
                identity_required=bool(visible),
            )
        )
    _donut_notes(shots)
    for shot in shots:
        if incomplete_generated_text(shot.action) and re.search(
            r"\b(?:da|de|ve|ile|ki)\s*$", shot.action.strip(), re.I
        ):
            raise ValueError(f"director produced truncated action: {shot.shot_id}")
        if shot.executable_model and not auto_route_allowed(shot.executable_model):
            raise ValueError(f"catalog-only executable {shot.executable_model}")
        if model_status_label(shot.executable_model) == ModelReadiness.CATALOG_ONLY.name:
            raise ValueError(f"catalog-only executable {shot.executable_model}")
        if shot.visible_cast and "n/a" in shot.visible_cast:
            raise ValueError("visible cast cannot be n/a")
        if len(shot.visible_cast) != len(set(shot.visible_cast)):
            raise ValueError(f"duplicate visible cast on {shot.shot_id}")
    total = round(sum(shot.duration_seconds for shot in shots), 1)
    beats = _beats_from_shots(spec, shots, payload, brief)
    directed_spec = spec.model_copy(
        update={
            "final_story": spec.final_story or synthesize_final_story(payload, brief),
            "scene_beats": beats,
            "estimated_duration": total,
        }
    )
    roles = evaluate_role_coverage(
        directed_spec, role_hints or {name: "cast" for name in cast_names}
    )
    revisions: list[str] = []
    under = [key for key, value in roles.items() if value.startswith("under-expressed")]
    if under:
        revisions.append(
            "role coverage flags: " + ", ".join(under) + "; no paid story rewrite applied"
        )
    plan = EpisodeShotPlan(
        shots=shots,
        engine_owned=True,
        total_duration_seconds=total,
        spatial_layout=layout,
        role_coverage=roles,
        revisions=revisions,
    )
    return DirectedEpisode(spec=directed_spec, shot_plan=plan, old_shot_count=old_count)


def _beats_from_shots(
    spec: FriendGroupStorySpec,
    shots: list[ShotRequirement],
    payload: dict[str, Any],
    _brief: EpisodeBrief,
) -> list[SceneBeatSpec]:
    by_scene: dict[str, list[ShotRequirement]] = {}
    for shot in shots:
        by_scene.setdefault(shot.scene_id, []).append(shot)
    beats: list[SceneBeatSpec] = []
    for index, scene in enumerate(list(payload.get("scenes") or [])):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or f"S{index + 1}")
        group = by_scene.get(scene_id, [])
        visual = " ".join(item.action for item in group)
        if incomplete_generated_text(visual):
            raise ValueError(f"scene {scene_id} visual truncated during reconstruction")
        present = unique_ids([cid for item in group for cid in item.visible_cast])
        hook = spec.cold_open_hook if index == 0 else ""
        beats.append(
            SceneBeatSpec(
                scene_id=scene_id,
                order_index=index,
                hook=hook,
                visual=visual,
                intent=str(scene.get("time") or ""),
                character_ids=present,
                duration_seconds=round(sum(item.duration_seconds for item in group), 1),
            )
        )
    if not beats:
        return spec.scene_beats
    return beats


def estimate_voice_usd(spec: FriendGroupStorySpec, profile: QualityProfile) -> float:
    chars = sum(len(line.text) for line in spec.dialogue_lines)
    model = policy_for(profile).tts_model
    if model == "eleven-v3":
        return round((chars / 1000.0) * ELEVEN_V3_USD_PER_1K_CHARS, 4)
    cost, _ = estimate_model_cost(model, characters=float(chars))
    return round(cost or (chars / 1_000_000) * 0.60, 4)


def estimate_audio_usd(total_seconds: float, profile: QualityProfile) -> tuple[float, float]:
    policy = policy_for(profile)
    sfx = 0.0
    if policy.sfx_model == "eleven-sfx":
        sfx = round((total_seconds / 60.0) * ELEVEN_SFX_USD_PER_MINUTE, 4)
    music = LYRIA_35_USD_PER_SONG if policy.music_model.startswith("lyria") else 0.0
    return sfx, music


def build_production_plan(
    directed: DirectedEpisode,
    profile: QualityProfile,
) -> EpisodeProductionPlan:
    routed = _reroute_existing(directed, profile)
    image_calls = 0
    video_usd = 0.0
    lines: list[ShotProductionLine] = []
    for shot in routed.shot_plan.shots:
        still = shot.production_class in {
            SceneProductionClass.STATIC_KEYFRAME.value,
            SceneProductionClass.POST_PRODUCTION_MOTION_GRAPHICS.value,
            SceneProductionClass.TITLE_CARD.value,
            SceneProductionClass.STATIC_CINEMATIC.value,
        }
        if still or shot.coverage in {"prop_insert", "insert"}:
            image_calls += 1
        video_model = shot.plate_model or shot.executable_model
        if shot.motion_graphics_required:
            video_model = shot.plate_model or first_executable(
                fallback_chain(SceneProductionClass.MULTI_REFERENCE_SCENE, profile)
            )
        if video_model not in _LOCAL_MODELS and not shot.motion_graphics_required:
            cost, _ = estimate_model_cost(video_model, seconds=shot.duration_seconds)
            video_usd += cost or 0.0
        elif shot.motion_graphics_required and video_model not in _LOCAL_MODELS:
            cost, _ = estimate_model_cost(video_model, seconds=shot.duration_seconds)
            video_usd += cost or 0.0
        lines.append(
            ShotProductionLine(
                shot_id=shot.shot_id,
                duration_seconds=shot.duration_seconds,
                production_class=shot.production_class,
                visible_characters=shot.visible_cast,
                locked_refs=shot.locked_refs,
                ideal_model=shot.ideal_model,
                ideal_status=shot.ideal_status,
                executable_model=shot.executable_model,
                fallback_chain=shot.fallback_chain,
                estimated_media_usd=shot.estimated_usd,
                voice_required=shot.voice_required,
                sfx_required=shot.sfx_required,
                music_required=shot.music_required,
                motion_graphics_required=shot.motion_graphics_required,
                coverage=shot.coverage,
                props=shot.props,
            )
        )
    image_usd = estimated_image_migration_usd(image_calls) if image_calls else 0.0
    voice_usd = estimate_voice_usd(directed.spec, profile)
    sfx_usd, music_usd = estimate_audio_usd(routed.shot_plan.total_duration_seconds, profile)
    audio_usd = round(sfx_usd + music_usd, 4)
    expected = round(image_usd + video_usd + voice_usd + audio_usd, 4)
    reserved = round(expected * 1.25, 4)
    return EpisodeProductionPlan(
        quality_profile=profile.value,
        shots=lines,
        image_usd=image_usd,
        video_usd=round(video_usd, 4),
        voice_usd=voice_usd,
        audio_usd=audio_usd,
        expected_usd=expected,
        reserved_usd=reserved,
        notes=[
            "No media generated. Catalog-only models stay ideal-only.",
            f"image_stills={image_calls}",
        ],
    )


def _reroute_existing(directed: DirectedEpisode, profile: QualityProfile) -> DirectedEpisode:
    shots: list[ShotRequirement] = []
    for shot in directed.shot_plan.shots:
        klass = SceneProductionClass(shot.production_class)
        ideal, ideal_status, executable, chain, plate = route_shot(
            klass, profile, overlay=bool(shot.overlay_kind)
        )
        cost, _ = estimate_model_cost(
            plate or executable, seconds=shot.duration_seconds
        )
        shots.append(
            shot.model_copy(
                update={
                    "ideal_model": ideal,
                    "ideal_status": ideal_status,
                    "executable_model": executable,
                    "preferred_model": executable,
                    "fallback_chain": chain,
                    "fallback_model": chain[1] if len(chain) > 1 else "local-camera",
                    "implementation_status": model_status_label(executable),
                    "plate_model": plate,
                    "estimated_usd": cost,
                }
            )
        )
    plan = directed.shot_plan.model_copy(update={"shots": shots})
    return DirectedEpisode(
        spec=directed.spec,
        shot_plan=plan,
        old_shot_count=directed.old_shot_count,
    )


def production_plans_for_profiles(
    directed: DirectedEpisode,
) -> dict[str, EpisodeProductionPlan]:
    return {
        "balanced": build_production_plan(directed, QualityProfile.BALANCED),
        "premium": build_production_plan(directed, QualityProfile.PREMIUM),
        "max": build_production_plan(directed, QualityProfile.MAX_QUALITY),
    }


def format_production_review(
    *,
    brief: EpisodeBrief,
    spec: FriendGroupStorySpec,
    directed: DirectedEpisode,
    location: LocationBible,
    voices: list[str],
    refs: list[str],
    plans: dict[str, EpisodeProductionPlan],
    known_story_usd: float,
) -> str:
    shots = directed.shot_plan.shots
    dialogue = [
        f"- [{line.scene_id}] {line.speaker_character_id}: {line.text}"
        + (f" ({line.delivery})" if line.delivery else "")
        for line in spec.dialogue_lines
    ]
    shot_lines = []
    for shot in shots:
        visible = ",".join(shot.visible_cast) or "none"
        off = ",".join(shot.offscreen_speakers) or "none"
        speaking = ",".join(shot.speaking_cast) or "none"
        shot_lines.append(
            f"- {shot.shot_id} {shot.duration_seconds:.1f}s class={shot.production_class} "
            f"coverage={shot.coverage} visible={visible} speaking={speaking} "
            f"offscreen={off} props={','.join(shot.props) or 'none'} "
            f"slot={shot.location_slot} overlay={shot.overlay_kind or 'none'} "
            f"ideal={shot.ideal_model} ({shot.ideal_status}) "
            f"executable={shot.executable_model} "
            f"fallback={'>'.join(shot.fallback_chain)} | {shot.action}"
        )

    def _plan_block(title: str, plan: EpisodeProductionPlan) -> list[str]:
        return [
            f"## {title}",
            "",
            f"image_usd={plan.image_usd:.4f}",
            f"video_usd={plan.video_usd:.4f}",
            f"voice_usd={plan.voice_usd:.4f}",
            f"audio_usd={plan.audio_usd:.4f}",
            f"expected_usd={plan.expected_usd:.4f}",
            f"reserved_usd={plan.reserved_usd:.4f}",
            *[f"- {note}" for note in plan.notes],
            "",
        ]

    layout = directed.shot_plan.spatial_layout
    overlays = [shot for shot in shots if shot.motion_graphics_required]
    overlay_lines = [
        f"- {shot.shot_id} phone_ui: " + " | ".join(shot.overlay_copy)
        for shot in overlays
    ] or ["- none"]
    return "\n".join(
        [
            "# Episode production review",
            "",
            "Status: PRODUCTION PLAN ONLY. MEDIA NOT GENERATED.",
            "Stage: PRODUCTION_DIRECTOR (deterministic; no text/media provider calls).",
            f"story_usage_usd={known_story_usd:.5f}",
            f"old_shot_count={directed.old_shot_count}",
            f"new_shot_count={len(shots)}",
            f"total_duration={directed.shot_plan.total_duration_seconds:.1f}s",
            "",
            "## TITLE",
            "",
            spec.title,
            "",
            "## HOOK",
            "",
            spec.cold_open_hook,
            "",
            "## PREMISE",
            "",
            spec.premise,
            "",
            "## FINAL STORY",
            "",
            spec.final_story,
            "",
            f"Ending: {spec.ending}",
            "",
            "## DIALOGUE",
            "",
            *dialogue,
            "",
            "## REVISED SHOT PLAN",
            "",
            *shot_lines,
            "",
            "## VISIBLE/OFFSCREEN CAST",
            "",
            *[
                f"- {shot.shot_id}: visible={','.join(shot.visible_cast) or 'none'} "
                f"speaking={','.join(shot.speaking_cast) or 'none'} "
                f"offscreen={','.join(shot.offscreen_speakers) or 'none'}"
                for shot in shots
            ],
            "",
            "## SHOT DURATIONS",
            "",
            *[f"- {shot.shot_id}: {shot.duration_seconds:.1f}s" for shot in shots],
            "",
            "## MODEL REQUIREMENTS",
            "",
            "## IDEAL MODEL",
            "",
            *[f"- {shot.shot_id}: {shot.ideal_model} ({shot.ideal_status})" for shot in shots],
            "",
            "## EXECUTABLE MODEL",
            "",
            *[
                f"- {shot.shot_id}: {shot.executable_model} "
                f"({shot.implementation_status})"
                for shot in shots
            ],
            "",
            "## FALLBACK",
            "",
            *[f"- {shot.shot_id}: {' > '.join(shot.fallback_chain)}" for shot in shots],
            "",
            "## LOCATION CONTINUITY",
            "",
            f"name={location.name}",
            *[f"{key}={value}" for key, value in layout.items()],
            "",
            "## PROP CONTINUITY",
            "",
            *[
                f"- {shot.shot_id}: {', '.join(shot.props) or 'none'}"
                + (f" | {shot.prop_notes}" if shot.prop_notes else "")
                for shot in shots
            ],
            "",
            "## VOICE PLAN",
            "",
            *voices,
            "TTS not called.",
            "",
            "## MOTION GRAPHICS",
            "",
            *overlay_lines,
            "",
            *_plan_block("BALANCED COST", plans["balanced"]),
            *_plan_block("PREMIUM COST", plans["premium"]),
            *_plan_block("MAX COST", plans["max"]),
            "## VISUAL CONTINUITY",
            "",
            *refs,
            "",
            f"target={brief.target_duration_seconds[0]:.0f}–"
            f"{brief.target_duration_seconds[1]:.0f}s",
            "provider_http_calls=0",
            "READY FOR MEDIA GENERATION = no (awaiting budget approval)",
            "",
        ]
    ) + "\n"
