from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from docprod.config import Settings, get_settings
from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.canary_cost import reserve_image_usd, typical_image_usd
from docprod.product.episode import (
    AnimaticKeyframeSpec,
    AnimaticPlan,
    AnimaticShotEdit,
    AnimaticVoiceLine,
    EpisodeBrief,
    EpisodeShotPlan,
    LocationBible,
    ShotRequirement,
    VoiceAssignment,
)
from docprod.product.errors import ProductError
from docprod.product.friend_group import DialogueLineSpec, FriendGroupStorySpec
from docprod.product.production_director import fold_character_id, unique_ids, unique_keep
from docprod.providers.elevenlabs_tts import elevenlabs_tts_hash
from docprod.providers.image_config import ImageGenerationConfig
from docprod.providers.openai_image import image_request_hash
from docprod.providers.paid_cache import tts_cache_hash
from docprod.providers.pricing import ELEVEN_V3_USD_PER_1K_CHARS
from docprod.quality.catalog import get_model
from docprod.quality.enums import QualityProfile, SceneProductionClass
from docprod.quality.policy_select import OPENAI_STOCK_VOICES, image_model_for, tts_model_for
from docprod.quality.router import estimate_model_cost
from docprod.render.subtitles import ass_timestamp, burn_in_required, ffmpeg_subtitle_filter
from docprod.storage.hashing import file_sha256

ANIMATIC_PROVIDER_HARD_CAP_USD = 2.00
TURKISH_CHARS_PER_SEC = 13.0
VERTICAL_STILL_SIZE = "1024x1536"
FORBIDDEN_VIDEO_MODELS = (
    "runway-gen-4.5",
    "runway-act-two",
    "veo-3.1-lite-generate-preview",
    "veo-3.1-generate-preview",
    "seedance-2.5-reference-to-video",
    "kling-3.0-motion-control-pro",
    "higgsfield-genjutsu",
)
_VIDEO_UPGRADE_CLASSES = {
    SceneProductionClass.CINEMATIC_MOTION.value,
    SceneProductionClass.HERO_CINEMATIC.value,
    SceneProductionClass.MULTI_REFERENCE_SCENE.value,
    SceneProductionClass.DIALOGUE_COVERAGE.value,
    SceneProductionClass.DIALOGUE_SHOT.value,
    SceneProductionClass.REACTION_SHOT.value,
    SceneProductionClass.PERFORMANCE_SHOT.value,
}
_MOTION_CYCLE = (
    "slow_push_in",
    "slow_pull_out",
    "pan_left",
    "pan_right",
    "documentary_handheld",
    "crop_push",
)


class AnimaticImageClient(Protocol):
    def generate(self, keyframe: AnimaticKeyframeSpec, dest: Path) -> Path: ...


class AnimaticVoiceClient(Protocol):
    def synthesize(self, line: AnimaticVoiceLine, dest: Path) -> Path: ...


class AnimaticRenderer(Protocol):
    def render(self, plan: AnimaticPlan, dest: Path, *, work_dir: Path) -> Path: ...


def select_animatic_voice_backend(
    settings: Settings | None,
    profile: QualityProfile,
) -> str:
    cfg = settings or get_settings()
    wanted = tts_model_for(profile, dialogue=True)
    spec = get_model("eleven-v3")
    eleven_ok = (
        wanted == "eleven-v3"
        and spec is not None
        and spec.implemented
        and cfg.elevenlabs_key_configured()
    )
    if eleven_ok:
        return "eleven-v3"
    return "gpt-4o-mini-tts"


def animatic_render_dir(series_slug: str, episode_number: int, *, root: Path) -> Path:
    if series_slug == "birko":
        return (
            root
            / "projects/birko_kemal_drama_canary/artifacts/render"
            / f"episode_{episode_number}"
        )
    return root / "projects" / series_slug / "artifacts" / "render" / f"episode_{episode_number}"


def animatic_review_relative(series_slug: str, episode_number: int) -> str:
    if series_slug == "birko" and episode_number == 2:
        return (
            "projects/birko_kemal_drama_canary/artifacts/review/"
            "episode_2_animatic_review.md"
        )
    return (
        f"projects/{series_slug}/artifacts/review/"
        f"episode_{episode_number}_animatic_review.md"
    )


def _still_config(model: str) -> ImageGenerationConfig:
    return ImageGenerationConfig(
        provider="openai",
        model=model,
        size=VERTICAL_STILL_SIZE,
        quality="medium",
        output_format="jpeg",
    )


def _fingerprint_image(keyframe: AnimaticKeyframeSpec) -> str:
    ref_sha = ",".join(
        file_sha256(Path(path)) if Path(path).is_file() else "missing"
        for path in keyframe.reference_files
    )
    return image_request_hash(
        prompt=keyframe.prompt,
        config=_still_config(keyframe.model),
        seed=None,
        extra={
            "visible": ",".join(keyframe.visible_characters),
            "refs": ",".join(keyframe.reference_files),
            "ref_sha": ref_sha,
            "slot": keyframe.location_slot,
            "keyframe": keyframe.keyframe_id,
        },
    )


def _fingerprint_voice(line: AnimaticVoiceLine) -> str:
    if line.model == "eleven-v3":
        return elevenlabs_tts_hash(
            model=line.model,
            voice=line.voice_id,
            text=line.text,
            instructions=f"{line.emotion}|{line.delivery}",
            language="tr",
        )
    return tts_cache_hash(
        model=line.model,
        voice=line.voice_id,
        text=line.text,
        instructions=f"{line.emotion}|{line.delivery}",
        language="tr",
    )


def _prompt_for(
    *,
    role: str,
    action: str,
    location: LocationBible,
    slot: str,
    visible: list[str],
    props: list[str],
) -> str:
    layout = location.spatial_layout or {}
    cafe = (
        f"{location.name}. {location.interior_layout} {layout.get('table', location.tables)} "
        f"{layout.get('counter', location.counter)} {layout.get('window', location.windows)} "
        f"{layout.get('door', location.entrance)}. Lighting: {location.lighting}. "
        f"Time: {location.time_of_day}."
    )
    if slot == "exterior_bench":
        cafe = (
            f"{location.name} exterior. {location.exterior} "
            f"{layout.get('exterior_bench', '')}. Cooler evening light. "
            f"Same building as the interior window wall."
        )
    people = ", ".join(visible) if visible else "no prominent faces"
    prop_line = ", ".join(props) if props else "set dressing only"
    identity = (
        "Use attached labeled references only for face identity. "
        "Do not copy portrait backgrounds. 9:16 cinematic still."
        if visible
        else "Architecture/set still. Do not invent readable text or logos with fine print."
    )
    return (
        f"{identity} Continuity plate ({role}). Location: {cafe} Visible: {people}. "
        f"Props: {prop_line}. Beat: {action} No readable UI text. Vertical 9:16."
    )


def _ref_files_for(visible: list[str], locked_refs: list[dict[str, object]]) -> list[str]:
    wanted = set(visible)
    out: list[str] = []
    for row in locked_refs:
        slug = fold_character_id(str(row.get("slug") or row.get("name") or ""))
        path = str(row.get("resolved_path") or "")
        if slug in wanted and path:
            out.append(path)
    return out


def cluster_keyframes(
    shots: list[ShotRequirement],
    location: LocationBible,
    locked_refs: list[dict[str, object]],
    profile: QualityProfile,
) -> tuple[list[AnimaticKeyframeSpec], dict[str, str]]:
    """Map shots to a minimum set of stills. Exact (slot, cast) plates are reused."""
    keyframes: dict[str, AnimaticKeyframeSpec] = {}
    shot_to_kf: dict[str, str] = {}

    def add(spec: AnimaticKeyframeSpec) -> None:
        spec.request_fingerprint = _fingerprint_image(spec)
        keyframes[spec.keyframe_id] = spec

    for slot in unique_keep([shot.location_slot or "interior_table" for shot in shots]):
        slot_name = slot or "interior_table"
        model = image_model_for(profile, identity_critical=False)
        kf_id = f"kf_master_{slot_name}"
        add(
            AnimaticKeyframeSpec(
                keyframe_id=kf_id,
                role="location_master",
                location_slot=slot_name,
                visible_characters=[],
                reference_files=[],
                props=list(location.props),
                model=model,
                identity_critical=False,
                prompt=_prompt_for(
                    role="location_master",
                    action="establishing continuity of the same space",
                    location=location,
                    slot=slot_name,
                    visible=[],
                    props=list(location.props),
                ),
                generate=True,
                notes="Shared architecture plate. Crops/pans reuse this still.",
            )
        )

    plates: dict[tuple[str, tuple[str, ...]], str] = {}
    for shot in shots:
        slot = shot.location_slot or "interior_table"
        visible = tuple(unique_ids(shot.visible_cast))
        if shot.overlay_kind == "phone_ui" or shot.motion_graphics_required:
            plate_key = (slot, visible or ("phone_plate",))
            kf_id = "kf_phone_plate"
            if kf_id not in keyframes:
                model = image_model_for(profile, identity_critical=bool(visible))
                people = list(visible)
                add(
                    AnimaticKeyframeSpec(
                        keyframe_id=kf_id,
                        role="phone_plate",
                        location_slot=slot,
                        visible_characters=people,
                        reference_files=_ref_files_for(people, locked_refs),
                        props=["phone"],
                        model=model,
                        identity_critical=bool(people),
                        prompt=_prompt_for(
                            role="phone_plate",
                            action=(
                                "People looking at a phone; screen may be blank or out of "
                                "focus. Do not render message text."
                            ),
                            location=location,
                            slot=slot,
                            visible=people,
                            props=["phone"],
                        ),
                        generate=True,
                        notes="Readable messages are local overlays, not model text.",
                    )
                )
            shot_to_kf[shot.shot_id] = kf_id
            continue
        if shot.coverage in {"prop_insert", "insert"} and (
            not visible or shot.production_class == SceneProductionClass.STATIC_KEYFRAME.value
        ):
            prop = (shot.props[0] if shot.props else "insert").replace(" ", "_")
            kf_id = f"kf_insert_{fold_character_id(prop) or 'detail'}"
            if kf_id not in keyframes:
                model = image_model_for(profile, identity_critical=False)
                add(
                    AnimaticKeyframeSpec(
                        keyframe_id=kf_id,
                        role="prop_insert",
                        location_slot=slot,
                        visible_characters=[],
                        reference_files=[],
                        props=list(shot.props),
                        model=model,
                        identity_critical=False,
                        prompt=_prompt_for(
                            role="prop_insert",
                            action=shot.action,
                            location=location,
                            slot=slot,
                            visible=[],
                            props=list(shot.props),
                        ),
                        generate=True,
                        notes="Close object still; reuse across matching inserts.",
                    )
                )
            shot_to_kf[shot.shot_id] = kf_id
            continue
        if not visible:
            shot_to_kf[shot.shot_id] = f"kf_master_{slot}"
            continue
        plate_key = (slot, visible)
        existing = plates.get(plate_key)
        if existing:
            shot_to_kf[shot.shot_id] = existing
            continue
        people = list(visible)
        kf_id = f"kf_{slot}_{'-'.join(people)}"
        if shot.coverage == "payoff" or slot == "exterior_bench":
            kf_id = f"kf_payoff_{'-'.join(people)}"
        model = image_model_for(profile, identity_critical=True)
        add(
            AnimaticKeyframeSpec(
                keyframe_id=kf_id,
                role="identity_plate",
                location_slot=slot,
                visible_characters=people,
                reference_files=_ref_files_for(people, locked_refs),
                props=list(shot.props),
                model=model,
                identity_critical=True,
                prompt=_prompt_for(
                    role="identity_plate",
                    action=shot.action,
                    location=location,
                    slot=slot,
                    visible=people,
                    props=list(shot.props),
                ),
                generate=True,
                notes="Locked refs only; do not regenerate canonical portraits.",
            )
        )
        plates[plate_key] = kf_id
        shot_to_kf[shot.shot_id] = kf_id
    return list(keyframes.values()), shot_to_kf


def _speech_seconds(text: str) -> float:
    chars = len(text.strip())
    if chars <= 0:
        return 0.0
    return round(max(0.7, chars / TURKISH_CHARS_PER_SEC), 2)


def _assign_lines_to_shots(
    spec: FriendGroupStorySpec,
    shots: list[ShotRequirement],
) -> dict[str, list[DialogueLineSpec]]:
    by_scene: dict[str, list[ShotRequirement]] = {}
    for shot in shots:
        by_scene.setdefault(shot.scene_id, []).append(shot)
    assigned: dict[str, list[DialogueLineSpec]] = {shot.shot_id: [] for shot in shots}
    for line in spec.dialogue_lines:
        speaker = fold_character_id(line.speaker_character_id)
        scene_shots = by_scene.get(line.scene_id, [])
        match = next(
            (
                shot
                for shot in scene_shots
                if speaker in shot.speaking_cast or speaker in shot.offscreen_speakers
            ),
            None,
        )
        if match is None and scene_shots:
            match = scene_shots[-1]
        if match is not None:
            assigned[match.shot_id].append(line)
    return assigned


def _motion_for(shot: ShotRequirement, reuse_index: int) -> str:
    if shot.overlay_kind:
        return "freeze_overlay"
    if shot.coverage in {"prop_insert", "insert"}:
        return "insert_hold"
    if shot.coverage == "payoff":
        return "slow_push_in"
    if shot.coverage == "reaction":
        return "crop_push"
    return _MOTION_CYCLE[reuse_index % len(_MOTION_CYCLE)]


def _sfx_for(shot: ShotRequirement) -> list[str]:
    cues: list[str] = []
    blob = f"{shot.action} {' '.join(shot.props)}".casefold()
    if "fiş" in blob or "receipt" in blob:
        cues.append("local_paper")
    if shot.overlay_kind == "phone_ui" or "telefon" in blob or "mesaj" in blob:
        cues.append("local_ui_blip")
    if "pos" in blob or "kart" in blob:
        cues.append("local_pos_beep")
    if "sıyrıl" in blob or "çıkar" in blob or "dış" in blob:
        cues.append("local_door")
    return cues


def _upgrade_for(shot: ShotRequirement) -> tuple[str, str, float | None]:
    if shot.production_class in _VIDEO_UPGRADE_CLASSES and not shot.overlay_kind:
        cost, _ = estimate_model_cost(
            shot.executable_model or "runway-gen-4.5",
            seconds=max(2.0, shot.duration_seconds),
        )
        reason = (
            f"{shot.production_class}/{shot.coverage} needs real motion after the animatic"
        )
        return "VIDEO_UPGRADE_RECOMMENDED", reason, cost
    return (
        "LOCAL_MOTION_SUFFICIENT",
        "Still + local motion/overlay is enough to judge the beat",
        None,
    )


def scale_edit_to_window(
    durations: list[float],
    speech: list[float],
    window: tuple[float, float],
) -> list[float]:
    lo, hi = window
    edited = [max(d, s) for d, s in zip(durations, speech, strict=True)]
    total = sum(edited)
    if lo <= total <= hi:
        return [round(item, 1) for item in edited]
    if total > hi:
        slack = [max(0.0, item - speech_item) for item, speech_item in zip(edited, speech)]
        extra = total - hi
        slack_sum = sum(slack) or 1.0
        out = []
        for item, speech_item, gap in zip(edited, speech, slack, strict=True):
            cut = extra * (gap / slack_sum)
            out.append(round(max(speech_item, item - cut, 1.0), 1))
        drift = hi - sum(out)
        if out:
            out[-1] = round(max(speech[-1], out[-1] + drift), 1)
        return out
    if edited:
        edited[-1] = round(edited[-1] + (lo - total), 1)
    return [round(item, 1) for item in edited]


def apply_animatic_cap(plan: AnimaticPlan) -> AnimaticPlan:
    ok = plan.reserved_usd - 1e-9 <= plan.hard_cap_usd
    notes = list(plan.notes)
    if not ok:
        notes.append(
            f"STOP BEFORE HTTP: reserved ${plan.reserved_usd:.4f} exceeds "
            f"ANIMATIC_PROVIDER_HARD_CAP_USD ${plan.hard_cap_usd:.2f}"
        )
    return plan.model_copy(update={"cap_ok": ok, "notes": notes})


def build_animatic_plan(
    *,
    brief: EpisodeBrief,
    spec: FriendGroupStorySpec,
    shot_plan: EpisodeShotPlan,
    location: LocationBible,
    locked_refs: list[dict[str, object]],
    voices: list[VoiceAssignment],
    settings: Settings | None = None,
    profile: QualityProfile = QualityProfile.PREMIUM,
) -> AnimaticPlan:
    backend = select_animatic_voice_backend(settings, profile)
    shots = list(shot_plan.shots)
    keyframes, shot_to_kf = cluster_keyframes(shots, location, locked_refs, profile)
    line_map = _assign_lines_to_shots(spec, shots)
    uses: dict[str, int] = {}
    edits: list[AnimaticShotEdit] = []
    planned: list[float] = []
    speech_list: list[float] = []
    voice_lines: list[AnimaticVoiceLine] = []
    voice_by_name = {
        fold_character_id(item.character_name): item for item in voices
    }
    for shot in shots:
        kf_id = shot_to_kf[shot.shot_id]
        uses[kf_id] = uses.get(kf_id, 0)
        motion = _motion_for(shot, uses[kf_id])
        uses[kf_id] += 1
        lines = line_map.get(shot.shot_id, [])
        speech = round(sum(_speech_seconds(item.text) for item in lines), 2)
        upgrade, reason, upgrade_cost = _upgrade_for(shot)
        reused = uses[kf_id] > 1
        edits.append(
            AnimaticShotEdit(
                shot_id=shot.shot_id,
                keyframe_id=kf_id,
                motion=motion,
                overlay_kind=shot.overlay_kind,
                overlay_copy=list(shot.overlay_copy),
                planned_duration_seconds=shot.duration_seconds,
                speech_seconds=speech,
                edit_duration_seconds=shot.duration_seconds,
                local_sfx=_sfx_for(shot),
                upgrade=upgrade,
                upgrade_reason=reason,
                upgrade_executable_model=(
                    shot.executable_model if upgrade.startswith("VIDEO") else ""
                ),
                upgrade_ideal_model=shot.ideal_model if upgrade.startswith("VIDEO") else "",
                upgrade_estimated_usd=upgrade_cost,
                reused=reused,
                location_slot=shot.location_slot,
                props=list(shot.props),
                visible_cast=list(shot.visible_cast),
            )
        )
        planned.append(shot.duration_seconds)
        speech_list.append(speech)
        for index, line in enumerate(lines):
            speaker = fold_character_id(line.speaker_character_id)
            assignment = voice_by_name.get(speaker)
            if backend == "eleven-v3" and assignment:
                provider, model, voice_id = (
                    "elevenlabs",
                    "eleven-v3",
                    assignment.voice_id,
                )
            else:
                fallback = (
                    assignment.fallback_voice_id
                    if assignment
                    else OPENAI_STOCK_VOICES[index % len(OPENAI_STOCK_VOICES)]
                )
                provider, model, voice_id = "openai", "gpt-4o-mini-tts", fallback
            item = AnimaticVoiceLine(
                line_id=f"{shot.shot_id}_line_{index + 1}",
                shot_id=shot.shot_id,
                speaker=speaker,
                text=line.text,
                emotion=line.emotion,
                delivery=line.delivery,
                provider=provider,
                model=model,
                voice_id=voice_id,
                estimated_seconds=_speech_seconds(line.text),
                cloning=False,
            )
            item.request_fingerprint = _fingerprint_voice(item)
            voice_lines.append(item)
    scaled = scale_edit_to_window(planned, speech_list, brief.target_duration_seconds)
    for edit, duration in zip(edits, scaled, strict=True):
        edit.edit_duration_seconds = duration
    resolved_voices: list[VoiceAssignment] = []
    for item in voices:
        if backend == "eleven-v3":
            resolved_voices.append(item.model_copy(update={"provider": "elevenlabs"}))
        else:
            resolved_voices.append(
                item.model_copy(
                    update={
                        "provider": "openai",
                        "voice_id": item.fallback_voice_id or item.voice_id,
                        "display_name": f"OpenAI stock · {item.character_name}",
                    }
                )
            )
    sunburst = sum(1 for item in keyframes if "sunburst" in item.model)
    flare = sum(1 for item in keyframes if "flare" in item.model)
    expected_image = 0.0
    reserved_image = 0.0
    for item in keyframes:
        if not item.generate:
            continue
        with_ref = bool(item.reference_files)
        expected_image += typical_image_usd(with_reference=with_ref)
        reserved_image += reserve_image_usd(with_reference=with_ref)
    chars = sum(len(line.text) for line in voice_lines)
    if backend == "eleven-v3":
        expected_voice = round((chars / 1000.0) * ELEVEN_V3_USD_PER_1K_CHARS, 4)
        reserved_voice = round(expected_voice * 1.5, 4)
    else:
        expected_voice = round((chars / 1_000_000) * 0.60 + (chars * 20 / 1_000_000) * 12.0, 4)
        reserved_voice = round(max(0.02, expected_voice * 2.0), 4)
    expected = round(expected_image + expected_voice, 4)
    reserved = round(reserved_image + reserved_voice, 4)
    upgrade_total = round(
        sum(edit.upgrade_estimated_usd or 0.0 for edit in edits), 4
    )
    reused_shots = sum(1 for edit in edits if edit.reused or not edit.overlay_kind and True)
    reused_or_local = sum(
        1
        for edit in edits
        if edit.reused or edit.upgrade == "LOCAL_MOTION_SUFFICIENT"
    )
    _ = reused_shots
    assignments = resolved_voices
    plan = AnimaticPlan(
        series_slug=brief.series_slug,
        episode_number=brief.episode_number,
        quality_profile=profile.value,
        shot_count=len(edits),
        keyframes=keyframes,
        shots=edits,
        voice_lines=voice_lines,
        voice_assignments=assignments,
        voice_provider="elevenlabs" if backend == "eleven-v3" else "openai",
        voice_model=backend,
        sunburst_count=sunburst,
        flare_count=flare,
        unique_image_count=sum(1 for item in keyframes if item.generate),
        reused_or_local_shot_count=reused_or_local,
        expected_image_usd=round(expected_image, 4),
        reserved_image_usd=round(reserved_image, 4),
        expected_voice_usd=expected_voice,
        reserved_voice_usd=reserved_voice,
        other_provider_usd=0.0,
        expected_usd=expected,
        reserved_usd=reserved,
        hard_cap_usd=ANIMATIC_PROVIDER_HARD_CAP_USD,
        cap_ok=True,
        total_edit_seconds=round(sum(scaled), 1),
        expected_voice_seconds=round(sum(line.estimated_seconds for line in voice_lines), 2),
        upgrade_estimated_usd=upgrade_total,
        execute=False,
        video_provider_calls=0,
        notes=[
            "Animatic is still-driven. No Runway/Veo/Higgsfield.",
            "Phone/UI text is local compositor copy.",
            "Premium SFX/music not in this budget.",
            f"subtitles_burn_in={burn_in_required()}",
            f"locked_refs={len(locked_refs)}",
        ],
    )
    return apply_animatic_cap(plan)


def format_animatic_review(plan: AnimaticPlan, spec: FriendGroupStorySpec) -> str:
    kf_lines = [
        f"- {item.keyframe_id} model={item.model} gen={item.generate} "
        f"visible={','.join(item.visible_characters) or 'none'} "
        f"refs={len(item.reference_files)} fp={item.request_fingerprint[:12]} "
        f"| {item.role}"
        for item in plan.keyframes
    ]
    shot_lines = [
        f"- {item.shot_id} {item.edit_duration_seconds:.1f}s kf={item.keyframe_id} "
        f"motion={item.motion} reused={item.reused} overlay={item.overlay_kind or 'none'} "
        f"{item.upgrade} sfx={','.join(item.local_sfx) or 'none'}"
        for item in plan.shots
    ]
    upgrades = [
        f"- {item.shot_id}: {item.upgrade_reason} exec={item.upgrade_executable_model} "
        f"ideal={item.upgrade_ideal_model} est={item.upgrade_estimated_usd}"
        for item in plan.shots
        if item.upgrade == "VIDEO_UPGRADE_RECOMMENDED"
    ] or ["- none"]
    voices = [
        f"- {item.character_name}: {item.provider}/{item.voice_id} clone={item.cloning}"
        for item in plan.voice_assignments
    ]
    return "\n".join(
        [
            "# Friend Group animatic plan",
            "",
            "Status: ANIMATIC PLAN ONLY. PROVIDER HTTP=0.",
            f"series={plan.series_slug} episode={plan.episode_number}",
            f"title={spec.title}",
            f"hook={spec.cold_open_hook}",
            f"shot_count={plan.shot_count}",
            f"unique_images={plan.unique_image_count} sunburst={plan.sunburst_count} "
            f"flare={plan.flare_count}",
            f"reused_or_local_shots={plan.reused_or_local_shot_count}",
            f"voice_provider={plan.voice_provider} model={plan.voice_model}",
            f"expected_voice_seconds={plan.expected_voice_seconds}",
            f"edit_seconds={plan.total_edit_seconds}",
            "",
            "## COST",
            "",
            f"expected_image_usd={plan.expected_image_usd:.4f}",
            f"reserved_image_usd={plan.reserved_image_usd:.4f}",
            f"expected_voice_usd={plan.expected_voice_usd:.4f}",
            f"reserved_voice_usd={plan.reserved_voice_usd:.4f}",
            f"other_provider_usd={plan.other_provider_usd:.4f}",
            f"expected_animatic_total={plan.expected_usd:.4f}",
            f"reserved_animatic_total={plan.reserved_usd:.4f}",
            f"hard_cap_usd={plan.hard_cap_usd:.2f} cap_ok={plan.cap_ok}",
            "",
            "## KEYFRAMES",
            "",
            *kf_lines,
            "",
            "## SHOT EDITS",
            "",
            *shot_lines,
            "",
            "## VOICE ASSIGNMENTS",
            "",
            *voices,
            "",
            "## VIDEO UPGRADE MAP (not executed)",
            "",
            *upgrades,
            f"estimated_later_premium_video_upgrade_usd={plan.upgrade_estimated_usd:.4f}",
            "",
            "## COMMANDS",
            "",
            "`uv run docprod friend-group-episode --stage animatic-plan`",
            "`uv run docprod friend-group-episode --stage animatic-generate --confirm-paid`",
            "",
            "provider_http_calls=0",
            f"READY FOR ANIMATIC GENERATION={'yes' if plan.cap_ok else 'no'}",
            "",
        ]
    ) + "\n"


def assert_animatic_ready_for_http(plan: AnimaticPlan) -> None:
    if plan.reserved_usd - 1e-9 > plan.hard_cap_usd:
        raise ProductError(
            f"STOP BEFORE HTTP: reserved ${plan.reserved_usd:.4f} exceeds "
            f"hard cap ${plan.hard_cap_usd:.2f}"
        )
    if plan.video_provider_calls:
        raise ProductError("animatic must not schedule video-provider calls")


def load_animatic_ledger(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"operations": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_animatic_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _mark_prepared(ledger: dict[str, Any], op_id: str, fingerprint: str) -> None:
    ops = ledger.setdefault("operations", {})
    current = ops.get(op_id) if isinstance(ops.get(op_id), dict) else {}
    if current.get("state") == "SUCCEEDED" and current.get("fingerprint") == fingerprint:
        return
    ops[op_id] = {
        "state": "PREPARED",
        "fingerprint": fingerprint,
        "artifact": current.get("artifact") or "",
    }


def _mark_succeeded(ledger: dict[str, Any], op_id: str, fingerprint: str, artifact: str) -> None:
    ops = ledger.setdefault("operations", {})
    ops[op_id] = {"state": "SUCCEEDED", "fingerprint": fingerprint, "artifact": artifact}


def _reuse_succeeded(ledger: dict[str, Any], op_id: str, fingerprint: str) -> str | None:
    ops = ledger.get("operations") if isinstance(ledger.get("operations"), dict) else {}
    row = ops.get(op_id) if isinstance(ops, dict) else None
    if not isinstance(row, dict):
        return None
    if row.get("state") == "SUCCEEDED" and row.get("fingerprint") == fingerprint:
        artifact = str(row.get("artifact") or "")
        if artifact and Path(artifact).is_file():
            return artifact
    return None


def write_phone_overlay(dest: Path, lines: list[str]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def write_animatic_subtitles(plan: AnimaticPlan, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    ass_path = dest_dir / "animatic.ass"
    cursor = 0.0
    events: list[str] = []
    by_shot = {line.shot_id: [] for line in plan.voice_lines}
    for line in plan.voice_lines:
        by_shot.setdefault(line.shot_id, []).append(line)
    for shot in plan.shots:
        start = cursor
        end = cursor + shot.edit_duration_seconds
        for line in by_shot.get(shot.shot_id, []):
            events.append(
                f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},Default,,0,0,0,,"
                f"{line.text.replace(chr(10), ' ')}"
            )
        cursor = end
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nStyle: Default,Arial,42,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,80,80,160,1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return ass_path


def execute_animatic_generate(
    plan: AnimaticPlan,
    *,
    confirm_paid: bool,
    work_dir: Path,
    image_client: AnimaticImageClient | None = None,
    voice_client: AnimaticVoiceClient | None = None,
    renderer: AnimaticRenderer | None = None,
    execute_calls: bool = True,
) -> dict[str, object]:
    if not confirm_paid:
        raise PaidApiNotConfirmedError(
            "animatic-generate requires --confirm-paid after animatic-plan approval"
        )
    assert_animatic_ready_for_http(plan)
    if any(kf.model in FORBIDDEN_VIDEO_MODELS for kf in plan.keyframes):
        raise ProductError("animatic image jobs cannot use video models")
    ledger_path = work_dir / "animatic_ledger.json"
    ledger = load_animatic_ledger(ledger_path)
    still_dir = work_dir / "stills"
    voice_dir = work_dir / "voices"
    overlay_dir = work_dir / "overlays"
    still_dir.mkdir(parents=True, exist_ok=True)
    voice_dir.mkdir(parents=True, exist_ok=True)
    http_calls = 0
    if not execute_calls:
        return {
            "stage": "animatic-generate",
            "execute": False,
            "provider_http_calls": 0,
            "output": "",
        }
    if image_client is None or voice_client is None or renderer is None:
        if image_client is None:
            image_client = OpenAIAnimaticImageClient(confirm_paid=confirm_paid)
        if voice_client is None:
            voice_client = DefaultAnimaticVoiceClient(confirm_paid=confirm_paid)
        if renderer is None:
            renderer = LocalStillAnimaticRenderer()
    for keyframe in plan.keyframes:
        if not keyframe.generate:
            continue
        op_id = f"image:{keyframe.keyframe_id}"
        reused = _reuse_succeeded(ledger, op_id, keyframe.request_fingerprint)
        dest = still_dir / f"{keyframe.keyframe_id}.jpg"
        if reused:
            continue
        _mark_prepared(ledger, op_id, keyframe.request_fingerprint)
        save_animatic_ledger(ledger_path, ledger)
        path = image_client.generate(keyframe, dest)
        http_calls += 1
        _mark_succeeded(ledger, op_id, keyframe.request_fingerprint, str(path))
        save_animatic_ledger(ledger_path, ledger)
    for line in plan.voice_lines:
        op_id = f"voice:{line.line_id}"
        reused = _reuse_succeeded(ledger, op_id, line.request_fingerprint)
        dest = voice_dir / f"{line.line_id}.wav"
        if reused:
            continue
        _mark_prepared(ledger, op_id, line.request_fingerprint)
        save_animatic_ledger(ledger_path, ledger)
        path = voice_client.synthesize(line, dest)
        http_calls += 1
        _mark_succeeded(ledger, op_id, line.request_fingerprint, str(path))
        save_animatic_ledger(ledger_path, ledger)
    for shot in plan.shots:
        if shot.overlay_kind == "phone_ui" and shot.overlay_copy:
            write_phone_overlay(overlay_dir / f"{shot.shot_id}.txt", shot.overlay_copy)
    ass_path = write_animatic_subtitles(plan, work_dir)
    output = work_dir / "birko_episode_2_animatic.mp4"
    if plan.series_slug != "birko":
        output = work_dir / f"{plan.series_slug}_episode_{plan.episode_number}_animatic.mp4"
    rendered = renderer.render(plan, output, work_dir=work_dir)
    return {
        "stage": "animatic-generate",
        "execute": True,
        "provider_http_calls": http_calls,
        "video_provider_calls": 0,
        "output": str(rendered),
        "subtitles": str(ass_path),
        "subtitle_filter": ffmpeg_subtitle_filter(ass_path),
        "ledger": str(ledger_path),
    }


class OpenAIAnimaticImageClient:
    def __init__(self, *, confirm_paid: bool, settings: Settings | None = None) -> None:
        self.confirm_paid = confirm_paid
        self.settings = settings

    def generate(self, keyframe: AnimaticKeyframeSpec, dest: Path) -> Path:
        from docprod.providers.openai_image import OpenAIImageProvider

        provider = OpenAIImageProvider(
            settings=self.settings,
            config=_still_config(keyframe.model),
        )
        refs = [Path(path) for path in keyframe.reference_files]
        result = provider.generate(
            keyframe.prompt,
            confirm_paid=self.confirm_paid,
            reference_images=refs,
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(result.image_bytes)
        return dest


class DefaultAnimaticVoiceClient:
    def __init__(self, *, confirm_paid: bool, settings: Settings | None = None) -> None:
        self.confirm_paid = confirm_paid
        self.settings = settings

    def synthesize(self, line: AnimaticVoiceLine, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if line.model == "eleven-v3":
            from docprod.providers.elevenlabs_tts import ElevenLabsTTSProvider, write_canonical_wav

            result = ElevenLabsTTSProvider(settings=self.settings).synthesize(
                line.text,
                confirm_paid=self.confirm_paid,
                voice_id=line.voice_id,
                language="tr",
                instructions=line.delivery,
                dry_run=False,
            )
            if result.get("cached"):
                dest.write_bytes(Path(str(result["path"])).read_bytes())
                return dest
            write_canonical_wav(result["bytes"], dest)
            return dest
        from docprod.providers.openai_tts import OpenAITTSProvider

        audio, _usage = OpenAITTSProvider(settings=self.settings).synthesize(
            line.text,
            confirm_paid=self.confirm_paid,
            instructions=line.delivery or line.emotion,
        )
        dest.write_bytes(audio)
        return dest


class LocalStillAnimaticRenderer:
    def render(self, plan: AnimaticPlan, dest: Path, *, work_dir: Path) -> Path:
        from docprod.product.animatic_render import render_existing_animatic

        render_existing_animatic(plan, work_dir=work_dir, dest=dest)
        return dest
