from __future__ import annotations

from collections import Counter

from docprod.quality.catalog import get_model
from docprod.quality.enums import CostConfidence, QualityProfile
from docprod.quality.profiles import policy_for
from docprod.quality.router import estimate_model_cost
from docprod.quality.specs import CostLine, EpisodeCostPlan, RouteDecision

VIDEO_MODELS_PREMIUM = {
    "runway-gen-4.5",
    "runway-act-two",
    "higgsfield-genjutsu",
    "veo-3.1-standard",
}


def _video_decisions(decisions: list[RouteDecision], policy) -> list[RouteDecision]:
    skip = {
        "local-camera",
        "local-title",
        "narration-over-image",
        policy.timeline_image_model,
        "gpt-image-2.5-flare",
        "gpt-image-2.5-sunburst",
        "comfyui-local",
    }
    out: list[RouteDecision] = []
    for item in decisions:
        if item.selected_model in skip:
            continue
        spec = get_model(item.selected_model)
        if spec is None or spec.modality.value != "video":
            continue
        out.append(item)
    return out


def _line_from_group(category: str, group: list[RouteDecision]) -> CostLine:
    first = group[0]
    spec = get_model(first.selected_model)
    quantity = sum(item.billable_seconds or 0.0 for item in group)
    costs = [item.estimated_cost for item in group]
    if any(c is None for c in costs):
        total = None
        conf = CostConfidence.UNRESOLVED
    else:
        total = round(sum(float(c) for c in costs), 6)
        conf = first.cost_confidence
    return CostLine(
        category=category,
        provider=first.selected_provider,
        model_id=first.selected_model,
        count=float(len(group)),
        quantity=quantity,
        unit="second",
        unit_price=spec.pricing.value if spec else None,
        estimated_cost=total,
        confidence=conf,
        notes=f"billable_seconds={quantity:.1f}",
    )


def build_cost_plan(
    *,
    project_id: str,
    profile: QualityProfile,
    decisions: list[RouteDecision],
    upgrade_existing: bool = True,
    music_calls: int = 1,
    tts_minutes: float = 2.1,
    tts_characters: int = 0,
    upgrade_narrator: bool = False,
    upgrade_music: bool = False,
    hero_sfx_seconds: float = 1.0,
) -> EpisodeCostPlan:
    policy = policy_for(profile)
    lines: list[CostLine] = []
    video = _video_decisions(decisions, policy)
    cheap = [d for d in video if d.selected_model not in VIDEO_MODELS_PREMIUM]
    premium = [d for d in video if d.selected_model in VIDEO_MODELS_PREMIUM]
    perf = [d for d in video if d.upgrade_kind.value == "performance_transfer"]
    if cheap:
        lines.append(_line_from_group("cheap_video", cheap))
    if premium:
        lines.append(_line_from_group("premium_video", premium))
    if perf:
        lines.append(_line_from_group("performance", perf))

    if upgrade_narrator or not upgrade_existing:
        tts_spec = get_model(policy.tts_model)
        tts_cost, tts_conf = estimate_model_cost(
            policy.tts_model, seconds=tts_minutes * 60, characters=float(tts_characters)
        )
        lines.append(
            CostLine(
                category="tts",
                provider=tts_spec.provider if tts_spec else "unknown",
                model_id=policy.tts_model,
                quantity=float(tts_characters or tts_minutes),
                unit="character" if tts_characters else "minute",
                estimated_cost=tts_cost,
                confidence=tts_conf,
                notes="narrator upgrade invalidates alignment + dialogue sync",
            )
        )
        align = get_model(policy.alignment_model)
        ac, aconf = estimate_model_cost(policy.alignment_model, seconds=tts_minutes * 60)
        lines.append(
            CostLine(
                category="alignment",
                provider=align.provider if align else "unknown",
                model_id=policy.alignment_model,
                quantity=tts_minutes,
                unit="minute",
                unit_price=align.pricing.value if align else None,
                estimated_cost=ac,
                confidence=aconf,
            )
        )
    if upgrade_music:
        music = get_model(policy.music_model)
        mc, mconf = estimate_model_cost(policy.music_model, seconds=tts_minutes * 60)
        lines.append(
            CostLine(
                category="music",
                provider=music.provider if music else "unknown",
                model_id=policy.music_model,
                count=float(music_calls),
                unit="song",
                estimated_cost=round(mc * music_calls, 6) if mc is not None else None,
                confidence=mconf,
            )
        )

    hero_sfx = sum(1 for d in decisions if d.sfx_class and d.sfx_class.value == "hero_sfx")
    if policy.premium_sfx and hero_sfx:
        sfx = get_model(policy.sfx_model)
        sc, sconf = estimate_model_cost(policy.sfx_model, seconds=hero_sfx_seconds * hero_sfx)
        lines.append(
            CostLine(
                category="sfx",
                provider=sfx.provider if sfx else "elevenlabs",
                model_id=policy.sfx_model,
                count=float(hero_sfx),
                quantity=hero_sfx_seconds * hero_sfx,
                unit="second",
                estimated_cost=sc,
                confidence=sconf,
                notes="HERO_SFX only; generic SFX stay local",
            )
        )
    else:
        lines.append(
            CostLine(
                category="sfx",
                provider="local",
                model_id="procedural-sfx",
                count=float(hero_sfx),
                estimated_cost=0.0,
                confidence=CostConfidence.KNOWN,
                notes="reuse existing local/procedural SFX",
            )
        )

    known = 0.0
    estimated = 0.0
    unresolved: list[str] = []
    for line in lines:
        if line.confidence is CostConfidence.KNOWN and line.estimated_cost is not None:
            known += line.estimated_cost
        elif line.confidence is CostConfidence.ESTIMATED and line.estimated_cost is not None:
            estimated += line.estimated_cost
        elif line.estimated_cost is None or line.confidence is CostConfidence.UNRESOLVED:
            unresolved.append(line.category)
    lower = round(known + estimated, 6)
    fully = not unresolved
    upper = lower if fully else None
    remaining = lower if upgrade_existing else None
    notes = [
        "upgrade_existing=true: reuse locked stills/TTS/Lyria/SFX unless flags set"
        if upgrade_existing
        else "full regeneration costing",
        "unresolved items mean this profile is NOT cheaper than a fully priced one",
    ]
    return EpisodeCostPlan(
        project_id=project_id,
        profile=profile,
        lines=lines,
        canonical_target_value=policy.target_paid_usd,
        cached_value=0.0,
        remaining_spend=remaining,
        hard_budget=policy.max_paid_usd,
        budget_remaining=round(policy.max_paid_usd - known, 6),
        known_cost=round(known, 6),
        estimated_cost=round(estimated, 6),
        unresolved_categories=sorted(set(unresolved)),
        unresolved_cost_items=sorted(set(unresolved)),
        estimated_lower_bound_usd=lower,
        estimated_upper_bound_usd=upper,
        fully_priced=fully,
        notes=notes,
    )


def count_classes(decisions: list[RouteDecision]) -> dict[str, int]:
    return dict(Counter(d.production_class.value for d in decisions))
