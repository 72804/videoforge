from __future__ import annotations

from docprod.providers.base import (
    ImageGenerationResult,
    TextGenerationResult,
    TTSResult,
    VideoGenerationResult,
)
from docprod.storage.hashing import content_hash


class MockTextGenerationProvider:
    """Deterministic, networkless text mock."""

    provider = "mock"
    model = "mock-text-v1"

    def generate_text(self, prompt: str, *, seed: int | None = None) -> TextGenerationResult:
        digest = content_hash({"prompt": prompt, "seed": seed})[:12]
        return TextGenerationResult(
            text=f"[mock text seed={seed!s} id={digest}] {prompt.strip()}",
            model=self.model,
            provider=self.provider,
            prompt_hash=digest,
            metadata={"network": "false", "paid": "false"},
        )


class MockTTSProvider:
    """Returns timing metadata only. Does not write audio."""

    provider = "mock"
    model = "mock-tts-v1"

    def synthesize(self, text: str, *, seed: int | None = None) -> TTSResult:
        words = max(1, len(text.split()))
        duration = round(words * 0.32, 3)
        return TTSResult(
            text=text,
            duration_seconds=duration,
            sample_rate=24000,
            audio_format="wav",
            provider=self.provider,
            model=self.model,
            note="Mock TTS: metadata only; no audio file generated.",
            metadata={"seed": str(seed), "network": "false", "paid": "false"},
        )


class MockImageGenerationProvider:
    """Describes a placeholder image that would be generated. No pixels."""

    provider = "mock"
    model = "mock-image-v1"

    def generate_image(
        self,
        prompt: str,
        *,
        seed: int | None = None,
        width: int = 1920,
        height: int = 1080,
    ) -> ImageGenerationResult:
        digest = content_hash({"prompt": prompt, "seed": seed, "w": width, "h": height})[:12]
        return ImageGenerationResult(
            prompt=prompt,
            width=width,
            height=height,
            provider=self.provider,
            model=self.model,
            would_write=f"cache/mock-images/{digest}.png",
            note="Mock image: no file written; paid image APIs are not called.",
            seed=seed,
            metadata={"network": "false", "paid": "false"},
        )


class MockVideoGenerationProvider:
    """Describes a placeholder clip that would be generated. No frames."""

    provider = "mock"
    model = "mock-video-v1"

    def generate_video(
        self,
        prompt: str,
        *,
        seed: int | None = None,
        duration_seconds: float = 4.0,
    ) -> VideoGenerationResult:
        digest = content_hash({"prompt": prompt, "seed": seed, "d": duration_seconds})[:12]
        return VideoGenerationResult(
            prompt=prompt,
            duration_seconds=duration_seconds,
            provider=self.provider,
            model=self.model,
            would_write=f"cache/mock-video/{digest}.mp4",
            note="Mock video: no file written; paid video APIs are not called.",
            seed=seed,
            metadata={"network": "false", "paid": "false"},
        )
