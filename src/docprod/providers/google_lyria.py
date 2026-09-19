from __future__ import annotations

import base64
import binascii
import logging
import mimetypes
import tempfile
from pathlib import Path
from typing import Any

from docprod.config import Settings, get_settings, require_gemini_api_key, require_paid_call_allowed
from docprod.providers.music_base import MusicGenerateRequest, MusicGenerateResult
from docprod.providers.paid_cache import PaidArtifactCache, lyria_request_hash
from docprod.providers.pricing import LYRIA_IMAGE_LIMIT
from docprod.render.ffmpeg import FFmpegError, probe_media, run_ffmpeg
from docprod.storage.hashing import file_sha256

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIN_AUDIO_BYTES = 64
MIN_AUDIO_SECONDS = 0.05
LYRIA_API_MODE = "interactions"


def image_mime(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    mime, _ = mimetypes.guess_type(path.name)
    return mime


def select_lyria_images(paths: list[Path], *, limit: int = LYRIA_IMAGE_LIMIT) -> list[Path]:
    selected: list[Path] = []
    for path in paths:
        if len(selected) >= limit:
            break
        if not path.is_file() or path.is_dir():
            continue
        if not path.stat().st_size:
            continue
        if path.stat().st_size > MAX_IMAGE_BYTES:
            logger.warning("Omitting oversized Lyria frame %s", path.name)
            continue
        mime = image_mime(path)
        if mime not in ALLOWED_IMAGE_MIME:
            logger.warning("Omitting unsupported Lyria frame %s", path.name)
            continue
        selected.append(path)
    return selected


def preflight_lyria_request(request: MusicGenerateRequest) -> None:
    text = request.prompt.upper()
    if not request.prompt.strip():
        raise ValueError("Lyria prompt is empty")
    if "INSTRUMENTAL" not in text:
        raise ValueError("Lyria prompt must require INSTRUMENTAL ONLY")
    if "NO VOCALS" not in text:
        raise ValueError("Lyria prompt must forbid vocals/lyrics")
    if "NO LYRICS" not in text:
        raise ValueError("Lyria prompt must forbid vocals/lyrics")
    if "NO SPOKEN" not in text:
        raise ValueError("Lyria prompt must forbid spoken words")
    if len(request.image_paths) > LYRIA_IMAGE_LIMIT:
        raise ValueError(f"Lyria image cap is {LYRIA_IMAGE_LIMIT}")


def build_lyria_interaction_input(
    prompt: str, image_paths: list[Path]
) -> str | list[dict[str, str]]:
    frames = select_lyria_images(image_paths)
    if not frames:
        return prompt
    items: list[dict[str, str]] = [{"type": "text", "text": prompt}]
    for path in frames:
        mime = image_mime(path) or "image/jpeg"
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        items.append({"type": "image", "mime_type": mime, "data": payload})
    return items


def sniff_audio_format(data: bytes, declared_mime: str | None = None) -> tuple[str, str]:
    mime = (declared_mime or "").lower().split(";")[0].strip()
    if data.startswith(b"RIFF") and b"WAVE" in data[:16]:
        return "audio/wav", ".wav"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "audio/mpeg", ".mp3"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "audio/mp4", ".m4a"
    if mime in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return "audio/wav", ".wav"
    if mime in {"audio/mpeg", "audio/mp3"}:
        return "audio/mpeg", ".mp3"
    if mime:
        suffix = mimetypes.guess_extension(mime) or ".bin"
        return mime, suffix
    return "application/octet-stream", ".bin"


def decode_output_audio(interaction: Any) -> tuple[bytes, str | None, str]:
    audio = getattr(interaction, "output_audio", None)
    if audio is None and isinstance(interaction, dict):
        audio = interaction.get("output_audio")
    if audio is None:
        raise RuntimeError("Lyria returned no output_audio")
    if isinstance(audio, dict):
        data = audio.get("data")
        mime = audio.get("mime_type")
    else:
        data = getattr(audio, "data", None)
        mime = getattr(audio, "mime_type", None)
    if data is None or data == "":
        raise RuntimeError("Lyria output_audio data is empty")
    raw = _decode_audio_payload(data)
    if len(raw) < MIN_AUDIO_BYTES:
        raise RuntimeError("Lyria audio is too small to recover")
    interaction_id = ""
    if isinstance(interaction, dict):
        interaction_id = str(interaction.get("id") or "")
    else:
        interaction_id = str(getattr(interaction, "id", None) or "")
    return raw, mime, interaction_id


def _decode_audio_payload(data: Any) -> bytes:
    if isinstance(data, bytes):
        if data.startswith((b"RIFF", b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            return data
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError:
            return data
        data = text
    if not isinstance(data, str) or not data.strip():
        raise ValueError("Lyria output_audio data is empty")
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Lyria output_audio base64 is invalid") from exc


def lyrics_warning(output_text: str | None) -> str | None:
    if not output_text or not output_text.strip():
        return None
    lowered = output_text.lower()
    markers = ("lyric", "lyrics", "verse", "chorus", "vocals", "spoken word")
    if any(marker in lowered for marker in markers):
        return "unexpected lyrical or spoken content in output_text"
    return None


def validate_provider_audio(data: bytes) -> float:
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as handle:
        handle.write(data)
        tmp = Path(handle.name)
    try:
        try:
            info = probe_media(tmp)
        except FFmpegError as exc:
            raise RuntimeError("Lyria audio is undecodable") from exc
        duration = float(info.duration or 0.0)
        if duration < MIN_AUDIO_SECONDS and not info.has_audio:
            raise RuntimeError("Lyria audio duration is effectively zero")
        if duration < MIN_AUDIO_SECONDS:
            raise RuntimeError("Lyria audio duration is effectively zero")
        return duration
    finally:
        tmp.unlink(missing_ok=True)


def normalize_music_to_wav(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".norm.tmp.wav")
    try:
        run_ffmpeg(
            [
                "-i",
                str(source),
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(tmp),
            ],
            timeout=60,
        )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


class GoogleLyriaProvider:
    name = "google"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: Any = None,
        cache: PaidArtifactCache | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.model = self._settings.music_model
        self._client = client
        self._cache = cache if cache is not None else PaidArtifactCache()

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("google-genai is required for Lyria generation") from exc
        key = require_gemini_api_key(self._settings)
        self._client = genai.Client(api_key=key)
        return self._client

    def _digest(self, request: MusicGenerateRequest, frames: list[Path]) -> str:
        return lyria_request_hash(
            model=self.model,
            prompt=request.prompt,
            image_sha256s=[file_sha256(path) for path in frames],
            duration_hint_seconds=request.duration_hint_seconds,
            api=LYRIA_API_MODE,
        )

    def generate_music(
        self,
        request: MusicGenerateRequest,
        *,
        confirm_paid: bool,
        use_cache: bool = True,
    ) -> MusicGenerateResult:
        preflight_lyria_request(request)
        frames = select_lyria_images(request.image_paths)
        digest = self._digest(request, frames)
        if use_cache:
            cached = self._cache.get("lyria", digest)
            if cached is not None:
                path, meta = cached
                audio = path.read_bytes()
                mime = str(meta.get("original_mime") or sniff_audio_format(audio)[0])
                return MusicGenerateResult(
                    audio_bytes=audio,
                    provider=self.name,
                    model=self.model,
                    mime=mime,
                    prompt=request.prompt,
                    metadata={
                        "cache_hit": "true",
                        "request_hash": digest,
                        "original_mime": mime,
                        "original_suffix": path.suffix or sniff_audio_format(audio)[1],
                        "api": LYRIA_API_MODE,
                        "interaction_id": str(meta.get("interaction_id") or ""),
                    },
                )
        require_paid_call_allowed(self.name, confirm_paid=confirm_paid, settings=self._settings)
        client = self._client_or_create()
        payload = build_lyria_interaction_input(request.prompt, frames)
        interaction = client.interactions.create(
            model=self.model,
            input=payload,
            response_format={"type": "audio"},
        )
        raw, declared_mime, interaction_id = decode_output_audio(interaction)
        mime, suffix = sniff_audio_format(raw, declared_mime)
        duration = validate_provider_audio(raw)
        output_text = getattr(interaction, "output_text", None)
        warning = lyrics_warning(output_text if isinstance(output_text, str) else None)
        meta: dict[str, str | int | float | bool] = {
            "provider": self.name,
            "model": self.model,
            "status": "ok",
            "api": LYRIA_API_MODE,
            "original_mime": mime,
            "duration_seconds": duration,
            "byte_count": len(raw),
            "interaction_id": interaction_id,
            "image_count": len(frames),
        }
        if warning:
            meta["lyrics_warning"] = warning
        if output_text:
            meta["output_text"] = output_text[:2000]
        self._cache.put("lyria", digest, raw, suffix=suffix, meta=meta)
        result_meta = {
            "cache_hit": "false",
            "request_hash": digest,
            "original_mime": mime,
            "original_suffix": suffix,
            "api": LYRIA_API_MODE,
            "interaction_id": interaction_id,
            "image_count": str(len(frames)),
        }
        if warning:
            result_meta["lyrics_warning"] = warning
        return MusicGenerateResult(
            audio_bytes=raw,
            provider=self.name,
            model=self.model,
            mime=mime,
            prompt=request.prompt,
            synthid=None,
            metadata=result_meta,
        )


class DisabledAdaptiveMusicProvider:
    name = "google"
    model = "lyria-realtime-exp"
    enabled = False

    def is_available(self) -> bool:
        return False
