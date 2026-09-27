from __future__ import annotations

from docprod.drama import DEFAULT_PROJECT_ID
from docprod.product.enums import ContentType, ProjectStatus, Visibility
from docprod.product.models import (
    Persona,
    PersonaReference,
    Project,
    Series,
    SeriesContinuity,
    TelegramUser,
    VoiceProfile,
)
from docprod.product.repository import MemoryRepository
from docprod.quality.policy_select import OPENAI_STOCK_VOICES

BIRKO_LOCKED_REFS = {
    "birko": (
        "Birko",
        "chaotic schemer who thinks he is the leader",
        f"projects/{DEFAULT_PROJECT_ID}/artifacts/visuals/character_refs/ref_birko.jpg",
        ("chaotic", "overconfident", "thinks he's the leader"),
    ),
    "kemal": (
        "Kemal",
        "quiet baby who absorbs the chaos",
        f"projects/{DEFAULT_PROJECT_ID}/artifacts/visuals/character_refs/ref_kemal.jpg",
        ("quiet", "observant"),
    ),
    "muge": (
        "Müge",
        "calm decision-maker",
        f"projects/{DEFAULT_PROJECT_ID}/artifacts/visuals/character_refs/ref_muge.jpg",
        ("calm", "sarcastic"),
    ),
}


def assign_stock_voices(characters: list, existing: dict[str, str] | None = None) -> dict[str, str]:
    """Distinct OpenAI stock voices. Persist per character id."""
    assigned = dict(existing or {})
    used = set(assigned.values())
    for character in characters:
        cid = character if isinstance(character, str) else character.id
        if cid in assigned:
            continue
        for voice in OPENAI_STOCK_VOICES:
            if voice not in used:
                assigned[cid] = voice
                used.add(voice)
                break
        else:
            assigned[cid] = OPENAI_STOCK_VOICES[len(assigned) % len(OPENAI_STOCK_VOICES)]
    return assigned


def stock_voice_profile(owner_user_id: str, voice_id: str, language: str = "en") -> VoiceProfile:
    return VoiceProfile(
        owner_user_id=owner_user_id,
        provider="openai",
        voice_id=voice_id,
        display_name=voice_id,
        language=language,
    )


def import_locked_birko_personas(repo: MemoryRepository, user: TelegramUser) -> list[Persona]:
    existing = [
        p
        for p in repo.personas.values()
        if p.owner_user_id == user.id and p.name.lower() in BIRKO_LOCKED_REFS
    ]
    if existing:
        return existing
    created: list[Persona] = []
    for slug, (name, description, path, traits) in BIRKO_LOCKED_REFS.items():
        persona = Persona(
            owner_user_id=user.id,
            name=name,
            display_name=name,
            description=description,
            personality_traits=list(traits),
            locked_identity=True,
            kind="standalone",
            consent_policy="owner_only",
            external_ref_path=path,
        )
        ref = PersonaReference(
            persona_id=persona.id,
            storage_key=path,
            external_path=path,
            primary=True,
        )
        persona.primary_reference_id = ref.id
        repo.personas[persona.id] = persona
        repo.persona_references[ref.id] = ref
        created.append(persona)
    return created


def ensure_birko_episode_2_draft(
    repo: MemoryRepository, user: TelegramUser
) -> tuple[Series, Project]:
    series = next(
        (s for s in repo.series.values() if s.owner_user_id == user.id and s.slug == "birko"),
        None,
    )
    if series is None:
        series = Series(
            owner_user_id=user.id,
            slug="birko",
            title="Birko",
            description="Internal dogfood friend-group series. V1/V2 assets stay locked.",
        )
        repo.series[series.id] = series
        continuity = SeriesContinuity(series_id=series.id)
        repo.series_continuity[continuity.id] = continuity
    draft = next(
        (
            p
            for p in repo.projects.values()
            if p.series_id == series.id and p.episode_number == 2
        ),
        None,
    )
    if draft is None:
        draft = Project(
            user_id=user.id,
            title="Birko Episode 2",
            prompt="Awaiting new cast and story input.",
            content_type=ContentType.FRIEND_GROUP,
            status=ProjectStatus.DRAFT,
            visibility=Visibility.PRIVATE,
            series_id=series.id,
            episode_number=2,
            quality_profile="premium",
            language="tr",
        )
        repo.projects[draft.id] = draft
    return series, draft
