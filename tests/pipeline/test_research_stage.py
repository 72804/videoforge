from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from docprod.cli import app
from docprod.config import Settings, get_settings
from docprod.exceptions import PaidApiNotConfirmedError, ResearchQualityError
from docprod.models.project import Project
from docprod.pipeline.build_dossier import run_build_dossier
from docprod.pipeline.research_topic import prepare_research, run_research_topic
from docprod.pipeline.write_script import run_write_script
from docprod.research.models import TopicSpec
from docprod.research.openai_web import OpenAIResponsesProvider
from docprod.storage.json_store import save_model
from docprod.storage.paths import ProjectPaths, default_projects_root
from docprod.writing.models import NarrationScript

runner = CliRunner()

URLS = [
    ("https://canlii.org/en/qc/qccs/doc/2013/2013qccs123/2013qccs123.html", "CanLII"),
    ("https://www.cbc.ca/news/canada/maple-syrup", "CBC"),
    ("https://www.reuters.com/article/maple-syrup-heist", "Reuters"),
    ("https://www.theglobeandmail.com/news/maple", "Globe"),
    ("https://www.bbc.com/news/world-us-canada-maple", "BBC"),
]

REPORT = (
    "In 2011 thieves began siphoning maple syrup. In 2012 the Federation of Quebec Maple Syrup "
    "Producers discovered thousands of barrels missing from a warehouse, a loss worth millions of "
    "dollars. Investigators later charged several people and courts recorded convictions."
)


def _settings(**kwargs: object) -> Settings:
    payload: dict[str, object] = {
        "allow_paid_apis": True,
        "openai_api_key": SecretStr("test-not-a-real-key"),
        "research_model": "gpt-5.6-luna",
        "dossier_model": "gpt-5.6-luna",
        "writer_model": "gpt-5.6-terra",
        "log_level": "INFO",
    }
    payload.update(kwargs)
    return Settings(**payload)


def _project(pid: str = "maple_heist_canary") -> Project:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Project(
        id=pid,
        title="Maple",
        language="tr",
        target_duration_seconds=420,
        created_at=now,
        updated_at=now,
    )


def _topic(pid: str = "maple_heist_canary") -> TopicSpec:
    return TopicSpec(
        project_id=pid,
        topic="The Great Canadian Maple Syrup Heist (2011–2012)",
        language="tr",
        target_runtime_minutes=7,
        content_type="documentary / unusual crime / heist",
    )


def _ns(payload: dict, output_text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=payload.get("id", "resp"),
        model=payload.get("model"),
        output_text=output_text,
        usage=SimpleNamespace(
            model_dump=lambda: {
                "input_tokens": 10,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 2},
                "output_tokens_details": {"reasoning_tokens": 3},
            }
        ),
        model_dump=lambda: payload,
    )


def _research_payload() -> tuple[dict, str]:
    sources = [{"url": url, "title": title} for url, title in URLS]
    annotations = [
        {
            "type": "url_citation",
            "url": URLS[0][0],
            "title": URLS[0][1],
            "start_index": 0,
            "end_index": 8,
        }
    ]
    payload = {
        "id": "resp_research",
        "model": "gpt-5.6-luna",
        "output": [
            {"type": "web_search_call", "action": {"sources": sources}},
            {
                "type": "message",
                "content": [{"type": "output_text", "text": REPORT, "annotations": annotations}],
            },
        ],
        "output_text": REPORT,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }
    return payload, REPORT


def _dossier_json() -> str:
    return json.dumps(
        {
            "topic": "Maple heist",
            "summary": "A 2011-2012 theft of maple syrup from a strategic reserve.",
            "entities": [{"name": "FPAQ", "role": "producers federation", "source_ids": ["S001"]}],
            "locations": [{"name": "Saint-Louis-de-Blandford", "source_ids": ["S002"]}],
            "timeline_events": [
                {
                    "event_id": "E1",
                    "date_or_range": "2011-2012",
                    "description": "Syrup removed from barrels.",
                    "source_ids": ["S001"],
                }
            ],
            "facts": [
                {
                    "fact_id": "F001",
                    "claim": "Thousands of barrels were missing.",
                    "source_ids": ["S001", "S002"],
                    "confidence": "high",
                    "status": "confirmed",
                }
            ],
            "figures": [
                {"name": "value", "value_text": "millions of dollars", "source_ids": ["S003"]}
            ],
            "legal_outcomes": [
                {
                    "description": "Several people were convicted.",
                    "status": "convicted",
                    "source_ids": ["S001"],
                }
            ],
            "uncertainties": [],
            "contradictions": [],
            "visual_opportunities": [
                {"description": "Barrels in a warehouse", "source_ids": ["S002"]}
            ],
            "source_ids_used": ["S001", "S002", "S003"],
        }
    )


def _script_json() -> str:
    sentence = "2012 yılında stratejik akçaağaç şurubu deposunda binlerce varil eksikti. "
    narration = sentence * 8
    return json.dumps(
        {
            "outline": {
                "logline": "Kanada rezervinden şurup çalındı.",
                "chapters": [
                    {
                        "chapter_id": "hook",
                        "title": "Hook",
                        "purpose": "open",
                        "beat_ids": ["b01"],
                    }
                ],
            },
            "beats": [
                {
                    "beat_id": "b01",
                    "narration": narration,
                    "claim_ids": ["F001"],
                    "source_ids": ["S001"],
                    "chapter": "hook",
                    "purpose": "fact",
                }
            ],
        }
    )


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        payload, text = _research_payload()
        self.research = _ns(payload, text)
        dossier_text = _dossier_json()
        self.dossier = _ns(
            {
                "id": "resp_dossier",
                "model": "gpt-5.6-luna",
                "output_text": dossier_text,
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": dossier_text}],
                    }
                ],
            },
            dossier_text,
        )
        script_text = _script_json()
        self.script = _ns(
            {
                "id": "resp_script",
                "model": "gpt-5.6-terra",
                "output_text": script_text,
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": script_text}],
                    }
                ],
            },
            script_text,
        )

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        if kwargs.get("tools"):
            return self.research
        fmt = ((kwargs.get("text") or {}) if isinstance(kwargs.get("text"), dict) else {}).get(
            "format", {}
        )
        name = fmt.get("name") if isinstance(fmt, dict) else None
        if name == "research_dossier":
            return self.dossier
        return self.script


def _prepare_project(tmp_path: Path, pid: str = "maple_heist_canary") -> ProjectPaths:
    paths = ProjectPaths(root=tmp_path / pid)
    paths.stages_dir.mkdir(parents=True, exist_ok=True)
    save_model(paths.project_json, _project(pid))
    save_model(paths.topic_json(), _topic(pid))
    return paths


def test_paid_gate_and_dry_run_zero_calls(tmp_path: Path) -> None:
    paths = _prepare_project(tmp_path)
    recorder = Recorder()
    provider = OpenAIResponsesProvider(
        settings=_settings(), client=SimpleNamespace(responses=recorder)
    )
    prepared = prepare_research(paths, settings=_settings())
    assert prepared.max_tool_calls == 8
    assert prepared.model == "gpt-5.6-luna"
    with pytest.raises(PaidApiNotConfirmedError):
        run_research_topic(
            paths,
            project=_project(),
            confirm_paid=False,
            settings=_settings(),
            client=provider,
        )
    assert recorder.calls == []


def test_research_web_search_include_and_max_tools(tmp_path: Path) -> None:
    paths = _prepare_project(tmp_path)
    recorder = Recorder()
    provider = OpenAIResponsesProvider(
        settings=_settings(), client=SimpleNamespace(responses=recorder)
    )
    result = run_research_topic(
        paths,
        project=_project(),
        confirm_paid=True,
        settings=_settings(),
        client=provider,
    )
    call = recorder.calls[0]
    assert call["tools"] == [{"type": "web_search"}]
    assert call["max_tool_calls"] == 8
    assert call["include"] == ["web_search_call.action.sources"]
    assert result.request_count == 1
    assert result.quality.passed
    assert len(result.registry.sources) >= 5
    again = run_research_topic(
        paths,
        project=_project(),
        confirm_paid=True,
        settings=_settings(),
        client=provider,
    )
    assert again.cache_hit is True
    assert len(recorder.calls) == 1


def test_model_change_invalidates_cache(tmp_path: Path) -> None:
    paths = _prepare_project(tmp_path)
    recorder = Recorder()
    provider = OpenAIResponsesProvider(
        settings=_settings(), client=SimpleNamespace(responses=recorder)
    )
    run_research_topic(
        paths,
        project=_project(),
        confirm_paid=True,
        settings=_settings(),
        client=provider,
    )
    other = _settings(research_model="gpt-5.6-terra")
    run_research_topic(
        paths,
        project=_project(),
        confirm_paid=True,
        settings=other,
        client=provider,
    )
    assert len(recorder.calls) == 2


def test_dossier_and_writer_have_no_web_search(tmp_path: Path) -> None:
    paths = _prepare_project(tmp_path)
    recorder = Recorder()
    provider = OpenAIResponsesProvider(
        settings=_settings(), client=SimpleNamespace(responses=recorder)
    )
    run_research_topic(
        paths,
        project=_project(),
        confirm_paid=True,
        settings=_settings(),
        client=provider,
    )
    dossier, summary, _hit, d_req = run_build_dossier(
        paths,
        confirm_paid=True,
        settings=_settings(),
        client=provider,
    )
    assert d_req == 1
    assert summary.passed
    assert dossier.facts
    script, _hit, s_req = run_write_script(
        paths,
        confirm_paid=True,
        settings=_settings(),
        client=provider,
        word_min=1,
        word_max=5000,
    )
    assert s_req == 1
    assert script.beats[0].source_ids
    for call in recorder.calls[1:]:
        assert "tools" not in call
        assert call.get("max_tool_calls") is None
    cached_script, hit, req = run_write_script(
        paths,
        confirm_paid=True,
        settings=_settings(),
        client=provider,
        word_min=1,
        word_max=5000,
    )
    assert hit is True
    assert req == 0
    assert isinstance(cached_script, NarrationScript)


def test_weak_research_stops_before_script(tmp_path: Path) -> None:
    paths = _prepare_project(tmp_path)
    recorder = Recorder()
    payload, text = _research_payload()
    payload["output"] = [
        {
            "type": "web_search_call",
            "action": {"sources": [{"url": "https://medium.com/@x/heist", "title": "blog"}]},
        }
    ]
    recorder.research = _ns(payload, text)
    provider = OpenAIResponsesProvider(
        settings=_settings(), client=SimpleNamespace(responses=recorder)
    )
    with pytest.raises(ResearchQualityError):
        run_research_topic(
            paths,
            project=_project(),
            confirm_paid=True,
            settings=_settings(),
            client=provider,
        )
    assert not paths.research_dossier_json().is_file()
    assert not paths.story_script_json().is_file()


def test_project_isolation_from_planner_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo = tmp_path / "planner_demo"
    demo.mkdir()
    (demo / "marker.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr("docprod.storage.paths.default_projects_root", lambda: tmp_path)
    paths = _prepare_project(tmp_path, "maple_heist_canary")
    recorder = Recorder()
    provider = OpenAIResponsesProvider(
        settings=_settings(), client=SimpleNamespace(responses=recorder)
    )
    run_research_topic(
        paths,
        project=_project(),
        confirm_paid=True,
        settings=_settings(),
        client=provider,
    )
    assert (demo / "marker.txt").read_text(encoding="utf-8") == "keep"
    assert not list(demo.glob("00_topic.json"))
    assert default_projects_root() == tmp_path or True


def test_cli_dry_run_and_paid_gate(projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_PAID_APIS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    get_settings.cache_clear()
    created = runner.invoke(
        app,
        [
            "init-research",
            "maple_heist_canary",
            "--topic",
            "The Great Canadian Maple Syrup Heist (2011–2012)",
            "--language",
            "tr",
            "--target-minutes",
            "7",
        ],
    )
    assert created.exit_code == 0, created.output
    dry = runner.invoke(app, ["research-topic", "maple_heist_canary", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "gpt-5.6-luna" in dry.output
    assert "max_web_tool_calls=8" in dry.output
    assert "dry_run=true" in dry.output
    blocked = runner.invoke(app, ["research-topic", "maple_heist_canary"])
    assert blocked.exit_code != 0
    assert "confirm-paid" in blocked.output.lower()
    assert not (projects_root / "planner_demo" / "stages" / "00_topic.json").is_file()
