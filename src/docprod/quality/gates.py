from __future__ import annotations

from dataclasses import dataclass, field

from docprod.drama.uniqueness import collage_violations, duplicate_fingerprints
from docprod.models.scene import ScenePlan
from docprod.quality.enums import QualityProfile
from docprod.quality.profiles import policy_for
from docprod.quality.specs import EpisodeCostPlan


@dataclass
class GateResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def preflight_gates(
    plan: ScenePlan,
    *,
    profile: QualityProfile,
    cost: EpisodeCostPlan | None = None,
    uniqueness_required: bool = True,
) -> GateResult:
    errors: list[str] = []
    warnings: list[str] = []
    policy = policy_for(profile)
    collage = collage_violations(plan)
    if collage:
        errors.append(f"collage_policy: {', '.join(collage)}")
    if uniqueness_required:
        dupes = duplicate_fingerprints(plan)
        allowed = []
        for a, b in dupes:
            scene_b = next(s for s in plan.scenes if s.id == b)
            if scene_b.metadata.get("intentional_callback"):
                allowed.append((a, b))
                warnings.append(f"intentional_callback {a}=={b}")
            else:
                errors.append(f"duplicate_visual {a}=={b}")
    if profile is QualityProfile.LOCAL_ONLY and policy.allow_paid:
        errors.append("local_only policy must not allow paid")
    if cost is not None and cost.known_cost > cost.hard_budget + 1e-6:
        errors.append(
            f"hard_budget exceeded: known={cost.known_cost} max={cost.hard_budget}"
        )
    if not plan.scenes:
        errors.append("empty_scene_plan")
    return GateResult(passed=not errors, errors=errors, warnings=warnings)
