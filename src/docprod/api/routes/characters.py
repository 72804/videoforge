from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from docprod.api.dependencies import current_user, get_service
from docprod.api.errors import map_product_error
from docprod.api.schemas import (
    CharacterCreate,
    CharacterPatch,
    CharacterReferenceView,
    CharacterView,
)
from docprod.product.enums import ReferenceMode
from docprod.product.errors import NotFoundError, ProductError
from docprod.product.models import Character, TelegramUser
from docprod.product.services import ProductService
from docprod.product.uploads import validate_image_bytes

router = APIRouter(tags=["characters"])


def _view(character: Character) -> CharacterView:
    return CharacterView(
        id=character.id,
        project_id=character.project_id,
        name=character.name,
        description=character.description,
        locked_identity=character.locked_identity,
        primary_reference_id=character.primary_reference_id,
    )


@router.post(
    "/projects/{project_id}/characters",
    response_model=CharacterView,
    operation_id="createCharacter",
)
def create_character(
    project_id: str,
    body: CharacterCreate,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> CharacterView:
    try:
        character = service.add_character(
            user.id,
            project_id,
            name=body.name,
            description=body.description,
        )
        if body.locked_identity:
            character = service.update_character(
                user.id, character.id, locked_identity=True
            )
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _view(character)


@router.get(
    "/projects/{project_id}/characters",
    response_model=list[CharacterView],
    operation_id="listCharacters",
)
def list_characters(
    project_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> list[CharacterView]:
    try:
        service._require_project(user.id, project_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return [_view(c) for c in service.repo.characters_for(project_id)]


@router.get(
    "/characters/{character_id}",
    response_model=CharacterView,
    operation_id="getCharacter",
)
def get_character(
    character_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> CharacterView:
    try:
        character = service._require_character(user.id, character_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _view(character)


@router.patch(
    "/characters/{character_id}",
    response_model=CharacterView,
    operation_id="patchCharacter",
)
def patch_character(
    character_id: str,
    body: CharacterPatch,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> CharacterView:
    try:
        character = service.update_character(
            user.id, character_id, **body.model_dump(exclude_none=True)
        )
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return _view(character)


@router.delete("/characters/{character_id}", operation_id="deleteCharacter")
def delete_character(
    character_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict[str, str]:
    try:
        service.delete_character(user.id, character_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return {"status": "deleted"}


@router.post(
    "/characters/{character_id}/references",
    response_model=CharacterReferenceView,
    operation_id="uploadCharacterReference",
)
async def upload_reference(
    character_id: str,
    file: UploadFile = File(...),
    role: str = Form("primary"),
    make_primary: bool = Form(True),
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> CharacterReferenceView:
    payload = await file.read()
    try:
        width, height, mime = validate_image_bytes(
            payload,
            max_bytes=service.limits.max_upload_bytes,
            declared_mime=file.content_type or "",
        )
        ref = service.add_character_reference(
            user.id,
            character_id,
            payload,
            mode=ReferenceMode.CUSTOM,
            primary=make_primary,
            role=role,
            width=width,
            height=height,
            mime=mime,
        )
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return CharacterReferenceView(
        id=ref.id,
        character_id=ref.character_id,
        sha256=ref.sha256,
        role=ref.role,
        primary=ref.primary,
        width=ref.width,
        height=ref.height,
        mime=ref.mime,
    )


@router.get("/characters/{character_id}/photo", operation_id="getCharacterPhoto")
def character_photo(
    character_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> Response:
    try:
        character = service._require_character(user.id, character_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    ref_id = character.primary_reference_id
    if not ref_id:
        raise map_product_error(NotFoundError("photo not found"))
    ref = service.repo.references.get(ref_id)
    if ref is None:
        raise map_product_error(NotFoundError("photo not found"))
    try:
        data = service.storage.get_bytes(ref.storage_key)
    except (FileNotFoundError, KeyError) as exc:
        raise map_product_error(NotFoundError("photo not found")) from exc
    return Response(content=data, media_type=ref.mime or "image/jpeg")
