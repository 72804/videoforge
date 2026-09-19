from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from docprod.audio.sound_models import SoundAsset, SoundNeed
from docprod.storage.json_store import load_model, save_model
from docprod.storage.paths import default_cache_root


class SoundLibraryFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    assets: list[SoundAsset] = Field(default_factory=list)


def default_library_path() -> Path:
    return default_cache_root() / "sound_library" / "library.json"


class SoundLibrary:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_library_path()
        self.assets: dict[str, SoundAsset] = {}
        if self.path.is_file():
            payload = load_model(self.path, SoundLibraryFile)
            self.assets = {item.asset_id: item for item in payload.assets}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        save_model(
            self.path,
            SoundLibraryFile(assets=list(self.assets.values())),
        )

    def add(self, asset: SoundAsset) -> None:
        self.assets[asset.asset_id] = asset

    def get(self, asset_id: str) -> SoundAsset | None:
        return self.assets.get(asset_id)

    def match(
        self,
        need: SoundNeed,
        *,
        matcher: str = "metadata",
        embeddings: dict[str, list[float]] | None = None,
        query_vector: list[float] | None = None,
    ) -> SoundAsset | None:
        category = {
            "music": "MUSIC_BED",
            "ambience": "AMBIENCE",
            "event_sfx": "EVENT_SFX",
            "transition_sting": "TRANSITION_STING",
        }.get(need.type)
        if category is None:
            return None
        candidates = [
            asset
            for asset in self.assets.values()
            if asset.reuse_allowed
            and asset.category == category
            and asset.reuse_class != "episode_specific"
        ]
        if not candidates:
            return None
        if matcher == "gemini_embedding_2" and len(self.assets) < 50:
            matcher = "metadata"
        if matcher == "gemini_embedding_2" and embeddings and query_vector:
            scored = sorted(
                candidates,
                key=lambda asset: -_cosine(
                    query_vector, embeddings.get(asset.embedding_id) or []
                ),
            )
            return scored[0] if scored else None
        scored = sorted(candidates, key=lambda asset: -_metadata_score(asset, need))
        best = scored[0]
        if _metadata_score(best, need) <= 0:
            return None
        return best

    def mark_used(self, asset_id: str, project_id: str) -> None:
        asset = self.assets.get(asset_id)
        if asset is None:
            return
        self.assets[asset_id] = asset.model_copy(
            update={
                "usage_count": asset.usage_count + 1,
                "last_used_project": project_id,
            }
        )


def _metadata_score(asset: SoundAsset, need: SoundNeed) -> float:
    score = 0.0
    mood = need.mood.casefold()
    if mood and any(mood in item.casefold() for item in asset.moods):
        score += 2.0
    hay = " ".join(asset.tags + asset.story_roles + [asset.texture, asset.notes]).casefold()
    for token in need.desired_texture.casefold().split():
        if token and token in hay:
            score += 0.5
    if abs(asset.intensity - need.energy) < 0.25:
        score += 0.5
    if need.sync_required and "sync" not in hay:
        score -= 1.0
    return score


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return -1.0
    num = sum(a * b for a, b in zip(left, right, strict=True))
    den_a = sum(a * a for a in left) ** 0.5
    den_b = sum(b * b for b in right) ** 0.5
    if den_a == 0 or den_b == 0:
        return -1.0
    return num / (den_a * den_b)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
