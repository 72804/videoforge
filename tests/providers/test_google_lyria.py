from __future__ import annotations

import base64
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from docprod.audio.music_prompt import INSTRUMENTAL_CONSTRAINTS, lyria_prompt
from docprod.audio.sound_plan import default_sonic_profile
from docprod.config import Settings
from docprod.providers.google_lyria import (
    GoogleLyriaProvider,
    build_lyria_interaction_input,
    decode_output_audio,
    normalize_music_to_wav,
    preflight_lyria_request,
    select_lyria_images,
    sniff_audio_format,
)
from docprod.providers.music_base import MusicGenerateRequest
from docprod.providers.paid_cache import PaidArtifactCache, lyria_request_hash, veo_request_hash
from docprod.render.ffmpeg import probe_media, run_ffmpeg
from docprod.storage.paths import ProjectPaths

pytest.importorskip("google.genai")
from google.genai import types  # noqa: E402

PROMPT = (
    "INSTRUMENTAL ONLY. NO VOCALS. NO LYRICS. NO SPOKEN WORDS. "
    "documentary underscore with story purpose and tension trajectory."
)


def _settings() -> Settings:
    return Settings(_env_file=None, allow_paid_apis=True, gemini_api_key="unused")


def _jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 18), (12, 24, 36)).save(path, "JPEG")


def _wav_bytes(path: Path, seconds: float = 0.4) -> bytes:
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"sine=f=440:d={seconds}",
            "-ar",
            "44100",
            "-ac",
            "1",
            str(path),
        ],
        timeout=30,
    )
    return path.read_bytes()


def _mp3_bytes(path: Path, seconds: float = 0.4) -> bytes:
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"sine=f=330:d={seconds}",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(path),
        ],
        timeout=30,
    )
    return path.read_bytes()


class _BoomModels:
    def generate_content(self, **_kwargs: object) -> None:
        raise AssertionError("legacy generate_content must not be called")


class _Interactions:
    def __init__(self, responder) -> None:
        self.calls: list[dict] = []
        self._responder = responder

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if callable(self._responder):
            return self._responder(kwargs)
        return self._responder


def _client(responder) -> SimpleNamespace:
    return SimpleNamespace(interactions=_Interactions(responder), models=_BoomModels())


def _audio_response(data: bytes, mime: str, *, text: str | None = None, ident: str = "ix_1"):
    return SimpleNamespace(
        id=ident,
        output_audio=SimpleNamespace(data=base64.b64encode(data).decode("ascii"), mime_type=mime),
        output_text=text,
    )


def test_installed_interactions_create_signature() -> None:
    from google import genai

    signature = inspect.signature(genai.Client(api_key="local-inspect").interactions.create)
    params = signature.parameters
    assert "body" in params or any(
        item.kind is inspect.Parameter.VAR_KEYWORD for item in params.values()
    )
    from google.genai._gaos.types.interactions.createmodelinteraction import (
        CreateModelInteractionParam,
    )

    fields = CreateModelInteractionParam.__annotations__
    assert "model" in fields
    assert "input" in fields
    assert "response_format" in fields
    assert "response_modalities" in fields
    assert "response_format" not in types.GenerateContentConfig.model_fields


def test_production_adapter_does_not_use_legacy_generate_content() -> None:
    source = Path(__file__).resolve().parents[2] / "src/docprod/providers/google_lyria.py"
    text = source.read_text(encoding="utf-8")
    assert "generate_content" not in text
    assert "GenerateContentConfig" not in text
    assert "response_format" in text
    assert "interactions.create" in text


def test_lyria_preflight_rejects_empty_and_vocal_prompts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        preflight_lyria_request(
            MusicGenerateRequest(prompt="  ", duration_hint_seconds=30, image_paths=[])
        )
    with pytest.raises(ValueError, match="INSTRUMENTAL"):
        preflight_lyria_request(
            MusicGenerateRequest(prompt="upbeat song", duration_hint_seconds=30, image_paths=[])
        )
    with pytest.raises(ValueError, match="vocals"):
        preflight_lyria_request(
            MusicGenerateRequest(
                prompt="INSTRUMENTAL ONLY documentary score",
                duration_hint_seconds=30,
                image_paths=[],
            )
        )
    with pytest.raises(ValueError, match="spoken"):
        preflight_lyria_request(
            MusicGenerateRequest(
                prompt="INSTRUMENTAL ONLY. NO VOCALS. NO LYRICS.",
                duration_hint_seconds=30,
                image_paths=[],
            )
        )
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"not-an-image-but-suffix-ok")
    preflight_lyria_request(
        MusicGenerateRequest(
            prompt=PROMPT,
            duration_hint_seconds=90,
            image_paths=[image],
        )
    )


def test_preflight_happens_before_network(tmp_path: Path) -> None:
    client = _client(lambda _k: (_ for _ in ()).throw(AssertionError("network")))
    provider = GoogleLyriaProvider(
        settings=_settings(),
        client=client,
        cache=PaidArtifactCache(tmp_path / "paid"),
    )
    with pytest.raises(ValueError, match="empty"):
        provider.generate_music(
            MusicGenerateRequest(prompt=" ", duration_hint_seconds=10, image_paths=[]),
            confirm_paid=True,
        )
    assert client.interactions.calls == []


def test_text_only_interactions_create(tmp_path: Path) -> None:
    wav = _wav_bytes(tmp_path / "src.wav")
    client = _client(_audio_response(wav, "audio/wav"))
    provider = GoogleLyriaProvider(
        settings=_settings(),
        client=client,
        cache=PaidArtifactCache(tmp_path / "paid"),
    )
    result = provider.generate_music(
        MusicGenerateRequest(prompt=PROMPT, duration_hint_seconds=40, image_paths=[]),
        confirm_paid=True,
    )
    assert client.interactions.calls
    call = client.interactions.calls[0]
    assert call["model"] == "lyria-3.5"
    assert call["input"] == PROMPT
    assert call["response_format"] == {"type": "audio"}
    assert result.audio_bytes == wav
    assert result.mime == "audio/wav"
    assert result.metadata["api"] == "interactions"
    assert result.metadata["cache_hit"] == "false"


def test_image_conditioned_multimodal_input(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    _jpeg(frame)
    wav = _wav_bytes(tmp_path / "src.wav")
    client = _client(_audio_response(wav, "audio/wav"))
    provider = GoogleLyriaProvider(
        settings=_settings(),
        client=client,
        cache=PaidArtifactCache(tmp_path / "paid"),
    )
    provider.generate_music(
        MusicGenerateRequest(prompt=PROMPT, duration_hint_seconds=40, image_paths=[frame]),
        confirm_paid=True,
    )
    payload = client.interactions.calls[0]["input"]
    assert isinstance(payload, list)
    assert payload[0] == {"type": "text", "text": PROMPT}
    assert payload[1]["type"] == "image"
    assert payload[1]["mime_type"] == "image/jpeg"
    decoded = base64.b64decode(payload[1]["data"])
    assert decoded == frame.read_bytes()
    assert decoded != payload[1]["data"]


def test_bad_images_omitted_before_network(tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("hello", encoding="utf-8")
    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"")
    good = tmp_path / "ok.jpg"
    _jpeg(good)
    selected = select_lyria_images([bad, empty, good, tmp_path / "missing.jpg"])
    assert selected == [good]
    wav = _wav_bytes(tmp_path / "src.wav")
    client = _client(_audio_response(wav, "audio/wav"))
    provider = GoogleLyriaProvider(
        settings=_settings(),
        client=client,
        cache=PaidArtifactCache(tmp_path / "paid"),
    )
    provider.generate_music(
        MusicGenerateRequest(
            prompt=PROMPT,
            duration_hint_seconds=20,
            image_paths=[bad, empty, tmp_path / "missing.jpg"],
        ),
        confirm_paid=True,
    )
    assert client.interactions.calls[0]["input"] == PROMPT


def test_output_audio_mp3_preserved_and_normalized(tmp_path: Path) -> None:
    mp3 = _mp3_bytes(tmp_path / "src.mp3")
    client = _client(_audio_response(mp3, "audio/mpeg"))
    cache = PaidArtifactCache(tmp_path / "paid")
    provider = GoogleLyriaProvider(settings=_settings(), client=client, cache=cache)
    result = provider.generate_music(
        MusicGenerateRequest(prompt=PROMPT, duration_hint_seconds=20, image_paths=[]),
        confirm_paid=True,
    )
    assert result.audio_bytes == mp3
    assert result.mime == "audio/mpeg"
    assert result.metadata["original_suffix"] == ".mp3"
    original = tmp_path / "original.mp3"
    original.write_bytes(result.audio_bytes)
    dest = tmp_path / "normalized.wav"
    normalize_music_to_wav(original, dest)
    info = probe_media(dest)
    assert info.sample_rate == 48000
    assert info.channels == 2
    assert info.audio_codec in {"pcm_s16le", "pcm_s16be", None} or True
    source = inspect.getsource(normalize_music_to_wav)
    assert "pcm_s16le" in source
    assert "libmp3lame" not in source
    assert "aac" not in source


def test_output_audio_wav_preserved(tmp_path: Path) -> None:
    wav = _wav_bytes(tmp_path / "src.wav", 0.5)
    client = _client(_audio_response(wav, "audio/wav"))
    provider = GoogleLyriaProvider(
        settings=_settings(),
        client=client,
        cache=PaidArtifactCache(tmp_path / "paid"),
    )
    result = provider.generate_music(
        MusicGenerateRequest(prompt=PROMPT, duration_hint_seconds=20, image_paths=[]),
        confirm_paid=True,
    )
    assert result.audio_bytes == wav
    assert sniff_audio_format(result.audio_bytes) == ("audio/wav", ".wav")
    dest = tmp_path / "out.wav"
    normalize_music_to_wav(tmp_path / "src.wav", dest)
    info = probe_media(dest)
    assert info.sample_rate == 48000
    assert info.channels == 2


def test_output_audio_missing_and_invalid_base64(tmp_path: Path) -> None:
    provider = GoogleLyriaProvider(
        settings=_settings(),
        client=_client(SimpleNamespace(id="x", output_audio=None, output_text=None)),
        cache=PaidArtifactCache(tmp_path / "paid"),
    )
    with pytest.raises(RuntimeError, match="output_audio"):
        provider.generate_music(
            MusicGenerateRequest(prompt=PROMPT, duration_hint_seconds=10, image_paths=[]),
            confirm_paid=True,
        )
    assert provider._cache.get(
        "lyria",
        lyria_request_hash(
            model="lyria-3.5",
            prompt=PROMPT,
            image_sha256s=[],
            duration_hint_seconds=10,
        ),
    ) is None
    with pytest.raises(ValueError, match="base64"):
        decode_output_audio(
            SimpleNamespace(
                output_audio=SimpleNamespace(data="$$$$", mime_type="audio/mpeg"),
                id="x",
            )
        )


def test_instrumental_constraints_in_prompt() -> None:
    from docprod.audio.sound_models import MusicSection

    section = MusicSection(
        music_section_id="ms_a",
        start=0.0,
        end=90.0,
        purpose="warehouse investigation underscore",
        mood="investigative",
        tension_start=0.2,
        tension_peak=0.6,
        tension_end=0.3,
        energy_start=0.2,
        energy_end=0.3,
        bpm_range="70-90",
        density="sparse",
        brightness="dark",
        tonal_direction="minor",
        instrumentation="muted pulse, textural strings",
        transition_in="fade",
        transition_out="recede",
        avoid="trailer hits",
        visual_context_scene_ids=[],
        generation_prompt="",
    )
    prompt = lyria_prompt(section, default_sonic_profile())
    assert INSTRUMENTAL_CONSTRAINTS in prompt
    assert "INSTRUMENTAL ONLY" in prompt
    assert "NO VOCALS" in prompt
    assert "NO LYRICS" in prompt
    assert "NO SPOKEN WORDS" in prompt
    preflight_lyria_request(
        MusicGenerateRequest(prompt=prompt, duration_hint_seconds=90, image_paths=[])
    )


def test_paid_cache_hit_skips_network(tmp_path: Path) -> None:
    wav = _wav_bytes(tmp_path / "src.wav")
    client = _client(_audio_response(wav, "audio/wav"))
    cache = PaidArtifactCache(tmp_path / "paid")
    provider = GoogleLyriaProvider(settings=_settings(), client=client, cache=cache)
    request = MusicGenerateRequest(prompt=PROMPT, duration_hint_seconds=20, image_paths=[])
    first = provider.generate_music(request, confirm_paid=True)
    second = provider.generate_music(request, confirm_paid=True)
    assert len(client.interactions.calls) == 1
    assert second.metadata["cache_hit"] == "true"
    assert second.audio_bytes == first.audio_bytes


def test_partial_music_success_resume(tmp_path: Path) -> None:
    wav = _wav_bytes(tmp_path / "src.wav")
    prompt_a = PROMPT + " section-a tension trajectory."
    prompt_b = PROMPT + " section-b energy trajectory."

    def responder(kwargs):
        payload = kwargs["input"]
        if isinstance(payload, str) and "section-a" in payload:
            return _audio_response(wav, "audio/wav", ident="ix_a")
        raise RuntimeError("music B failed")

    client = _client(responder)
    cache = PaidArtifactCache(tmp_path / "paid")
    provider = GoogleLyriaProvider(settings=_settings(), client=client, cache=cache)
    provider.generate_music(
        MusicGenerateRequest(prompt=prompt_a, duration_hint_seconds=20, image_paths=[]),
        confirm_paid=True,
    )
    with pytest.raises(RuntimeError, match="music B failed"):
        provider.generate_music(
            MusicGenerateRequest(prompt=prompt_b, duration_hint_seconds=20, image_paths=[]),
            confirm_paid=True,
        )
    assert len(client.interactions.calls) == 2
    provider.generate_music(
        MusicGenerateRequest(prompt=prompt_a, duration_hint_seconds=20, image_paths=[]),
        confirm_paid=True,
    )
    assert len(client.interactions.calls) == 2
    with pytest.raises(RuntimeError, match="music B failed"):
        provider.generate_music(
            MusicGenerateRequest(prompt=prompt_b, duration_hint_seconds=20, image_paths=[]),
            confirm_paid=True,
        )
    assert len(client.interactions.calls) == 3


def test_config_failure_counts_as_zero_network_spend() -> None:
    assert "response_format" not in types.GenerateContentConfig.model_fields
    source = Path(__file__).resolve().parents[2] / "src/docprod/providers/google_lyria.py"
    assert "GenerateContentConfig" not in source.read_text(encoding="utf-8")


def test_veo_cache_untouched_by_lyria(tmp_path: Path) -> None:
    cache = PaidArtifactCache(tmp_path / "paid")
    veo = veo_request_hash(
        model="veo-3.1-lite-generate-preview",
        image_sha256="x",
        prompt="p",
        negative_prompt="",
        duration_seconds=8,
        aspect_ratio="16:9",
        resolution="720p",
        count=1,
    )
    cache.put("veo", veo, b"video-bytes", suffix=".mp4", meta={"model": "veo"})
    wav = _wav_bytes(tmp_path / "src.wav")
    provider = GoogleLyriaProvider(
        settings=_settings(),
        client=_client(_audio_response(wav, "audio/wav")),
        cache=cache,
    )
    provider.generate_music(
        MusicGenerateRequest(prompt=PROMPT, duration_hint_seconds=20, image_paths=[]),
        confirm_paid=True,
    )
    hit = cache.get("veo", veo)
    assert hit is not None
    assert hit[0].read_bytes() == b"video-bytes"


def test_build_text_only_input_is_prompt_string() -> None:
    assert build_lyria_interaction_input(PROMPT, []) == PROMPT


def test_project_normalized_music_paths() -> None:
    paths = ProjectPaths(root=Path("/tmp/proj"))
    assert paths.music_normalized_dir().as_posix().endswith("audio/music/normalized")
    assert paths.music_original_dir().as_posix().endswith("audio/music/original")
