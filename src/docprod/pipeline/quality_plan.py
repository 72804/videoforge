from __future__ import annotations

from dataclasses import dataclass

from docprod.audio.models import RuntimeTimeline
from docprod.models.scene import ScenePlan
from docprod.quality.availability import availability
from docprod.quality.budget import allocate_video
from docprod.quality.character import character_set_for_drama
from docprod.quality.cost_plan import build_cost_plan
from docprod.quality.critic import critique_script
from docprod.quality.driving import driving_plan_for, needs_driving_performance
from docprod.quality.enums import QualityProfile
from docprod.quality.gates import preflight_gates
from docprod.quality.locked import B07_I2V_PROMPT, apply_runtime_durations
from docprod.quality.report import profile_summary, render_router_markdown
from docprod.quality.shots import (
    audio_driven_request_for,
    dialogue_request_for,
    performance_request_for,
)
from docprod.quality.tts_compare import compare_narrators
from docprod.storage.json_store import load_model, save_json
from docprod.storage.paths import ProjectPaths
from docprod.writing.models import NarrationScript

PROFILES = tuple(QualityProfile)


@dataclass
class QualityPlanBundle:
    profile: QualityProfile
    markdown_path: str
    json_path: str
    summary: dict
    gate_passed: bool


def plan_quality(
    paths: ProjectPaths,
    *,
    profile: QualityProfile,
    upgrade_existing: bool = True,
) -> QualityPlanBundle:
    plan = load_model(paths.scene_plan_json, ScenePlan)
    if paths.runtime_timeline_json().is_file():
        timeline = load_model(paths.runtime_timeline_json(), RuntimeTimeline)
        plan = apply_runtime_durations(plan, timeline)
    decisions = allocate_video(plan, profile, allow_manual_inputs=False)
    cost = build_cost_plan(
        project_id=plan.project_id,
        profile=profile,
        decisions=decisions,
        upgrade_existing=upgrade_existing,
    )
    uniqueness = str(paths.root.name).endswith("drama_canary") or any(
        s.metadata.get("episode_mode") == "custom_short_drama" for s in plan.scenes
    )
    gates = preflight_gates(plan, profile=profile, cost=cost, uniqueness_required=uniqueness)
    critic = None
    script_chars = 0
    if paths.story_script_json().is_file():
        script = load_model(paths.story_script_json(), NarrationScript)
        critic = critique_script(script, plan)
        script_chars = len(script.full_narration)
    charset = character_set_for_drama(paths)
    dialogue = [dialogue_request_for(s) for s in plan.scenes]
    audio_driven = [audio_driven_request_for(s) for s in plan.scenes]
    performance = [performance_request_for(s) for s in plan.scenes]
    driving = [
        driving_plan_for(s).model_dump()
        for s, decision in zip(plan.scenes, decisions, strict=True)
        if needs_driving_performance(s, model_id=decision.selected_model)
    ]
    awaiting_human = any(d.manual_input_required and d.needs_driving_performance for d in decisions)
    b07 = next((s for s in plan.scenes if (s.metadata or {}).get("beat_id") == "b07"), None)
    tts_rows = compare_narrators(
        character_count=script_chars or 2500,
        speech_minutes=max(plan.scenes[-1].end / 60.0, 0.1) if plan.scenes else 2.0,
        cached_openai=upgrade_existing,
    )
    summary = profile_summary(decisions, cost)
    payload = {
        "project_id": plan.project_id,
        "profile": profile.value,
        "availability": {k: v.value for k, v in availability().providers.items()},
        "local_endpoints": {k: v.value for k, v in availability().local_endpoints.items()},
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "cost": cost.model_dump(mode="json"),
        "summary": summary,
        "gates": {"passed": gates.passed, "errors": gates.errors, "warnings": gates.warnings},
        "critic": critic.model_dump() if critic else None,
        "characters": charset.model_dump(),
        "dialogue_shots": [d.model_dump() for d in dialogue if d],
        "audio_driven_dialogue": [d.model_dump() for d in audio_driven if d],
        "performance_shots": [p.model_dump() for p in performance if p],
        "driving_performance": driving,
        "awaiting_human_performance": awaiting_human,
        "b07_i2v_prompt": B07_I2V_PROMPT if b07 is not None else "",
        "automation": {
            "allow_manual_inputs": False,
            "human_performance_required": False,
            "default_path": "script→images→video→dialogue→music→sfx→render",
        },
        "tts_comparison": [row.model_dump(mode="json") for row in tts_rows],
        "reuse": {
            "stills": True,
            "title_cards": True,
            "narration": upgrade_existing,
            "alignment": upgrade_existing,
            "lyria_music": True,
            "generic_sfx": True,
        },
        "episode_outputs": {
            "v1": "birko_kemal_drama_v1.mp4",
            "v2": "birko_kemal_drama_v2.mp4",
        },
        "paid_calls": 0,
    }
    review = paths.review_dir
    review.mkdir(parents=True, exist_ok=True)
    stem = f"quality_router_plan_{profile.value}"
    md_path = review / f"{stem}.md"
    json_path = review / f"{stem}.json"
    md_path.write_text(
        render_router_markdown(
            project_id=plan.project_id,
            profile=profile,
            decisions=decisions,
            cost=cost,
            plan=plan,
        ),
        encoding="utf-8",
    )
    save_json(json_path, payload)
    v2_md = review / f"quality_router_plan_v2_{profile.value}.md"
    v2_json = review / f"quality_router_plan_v2_{profile.value}.json"
    v2_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    save_json(v2_json, payload)
    if profile is QualityProfile.BALANCED:
        (review / "quality_router_plan.md").write_text(
            md_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        save_json(review / "quality_router_plan.json", payload)
    return QualityPlanBundle(
        profile=profile,
        markdown_path=str(md_path),
        json_path=str(json_path),
        summary=summary,
        gate_passed=gates.passed,
    )


def plan_all_profiles(paths: ProjectPaths) -> list[QualityPlanBundle]:
    return [plan_quality(paths, profile=profile) for profile in QualityProfile]
