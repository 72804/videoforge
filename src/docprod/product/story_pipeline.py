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
from docprod.product.errors import AuthorizationError
from docprod.product.series import birko_character_refs_dir, list_birko_ref_inventory
from docprod.quality.enums import QualityProfile
from docprod.quality.policy_select import OPENAI_STOCK_VOICES
from docprod.quality.story_director import script_ensemble_plan
from docprod.storage.hashing import file_sha256

STORY_HARD_CAP_USD = 2.50
STORY_GENERATE_AUTHORIZED = False
TREATMENT_COUNT = 3
REVIEW_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_story_review.md"
)
PLAN_JSON_RELATIVE = (
    "projects/birko_kemal_drama_canary/artifacts/review/episode_2_story_plan.json"
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
) -> StoryGenerationPlan:
    ensemble = script_ensemble_plan(QualityProfile.PREMIUM, flagship=flagship)
    treatment_in, treatment_out = 3500, 1800
    critic_in, critic_out = 6500, 2500
    final_in, final_out = 7000, 3500
    calls = [
        StoryCallSpec(
            role="primary",
            model_id=str(ensemble["primary_model"]),
            count=TREATMENT_COUNT,
            purpose="creative treatments of the locked premise",
            estimated_input_tokens=treatment_in,
            estimated_output_tokens=treatment_out,
        ),
        StoryCallSpec(
            role="critic",
            model_id=str(ensemble["critic_model"]),
            count=1,
            purpose="independent story/dialogue critique",
            estimated_input_tokens=critic_in,
            estimated_output_tokens=critic_out,
        ),
        StoryCallSpec(
            role="finalizer",
            model_id=str(ensemble["finalizer_model"]),
            count=1,
            purpose="synthesize final FriendGroupStorySpec",
            estimated_input_tokens=final_in,
            estimated_output_tokens=final_out,
        ),
    ]
    input_tokens = TREATMENT_COUNT * treatment_in + critic_in + final_in
    output_tokens = TREATMENT_COUNT * treatment_out + critic_out + final_out
    planning_usd = round(
        (input_tokens / 1_000_000) * 15.0 + (output_tokens / 1_000_000) * 75.0,
        2,
    )
    return StoryGenerationPlan(
        series_slug=brief.series_slug,
        episode_number=brief.episode_number,
        quality_profile="premium",
        flagship=flagship,
        treatment_count=TREATMENT_COUNT,
        calls=calls,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_usd=planning_usd,
        cost_confidence="unresolved",
        hard_cap_usd=STORY_HARD_CAP_USD,
        execute=False,
        media_calls=0,
        notes=[
            "GPT-6 Astra and Claude Opus 5.5 unit prices are unresolved in the catalog.",
            "estimated_usd uses conservative analog rates for planning only.",
            "Do not execute text models until story-generate is authorized.",
            "Zero image/video/audio calls in this plan.",
            f"Locked premise for {brief.series_slug} ep {brief.episode_number}.",
            "Engine owns hook, scenes, dialogue, shots; user owns premise/cast/location/tone.",
        ],
    )


def story_generation_outputs() -> list[str]:
    return [
        "FriendGroupStorySpec (title, logline, hook, premise, beats, dialogue, narration, "
        "callbacks, payoff, ending, continuity, motion graphics, audio intent)",
        "CreativeEnsembleRun (3 treatments, Opus critique, Astra final)",
        "EpisodeShotPlan with per-shot production class and cast_refs",
        "LocationBible details filled by engine",
        "prop continuity ledger from generated story",
        "VoiceAssignment proposals (no TTS)",
        REVIEW_RELATIVE,
        PLAN_JSON_RELATIVE,
    ]


def write_story_plan_artifacts(
    brief: EpisodeBrief,
    plan: StoryGenerationPlan,
    refs: list[dict[str, object]],
) -> dict[str, str]:
    root = _repo_root()
    review_path = root / REVIEW_RELATIVE
    plan_path = root / PLAN_JSON_RELATIVE
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
        f"- {call.role}: {call.model_id} ×{call.count} — {call.purpose} "
        f"(~{call.estimated_input_tokens} in / {call.estimated_output_tokens} out per call)"
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
                f"estimated_usd={plan.estimated_usd} (confidence={plan.cost_confidence})",
                f"hard_cap_usd={plan.hard_cap_usd}",
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
    return {"review": str(review_path), "plan": str(plan_path)}


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
    plan = build_story_generation_plan(brief, flagship=True)
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
) -> dict[str, object]:
    if not confirm_paid:
        raise PaidApiNotConfirmedError(
            "story-generate requires --confirm-paid after explicit authorization"
        )
    if not STORY_GENERATE_AUTHORIZED:
        raise AuthorizationError(
            "text-model story generation is not authorized in this checkpoint"
        )
    raise AuthorizationError("unreachable: story generate must not call providers yet")
