from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from docprod.config import Settings
from docprod.exceptions import MaxPaidRequestsExceededError
from docprod.providers.request_budget import ModelRequestBudget
from docprod.research.openai_web import OpenAIResponsesProvider


def _settings() -> Settings:
    return Settings(
        allow_paid_apis=True,
        openai_api_key=SecretStr("test-not-a-real-key"),
        _env_file=None,
    )


def test_ensure_remaining_does_not_consume_successful_slots() -> None:
    budget = ModelRequestBudget(max_requests=2)
    budget.ensure_remaining("veo", 1)
    assert budget.used_requests == 0
    assert budget.remaining_requests == 2
    budget.reserve("veo", 1)
    assert budget.used_requests == 1
    budget.ensure_remaining("veo", 1)
    with pytest.raises(MaxPaidRequestsExceededError):
        budget.ensure_remaining("veo", 2)
    assert budget.used_requests == 1
    assert budget.remaining_requests == 1
    budget = ModelRequestBudget(max_requests=1)
    budget.reserve("research")
    assert budget.used_requests == 1
    assert budget.remaining_requests == 0
    assert budget.stage_counts["research"] == 1
    with pytest.raises(MaxPaidRequestsExceededError, match="exhausted"):
        budget.reserve("research")


def test_retry_consumes_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("docprod.research.openai_web._is_transient", lambda _exc: True)
    calls = {"n": 0}

    class Responses:
        def create(self, **_kwargs: object) -> SimpleNamespace:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("transient")
            return SimpleNamespace(output_text="ok", usage=None, id="resp")

    budget = ModelRequestBudget(max_requests=2)
    provider = OpenAIResponsesProvider(
        settings=_settings(),
        client=SimpleNamespace(responses=Responses()),
    )
    provider.create(
        model="gpt-5.6-luna",
        instructions="x",
        input_text="y",
        confirm_paid=True,
        budget=budget,
        stage="planner",
        allow_retry=True,
    )
    assert calls["n"] == 2
    assert budget.used_requests == 2
    assert budget.stage_counts["planner"] == 2
    with pytest.raises(MaxPaidRequestsExceededError):
        provider.create(
            model="gpt-5.6-luna",
            instructions="x",
            input_text="y",
            confirm_paid=True,
            budget=budget,
            stage="planner",
            allow_retry=False,
        )
