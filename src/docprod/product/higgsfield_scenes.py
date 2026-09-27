from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docprod.config import Settings
from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.canary_cost import typical_image_usd, typical_tts_usd, usd_round
from docprod.product.errors import ProductError
from docprod.product.friend_group import FriendGroupStorySpec
from docprod.product.simple_video import (
    MAX_VISIBLE_CAST,
    SIMPLE_PRIMARY_MODEL,
    SIMPLE_SECONDARY_MODEL,
    SIMPLE_VIDEO_HARD_CAP_USD,
    STOCK_VOICES,
)
from docprod.providers.higgsfield import (
    higgsfield_credentials_present,
    seedance_reference_to_video_body,
    seedance_request_fingerprint,
)
from docprod.quality.native_audio import native_audio_use
from docprod.quality.router import estimate_model_cost
from docprod.render.ffmpeg import probe_media
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
        rows.append(
            HiggsfieldDialogue(
                speaker=src.speaker_character_id,
                text=src.text,
                delivery=src.delivery,
                audio_path=str(wav) if wav else "",
                audio_seconds=round(seconds, 3),
                missing_tts=wav is None,
                voice=STOCK_VOICES.get(src.speaker_character_id, ""),
            )
        )
    return rows


def _scene_duration(lines: list[HiggsfieldDialogue], *, motion: float) -> float:
    speech = sum(item.audio_seconds or (max(len(item.text), 8) / 13.0) for item in lines)
    needed = speech + motion
    return round(min(10.0, max(5.0, needed)), 3)


def _prompt(*, action: str, visible: list[str], location: str, moving: str) -> str:
    people = ", ".join(visible)
    return (
        f"9:16 cinematic live-action, continuous motion, no slideshow. "
        f"{location}. Visible: {people}. {action} {moving} "
        f"Turkish café evening, natural light, real acting, keep faces consistent "
        f"with attached reference photos. Do not freeze into a still."
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
    exterior: bool = False,
) -> HiggsfieldScene:
    duration = _scene_duration(lines, motion=motion)
    char_paths = []
    seen: set[str] = set()
    for slug in visible:
        path = ref_map.get(slug)
        if not path or slug in seen:
            continue
        seen.add(slug)
        char_paths.append(path)
    image_urls = [f"file://{path}" for path in char_paths]
    loc = str(location_path) if location_path.is_file() else ""
    if loc and len(char_paths) <= 2:
        image_urls.append(f"file://{loc}")
    audio_urls = [item.audio_path for item in lines if item.audio_path]
    loc_label = (
        "Krispy Kreme exterior bench, same café window wall"
        if exterior
        else "same Krispy Kreme café interior, six-top table, window, door, counter, evening"
    )
    moving = (
        "Hands, eyelines, and body weight keep moving for the full duration; "
        "no dead hold after the last line."
    )
    body = seedance_reference_to_video_body(
        prompt=_prompt(action=action, visible=visible, location=loc_label, moving=moving),
        duration=duration,
        image_urls=image_urls,
        audio_urls=[f"file://{path}" for path in audio_urls] or None,
    )
    shas = [file_sha256(Path(path)) for path in char_paths if Path(path).is_file()]
    if loc and Path(loc).is_file():
        shas.append(file_sha256(Path(loc)))
    audio_shas = [file_sha256(Path(path)) for path in audio_urls if Path(path).is_file()]
    billed = float(body["duration"])
    expected, _conf = estimate_model_cost(SIMPLE_PRIMARY_MODEL, seconds=billed)
    reserved, _rconf = estimate_model_cost(SIMPLE_PRIMARY_MODEL, seconds=min(10.0, billed * 1.2))
    return HiggsfieldScene(
        scene_id=scene_id,
        duration=float(body["duration"]),
        visible_characters=visible,
        offscreen_speakers=offscreen,
        character_refs=char_paths,
        location_ref=loc,
        props=props,
        action=action,
        dialogue_lines=lines,
        camera_intent=camera,
        video_prompt=str(body["prompt"]),
        audio_track=audio_urls,
        request_fingerprint=seedance_request_fingerprint(
            prompt=str(body["prompt"]),
            duration=float(body["duration"]),
            image_shas=shas,
            audio_shas=audio_shas,
        ),
        request_body=body,
        expected_usd=float(expected or 0.0),
        reserved_usd=float(reserved or 0.0),
    )


def build_higgsfield_scenes(
    spec: FriendGroupStorySpec,
    refs: list[dict[str, object]],
    *,
    root: Path | None = None,
) -> HiggsfieldScenePlan:
    base = root or _repo_root()
    report = canonical_ref_report(refs)
    ref_map = {slug: row["use"] for slug, row in report.items() if row["use"]}
    wavs = _wav_index(root=base)
    interior = base / INTERIOR_LOCATION_RELATIVE
    exterior = base / EXTERIOR_LOCATION_RELATIVE

    def attach(texts: list[str]) -> list[HiggsfieldDialogue]:
        return _attach_dialogue(spec, texts, wavs)

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
        ),
        _fill_scene(
            scene_id="HF3_birko_slips",
            visible=["birko", "hg"],
            offscreen=["kemal"],
            action=(
                "Boxes are empty. The bill tray arrives. Everyone leans in. Birko slips out "
                "behind the chairs. HG sees him, stays quiet, slides the receipt toward Kemal."
            ),
            camera="wider table then Birko's hands leaving, HG's look",
            props=["receipt", "premium donut box", "POS"],
            lines=[],
            motion=6.0,
            location_path=interior,
            ref_map=ref_map,
        ),
        _fill_scene(
            scene_id="HF4_muge_kemal",
            visible=["muge", "kemal"],
            offscreen=["hg"],
            action=(
                "Müge grabs the receipt and taps the premium-box price. Kemal points at the exit."
            ),
            camera="shot-reverse at the six-top",
            props=["receipt", "premium donut box"],
            lines=attach(
                [
                    "Bu özel kutuyu kim söyledi?",
                    "Kocan kaçmış, sen kutuyu soruyorsun!",
                    "Fiyatını gördün mü?",
                ]
            ),
            motion=1.2,
            location_path=interior,
            ref_map=ref_map,
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
    video_e = usd_round(sum(scene.expected_usd for scene in scenes))
    video_r = usd_round(sum(scene.reserved_usd for scene in scenes))
    tts_e = usd_round(typical_tts_usd() * max(missing, 0))
    tts_r = usd_round(typical_tts_usd() * max(missing, 0) * 1.5)
    loc_e = 0.0
    loc_r = 0.0
    if not interior.is_file():
        loc_e = typical_image_usd(with_reference=False)
        loc_r = usd_round(loc_e * 1.5)
    expected = usd_round(video_e + tts_e + loc_e)
    reserved = usd_round(video_r + tts_r + loc_r)
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
        spoken = "; ".join(f"{item.speaker}: {item.text}" for item in scene.dialogue_lines)
        dialogue = spoken or "(action only)"
        audio = ", ".join(scene.audio_track) or "none"
        refs = ", ".join(scene.character_refs)
        lines.extend(
            [
                f"### {scene.scene_id}",
                f"- duration: {scene.duration}s",
                f"- dialogue: {dialogue}",
                f"- visible: {', '.join(scene.visible_characters)}",
                f"- offscreen: {', '.join(scene.offscreen_speakers) or '—'}",
                f"- refs: {refs}",
                f"- location_ref: {scene.location_ref or '—'}",
                f"- action: {scene.action}",
                f"- camera: {scene.camera_intent}",
                f"- model: {scene.provider}/{scene.model}",
                f"- video_prompt: {scene.video_prompt}",
                f"- audio: {audio}",
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
            f"missing_tts={plan.missing_tts_count}",
            f"scenes={len(plan.scenes)}",
            "",
            "`uv run docprod birko-episode2 --stage higgsfield-scene-plan`",
            "`uv run docprod birko-episode2 --stage higgsfield-scene-generate --confirm-paid`",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def execute_higgsfield_scene_plan(
    *,
    refs: list[dict[str, object]],
    settings: Settings | None = None,
) -> dict[str, object]:
    spec = load_existing_story()
    plan = build_higgsfield_scenes(spec, refs)
    report = canonical_ref_report(refs)
    root = _repo_root()
    plan_path = root / HIGGSFIELD_PLAN_RELATIVE
    review_path = root / HIGGSFIELD_REVIEW_RELATIVE
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    payload = plan.model_dump()
    payload["higgsfield_credentials_present"] = higgsfield_credentials_present(settings)
    payload["native_audio_policy"] = native_audio_use(
        SIMPLE_PRIMARY_MODEL, needs_character_dialogue=True
    )
    payload["fallback_model"] = SIMPLE_SECONDARY_MODEL
    payload["execute"] = False
    plan_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    review_path.write_text(format_higgsfield_review(plan, report), encoding="utf-8")
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
        "provider_http_calls": 0,
        "media_calls": 0,
        "stars": 0,
        "execute": False,
    }


def execute_higgsfield_scene_generate(
    *,
    confirm_paid: bool,
    refs: list[dict[str, object]],
    execute_calls: bool = False,
    settings: Settings | None = None,
) -> dict[str, object]:
    if not confirm_paid:
        raise PaidApiNotConfirmedError(
            "higgsfield-scene-generate requires --confirm-paid after higgsfield-scene-plan"
        )
    planned = execute_higgsfield_scene_plan(refs=refs, settings=settings)
    if not execute_calls:
        return {**planned, "stage": "higgsfield-scene-generate", "execute": False}
    raise ProductError(
        "STOP BEFORE HTTP: Higgsfield scene payloads are planned; live POST waits "
        "for explicit generation approval"
    )


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
