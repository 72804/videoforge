from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docprod.config import Settings
from docprod.exceptions import PaidApiNotConfirmedError
from docprod.product.birko_bible import GROUP_DYNAMIC, LOCKED_EPISODE_2_ENDING
from docprod.product.canary_cost import typical_image_usd, typical_tts_usd, usd_round
from docprod.product.episode import EpisodeBrief, StoryGenerationPlan
from docprod.product.errors import ProductError
from docprod.providers.higgsfield import (
    KLING_I2V_CONTRACT,
    KLING_MOTION_CONTRACT,
    SEEDANCE_CONTRACTS,
    higgsfield_credentials_present,
    kling_image_to_video_body,
    kling_motion_control_body,
    seedance_reference_to_video_body,
    seedance_request_fingerprint,
)
from docprod.quality.native_audio import native_audio_use
from docprod.quality.router import estimate_model_cost
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.storage.hashing import file_sha256
from docprod.storage.json_store import atomic_write_text

SIMPLE_VIDEO_HARD_CAP_USD = 12.00
SIMPLE_PRIMARY_MODEL = "seedance-2.5-reference-to-video"
SIMPLE_SECONDARY_MODEL = "kling-3.0-pro-image-to-video"
SIMPLE_MOTION_MODEL = "kling-3.0-motion-control-pro"
SIMPLE_SCRIPT_MODEL = "gpt-6-astra"
MIN_SCENES = 6
MAX_SCENES = 8
MIN_LINES = 8
MAX_LINES = 12
MAX_VISIBLE_CAST = 3
SCENE_MIN_SECONDS = 5.0
SCENE_MAX_SECONDS = 10.0
PLAN_SCENE_COUNT = 7
PLAN_SCENE_SECONDS = 8.0
STOCK_VOICES = {
    "birko": "ash",
    "kemal": "cedar",
    "muge": "coral",
    "erni": "shimmer",
    "hg": "verse",
    "musti": "sage",
}

SIMPLE_SCRIPT_PLAN_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_simple_script_plan.json"
)
SIMPLE_SCRIPT_REVIEW_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_simple_script_review.md"
)
SIMPLE_SCRIPT_JSON_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_simple_script.json"
)
SIMPLE_VIDEO_PLAN_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_simple_video_plan.json"
)
SIMPLE_VIDEO_REVIEW_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_simple_video_review.md"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


class SimpleDialogueLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str
    text: str
    emotion: str = ""


class SimpleScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    duration: float
    location: str = "Krispy Kreme café"
    visible_character_ids: list[str] = Field(default_factory=list)
    offscreen_character_ids: list[str] = Field(default_factory=list)
    action: str = ""
    dialogue_lines: list[SimpleDialogueLine] = Field(default_factory=list)
    emotion: str = ""
    camera_intent: str = ""
    required_character_refs: list[str] = Field(default_factory=list)
    required_location_ref: str = ""
    props: list[str] = Field(default_factory=list)
    video_prompt: str = ""
    audio_intent: str = ""


class SimpleScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    language: str = "tr"
    scenes: list[SimpleScene] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SimpleVideoJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    provider: str = "higgsfield"
    model: str = SIMPLE_PRIMARY_MODEL
    fallback_model: str = SIMPLE_SECONDARY_MODEL
    prompt: str = ""
    duration: float = 8.0
    resolution: str = "720p"
    aspect_ratio: str = "9:16"
    character_ref_ids: list[str] = Field(default_factory=list)
    character_ref_paths: list[str] = Field(default_factory=list)
    location_ref_path: str = ""
    audio_urls: list[str] = Field(default_factory=list)
    request_fingerprint: str = ""
    request_body: dict[str, Any] = Field(default_factory=dict)
    native_audio_policy: str = "replace_or_mix_under_dialogue"
    expected_usd: float = 0.0
    reserved_usd: float = 0.0


SIMPLE_SCRIPT_INSTRUCTIONS = """You write FINAL production-ready Turkish friend-group shorts.

Output JSON only with keys: title, language, scenes, notes.
language must be "tr".
scenes: 6 to 8 complete cinematic beats. NOT 28 shots. NOT a storyboard.
Each scene: 5-10 seconds. Total runtime 45-60 seconds.

Each scene object:
scene_id, duration, location, visible_character_ids, offscreen_character_ids,
action, dialogue_lines (list of {speaker, text, emotion}), emotion, camera_intent,
required_character_refs, required_location_ref, props, video_prompt, audio_intent.

visible_character_ids: 1 or 2 people. 3 only if the joke needs it. Never 6.
Cover group talk by CUTTING between scenes, not crowding one clip.

dialogue_lines for the WHOLE episode: about 8-12 spoken lines total. Short. Natural.
Birko is sparse. No narrator. No personality lectures. No catchphrase spam.
Silence is allowed only if action is visible and funny.

First 1-2 seconds must hook. Last scene is Birko outside eating the last donut.

video_prompt: one cinematic paragraph for reference-to-video. 9:16 café realism.
Do not mention other AI models. Do not invent extra characters.
"""


def simple_script_user_payload(brief: EpisodeBrief, refs: list[dict[str, object]]) -> str:
    from docprod.product.story_pipeline import story_model_context
    context = story_model_context(brief, refs)
    context.pop("episode_brief", None)
    payload = {
        "locked_premise": brief.premise,
        "locked_ending": brief.ending or LOCKED_EPISODE_2_ENDING,
        "location": brief.location,
        "cast": list(brief.cast_names),
        "target_duration_seconds": list(brief.target_duration_seconds),
        "character_bible": context["character_bible"],
        "group_dynamic": GROUP_DYNAMIC,
        "reference_image_metadata": context["reference_image_metadata"],
        "continuity": "Episode 2 of the Birko friend group. Do not reuse a 28-shot plan.",
        "forbidden": [
            "28 micro-shots",
            "still-image animatic",
            "old VIDEO_UPGRADE map",
            "equal dialogue for every character",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def dialogue_line_count(script: SimpleScript) -> int:
    return sum(len(scene.dialogue_lines) for scene in script.scenes)


def validate_simple_script(script: SimpleScript) -> None:
    if not MIN_SCENES <= len(script.scenes) <= MAX_SCENES:
        raise ProductError(f"simple script must have {MIN_SCENES}–{MAX_SCENES} scenes")
    lines = dialogue_line_count(script)
    if not MIN_LINES <= lines <= MAX_LINES:
        raise ProductError(f"simple script must have {MIN_LINES}–{MAX_LINES} spoken lines")
    total = 0.0
    for scene in script.scenes:
        if not SCENE_MIN_SECONDS <= scene.duration <= SCENE_MAX_SECONDS:
            raise ProductError(f"{scene.scene_id} duration {scene.duration}s out of 5–10s")
        visible = [item for item in scene.visible_character_ids if item]
        if len(visible) > MAX_VISIBLE_CAST:
            raise ProductError(f"{scene.scene_id} has {len(visible)} visible cast; max 3")
        if not visible:
            raise ProductError(f"{scene.scene_id} needs at least one visible character")
        total += scene.duration
    if total < 45.0 or total > 60.0:
        raise ProductError(f"simple script total {total:.1f}s must be 45–60s")


def parse_simple_script(text: str) -> SimpleScript:
    blob = text.strip()
    if blob.startswith("```"):
        blob = blob.strip("`")
        blob = blob.split("\n", 1)[-1]
    payload = json.loads(blob)
    if not isinstance(payload, dict):
        raise ProductError("simple script JSON must be an object")
    script = SimpleScript.model_validate(payload)
    validate_simple_script(script)
    return script


def _ref_map(refs: list[dict[str, object]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in refs:
        slug = str(row.get("slug") or "").casefold()
        path = str(row.get("resolved_path") or "")
        if slug and path:
            out[slug] = path
    return out


def refs_for_scene(scene: SimpleScene, ref_map: dict[str, str]) -> list[tuple[str, str]]:
    wanted = list(scene.required_character_refs) or list(scene.visible_character_ids)
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for slug in wanted:
        key = slug.casefold().removeprefix("ref_")
        if key in seen:
            continue
        path = ref_map.get(key)
        if not path:
            continue
        seen.add(key)
        pairs.append((key, path))
    return pairs


def build_simple_script_plan(brief: EpisodeBrief) -> StoryGenerationPlan:
    from docprod.product.story_pipeline import _call_cost
    call = _call_cost(
        call_id="simple_script",
        role="primary",
        model_id=SIMPLE_SCRIPT_MODEL,
        purpose="one-shot 6–8 scene Friend Group short; no ensemble",
        estimated_input=2800,
        reserved_input=4500,
        estimated_output=2200,
        reserved_output=3500,
    )
    expected = round(call.expected_usd, 5)
    reserved = round(call.reserved_usd, 5)
    return StoryGenerationPlan(
        series_slug=brief.series_slug,
        episode_number=brief.episode_number,
        quality_profile="premium",
        flagship=True,
        treatment_count=1,
        calls=[call],
        estimated_input_tokens=call.estimated_input_tokens,
        estimated_output_tokens=call.estimated_output_tokens,
        reserved_input_tokens=call.reserved_input_tokens,
        reserved_output_tokens=call.reserved_output_tokens,
        estimated_usd=expected,
        reserved_usd=reserved,
        cost_confidence="known",
        hard_cap_usd=SIMPLE_VIDEO_HARD_CAP_USD,
        cap_ok=reserved <= SIMPLE_VIDEO_HARD_CAP_USD,
        execute=False,
        media_calls=0,
        notes=[
            "ONE gpt-6-astra writing call. No 5-call ensemble.",
            "Do not send the 28-shot production plan.",
            f"Hard cap for full simplified video is ${SIMPLE_VIDEO_HARD_CAP_USD:.2f}.",
        ],
    )


def _scene_video_cost(seconds: float) -> tuple[float, float]:
    expected, _conf = estimate_model_cost(SIMPLE_PRIMARY_MODEL, seconds=seconds)
    reserved, _rconf = estimate_model_cost(SIMPLE_PRIMARY_MODEL, seconds=max(seconds, 10.0))
    return float(expected or 0.0), float(reserved or 0.0)


def envelope_video_cost(*, scene_count: int = PLAN_SCENE_COUNT) -> dict[str, float]:
    script = build_simple_script_plan(
        EpisodeBrief(series_slug="birko", episode_number=2)
    )
    video_e = 0.0
    video_r = 0.0
    for _ in range(scene_count):
        exp, res = _scene_video_cost(PLAN_SCENE_SECONDS)
        video_e += exp
        video_r += res
    tts_e = usd_round(typical_tts_usd() * MAX_LINES / 4.0)
    tts_r = usd_round(typical_tts_usd() * MAX_LINES / 2.0)
    loc_e = typical_image_usd(with_reference=False)
    loc_r = usd_round(loc_e * 1.5)
    expected = usd_round(float(script.estimated_usd or 0.0) + video_e + tts_e + loc_e)
    reserved = usd_round(script.reserved_usd + video_r + tts_r + loc_r)
    return {
        "script_expected_usd": float(script.estimated_usd or 0.0),
        "script_reserved_usd": script.reserved_usd,
        "higgsfield_expected_usd": usd_round(video_e),
        "higgsfield_reserved_usd": usd_round(video_r),
        "tts_expected_usd": tts_e,
        "tts_reserved_usd": tts_r,
        "location_image_expected_usd": loc_e,
        "location_image_reserved_usd": loc_r,
        "expected_usd": expected,
        "reserved_usd": reserved,
        "hard_cap_usd": SIMPLE_VIDEO_HARD_CAP_USD,
        "cap_ok": 1.0 if reserved <= SIMPLE_VIDEO_HARD_CAP_USD + 1e-9 else 0.0,
    }


def build_simple_video_jobs(
    script: SimpleScript,
    refs: list[dict[str, object]],
    *,
    audio_paths: dict[str, str] | None = None,
) -> list[SimpleVideoJob]:
    ref_map = _ref_map(refs)
    jobs: list[SimpleVideoJob] = []
    for scene in script.scenes:
        pairs = refs_for_scene(scene, ref_map)
        paths = [path for _slug, path in pairs]
        shas = [file_sha256(Path(path)) for path in paths if Path(path).is_file()]
        image_urls = [f"file://{path}" for path in paths]
        audio = list((audio_paths or {}).get(scene.scene_id, "").split("|"))
        audio = [item for item in audio if item]
        body = seedance_reference_to_video_body(
            prompt=scene.video_prompt or scene.action,
            duration=scene.duration,
            image_urls=image_urls,
            audio_urls=audio or None,
        )
        exp, res = _scene_video_cost(scene.duration)
        fingerprint = seedance_request_fingerprint(
            prompt=str(body["prompt"]),
            duration=float(body["duration"]),
            image_shas=shas,
            audio_shas=[file_sha256(Path(item)) for item in audio if Path(item).is_file()],
        )
        jobs.append(
            SimpleVideoJob(
                scene_id=scene.scene_id,
                prompt=str(body["prompt"]),
                duration=float(body["duration"]),
                character_ref_ids=[slug for slug, _path in pairs],
                character_ref_paths=paths,
                location_ref_path=scene.required_location_ref,
                audio_urls=audio,
                request_fingerprint=fingerprint,
                request_body=body,
                native_audio_policy=native_audio_use(
                    SIMPLE_PRIMARY_MODEL, needs_character_dialogue=bool(scene.dialogue_lines)
                ),
                expected_usd=exp,
                reserved_usd=res,
            )
        )
    return jobs


def next_unfinished_scene(ledger: dict[str, Any], jobs: list[SimpleVideoJob]) -> str | None:
    ops = ledger.get("operations") if isinstance(ledger.get("operations"), dict) else {}
    for job in jobs:
        row = ops.get(job.scene_id) if isinstance(ops, dict) else None
        if not isinstance(row, dict) or row.get("state") != "SUCCEEDED":
            return job.scene_id
    return None


def mark_scene_succeeded(
    ledger: dict[str, Any],
    job: SimpleVideoJob,
    *,
    artifact: str,
    request_id: str,
    cost: float,
) -> dict[str, Any]:
    ops = ledger.setdefault("operations", {})
    ops[job.scene_id] = {
        "scene_id": job.scene_id,
        "request_fingerprint": job.request_fingerprint,
        "refs": job.character_ref_paths,
        "prompt": job.prompt,
        "provider": job.provider,
        "model": job.model,
        "request_id": request_id,
        "status": "SUCCEEDED",
        "state": "SUCCEEDED",
        "artifact": artifact,
        "cost": cost,
    }
    return ledger


def concat_simple_scenes(paths: list[Path], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = dest.with_suffix(".txt")
    lines = [f"file '{path}'" for path in paths]
    atomic_write_text(manifest, "\n".join(lines) + "\n")
    run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", str(manifest), "-c", "copy", str(dest)],
        timeout=180,
    )
    info = probe_media(dest)
    planned = 0.0
    for path in paths:
        planned += probe_media(path).duration
    if info.duration + 0.75 < planned:
        raise ProductError("simple concat collapsed duration; no silent padding was applied")
    return dest


def example_simple_script() -> SimpleScript:
    lines = [
        ("S1", 7.0, ["kemal"], "kemal", "Hesabı kim ödüyor?"),
        ("S2", 6.0, ["hg"], "hg", "Sen kapat, Kemalooom."),
        ("S3", 8.0, ["muge"], "muge", "Şu kutunun fiyatını gördün mü?"),
        ("S4", 8.0, ["erni", "kemal"], "erni", "Sen daha babysin."),
        ("S5", 7.0, ["musti"], "musti", "Öde öde öde."),
        ("S6", 9.0, ["kemal", "hg"], "kemal", "Birko nerde?"),
        ("S7", 8.0, ["birko"], "birko", "Afiyet."),
    ]
    extra = [
        ("S4", "kemal", "Ne baby'si?"),
        ("S6", "hg", "Kaçtı dayiiii."),
        ("S7", "kemal", "Birko! Ben sadece su içtim!"),
    ]
    scenes: list[SimpleScene] = []
    extras_by: dict[str, list[SimpleDialogueLine]] = {}
    for scene_id, speaker, text in extra:
        extras_by.setdefault(scene_id, []).append(
            SimpleDialogueLine(speaker=speaker, text=text)
        )
    for scene_id, duration, visible, speaker, text in lines:
        dialogue = [SimpleDialogueLine(speaker=speaker, text=text)]
        dialogue.extend(extras_by.get(scene_id, []))
        scenes.append(
            SimpleScene(
                scene_id=scene_id,
                duration=duration,
                visible_character_ids=visible,
                action="café beat",
                dialogue_lines=dialogue,
                required_character_refs=visible,
                video_prompt=f"9:16 café, {', '.join(visible)}, natural light",
                audio_intent="mix stock TTS over ambient",
            )
        )
    return SimpleScript(title="Hesap", language="tr", scenes=scenes)


def simple_render_dir(*, root: Path | None = None) -> Path:
    base = root or _repo_root()
    return base / "projects/birko_kemal_drama_canary/artifacts/render/episode_2_simple"


def write_simple_script_plan_artifacts(
    brief: EpisodeBrief,
    plan: StoryGenerationPlan,
    refs: list[dict[str, object]],
) -> dict[str, str]:
    root = _repo_root()
    review = root / SIMPLE_SCRIPT_REVIEW_RELATIVE
    json_path = root / SIMPLE_SCRIPT_PLAN_RELATIVE
    review.parent.mkdir(parents=True, exist_ok=True)
    prompt = simple_script_user_payload(brief, refs)
    review.write_text(
        "\n".join(
            [
                "# Simplified Friend Group script plan",
                "",
                "One gpt-6-astra call. Not the five-call ensemble.",
                "Not the 28-shot animatic plan.",
                "",
                f"expected_usd={plan.estimated_usd}",
                f"reserved_usd={plan.reserved_usd}",
                f"hard_cap_usd={SIMPLE_VIDEO_HARD_CAP_USD}",
                "",
                "`uv run docprod birko-episode2 --stage simple-script-plan`",
                "`uv run docprod birko-episode2 --stage simple-script-generate --confirm-paid`",
                "",
                "## Writer payload",
                "",
                "```json",
                prompt,
                "```",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    json_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return {"review": str(review), "plan": str(json_path)}


def execute_simple_script_plan(
    *,
    brief: EpisodeBrief,
    refs: list[dict[str, object]],
) -> dict[str, object]:
    plan = build_simple_script_plan(brief)
    artifacts = write_simple_script_plan_artifacts(brief, plan, refs)
    return {
        "stage": "simple-script-plan",
        "plan": plan.model_dump(),
        "artifacts": artifacts,
        "prompt_instructions": SIMPLE_SCRIPT_INSTRUCTIONS,
        "scene_count_target": f"{MIN_SCENES}-{MAX_SCENES}",
        "dialogue_target": f"{MIN_LINES}-{MAX_LINES}",
        "provider_http_calls": 0,
        "media_calls": 0,
        "stars": 0,
        "planned_text_model_calls": 1,
        "submitted_text_model_calls": 0,
        "completed_text_model_calls": 0,
        "text_model_calls": 0,
        "execute": False,
        "expected_usd": plan.estimated_usd,
        "reserved_usd": plan.reserved_usd,
        "hard_cap_usd": SIMPLE_VIDEO_HARD_CAP_USD,
        "cap_ok": plan.cap_ok,
    }


def execute_simple_script_generate(
    *,
    confirm_paid: bool,
    brief: EpisodeBrief,
    refs: list[dict[str, object]],
    settings: Settings | None = None,
    text_client: Any = None,
    execute_calls: bool = False,
) -> dict[str, object]:
    if not confirm_paid:
        raise PaidApiNotConfirmedError(
            "simple-script-generate requires --confirm-paid after simple-script-plan"
        )
    plan = build_simple_script_plan(brief)
    if not execute_calls:
        return {
            "stage": "simple-script-generate",
            "execute": False,
            "provider_http_calls": 0,
            "media_calls": 0,
            "stars": 0,
            "plan": plan.model_dump(),
        }
    from docprod.product.story_pipeline import openai_key_present

    if not openai_key_present(settings):
        raise ProductError("OPENAI_API_KEY is required for simple-script-generate")
    if text_client is None:
        from docprod.config import get_settings
        from docprod.product.story_pipeline import OpenAIStoryClient

        text_client = OpenAIStoryClient(settings or get_settings())
    raw = text_client.create(
        model=SIMPLE_SCRIPT_MODEL,
        instructions=SIMPLE_SCRIPT_INSTRUCTIONS,
        input_text=simple_script_user_payload(brief, refs),
        confirm_paid=confirm_paid,
    )
    text = str(getattr(raw, "output_text", None) or raw)
    script = parse_simple_script(text)
    dest = _repo_root() / SIMPLE_SCRIPT_JSON_RELATIVE
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return {
        "stage": "simple-script-generate",
        "execute": True,
        "provider_http_calls": 1,
        "output": str(dest),
        "scene_count": len(script.scenes),
        "dialogue_lines": dialogue_line_count(script),
        "plan": plan.model_dump(),
        "stars": 0,
        "media_calls": 0,
    }


def execute_simple_video_plan(
    *,
    brief: EpisodeBrief,
    refs: list[dict[str, object]],
    script: SimpleScript | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    from docprod.product.story_pipeline import location_bible_for_brief

    envelope = envelope_video_cost()
    loaded = script
    script_path = _repo_root() / SIMPLE_SCRIPT_JSON_RELATIVE
    if loaded is None and script_path.is_file():
        loaded = SimpleScript.model_validate_json(script_path.read_text(encoding="utf-8"))
        validate_simple_script(loaded)
    jobs = build_simple_video_jobs(loaded, refs) if loaded is not None else []
    if jobs:
        expected = usd_round(
            sum(job.expected_usd for job in jobs)
            + envelope["script_expected_usd"]
            + envelope["tts_expected_usd"]
            + envelope["location_image_expected_usd"]
        )
        reserved = usd_round(
            sum(job.reserved_usd for job in jobs)
            + envelope["script_reserved_usd"]
            + envelope["tts_reserved_usd"]
            + envelope["location_image_reserved_usd"]
        )
        envelope["expected_usd"] = expected
        envelope["reserved_usd"] = reserved
        envelope["higgsfield_expected_usd"] = usd_round(sum(job.expected_usd for job in jobs))
        envelope["higgsfield_reserved_usd"] = usd_round(sum(job.reserved_usd for job in jobs))
        envelope["cap_ok"] = 1.0 if reserved <= SIMPLE_VIDEO_HARD_CAP_USD + 1e-9 else 0.0
    if envelope["reserved_usd"] - 1e-9 > SIMPLE_VIDEO_HARD_CAP_USD:
        raise ProductError(
            f"STOP BEFORE HTTP: reserved ${envelope['reserved_usd']:.4f} exceeds "
            f"hard cap ${SIMPLE_VIDEO_HARD_CAP_USD:.2f}"
        )
    root = _repo_root()
    plan_path = root / SIMPLE_VIDEO_PLAN_RELATIVE
    review_path = root / SIMPLE_VIDEO_REVIEW_RELATIVE
    payload = {
        "execute": False,
        "primary_model": SIMPLE_PRIMARY_MODEL,
        "secondary_model": SIMPLE_SECONDARY_MODEL,
        "motion_model": SIMPLE_MOTION_MODEL,
        "seedance_contract": SEEDANCE_CONTRACTS[SIMPLE_PRIMARY_MODEL],
        "kling_i2v_contract": KLING_I2V_CONTRACT,
        "kling_motion_contract": KLING_MOTION_CONTRACT,
        "higgsfield_credentials_present": higgsfield_credentials_present(settings),
        "jobs": [job.model_dump() for job in jobs],
        "costs": envelope,
        "edit": "hard_cut_sequential",
        "voices": STOCK_VOICES,
        "location": location_bible_for_brief(brief).model_dump(),
    }
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    review_path.write_text(
        "\n".join(
            [
                "# Simplified Friend Group video plan",
                "",
                "Astra scenes → Seedance reference-to-video → stock TTS → hard-cut concat.",
                "Historical 28-shot animatic is not the source.",
                "",
                f"expected_usd={envelope['expected_usd']}",
                f"reserved_usd={envelope['reserved_usd']}",
                f"hard_cap_usd={SIMPLE_VIDEO_HARD_CAP_USD}",
                f"higgsfield_key_present={payload['higgsfield_credentials_present']}",
                "",
                "`uv run docprod birko-episode2 --stage simple-video-plan`",
                "`uv run docprod birko-episode2 --stage simple-video-generate --confirm-paid`",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "stage": "simple-video-plan",
        "plan": payload,
        "artifacts": {"plan": str(plan_path), "review": str(review_path)},
        "provider_http_calls": 0,
        "media_calls": 0,
        "stars": 0,
        "expected_usd": envelope["expected_usd"],
        "reserved_usd": envelope["reserved_usd"],
        "hard_cap_usd": SIMPLE_VIDEO_HARD_CAP_USD,
        "cap_ok": bool(envelope["cap_ok"]),
        "execute": False,
    }


def execute_simple_video_generate(
    *,
    confirm_paid: bool,
    brief: EpisodeBrief,
    refs: list[dict[str, object]],
    script: SimpleScript | None = None,
    execute_calls: bool = False,
    settings: Settings | None = None,
) -> dict[str, object]:
    if not confirm_paid:
        raise PaidApiNotConfirmedError(
            "simple-video-generate requires --confirm-paid after simple-video-plan"
        )
    planned = execute_simple_video_plan(brief=brief, refs=refs, script=script, settings=settings)
    if not execute_calls:
        return {
            **planned,
            "stage": "simple-video-generate",
            "execute": False,
            "provider_http_calls": 0,
            "resume_from": None,
        }
    raise ProductError(
        "STOP BEFORE HTTP: Higgsfield request payloads are ready; live POST waits "
        "for approved Astra simple script"
    )


def kling_fallback_body(job: SimpleVideoJob) -> dict[str, Any]:
    image = job.character_ref_paths[0] if job.character_ref_paths else ""
    return kling_image_to_video_body(
        prompt=job.prompt,
        image_url=f"file://{image}" if image else "",
        duration=job.duration,
    )


def kling_motion_body(job: SimpleVideoJob, driving_video_url: str) -> dict[str, Any]:
    image = job.character_ref_paths[0] if job.character_ref_paths else ""
    return kling_motion_control_body(
        prompt=job.prompt,
        image_url=f"file://{image}" if image else "",
        video_url=driving_video_url,
    )
