from __future__ import annotations

from pathlib import Path

import pytest

from docprod.audio.align import align_script_to_whisper
from docprod.audio.chunks import (
    TTS_API_MAX_INPUT_CHARS,
    TTS_SAFE_CHUNK_CHARS,
    NarrationChunkPlanner,
    validate_chunk_manifest,
)
from docprod.audio.join import (
    EDGE_FADE,
    JOIN_CHAPTER,
    MAX_JOIN_CHAPTER,
    concat_chunk_wavs,
    detect_edge_silence,
    format_normalize_wav,
    join_target_seconds,
)
from docprod.audio.models import (
    DEFAULT_VOICE_INSTRUCTIONS,
    TTS_CONTINUATION_INSTRUCTIONS,
    TTS_ONCE_INSTRUCTIONS,
    CanonicalNarrationScript,
    SceneNarrationSpan,
    WhisperWord,
)
from docprod.exceptions import MaxPaidRequestsExceededError
from docprod.models.enums import AssetStrategy, Mood, TransitionType, VisualEffect
from docprod.models.scene import GenerationSpec, Scene, ScenePlan
from docprod.providers.request_budget import ModelRequestBudget
from docprod.render.ffmpeg import run_ffmpeg


def _script(
    text: str, *, chapters: list[str] | None = None
) -> tuple[CanonicalNarrationScript, ScenePlan]:
    span = SceneNarrationSpan(
        scene_id="scene_0001",
        narration=text,
        char_start=0,
        char_end=len(text),
        planned_duration=1.0,
    )
    script = CanonicalNarrationScript(project_id="p", text=text, spans=[span])
    scene = Scene(
        id="scene_0001",
        start=0,
        end=1,
        duration=1,
        narration=text,
        visual_intent="x",
        asset_strategy=AssetStrategy.document,
        effect=VisualEffect.none,
        transition=TransitionType.cut,
        mood=Mood.neutral,
        subtitle=text[:40],
        generation=GenerationSpec(),
        metadata={"chapter": (chapters or ["A"])[0]},
    )
    plan = ScenePlan(project_id="p", scenes=[scene], total_duration=1)
    return script, plan


def _chapter_script() -> tuple[CanonicalNarrationScript, ScenePlan]:
    a = ("Birinci bölüm cümlesi. " * 150).strip()
    b = ("İkinci bölüm cümlesi. " * 150).strip()
    text = a + " " + b
    spans = [
        SceneNarrationSpan(
            scene_id="scene_0001", narration=a, char_start=0, char_end=len(a), planned_duration=1
        ),
        SceneNarrationSpan(
            scene_id="scene_0002",
            narration=b,
            char_start=len(a) + 1,
            char_end=len(text),
            planned_duration=1,
        ),
    ]
    script = CanonicalNarrationScript(project_id="p", text=text, spans=spans)
    scenes = []
    for index, (sid, narration, chapter, start) in enumerate(
        (
            ("scene_0001", a, "HOOK", 0.0),
            ("scene_0002", b, "BODY", 1.0),
        ),
        start=1,
    ):
        scenes.append(
            Scene(
                id=sid,
                start=start,
                end=start + 1,
                duration=1,
                narration=narration,
                visual_intent="x",
                asset_strategy=AssetStrategy.document,
                effect=VisualEffect.none,
                transition=TransitionType.cut,
                mood=Mood.neutral,
                subtitle="x",
                generation=GenerationSpec(),
                metadata={"chapter": chapter},
            )
        )
    plan = ScenePlan(project_id="p", scenes=scenes, total_duration=2)
    return script, plan


def _two_chapter(left: str, right: str) -> tuple[CanonicalNarrationScript, ScenePlan]:
    text = left + " " + right
    script = CanonicalNarrationScript(
        project_id="p",
        text=text,
        spans=[
            SceneNarrationSpan(
                scene_id="scene_0001",
                narration=left,
                char_start=0,
                char_end=len(left),
                planned_duration=1,
            ),
            SceneNarrationSpan(
                scene_id="scene_0002",
                narration=right,
                char_start=len(left) + 1,
                char_end=len(text),
                planned_duration=1,
            ),
        ],
    )
    scenes = []
    for sid, narration, chapter, start in (
        ("scene_0001", left, "HOOK", 0.0),
        ("scene_0002", right, "BODY", 1.0),
    ):
        scenes.append(
            Scene(
                id=sid,
                start=start,
                end=start + 1,
                duration=1,
                narration=narration,
                visual_intent="x",
                asset_strategy=AssetStrategy.document,
                effect=VisualEffect.none,
                transition=TransitionType.cut,
                mood=Mood.neutral,
                subtitle="x",
                generation=GenerationSpec(),
                metadata={"chapter": chapter},
            )
        )
    return script, ScenePlan(project_id="p", scenes=scenes, total_duration=2)


def test_short_script_one_chunk() -> None:
    script, plan = _script("Kısa belgesel cümlesi burada biter.")
    manifest = NarrationChunkPlanner().plan(script, plan)
    assert manifest.chunk_count == 1
    assert manifest.chunks[0].character_count <= TTS_SAFE_CHUNK_CHARS


def test_long_script_multiple_chunks() -> None:
    sentence = "Bu cümle belgesel anlatımını sürdürür. "
    text = sentence * 200
    script, plan = _script(text.strip())
    manifest = NarrationChunkPlanner().plan(script, plan)
    assert manifest.canonical_character_count > 4096
    assert manifest.chunk_count >= 2
    assert all(item.character_count <= TTS_API_MAX_INPUT_CHARS for item in manifest.chunks)
    validate_chunk_manifest(manifest, script)


def test_prefers_safe_limit() -> None:
    sentence = "Ölçülü bir cümle daha. "
    text = (sentence * 250).strip()
    script, plan = _script(text)
    manifest = NarrationChunkPlanner().plan(script, plan)
    assert manifest.chunks[0].character_count <= TTS_SAFE_CHUNK_CHARS


def test_chapter_boundary_preferred() -> None:
    script, plan = _chapter_script()
    manifest = NarrationChunkPlanner().plan(script, plan)
    assert manifest.chunk_count == 2
    assert manifest.chunks[1].boundary_type == "chapter"
    assert "".join(item.text for item in manifest.chunks) == script.text


def test_date_phrase_cannot_be_split() -> None:
    from docprod.audio.boundaries import NarrationBoundaryValidator

    text = "Polis 25 Eylül 2012 de operasyon yaptı."
    split = text.index("2012")
    assert NarrationBoundaryValidator().reason(text, split) == "date_phrase"
    left = ("Anlatı düzenli ilerler. " * 155) + "Operasyon 25 Eylül"
    right = "2012 de polis geldi. " + ("Sonrası cümle burada biter. " * 90)
    script, plan = _two_chapter(left.strip(), right.strip())
    manifest = NarrationChunkPlanner().plan(script, plan)
    joined = "".join(item.text for item in manifest.chunks)
    assert joined == script.text
    cut_at_date = manifest.chunks[0].text.rstrip().endswith("Eylül") and manifest.chunks[
        1
    ].text.lstrip().startswith("2012")
    assert not cut_at_date
    validate_chunk_manifest(manifest, script)


def test_number_unit_cannot_be_split() -> None:
    from docprod.audio.boundaries import NarrationBoundaryValidator

    text = "Toplam 18 milyon Kanada doları kayboldu."
    split = text.index("Kanada")
    assert NarrationBoundaryValidator().reason(text, split) == "number_unit"


def test_full_name_cannot_be_split() -> None:
    from docprod.audio.boundaries import NarrationBoundaryValidator

    text = "Sonra Richard Vallières ifade verdi."
    split = text.index("Vallières")
    assert NarrationBoundaryValidator().reason(text, split) == "full_name"


def test_unsafe_chapter_boundary_rejected() -> None:
    left = ("Anlatı düzenli ilerler. " * 155) + "Operasyon 25 Eylül"
    right = "2012 de polis geldi. " + ("Sonrası cümle burada biter. " * 90)
    script, plan = _two_chapter(left.strip(), right.strip())
    manifest = NarrationChunkPlanner().plan(script, plan)
    assert manifest.chunks[1].boundary_type != "chapter" or not manifest.chunks[0].text.endswith(
        "Eylül"
    )


def test_safe_sentence_boundary_preferred() -> None:
    text = ("kelime " * 900 + "Son. " + "devam " * 900).strip()
    script, plan = _script(text)
    manifest = NarrationChunkPlanner().plan(script, plan)
    for item in manifest.chunks:
        assert not item.text or item.text[0].isalnum() or item.text[0].isspace()
        assert "keli me" not in item.text
    validate_chunk_manifest(manifest, script)


def test_reconstruction_and_spans() -> None:
    script, plan = _chapter_script()
    manifest = NarrationChunkPlanner().plan(script, plan)
    validate_chunk_manifest(manifest, script)
    words = set()
    for item in manifest.chunks:
        for index in range(item.word_start, item.word_end):
            assert index not in words
            words.add(index)


def test_budget_equals_chunk_count() -> None:
    budget = ModelRequestBudget(2)
    budget.reserve("tts")
    budget.reserve("tts")
    with pytest.raises(MaxPaidRequestsExceededError):
        budget.reserve("tts")


def test_continuation_instructions() -> None:
    script, plan = _chapter_script()
    manifest = NarrationChunkPlanner().plan(script, plan)
    assert DEFAULT_VOICE_INSTRUCTIONS in manifest.chunks[0].instructions
    assert TTS_ONCE_INSTRUCTIONS in manifest.chunks[0].instructions
    assert TTS_CONTINUATION_INSTRUCTIONS in manifest.chunks[1].instructions
    assert TTS_ONCE_INSTRUCTIONS in manifest.chunks[1].instructions
    left = manifest.chunks[0].instructions.split()[0:3]
    right = manifest.chunks[1].instructions.split()[0:3]
    assert left == right


def test_no_speech_crossfade() -> None:
    assert EDGE_FADE <= 0.01


def test_paragraph_boundary_preferred() -> None:
    a = ("Birinci paragraf cümlesi belgeseli sürdürür. " * 70).strip()
    b = ("İkinci paragraf yeni bir düşünceyle açılır. " * 70).strip()
    text = a + "\n\n" + b
    script, plan = _script(text)
    manifest = NarrationChunkPlanner().plan(script, plan)
    assert manifest.chunk_count == 2
    assert manifest.chunks[1].boundary_type == "paragraph"


def test_sentence_boundary_fallback() -> None:
    sentence = "Ölçülü belgesel cümlesi burada biter. "
    text = (sentence * 220).strip()
    script, plan = _script(text)
    manifest = NarrationChunkPlanner().plan(script, plan)
    assert manifest.chunk_count >= 2
    assert manifest.chunks[1].boundary_type == "sentence"


def test_tts_failed_request_cannot_retry() -> None:
    from types import SimpleNamespace

    from pydantic import SecretStr

    from docprod.config import Settings
    from docprod.providers.openai_tts import OpenAITTSProvider

    class Boom:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs: object) -> None:
            self.calls += 1
            raise RuntimeError("tts failed")

    boom = Boom()
    settings = Settings(
        allow_paid_apis=True,
        openai_api_key=SecretStr("test-not-a-real-key"),
        log_level="INFO",
    )
    provider = OpenAITTSProvider(
        settings=settings,
        client=SimpleNamespace(audio=SimpleNamespace(speech=boom)),
    )
    with pytest.raises(RuntimeError):
        provider.synthesize("Merhaba dünya.", confirm_paid=True, max_attempts=1)
    assert boom.calls == 1
    assert provider.request_count == 1
    assert join_target_seconds("sentence") <= 0.30
    assert JOIN_CHAPTER <= MAX_JOIN_CHAPTER


def _tone(path: Path, duration: float, *, silence_pad: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if silence_pad <= 0:
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=220:sample_rate=48000",
                "-t",
                f"{duration:.3f}",
                "-ac",
                "1",
                str(path),
            ],
            timeout=30,
        )
        return
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc=0:s=48000:d={silence_pad:.3f}",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc=0:s=48000:d={silence_pad:.3f}",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
            "-t",
            f"{duration + 2 * silence_pad:.3f}",
            str(path),
        ],
        timeout=30,
    )


def test_format_normalize_and_concat(tmp_path: Path) -> None:
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _tone(a, 0.4, silence_pad=0.5)
    _tone(b, 0.4, silence_pad=0.5)
    na = tmp_path / "na.wav"
    nb = tmp_path / "nb.wav"
    format_normalize_wav(a, na)
    format_normalize_wav(b, nb)
    dest = tmp_path / "master.wav"
    result = concat_chunk_wavs([na, nb], dest, boundary_types=["start", "sentence"])
    assert dest.is_file()
    assert len(result.join_silences) == 1
    assert result.join_silences[0] >= 0.18
    assert result.join_silences[0] <= 0.30
    lead, trail = detect_edge_silence(na)
    assert lead is None or lead >= 0.0


def test_chunk_windows_constrain_alignment() -> None:
    from docprod.audio.models import ChunkAudioWindow

    plan = ScenePlan(
        project_id="p",
        scenes=[
            Scene(
                id="scene_0001",
                start=0,
                end=1,
                duration=1,
                narration="Bir iki üç dört beş altı yedi sekiz.",
                visual_intent="x",
                asset_strategy=AssetStrategy.document,
                effect=VisualEffect.none,
                transition=TransitionType.cut,
                mood=Mood.neutral,
                subtitle="x",
                generation=GenerationSpec(),
                metadata={"chapter": "A"},
            )
        ],
        total_duration=1,
    )
    whisper = [
        WhisperWord(word="Bir", start=0.0, end=0.2),
        WhisperWord(word="iki", start=0.2, end=0.4),
        WhisperWord(word="üç", start=0.4, end=0.6),
        WhisperWord(word="dört", start=0.6, end=0.8),
        WhisperWord(word="beş", start=5.0, end=5.2),
        WhisperWord(word="altı", start=5.2, end=5.4),
        WhisperWord(word="yedi", start=5.4, end=5.6),
        WhisperWord(word="sekiz", start=5.6, end=5.8),
    ]
    windows = [
        ChunkAudioWindow(word_start=0, word_end=4, audio_start=0.0, audio_end=1.0),
        ChunkAudioWindow(word_start=4, word_end=8, audio_start=5.0, audio_end=6.0),
    ]
    report = align_script_to_whisper(
        plan, whisper, language="tr", require_quality=False, chunk_windows=windows
    )
    assert report.tokens[0].timing_source == "whisper"
    assert report.tokens[4].start == 5.0
