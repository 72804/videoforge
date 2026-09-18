from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from pydantic import SecretStr
from typer.testing import CliRunner

from docprod.cli import app
from docprod.config import Settings
from docprod.models.project import Project
from docprod.pipeline.plan_story_scenes import run_plan_story_scenes
from docprod.planning.semantic_models import SemanticIntentSet
from docprod.research.models import Fact, ResearchDossier, SourceRecord, SourceRegistry, TopicSpec
from docprod.research.openai_web import OpenAIResponsesProvider
from docprod.storage.json_store import save_model
from docprod.storage.paths import ProjectPaths
from docprod.writing.models import NarrationBeat, NarrationScript, StoryOutline

runner = CliRunner()

WORDS = " ".join(["kelime"] * 36)
INTENT_JSON = """
{"intents":[
  {"intent_id":"I001","chapter":"HOOK","narration_start_word":0,"narration_end_word":12,
   "visual_subject":"warehouse","preferred_source_type":"stock_video","movement_need":"low",
   "historical_specificity":"generic","claim_ids":["F001"],"source_ids":["S001"],
   "reenactment_freedom":"generic_only","stock_query_seed":"maple warehouse",
   "image_prompt_seed":"warehouse exterior","archive_search_seed":"quebec heist 2012",
   "reasoning_summary":"Establish location."},
  {"intent_id":"I002","chapter":"SCALE","narration_start_word":12,"narration_end_word":24,
   "visual_subject":"quantity graphic","preferred_source_type":"infographic","movement_need":"none",
   "historical_specificity":"generic","claim_ids":["F001"],"source_ids":["S001"],
   "reenactment_freedom":"avoid","graphic_brief":"Approximate 18-18.7 million CAD range",
   "reasoning_summary":"Show disputed range."},
  {"intent_id":"I003","chapter":"COURT","narration_start_word":24,"narration_end_word":36,
   "visual_subject":"court summary","preferred_source_type":"document","movement_need":"none",
   "historical_specificity":"approximate_period","claim_ids":["F001"],"source_ids":["S001"],
   "reenactment_freedom":"avoid","graphic_brief":"Stylized sentencing summary",
   "reasoning_summary":"Court graphic, not a fake record."}
]}
"""


def _settings() -> Settings:
    return Settings(
        allow_paid_apis=True,
        openai_api_key=SecretStr("test-not-a-real-key"),
        scene_planner_model="gpt-5.6-luna",
        _env_file=None,
    )


def _ns(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp-plan",
        model="gpt-5.6-luna",
        output_text=text,
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=20,
            model_dump=lambda: {"input_tokens": 10, "output_tokens": 20},
        ),
        model_dump=lambda: {"id": "resp-plan", "output_text": text, "model": "gpt-5.6-luna"},
    )


def _setup(tmp_path, monkeypatch) -> ProjectPaths:
    monkeypatch.setattr("docprod.storage.paths.default_projects_root", lambda: tmp_path)
    monkeypatch.setattr("docprod.cli.pathmod.default_projects_root", lambda: tmp_path)
    paths = ProjectPaths(tmp_path / "maple_heist_canary")
    paths.root.mkdir(parents=True)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    save_model(
        paths.project_json,
        Project(
            id="maple_heist_canary",
            title="Maple",
            language="tr",
            target_duration_seconds=420,
            created_at=now,
            updated_at=now,
        ),
    )
    save_model(
        paths.topic_json(),
        TopicSpec(
            project_id="maple_heist_canary",
            topic="The Great Canadian Maple Syrup Heist (2011–2012)",
            language="tr",
            target_runtime_minutes=7,
            content_type="documentary",
        ),
    )
    save_model(
        paths.sources_json(),
        SourceRegistry(
            project_id="maple_heist_canary",
            sources=[
                SourceRecord(
                    source_id="S001",
                    url="https://canlii.org/a",
                    title="CanLII",
                    domain="canlii.org",
                    accessed_at=now,
                    quality_tier="A",
                    quality_reason="court",
                ),
                SourceRecord(
                    source_id="S099",
                    url="https://www.reddit.com/r/x",
                    title="reddit",
                    domain="reddit.com",
                    accessed_at=now,
                    quality_tier="low",
                    quality_reason="social",
                ),
            ],
        ),
    )
    save_model(
        paths.research_dossier_json(),
        ResearchDossier(
            project_id="maple_heist_canary",
            topic="heist",
            summary="summary",
            facts=[
                Fact(
                    fact_id="F001",
                    claim="Barrels missing",
                    source_ids=["S001"],
                    confidence="high",
                    status="confirmed",
                )
            ],
            source_ids_used=["S001"],
        ),
    )
    save_model(
        paths.story_script_json(),
        NarrationScript(
            project_id="maple_heist_canary",
            language="tr",
            outline=StoryOutline(),
            beats=[
                NarrationBeat(
                    beat_id="B001",
                    narration=WORDS,
                    claim_ids=["F001"],
                    source_ids=["S001"],
                )
            ],
            full_narration=WORDS,
            word_count=36,
        ),
    )
    return paths


def test_dry_run_zero_network(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("network")

    monkeypatch.setattr("docprod.research.openai_web.OpenAIResponsesProvider.create", boom)
    result = runner.invoke(app, ["plan-story-scenes", "maple_heist_canary", "--dry-run"])
    assert result.exit_code == 0
    assert "max_model_requests=1" in result.stdout
    assert "web_search=false" in result.stdout
    assert called["n"] == 0


def test_paid_gate_and_no_tools(tmp_path, monkeypatch) -> None:
    paths = _setup(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    class Client:
        def __init__(self) -> None:
            self.responses = self

        def create(self, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return _ns(INTENT_JSON)

    provider = OpenAIResponsesProvider(settings=_settings(), client=Client())
    result = run_plan_story_scenes(
        paths,
        confirm_paid=True,
        settings=_settings(),
        client=provider,
    )
    assert result.request_count == 1
    assert "tools" not in captured
    assert captured["model"] == "gpt-5.6-luna"
    registry = SourceRegistry.model_validate_json(paths.sources_json().read_text())
    assert "S001" in registry.evidence_source_ids
    assert "S099" not in registry.evidence_source_ids
    assert paths.scene_plan_json.is_file()
    intents = SemanticIntentSet.model_validate_json(paths.semantic_intents_json().read_text())
    assert intents.intents[0].stock_query_seed
    second = run_plan_story_scenes(
        paths,
        confirm_paid=True,
        settings=_settings(),
        client=provider,
    )
    assert second.cache_hit is True
    assert second.request_count == 0


def test_parse_failure_stops_without_retry(tmp_path, monkeypatch) -> None:
    paths = _setup(tmp_path, monkeypatch)
    calls = {"n": 0}

    class Client:
        def __init__(self) -> None:
            self.responses = self

        def create(self, **_kwargs: object) -> SimpleNamespace:
            calls["n"] += 1
            return _ns("not-json")

    provider = OpenAIResponsesProvider(settings=_settings(), client=Client())
    try:
        run_plan_story_scenes(paths, confirm_paid=True, settings=_settings(), client=provider)
        raise AssertionError("expected failure")
    except Exception as exc:
        assert "STOP" in str(exc) or "not JSON" in str(exc)
    assert calls["n"] == 1
    assert paths.semantic_planner_raw_json().is_file()
    assert not paths.semantic_intents_json().is_file()


def test_planner_demo_untouched_by_story_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("docprod.storage.paths.default_projects_root", lambda: tmp_path)
    demo = tmp_path / "planner_demo" / "stages"
    demo.mkdir(parents=True)
    marker = demo / "05_scenes.json"
    marker.write_text('{"keep": true}', encoding="utf-8")
    _setup(tmp_path, monkeypatch)
    assert marker.read_text(encoding="utf-8") == '{"keep": true}'
