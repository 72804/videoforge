from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from tests.render.helpers import mini_plan
from typer.testing import CliRunner

from docprod.audio.script import tokenize_display
from docprod.cli import app
from docprod.config import Settings
from docprod.exceptions import AlignmentQualityError, PaidApiNotConfirmedError
from docprod.graphics.renderer import execute_generate_graphic
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.pipeline.generate_narration import generate_narration, prepare_narration
from docprod.providers.image_config import GeneratedImageManifest
from docprod.providers.openai_tts import OpenAITTSProvider
from docprod.providers.openai_whisper import OpenAIWhisperAligner
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.render.models import TINY_TEST_PROFILE
from docprod.render.renderer import render_preview
from docprod.render.subtitles import build_srt
from docprod.stock.downloader import reclip_stock_to_duration
from docprod.storage.hashing import content_hash, file_sha256
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import ProjectPaths

runner = CliRunner()


def _settings() -> Settings:
    return Settings(
        allow_paid_apis=True,
        openai_api_key=SecretStr("test-not-a-real-key"),
        log_level="INFO",
    )


def _project(pid: str = "tiny") -> Project:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Project(
        id=pid,
        title="Tiny",
        language="tr",
        target_duration_seconds=4,
        created_at=now,
        updated_at=now,
        random_seed=7,
    )


def _scene(
    scene_id: str,
    text: str,
    start: float,
    end: float,
    *,
    strategy: AssetStrategy = AssetStrategy.placeholder,
    effect: VisualEffect = VisualEffect.slow_push_in,
    category: str = "generic",
) -> Scene:
    generation = GenerationSpec()
    if strategy == AssetStrategy.ai_image:
        generation = GenerationSpec(image_prompt="still")
    return Scene(
        id=scene_id,
        start=start,
        end=end,
        duration=round(end - start, 4),
        narration=text,
        visual_intent=text,
        asset_strategy=strategy,
        effect=effect,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=text,
        generation=generation,
        metadata={"primary_category": category},
    )


def _write_wav(path: Path, duration: float = 2.4) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=44100",
            "-t",
            f"{duration:.3f}",
            "-ac",
            "1",
            str(path),
        ],
        timeout=30,
    )
    return path.read_bytes()


def _color_mp4(path: Path, *, duration: float = 4.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30",
            "-t",
            str(duration),
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-c:v",
            "libx264",
            str(path),
        ],
        timeout=60,
    )


def _jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ["-f", "lavfi", "-i", "color=c=blue:s=320x180", "-frames:v", "1", str(path)],
        timeout=20,
    )


class FakeSpeech:
    def __init__(self, wav_bytes: bytes) -> None:
        self.calls: list[dict[str, object]] = []
        self.wav_bytes = wav_bytes

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.wav_bytes)


class FakeTranscriptions:
    def __init__(self, words: list[dict[str, object]], language: str = "turkish") -> None:
        self.calls: list[dict[str, object]] = []
        self.words = words
        self.language = language

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        payload = {"language": self.language, "words": self.words, "text": "x"}
        return SimpleNamespace(model_dump=lambda p=payload: p)


def _client(speech: FakeSpeech, transcriptions: FakeTranscriptions) -> SimpleNamespace:
    return SimpleNamespace(
        audio=SimpleNamespace(speech=speech, transcriptions=transcriptions),
    )


def _plan_two() -> ScenePlan:
    return ScenePlan(
        project_id="tiny",
        scenes=[
            _scene("scene_0001", "Bir adam yürüdü.", 0.0, 2.0),
            _scene("scene_0002", "Araba durdu şimdi.", 2.0, 4.0),
        ],
        total_duration=4.0,
    )


def _whisper_words() -> list[dict[str, object]]:
    return [
        {"word": "Bir", "start": 0.10, "end": 0.30},
        {"word": "adam", "start": 0.30, "end": 0.50},
        {"word": "yürüdü", "start": 0.50, "end": 0.90},
        {"word": "Araba", "start": 1.20, "end": 1.50},
        {"word": "durdu", "start": 1.50, "end": 1.80},
        {"word": "şimdi", "start": 1.80, "end": 2.10},
    ]


def test_paid_gate_rejects_without_confirm(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "tiny")
    plan = _plan_two()
    wav = tmp_path / "n.wav"
    _write_wav(wav, 2.4)
    speech = FakeSpeech(wav.read_bytes())
    tts = OpenAITTSProvider(settings=_settings(), client=_client(speech, FakeTranscriptions([])))
    with pytest.raises(PaidApiNotConfirmedError):
        generate_narration(
            paths,
            project=_project(),
            plan=plan,
            confirm_paid=False,
            settings=_settings(),
            tts=tts,
            whisper=OpenAIWhisperAligner(settings=_settings(), client=SimpleNamespace()),
        )
    assert speech.calls == []
    assert not paths.runtime_timeline_json().is_file()


def test_one_master_tts_and_whisper_and_runtime(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "tiny")
    paths.stages_dir.mkdir(parents=True, exist_ok=True)
    plan = _plan_two()
    save_model(paths.scene_plan_json, plan)
    before = content_hash(load_model(paths.scene_plan_json, ScenePlan))
    wav = tmp_path / "n.wav"
    payload = _write_wav(wav, 2.4)
    speech = FakeSpeech(payload)
    trans = FakeTranscriptions(_whisper_words())
    client = _client(speech, trans)
    result = generate_narration(
        paths,
        project=_project(),
        plan=plan,
        confirm_paid=True,
        settings=_settings(),
        tts=OpenAITTSProvider(settings=_settings(), client=client),
        whisper=OpenAIWhisperAligner(settings=_settings(), client=client),
    )
    assert len(speech.calls) == 1
    assert speech.calls[0]["input"] == result.script.text
    assert speech.calls[0]["response_format"] == "wav"
    assert len(trans.calls) == 1
    assert trans.calls[0]["timestamp_granularities"] == ["word"]
    assert trans.calls[0]["language"] == "tr"
    assert result.tts_request_count == 1
    assert result.whisper_request_count == 1
    assert result.alignment.match_fraction == 1.0
    assert [item.scene_id for item in result.timeline.scenes] == ["scene_0001", "scene_0002"]
    assert result.timeline.scenes[0].end == result.timeline.scenes[1].start
    assert result.timeline.scenes[0].start == 0.0
    assert abs(result.timeline.total_duration - result.meta.duration) < 0.08
    after = content_hash(load_model(paths.scene_plan_json, ScenePlan))
    assert after == before
    assert abs(plan.total_duration - 4.0) < 1e-9
    timed = [
        scene.model_copy(
            update={
                "start": item.start,
                "end": item.end,
                "duration": item.duration,
            }
        )
        for scene, item in zip(plan.scenes, result.timeline.scenes, strict=True)
    ]
    srt = build_srt(
        ScenePlan(
            project_id="tiny",
            scenes=timed,
            total_duration=result.timeline.total_duration,
        )
    )
    assert "Bir adam yürüdü" in srt
    assert "00:00:00,000" in srt


def test_low_alignment_does_not_write_timeline(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "tiny")
    paths.stages_dir.mkdir(parents=True, exist_ok=True)
    plan = _plan_two()
    wav = tmp_path / "n.wav"
    payload = _write_wav(wav, 2.4)
    speech = FakeSpeech(payload)
    trans = FakeTranscriptions(
        [{"word": "hello", "start": 0.0, "end": 0.2}, {"word": "world", "start": 0.2, "end": 0.4}]
    )
    client = _client(speech, trans)
    with pytest.raises(AlignmentQualityError):
        generate_narration(
            paths,
            project=_project(),
            plan=plan,
            confirm_paid=True,
            settings=_settings(),
            tts=OpenAITTSProvider(settings=_settings(), client=client),
            whisper=OpenAIWhisperAligner(settings=_settings(), client=client),
        )
    assert not paths.runtime_timeline_json().is_file()


def test_cli_generate_narration_requires_confirm_paid(
    projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOW_PAID_APIS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    from docprod.config import get_settings

    get_settings.cache_clear()
    init = runner.invoke(
        app,
        ["init-project", "demo", "--title", "Demo", "--language", "tr", "--duration", "4"],
    )
    assert init.exit_code == 0, init.output
    paths = ProjectPaths(root=projects_root / "demo")
    save_model(paths.scene_plan_json, _plan_two().model_copy(update={"project_id": "demo"}))
    result = runner.invoke(app, ["generate-narration", "demo"])
    assert result.exit_code != 0
    assert "confirm-paid" in result.output.lower()


def test_still_and_map_retime_to_runtime_duration(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "tiny")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    still = _scene(
        "scene_0003",
        "Bir kare durdu.",
        0.0,
        0.8,
        strategy=AssetStrategy.ai_image,
    )
    mapped = _scene(
        "scene_0012",
        "Haritada rota çizildi.",
        0.8,
        1.6,
        strategy=AssetStrategy.map,
        effect=VisualEffect.map_route,
        category="map_or_travel",
    )
    image = paths.scene_image_path("scene_0003")
    _jpeg(image)
    save_model(
        paths.scene_image_meta("scene_0003"),
        GeneratedImageManifest(
            provider="openai",
            model="gpt-image-2.5-flare",
            scene_id="scene_0003",
            prompt="still",
            size="320x180",
            quality="medium",
            output_format="jpeg",
            source_scene_hash="abc",
            request_hash="def",
            output_path="artifacts/visuals/scene_0003/image.jpg",
            output_sha256=file_sha256(image),
            generation_status="success",
        ),
    )
    execute_generate_graphic(paths, scene=mapped, seed=7)
    result = render_preview(
        paths,
        project=_project(),
        plan=mini_plan(still, mapped),
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=False,
    )
    still_probe = probe_media(paths.preview_segments_dir / "scene_0003.mp4")
    map_probe = probe_media(paths.preview_segments_dir / "scene_0012.mp4")
    assert abs(still_probe.duration - 0.8) < 0.2
    assert abs(map_probe.duration - 0.8) < 0.2
    assert result.manifest.segments[0].source_asset == "generated_still"
    assert result.manifest.segments[1].source_asset == "local_map"


def test_stock_reclip_matches_runtime_and_has_no_audio(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "tiny")
    source = paths.stock_source_mp4("scene_0001")
    _color_mp4(source, duration=4.0)
    dest = paths.stock_clip_mp4("scene_0001")
    reclip_stock_to_duration(source, dest, needed=1.2, seed=7, scene_id="scene_0001")
    probe = probe_media(dest)
    assert probe.has_audio is False
    assert abs(probe.duration - 1.2) < 0.15


def test_final_mix_has_audio_matching_narration(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "tiny")
    paths.preview_segments_dir.mkdir(parents=True, exist_ok=True)
    wav = paths.narration_master_wav()
    _write_wav(wav, 0.8)
    plan = mini_plan(_scene("scene_0001", "Bir adam yürüdü şimdi.", 0.0, 0.8))
    result = render_preview(
        paths,
        project=_project(),
        plan=plan,
        profile=TINY_TEST_PROFILE,
        workers=1,
        use_cache=False,
        output_mp4=paths.preview_narrated_mp4(),
        manifest_path=paths.preview_narrated_manifest(),
        captions_srt=paths.captions_narrated_srt(),
        captions_ass=paths.captions_narrated_ass(),
        narration_wav=wav,
    )
    probe = probe_media(paths.preview_narrated_mp4())
    assert probe.has_audio is True
    assert probe.audio_codec == "aac"
    assert abs(probe.duration - result.manifest.expected_duration) < 0.25
    assert paths.captions_narrated_srt().is_file()
    captions = paths.captions_narrated_srt().read_text(encoding="utf-8")
    assert "Bir adam yürüdü şimdi" in captions


def test_prepare_dry_run_writes_script(tmp_path: Path) -> None:
    paths = ProjectPaths(root=tmp_path / "tiny")
    prepared = prepare_narration(paths, _plan_two(), settings=_settings())
    assert prepared.model == "gpt-4o-mini-tts"
    assert prepared.voice == "cedar"
    assert paths.narration_script_txt().is_file()
    assert tokenize_display(prepared.script.text)[:3] == ["Bir", "adam", "yürüdü"]
