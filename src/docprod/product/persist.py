from __future__ import annotations

from pathlib import Path
from typing import Any

from docprod.product.models import (
    Asset,
    AssetVersion,
    AudioMixSpec,
    Character,
    CharacterReference,
    DialogueTrack,
    Friendship,
    GenerationAttempt,
    GenerationJob,
    GenerationPlan,
    IdempotencyRecord,
    NotificationOutbox,
    PaymentIntent,
    Persona,
    PersonaReference,
    Project,
    Render,
    Scene,
    SceneVersion,
    ScriptVersion,
    Series,
    SeriesContinuity,
    StarQuote,
    StarTransaction,
    TelegramPayment,
    TelegramUser,
    VoiceProfile,
    WorkerHeartbeat,
)
from docprod.product.repository import MemoryRepository
from docprod.storage.json_store import load_json, save_json

_TABLES: tuple[tuple[str, type], ...] = (
    ("users", TelegramUser),
    ("projects", Project),
    ("characters", Character),
    ("references", CharacterReference),
    ("scripts", ScriptVersion),
    ("scenes", Scene),
    ("scene_versions", SceneVersion),
    ("assets", Asset),
    ("asset_versions", AssetVersion),
    ("plans", GenerationPlan),
    ("quotes", StarQuote),
    ("intents", PaymentIntent),
    ("jobs", GenerationJob),
    ("attempts", GenerationAttempt),
    ("renders", Render),
    ("transactions", StarTransaction),
    ("payments", TelegramPayment),
    ("outbox", NotificationOutbox),
    ("idempotency", IdempotencyRecord),
    ("workers", WorkerHeartbeat),
    ("voice_profiles", VoiceProfile),
    ("friendships", Friendship),
    ("personas", Persona),
    ("persona_references", PersonaReference),
    ("series", Series),
    ("series_continuity", SeriesContinuity),
    ("dialogue_tracks", DialogueTrack),
    ("audio_mixes", AudioMixSpec),
)


def dump_repository(repo: MemoryRepository) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    mapping = {
        "users": repo.users,
        "projects": repo.projects,
        "characters": repo.characters,
        "references": repo.references,
        "scripts": repo.scripts,
        "scenes": repo.scenes,
        "scene_versions": repo.scene_versions,
        "assets": repo.assets,
        "asset_versions": repo.asset_versions,
        "plans": repo.plans,
        "quotes": repo.quotes,
        "intents": repo.intents,
        "jobs": repo.jobs,
        "attempts": repo.attempts,
        "renders": repo.renders,
        "transactions": repo.transactions,
        "payments": repo.payments,
        "outbox": repo.outbox,
        "idempotency": repo.idempotency,
        "workers": repo.workers,
        "voice_profiles": repo.voice_profiles,
        "friendships": repo.friendships,
        "personas": repo.personas,
        "persona_references": repo.persona_references,
        "series": repo.series,
        "series_continuity": repo.series_continuity,
        "dialogue_tracks": repo.dialogue_tracks,
        "audio_mixes": repo.audio_mixes,
    }
    for name, rows in mapping.items():
        payload[name] = {key: model.model_dump(mode="json") for key, model in rows.items()}
    return payload


def load_repository(
    payload: dict[str, Any], repo: MemoryRepository | None = None
) -> MemoryRepository:
    store = repo or MemoryRepository()
    types = dict(_TABLES)
    for name, model_type in types.items():
        raw = payload.get(name) or {}
        table: dict[str, Any] = getattr(store, name)
        table.clear()
        for key, value in raw.items():
            table[key] = model_type.model_validate(value)
    store.users_by_telegram = {
        user.telegram_user_id: user.id for user in store.users.values()
    }
    store.txn_by_idempotency = {
        txn.idempotency_key: txn.id for txn in store.transactions.values()
    }
    store.payments_by_telegram = {
        pay.telegram_payment_id: pay.id for pay in store.payments.values()
    }
    return store


def save_repository(path: Path, repo: MemoryRepository) -> None:
    save_json(path, dump_repository(repo))


def load_repository_file(path: Path) -> MemoryRepository:
    if not path.is_file():
        return MemoryRepository()
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError("product store is not an object")
    return load_repository(data)
