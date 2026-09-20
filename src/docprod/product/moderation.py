from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModerationDecision:
    allowed: bool
    reason: str = ""


class ModerationHooks:
    def check_prompt(self, text: str) -> ModerationDecision:
        return ModerationDecision(True)

    def check_image(self, data: bytes) -> ModerationDecision:
        return ModerationDecision(True)

    def check_generation_eligibility(self, prompt: str) -> ModerationDecision:
        prompt_ok = self.check_prompt(prompt)
        if not prompt_ok.allowed:
            return prompt_ok
        return ModerationDecision(True)
