from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from docprod.product.ids import new_id
from docprod.product.models import ScriptVersion, utcnow
from docprod.quality.story_director import script_ensemble_plan

ENSEMBLE_STAGES = (
    "treatment_1",
    "treatment_2",
    "treatment_3",
    "critic",
    "finalizer",
)


class CreativeScorecard(BaseModel):
    """Heuristic only. Never shown as scientific scores to customers."""

    model_config = ConfigDict(extra="forbid")

    hook_strength: float = 0.0
    character_specificity: float = 0.0
    dialogue_naturalness: float = 0.0
    escalation: float = 0.0
    callback_quality: float = 0.0
    payoff: float = 0.0
    shareability: float = 0.0
    visual_opportunity: float = 0.0
    production_feasibility: float = 0.0
    continuity: float = 0.0
    inside_joke_usage: float = 0.0
    raw_critique: str = ""
    keep: list[str] = Field(default_factory=list)
    change: list[str] = Field(default_factory=list)
    reject_if_blindly_applied: list[str] = Field(default_factory=list)
    memeable_moments: list[str] = Field(default_factory=list)
    feasibility_risks: list[str] = Field(default_factory=list)


class EnsembleUsageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float | None = None


class CreativeEnsembleRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    project_id: str
    task: str = "premium_script"
    primary_model: str
    critic_model: str = ""
    finalizer_model: str
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    treatments: list[str] = Field(default_factory=list)
    critic_output: str = ""
    scorecard: CreativeScorecard | None = None
    final_script: str = ""
    model_usage: list[EnsembleUsageRecord] = Field(default_factory=list)
    executed: bool = False
    created_at: str = ""


def completed_ensemble_stages(run: CreativeEnsembleRun) -> list[str]:
    done: list[str] = []
    for index, text in enumerate(run.treatments):
        if str(text).strip():
            done.append(f"treatment_{index + 1}")
    if run.critic_output.strip():
        done.append("critic")
    if run.final_script.strip():
        done.append("finalizer")
    return done


def remaining_ensemble_stages(run: CreativeEnsembleRun) -> list[str]:
    done = set(completed_ensemble_stages(run))
    return [stage for stage in ENSEMBLE_STAGES if stage not in done]


def scorecard_for_staff(card: CreativeScorecard) -> dict[str, float | str | list[str]]:
    return card.model_dump()


def scorecard_for_customer(_card: CreativeScorecard) -> dict[str, str]:
    """Normal UX never sees numeric internals."""
    return {}


def persist_ensemble_on_script(
    script: ScriptVersion,
    run: CreativeEnsembleRun,
) -> ScriptVersion:
    payload = dict(script.story_spec)
    payload["ensemble"] = run.model_dump()
    return script.model_copy(update={"story_spec": payload})


def planned_ensemble_run(project_id: str, plan: dict) -> CreativeEnsembleRun:
    return CreativeEnsembleRun(
        project_id=project_id,
        primary_model=str(plan.get("primary_model") or ""),
        critic_model=str(plan.get("critic_model") or ""),
        finalizer_model=str(plan.get("finalizer_model") or ""),
        prompt_versions=dict(plan.get("prompt_versions") or {}),
        executed=False,
        created_at=utcnow().isoformat(),
    )


def plan_and_persist_script_ensemble(
    script: ScriptVersion,
    *,
    profile,
    flagship: bool = False,
) -> tuple[ScriptVersion, CreativeEnsembleRun]:
    plan = script_ensemble_plan(profile, flagship=flagship)
    run = planned_ensemble_run(script.project_id, plan)
    return persist_ensemble_on_script(script, run), run
