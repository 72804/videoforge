from __future__ import annotations

from pathlib import Path

from PIL import Image

from docprod.exceptions import PaidApiNotConfirmedError
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
from docprod.product.series import (
    BIRKO_E2_TARGET_STACK,
    birko_character_refs_dir,
    list_birko_ref_inventory,
)
from docprod.providers.pricing import (
    GPT6_ASTRA_PRICING_SOURCE,
    STORY_TEXT_PRICING_AS_OF,
    text_tokens_cost_usd,
)
from docprod.quality.catalog import get_model
from docprod.quality.ensemble import CreativeEnsembleRun, remaining_ensemble_stages
from docprod.quality.enums import QualityProfile
from docprod.quality.policy_select import OPENAI_STOCK_VOICES
from docprod.quality.story_director import script_ensemble_plan
from docprod.storage.hashing import file_sha256

STORY_HARD_CAP_USD = 2.50
STORY_GENERATE_AUTHORIZED = False
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

_ELEVEN_PROPOSED = {
    "birko": ("eleven_v3_proposed_low_energy_tr", "ash"),
    "kemal": ("eleven_v3_proposed_earnest_baritone_tr", "cedar"),
    "muge": ("eleven_v3_proposed_flirty_alto_tr", "coral"),
    "erni": ("eleven_v3_proposed_sweet_manipulator_tr", "shimmer"),
    "hg": ("eleven_v3_proposed_devilish_tr", "verse"),
    "musti": ("eleven_v3_proposed_young_gremlin_tr", "sage"),
}


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
    folder = birko_character_refs_dir()
    inventory = list_birko_ref_inventory()
    by_slug = inventory["by_slug"] if isinstance(inventory["by_slug"], dict) else {}
    rows: list[dict[str, object]] = []
    for member in BIRKO_CAST:
        row = by_slug.get(member.slug) if isinstance(by_slug, dict) else {}
        found = list(row.get("found") or []) if isinstance(row, dict) else []
        if not found:
            rows.append(
                {
                    "slug": member.slug,
                    "name": member.name,
                    "expected": list(member.expected_ref_filenames),
                    "resolved_path": "",
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
            "Do not execute text models until story-generate is authorized.",
            "Zero image/video/audio calls in this plan.",
        ],
    )


def story_generation_outputs() -> list[str]:
    return [
        "FriendGroupStorySpec (title, logline, hook, premise, beats, dialogue, narration, "
        "callbacks, payoff, ending, continuity, motion graphics, audio intent)",
        "CreativeEnsembleRun (3 Astra treatments, fresh Astra critic, Astra final)",
        "EpisodeShotPlan with per-shot production class and cast_refs",
        "LocationBible details filled by engine",
        "prop continuity ledger from generated story",
        "VoiceAssignment proposals (no TTS)",
        REVIEW_RELATIVE,
        PLAN_JSON_RELATIVE,
        CHECKPOINT_RELATIVE,
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
                "Not generated. `FriendGroupStorySpec` will be produced by Astra→Opus→Astra.",
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
                "`uv run docprod birko-episode2 --stage story-generate`",
                "(story-generate is refused until authorized)",
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
    checkpoint = CreativeEnsembleRun(
        project_id=f"{brief.series_slug}-ep{brief.episode_number}",
        primary_model=primary,
        critic_model=critic,
        finalizer_model=finalizer,
        treatments=["", "", ""],
        executed=False,
    )
    checkpoint_path.write_text(checkpoint.model_dump_json(indent=2) + "\n", encoding="utf-8")
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
) -> dict[str, object]:
    token = stage.strip().lower().replace("_", "-")
    brief = locked_episode_brief(series_slug=series_slug, episode_number=episode_number)
    refs = inspect_locked_character_refs() if series_slug == "birko" else []
    plan = build_story_generation_plan(brief, flagship=True, refs=refs)
    if token in {"story-plan", "plan"}:
        paths = write_story_plan_artifacts(brief, plan, refs)
        return {
            "stage": "story-plan",
            "brief": brief.model_dump(),
            "plan": plan.model_dump(),
            "refs": refs,
            "voices": [item.model_dump() for item in proposed_voice_assignments()],
            "location": location_bible_for_brief(brief).model_dump(),
            "artifacts": paths,
            "prompt": episode_2_draft_prompt() if series_slug == "birko" else "",
            "media_calls": 0,
            "stars": 0,
            "text_model_calls": 0,
        }
    if token in {"story-generate", "generate"}:
        return execute_story_generation(confirm_paid=confirm_paid, plan=plan)
    raise ValueError(f"unknown stage {stage!r}; use story-plan or story-generate")


def execute_story_generation(
    *,
    confirm_paid: bool,
    plan: StoryGenerationPlan,
    checkpoint: CreativeEnsembleRun | None = None,
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
    primary, critic, finalizer = _models_from_plan(plan)
    run = checkpoint or CreativeEnsembleRun(
        project_id=f"{plan.series_slug}-ep{plan.episode_number}",
        primary_model=primary,
        critic_model=critic,
        finalizer_model=finalizer,
        treatments=["", "", ""],
        executed=False,
    )
    remaining = remaining_ensemble_stages(run)
    if not STORY_GENERATE_AUTHORIZED:
        raise AuthorizationError(
            "text-model story generation is not authorized in this checkpoint; "
            f"remaining_stages={remaining}; usage_records={len(run.model_usage)}"
        )
    raise AuthorizationError("unreachable: story generate must not call providers yet")
