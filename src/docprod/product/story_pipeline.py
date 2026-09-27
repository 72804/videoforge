from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from docprod.config import Settings, get_settings
from docprod.exceptions import MissingApiKeyError, PaidApiNotConfirmedError
from docprod.product.animatic import (
    ANIMATIC_PROVIDER_HARD_CAP_USD,
    animatic_render_dir,
    animatic_review_relative,
    build_animatic_plan,
    execute_animatic_generate,
    format_animatic_review,
)
from docprod.product.birko_bible import (
    BIRKO_CAST,
    GROUP_DYNAMIC,
    LOCKED_EPISODE_2_ENDING,
    LOCKED_EPISODE_2_PREMISE,
    episode_2_draft_prompt,
)
from docprod.product.episode import (
    EpisodeBrief,
    LocationBible,
    StoryCallSpec,
    StoryGenerationPlan,
    VoiceAssignment,
)
from docprod.product.errors import AuthorizationError, ProductError
from docprod.product.friend_group import HOOK_FIRST_WRITER_INSTRUCTIONS
from docprod.product.production_director import (
    DirectedEpisode,
    direct_friend_group_episode,
    format_production_review,
    production_plans_for_profiles,
)
from docprod.product.series import (
    BIRKO_E2_TARGET_STACK,
    birko_character_refs_dir,
    custom_identity_source,
    list_birko_ref_inventory,
    promote_custom_identity_photos,
)
from docprod.product.story_artifacts import (
    _parse_json_blob,
    format_generated_review,
    hydrate_succeeded_stages,
    location_bible_from_story,
    output_sha256,
    parse_friend_group_story,
    stage_output_text,
)
from docprod.providers.pricing import (
    GPT6_ASTRA_PRICING_SOURCE,
    STORY_TEXT_PRICING_AS_OF,
    text_tokens_cost_usd,
)
from docprod.quality.catalog import get_model
from docprod.quality.ensemble import (
    CreativeEnsembleRun,
    EnsembleStageRecord,
    EnsembleUsageRecord,
    remaining_ensemble_stages,
    stage_record_for,
)
from docprod.quality.enums import QualityProfile
from docprod.quality.policy_select import OPENAI_STOCK_VOICES
from docprod.quality.story_director import CRITIC_SYSTEM, FINALIZER_SYSTEM, script_ensemble_plan
from docprod.storage.hashing import content_hash, file_sha256

STORY_HARD_CAP_USD = 2.50
AUTHORIZED_STORY_EPISODES = frozenset({("birko", 2)})
STORY_GENERATE_AUTHORIZED = False  # global paid-story switch stays off
TREATMENT_COUNT = 3
# Verified token envelope from the last story-plan (text-only context).
BIRKO_E2_TREATMENT_EST_IN = 3107
BIRKO_E2_TREATMENT_RES_IN = 4971
BIRKO_E2_TREATMENT_EST_OUT = 1600
BIRKO_E2_TREATMENT_RES_OUT = 2500
BIRKO_E2_CRITIC_EST_IN = 8007
BIRKO_E2_CRITIC_RES_IN = 12010
BIRKO_E2_CRITIC_EST_OUT = 2200
BIRKO_E2_CRITIC_RES_OUT = 3500
BIRKO_E2_FINAL_EST_IN = 10307
BIRKO_E2_FINAL_RES_IN = 15460
BIRKO_E2_FINAL_EST_OUT = 2800
BIRKO_E2_FINAL_RES_OUT = 4000
REVIEW_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_story_review.md"
)
PLAN_JSON_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_story_plan.json"
)
CHECKPOINT_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/"
    "episode_2_ensemble_checkpoint.json"
)
PRODUCTION_REVIEW_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/"
    "episode_2_production_review.md"
)
PRODUCTION_PLAN_JSON_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/"
    "episode_2_production_plan.json"
)
ANIMATIC_PLAN_JSON_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/"
    "episode_2_animatic_plan.json"
)

_ELEVEN_PROPOSED = {
    "birko": ("eleven_v3_proposed_low_energy_tr", "ash"),
    "kemal": ("eleven_v3_proposed_earnest_baritone_tr", "cedar"),
    "muge": ("eleven_v3_proposed_flirty_alto_tr", "coral"),
    "erni": ("eleven_v3_proposed_sweet_manipulator_tr", "shimmer"),
    "hg": ("eleven_v3_proposed_devilish_tr", "verse"),
    "musti": ("eleven_v3_proposed_young_gremlin_tr", "sage"),
}


class StoryTextClient(Protocol):
    def create(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        confirm_paid: bool,
    ) -> Any: ...


def story_generation_authorized(series_slug: str, episode_number: int) -> bool:
    return (series_slug.strip().casefold(), int(episode_number)) in AUTHORIZED_STORY_EPISODES


def openai_key_present(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return cfg.openai_key_configured()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def locked_episode_brief(
    *,
    series_slug: str = "birko",
    episode_number: int = 2,
) -> EpisodeBrief:
    if series_slug != "birko" or episode_number != 2:
        return EpisodeBrief(
            series_slug=series_slug,
            episode_number=episode_number,
            premise_locked=False,
            engine_owns_structure=True,
        )
    return EpisodeBrief(
        series_slug="birko",
        episode_number=2,
        title="Birko Episode 2",
        language="tr",
        location="Krispy Kreme café",
        primary_tone="drama",
        secondary_tone="absurd / dark comedy generated naturally from character behavior",
        target_duration_seconds=(45.0, 60.0),
        cast_names=[member.name for member in BIRKO_CAST],
        premise=LOCKED_EPISODE_2_PREMISE,
        ending=LOCKED_EPISODE_2_ENDING,
        premise_locked=True,
        engine_owns_structure=True,
    )


def location_bible_for_brief(brief: EpisodeBrief) -> LocationBible:
    return LocationBible(
        name=brief.location or "ENGINE_OWNED",
        interior_layout="",
        tables="",
        counter="",
        windows="",
        entrance="",
        exterior="",
        lighting="",
        time_of_day="",
        props=[],
        engine_owned_details=True,
    )


def inspect_locked_character_refs() -> list[dict[str, object]]:
    promote_custom_identity_photos()
    folder = birko_character_refs_dir()
    inventory = list_birko_ref_inventory()
    by_slug = inventory["by_slug"] if isinstance(inventory["by_slug"], dict) else {}
    rows: list[dict[str, object]] = []
    for member in BIRKO_CAST:
        row = by_slug.get(member.slug) if isinstance(by_slug, dict) else {}
        found = list(row.get("found") or []) if isinstance(row, dict) else []
        custom = custom_identity_source(member.slug)
        if not found:
            rows.append(
                {
                    "slug": member.slug,
                    "name": member.name,
                    "expected": list(member.expected_ref_filenames),
                    "resolved_path": "",
                    "custom_source": str(custom) if custom else "",
                    "sha256": "",
                    "width": 0,
                    "height": 0,
                    "present": False,
                }
            )
            continue
        path = folder / found[0]
        width = height = 0
        if path.is_file():
            with Image.open(path) as image:
                width, height = image.size
        rows.append(
            {
                "slug": member.slug,
                "name": member.name,
                "expected": list(member.expected_ref_filenames),
                "resolved_path": str(path.resolve()) if path.is_file() else str(path),
                "custom_source": str(custom) if custom else "",
                "sha256": file_sha256(path) if path.is_file() else "",
                "width": width,
                "height": height,
                "present": path.is_file(),
            }
        )
    return rows


def approx_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _ref_metadata(refs: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in refs:
        rows.append(
            {
                "slug": row.get("slug"),
                "name": row.get("name"),
                "resolved_path": row.get("resolved_path"),
                "custom_source": row.get("custom_source"),
                "sha256": row.get("sha256"),
                "width": row.get("width"),
                "height": row.get("height"),
                "present": row.get("present"),
            }
        )
    return rows


def story_model_context(
    brief: EpisodeBrief,
    refs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Text-only payload for Astra/Opus. No image binaries, no repository code."""
    characters: list[dict[str, object]] = []
    for member in BIRKO_CAST:
        characters.append(
            {
                "slug": member.slug,
                "name": member.name,
                "role_archetype": member.role_archetype,
                "description": member.description,
                "personality_traits": list(member.personality_traits),
                "behavioral_quirks": list(member.behavioral_quirks),
                "catchphrases": list(member.catchphrases),
                "relationships": dict(member.relationships),
                "voice_notes": member.voice_notes,
                "never_do": list(member.never_do),
                "aliases": list(member.aliases),
            }
        )
    return {
        "episode_brief": brief.model_dump(),
        "character_bible": characters,
        "group_dynamic": GROUP_DYNAMIC,
        "reference_image_metadata": _ref_metadata(refs or []),
        "send_image_binaries": False,
        "send_repository_code": False,
    }


def _rates(model_id: str) -> tuple[float, float]:
    spec = get_model(model_id)
    if spec is None:
        raise ProductError(f"unknown story model {model_id}")
    price = spec.pricing
    if price.input_usd_per_million is None or price.output_usd_per_million is None:
        raise ProductError(f"story model {model_id} is missing input/output list prices")
    return float(price.input_usd_per_million), float(price.output_usd_per_million)


def _headroom(tokens: int, *, extra: int, factor: float) -> int:
    return max(tokens + extra, int(tokens * factor))


def _call_cost(
    *,
    call_id: str,
    role: str,
    model_id: str,
    purpose: str,
    estimated_input: int,
    reserved_input: int,
    estimated_output: int,
    reserved_output: int,
) -> StoryCallSpec:
    in_rate, out_rate = _rates(model_id)
    return StoryCallSpec(
        call_id=call_id,
        role=role,
        model_id=model_id,
        count=1,
        purpose=purpose,
        estimated_input_tokens=estimated_input,
        reserved_input_tokens=reserved_input,
        estimated_output_tokens=estimated_output,
        reserved_output_tokens=reserved_output,
        expected_usd=text_tokens_cost_usd(
            input_tokens=estimated_input,
            output_tokens=estimated_output,
            input_usd_per_million=in_rate,
            output_usd_per_million=out_rate,
        ),
        reserved_usd=text_tokens_cost_usd(
            input_tokens=reserved_input,
            output_tokens=reserved_output,
            input_usd_per_million=in_rate,
            output_usd_per_million=out_rate,
        ),
    )


def _models_from_plan(plan: StoryGenerationPlan) -> tuple[str, str, str]:
    primary = next(
        (call.model_id for call in plan.calls if call.role == "primary"),
        "gpt-6-astra",
    )
    critic = next(
        (call.model_id for call in plan.calls if call.role == "critic"),
        "gpt-6-astra",
    )
    finalizer = next(
        (call.model_id for call in plan.calls if call.role == "finalizer"),
        "gpt-6-astra",
    )
    return primary, critic, finalizer


def story_generation_readiness(
    plan: StoryGenerationPlan,
    *,
    settings: Settings | None = None,
) -> dict[str, object]:
    authorized = story_generation_authorized(plan.series_slug, plan.episode_number)
    key_ok = openai_key_present(settings)
    return {
        "ready": authorized and plan.cap_ok and key_ok,
        "series": plan.series_slug,
        "episode": plan.episode_number,
        "model": "gpt-6-astra",
        "calls": len(plan.calls),
        "reserved_total": plan.reserved_usd,
        "expected_total": plan.estimated_usd,
        "hard_cap_usd": plan.hard_cap_usd,
        "confirm_paid_required": True,
        "media_generation": False,
        "anthropic_required": False,
        "openai_key_configured": key_ok,
        "authorized_episode": authorized,
        "global_story_generate_authorized": STORY_GENERATE_AUTHORIZED,
    }


def _checkpoint_path() -> Path:
    return _repo_root() / CHECKPOINT_RELATIVE


def load_ensemble_checkpoint() -> CreativeEnsembleRun | None:
    path = _checkpoint_path()
    if not path.is_file():
        return None
    run = CreativeEnsembleRun.model_validate_json(path.read_text(encoding="utf-8"))
    hydrate_succeeded_stages(run)
    return run


def save_ensemble_checkpoint(run: CreativeEnsembleRun) -> Path:
    path = _checkpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _pad_treatments(run: CreativeEnsembleRun) -> None:
    while len(run.treatments) < TREATMENT_COUNT:
        run.treatments.append("")


def _usage_from_response(
    response: Any,
    *,
    call_id: str,
    model_id: str,
    fingerprint: str = "",
) -> EnsembleUsageRecord:
    usage = getattr(response, "usage", None)
    payload: dict[str, Any] = {}
    if usage is not None and hasattr(usage, "model_dump"):
        dumped = usage.model_dump()
        if isinstance(dumped, dict):
            payload = dumped
    elif isinstance(usage, dict):
        payload = usage
    input_tokens = int(payload.get("input_tokens") or 0)
    output_tokens = int(payload.get("output_tokens") or 0)
    in_rate, out_rate = _rates(model_id)
    return EnsembleUsageRecord(
        call_id=call_id,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usd=text_tokens_cost_usd(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_usd_per_million=in_rate,
            output_usd_per_million=out_rate,
        ),
        request_id=str(getattr(response, "request_id", "") or ""),
        response_id=str(getattr(response, "id", "") or ""),
        request_fingerprint=fingerprint,
        state="SUCCEEDED" if (input_tokens or output_tokens) else "UNCERTAIN",
    )


def _output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    return str(response)


class OpenAIStoryClient:
    """Scoped Astra text client. Does not enable image/video/TTS or Anthropic."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        confirm_paid: bool,
    ) -> Any:
        if not confirm_paid:
            raise PaidApiNotConfirmedError(
                "story-generate requires --confirm-paid after explicit authorization"
            )
        from openai import OpenAI

        from docprod.config import require_openai_api_key

        client = OpenAI(api_key=require_openai_api_key(self.settings))
        return client.responses.create(
            model=model,
            instructions=instructions,
            input=input_text,
        )


def rebuild_story_artifacts(
    brief: EpisodeBrief,
    plan: StoryGenerationPlan,
    refs: list[dict[str, object]],
    run: CreativeEnsembleRun,
) -> dict[str, str]:
    hydrate_succeeded_stages(run)
    save_ensemble_checkpoint(run)
    voices = proposed_voice_assignments(language=brief.language)
    voice_lines = [
        f"- {item.character_name}: {item.provider}/{item.voice_id} "
        f"(fallback {item.fallback_provider}/{item.fallback_voice_id}; no cloning; TTS not called)"
        for item in voices
    ]
    ref_lines = [
        f"- {row['name']}: present={row['present']} path={row['resolved_path']} "
        f"sha256={row['sha256']} {row['width']}x{row['height']}"
        for row in refs
    ]
    root = _repo_root()
    review_path = root / REVIEW_RELATIVE
    spec_path = (
        root / "projects/birko_kemal_drama_canary/artifacts/review/episode_2_story_spec.json"
    )
    review_path.parent.mkdir(parents=True, exist_ok=True)
    if not run.final_script.strip():
        return {"review": str(review_path), "spec": ""}
    spec = parse_friend_group_story(run, brief)
    payload = _parse_json_blob(run.final_script)
    location = location_bible_from_story(brief)
    role_hints = {member.name: member.role_archetype for member in BIRKO_CAST}
    directed = direct_friend_group_episode(
        payload,
        spec,
        brief,
        location,
        locked_refs=refs,
        profile=QualityProfile.PREMIUM,
        role_hints=role_hints,
    )
    spec = directed.spec
    shots = directed.shot_plan
    known = sum(float(item.usd or 0) for item in run.model_usage)
    review_path.write_text(
        format_generated_review(
            brief=brief,
            spec=spec,
            shots=shots,
            location=location,
            voices=voice_lines,
            refs=ref_lines,
            known_usd=known,
            completed_calls=len(run.model_usage),
            planned_calls=len(plan.calls),
        ),
        encoding="utf-8",
    )
    spec_path.write_text(spec.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return {"review": str(review_path), "spec": str(spec_path)}


def execute_production_director(
    *,
    plan: StoryGenerationPlan,
    refs: list[dict[str, object]],
    settings: Settings | None = None,
) -> dict[str, object]:
    del settings
    brief = locked_episode_brief(series_slug=plan.series_slug, episode_number=plan.episode_number)
    run = load_ensemble_checkpoint()
    if run is None or not run.final_script.strip():
        raise ProductError("production-plan requires a completed story checkpoint")
    hydrate_succeeded_stages(run)
    spec = parse_friend_group_story(run, brief)
    payload = _parse_json_blob(run.final_script)
    location = location_bible_from_story(brief)
    role_hints = {member.name: member.role_archetype for member in BIRKO_CAST}
    directed = direct_friend_group_episode(
        payload,
        spec,
        brief,
        location,
        locked_refs=refs,
        profile=QualityProfile.PREMIUM,
        role_hints=role_hints,
    )
    spec = directed.spec
    plans = production_plans_for_profiles(directed)
    voices = proposed_voice_assignments(language=brief.language)
    voice_lines = [
        f"- {item.character_name}: {item.provider}/{item.voice_id} "
        f"(fallback {item.fallback_provider}/{item.fallback_voice_id}; no cloning; TTS not called)"
        for item in voices
    ]
    ref_lines = [
        f"- {row['name']}: present={row['present']} path={row['resolved_path']} "
        f"sha256={row['sha256']} {row['width']}x{row['height']}"
        for row in refs
    ]
    known = sum(float(item.usd or 0) for item in run.model_usage)
    root = _repo_root()
    production_path = root / PRODUCTION_REVIEW_RELATIVE
    plan_json_path = root / PRODUCTION_PLAN_JSON_RELATIVE
    spec_path = (
        root / "projects/birko_kemal_drama_canary/artifacts/review/episode_2_story_spec.json"
    )
    production_path.parent.mkdir(parents=True, exist_ok=True)
    production_path.write_text(
        format_production_review(
            brief=brief,
            spec=spec,
            directed=directed,
            location=location,
            voices=voice_lines,
            refs=ref_lines,
            plans=plans,
            known_story_usd=known,
        ),
        encoding="utf-8",
    )
    plan_json_path.write_text(
        json.dumps(
            {
                "old_shot_count": directed.old_shot_count,
                "new_shot_count": len(directed.shot_plan.shots),
                "total_duration_seconds": directed.shot_plan.total_duration_seconds,
                "role_coverage": directed.shot_plan.role_coverage,
                "plans": {key: value.model_dump() for key, value in plans.items()},
                "shot_plan": directed.shot_plan.model_dump(),
                "provider_http_calls": 0,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    spec_path.write_text(spec.model_dump_json(indent=2) + "\n", encoding="utf-8")
    rebuild_story_artifacts(brief, plan, refs, run)
    return {
        "stage": "production-plan",
        "plan": plan.model_dump(),
        "artifacts": {
            "review": str(root / REVIEW_RELATIVE),
            "production_review": str(production_path),
            "production_plan": str(plan_json_path),
            "spec": str(spec_path),
        },
        "old_shot_count": directed.old_shot_count,
        "new_shot_count": len(directed.shot_plan.shots),
        "total_duration_seconds": directed.shot_plan.total_duration_seconds,
        "balanced": plans["balanced"].model_dump(),
        "premium": plans["premium"].model_dump(),
        "max": plans["max"].model_dump(),
        "media_calls": 0,
        "stars": 0,
        "provider_http_calls": 0,
        "planned_text_model_calls": len(plan.calls),
        "submitted_text_model_calls": 0,
        "completed_text_model_calls": len(run.model_usage),
        "text_model_calls": 0,
        "ready_for_media_generation": False,
    }


def reconstruct_directed_episode(
    plan: StoryGenerationPlan,
    refs: list[dict[str, object]],
) -> tuple[DirectedEpisode, EpisodeBrief, LocationBible, Any]:
    brief = locked_episode_brief(series_slug=plan.series_slug, episode_number=plan.episode_number)
    run = load_ensemble_checkpoint()
    if run is None or not run.final_script.strip():
        raise ProductError("animatic-plan requires a completed story checkpoint")
    hydrate_succeeded_stages(run)
    spec = parse_friend_group_story(run, brief)
    payload = _parse_json_blob(run.final_script)
    location = location_bible_from_story(brief)
    role_hints = {member.name: member.role_archetype for member in BIRKO_CAST}
    directed = direct_friend_group_episode(
        payload,
        spec,
        brief,
        location,
        locked_refs=refs,
        profile=QualityProfile.PREMIUM,
        role_hints=role_hints,
    )
    return directed, brief, location, run


def execute_animatic_plan(
    *,
    plan: StoryGenerationPlan,
    refs: list[dict[str, object]],
    settings: Settings | None = None,
) -> dict[str, object]:
    directed, brief, location, run = reconstruct_directed_episode(plan, refs)
    voices = proposed_voice_assignments(language=brief.language)
    animatic = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
        settings=settings,
        profile=QualityProfile.PREMIUM,
    )
    root = _repo_root()
    review_rel = animatic_review_relative(brief.series_slug, brief.episode_number)
    review_path = root / review_rel
    json_path = root / ANIMATIC_PLAN_JSON_RELATIVE
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        format_animatic_review(animatic, directed.spec),
        encoding="utf-8",
    )
    json_path.write_text(animatic.model_dump_json(indent=2) + "\n", encoding="utf-8")
    known = sum(float(item.usd or 0) for item in run.model_usage)
    return {
        "stage": "animatic-plan",
        "plan": plan.model_dump(),
        "animatic": animatic.model_dump(),
        "artifacts": {
            "review": str(review_path),
            "animatic_plan": str(json_path),
        },
        "shot_count": animatic.shot_count,
        "unique_image_count": animatic.unique_image_count,
        "sunburst_count": animatic.sunburst_count,
        "flare_count": animatic.flare_count,
        "reused_or_local_shot_count": animatic.reused_or_local_shot_count,
        "voice_provider": animatic.voice_provider,
        "expected_image_usd": animatic.expected_image_usd,
        "expected_voice_usd": animatic.expected_voice_usd,
        "expected_usd": animatic.expected_usd,
        "reserved_usd": animatic.reserved_usd,
        "hard_cap_usd": animatic.hard_cap_usd,
        "cap_ok": animatic.cap_ok,
        "upgrade_estimated_usd": animatic.upgrade_estimated_usd,
        "story_usage_usd": known,
        "media_calls": 0,
        "stars": 0,
        "provider_http_calls": 0,
        "video_provider_calls": 0,
        "planned_text_model_calls": len(plan.calls),
        "submitted_text_model_calls": 0,
        "completed_text_model_calls": len(run.model_usage),
        "text_model_calls": 0,
        "ready_for_animatic_generation": bool(animatic.cap_ok),
    }


def execute_animatic_generation(
    *,
    confirm_paid: bool,
    plan: StoryGenerationPlan,
    refs: list[dict[str, object]],
    settings: Settings | None = None,
    execute_calls: bool = False,
    image_client: Any = None,
    voice_client: Any = None,
    renderer: Any = None,
    work_dir: Path | None = None,
) -> dict[str, object]:
    if not confirm_paid:
        raise PaidApiNotConfirmedError(
            "animatic-generate requires --confirm-paid after animatic-plan approval"
        )
    directed, brief, location, _run = reconstruct_directed_episode(plan, refs)
    voices = proposed_voice_assignments(language=brief.language)
    animatic = build_animatic_plan(
        brief=brief,
        spec=directed.spec,
        shot_plan=directed.shot_plan,
        location=location,
        locked_refs=refs,
        voices=voices,
        settings=settings,
        profile=QualityProfile.PREMIUM,
    )
    if animatic.reserved_usd - 1e-9 > ANIMATIC_PROVIDER_HARD_CAP_USD:
        raise ProductError(
            f"STOP BEFORE HTTP: reserved ${animatic.reserved_usd:.4f} exceeds "
            f"hard cap ${ANIMATIC_PROVIDER_HARD_CAP_USD:.2f}"
        )
    root = _repo_root()
    dest = work_dir or animatic_render_dir(brief.series_slug, brief.episode_number, root=root)
    dest.mkdir(parents=True, exist_ok=True)
    result = execute_animatic_generate(
        animatic,
        confirm_paid=confirm_paid,
        work_dir=dest,
        image_client=image_client,
        voice_client=voice_client,
        renderer=renderer,
        execute_calls=execute_calls,
    )
    result["animatic"] = animatic.model_dump()
    result["plan"] = plan.model_dump()
    result["stars"] = 0
    result["media_calls"] = 0 if not execute_calls else result.get("provider_http_calls", 0)
    result["planned_text_model_calls"] = len(plan.calls)
    result["submitted_text_model_calls"] = 0
    result["completed_text_model_calls"] = 0
    result["text_model_calls"] = 0
    return result


def execute_animatic_rerender(
    *,
    plan: StoryGenerationPlan,
    refs: list[dict[str, object]],
    settings: Settings | None = None,
    work_dir: Path | None = None,
) -> dict[str, object]:
    from docprod.product.animatic_render import render_existing_animatic
    from docprod.product.episode import AnimaticPlan

    root = _repo_root()
    json_path = root / ANIMATIC_PLAN_JSON_RELATIVE
    if json_path.is_file():
        animatic = AnimaticPlan.model_validate_json(json_path.read_text(encoding="utf-8"))
    else:
        directed, brief, location, _run = reconstruct_directed_episode(plan, refs)
        voices = proposed_voice_assignments(language=brief.language)
        animatic = build_animatic_plan(
            brief=brief,
            spec=directed.spec,
            shot_plan=directed.shot_plan,
            location=location,
            locked_refs=refs,
            voices=voices,
            settings=settings,
            profile=QualityProfile.PREMIUM,
        )
    dest_dir = work_dir or animatic_render_dir(
        animatic.series_slug, animatic.episode_number, root=root
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    output = dest_dir / "birko_episode_2_animatic.mp4"
    if animatic.series_slug != "birko":
        output = dest_dir / f"{animatic.series_slug}_episode_{animatic.episode_number}_animatic.mp4"
    truncated = dest_dir / f"{output.stem}_truncated.mp4"
    if output.is_file() and not truncated.is_file():
        from docprod.render.ffmpeg import probe_media

        try:
            if probe_media(output).duration < 10:
                output.replace(truncated)
        except Exception:
            shutil.copy2(output, truncated)
    fixed = dest_dir / f"{output.stem}_fixed.mp4"
    rendered = render_existing_animatic(animatic, work_dir=dest_dir, dest=fixed)
    shutil.copy2(Path(str(rendered["output"])), output)
    rendered["output"] = str(output)
    rendered["fixed_output"] = str(fixed)
    rendered["truncated_backup"] = str(truncated) if truncated.is_file() else ""
    rendered["stage"] = "animatic-rerender"
    rendered["execute"] = True
    rendered["provider_http_calls"] = 0
    rendered["media_calls"] = 0
    rendered["video_provider_calls"] = 0
    rendered["plan"] = plan.model_dump()
    rendered["stars"] = 0
    rendered["planned_text_model_calls"] = len(plan.calls)
    rendered["submitted_text_model_calls"] = 0
    rendered["completed_text_model_calls"] = 0
    rendered["text_model_calls"] = 0
    return rendered


def story_status_report(
    plan: StoryGenerationPlan,
    run: CreativeEnsembleRun | None,
) -> dict[str, object]:
    if run is None:
        run = CreativeEnsembleRun(
            project_id=f"{plan.series_slug}-ep{plan.episode_number}",
            primary_model="gpt-6-astra",
            critic_model="gpt-6-astra",
            finalizer_model="gpt-6-astra",
        )
    hydrate_succeeded_stages(run)
    rows: list[dict[str, object]] = []
    for stage_id in ("treatment_1", "treatment_2", "treatment_3", "critic", "finalizer"):
        text = stage_output_text(run, stage_id)
        record = stage_record_for(run, stage_id)
        usage = next((item for item in run.model_usage if item.call_id == stage_id), None)
        state = record.state if record else ("SUCCEEDED" if text.strip() else "NOT_STARTED")
        rows.append(
            {
                "stage": stage_id,
                "state": state,
                "model": (record.model_id if record else "gpt-6-astra"),
                "request_fingerprint": record.request_fingerprint if record else "",
                "request_id": (record.request_id if record else "")
                or (usage.request_id if usage else ""),
                "response_id": (record.response_id if record else "")
                or (usage.response_id if usage else ""),
                "input_tokens": (record.input_tokens if record else 0)
                or (usage.input_tokens if usage else 0),
                "output_tokens": (record.output_tokens if record else 0)
                or (usage.output_tokens if usage else 0),
                "usd": (record.usd if record else None) or (usage.usd if usage else None),
                "output_present": bool(text.strip()),
                "output_length": len(text),
                "output_hash": output_sha256(text) if text else "",
                "network_id_proven": bool(
                    (record and (record.request_id or record.response_id))
                    or (usage and (usage.request_id or usage.response_id))
                ),
                "safe_to_reuse": state == "SUCCEEDED" and bool(text.strip()),
            }
        )
    known = sum(float(item.usd or 0) for item in run.model_usage)
    completed = sum(1 for row in rows if row["state"] == "SUCCEEDED")
    resume = "SAFE_REUSE_SUCCEEDED" if completed == 5 else "INCOMPLETE_OR_BLOCKED"
    if any(row["state"] in {"SUBMITTED", "UNCERTAIN"} for row in rows):
        resume = "STOP_UNCERTAIN"
    return {
        "stages": rows,
        "planned_text_model_calls": len(plan.calls),
        "submitted_text_model_calls": sum(
            1 for row in rows if row["state"] in {"SUBMITTED", "SUCCEEDED", "UNCERTAIN"}
        ),
        "completed_text_model_calls": completed,
        "known_usd": round(known, 6),
        "resume_safety": resume,
        "media_calls": 0,
    }


def proposed_voice_assignments(*, language: str = "tr") -> list[VoiceAssignment]:
    assignments: list[VoiceAssignment] = []
    for index, member in enumerate(BIRKO_CAST):
        eleven_id, fallback = _ELEVEN_PROPOSED.get(
            member.slug,
            (
                f"eleven_v3_proposed_{member.slug}",
                OPENAI_STOCK_VOICES[index % len(OPENAI_STOCK_VOICES)],
            ),
        )
        assignments.append(
            VoiceAssignment(
                character_name=member.name,
                provider="elevenlabs",
                voice_id=eleven_id,
                display_name=f"Eleven v3 proposed · {member.name}",
                language=language,
                fallback_provider="openai",
                fallback_voice_id=fallback,
                vibe=member.voice_notes,
                cloning=False,
            )
        )
    return assignments


def build_story_generation_plan(
    brief: EpisodeBrief,
    *,
    flagship: bool = True,
    refs: list[dict[str, object]] | None = None,
) -> StoryGenerationPlan:
    ensemble = script_ensemble_plan(QualityProfile.PREMIUM, flagship=flagship)
    primary = str(ensemble["primary_model"])
    finalizer = str(ensemble["finalizer_model"])
    critic = str(ensemble["critic_model"])
    birko_e2 = brief.series_slug == "birko" and brief.episode_number == 2
    if birko_e2:
        critic = str(BIRKO_E2_TARGET_STACK["script_critic"])
    context = story_model_context(brief, refs)
    base_tokens = approx_tokens(str(context))
    treatment_out_est, treatment_out_res = 1600, 2500
    critic_out_est, critic_out_res = 2200, 3500
    final_out_est, final_out_res = 2800, 4000
    treatment_in_est = base_tokens + 400
    treatment_in_res = _headroom(treatment_in_est, extra=1500, factor=1.6)
    critic_in_est = base_tokens + TREATMENT_COUNT * treatment_out_est + 500
    critic_in_res = _headroom(critic_in_est, extra=2500, factor=1.5)
    final_in_est = base_tokens + TREATMENT_COUNT * treatment_out_est + critic_out_est + 600
    final_in_res = _headroom(final_in_est, extra=3000, factor=1.5)
    if birko_e2:
        treatment_in_est = BIRKO_E2_TREATMENT_EST_IN
        treatment_in_res = BIRKO_E2_TREATMENT_RES_IN
        treatment_out_est = BIRKO_E2_TREATMENT_EST_OUT
        treatment_out_res = BIRKO_E2_TREATMENT_RES_OUT
        critic_in_est = BIRKO_E2_CRITIC_EST_IN
        critic_in_res = BIRKO_E2_CRITIC_RES_IN
        critic_out_est = BIRKO_E2_CRITIC_EST_OUT
        critic_out_res = BIRKO_E2_CRITIC_RES_OUT
        final_in_est = BIRKO_E2_FINAL_EST_IN
        final_in_res = BIRKO_E2_FINAL_RES_IN
        final_out_est = BIRKO_E2_FINAL_EST_OUT
        final_out_res = BIRKO_E2_FINAL_RES_OUT
    calls = [
        _call_cost(
            call_id=f"treatment_{index}",
            role="primary",
            model_id=primary,
            purpose=f"creative treatment {index} of the locked premise",
            estimated_input=treatment_in_est,
            reserved_input=treatment_in_res,
            estimated_output=treatment_out_est,
            reserved_output=treatment_out_res,
        )
        for index in range(1, TREATMENT_COUNT + 1)
    ]
    calls.append(
        _call_cost(
            call_id="critic",
            role="critic",
            model_id=critic,
            purpose=(
                "fresh independent critic call: explicit treatments + bible + "
                "locked premise + duration/tone; no treatment-chat state"
            ),
            estimated_input=critic_in_est,
            reserved_input=critic_in_res,
            estimated_output=critic_out_est,
            reserved_output=critic_out_res,
        )
    )
    calls.append(
        _call_cost(
            call_id="finalizer",
            role="finalizer",
            model_id=finalizer,
            purpose="synthesize final FriendGroupStorySpec from treatments + critique",
            estimated_input=final_in_est,
            reserved_input=final_in_res,
            estimated_output=final_out_est,
            reserved_output=final_out_res,
        )
    )
    expected = round(sum(call.expected_usd for call in calls), 6)
    reserved = round(sum(call.reserved_usd for call in calls), 6)
    cap_ok = reserved - 1e-9 <= STORY_HARD_CAP_USD
    if not cap_ok:
        raise ProductError(
            f"STOP: reserved story total ${reserved:.4f} exceeds hard cap "
            f"${STORY_HARD_CAP_USD:.2f}. Cap was not increased."
        )
    return StoryGenerationPlan(
        series_slug=brief.series_slug,
        episode_number=brief.episode_number,
        quality_profile="premium",
        flagship=flagship,
        treatment_count=TREATMENT_COUNT,
        calls=calls,
        estimated_input_tokens=sum(call.estimated_input_tokens for call in calls),
        estimated_output_tokens=sum(call.estimated_output_tokens for call in calls),
        reserved_input_tokens=sum(call.reserved_input_tokens for call in calls),
        reserved_output_tokens=sum(call.reserved_output_tokens for call in calls),
        estimated_usd=expected,
        reserved_usd=reserved,
        cost_confidence="known",
        hard_cap_usd=STORY_HARD_CAP_USD,
        cap_ok=cap_ok,
        execute=False,
        media_calls=0,
        send_image_binaries=False,
        notes=[
            f"Astra pricing as of {STORY_TEXT_PRICING_AS_OF}: {GPT6_ASTRA_PRICING_SOURCE}",
            "Birko Episode 2 critic is gpt-6-astra. ANTHROPIC_API_KEY is not required.",
            "Claude Opus 5.5 remains in the global catalog for future optional ensembles.",
            "Critic is a separate fresh request with critic-specific instructions.",
            "Story models receive episode brief, character bible, relationships, "
            "continuity, constraints, and prior treatments/critique when needed.",
            "Reference images are metadata only (path/hash/dims). No image binaries.",
            "No repository/code context is sent to story models.",
            "Partial ensemble outputs persist; completed treatments are not repeated.",
            "Birko Episode 2 text-model story generation is allowlisted. "
            "--confirm-paid and the $2.50 cap still apply. Media stays disabled.",
            "Zero image/video/audio calls in this plan.",
        ],
    )


def story_generation_outputs() -> list[str]:
    return [
        "FriendGroupStorySpec (title, logline, hook, premise, final_story, beats, dialogue)",
        "CreativeEnsembleRun (3 Astra treatments, fresh Astra critic, Astra final)",
        "PRODUCTION_DIRECTOR EpisodeShotPlan with visible/offscreen cast and routing",
        "EpisodeProductionPlan Balanced/Premium/Max (no media)",
        "LocationBible details filled by engine",
        "prop continuity ledger from generated story",
        "VoiceAssignment proposals (no TTS)",
        REVIEW_RELATIVE,
        PRODUCTION_REVIEW_RELATIVE,
        PLAN_JSON_RELATIVE,
        CHECKPOINT_RELATIVE,
        ANIMATIC_PLAN_JSON_RELATIVE,
    ]


def write_story_plan_artifacts(
    brief: EpisodeBrief,
    plan: StoryGenerationPlan,
    refs: list[dict[str, object]],
) -> dict[str, str]:
    root = _repo_root()
    review_path = root / REVIEW_RELATIVE
    plan_path = root / PLAN_JSON_RELATIVE
    checkpoint_path = root / CHECKPOINT_RELATIVE
    review_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_ensemble_checkpoint()
    if existing is not None and existing.final_script.strip():
        plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
        rebuilt = rebuild_story_artifacts(brief, plan, refs, existing)
        return {
            "review": rebuilt.get("review") or str(review_path),
            "plan": str(plan_path),
            "checkpoint": str(checkpoint_path),
            "spec": rebuilt.get("spec") or "",
        }
    voices = proposed_voice_assignments(language=brief.language)
    location = location_bible_for_brief(brief)
    ref_lines = []
    for row in refs:
        ref_lines.append(
            f"- {row['name']}: present={row['present']} "
            f"path={row['resolved_path']} sha256={row['sha256']} "
            f"{row['width']}x{row['height']}"
        )
    voice_lines = [
        f"- {item.character_name}: {item.provider}/{item.voice_id} "
        f"(fallback {item.fallback_provider}/{item.fallback_voice_id}; no cloning; TTS not called)"
        for item in voices
    ]
    call_lines = [
        (
            f"- {call.call_id}: model={call.model_id} purpose={call.purpose} | "
            f"est_in={call.estimated_input_tokens} reserved_in={call.reserved_input_tokens} | "
            f"est_out={call.estimated_output_tokens} reserved_out="
            f"{call.reserved_output_tokens} | expected=${call.expected_usd:.4f} "
            f"reserved=${call.reserved_usd:.4f}"
        )
        for call in plan.calls
    ]
    review_path.write_text(
        "\n".join(
            [
                "# Birko Episode 2 — Story Review (PLAN ONLY)",
                "",
                "Status: PREMISE LOCKED. STORY NOT GENERATED. MEDIA NOT GENERATED.",
                "",
                "## TITLE",
                "",
                brief.title or "(engine will title after generation)",
                "",
                "## LOGLINE",
                "",
                "ENGINE-OWNED — not written by a human in this checkpoint.",
                "",
                "## HOOK",
                "",
                "ENGINE-OWNED — first 1–3 seconds will be created by VideoForge.",
                "",
                "## CAST",
                "",
                ", ".join(brief.cast_names),
                "",
                "Character bible is authoritative. Identities are locked reference images.",
                "",
                "## LOCKED PREMISE",
                "",
                brief.premise,
                "",
                f"Ending (concept locked): {brief.ending}",
                "",
                f"Location: {brief.location}",
                f"Language: {brief.language}",
                f"Tone: {brief.primary_tone} / {brief.secondary_tone}",
                f"Target duration: {brief.target_duration_seconds[0]:.0f}–"
                f"{brief.target_duration_seconds[1]:.0f} seconds",
                "",
                "## GROUP DYNAMIC",
                "",
                GROUP_DYNAMIC,
                "",
                "## FINAL STORY",
                "",
                "Not generated. `FriendGroupStorySpec` will be produced by Astra treatments, "
                "a fresh Astra critic, then an Astra finalizer.",
                "No screenplay is hardcoded in the repository.",
                "",
                "## SCENE BREAKDOWN",
                "",
                "ENGINE-OWNED. Empty until story-generate.",
                "",
                "## ALL DIALOGUE",
                "",
                "ENGINE-OWNED. Empty until story-generate. Dialogue-first; not narrator-only.",
                "",
                "## NARRATION",
                "",
                "ENGINE-OWNED. Sparse only if needed for compression/transitions.",
                "",
                "## SHOT PLAN",
                "",
                "ENGINE-OWNED after the final story exists. Scenes may map to multiple shots.",
                "Requirements first (STATIC_KEYFRAME, DIALOGUE_COVERAGE,",
                "MULTI_REFERENCE_SCENE, …). Router chooses eligible implementations.",
                "Catalog-only models stay catalog-only.",
                "",
                "## VOICE ASSIGNMENTS (proposed, TTS not called)",
                "",
                *voice_lines,
                "",
                "## VISUAL CONTINUITY",
                "",
                "Each shot must list `cast_refs`. Recurring characters use locked refs only.",
                "",
                "### Character references",
                "",
                *ref_lines,
                "",
                "### Location bible (name locked; details engine-owned)",
                "",
                f"name={location.name} engine_owned_details={location.engine_owned_details}",
                "",
                "## PROP CONTINUITY",
                "",
                "ENGINE-OWNED after script generation. Track bill/receipt, boxes, drinks, "
                "phone, last donut only if the generated story introduces them.",
                "",
                "## MODEL REQUIREMENTS PER SHOT",
                "",
                "Not generated. After story-generate the shot planner emits production class, "
                "preferred_model, fallback_model, implementation_status.",
                "",
                "## EXPECTED DURATION",
                "",
                f"{brief.target_duration_seconds[0]:.0f}–{brief.target_duration_seconds[1]:.0f}s",
                "",
                "## STORY MODEL COST",
                "",
                *call_lines,
                "",
                f"estimated_input_tokens={plan.estimated_input_tokens}",
                f"estimated_output_tokens={plan.estimated_output_tokens}",
                f"reserved_input_tokens={plan.reserved_input_tokens}",
                f"reserved_output_tokens={plan.reserved_output_tokens}",
                f"EXPECTED STORY TOTAL=${plan.estimated_usd}",
                f"RESERVED STORY TOTAL=${plan.reserved_usd}",
                f"HARD CAP=${plan.hard_cap_usd}",
                f"cap_ok={plan.cap_ok} confidence={plan.cost_confidence}",
                "send_image_binaries=false",
                "execute=false",
                "image/video/audio calls=0",
                "Stars=0",
                "",
                "## COMMANDS",
                "",
                "`uv run docprod friend-group-episode --series-slug birko "
                "--episode 2 --stage story-plan`",
                "`uv run docprod birko-episode2 --stage story-plan`",
                "`uv run docprod birko-episode2 --stage story-generate --confirm-paid`",
                "(requires allowlisted episode + --confirm-paid; media stays off)",
                "",
                "## OUTPUTS STORY GENERATION WILL CREATE",
                "",
                *[f"- {item}" for item in story_generation_outputs()],
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    primary, critic, finalizer = _models_from_plan(plan)
    existing = load_ensemble_checkpoint()
    if existing is not None and remaining_ensemble_stages(existing) != [
        "treatment_1",
        "treatment_2",
        "treatment_3",
        "critic",
        "finalizer",
    ]:
        checkpoint = existing
    else:
        checkpoint = CreativeEnsembleRun(
            project_id=f"{brief.series_slug}-ep{brief.episode_number}",
            primary_model=primary,
            critic_model=critic,
            finalizer_model=finalizer,
            treatments=["", "", ""],
            executed=False,
        )
    save_ensemble_checkpoint(checkpoint)
    return {
        "review": str(review_path),
        "plan": str(plan_path),
        "checkpoint": str(checkpoint_path),
    }


def run_friend_group_episode(
    *,
    stage: str,
    series_slug: str = "birko",
    episode_number: int = 2,
    confirm_paid: bool = False,
    settings: Settings | None = None,
    text_client: StoryTextClient | None = None,
    execute_calls: bool | None = None,
    retry_failed: bool = False,
    only_scenes: str | None = None,
) -> dict[str, object]:
    token = stage.strip().lower().replace("_", "-")
    brief = locked_episode_brief(series_slug=series_slug, episode_number=episode_number)
    refs = inspect_locked_character_refs() if series_slug == "birko" else []
    plan = build_story_generation_plan(brief, flagship=True, refs=refs)
    readiness = story_generation_readiness(plan, settings=settings)
    if token in {"story-status", "status"}:
        run = load_ensemble_checkpoint()
        status = story_status_report(plan, run)
        return {
            "stage": "story-status",
            "status": status,
            "plan": plan.model_dump(),
            "planned_text_model_calls": status["planned_text_model_calls"],
            "submitted_text_model_calls": status["submitted_text_model_calls"],
            "completed_text_model_calls": status["completed_text_model_calls"],
            "text_model_calls": status["completed_text_model_calls"],
            "media_calls": 0,
            "stars": 0,
        }
    if token in {"story-plan", "plan", "story-check", "check"}:
        paths = write_story_plan_artifacts(brief, plan, refs)
        return {
            "stage": "story-check" if token in {"story-check", "check"} else "story-plan",
            "brief": brief.model_dump(),
            "plan": plan.model_dump(),
            "readiness": readiness,
            "ready": bool(readiness["ready"]),
            "refs": refs,
            "voices": [item.model_dump() for item in proposed_voice_assignments()],
            "location": location_bible_for_brief(brief).model_dump(),
            "artifacts": paths,
            "prompt": episode_2_draft_prompt() if series_slug == "birko" else "",
            "media_calls": 0,
            "stars": 0,
            "planned_text_model_calls": len(plan.calls),
            "submitted_text_model_calls": 0,
            "completed_text_model_calls": 0,
            "text_model_calls": 0,
        }
    if token in {"story-generate", "generate"}:
        return execute_story_generation(
            confirm_paid=confirm_paid,
            plan=plan,
            settings=settings,
            text_client=text_client,
            execute_calls=True if execute_calls is None else execute_calls,
        )
    if token in {"production-plan", "production-director", "director"}:
        return execute_production_director(
            plan=plan,
            refs=refs,
            settings=settings,
        )
    if token in {"animatic-plan"}:
        return execute_animatic_plan(plan=plan, refs=refs, settings=settings)
    if token in {"animatic-generate"}:
        return execute_animatic_generation(
            confirm_paid=confirm_paid,
            plan=plan,
            refs=refs,
            settings=settings,
            execute_calls=True if execute_calls is None else execute_calls,
        )
    if token in {"animatic-rerender", "animatic-repair"}:
        return execute_animatic_rerender(
            plan=plan,
            refs=refs,
            settings=settings,
        )
    if token in {"simple-script-plan"}:
        from docprod.product.simple_video import execute_simple_script_plan

        return execute_simple_script_plan(brief=brief, refs=refs)
    if token in {"simple-script-generate"}:
        from docprod.product.simple_video import execute_simple_script_generate

        return execute_simple_script_generate(
            confirm_paid=confirm_paid,
            brief=brief,
            refs=refs,
            settings=settings,
            text_client=text_client,
            execute_calls=True if execute_calls is None else execute_calls,
        )
    if token in {"simple-video-plan"}:
        from docprod.product.simple_video import execute_simple_video_plan

        return execute_simple_video_plan(brief=brief, refs=refs, settings=settings)
    if token in {"simple-video-generate"}:
        from docprod.product.simple_video import execute_simple_video_generate

        return execute_simple_video_generate(
            confirm_paid=confirm_paid,
            brief=brief,
            refs=refs,
            settings=settings,
            execute_calls=True if execute_calls is None else execute_calls,
        )
    if token in {"higgsfield-scene-plan"}:
        from docprod.product.higgsfield_scenes import execute_higgsfield_scene_plan

        return execute_higgsfield_scene_plan(refs=refs, settings=settings)
    if token in {"higgsfield-scene-preflight"}:
        from docprod.product.higgsfield_scenes import execute_higgsfield_scene_preflight

        return execute_higgsfield_scene_preflight(
            refs=refs,
            settings=settings,
            series_slug=series_slug,
            episode_number=episode_number,
        )
    if token in {"higgsfield-scene-resume"}:
        from docprod.product.higgsfield_scenes import execute_higgsfield_scene_resume

        return execute_higgsfield_scene_resume(refs=refs, settings=settings)
    if token in {"higgsfield-scene-generate"}:
        from docprod.product.higgsfield_scenes import execute_higgsfield_scene_generate

        return execute_higgsfield_scene_generate(
            confirm_paid=confirm_paid,
            refs=refs,
            settings=settings,
            series_slug=series_slug,
            episode_number=episode_number,
            execute_calls=True if execute_calls is None else execute_calls,
            retry_failed=retry_failed,
            only_scenes=only_scenes,
        )
    raise ValueError(
        f"unknown stage {stage!r}; use story-plan, story-check, story-status, "
        "story-generate, production-plan, animatic-plan, animatic-generate, "
        "animatic-rerender, simple-script-plan, simple-script-generate, "
        "simple-video-plan, simple-video-generate, higgsfield-scene-plan, "
        "higgsfield-scene-preflight, higgsfield-scene-resume, or higgsfield-scene-generate"
    )


def execute_story_generation(
    *,
    confirm_paid: bool,
    plan: StoryGenerationPlan,
    checkpoint: CreativeEnsembleRun | None = None,
    settings: Settings | None = None,
    text_client: StoryTextClient | None = None,
    execute_calls: bool = True,
    persist: bool = True,
) -> dict[str, object]:
    if not confirm_paid:
        raise PaidApiNotConfirmedError(
            "story-generate requires --confirm-paid after explicit authorization"
        )
    if plan.reserved_usd - 1e-9 > plan.hard_cap_usd:
        raise ProductError(
            f"STOP: reserved story total ${plan.reserved_usd:.4f} exceeds hard cap "
            f"${plan.hard_cap_usd:.2f}. Cap was not increased."
        )
    if not story_generation_authorized(plan.series_slug, plan.episode_number):
        raise AuthorizationError(
            f"story generation is not allowlisted for {plan.series_slug} "
            f"episode {plan.episode_number}"
        )
    cfg = settings or get_settings()
    if not openai_key_present(cfg):
        raise MissingApiKeyError(
            "OPENAI_API_KEY is not set. Add it to .env (never commit the file)."
        )
    primary, critic, finalizer = _models_from_plan(plan)
    run = checkpoint or load_ensemble_checkpoint()
    if run is None:
        run = CreativeEnsembleRun(
            project_id=f"{plan.series_slug}-ep{plan.episode_number}",
            primary_model=primary,
            critic_model=critic,
            finalizer_model=finalizer,
            treatments=["", "", ""],
            executed=False,
        )
    _pad_treatments(run)
    hydrate_succeeded_stages(run)
    remaining = remaining_ensemble_stages(run)
    entered_executor = True
    if not execute_calls:
        return {
            "stage": "story-generate",
            "authorized": True,
            "entered_executor": entered_executor,
            "execute_calls": False,
            "remaining_stages": remaining,
            "usage_records": len(run.model_usage),
            "media_calls": 0,
            "stars": 0,
            "planned_text_model_calls": len(plan.calls),
            "submitted_text_model_calls": 0,
            "completed_text_model_calls": len(run.model_usage),
            "text_model_calls": 0,
            "plan": plan.model_dump(),
        }
    if not remaining:
        artifacts = {}
        if persist:
            artifacts = rebuild_story_artifacts(
                locked_episode_brief(
                    series_slug=plan.series_slug, episode_number=plan.episode_number
                ),
                plan,
                inspect_locked_character_refs() if plan.series_slug == "birko" else [],
                run,
            )
        return {
            "stage": "story-generate",
            "authorized": True,
            "entered_executor": entered_executor,
            "execute_calls": True,
            "provider_http_calls": 0,
            "remaining_stages": [],
            "usage_records": len(run.model_usage),
            "media_calls": 0,
            "stars": 0,
            "planned_text_model_calls": len(plan.calls),
            "submitted_text_model_calls": len(run.model_usage),
            "completed_text_model_calls": len(run.model_usage),
            "text_model_calls": len(run.model_usage),
            "plan": plan.model_dump(),
            "artifacts": artifacts,
            "checkpoint": str(_checkpoint_path()),
        }
    client = text_client or OpenAIStoryClient(cfg)
    context = json.dumps(
        story_model_context(
            locked_episode_brief(
                series_slug=plan.series_slug,
                episode_number=plan.episode_number,
            )
        ),
        ensure_ascii=False,
    )
    spent = sum(float(item.usd or 0) for item in run.model_usage)
    reserved_by_id = {call.call_id: call.reserved_usd for call in plan.calls}
    http_calls = 0
    for stage_id in remaining:
        reserved = float(reserved_by_id.get(stage_id, 0))
        if spent + reserved - 1e-9 > plan.hard_cap_usd:
            raise ProductError(
                f"STOP: spent ${spent:.4f} plus reserved ${reserved:.4f} for {stage_id} "
                f"exceeds hard cap ${plan.hard_cap_usd:.2f}"
            )
        if stage_id.startswith("treatment_"):
            index = int(stage_id.rsplit("_", 1)[-1])
            instructions = HOOK_FIRST_WRITER_INSTRUCTIONS
            payload = (
                f"Write creative treatment {index} of 3. Do not see other treatments.\n"
                f"{context}"
            )
            model_id = primary
        elif stage_id == "critic":
            instructions = CRITIC_SYSTEM
            payload = (
                "FRESH CRITIC CALL. No hidden conversation state.\n"
                f"{context}\n\nTREATMENT 1:\n{run.treatments[0]}\n\n"
                f"TREATMENT 2:\n{run.treatments[1]}\n\nTREATMENT 3:\n{run.treatments[2]}"
            )
            model_id = critic
        else:
            instructions = FINALIZER_SYSTEM
            payload = (
                f"{context}\n\nTREATMENT 1:\n{run.treatments[0]}\n\n"
                f"TREATMENT 2:\n{run.treatments[1]}\n\nTREATMENT 3:\n{run.treatments[2]}\n\n"
                f"CRITIC:\n{run.critic_output}"
            )
            model_id = finalizer
        fingerprint = content_hash(
            {"stage": stage_id, "model": model_id, "input": payload}
        )
        stage = stage_record_for(run, stage_id)
        if stage is None:
            stage = EnsembleStageRecord(stage_id=stage_id, model_id=model_id)
            run.stages.append(stage)
        stage.state = "PREPARED"
        stage.model_id = model_id
        stage.request_fingerprint = fingerprint
        stage.reserved_usd = reserved
        if persist:
            save_ensemble_checkpoint(run)
        response = client.create(
            model=model_id,
            instructions=instructions,
            input_text=payload,
            confirm_paid=True,
        )
        http_calls += 1
        text = _output_text(response)
        record = _usage_from_response(
            response, call_id=stage_id, model_id=model_id, fingerprint=fingerprint
        )
        run.model_usage.append(record)
        spent += float(record.usd or 0)
        stage.request_id = record.request_id
        stage.response_id = record.response_id
        stage.input_tokens = record.input_tokens
        stage.output_tokens = record.output_tokens
        stage.usd = record.usd
        stage.output_length = len(text)
        stage.output_hash = output_sha256(text)
        stage.state = "SUCCEEDED" if text.strip() else "UNCERTAIN"
        if stage_id.startswith("treatment_"):
            index = int(stage_id.rsplit("_", 1)[-1])
            run.treatments[index - 1] = text
        elif stage_id == "critic":
            run.critic_output = text
        else:
            run.final_script = text
            run.executed = True
        if persist:
            save_ensemble_checkpoint(run)
    artifacts = {}
    if persist and run.final_script.strip():
        try:
            artifacts = rebuild_story_artifacts(
                locked_episode_brief(
                    series_slug=plan.series_slug, episode_number=plan.episode_number
                ),
                plan,
                inspect_locked_character_refs() if plan.series_slug == "birko" else [],
                run,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            artifacts = {}
    return {
        "stage": "story-generate",
        "authorized": True,
        "entered_executor": entered_executor,
        "execute_calls": True,
        "provider_http_calls": http_calls,
        "remaining_stages": remaining_ensemble_stages(run),
        "usage_records": len(run.model_usage),
        "media_calls": 0,
        "stars": 0,
        "planned_text_model_calls": len(plan.calls),
        "submitted_text_model_calls": http_calls,
        "completed_text_model_calls": len(
            [item for item in run.model_usage if item.input_tokens or item.output_tokens]
        ),
        "text_model_calls": http_calls,
        "plan": plan.model_dump(),
        "artifacts": artifacts,
        "checkpoint": str(_checkpoint_path()),
    }
