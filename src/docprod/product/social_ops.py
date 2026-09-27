from __future__ import annotations

from docprod.product.enums import (
    CharacterKind,
    ContentType,
    FriendshipStatus,
    ProjectStatus,
    Visibility,
)
from docprod.product.errors import NotFoundError, ProductError
from docprod.product.friend_group import FriendGroupStorySpec
from docprod.product.ids import new_id
from docprod.product.models import (
    Character,
    DialogueTrack,
    Friendship,
    Persona,
    Project,
    TelegramUser,
    utcnow,
)
from docprod.product.privacy import (
    accepted_friend_ids,
    can_cast_linked_user,
    can_view_project,
    friendship_between,
    is_blocked,
)
from docprod.product.series import (
    assign_stock_voices,
    ensure_birko_episode_2_draft,
    import_locked_birko_personas,
    stock_voice_profile,
)
from docprod.product.services import ProductService


def update_profile(svc: ProductService, user: TelegramUser, **fields: object) -> TelegramUser:
    allowed = {
        "display_name",
        "bio",
        "default_traits",
        "allow_friends_to_cast_me",
    }
    for key, value in fields.items():
        if key not in allowed:
            raise ProductError(f"cannot update {key}")
        setattr(user, key, value)
    user.updated_at = svc.clock()
    return user


def request_friend(
    svc: ProductService,
    user: TelegramUser,
    *,
    username: str | None,
    user_id: str | None,
) -> Friendship:
    other: TelegramUser | None = None
    if user_id:
        other = svc.repo.users.get(user_id)
    elif username:
        other = svc.repo.user_by_username(username)
    if other is None:
        raise NotFoundError("user not found")
    if other.id == user.id:
        raise ProductError("cannot friend yourself")
    if is_blocked(svc.repo, user.id, other.id):
        raise ProductError("cannot send friend request")
    existing = friendship_between(svc.repo, user.id, other.id)
    if existing:
        return existing
    row = Friendship(
        requester_id=user.id,
        addressee_id=other.id,
        status=FriendshipStatus.PENDING.value,
    )
    svc.repo.friendships[row.id] = row
    return row


def respond_friend(
    svc: ProductService, user: TelegramUser, friendship_id: str, *, accept: bool
) -> Friendship:
    row = svc.repo.friendships.get(friendship_id)
    if row is None or row.addressee_id != user.id:
        raise NotFoundError("friend request not found")
    row.status = FriendshipStatus.ACCEPTED.value if accept else FriendshipStatus.DECLINED.value
    row.updated_at = utcnow()
    return row


def remove_friend(svc: ProductService, user: TelegramUser, other_id: str) -> None:
    row = friendship_between(svc.repo, user.id, other_id)
    if row is None:
        raise NotFoundError("friendship not found")
    del svc.repo.friendships[row.id]


def list_friends(svc: ProductService, user: TelegramUser) -> list[TelegramUser]:
    ids = accepted_friend_ids(svc.repo, user.id)
    return [svc.repo.users[uid] for uid in ids if uid in svc.repo.users]


def create_persona(svc: ProductService, user: TelegramUser, **fields: object) -> Persona:
    persona = Persona(owner_user_id=user.id, name=str(fields.get("name") or "Friend"))
    for key, value in fields.items():
        if hasattr(persona, key) and key not in {"id", "owner_user_id"}:
            setattr(persona, key, value)
    svc.repo.personas[persona.id] = persona
    return persona


def snapshot_persona_to_project(
    svc: ProductService, user: TelegramUser, project_id: str, persona: Persona
) -> Character:
    project = svc._require_project(user.id, project_id)
    if persona.linked_user_id:
        subject = svc.repo.users.get(persona.linked_user_id)
        if subject is None or not can_cast_linked_user(svc.repo, user.id, subject):
            raise ProductError("casting this person is not allowed")
    character = Character(
        project_id=project.id,
        name=persona.name,
        display_name=persona.display_name or persona.name,
        description=persona.description,
        personality_traits=list(persona.personality_traits),
        role_archetype=persona.role_archetype,
        appearance_notes=persona.appearance_notes,
        relationships=dict(persona.relationships),
        catchphrases=list(persona.catchphrases),
        behavioral_quirks=list(persona.behavioral_quirks),
        locked_identity=persona.locked_identity,
        voice_profile_id=persona.voice_profile_id,
        linked_user_id=persona.linked_user_id,
        owner_user_id=user.id,
        persona_id=persona.id,
        kind=persona.kind,
        consent_policy=persona.consent_policy,
        voice_notes=persona.voice_notes,
        never_do=list(persona.never_do),
        aliases=list(persona.aliases),
    )
    svc.repo.characters[character.id] = character
    return character


def cast_friend_to_project(
    svc: ProductService, user: TelegramUser, project_id: str, friend_user_id: str
) -> Character:
    svc._require_project(user.id, project_id)
    subject = svc.repo.users.get(friend_user_id)
    if subject is None:
        raise NotFoundError("user not found")
    if not can_cast_linked_user(svc.repo, user.id, subject):
        raise ProductError("casting this person is not allowed")
    persona = Persona(
        owner_user_id=user.id,
        name=subject.display_name or subject.first_name or "Friend",
        display_name=subject.display_name or subject.first_name or "Friend",
        personality_traits=list(subject.default_traits),
        linked_user_id=subject.id,
        kind=CharacterKind.LINKED_FRIEND.value,
        consent_policy="friends_cast_ok",
    )
    svc.repo.personas[persona.id] = persona
    return snapshot_persona_to_project(svc, user, project_id, persona)


def visible_projects_for_profile(
    svc: ProductService,
    viewer: TelegramUser,
    subject_id: str,
    *,
    with_me: bool = False,
) -> list[Project]:
    rows: list[Project] = []
    for project in svc.repo.projects.values():
        if project.status is ProjectStatus.ARCHIVED:
            continue
        if not can_view_project(svc.repo, viewer, project):
            continue
        if with_me:
            if not any(
                c.linked_user_id == subject_id for c in svc.repo.characters_for(project.id)
            ):
                continue
        elif project.user_id != subject_id:
            continue
        rows.append(project)
    return sorted(rows, key=lambda p: p.updated_at, reverse=True)


def ensure_character_voices(
    svc: ProductService, user: TelegramUser, project_id: str
) -> dict[str, str]:
    characters = svc.repo.characters_for(project_id)
    existing = {}
    for character in characters:
        if character.voice_profile_id:
            profile = svc.repo.voice_profiles.get(character.voice_profile_id)
            if profile:
                existing[character.id] = profile.voice_id
    assigned = assign_stock_voices(characters, existing)
    for character in characters:
        voice_id = assigned[character.id]
        if character.voice_profile_id:
            continue
        lang = svc.repo.projects[project_id].language
        profile = stock_voice_profile(user.id, voice_id, language=lang)
        svc.repo.voice_profiles[profile.id] = profile
        character.voice_profile_id = profile.id
    return assigned


def attach_story_spec(svc: ProductService, project: Project, spec: FriendGroupStorySpec) -> None:
    if project.active_script_version_id:
        script = svc.repo.scripts.get(project.active_script_version_id)
        if script is not None:
            script.story_spec = spec.model_dump()
    mix_id = new_id()
    from docprod.product.models import AudioMixSpec

    mix = AudioMixSpec(id=mix_id, project_id=project.id, burn_subtitles=True)
    svc.repo.audio_mixes[mix.id] = mix
    for line in spec.dialogue_lines:
        track = DialogueTrack(
            project_id=project.id,
            scene_id=line.scene_id or None,
            speaker_character_id=line.speaker_character_id,
            text=line.text,
            emotion=line.emotion,
        )
        svc.repo.dialogue_tracks[track.id] = track
        mix.dialogue_track_ids.append(track.id)


def seed_birko_foundation(svc: ProductService, user: TelegramUser) -> dict[str, object]:
    personas = import_locked_birko_personas(svc.repo, user)
    series, draft = ensure_birko_episode_2_draft(svc.repo, user)
    return {"personas": personas, "series": series, "episode": draft}


def create_friend_group_project(
    svc: ProductService,
    user: TelegramUser,
    *,
    prompt: str,
    title: str,
    quality_profile: str = "balanced",
    visibility: str = "PRIVATE",
    style: str = "",
) -> Project:
    vis = Visibility(visibility)
    project = svc.create_project(
        user.id,
        title=title,
        prompt=prompt,
        quality_profile=quality_profile,
        style=style,
        content_type=ContentType.FRIEND_GROUP,
        visibility=vis,
    )
    return project
