from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from docprod.api.dependencies import current_user, get_ctx, get_service, run_queued_job
from docprod.api.errors import map_product_error
from docprod.api.idempotency import lookup, remember
from docprod.api.schemas import (
    GenerateRequest,
    JobAccepted,
    ReorderRequest,
    ScenePatch,
    SceneSummaryView,
)
from docprod.product.errors import ProductError
from docprod.product.invalidation import InvalidationEvent, effects_for
from docprod.product.models import Scene, TelegramUser
from docprod.product.services import ProductService

router = APIRouter(tags=["scenes"])


def _version_number(service: ProductService, scene: Scene) -> int:
    return sum(1 for v in service.repo.scene_versions.values() if v.scene_id == scene.id)


def _summary(service: ProductService, scene: Scene) -> SceneSummaryView:
    version = service._active_version(scene)
    stale = "stale" if version.image_stale or version.video_stale else "ready"
    return SceneSummaryView(
        id=scene.id,
        order_index=scene.order_index,
        duration_seconds=version.duration_seconds,
        characters=list(version.character_ids),
        status=stale,
        production_class=version.production_class,
        image_model=version.image_model,
        video_model=version.video_model,
        locked=scene.locked,
        version_number=_version_number(service, scene),
        estimated_regeneration_stars=service.pricing.stars_for_usd(0.45),
        image_asset_version_id=version.image_asset_version_id,
        video_asset_version_id=version.video_asset_version_id,
        visual_prompt=version.visual_prompt,
        motion_prompt=version.motion_prompt,
    )


@router.get(
    "/projects/{project_id}/scenes",
    response_model=list[SceneSummaryView],
    operation_id="listScenes",
)
def list_scenes(
    project_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> list[SceneSummaryView]:
    try:
        service._require_project(user.id, project_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return [_summary(service, s) for s in service.repo.scenes_for(project_id)]


@router.get("/scenes/{scene_id}", operation_id="getScene")
def get_scene(
    scene_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict:
    try:
        scene = service._require_scene(user.id, scene_id)
        version = service._active_version(scene)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    versions = [
        v.model_dump(mode="json")
        for v in service.repo.scene_versions.values()
        if v.scene_id == scene.id
    ]
    assets = [
        av.model_dump(mode="json")
        for av in service.repo.asset_versions.values()
        if service.repo.assets[av.asset_id].scene_id == scene.id
    ]
    return {
        "scene": {"id": scene.id, "locked": scene.locked, "order_index": scene.order_index},
        "active_version": version.model_dump(mode="json"),
        "versions": versions,
        "assets": assets,
    }


@router.patch("/scenes/{scene_id}", operation_id="patchScene")
def patch_scene(
    scene_id: str,
    body: ScenePatch,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict:
    fields = body.model_dump(exclude_none=True)
    event = None
    if "visual_prompt" in fields:
        event = InvalidationEvent.SCENE_VISUAL_PROMPT_CHANGED
    elif "motion_prompt" in fields:
        event = InvalidationEvent.SCENE_MOTION_PROMPT_CHANGED
    elif "duration_seconds" in fields:
        event = InvalidationEvent.SCENE_DURATION_CHANGED
    elif "character_ids" in fields:
        event = InvalidationEvent.SCENE_CHARACTERS_CHANGED
    elif "image_model" in fields:
        event = InvalidationEvent.SCENE_IMAGE_MODEL_CHANGED
    elif "video_model" in fields:
        event = InvalidationEvent.SCENE_VIDEO_MODEL_CHANGED
    flags = effects_for(event) if event else {"image": False, "video": False, "render": True}
    try:
        version = service.edit_scene(user.id, scene_id, **fields)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    invalidated = [name for name, stale in flags.items() if stale]
    return {"scene_version": version.model_dump(mode="json"), "invalidated": invalidated}


@router.post(
    "/projects/{project_id}/scenes/reorder",
    operation_id="reorderScenes",
)
def reorder_scenes(
    project_id: str,
    body: ReorderRequest,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict:
    try:
        service.reorder_scenes(user.id, project_id, body.scene_ids)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return {"invalidated": ["render"]}


@router.post("/scenes/{scene_id}/lock", operation_id="lockScene")
def lock_scene(
    scene_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict:
    try:
        scene = service.lock_scene(user.id, scene_id, True)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return {"id": scene.id, "locked": scene.locked}


@router.post("/scenes/{scene_id}/unlock", operation_id="unlockScene")
def unlock_scene(
    scene_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict:
    try:
        scene = service.lock_scene(user.id, scene_id, False)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return {"id": scene.id, "locked": scene.locked}


@router.get("/scenes/{scene_id}/versions", operation_id="listSceneVersions")
def list_versions(
    scene_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict:
    try:
        scene = service._require_scene(user.id, scene_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    versions = [
        v.model_dump(mode="json")
        for v in service.repo.scene_versions.values()
        if v.scene_id == scene.id
    ]
    return {"active_version_id": scene.active_version_id, "versions": versions}


@router.post("/scenes/{scene_id}/restore/{version_id}", operation_id="restoreSceneVersion")
def restore_version(
    scene_id: str,
    version_id: str,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> dict:
    try:
        scene = service.restore_scene_version(user.id, scene_id, version_id)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    return {"active_version_id": scene.active_version_id}


def _regen(
    *,
    request: Request,
    user: TelegramUser,
    service: ProductService,
    body: GenerateRequest,
    kind: str,
    scene_id: str,
    action: str,
    idempotency_key: str | None,
) -> JobAccepted:
    payload = {**body.model_dump(), "kind": kind, "scene_id": scene_id}
    try:
        hit = lookup(
            service, user_id=user.id, action=action, key=idempotency_key, payload=payload
        )
        if hit:
            return JobAccepted.model_validate(hit.body)
        scene = service._require_scene(user.id, scene_id)
        job = service.queue_generation(
            user.id, scene.project_id, body.quote_id, kind=kind, scene_id=scene_id
        )
        job = run_queued_job(get_ctx(request), job)
    except ProductError as exc:
        raise map_product_error(exc) from exc
    accepted = JobAccepted(job_id=job.id, status=job.status.value)
    remember(
        service,
        user_id=user.id,
        action=action,
        key=idempotency_key,
        payload=payload,
        status_code=202,
        body=accepted.model_dump(),
    )
    return accepted


@router.post(
    "/scenes/{scene_id}/regenerate-image",
    status_code=202,
    response_model=JobAccepted,
    operation_id="regenerateSceneImage",
)
def regenerate_image(
    scene_id: str,
    body: GenerateRequest,
    request: Request,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobAccepted:
    return _regen(
        request=request,
        user=user,
        service=service,
        body=body,
        kind="scene_image",
        scene_id=scene_id,
        action="regenerate-image",
        idempotency_key=idempotency_key,
    )


@router.post(
    "/scenes/{scene_id}/regenerate-video",
    status_code=202,
    response_model=JobAccepted,
    operation_id="regenerateSceneVideo",
)
def regenerate_video(
    scene_id: str,
    body: GenerateRequest,
    request: Request,
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobAccepted:
    return _regen(
        request=request,
        user=user,
        service=service,
        body=body,
        kind="scene_video",
        scene_id=scene_id,
        action="regenerate-video",
        idempotency_key=idempotency_key,
    )
