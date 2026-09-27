from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from docprod.config import Settings
from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.animatic_render import DialogueCue, write_timed_subtitles
from docprod.product.birko_bible import member_by_slug
from docprod.product.canary_cost import usd_round
from docprod.product.errors import ProductError
from docprod.product.friend_group import FriendGroupStorySpec
from docprod.product.higgsfield_inputs import (
    PublicAsset,
    assert_https_input_url,
    assert_https_request_body,
    asset_lookup,
    build_public_asset_map,
    collect_request_input_urls,
    preflight_input_urls,
)
from docprod.product.simple_video import (
    MAX_VISIBLE_CAST,
    SIMPLE_PRIMARY_MODEL,
    SIMPLE_SECONDARY_MODEL,
    SIMPLE_VIDEO_HARD_CAP_USD,
    concat_simple_scenes,
)
from docprod.providers.higgsfield import (
    SEEDANCE_CONTRACTS,
    classify_higgsfield_status,
    download_higgsfield_media,
    extract_higgsfield_video_url,
    higgsfield_credentials_present,
    higgsfield_request_result,
    higgsfield_request_status,
    sanitize_higgsfield_lifecycle,
    seedance_image_to_video_body,
    seedance_reference_to_video_body,
    seedance_request_fingerprint,
    submit_higgsfield_json,
)
from docprod.quality.router import estimate_model_cost
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.render.subtitles import ffmpeg_subtitle_filter
from docprod.storage.hashing import file_sha256

STORY_SPEC_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_story_spec.json"
)
ANIMATIC_PLAN_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_animatic_plan.json"
)
HIGGSFIELD_PLAN_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_higgsfield_scene_plan.json"
)
HIGGSFIELD_REVIEW_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_higgsfield_scene_review.md"
)
HIGGSFIELD_LEDGER_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/render/episode_2/"
    "higgsfield_ledger.json"
)
HIGGSFIELD_CLIPS_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/render/episode_2/higgsfield"
)
HIGGSFIELD_FINAL_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/render/episode_2/"
    "birko_episode_2_higgsfield.mp4"
)
RESUME_DEADLINE_SECONDS = 720.0
POLL_INTERVAL_SECONDS = 5.0
POLL_MAX_INTERVAL_SECONDS = 15.0
APPROVED_EXPECTED_USD = 9.216
APPROVED_RESERVED_USD = 11.3472
APPROVED_HARD_CAP_USD = 12.0
APPROVED_SCENE_IDS = (
    "HF1_hook_bill",
    "HF2_order_setup",
    "HF3_birko_slips",
    "HF4_muge_kemal",
    "HF5_erni",
    "HF6_musti",
    "HF7_kemal_pays",
    "HF8_payoff",
)
APPROVED_DURATIONS = (6, 7, 6, 8, 9, 9, 8, 6)
LOCKED_DURATION = dict(zip(APPROVED_SCENE_IDS, APPROVED_DURATIONS, strict=True))
I2V_SCENE_IDS = {
    "HF1_hook_bill",
    "HF3_birko_slips",
    "HF4_muge_kemal",
    "HF7_kemal_pays",
    "HF8_payoff",
}
SIMPLE_I2V_MODEL = "seedance-2.5-image-to-video"
PROMPT_REVISION_REASON = "provider safety retry"
HF3_REVISION_3_REASON = "Birko-only I2V safety fallback"
HF3_REVISION_3_PROMPT = (
    "9:16 cinematic live-action. A fully clothed adult man is seated in a bright casual café. "
    "A receipt arrives at the table. He notices it, quietly stands up, pushes his chair back "
    "naturally, and casually walks away from the table and out of frame. Dry awkward comedy, "
    "understated realistic acting, natural café motion, consistent face and appearance with the "
    "attached reference photo. Continuous cinematic movement for the full shot. No spoken "
    "dialogue. Generate natural café ambience, chair movement, paper receipt sound, cups and "
    "distant room tone."
)
HF3_REVISION_2_VIDEO_PROMPT = (
    "9:16 cinematic live-action, continuous motion, no slideshow. same Krispy Kreme café "
    "interior, six-top table, window, door, counter, evening. Visible: Birko, HG. Two fully "
    "clothed adult male friends in a bright casual café. A bill arrives at the table. Birko "
    "quietly stands and casually walks away from the table. HG notices him leaving and calmly "
    "slides the receipt toward Kemal's side of the table. Dry awkward comedy. No violence. "
    "No threat. No physical confrontation. No sexual content. No nudity. No suggestive behavior. "
    "Natural cinematic café scene. Natural conversational motion continues for the full duration; "
    "fully clothed adults; no freeze-frame. Turkish café evening, natural light, real acting, "
    "keep faces consistent with attached reference photos. Do not freeze into a still. No spoken "
    "dialogue in this scene. Do not invent lines. Generate native café ambience and foley only. "
    "Native scene sound: Krispy Kreme café ambience, cups, distant POS, chairs, evening interior "
    "beds. Keep foley under the spoken Turkish. Chair scrape as someone leaves, bill tray arrival, "
    "hushed table."
)
ORIGINAL_HF3_VIDEO_PROMPT = (
    "9:16 cinematic live-action, continuous motion, no slideshow. same Krispy Kreme café "
    "interior, six-top table, window, door, counter, evening. Visible: Birko, HG. Boxes are "
    "empty. The bill tray arrives. Everyone leans in. Birko slips out behind the chairs. HG "
    "sees him, stays quiet, slides the receipt toward Kemal. Hands, eyelines, and body weight "
    "keep moving for the full duration; no dead hold after the last line. Turkish café evening, "
    "natural light, real acting, keep faces consistent with attached reference photos. Do not "
    "freeze into a still. No spoken dialogue in this scene. Do not invent lines. Generate native "
    "café ambience and foley only. Native scene sound: Krispy Kreme café ambience, cups, distant "
    "POS, chairs, evening interior beds. Keep foley under the spoken Turkish. Chair scrape as "
    "someone leaves, bill tray arrival, hushed table."
)
ORIGINAL_HF4_VIDEO_PROMPT = (
    "9:16 cinematic live-action, continuous motion, no slideshow. same Krispy Kreme café "
    "interior, six-top table, window, door, counter, evening. Visible: Müge, Kemal. Müge grabs "
    "the receipt and taps the premium-box price. Kemal points at the exit. Hands, eyelines, and "
    "body weight keep moving for the full duration; no dead hold after the last line. "
    "Turkish café evening, natural light, real acting, keep faces consistent with attached "
    "reference photos. Do not freeze into a still. Seedance native audio: generate_audio=true. "
    "Characters speak natural, lip-synced Turkish in sync with the picture. Use only the "
    "approved lines below; do not add, translate, or rewrite dialogue. Müge says EXACTLY these "
    "Turkish words: \"Bu özel kutuyu kim söyledi?\" (speaker=muge; intended voice/delivery: "
    "confident Turkish female, slightly incredulous/materialistic energy. Character bible: "
    "Kendinden emin, flörtöz, gerektiğinde aşırı tatlı; sinirlenince hızla sertleşen yetişkin "
    "kadın sesi.). Kemal says EXACTLY these Turkish words: "
    "\"Kocan kaçmış, sen kutuyu soruyorsun!\" (speaker=kemal; intended voice/delivery: natural "
    "young Turkish male, increasingly frustrated. Character bible: Normal genç yetişkin erkek "
    "sesi. Yorgun/bezmiş. Sinirlenince enerji yükselir. Grubun en doğal konuşanı.). Müge says "
    "EXACTLY these Turkish words: \"Fiyatını gördün mü?\" (speaker=muge; intended voice/delivery: "
    "confident Turkish female, slightly incredulous/materialistic energy. Character bible: "
    "Kendinden emin, flörtöz, gerektiğinde aşırı tatlı; sinirlenince hızla sertleşen yetişkin "
    "kadın sesi.). Native scene sound: Krispy Kreme café ambience, cups, distant POS, chairs, "
    "evening interior beds. Keep foley under the spoken Turkish. Paper receipt, overlapping "
    "café room tone."
)
HF4_REVISION_3_REASON = "Müge-only I2V safety fallback preserving character visibility"
HF4_REVISION_3_PROMPT = (
    "9:16 cinematic live-action. An adult woman sits at a table in a bright casual café with "
    "an expensive donut box and a receipt in front of her. She looks between the box and receipt, "
    "asks a question to a man seated just outside the camera frame, listens to his offscreen "
    "response with mild surprise, then looks back at the price on the receipt and answers him. "
    "Dry conversational comedy, understated realistic acting, natural facial reactions and hand "
    "movement, consistent face and appearance with the attached reference photo. Continuous "
    "cinematic movement for the full shot. Generate natural café ambience and synchronized "
    "Turkish dialogue. Seedance native audio: generate_audio=true. Characters speak natural, "
    "lip-synced Turkish in sync with the picture. Use only the approved lines below; do not add, "
    "translate, or rewrite dialogue. Müge says EXACTLY these Turkish words: "
    "\"Bu özel kutuyu kim söyledi?\" (speaker=muge; on-camera, lip-synced; "
    "intended voice/delivery: "
    "natural adult Turkish female voice, mildly incredulous). Kemal says EXACTLY these Turkish "
    "words: \"Kocan kaçmış, sen kutuyu soruyorsun!\" (speaker=kemal; offscreen native audio; "
    "intended voice/delivery: natural young adult Turkish male voice, frustrated disbelief). "
    "Müge says EXACTLY these Turkish words: \"Fiyatını gördün mü?\" (speaker=muge; on-camera, "
    "lip-synced; intended voice/delivery: natural adult Turkish female voice, mildly incredulous)."
)
HF4_REVISION_2_VIDEO_PROMPT = (
    "9:16 cinematic live-action, continuous motion, no slideshow. same Krispy Kreme café "
    "interior, six-top table, window, door, counter, evening. Visible: Müge, Kemal. Two fully "
    "clothed adult friends seated in a bright casual café. Müge looks at an expensive donut box "
    "and the receipt. Kemal reacts with frustrated disbelief. They have a normal verbal "
    "disagreement about the price and who ordered it. No physical contact. No romance. "
    "No flirting. "
    "No suggestive posing. No body emphasis. No sexual content. No nudity. Natural conversational "
    "comedy. Natural conversational motion continues for the full duration; fully clothed adults; "
    "no freeze-frame. Turkish café evening, natural light, real acting, keep faces consistent with "
    "attached reference photos. Do not freeze into a still. Seedance native audio: generate_audio="
    "true. Characters speak natural, lip-synced Turkish in sync with the picture. Use only the "
    "approved lines below; do not add, translate, or rewrite dialogue. Müge says EXACTLY these "
    "Turkish words: \"Bu özel kutuyu kim söyledi?\" (speaker=muge; intended voice/delivery: "
    "confident Turkish female, slightly incredulous/materialistic energy). Kemal says EXACTLY "
    "these Turkish words: \"Kocan kaçmış, sen kutuyu soruyorsun!\" "
    "(speaker=kemal; intended voice/delivery: "
    "natural young Turkish male, increasingly frustrated). Müge says EXACTLY these Turkish words: "
    "\"Fiyatını gördün mü?\" (speaker=muge; intended voice/delivery: confident Turkish female, "
    "slightly incredulous/materialistic energy). Native scene sound: Krispy Kreme café ambience, "
    "cups, distant POS, chairs, evening interior beds. Keep foley under the spoken Turkish. "
    "Paper receipt, overlapping café room tone."
)
HF4_MUGE_VOICE = "natural adult Turkish female voice, mildly incredulous"
HF4_KEMAL_OFFSCREEN_VOICE = "natural young adult Turkish male voice, frustrated disbelief"
APPROVED_PLAN_FINGERPRINT = (
    "24089ff09e662a5579a2632b57a61c14794b03f55cad301e2fe7fac13ca1b8fb"
)
INTERIOR_LOCATION_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/render/episode_2/stills/"
    "kf_master_interior_table.jpg"
)
EXTERIOR_LOCATION_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/render/episode_2/stills/"
    "kf_master_exterior_bench.jpg"
)
VOICES_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/render/episode_2/voices"
)
SEEDANCE_VOICE_DIRECTION = {
    "birko": "low-energy, heavy, relaxed, dry/deadpan Turkish male voice",
    "kemal": "natural young Turkish male, increasingly frustrated",
    "muge": "confident Turkish female, slightly incredulous/materialistic energy",
    "erni": "bright sweet feminine Turkish voice with subtly teasing/manipulative delivery",
    "hg": "cool low Turkish male voice, dark/amused, calm",
    "musti": "young energetic Turkish male, chaotic/defensive",
}
CHARACTER_DISPLAY = {
    "birko": "Birko",
    "kemal": "Kemal",
    "muge": "Müge",
    "erni": "Erni",
    "hg": "HG",
    "musti": "Musti",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


class HiggsfieldDialogue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str
    text: str
    delivery: str = ""
    audio_path: str = ""
    audio_seconds: float = 0.0
    missing_tts: bool = False
    voice: str = ""


class HiggsfieldScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    duration: float
    visible_characters: list[str] = Field(default_factory=list)
    offscreen_speakers: list[str] = Field(default_factory=list)
    character_refs: list[str] = Field(default_factory=list)
    input_assets: list[dict[str, str]] = Field(default_factory=list)
    location_ref: str = ""
    props: list[str] = Field(default_factory=list)
    action: str = ""
    dialogue_lines: list[HiggsfieldDialogue] = Field(default_factory=list)
    camera_intent: str = ""
    video_prompt: str = ""
    audio_track: list[str] = Field(default_factory=list)
    provider: str = "higgsfield"
    model: str = SIMPLE_PRIMARY_MODEL
    request_fingerprint: str = ""
    request_body: dict[str, Any] = Field(default_factory=dict)
    expected_usd: float = 0.0
    reserved_usd: float = 0.0
    generate_audio: bool = True
    native_audio: bool = True
    external_tts: bool = False
    fallback_tts_paths: list[str] = Field(default_factory=list)
    prompt_revision: int = 1
    prompt_revision_reason: str = ""
    prompt_history: list[dict[str, Any]] = Field(default_factory=list)


class HiggsfieldScenePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    source_story: str = STORY_SPEC_RELATIVE
    scenes: list[HiggsfieldScene] = Field(default_factory=list)
    canonical_refs: dict[str, str] = Field(default_factory=dict)
    expected_usd: float = 0.0
    reserved_usd: float = 0.0
    hard_cap_usd: float = SIMPLE_VIDEO_HARD_CAP_USD
    cap_ok: bool = True
    missing_tts_count: int = 0
    provider_http_calls: int = 0
    native_audio: bool = True
    external_tts: bool = False


def parse_only_scenes(raw: str | None) -> frozenset[str] | None:
    if raw is None:
        return None
    token = str(raw).strip()
    if not token:
        return None
    ids = [part.strip() for part in token.split(",") if part.strip()]
    if not ids:
        raise ProductError("--only-scenes listed no scene ids")
    unknown = [scene_id for scene_id in ids if scene_id not in APPROVED_SCENE_IDS]
    if unknown:
        raise ProductError(f"unknown --only-scenes id(s): {unknown}")
    return frozenset(ids)


def is_higgsfield_safety_failure(row: dict[str, Any]) -> bool:
    blob = f"{row.get('error') or ''} {row.get('provider_status') or ''}".lower()
    return "nsfw" in blob or "content safety" in blob or "safety checks" in blob


def selected_scene_cost_report(
    plan: HiggsfieldScenePlan,
    only_scenes: frozenset[str] | None,
    *,
    ledger: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    if only_scenes is None:
        return {
            "selected_scene_ids": [],
            "selected_expected_total": 0.0,
            "selected_generation_posts_max": 0,
        }
    ops = ledger.get("operations") if isinstance((ledger or {}).get("operations"), dict) else {}
    expected = 0.0
    posts_max = 0
    ordered = [scene.scene_id for scene in plan.scenes if scene.scene_id in only_scenes]
    for scene in plan.scenes:
        if scene.scene_id not in only_scenes:
            continue
        expected += float(scene.expected_usd)
        row = ops.get(scene.scene_id) if isinstance(ops.get(scene.scene_id), dict) else {}
        clip = _clip_path(scene.scene_id, root=root or _repo_root())
        if str(row.get("state") or "") == "SUCCEEDED" and _playable_clip(clip):
            continue
        posts_max += 1
    return {
        "selected_scene_ids": ordered,
        "selected_expected_total": usd_round(expected),
        "selected_generation_posts_max": posts_max,
    }


def load_existing_story(*, root: Path | None = None) -> FriendGroupStorySpec:
    path = (root or _repo_root()) / STORY_SPEC_RELATIVE
    if not path.is_file():
        raise ProductError(f"missing existing story spec {path}")
    return FriendGroupStorySpec.model_validate_json(path.read_text(encoding="utf-8"))


def canonical_ref_report(refs: list[dict[str, object]]) -> dict[str, dict[str, str]]:
    folder = _repo_root() / "projects/birko_kemal_drama_canary/artifacts/visuals/character_refs"
    inputs = _repo_root() / "projects/birko_kemal_drama_canary/inputs/characters"
    out: dict[str, dict[str, str]] = {}
    by_slug = {str(row.get("slug")): row for row in refs}
    for slug in ("birko", "kemal", "muge", "erni", "hg", "musti"):
        row = by_slug.get(slug) or {}
        resolved = str(row.get("resolved_path") or "")
        custom = str(row.get("custom_source") or "")
        archive = folder / f"ref_{slug}_v1_archive.jpg"
        front = inputs / slug / "front.png"
        out[slug] = {
            "canonical": resolved,
            "custom_source": custom or (str(front) if front.is_file() else ""),
            "v1_archive": str(archive) if archive.is_file() else "",
            "use": resolved,
        }
    return out


def _norm_text(text: str) -> str:
    return " ".join(text.split())


def _wav_index(*, root: Path) -> dict[str, Path]:
    mapped: dict[str, Path] = {}
    plan_path = root / ANIMATIC_PLAN_RELATIVE
    voice_dir = root / VOICES_RELATIVE
    if plan_path.is_file():
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
        for line in payload.get("voice_lines") or []:
            if not isinstance(line, dict):
                continue
            text = _norm_text(str(line.get("text") or ""))
            wav = voice_dir / f"{line.get('line_id')}.wav"
            if text and wav.is_file():
                mapped[text] = wav
    if voice_dir.is_dir():
        for wav in sorted(voice_dir.glob("*.wav")):
            mapped.setdefault(wav.stem, wav)
    return mapped


def _audio_seconds(path: Path) -> float:
    try:
        return max(0.05, float(probe_media(path).duration or 0.0))
    except Exception:
        return 0.0


def _attach_dialogue(
    spec: FriendGroupStorySpec,
    texts: list[str],
    wavs: dict[str, Path],
    *,
    include_bible: bool = True,
    voice_overrides: dict[str, str] | None = None,
) -> list[HiggsfieldDialogue]:
    by_text = {_norm_text(line.text): line for line in spec.dialogue_lines}
    rows: list[HiggsfieldDialogue] = []
    for text in texts:
        key = _norm_text(text)
        src = by_text.get(key)
        if src is None:
            raise ProductError(f"dialogue not in existing story: {text}")
        wav = wavs.get(key)
        seconds = _audio_seconds(wav) if wav else 0.0
        slug = src.speaker_character_id
        rows.append(
            HiggsfieldDialogue(
                speaker=slug,
                text=src.text,
                delivery=src.delivery,
                audio_path=str(wav) if wav else "",
                audio_seconds=round(seconds, 3),
                missing_tts=wav is None,
                voice=_voice_direction(
                    slug,
                    include_bible=include_bible,
                    override=(voice_overrides or {}).get(slug),
                ),
            )
        )
    return rows


def _scene_duration(lines: list[HiggsfieldDialogue], *, motion: float) -> float:
    speech = sum(item.audio_seconds or (max(len(item.text), 8) / 13.0) for item in lines)
    needed = speech + motion
    return round(min(10.0, max(5.0, needed)), 3)


def _display_name(slug: str) -> str:
    return CHARACTER_DISPLAY.get(slug, slug)


def _voice_direction(
    slug: str,
    *,
    include_bible: bool = True,
    override: str | None = None,
) -> str:
    if override:
        return override
    directed = SEEDANCE_VOICE_DIRECTION[slug]
    if not include_bible:
        return directed
    try:
        bible = member_by_slug(slug).voice_notes.strip()
    except KeyError:
        return directed
    return f"{directed}. Character bible: {bible}"


def _dialogue_audio_prompt(lines: list[HiggsfieldDialogue]) -> str:
    if not lines:
        return (
            "No spoken dialogue in this scene. Do not invent lines. "
            "Generate native café ambience and foley only."
        )
    spoken = []
    for item in lines:
        name = _display_name(item.speaker)
        spoken.append(
            f'{name} says EXACTLY these Turkish words: "{item.text}" '
            f"(speaker={item.speaker}; intended voice/delivery: {item.voice})."
        )
    return (
        "Seedance native audio: generate_audio=true. Characters speak natural, "
        "lip-synced Turkish in sync with the picture. Use only the approved lines "
        "below; do not add, translate, or rewrite dialogue. "
        + " ".join(spoken)
    )


def _ambience_prompt(*, exterior: bool, scene_id: str) -> str:
    if exterior:
        return (
            "Native scene sound: evening street outside the café, distant interior "
            "murmur through the window, phone speaker, hang-up click, quiet donut bite foley."
        )
    extra = {
        "HF1_hook_bill": "Receipt tray clink, low café murmur, water bottle on the table.",
        "HF2_order_setup": "Phone taps, menu rustle, café chatter.",
        "HF3_birko_slips": "Chair scrape as someone leaves, bill tray arrival, hushed table.",
        "HF4_muge_kemal": "Paper receipt, overlapping café room tone.",
        "HF5_erni": "Close table foley, cups, soft café beds.",
        "HF6_musti": "Tense table, light clatter, café beds under raised voices.",
        "HF7_kemal_pays": "POS beep, card tap, box lid, phone call room tone.",
    }
    base = (
        "Native scene sound: Krispy Kreme café ambience, cups, distant POS, chairs, "
        "evening interior beds. Keep foley under the spoken Turkish."
    )
    detail = extra.get(scene_id, "")
    return f"{base} {detail}".strip()


def _seedance_prompt(
    *,
    action: str,
    visible: list[str],
    location: str,
    moving: str,
    lines: list[HiggsfieldDialogue],
    exterior: bool,
    scene_id: str,
) -> str:
    people = ", ".join(_display_name(slug) for slug in visible)
    return (
        f"9:16 cinematic live-action, continuous motion, no slideshow. "
        f"{location}. Visible: {people}. {action} {moving} "
        f"Turkish café evening, natural light, real acting, keep faces consistent "
        f"with attached reference photos. Do not freeze into a still. "
        f"{_dialogue_audio_prompt(lines)} {_ambience_prompt(exterior=exterior, scene_id=scene_id)}"
    )


def _fill_scene(
    *,
    scene_id: str,
    visible: list[str],
    offscreen: list[str],
    action: str,
    camera: str,
    props: list[str],
    lines: list[HiggsfieldDialogue],
    motion: float,
    location_path: Path,
    ref_map: dict[str, str],
    public_lookup: dict[str, PublicAsset],
    exterior: bool = False,
    moving: str | None = None,
    prompt_revision: int = 1,
    prompt_revision_reason: str = "",
    prompt_history: list[dict[str, Any]] | None = None,
    include_location: bool = True,
    prompt_override: str | None = None,
) -> HiggsfieldScene:
    duration = float(LOCKED_DURATION[scene_id])
    char_paths = []
    seen: set[str] = set()
    assets: list[dict[str, str]] = []
    remote_chars: list[str] = []
    for slug in visible:
        path = ref_map.get(slug)
        if not path or slug in seen:
            continue
        seen.add(slug)
        char_paths.append(path)
        pub = public_lookup.get(slug)
        if pub is None or not pub.remote_https_url:
            raise ProductError(
                f"STOP BEFORE PAID HTTP: missing remote HTTPS ref for {slug}"
            )
        assets.append(pub.model_dump())
        remote_chars.append(assert_https_input_url(pub.remote_https_url))
    loc = str(location_path) if location_path.is_file() else ""
    loc_key = "exterior" if exterior else "interior"
    loc_pub = public_lookup.get(loc_key)
    if include_location and loc_pub is not None:
        assets.append(loc_pub.model_dump())
    loc_label = (
        "matching Krispy Kreme exterior bench and café window wall, same evening storefront"
        if exterior
        else "same Krispy Kreme café interior, six-top table, window, door, counter, evening"
    )
    loc_moving = moving or (
        "Hands, eyelines, and body weight keep moving for the full duration; "
        "no dead hold after the last line."
    )
    prompt = prompt_override or _seedance_prompt(
        action=action,
        visible=visible,
        location=loc_label,
        moving=loc_moving,
        lines=lines,
        exterior=exterior,
        scene_id=scene_id,
    )
    use_i2v = scene_id in I2V_SCENE_IDS or len(visible) == 1
    if use_i2v:
        model = SIMPLE_I2V_MODEL
        if not remote_chars:
            raise ProductError(f"STOP BEFORE PAID HTTP: {scene_id} has no character HTTPS input")
        body = seedance_image_to_video_body(
            prompt=prompt,
            duration=duration,
            image_url=remote_chars[0],
            generate_audio=True,
        )
    else:
        model = SIMPLE_PRIMARY_MODEL
        image_urls = list(remote_chars)
        if loc_pub is not None and loc_pub.remote_https_url:
            image_urls.append(assert_https_input_url(loc_pub.remote_https_url))
        body = seedance_reference_to_video_body(
            prompt=prompt,
            duration=duration,
            image_urls=image_urls,
            audio_urls=None,
            generate_audio=True,
        )
    assert_https_request_body(body)
    if "audio_urls" in body:
        raise ProductError("STOP BEFORE HTTP: audio_urls must not enter Seedance requests")
    shas = [file_sha256(Path(path)) for path in char_paths if Path(path).is_file()]
    if include_location and loc and Path(loc).is_file():
        shas.append(file_sha256(Path(loc)))
    billed = float(body["duration"])
    expected, _conf = estimate_model_cost(model, seconds=billed)
    reserved, _rconf = estimate_model_cost(model, seconds=min(10.0, billed * 1.2))
    fallback_tts = [item.audio_path for item in lines if item.audio_path]
    return HiggsfieldScene(
        scene_id=scene_id,
        duration=float(body["duration"]),
        visible_characters=visible,
        offscreen_speakers=offscreen,
        character_refs=char_paths,
        input_assets=assets,
        location_ref=loc if include_location else "",
        props=props,
        action=action,
        dialogue_lines=lines,
        camera_intent=camera,
        video_prompt=str(body["prompt"]),
        audio_track=[],
        generate_audio=True,
        native_audio=True,
        external_tts=False,
        fallback_tts_paths=fallback_tts,
        model=model,
        request_fingerprint=seedance_request_fingerprint(
            prompt=str(body["prompt"]),
            duration=float(body["duration"]),
            image_shas=shas,
            audio_shas=[],
            model=model,
        ),
        request_body=body,
        expected_usd=float(expected or 0.0),
        reserved_usd=float(reserved or 0.0),
        prompt_revision=prompt_revision,
        prompt_revision_reason=prompt_revision_reason,
        prompt_history=list(prompt_history or []),
    )


def build_higgsfield_scenes(
    spec: FriendGroupStorySpec,
    refs: list[dict[str, object]],
    *,
    root: Path | None = None,
    settings: Settings | None = None,
) -> HiggsfieldScenePlan:
    base = root or _repo_root()
    report = canonical_ref_report(refs)
    ref_map = {slug: row["use"] for slug, row in report.items() if row["use"]}
    wavs = _wav_index(root=base)
    interior = base / INTERIOR_LOCATION_RELATIVE
    exterior = base / EXTERIOR_LOCATION_RELATIVE
    location_locals = {}
    if interior.is_file():
        location_locals["interior"] = str(interior)
    if exterior.is_file():
        location_locals["exterior"] = str(exterior)
    public_payload = build_public_asset_map(
        character_locals=ref_map,
        location_locals=location_locals,
        root=base,
        settings=settings,
        packaged_dir=None if base == _repo_root() else base / "packaged_hf_inputs",
    )
    lookup = asset_lookup(public_payload)

    def attach(
        texts: list[str],
        *,
        include_bible: bool = True,
        voice_overrides: dict[str, str] | None = None,
    ) -> list[HiggsfieldDialogue]:
        return _attach_dialogue(
            spec,
            texts,
            wavs,
            include_bible=include_bible,
            voice_overrides=voice_overrides,
        )

    scenes = [
        _fill_scene(
            scene_id="HF1_hook_bill",
            visible=["kemal"],
            offscreen=[],
            action=(
                "3840 TL receipt lands in front of Kemal. Donut boxes and coffees fill the "
                "table; only a small water bottle sits at his place. He stares at the empty chair."
            ),
            camera="tight two-thirds on Kemal, bill readable, slow push",
            props=["receipt", "water bottle", "donut boxes"],
            lines=attach(["Ben sadece su içtim."]),
            motion=3.5,
            location_path=interior,
            ref_map=ref_map,
            public_lookup=lookup,
        ),
        _fill_scene(
            scene_id="HF2_order_setup",
            visible=["birko", "hg"],
            offscreen=[],
            action=(
                "Earlier: Birko checks private invite messages. HG reads over his shoulder, "
                "points at the premium box on the menu. Birko locks the phone."
            ),
            camera="OTS phone then two-shot Birko and HG",
            props=["phone", "menu", "premium donut box"],
            lines=attach(["Şu pahalı kutudan da söyleyelim.", "Söyle."]),
            motion=2.0,
            location_path=interior,
            ref_map=ref_map,
            public_lookup=lookup,
        ),
        _fill_scene(
            scene_id="HF3_birko_slips",
            visible=["birko"],
            offscreen=[],
            action=(
                "A fully clothed adult man notices a receipt, stands, and casually "
                "walks out of frame."
            ),
            camera="medium shot, Birko stands and walks out of frame",
            props=["receipt"],
            lines=attach([], include_bible=False),
            motion=6.0,
            location_path=interior,
            ref_map=ref_map,
            public_lookup=lookup,
            include_location=False,
            prompt_override=HF3_REVISION_3_PROMPT,
            prompt_revision=3,
            prompt_revision_reason=HF3_REVISION_3_REASON,
            prompt_history=[
                {
                    "revision": 1,
                    "prompt": ORIGINAL_HF3_VIDEO_PROMPT,
                    "reason": "original failed paid attempt",
                },
                {
                    "revision": 2,
                    "prompt": HF3_REVISION_2_VIDEO_PROMPT,
                    "reason": PROMPT_REVISION_REASON,
                },
            ],
        ),
        _fill_scene(
            scene_id="HF4_muge_kemal",
            visible=["muge"],
            offscreen=["kemal"],
            action=(
                "Müge looks at the expensive donut box and receipt, asks who ordered it, "
                "listens to offscreen Kemal, then answers about the price."
            ),
            camera="reaction shot on Müge; Kemal remains offscreen",
            props=["receipt", "premium donut box"],
            lines=attach(
                [
                    "Bu özel kutuyu kim söyledi?",
                    "Kocan kaçmış, sen kutuyu soruyorsun!",
                    "Fiyatını gördün mü?",
                ],
                include_bible=False,
                voice_overrides={
                    "muge": HF4_MUGE_VOICE,
                    "kemal": HF4_KEMAL_OFFSCREEN_VOICE,
                },
            ),
            motion=1.2,
            location_path=interior,
            ref_map=ref_map,
            public_lookup=lookup,
            include_location=False,
            prompt_override=HF4_REVISION_3_PROMPT,
            prompt_revision=3,
            prompt_revision_reason=HF4_REVISION_3_REASON,
            prompt_history=[
                {
                    "revision": 1,
                    "prompt": ORIGINAL_HF4_VIDEO_PROMPT,
                    "reason": "original failed paid attempt",
                },
                {
                    "revision": 2,
                    "prompt": HF4_REVISION_2_VIDEO_PROMPT,
                    "reason": PROMPT_REVISION_REASON,
                },
            ],
        ),
        _fill_scene(
            scene_id="HF5_erni",
            visible=["erni", "kemal"],
            offscreen=["muge"],
            action=(
                "Erni leans to Müge first, then turns the same sweet smile on Kemal and "
                "sets the bill in front of him."
            ),
            camera="close two-shot Erni and Kemal",
            props=["receipt"],
            lines=attach(
                [
                    "Sen karışma baby, Kemal kapatır.",
                    "Sen kapat, Müge'yle ben bölüşürüm.",
                    "Şimdi bölüşelim.",
                ]
            ),
            motion=1.2,
            location_path=interior,
            ref_map=ref_map,
            public_lookup=lookup,
        ),
        _fill_scene(
            scene_id="HF6_musti",
            visible=["musti", "kemal"],
            offscreen=[],
            action="Musti rage-baits Kemal across the table; Kemal's face breaks.",
            camera="tight reverse on Musti then Kemal",
            props=["receipt"],
            lines=attach(
                [
                    "Çocukluk arkadaşını bir hesap için mi sileceksin?",
                    "Sen de mi?",
                    "Abi ya, ben berbat bi insan değilim.",
                ]
            ),
            motion=1.0,
            location_path=interior,
            ref_map=ref_map,
            public_lookup=lookup,
        ),
        _fill_scene(
            scene_id="HF7_kemal_pays",
            visible=["kemal"],
            offscreen=["musti", "muge", "hg"],
            action=(
                "Nobody else produces money. Kemal taps his card on the POS. Müge's box lid "
                "lifts at the edge of frame: last slot empty. He calls Birko."
            ),
            camera="Kemal and POS, brief insert of empty box",
            props=["POS", "premium donut box", "phone"],
            lines=attach(["Tamam. Ödüyorum. Payınızı bugün atıyorsunuz."]),
            motion=4.0,
            location_path=interior,
            ref_map=ref_map,
            public_lookup=lookup,
        ),
        _fill_scene(
            scene_id="HF8_payoff",
            visible=["birko"],
            offscreen=["kemal"],
            action=(
                "Outside on the café bench. Birko answers, says almost nothing, hangs up, "
                "and calmly bites the last donut. Stay on him."
            ),
            camera="exterior bench, café window behind him",
            props=["last donut", "phone"],
            lines=attach(["Birko! Ben sadece su içtim!", "Afiyet olsun."]),
            motion=2.5,
            location_path=exterior,
            ref_map=ref_map,
            public_lookup=lookup,
            exterior=True,
        ),
    ]
    if not 6 <= len(scenes) <= 8:
        raise ProductError("higgsfield plan must have 6–8 scenes")
    if any(len(scene.visible_characters) > MAX_VISIBLE_CAST for scene in scenes):
        raise ProductError("visible cast exceeds 3")
    used_lines = [item.text for scene in scenes for item in scene.dialogue_lines]
    expected_lines = [line.text for line in spec.dialogue_lines]
    if used_lines != expected_lines:
        raise ProductError("higgsfield plan must reuse every existing dialogue line in order")
    missing = sum(1 for scene in scenes for item in scene.dialogue_lines if item.missing_tts)
    expected = usd_round(sum(scene.expected_usd for scene in scenes))
    reserved = usd_round(sum(scene.reserved_usd for scene in scenes))
    if reserved - 1e-9 > SIMPLE_VIDEO_HARD_CAP_USD:
        raise ProductError(
            f"STOP BEFORE HTTP: reserved ${reserved:.4f} exceeds "
            f"hard cap ${SIMPLE_VIDEO_HARD_CAP_USD:.2f}"
        )
    return HiggsfieldScenePlan(
        title=spec.title,
        scenes=scenes,
        canonical_refs={slug: row["use"] for slug, row in report.items()},
        expected_usd=expected,
        reserved_usd=reserved,
        cap_ok=reserved <= SIMPLE_VIDEO_HARD_CAP_USD,
        missing_tts_count=missing,
        native_audio=True,
        external_tts=False,
    )


def format_higgsfield_review(
    plan: HiggsfieldScenePlan,
    ref_report: dict[str, dict[str, str]],
) -> str:
    lines = [
        "# Episode 2 Higgsfield scene review",
        "",
        "Source: existing ensemble story `episode_2_story_spec.json` (Sadece Su).",
        "Not the 28-shot animatic. Not a new Astra script.",
        "Seedance 2.5 native audio experiment. Existing TTS WAVs are fallback only.",
        "",
        f"native_audio={str(plan.native_audio).lower()}",
        f"external_tts={str(plan.external_tts).lower()}",
        "",
        "## Canonical references (do not silently swap)",
        "",
    ]
    for slug, row in ref_report.items():
        lines.append(f"- **{slug}**: `{row['use']}`")
        if row.get("custom_source"):
            lines.append(f"  - custom upload: `{row['custom_source']}`")
        if row.get("v1_archive"):
            lines.append(f"  - old generated archive: `{row['v1_archive']}`")
    lines.extend(["", "## Scenes", ""])
    for scene in plan.scenes:
        spoken = "; ".join(
            f"{_display_name(item.speaker)}: {item.text}" for item in scene.dialogue_lines
        )
        dialogue = spoken or "(action only)"
        refs = ", ".join(scene.character_refs)
        fallback = ", ".join(scene.fallback_tts_paths) or "none (untouched archive)"
        lines.extend(
            [
                f"### {scene.scene_id}",
                f"- duration: {scene.duration}s",
                f"- native_audio={str(scene.native_audio).lower()}",
                f"- external_tts={str(scene.external_tts).lower()}",
                f"- generate_audio={str(scene.generate_audio).lower()}",
                f"- dialogue: {dialogue}",
                f"- visible: {', '.join(scene.visible_characters)}",
                f"- offscreen: {', '.join(scene.offscreen_speakers) or '—'}",
                f"- refs: {refs}",
                f"- location_ref: {scene.location_ref or '—'}",
                f"- action: {scene.action}",
                f"- camera: {scene.camera_intent}",
                f"- model: {scene.provider}/{scene.model}",
                f"- video_prompt: {scene.video_prompt}",
                "- seedance_audio: native generate_audio (no mixed OpenAI TTS)",
                f"- fallback_tts: {fallback}",
                f"- expected_usd: {scene.expected_usd}",
                f"- fingerprint: `{scene.request_fingerprint[:16]}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Totals",
            "",
            f"expected_usd={plan.expected_usd}",
            f"reserved_usd={plan.reserved_usd}",
            f"hard_cap_usd={plan.hard_cap_usd}",
            f"cap_ok={plan.cap_ok}",
            f"native_audio={str(plan.native_audio).lower()}",
            f"external_tts={str(plan.external_tts).lower()}",
            f"missing_tts={plan.missing_tts_count}",
            f"scenes={len(plan.scenes)}",
            "new_image_usd=0",
            "new_tts_usd=0",
            "new_external_audio_usd=0",
            "new_llm_usd=0",
            "sunk_astra_simple_script=excluded_from_new_spend",
            "",
            "`uv run docprod birko-episode2 --stage higgsfield-scene-plan`",
            "`uv run docprod birko-episode2 --stage higgsfield-scene-generate --confirm-paid`",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def format_higgsfield_cli_cost_lines(payload: dict[str, object]) -> tuple[str, str]:
    present = payload.get("higgsfield_credentials_present")
    if present is None:
        nested = payload.get("plan")
        if isinstance(nested, dict):
            present = nested.get("higgsfield_credentials_present")
    totals = (
        f"expected_total={payload.get('expected_usd')} "
        f"reserved_total={payload.get('reserved_usd')} "
        f"hard_cap_usd={payload.get('hard_cap_usd')} cap_ok={payload.get('cap_ok')}"
    )
    creds = f"higgsfield_credentials_present={str(bool(present)).lower()}"
    return totals, creds


def higgsfield_plan_fingerprint(plan: HiggsfieldScenePlan) -> str:
    payload = {
        "scene_ids": [scene.scene_id for scene in plan.scenes],
        "durations": [int(scene.duration) for scene in plan.scenes],
        "expected_usd": plan.expected_usd,
        "reserved_usd": plan.reserved_usd,
        "hard_cap_usd": plan.hard_cap_usd,
        "cap_ok": plan.cap_ok,
        "native_audio": plan.native_audio,
        "external_tts": plan.external_tts,
        "bodies": [
            {
                "scene_id": scene.scene_id,
                "model": scene.model,
                "prompt": scene.request_body.get("prompt"),
                "duration": scene.request_body.get("duration"),
                "generate_audio": scene.request_body.get("generate_audio"),
                "aspect_ratio": scene.request_body.get("aspect_ratio"),
                "resolution": scene.request_body.get("resolution"),
                "has_audio_urls": "audio_urls" in scene.request_body,
                "image_names": [
                    Path(urlparse(url).path).name
                    for url in collect_request_input_urls(scene.request_body)
                ],
            }
            for scene in plan.scenes
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _episode_remote_input_urls(plan: HiggsfieldScenePlan) -> list[str]:
    urls: list[str] = []
    for scene in plan.scenes:
        for asset in scene.input_assets:
            remote = str(asset.get("remote_https_url") or "").strip()
            if remote:
                urls.append(remote)
        urls.extend(collect_request_input_urls(scene.request_body))
    unique = list(dict.fromkeys(urls))
    for url in unique:
        assert_https_input_url(url)
        if "/api/v1/public-inputs/" in url:
            raise ProductError(
                "STOP BEFORE PAID HTTP: FastAPI public-inputs URLs must not be used"
            )
        if "/hf-in/" not in url:
            raise ProductError(
                "STOP BEFORE PAID HTTP: Episode 2 inputs must use static /hf-in/ URLs"
            )
    return unique


def higgsfield_live_stop_reasons(
    *,
    series_slug: str,
    episode_number: int,
    stage: str,
    confirm_paid: bool,
    plan: HiggsfieldScenePlan,
    settings: Settings | None = None,
    require_confirm_paid: bool = True,
    approved_fingerprint: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    if series_slug.strip().casefold() != "birko" or int(episode_number) != 2:
        reasons.append("series/episode is not birko episode 2")
    if stage.strip().lower() != "higgsfield-scene-generate":
        reasons.append("stage is not higgsfield-scene-generate")
    if require_confirm_paid and not confirm_paid:
        reasons.append("confirm_paid is false")
    if not higgsfield_credentials_present(settings):
        reasons.append("HF_API_KEY is not present")
    if tuple(scene.scene_id for scene in plan.scenes) != APPROVED_SCENE_IDS:
        reasons.append("scene ids do not match the approved 8-scene plan")
    if tuple(int(scene.duration) for scene in plan.scenes) != APPROVED_DURATIONS:
        reasons.append("durations do not match the approved 8-scene plan")
    if abs(float(plan.expected_usd) - APPROVED_EXPECTED_USD) > 1e-9:
        reasons.append(f"expected_total is not {APPROVED_EXPECTED_USD}")
    if abs(float(plan.reserved_usd) - APPROVED_RESERVED_USD) > 1e-9:
        reasons.append(f"reserved_total is not {APPROVED_RESERVED_USD}")
    if abs(float(plan.hard_cap_usd) - APPROVED_HARD_CAP_USD) > 1e-9:
        reasons.append("hard_cap_usd is not 12.0")
    if plan.cap_ok is not True:
        reasons.append("cap_ok is not True")
    if float(plan.reserved_usd) - 1e-9 > APPROVED_HARD_CAP_USD:
        reasons.append("reserved cost exceeds $12")
    expected = APPROVED_PLAN_FINGERPRINT if approved_fingerprint is None else approved_fingerprint
    actual = higgsfield_plan_fingerprint(plan)
    if not expected or actual != expected:
        reasons.append("plan fingerprint mismatch")
    return reasons


def assert_higgsfield_live_authorized(
    *,
    series_slug: str,
    episode_number: int,
    stage: str,
    confirm_paid: bool,
    plan: HiggsfieldScenePlan,
    settings: Settings | None = None,
    approved_fingerprint: str | None = None,
) -> None:
    reasons = higgsfield_live_stop_reasons(
        series_slug=series_slug,
        episode_number=episode_number,
        stage=stage,
        confirm_paid=confirm_paid,
        plan=plan,
        settings=settings,
        require_confirm_paid=True,
        approved_fingerprint=approved_fingerprint,
    )
    if reasons:
        raise ProductError("STOP BEFORE HTTP: " + "; ".join(reasons))


def _load_ledger(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"operations": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"operations": {}}
    if not isinstance(payload.get("operations"), dict):
        payload["operations"] = {}
    return payload


def _save_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _clip_path(scene_id: str, *, root: Path | None = None) -> Path:
    return (root or _repo_root()) / HIGGSFIELD_CLIPS_RELATIVE / f"{scene_id}.mp4"


def _update_op(ledger: dict[str, Any], scene_id: str, **fields: Any) -> None:
    ops = ledger.setdefault("operations", {})
    row = ops.get(scene_id) if isinstance(ops.get(scene_id), dict) else {}
    merged = {**row, **fields}
    ops[scene_id] = merged


def _persist_probe(row: dict[str, Any], path: Path) -> dict[str, Any]:
    info = probe_media(path)
    row["duration"] = info.duration
    row["width"] = info.width
    row["height"] = info.height
    row["video_codec"] = info.video_codec
    row["audio_codec"] = info.audio_codec
    row["audio_present"] = bool(info.has_audio)
    row["has_video"] = bool(info.has_video)
    return row


def _playable_clip(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 64:
        return False
    try:
        info = probe_media(path)
    except Exception:
        return False
    return bool(info.has_video and info.duration > 0.2)


def _subtitle_cues(plan: HiggsfieldScenePlan, clips: list[Path]) -> list[DialogueCue]:
    cues: list[DialogueCue] = []
    offset = 0.0
    for scene, clip in zip(plan.scenes, clips, strict=True):
        duration = probe_media(clip).duration if clip.is_file() else float(scene.duration)
        lines = scene.dialogue_lines
        if lines:
            slice_len = duration / len(lines)
            for index, line in enumerate(lines):
                start = offset + index * slice_len
                end = offset + (index + 1) * slice_len
                cues.append(
                    DialogueCue(
                        speaker=line.speaker,
                        source=clip,
                        start=start,
                        duration=slice_len,
                        end=end,
                        text=line.text,
                        shot_id=scene.scene_id,
                        line_id=f"{scene.scene_id}-{index}",
                    )
                )
        offset += duration
    return cues


def concat_higgsfield_episode(
    plan: HiggsfieldScenePlan,
    *,
    root: Path | None = None,
) -> Path:
    base = root or _repo_root()
    clips = [_clip_path(scene.scene_id, root=base) for scene in plan.scenes]
    missing = [str(path) for path in clips if not _playable_clip(path)]
    if missing:
        raise ProductError(f"cannot concat; missing or unplayable clips: {missing}")
    dest = base / HIGGSFIELD_FINAL_RELATIVE
    dest.parent.mkdir(parents=True, exist_ok=True)
    concat = dest.with_name(dest.stem + "_concat.mp4")
    concat_simple_scenes(clips, concat)
    cues = _subtitle_cues(plan, clips)
    ass_path = dest.with_name("higgsfield_episode.ass")
    write_timed_subtitles(cues, ass_path)
    probed = probe_media(concat)
    staged = dest.with_name(dest.stem + "_burn.mp4")
    cmd = [
        "-i",
        str(concat),
        "-vf",
        ffmpeg_subtitle_filter(ass_path),
        "-c:a",
        "copy",
        str(staged),
    ]
    if "-shortest" in cmd:
        raise ProductError("higgsfield subtitle burn must not use -shortest")
    run_ffmpeg(cmd, timeout=180)
    staged.replace(dest)
    if probe_media(dest).duration + 0.75 < probed.duration:
        raise ProductError("higgsfield concat collapsed duration")
    return dest


def _raw_provider_status(payload: dict[str, Any]) -> str:
    raw = payload.get("status")
    if isinstance(raw, dict):
        raw = raw.get("status") or raw.get("state")
    if not raw:
        raw = payload.get("state")
    if not raw and isinstance(payload.get("request"), dict):
        return _raw_provider_status(payload["request"])
    return str(raw or "")


def _http_status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def _invoke_result(
    result_fn: Callable[..., dict[str, Any]],
    request_id: str,
    *,
    settings: Settings | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        extra = result_fn(request_id, settings=settings, payload=payload)
    except TypeError:
        extra = result_fn(request_id, settings=settings)
    return extra if isinstance(extra, dict) else {}


def _download_completed_clip(
    *,
    scene_id: str,
    request_id: str,
    payload: dict[str, Any],
    result_fn: Callable[..., dict[str, Any]],
    download_fn: Callable[..., Path],
    settings: Settings | None,
    root: Path,
) -> tuple[Path | None, str, dict[str, Any]]:
    merged = dict(payload)
    url = extract_higgsfield_video_url(merged)
    if not url:
        extra = _invoke_result(result_fn, request_id, settings=settings, payload=payload)
        if extra:
            merged = {**merged, **extra}
        url = extract_higgsfield_video_url(merged)
    if not url:
        return None, "", merged
    dest = _clip_path(scene_id, root=root)
    download_fn(url, dest)
    return dest, url, merged


def poll_existing_higgsfield_request(
    *,
    scene_id: str,
    request_id: str,
    ledger: dict[str, Any],
    ledger_path: Path,
    settings: Settings | None,
    root: Path,
    status_fn: Callable[..., dict[str, Any]],
    result_fn: Callable[..., dict[str, Any]],
    download_fn: Callable[..., Path],
    sleeper: Callable[[float], None],
    now_fn: Callable[[], float],
    deadline: float,
    interval: float,
) -> str:
    wait = interval
    while now_fn() < deadline:
        state = poll_higgsfield_request_once(
            scene_id=scene_id,
            request_id=request_id,
            ledger=ledger,
            ledger_path=ledger_path,
            settings=settings,
            root=root,
            status_fn=status_fn,
            result_fn=result_fn,
            download_fn=download_fn,
        )
        if state not in {"SUBMITTED", "PROCESSING"}:
            return state
        sleeper(wait)
        wait = min(POLL_MAX_INTERVAL_SECONDS, wait * 1.3)
    _save_ledger(ledger_path, ledger)
    return str(ledger["operations"][scene_id].get("state") or "SUBMITTED")


def poll_higgsfield_request_once(
    *,
    scene_id: str,
    request_id: str,
    ledger: dict[str, Any],
    ledger_path: Path,
    settings: Settings | None,
    root: Path,
    status_fn: Callable[..., dict[str, Any]],
    result_fn: Callable[..., dict[str, Any]],
    download_fn: Callable[..., Path],
) -> str:
    payload = status_fn(request_id, settings=settings)
    raw_status = _raw_provider_status(payload)
    if not raw_status:
        extra = _invoke_result(result_fn, request_id, settings=settings, payload=payload)
        if extra:
            payload = {**payload, **extra}
            raw_status = _raw_provider_status(payload)
    kind = classify_higgsfield_status(raw_status)
    lifecycle = sanitize_higgsfield_lifecycle(payload, request_id=request_id)
    _update_op(
        ledger,
        scene_id,
        request_id=request_id,
        provider_status=raw_status or kind,
        provider_lifecycle=lifecycle,
    )
    if kind in {"queued"}:
        _update_op(ledger, scene_id, state="SUBMITTED")
        _save_ledger(ledger_path, ledger)
        return "SUBMITTED"
    if kind == "in_progress":
        _update_op(ledger, scene_id, state="PROCESSING")
        _save_ledger(ledger_path, ledger)
        return "PROCESSING"
    if kind == "completed":
        try:
            dest, url, merged = _download_completed_clip(
                scene_id=scene_id,
                request_id=request_id,
                payload=payload,
                result_fn=result_fn,
                download_fn=download_fn,
                settings=settings,
                root=root,
            )
        except Exception as exc:
            if _http_status_code(exc) == 405:
                _update_op(
                    ledger,
                    scene_id,
                    state="UNCERTAIN",
                    error="result retrieval HTTP 405; not resubmitting",
                    provider_lifecycle=lifecycle,
                )
                _save_ledger(ledger_path, ledger)
                return "UNCERTAIN"
            raise
        lifecycle = sanitize_higgsfield_lifecycle(merged, request_id=request_id)
        if dest is None or not _playable_clip(dest):
            _update_op(
                ledger,
                scene_id,
                state="UNCERTAIN",
                error="completed without playable video",
                video_url=url,
                provider_lifecycle=lifecycle,
            )
            _save_ledger(ledger_path, ledger)
            return "UNCERTAIN"
        row = {
            "state": "SUCCEEDED",
            "request_id": request_id,
            "provider_status": raw_status or "completed",
            "artifact_path": str(dest),
            "video_url": url,
            "downloaded": True,
            "provider_lifecycle": lifecycle,
        }
        row.update(_persist_probe(row, dest))
        _update_op(ledger, scene_id, **row)
        _save_ledger(ledger_path, ledger)
        return "SUCCEEDED"
    if kind == "failed":
        _update_op(
            ledger,
            scene_id,
            state="FAILED",
            error=str(payload.get("error") or raw_status or "failed"),
        )
        _save_ledger(ledger_path, ledger)
        return "FAILED"
    if kind == "canceled":
        _update_op(ledger, scene_id, state="CANCELLED")
        _save_ledger(ledger_path, ledger)
        return "CANCELLED"
    _update_op(ledger, scene_id, state="UNCERTAIN", error=f"ambiguous status {raw_status!r}")
    _save_ledger(ledger_path, ledger)
    return "UNCERTAIN"


def _archive_failed_operation(ledger: dict[str, Any], scene_id: str) -> None:
    ops = ledger.setdefault("operations", {})
    row = ops.get(scene_id) if isinstance(ops.get(scene_id), dict) else {}
    history = list(row.get("history") or [])
    snapshot = {key: value for key, value in row.items() if key != "history"}
    if snapshot:
        history.append(snapshot)
    failed_ids = list(row.get("failed_request_ids") or [])
    request_id = str(row.get("request_id") or "").strip()
    if request_id and request_id not in failed_ids:
        failed_ids.append(request_id)
    ops[scene_id] = {
        "state": "NOT_STARTED",
        "history": history,
        "failed_request_ids": failed_ids,
        "model": row.get("model"),
    }


def recover_higgsfield_jobs(
    plan: HiggsfieldScenePlan,
    *,
    settings: Settings | None = None,
    allow_submit: bool = False,
    retry_failed: bool = False,
    confirm_paid: bool = False,
    submit: Callable[..., dict[str, Any]] | None = None,
    status_fn: Callable[..., dict[str, Any]] | None = None,
    result_fn: Callable[..., dict[str, Any]] | None = None,
    download_fn: Callable[..., Path] | None = None,
    sleeper: Callable[[float], None] | None = None,
    now_fn: Callable[[], float] | None = None,
    deadline_seconds: float = RESUME_DEADLINE_SECONDS,
    root: Path | None = None,
    only_scenes: frozenset[str] | None = None,
) -> dict[str, Any]:
    base = root or _repo_root()
    ledger_path = base / HIGGSFIELD_LEDGER_RELATIVE
    ledger = _load_ledger(ledger_path)
    status = status_fn or higgsfield_request_status
    result = result_fn or higgsfield_request_result
    downloader = download_fn or download_higgsfield_media
    sleep = sleeper or time.sleep
    now = now_fn or time.time
    deadline = now() + deadline_seconds
    generation_posts = 0
    status_calls = 0
    result_calls = 0

    def counted_status(request_id: str, *, settings: Settings | None = None) -> dict[str, Any]:
        nonlocal status_calls
        status_calls += 1
        return status(request_id, settings=settings)

    def counted_result(
        request_id: str,
        *,
        settings: Settings | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        nonlocal result_calls
        result_calls += 1
        return _invoke_result(result, request_id, settings=settings, payload=payload or {})

    def poll_one(scene_id: str, request_id: str) -> str:
        return poll_existing_higgsfield_request(
            scene_id=scene_id,
            request_id=request_id,
            ledger=ledger,
            ledger_path=ledger_path,
            settings=settings,
            root=base,
            status_fn=counted_status,
            result_fn=counted_result,
            download_fn=downloader,
            sleeper=sleep,
            now_fn=now,
            deadline=deadline,
            interval=POLL_INTERVAL_SECONDS,
        )

    poster = submit or submit_higgsfield_json
    selected = only_scenes
    for scene in plan.scenes:
        row = ledger["operations"].get(scene.scene_id)
        row = row if isinstance(row, dict) else {}
        state = str(row.get("state") or "")
        request_id = str(row.get("request_id") or "").strip()
        clip = _clip_path(scene.scene_id, root=base)
        if state == "SUCCEEDED" and _playable_clip(clip):
            continue
        if selected is not None and scene.scene_id not in selected:
            continue
        if state in {"UNCERTAIN", "CANCELLED"}:
            continue
        if state == "FAILED" and not retry_failed:
            continue
        if state == "FAILED" and retry_failed:
            if selected is None and is_higgsfield_safety_failure(row):
                continue
            _archive_failed_operation(ledger, scene.scene_id)
            _save_ledger(ledger_path, ledger)
            state = "NOT_STARTED"
            request_id = ""
        if request_id and state in {"", "SUBMITTED", "PROCESSING", "SUCCEEDED", "NOT_STARTED"}:
            poll_one(scene.scene_id, request_id)
            row = ledger["operations"].get(scene.scene_id) or {}
            if str(row.get("state")) == "SUCCEEDED" and _playable_clip(clip):
                continue
            if str(row.get("state")) in {"FAILED", "CANCELLED", "UNCERTAIN"}:
                continue
            if now() > deadline:
                break
            continue
        if not allow_submit:
            continue
        if now() > deadline:
            break
        assert_https_request_body(scene.request_body)
        posted = poster(
            url=str(SEEDANCE_CONTRACTS[scene.model]["url"]),
            body=scene.request_body,
            confirm_paid=confirm_paid,
            settings=settings,
        )
        generation_posts += 1
        request_id = str(posted.get("request_id") or "")
        preserved = ledger["operations"].get(scene.scene_id) if isinstance(
            ledger["operations"].get(scene.scene_id), dict
        ) else {}
        prompt_history = list(preserved.get("prompt_history") or [])
        for item in scene.prompt_history:
            if item not in prompt_history:
                prompt_history.append(item)
        _update_op(
            ledger,
            scene.scene_id,
            state="SUBMITTED",
            request_id=request_id,
            model=scene.model,
            history=list(preserved.get("history") or []),
            failed_request_ids=list(preserved.get("failed_request_ids") or []),
            prompt_revision=scene.prompt_revision,
            prompt_revision_reason=scene.prompt_revision_reason,
            prompt_history=prompt_history,
            submitted_prompt=scene.video_prompt,
        )
        _save_ledger(ledger_path, ledger)
        if request_id:
            poll_one(scene.scene_id, request_id)
        if now() > deadline:
            break

    ops = ledger.get("operations") if isinstance(ledger.get("operations"), dict) else {}
    succeeded = [
        scene.scene_id
        for scene in plan.scenes
        if isinstance(ops.get(scene.scene_id), dict)
        and ops[scene.scene_id].get("state") == "SUCCEEDED"
        and _playable_clip(_clip_path(scene.scene_id, root=base))
    ]
    final = None
    if len(succeeded) == len(plan.scenes):
        final = str(concat_higgsfield_episode(plan, root=base))
    selected = selected_scene_cost_report(plan, only_scenes, ledger=ledger, root=base)
    return {
        "ledger": ledger,
        "ledger_path": str(ledger_path),
        "generation_posts": generation_posts,
        "status_http_calls": status_calls,
        "result_http_calls": result_calls,
        "provider_http_calls": status_calls + result_calls,
        "succeeded": succeeded,
        "final": final,
        **selected,
    }


def execute_higgsfield_scene_plan(
    *,
    refs: list[dict[str, object]],
    settings: Settings | None = None,
) -> dict[str, object]:
    spec = load_existing_story()
    plan = build_higgsfield_scenes(spec, refs, settings=settings)
    report = canonical_ref_report(refs)
    root = _repo_root()
    plan_path = root / HIGGSFIELD_PLAN_RELATIVE
    review_path = root / HIGGSFIELD_REVIEW_RELATIVE
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    payload = plan.model_dump()
    payload["higgsfield_credentials_present"] = higgsfield_credentials_present(settings)
    payload["native_audio"] = True
    payload["external_tts"] = False
    payload["native_audio_policy"] = "seedance_native_dialogue"
    payload["fallback_model"] = SIMPLE_SECONDARY_MODEL
    payload["plan_fingerprint"] = higgsfield_plan_fingerprint(plan)
    payload["execute"] = False
    plan_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    review_path.write_text(format_higgsfield_review(plan, report), encoding="utf-8")
    credentials_present = bool(payload["higgsfield_credentials_present"])
    return {
        "stage": "higgsfield-scene-plan",
        "plan": payload,
        "artifacts": {"plan": str(plan_path), "review": str(review_path)},
        "canonical_refs": report,
        "scene_count": len(plan.scenes),
        "expected_usd": plan.expected_usd,
        "reserved_usd": plan.reserved_usd,
        "hard_cap_usd": plan.hard_cap_usd,
        "cap_ok": plan.cap_ok,
        "plan_fingerprint": payload["plan_fingerprint"],
        "higgsfield_credentials_present": credentials_present,
        "new_image_usd": 0.0,
        "new_tts_usd": 0.0,
        "new_external_audio_usd": 0.0,
        "new_llm_usd": 0.0,
        "provider_http_calls": 0,
        "media_calls": 0,
        "stars": 0,
        "execute": False,
    }


def execute_higgsfield_scene_preflight(
    *,
    refs: list[dict[str, object]],
    settings: Settings | None = None,
    series_slug: str = "birko",
    episode_number: int = 2,
    url_probe: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, object]:
    planned = execute_higgsfield_scene_plan(refs=refs, settings=settings)
    plan = build_higgsfield_scenes(load_existing_story(), refs, settings=settings)
    reasons = higgsfield_live_stop_reasons(
        series_slug=series_slug,
        episode_number=episode_number,
        stage="higgsfield-scene-generate",
        confirm_paid=True,
        plan=plan,
        settings=settings,
        require_confirm_paid=False,
    )
    unique_urls = _episode_remote_input_urls(plan)
    remote_ok = False
    try:
        preflight_input_urls(unique_urls, probe=url_probe)
        remote_ok = True
    except ProductError as exc:
        reasons = [*reasons, str(exc)]
    authorized = not reasons and remote_ok
    return {
        **planned,
        "stage": "higgsfield-scene-preflight",
        "ready_for_live": authorized,
        "live_post_authorized": authorized,
        "confirm_paid_required": True,
        "native_audio": True,
        "external_tts": False,
        "model": SIMPLE_PRIMARY_MODEL,
        "i2v_model": SIMPLE_I2V_MODEL,
        "i2v_usd_per_second": 0.144,
        "r2v_usd_per_second": 0.1728,
        "series": series_slug,
        "episode": episode_number,
        "stop_reasons": reasons,
        "input_url_count": len(unique_urls),
        "remote_inputs": len(unique_urls),
        "remote_inputs_reachable": len(unique_urls) if remote_ok else 0,
        "remote_urls_reachable": remote_ok,
        "provider_http_calls": 0,
        "generation_posts": 0,
        "execute": False,
    }


def execute_higgsfield_scene_generate(
    *,
    confirm_paid: bool,
    refs: list[dict[str, object]],
    execute_calls: bool = False,
    settings: Settings | None = None,
    series_slug: str = "birko",
    episode_number: int = 2,
    submit: Callable[..., dict[str, Any]] | None = None,
    approved_fingerprint: str | None = None,
    status_fn: Callable[..., dict[str, Any]] | None = None,
    result_fn: Callable[..., dict[str, Any]] | None = None,
    download_fn: Callable[..., Path] | None = None,
    sleeper: Callable[[float], None] | None = None,
    now_fn: Callable[[], float] | None = None,
    deadline_seconds: float = RESUME_DEADLINE_SECONDS,
    root: Path | None = None,
    retry_failed: bool = False,
    url_probe: Callable[[str], dict[str, Any]] | None = None,
    only_scenes: frozenset[str] | str | None = None,
) -> dict[str, object]:
    if not confirm_paid:
        raise PaidApiNotConfirmedError(
            "higgsfield-scene-generate requires --confirm-paid after higgsfield-scene-plan"
        )
    planned = execute_higgsfield_scene_plan(refs=refs, settings=settings)
    plan = build_higgsfield_scenes(load_existing_story(), refs, settings=settings)
    assert_higgsfield_live_authorized(
        series_slug=series_slug,
        episode_number=episode_number,
        stage="higgsfield-scene-generate",
        confirm_paid=confirm_paid,
        plan=plan,
        settings=settings,
        approved_fingerprint=approved_fingerprint,
    )
    selected_ids = parse_only_scenes(only_scenes) if isinstance(only_scenes, str) else only_scenes
    unique_urls = _episode_remote_input_urls(plan)
    if execute_calls:
        preflight_input_urls(unique_urls, probe=url_probe)
    if not execute_calls:
        return {
            **planned,
            "stage": "higgsfield-scene-generate",
            "execute": False,
            "live_post_authorized": True,
            **selected_scene_cost_report(plan, selected_ids),
        }
    recovered = recover_higgsfield_jobs(
        plan,
        settings=settings,
        allow_submit=True,
        retry_failed=retry_failed,
        confirm_paid=confirm_paid,
        submit=submit,
        status_fn=status_fn,
        result_fn=result_fn,
        download_fn=download_fn,
        sleeper=sleeper,
        now_fn=now_fn,
        deadline_seconds=deadline_seconds,
        root=root,
        only_scenes=selected_ids,
    )
    ops = recovered["ledger"].get("operations") if isinstance(recovered["ledger"], dict) else {}
    states = {
        scene.scene_id: (ops.get(scene.scene_id) or {}).get("state")
        for scene in plan.scenes
    }
    return {
        **planned,
        "stage": "higgsfield-scene-generate",
        "execute": True,
        "live_post_authorized": True,
        "provider_http_calls": recovered["provider_http_calls"],
        "status_http_calls": recovered["status_http_calls"],
        "result_http_calls": recovered["result_http_calls"],
        "generation_posts": recovered["generation_posts"],
        "media_calls": recovered["generation_posts"],
        "states": states,
        "final": recovered["final"],
        "selected_scene_ids": recovered.get("selected_scene_ids") or [],
        "selected_expected_total": recovered.get("selected_expected_total") or 0.0,
        "selected_generation_posts_max": recovered.get("selected_generation_posts_max") or 0,
        "artifacts": {
            **(planned.get("artifacts") if isinstance(planned.get("artifacts"), dict) else {}),
            "ledger": recovered["ledger_path"],
            "clips": str((root or _repo_root()) / HIGGSFIELD_CLIPS_RELATIVE),
            "final": recovered["final"],
        },
    }


def execute_higgsfield_scene_resume(
    *,
    refs: list[dict[str, object]],
    settings: Settings | None = None,
    status_fn: Callable[..., dict[str, Any]] | None = None,
    result_fn: Callable[..., dict[str, Any]] | None = None,
    download_fn: Callable[..., Path] | None = None,
    sleeper: Callable[[float], None] | None = None,
    now_fn: Callable[[], float] | None = None,
    deadline_seconds: float = RESUME_DEADLINE_SECONDS,
    root: Path | None = None,
) -> dict[str, object]:
    plan = build_higgsfield_scenes(load_existing_story(), refs, settings=settings)
    recovered = recover_higgsfield_jobs(
        plan,
        settings=settings,
        allow_submit=False,
        status_fn=status_fn,
        result_fn=result_fn,
        download_fn=download_fn,
        sleeper=sleeper,
        now_fn=now_fn,
        deadline_seconds=deadline_seconds,
        root=root,
    )
    ops = recovered["ledger"].get("operations") if isinstance(recovered["ledger"], dict) else {}
    states = {
        scene.scene_id: (ops.get(scene.scene_id) or {}).get("state")
        for scene in plan.scenes
    }
    return {
        "stage": "higgsfield-scene-resume",
        "plan": plan.model_dump(),
        "scene_count": len(plan.scenes),
        "expected_usd": plan.expected_usd,
        "reserved_usd": plan.reserved_usd,
        "hard_cap_usd": plan.hard_cap_usd,
        "cap_ok": plan.cap_ok,
        "generation_posts": 0,
        "provider_http_calls": recovered["provider_http_calls"],
        "status_http_calls": recovered["status_http_calls"],
        "result_http_calls": recovered["result_http_calls"],
        "higgsfield_credentials_present": higgsfield_credentials_present(settings),
        "states": states,
        "succeeded": recovered["succeeded"],
        "final": recovered["final"],
        "artifacts": {
            "ledger": recovered["ledger_path"],
            "clips": str((root or _repo_root()) / HIGGSFIELD_CLIPS_RELATIVE),
            "final": recovered["final"],
        },
        "execute": True,
    }


def next_unfinished_higgsfield_scene(
    ledger: dict[str, Any],
    plan: HiggsfieldScenePlan,
) -> str | None:
    ops = ledger.get("operations") if isinstance(ledger.get("operations"), dict) else {}
    for scene in plan.scenes:
        row = ops.get(scene.scene_id) if isinstance(ops, dict) else None
        if not isinstance(row, dict) or row.get("state") != "SUCCEEDED":
            return scene.scene_id
    return None
