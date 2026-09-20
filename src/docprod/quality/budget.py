from __future__ import annotations

from dataclasses import dataclass

from docprod.models.scene import Scene, ScenePlan
from docprod.quality.availability import availability
from docprod.quality.catalog import get_model
from docprod.quality.classify import classify_scene, score_scene, sfx_class_for
from docprod.quality.driving import needs_driving_performance
from docprod.quality.duration import billable_seconds, cost_per_used_second, wasted_seconds
from docprod.quality.enums import (
    AdapterStatus,
    CostConfidence,
    ProviderStatus,
    QualityProfile,
    SceneProductionClass,
)
from docprod.quality.locked import locked_video_models
from docprod.quality.profiles import policy_for
from docprod.quality.router import (
    estimate_model_cost,
    fallback_chain,
    preferred_video_model,
    still_route,
    technique_for_model,
    upgrade_kind_for,
    wants_video,
)
from docprod.quality.scoring import utility
from docprod.quality.specs import RouteDecision, SceneValueScore


@dataclass
class _Cand:
    scene: Scene
    klass: SceneProductionClass
    scores: SceneValueScore
    util: float
    cost: float | None
    forced: bool
    locked: str
    music_sync: bool
    must_video: bool
    must_perf: bool


def pick_from_chain(
    chain: list[str],
    status: dict[str, ProviderStatus],
    profile: QualityProfile,
    *,
    used_seconds: float = 0.0,
    allow_manual_inputs: bool = False,
    has_driving_video: bool = False,
) -> str:
    policy = policy_for(profile)
    for model_id in chain:
        if model_id in {"local-camera", "local-title", "narration-over-image"}:
            return model_id
        spec = get_model(model_id)
        if spec is None:
            continue
        if spec.adapter_status is AdapterStatus.DOCUMENTED_UNIMPLEMENTED:
            continue
        if spec.manual_input_required and not has_driving_video and not allow_manual_inputs:
            continue
        if not policy.allow_paid and not spec.local:
            continue
        if spec.local:
            return model_id
        if not spec.implemented:
            continue
        seconds = used_seconds or spec.min_duration_seconds or 0
        cost, conf = estimate_model_cost(model_id, seconds=seconds)
        if profile is QualityProfile.BALANCED and conf is CostConfidence.UNRESOLVED:
            continue
        st = status.get(spec.provider, ProviderStatus.UNCONFIGURED)
        if spec.implemented or st is not ProviderStatus.UNCONFIGURED:
            return model_id
    return "local-camera"


def allocate_video(
    plan: ScenePlan,
    profile: QualityProfile,
    *,
    status: dict[str, ProviderStatus] | None = None,
    allow_manual_inputs: bool = False,
    driving_videos: dict[str, str] | None = None,
    locked_models: dict[str, str] | None = None,
) -> list[RouteDecision]:
    policy = policy_for(profile)
    avail = status or availability().providers
    drives = driving_videos or {}
    locked_map = (
        locked_models if locked_models is not None else locked_video_models(plan, profile)
    )
    cands: list[_Cand] = []
    static: list[RouteDecision] = []
    static_ids: set[str] = set()

    for scene in plan.scenes:
        klass = classify_scene(scene)
        scores = score_scene(scene, klass)
        meta = scene.metadata or {}
        must_static = bool(meta.get("must_static"))
        must_video = bool(meta.get("must_video"))
        must_perf = bool(meta.get("must_performance"))
        music_sync = bool(meta.get("music_sync_required"))
        beat = str(meta.get("beat_id") or "")
        locked = str(meta.get("locked_provider") or locked_map.get(beat) or "")
        drive = drives.get(scene.id) or drives.get(beat) or ""
        if locked:
            spec = get_model(locked)
            if (
                spec is not None
                and spec.manual_input_required
                and not drive
                and not allow_manual_inputs
            ):
                locked = ""
        if (
            klass is SceneProductionClass.TITLE_CARD
            or must_static
            or klass is SceneProductionClass.ARCHIVAL_SHOT
        ):
            decision = still_route(scene.id, klass, profile)
            decision.scores = scores
            decision.must_static = True
            decision.sfx_class = sfx_class_for(scene)
            static.append(decision)
            static_ids.add(scene.id)
            continue
        video = (
            must_video
            or must_perf
            or music_sync
            or bool(locked)
            or wants_video(klass, scores, profile, music_sync=music_sync)
        )
        if not video or (profile is QualityProfile.ECONOMY and not must_video):
            decision = still_route(scene.id, klass, profile)
            decision.scores = scores
            decision.sfx_class = sfx_class_for(scene)
            static.append(decision)
            static_ids.add(scene.id)
            continue
        model = locked or preferred_video_model(klass, profile)
        cost, _conf = estimate_model_cost(model, seconds=scene.duration)
        tech = technique_for_model(model)
        cands.append(
            _Cand(
                scene=scene,
                klass=klass,
                scores=scores,
                util=utility(
                    scores, production_class=klass, technique=tech, estimated_cost=cost
                ),
                cost=cost,
                forced=must_video or must_perf or bool(locked),
                locked=locked,
                music_sync=music_sync,
                must_video=must_video,
                must_perf=must_perf,
            )
        )

    target = policy.target_paid_usd
    hard = policy.max_paid_usd
    chosen: set[str] = {item.scene.id for item in cands if item.forced}
    spent = 0.0
    for item in cands:
        if item.scene.id in chosen and item.cost:
            spent += item.cost
    for item in sorted(cands, key=lambda row: row.util, reverse=True):
        if item.scene.id in chosen:
            continue
        add = item.cost if item.cost is not None else 0.0
        if item.cost is None and profile is QualityProfile.BALANCED:
            continue
        if spent + add > hard + 1e-9:
            continue
        if spent + add > target + 1e-9 and profile is QualityProfile.BALANCED:
            continue
        chosen.add(item.scene.id)
        spent += add

    by_static = {item.scene_id: item for item in static}
    by_cand = {item.scene.id: item for item in cands}
    out: list[RouteDecision] = []
    for scene in plan.scenes:
        if scene.id in static_ids:
            out.append(by_static[scene.id])
            continue
        item = by_cand[scene.id]
        if scene.id not in chosen:
            decision = still_route(scene.id, item.klass, profile)
            decision.scores = item.scores
            decision.sfx_class = sfx_class_for(scene)
            decision.reason = (
                "Ranked below budget cutoff; keep unique still + local camera motion."
            )
            out.append(decision)
            continue
        chain = fallback_chain(item.klass, profile)
        beat = str((item.scene.metadata or {}).get("beat_id") or "")
        drive = drives.get(item.scene.id) or drives.get(beat) or ""
        model = item.locked
        if model:
            spec = get_model(model)
            if spec is None or (not spec.implemented and not spec.local):
                model = ""
        if not model:
            model = pick_from_chain(
                chain,
                avail,
                profile,
                used_seconds=item.scene.duration,
                allow_manual_inputs=allow_manual_inputs,
                has_driving_video=bool(drive),
            )
        spec = get_model(model)
        provider = spec.provider if spec else "local"
        used = item.scene.duration
        billed = billable_seconds(model, used) if get_model(model) else 0.0
        cost, conf = estimate_model_cost(model, seconds=used)
        wasted = wasted_seconds(billed, used)
        kind = upgrade_kind_for(item.klass, model)
        driving = needs_driving_performance(
            item.scene,
            model_id=model,
            driving_video=drive,
            allow_manual_inputs=allow_manual_inputs,
        )
        manual = bool(spec and spec.manual_input_required and driving)
        out.append(
            RouteDecision(
                scene_id=scene.id,
                production_class=item.klass,
                quality_profile=profile,
                selected_provider=provider,
                selected_model=model,
                fallback_chain=chain,
                estimated_cost=cost,
                cost_confidence=conf,
                reason=(
                    f"{kind.value}: story={item.scores.story_importance:.2f} "
                    f"motion={item.scores.motion_need:.2f} util={item.util:.2f} "
                    f"used={used:.1f}s billable={billed:.0f}s waste={wasted:.1f}s"
                    + (
                        " needs driving performance"
                        if driving
                        else " automated; no human performance"
                    )
                ),
                quality_tier=policy.default_tier,
                scores=item.scores,
                must_video=item.must_video,
                must_performance=item.must_perf,
                locked_provider=item.locked,
                sfx_class=sfx_class_for(scene),
                music_sync_required=item.music_sync,
                used_seconds=used,
                billable_seconds=billed,
                wasted_seconds=wasted,
                effective_cost_per_used_second=cost_per_used_second(cost, used),
                upgrade_kind=kind,
                needs_driving_performance=driving,
                manual_input_required=manual,
            )
        )
    return out
