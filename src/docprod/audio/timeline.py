from __future__ import annotations

from docprod.audio.models import (
    SCENE_END_TAIL,
    AlignmentReport,
    RuntimeSceneTiming,
    RuntimeTimeline,
)
from docprod.models.scene import Scene, ScenePlan


def build_runtime_timeline(
    plan: ScenePlan,
    report: AlignmentReport,
    *,
    audio_duration: float,
    tail: float = SCENE_END_TAIL,
) -> RuntimeTimeline:
    by_scene: dict[str, list[tuple[float, float]]] = {scene.id: [] for scene in plan.scenes}
    for token in report.tokens:
        if token.start is None or token.end is None:
            continue
        by_scene.setdefault(token.scene_id, []).append((token.start, token.end))
    timings: list[RuntimeSceneTiming] = []
    starts: list[float] = []
    for index, scene in enumerate(plan.scenes):
        spans = by_scene.get(scene.id) or []
        if not spans:
            raise ValueError(f"No aligned words for {scene.id}; cannot build runtime timeline")
        first_word = min(item[0] for item in spans)
        starts.append(0.0 if index == 0 else first_word)
    for index, scene in enumerate(plan.scenes):
        start = starts[index]
        if index + 1 < len(starts):
            end = starts[index + 1]
        else:
            last_end = max(item[1] for item in by_scene[scene.id])
            end = min(audio_duration, max(last_end + tail, start + 0.04))
            if end < audio_duration:
                end = audio_duration
        if end <= start:
            end = start + 0.04
        duration = round(end - start, 4)
        timings.append(
            RuntimeSceneTiming(
                scene_id=scene.id,
                start=round(start, 4),
                end=round(end, 4),
                duration=duration,
                planned_duration=float(scene.duration),
                narration=scene.narration,
            )
        )
    total = timings[-1].end if timings else 0.0
    return RuntimeTimeline(
        project_id=plan.project_id,
        audio_duration=round(audio_duration, 4),
        total_duration=round(total, 4),
        scenes=timings,
    )


def apply_runtime_timeline(plan: ScenePlan, timeline: RuntimeTimeline) -> ScenePlan:
    by_id = {item.scene_id: item for item in timeline.scenes}
    scenes: list[Scene] = []
    for scene in plan.scenes:
        timing = by_id[scene.id]
        scenes.append(
            scene.model_copy(
                update={
                    "start": timing.start,
                    "end": timing.end,
                    "duration": round(timing.end - timing.start, 4),
                }
            )
        )
    return plan.model_copy(
        update={
            "scenes": scenes,
            "total_duration": scenes[-1].end if scenes else 0.0,
        }
    )
