from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from docprod.audio.duplicates import detect_repeated_audio
from docprod.audio.integrity import (
    assert_promotable,
    evaluate_chunk_integrity,
    evaluate_master_duration,
)
from docprod.audio.models import DEFAULT_VOICE_INSTRUCTIONS
from docprod.config import Settings
from docprod.exceptions import IntegrityBlockedError, PaidApiNotConfirmedError
from docprod.pipeline.audit_episode import _classify_ai_video, _subtitle_flags
from docprod.pipeline.narration_gates import (
    build_whisper_preflight,
    next_chunk_version,
    retry_narration_chunk,
)
from docprod.providers.openai_tts import OpenAITTSProvider
from docprod.render.ffmpeg import run_ffmpeg
from docprod.storage.paths import ProjectPaths


def test_duration_and_relative_wpm_anomaly() -> None:
    first = evaluate_chunk_integrity(
        chunk_id="chunk_001", word_count=480, character_count=3569, duration=250.2
    )
    assert first.status == "PASS"
    assert 110 < first.wpm < 120
    second = evaluate_chunk_integrity(
        chunk_id="chunk_002",
        word_count=372,
        character_count=2562,
        duration=366.2,
        prior_wpm=[first.wpm],
    )
    assert second.status == "FAIL"
    assert second.wpm < 75


def test_broad_wpm_sanity_warning() -> None:
    result = evaluate_chunk_integrity(
        chunk_id="c", word_count=100, character_count=600, duration=50.0
    )
    assert result.wpm == 120
    assert result.status == "PASS"


def test_malformed_chunk_blocks_master() -> None:
    bad = evaluate_chunk_integrity(
        chunk_id="chunk_002",
        word_count=372,
        character_count=2562,
        duration=366.2,
        prior_wpm=[115.1],
    )
    with pytest.raises(IntegrityBlockedError):
        assert_promotable([bad])


def test_malformed_master_blocks_whisper_preflight(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "proj")
    paths.narration_chunks_dir().mkdir(parents=True)
    (paths.narration_chunks_dir() / "chunk_002.integrity.json").write_text(
        '{"chunk_id":"chunk_002","status":"FAIL","wpm":60.9}',
        encoding="utf-8",
    )
    wav = paths.narration_master_wav()
    wav.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "616", str(wav)],
        timeout=30,
    )
    pre = build_whisper_preflight(paths, canonical_word_count=852, observed_wpm=115.0)
    assert pre.allowed is False
    assert pre.master_status == "FAIL"


def test_repaired_master_may_proceed(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "proj")
    paths.narration_chunks_dir().mkdir(parents=True)
    (paths.narration_chunks_dir() / "chunk_002.integrity.json").write_text(
        '{"chunk_id":"chunk_002","status":"FAIL"}',
        encoding="utf-8",
    )
    paths.narration_master_repair_json().parent.mkdir(parents=True, exist_ok=True)
    paths.narration_master_repair_json().write_text(
        '{"repair_type":"local_duplicate_tail_trim"}', encoding="utf-8"
    )
    wav = paths.narration_master_wav()
    run_ffmpeg(
        ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "8", str(wav)],
        timeout=20,
    )
    pre = build_whisper_preflight(paths, canonical_word_count=20, observed_wpm=120.0)
    assert pre.allowed is True
    assert pre.repaired is True


def test_duplicate_tail_detector_fixture(tmp_path: Path) -> None:
    one = tmp_path / "one.wav"
    two = tmp_path / "two.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1.2",
            "-ac",
            "1",
            str(one),
        ],
        timeout=20,
    )
    run_ffmpeg(
        ["-i", str(one), "-i", str(one), "-filter_complex", "concat=n=2:v=0:a=1", str(two)],
        timeout=20,
    )
    result = detect_repeated_audio(two)
    assert result.max_correlation >= 0.7


def test_retry_creates_version_not_overwrite(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "proj")
    original = paths.narration_chunk_wav(2)
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"RIFF" + b"orig" * 20)
    settings = Settings(
        allow_paid_apis=True, openai_api_key=SecretStr("test-not-a-real-key"), log_level="INFO"
    )

    class Boom:
        def create(self, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(content=b"RIFF" + b"newv" * 20)

    tts = OpenAITTSProvider(
        settings=settings, client=SimpleNamespace(audio=SimpleNamespace(speech=Boom()))
    )
    dest = retry_narration_chunk(
        paths,
        "chunk_002",
        text="Merhaba dünya.",
        instructions=DEFAULT_VOICE_INSTRUCTIONS,
        confirm_paid=True,
        settings=settings,
        tts=tts,
    )
    assert dest != original
    assert original.read_bytes().startswith(b"RIFForig")
    assert dest.is_file()
    assert (paths.narration_chunk_versions_dir("chunk_002") / "v001.wav").is_file()
    assert next_chunk_version(paths.narration_chunk_versions_dir("chunk_002")) >= 2


def test_retry_requires_paid_confirmation(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "proj")
    settings = Settings(
        allow_paid_apis=True, openai_api_key=SecretStr("test-not-a-real-key"), log_level="INFO"
    )
    with pytest.raises(PaidApiNotConfirmedError):
        retry_narration_chunk(
            paths,
            "chunk_002",
            text="x",
            instructions="x",
            confirm_paid=False,
            settings=settings,
        )


def test_no_paid_call_during_qc() -> None:
    with pytest.raises(RuntimeError):
        from docprod.pipeline.audit_episode import audit_episode

        audit_episode(ProjectPaths(Path("/tmp/x")), paid_calls=1)


def test_scene_duration_and_subtitle_qc() -> None:
    flags = _subtitle_flags([(0.0, 0.4, "çok uzun metin " * 8), (1.0, 1.2, "kısa")])
    assert any("too_fast" in item or "too_long" in item or "flash" in item for item in flags)


def test_ai_video_value_classification() -> None:
    assert _classify_ai_video("birden çok fıçıdan numune alınmasını", "high", 8.3) == "HIGH_VALUE"
    assert _classify_ai_video("depo içi fazla rezerv şurubu", "low", 9.1) == "LOW_VALUE"
    assert _classify_ai_video("aynı görünen fıçı sıraları", "low", 8.0) == "LOW_VALUE"


def test_expected_master_range_blocks_old_raw() -> None:
    check = evaluate_master_duration(
        canonical_word_count=852, actual_duration=616.31, observed_wpm=115.1
    )
    assert check.blocks_whisper()
    repaired = evaluate_master_duration(
        canonical_word_count=852, actual_duration=430.87, observed_wpm=115.1
    )
    assert repaired.status in {"PASS", "SUSPICIOUS"}
    assert not repaired.blocks_whisper()
