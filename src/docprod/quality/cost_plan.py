from __future__ import annotations

from collections import Counter

from docprod.quality.catalog import get_model
from docprod.quality.enums import CostConfidence, QualityProfile
from docprod.quality.profiles import VIDEO_SECONDS, policy_for
from docprod.quality.router import estimate_model_cost
from docprod.quality.specs import CostLine, EpisodeCostPlan, RouteDecision

VIDEO_MODELS_PREMIUM = {
    "veo-3.1-standard",
    "runway-gen-4.5",
    "runway-act-two",
    "higgsfield-genjutsu",
}


def build_cost_plan(
    *,
    project_id: str,
    profile: QualityProfile,
    decisions: list[RouteDecision],
    upgrade_existing: bool = True,
    music_calls: int = 1,
    tts_minutes: float = 2.1,
) -> EpisodeCostPlan:
    policy = policy_for(profile)
    lines: list[CostLine] = []
    if not upgrade_existing:
        stills = [
            d
            for d in decisions
            if d.selected_model in {policy.timeline_image_model, policy.character_image_model}
            or d.selected_model.endswith("flare")
            or d.selected_model.endswith("sunburst")
            or d.selected_model == "comfyui-local"
        ]
        lines.append(
            CostLine(
                category="timeline_images",
                provider="openai",
                model_id=policy.timeline_image_model,
                count=float(len(stills)),
                unit="image",
                confidence=CostConfidence.ESTIMATED,
                notes="usage-based; not regenerated in upgrade mode",
            )
        )
    video = [
        d
        for d in decisions
        if d.selected_model not in {
            "local-camera",
            "local-title",
            "narration-over-image",
            policy.timeline_image_model,
            "gpt-image-2.5-flare",
            "gpt-image-2.5-sunburst",
            "comfyui-local",
        }
        and get_model(d.selected_model)
        and get_model(d.selected_model).modality.value == "video"
    ]
    cheap = [d for d in video if d.selected_model not in VIDEO_MODELS_PREMIUM]
    premium = [d for d in video if d.selected_model in VIDEO_MODELS_PREMIUM]
    perf = [
        d
        for d in video
        if d.production_class.value in {"performance_shot", "music_synced_performance"}
        or "act-two" in d.selected_model
        or "genjutsu" in d.selected_model
        or "avatar" in d.selected_model
    ]
    if cheap:
        cost, conf = estimate_model_cost(cheap[0].selected_model)
        qty = VIDEO_SECONDS * len(cheap)
        total = round(cost * len(cheap), 6) if cost is not None else None
        lines.append(
            CostLine(
                category="cheap_video",
                provider=cheap[0].selected_provider,
                model_id=cheap[0].selected_model,
                count=float(len(cheap)),
                quantity=qty,
                unit="second",
                unit_price=get_model(cheap[0].selected_model).pricing.value
                if get_model(cheap[0].selected_model)
                else None,
                estimated_cost=total,
                confidence=conf,
            )
        )
    if premium:
        cost, conf = estimate_model_cost(premium[0].selected_model)
        lines.append(
            CostLine(
                category="premium_video",
                provider=premium[0].selected_provider,
                model_id=premium[0].selected_model,
                count=float(len(premium)),
                quantity=VIDEO_SECONDS * len(premium),
                unit="second",
                estimated_cost=cost * len(premium) if cost is not None else None,
                confidence=conf,
            )
        )
    if perf:
        cost, conf = estimate_model_cost(perf[0].selected_model)
        lines.append(
            CostLine(
                category="performance",
                provider=perf[0].selected_provider,
                model_id=perf[0].selected_model,
                count=float(len(perf)),
                quantity=VIDEO_SECONDS * len(perf),
                unit="second",
                estimated_cost=cost * len(perf) if cost is not None else None,
                confidence=conf,
            )
        )
    tts_spec = get_model(policy.tts_model)
    if not upgrade_existing:
        tts_cost, tts_conf = estimate_model_cost(policy.tts_model, seconds=tts_minutes * 60)
        lines.append(
            CostLine(
                category="tts",
                provider=tts_spec.provider if tts_spec else "unknown",
                model_id=policy.tts_model,
                quantity=tts_minutes,
                unit="minute",
                estimated_cost=tts_cost,
                confidence=tts_conf
                if policy.tts_model != "gpt-4o-mini-tts"
                else CostConfidence.UNRESOLVED,
                notes="OpenAI TTS needs usage tokens; Eleven price UNRESOLVED",
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
        music = get_model(policy.music_model)
        mc, mconf = estimate_model_cost(policy.music_model)
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
        lines.append(
            CostLine(
                category="sfx",
                provider=sfx.provider if sfx else "elevenlabs",
                model_id=policy.sfx_model,
                count=float(hero_sfx),
                confidence=CostConfidence.UNRESOLVED,
                notes="Hero SFX only; unit price UNRESOLVED",
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
    remaining = None
    if upgrade_existing:
        remaining = round(known + estimated, 6)
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
        notes=[
            "upgrade_existing=true: do not regenerate locked images" if upgrade_existing else "",
            f"video_clip_seconds={VIDEO_SECONDS}",
        ],
    )


def count_classes(decisions: list[RouteDecision]) -> dict[str, int]:
    return dict(Counter(d.production_class.value for d in decisions))
