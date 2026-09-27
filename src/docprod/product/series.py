from __future__ import annotations

import unicodedata
from pathlib import Path

from docprod.product.birko_bible import (
    BIRKO_CAST,
    CUSTOM_IDENTITY_INPUTS,
    GROUP_DYNAMIC,
    INPUTS_CHARACTERS_RELATIVE,
    REFS_RELATIVE,
    BirkoCastMember,
    episode_2_draft_prompt,
)
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

BIRKO_E2_TARGET_STACK = {
    "story_treatments": "gpt-6-astra",
    "script_critic": "gpt-6-astra",
    "final_script": "gpt-6-astra",
    "requires_anthropic": False,
    "critic_fresh_call": True,
    "identity": "locked_refs_plus_sunburst",
    "scene_images": "sunburst_flare_routed",
    "video": "per_shot_eligible",
    "voices": "eleven-v3_or_stock",
    "motion_graphics": "local_ffmpeg_first",
    "execute": False,
}

# Legacy alias: locked original three. Do not regenerate these files.
BIRKO_LOCKED_REFS = {
    member.slug: (
        member.name,
        member.description,
        f"{REFS_RELATIVE}/{member.expected_ref_filenames[0]}",
        member.personality_traits,
    )
    for member in BIRKO_CAST
    if member.always_locked
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def birko_character_refs_dir() -> Path:
    return _repo_root() / REFS_RELATIVE


def birko_character_inputs_dir() -> Path:
    return _repo_root() / INPUTS_CHARACTERS_RELATIVE


def custom_identity_source(slug: str) -> Path | None:
    filename = CUSTOM_IDENTITY_INPUTS.get(slug)
    if not filename:
        return None
    path = birko_character_inputs_dir() / slug / filename
    return path if path.is_file() else None


def _jpeg_from(source: Path, dest: Path) -> None:
    from PIL import Image

    image = Image.open(source).convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="JPEG", quality=95, optimize=True)


def promote_muge_user_photos() -> dict[str, str]:
    """Use the 22.00.03 screenshot as primary Müge; keep 21.59.37 as a second angle.

    Archives the old generated still. Does not call image models.
    """
    folder = birko_character_refs_dir()
    primary_src = folder / "Screenshot 2026-09-27 at 22.00.03.png"
    alt_src = folder / "Screenshot 2026-09-27 at 21.59.37.png"
    canonical = folder / "ref_muge.jpg"
    alt = folder / "ref_muge_alt.jpg"
    archive = folder / "ref_muge_v1_archive.jpg"
    result: dict[str, str] = {}
    if primary_src.is_file() and canonical.is_file() and not archive.is_file():
        canonical.replace(archive)
        result["archived"] = archive.name
    if primary_src.is_file():
        _jpeg_from(primary_src, canonical)
        result["primary"] = canonical.name
    if alt_src.is_file():
        _jpeg_from(alt_src, alt)
        result["alt"] = alt.name
    return result


def promote_custom_identity_photos() -> dict[str, dict[str, str]]:
    """Lock Birko/Kemal to user inputs/characters/*/front.png, not generated v1 stills.

    Archives the old canonical JPEG once. Does not call image models.
    """
    from docprod.storage.hashing import file_sha256

    folder = birko_character_refs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, str]] = {}
    for slug in CUSTOM_IDENTITY_INPUTS:
        source = custom_identity_source(slug)
        if source is None:
            continue
        canonical = folder / f"ref_{slug}.jpg"
        archive = folder / f"ref_{slug}_v1_archive.jpg"
        tmp = folder / f".ref_{slug}.promote.jpg"
        _jpeg_from(source, tmp)
        new_sha = file_sha256(tmp)
        row = {"source": str(source), "primary": canonical.name}
        if canonical.is_file() and file_sha256(canonical) == new_sha:
            tmp.unlink(missing_ok=True)
            row["unchanged"] = "1"
            out[slug] = row
            continue
        if canonical.is_file() and not archive.is_file():
            canonical.replace(archive)
            row["archived"] = archive.name
        tmp.replace(canonical)
        out[slug] = row
    return out


def _norm(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    return ascii_only.casefold().strip()


def list_birko_ref_inventory() -> dict[str, object]:
    folder = birko_character_refs_dir()
    present: list[str] = []
    if folder.is_dir():
        present = sorted(
            path.name
            for path in folder.iterdir()
            if path.is_file() and not path.name.startswith(".")
        )
    present_folded = {name.casefold(): name for name in present}
    by_slug: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    for member in BIRKO_CAST:
        hits: list[str] = []
        for expected in member.expected_ref_filenames:
            actual = present_folded.get(expected.casefold())
            if actual and actual not in hits:
                hits.append(actual)
        by_slug[member.slug] = {
            "name": member.name,
            "expected": list(member.expected_ref_filenames),
            "found": hits,
            "locked_identity": member.always_locked or (member.lock_if_ref_exists and bool(hits)),
        }
        if not hits:
            missing.append(member.slug)
    return {
        "folder": str(folder.relative_to(_repo_root()) if folder.exists() else REFS_RELATIVE),
        "present_files": present,
        "by_slug": by_slug,
        "missing_slugs": missing,
    }


def _resolve_ref_path(member: BirkoCastMember, inventory: dict[str, object]) -> tuple[str, bool]:
    by_slug = inventory["by_slug"]
    row = by_slug[member.slug] if isinstance(by_slug, dict) else {}
    found = list(row.get("found") or []) if isinstance(row, dict) else []
    if found:
        return f"{REFS_RELATIVE}/{found[0]}", True
    if member.always_locked and member.expected_ref_filenames:
        return f"{REFS_RELATIVE}/{member.expected_ref_filenames[0]}", True
    if member.expected_ref_filenames:
        return f"{REFS_RELATIVE}/{member.expected_ref_filenames[0]}", False
    return "", False


def _find_persona(
    repo: MemoryRepository, user_id: str, member: BirkoCastMember
) -> Persona | None:
    keys = {_norm(member.slug), _norm(member.name), _norm(member.display_name)}
    keys.update(_norm(alias) for alias in member.aliases)
    for persona in repo.personas.values():
        if persona.owner_user_id != user_id:
            continue
        names = {_norm(persona.name), _norm(persona.display_name)}
        names.update(_norm(alias) for alias in persona.aliases)
        if names & keys:
            return persona
    return None


def _apply_bible(
    persona: Persona,
    member: BirkoCastMember,
    *,
    ref_path: str,
    identity_ready: bool,
) -> None:
    locked = member.always_locked or (member.lock_if_ref_exists and identity_ready)
    if member.always_locked and persona.external_ref_path:
        ref_path = persona.external_ref_path
        locked = True
    persona.name = member.name
    persona.display_name = member.display_name
    persona.description = member.description
    persona.personality_traits = list(member.personality_traits)
    persona.role_archetype = member.role_archetype
    persona.appearance_notes = member.appearance_notes
    persona.relationships = dict(member.relationships)
    persona.catchphrases = list(member.catchphrases)
    persona.behavioral_quirks = list(member.behavioral_quirks)
    persona.voice_notes = member.voice_notes
    persona.never_do = list(member.never_do)
    persona.aliases = list(member.aliases)
    persona.kind = "standalone"
    persona.consent_policy = "owner_only"
    persona.locked_identity = locked
    persona.external_ref_path = ref_path


def import_locked_birko_personas(repo: MemoryRepository, user: TelegramUser) -> list[Persona]:
    """Upsert the full Birko bible. Never copies or regenerates locked image files."""
    promote_muge_user_photos()
    promote_custom_identity_photos()
    inventory = list_birko_ref_inventory()
    out: list[Persona] = []
    for member in BIRKO_CAST:
        ref_path, identity_ready = _resolve_ref_path(member, inventory)
        persona = _find_persona(repo, user.id, member)
        if persona is None:
            persona = Persona(owner_user_id=user.id, name=member.name)
            repo.personas[persona.id] = persona
        _apply_bible(persona, member, ref_path=ref_path, identity_ready=identity_ready)
        if ref_path:
            found_names: list[str] = []
            row = inventory["by_slug"]
            if isinstance(row, dict) and isinstance(row.get(member.slug), dict):
                found_names = list(row[member.slug].get("found") or [])
            paths = [f"{REFS_RELATIVE}/{name}" for name in found_names] or [ref_path]
            existing_refs = [
                row
                for row in repo.persona_references.values()
                if row.persona_id == persona.id
            ]
            by_path = {item.external_path or item.storage_key: item for item in existing_refs}
            primary_ref = None
            for index, path in enumerate(paths):
                is_primary = index == 0
                item = by_path.get(path)
                if item is None:
                    item = PersonaReference(
                        persona_id=persona.id,
                        storage_key=path,
                        external_path=path,
                        primary=is_primary,
                    )
                    repo.persona_references[item.id] = item
                else:
                    item.storage_key = path
                    item.external_path = path
                    item.primary = is_primary
                if is_primary:
                    primary_ref = item
            if primary_ref is not None:
                persona.primary_reference_id = primary_ref.id
                persona.external_ref_path = primary_ref.external_path
        out.append(persona)
    return out


def _continuity_for(repo: MemoryRepository, series: Series) -> SeriesContinuity:
    existing = next(
        (row for row in repo.series_continuity.values() if row.series_id == series.id),
        None,
    )
    if existing is None:
        existing = SeriesContinuity(series_id=series.id)
        repo.series_continuity[existing.id] = existing
    existing.character_notes = {
        member.slug: f"{member.role_archetype}. {member.description}" for member in BIRKO_CAST
    }
    existing.running_jokes = [
        "Birko deadpan: dog / zorsun",
        "Erni baby-talk (occasional, not spam)",
        "HG: doggy; Dayiiii / Kemalooom / Bozuk pasta",
        "Musti: Dayı ölmez / Ağğğbiiiğ / Mügelom; 'ben berbat bi insan değilim'",
        GROUP_DYNAMIC,
    ]
    return existing


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
    _continuity_for(repo, series)
    draft = next(
        (
            p
            for p in repo.projects.values()
            if p.series_id == series.id and p.episode_number == 2
        ),
        None,
    )
    prompt = episode_2_draft_prompt()
    if draft is None:
        draft = Project(
            user_id=user.id,
            title="Birko Episode 2",
            prompt=prompt,
            content_type=ContentType.FRIEND_GROUP,
            status=ProjectStatus.DRAFT,
            visibility=Visibility.PRIVATE,
            series_id=series.id,
            episode_number=2,
            quality_profile="premium",
            language="tr",
        )
        repo.projects[draft.id] = draft
    elif draft.status is ProjectStatus.DRAFT and not draft.active_script_version_id:
        draft.prompt = prompt
        draft.language = "tr"
        draft.quality_profile = "premium"
    return series, draft
