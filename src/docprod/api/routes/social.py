from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from docprod.api.dependencies import current_user, get_service
from docprod.api.errors import map_product_error
from docprod.api.schemas import (
    CastBody,
    CharacterView,
    FriendRequestBody,
    FriendshipView,
    PersonaCreate,
    PersonaView,
    ProfilePatch,
    ProjectSummaryView,
    SeriesView,
    UserView,
    VoiceProfileView,
)
from docprod.product import social_ops
from docprod.product.errors import NotFoundError, ProductError
from docprod.product.models import Character, Persona, TelegramUser
from docprod.product.privacy import require_visible_project
from docprod.product.services import ProductService

router = APIRouter(tags=["social"])


def _user_view(user: TelegramUser) -> UserView:
    return UserView(
        id=user.id,
        telegram_user_id=user.telegram_user_id,
        username=user.username,
        first_name=user.first_name,
        language_code=user.language_code,
        display_name=user.display_name,
        bio=user.bio,
        default_traits=user.default_traits,
        allow_friends_to_cast_me=user.allow_friends_to_cast_me,
    )


def _persona_view(persona: Persona) -> PersonaView:
    return PersonaView(
        id=persona.id,
        owner_user_id=persona.owner_user_id,
        name=persona.name,
        display_name=persona.display_name,
        description=persona.description,
        personality_traits=persona.personality_traits,
        role_archetype=persona.role_archetype,
        kind=persona.kind,
        linked_user_id=persona.linked_user_id,
        locked_identity=persona.locked_identity,
        external_ref_path=persona.external_ref_path,
    )


def _character_view(character: Character) -> CharacterView:
    return CharacterView(
        id=character.id,
        project_id=character.project_id,
        name=character.name,
        description=character.description,
        locked_identity=character.locked_identity,
        primary_reference_id=character.primary_reference_id,
        display_name=character.display_name,
        personality_traits=character.personality_traits,
        role_archetype=character.role_archetype,
        kind=character.kind,
        linked_user_id=character.linked_user_id,
        voice_profile_id=character.voice_profile_id,
    )


@router.get("/me", response_model=UserView, operation_id="getMe")
def get_me(user: TelegramUser = Depends(current_user)) -> UserView:
    return _user_view(user)


@router.patch("/me", response_model=UserView, operation_id="patchMe")
def patch_me(
    body: ProfilePatch,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> UserView:
    try:
        updated = social_ops.update_profile(service, user, **body.model_dump(exclude_none=True))
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _user_view(updated)


@router.get("/users/{user_id}", response_model=UserView, operation_id="getProfile")
def get_profile(
    user_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> UserView:
    target = service.repo.users.get(user_id)
    if target is None:
        raise map_product_error(NotFoundError("user not found"))
    return _user_view(target)


@router.get(
    "/users/{user_id}/videos",
    response_model=list[ProjectSummaryView],
    operation_id="profileVideos",
)
def profile_videos(
    user_id: str,
    with_me: bool = Query(False),
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> list[ProjectSummaryView]:
    from docprod.api.routes.projects import _summary

    rows = social_ops.visible_projects_for_profile(service, user, user_id, with_me=with_me)
    return [_summary(service, p) for p in rows]


@router.post("/friends/requests", response_model=FriendshipView, operation_id="requestFriend")
def request_friend(
    body: FriendRequestBody,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> FriendshipView:
    try:
        row = social_ops.request_friend(service, user, username=body.username, user_id=body.user_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return FriendshipView(
        id=row.id,
        requester_id=row.requester_id,
        addressee_id=row.addressee_id,
        status=row.status,
    )


@router.post("/friends/requests/{friendship_id}/accept", response_model=FriendshipView)
def accept_friend(
    friendship_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> FriendshipView:
    try:
        row = social_ops.respond_friend(service, user, friendship_id, accept=True)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return FriendshipView(
        id=row.id, requester_id=row.requester_id, addressee_id=row.addressee_id, status=row.status
    )


@router.post("/friends/requests/{friendship_id}/decline", response_model=FriendshipView)
def decline_friend(
    friendship_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> FriendshipView:
    try:
        row = social_ops.respond_friend(service, user, friendship_id, accept=False)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return FriendshipView(
        id=row.id, requester_id=row.requester_id, addressee_id=row.addressee_id, status=row.status
    )


@router.get("/friends", response_model=list[UserView], operation_id="listFriends")
def list_friends(
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> list[UserView]:
    return [_user_view(row) for row in social_ops.list_friends(service, user)]


@router.delete("/friends/{other_id}", operation_id="removeFriend")
def remove_friend(
    other_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict[str, str]:
    try:
        social_ops.remove_friend(service, user, other_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return {"status": "removed"}


@router.get("/personas", response_model=list[PersonaView], operation_id="listPersonas")
def list_personas(
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> list[PersonaView]:
    return [_persona_view(p) for p in service.repo.personas_for(user.id)]


@router.post("/personas", response_model=PersonaView, operation_id="createPersona")
def create_persona(
    body: PersonaCreate,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> PersonaView:
    persona = social_ops.create_persona(service, user, **body.model_dump())
    return _persona_view(persona)


@router.post(
    "/projects/{project_id}/cast",
    response_model=CharacterView,
    operation_id="castToProject",
)
def cast_to_project(
    project_id: str,
    body: CastBody,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> CharacterView:
    try:
        if body.friend_user_id:
            character = social_ops.cast_friend_to_project(
                service, user, project_id, body.friend_user_id
            )
        elif body.persona_id:
            persona = service.repo.personas.get(body.persona_id)
            if persona is None or persona.owner_user_id != user.id:
                raise ProductError("persona not found")
            character = social_ops.snapshot_persona_to_project(service, user, project_id, persona)
        else:
            raise ProductError("persona_id or friend_user_id required")
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _character_view(character)


@router.post(
    "/projects/{project_id}/voices/assign",
    response_model=list[VoiceProfileView],
    operation_id="assignVoices",
)
def assign_voices(
    project_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> list[VoiceProfileView]:
    try:
        service._require_project(user.id, project_id)
        social_ops.ensure_character_voices(service, user, project_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    rows = []
    for character in service.repo.characters_for(project_id):
        if not character.voice_profile_id:
            continue
        profile = service.repo.voice_profiles[character.voice_profile_id]
        rows.append(
            VoiceProfileView(
                id=profile.id,
                provider=profile.provider,
                voice_id=profile.voice_id,
                display_name=profile.display_name,
                language=profile.language,
            )
        )
    return rows


@router.post("/series/birko/foundation", response_model=SeriesView, operation_id="birkoFoundation")
def birko_foundation(
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> SeriesView:
    seeded = social_ops.seed_birko_foundation(service, user)
    series = seeded["series"]
    episode = seeded["episode"]
    return SeriesView(
        id=series.id,
        slug=series.slug,
        title=series.title,
        description=series.description,
        episode_id=episode.id,
    )


@router.get(
    "/projects/{project_id}/public",
    response_model=ProjectSummaryView,
    operation_id="getVisibleProject",
)
def get_visible_project(
    project_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> ProjectSummaryView:
    from docprod.api.routes.projects import _summary

    try:
        project = require_visible_project(service.repo, user, project_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _summary(service, project, detail=True)
