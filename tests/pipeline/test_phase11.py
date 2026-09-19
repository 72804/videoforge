from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from docprod.audio.models import RuntimeSceneTiming, RuntimeTimeline
from docprod.audio.veo_media import extract_provider_audio, mute_and_normalize_visual, qc_sync_audio
from docprod.config import Settings
from docprod.graphics.renderer import execute_generate_graphic
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.project import Project
from docprod.models.scene import Scene, ScenePlan
from docprod.pipeline.produce_episode import produce_episode
from docprod.providers.music_base import MusicGenerateRequest, MusicGenerateResult
from docprod.providers.pricing import (
    HIGH_VALUE_VIDEO_UNITS,
    LOW_VALUE_VIDEO_UNITS,
    VEO_HARD_REQUESTS,
    VEO_SECONDS_PER_REQUEST,
    veo_cost_usd,
)
from docprod.providers.request_budget import ModelRequestBudget
from docprod.providers.video_base import VideoShotRequest, VideoShotResult
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.storage.json_store import save_model
from docprod.storage.paths import SCENE_PLAN_FILENAME, ProjectPaths, ensure_project_layout
from docprod.writing.models import NarrationBeat, NarrationScript, StoryChapter, StoryOutline


def _jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 36), (40, 40, 40)).save(path, "JPEG")


def _wav(path: Path, seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"sine=f=440:d={seconds}",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(path),
        ],
        timeout=30,
    )


def _mp4_with_audio(path: Path, seconds: float = 8.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=gray:s=1280x720:d={seconds}:r=30",
            "-f",
            "lavfi",
            "-i",
            f"sine=f=220:d={seconds}",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        timeout=40,
    )


def _scene(i: int, start: float, end: float, unit: str, narration: str) -> Scene:
    return Scene(
        id=f"scene_{i:04d}",
        start=start,
        end=end,
        duration=round(end - start, 4),
        narration=narration,
        visual_intent="document",
        asset_strategy=AssetStrategy.document,
        effect=VisualEffect.newspaper_reveal,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=narration,
        metadata={
            "primary_category": "document",
            "asset_unit_id": unit,
            "runtime_preview_strategy": "ai_keyframe_preview",
        },
    )


def _project_bundle(root: Path) -> tuple[ProjectPaths, Project]:
    paths = ProjectPaths(root=root)
    ensure_project_layout(paths)
    now = datetime.now(UTC)
    project = Project(
        id="tiny11",
        title="Phase11",
        language="tr",
        target_duration_seconds=12.0,
        created_at=now,
        updated_at=now,
    )
    save_model(paths.project_json, project)
    scenes = [
        _scene(1, 0.0, 4.0, "au_0005_0006", "depoda fıçı kontrolü"),
        _scene(2, 4.0, 8.0, "au_0018", "soruşturma raporu"),
        _scene(3, 8.0, 12.0, "au_0025", "numune fıçı incelemesi mahkeme"),
    ]
    for scene in scenes:
        execute_generate_graphic(paths, scene=scene, seed=3)
    plan = ScenePlan(project_id="tiny11", scenes=scenes, total_duration=12.0)
    save_model(paths.stages_dir / SCENE_PLAN_FILENAME, plan)
    timeline = RuntimeTimeline(
        project_id="tiny11",
        audio_duration=12.0,
        total_duration=12.0,
        scenes=[
            RuntimeSceneTiming(
                scene_id=scene.id,
                start=scene.start,
                end=scene.end,
                duration=scene.duration,
                planned_duration=scene.duration,
                narration=scene.narration,
                asset_unit_id=str(scene.metadata["asset_unit_id"]),
            )
            for scene in scenes
        ],
    )
    save_model(paths.runtime_timeline_json(), timeline)
    save_model(
        paths.story_script_json(),
        NarrationScript(
            project_id="tiny11",
            outline=StoryOutline(
                chapters=[
                    StoryChapter(
                        chapter_id="c1",
                        title="warehouse_discovery",
                        purpose="hook",
                    )
                ]
            ),
            beats=[NarrationBeat(beat_id="B001", narration="x")],
            full_narration="x",
        ),
    )
    _wav(paths.narration_master_wav(), 12.0)
    for unit in (*HIGH_VALUE_VIDEO_UNITS, *LOW_VALUE_VIDEO_UNITS):
        _jpeg(paths.ai_keyframe_path(unit))
    _mp4_with_audio(paths.preview_visual_v3_mp4(), 12.0)
    return paths, project


def test_produce_dry_run_high_value_budget(tmp_path: Path) -> None:
    paths, project = _project_bundle(tmp_path / "tiny11")
    settings = Settings(
        _env_file=None,
        allow_paid_apis=False,
        enable_lyria_realtime=False,
        enable_semantic_audio_qc=False,
        sound_library_matcher="metadata",
        phase11_max_usd=2.0,
    )
    report = produce_episode(paths, project, dry_run=True, confirm_paid=False, settings=settings)
    assert report.video_units == list(HIGH_VALUE_VIDEO_UNITS)
    assert "au_0018" not in report.video_units
    assert report.video_seconds == VEO_HARD_REQUESTS * VEO_SECONDS_PER_REQUEST
    assert report.video_cost_usd == veo_cost_usd(16)
    assert report.music_generation_count <= 4
    assert report.realtime_enabled is False
    assert report.semantic_qc is False
    assert report.openai_image == 0
    assert report.tts == 0
    assert report.whisper == 0
    assert paths.sound_plan_json().is_file()
    assert paths.sonic_profile_json().is_file()


def test_veo_budget_and_native_audio_split(tmp_path: Path) -> None:
    budget = ModelRequestBudget(VEO_HARD_REQUESTS)
    budget.reserve("veo")
    budget.reserve("veo")
    import pytest

    with pytest.raises(Exception):
        budget.reserve("veo")
    raw = tmp_path / "raw.mp4"
    _mp4_with_audio(raw, 8.0)
    wav = tmp_path / "cand.wav"
    visual = tmp_path / "vis.mp4"
    extract_provider_audio(raw, wav)
    mute_and_normalize_visual(raw, visual, duration=8.14, generated_seconds=8.0)
    assert probe_media(wav).has_audio
    assert probe_media(visual).has_audio is False
    qc = qc_sync_audio(wav, speech_detector=lambda _p: True)
    assert qc.accepted is False
    assert "unexpected_dialogue" in qc.reasons
    clean = qc_sync_audio(wav, speech_detector=lambda _p: False)
    assert clean.speech_like is False


class _FakeVeo:
    name = "google"
    model = "veo-3.1-lite-generate-preview"

    def generate_shot(self, request: VideoShotRequest, *, confirm_paid: bool) -> VideoShotResult:
        assert confirm_paid
        assert request.image_path.is_file()
        dest = request.image_path.with_suffix(".fake.mp4")
        _mp4_with_audio(dest, 8.0)
        payload = dest.read_bytes()
        dest.unlink(missing_ok=True)
        return VideoShotResult(
            video_bytes=payload,
            provider="google",
            model=self.model,
            duration_seconds=8.0,
            prompt=request.prompt,
        )


class _FakeLyria:
    name = "google"
    model = "lyria-3.5"
    calls = 0

    def generate_music(
        self, request: MusicGenerateRequest, *, confirm_paid: bool
    ) -> MusicGenerateResult:
        assert confirm_paid
        assert "INSTRUMENTAL ONLY" in request.prompt
        assert len(request.image_paths) <= 6
        self.calls += 1
        from tempfile import NamedTemporaryFile

        tmp = NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        _wav(Path(tmp.name), 2.0)
        data = Path(tmp.name).read_bytes()
        Path(tmp.name).unlink(missing_ok=True)
        return MusicGenerateResult(
            audio_bytes=data,
            provider="google",
            model=self.model,
            mime="audio/wav",
            prompt=request.prompt,
        )


def test_live_produce_with_fakes(tmp_path: Path, monkeypatch) -> None:
    paths, project = _project_bundle(tmp_path / "tiny11")
    monkeypatch.setenv("ALLOW_PAID_APIS", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from docprod.config import get_settings

    get_settings.cache_clear()
    settings = Settings(
        _env_file=None,
        allow_paid_apis=True,
        gemini_api_key="test-key",
        enable_lyria_realtime=False,
        sound_library_matcher="metadata",
        phase11_max_usd=2.0,
    )
    lyria = _FakeLyria()
    report = produce_episode(
        paths,
        project,
        dry_run=False,
        confirm_paid=True,
        settings=settings,
        video_provider=_FakeVeo(),
        music_provider=lyria,
        speech_detector=lambda _p: False,
    )
    assert report.actual_spend_usd >= 0
    assert paths.veo_visual_path("au_0005_0006").is_file()
    assert paths.veo_candidate_wav("au_0005_0006").is_file()
    assert probe_media(paths.veo_visual_path("au_0005_0006")).has_audio is False
    assert not paths.veo_visual_path("au_0018").is_file()
    assert paths.production_v1_mp4().is_file()
    assert lyria.calls <= 4
    assert paths.preview_visual_v3_mp4().is_file()
