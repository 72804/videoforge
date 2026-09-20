from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from docprod.models.scene import ScenePlan
from docprod.quality.classify import story_function_for
from docprod.quality.enums import StoryFunction
from docprod.writing.models import NarrationScript

GENERIC_TITLES = {"giriş", "gelişme", "sonuç", "giris", "sonuc"}


class CriticFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    detail: str


class CriticReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[CriticFinding] = Field(default_factory=list)
    rewrite_recommended: bool = False
    max_rewrites: int = 1


def critique_script(script: NarrationScript, plan: ScenePlan | None = None) -> CriticReport:
    findings: list[CriticFinding] = []
    if script.beats:
        first = script.beats[0].narration.strip()
        if len(first) < 12:
            findings.append(
                CriticFinding(code="hook", severity="high", detail="Opening beat is too thin.")
            )
    titles = [chapter.title.casefold() for chapter in script.outline.chapters]
    for title in titles:
        if title in GENERIC_TITLES:
            findings.append(
                CriticFinding(
                    code="generic_title",
                    severity="high",
                    detail=f"Generic chapter title: {title}",
                )
            )
    functions = []
    if plan is not None:
        functions = [story_function_for(scene) for scene in plan.scenes]
        if StoryFunction.HOOK not in functions:
            findings.append(
                CriticFinding(code="hook", severity="medium", detail="No HOOK function classified.")
            )
        if StoryFunction.PAYOFF not in functions:
            findings.append(
                CriticFinding(code="payoff", severity="high", detail="No PAYOFF beat classified.")
            )
    rewrite = any(item.severity == "high" for item in findings)
    return CriticReport(findings=findings, rewrite_recommended=rewrite, max_rewrites=1)
