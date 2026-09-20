from __future__ import annotations

from collections.abc import Callable
from typing import Any

from docprod.db import orm
from docprod.product.ids import new_id
from docprod.product.models import (
    Asset,
    AssetVersion,
    Character,
    CharacterReference,
    GenerationAttempt,
    GenerationJob,
    GenerationPlan,
    GenerationPlanItem,
    IdempotencyRecord,
    NotificationOutbox,
    PaymentIntent,
    Project,
    Render,
    Scene,
    SceneVersion,
    ScriptVersion,
    StarQuote,
    StarTransaction,
    TelegramPayment,
    TelegramUser,
    WorkerHeartbeat,
)


def _dump(model: Any, **rename: str) -> dict[str, Any]:
    data = model.model_dump()
    for src, dest in rename.items():
        data[dest] = data.pop(src)
    for key, value in list(data.items()):
        if hasattr(value, "value"):
            data[key] = value.value
    return data


def user_to_row(user: TelegramUser) -> orm.TelegramUserRow:
    return orm.TelegramUserRow(**user.model_dump())


def row_dict(row: Any) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def user_from_row(row: orm.TelegramUserRow) -> TelegramUser:
    return TelegramUser.model_validate(row_dict(row))


def project_to_row(project: Project) -> orm.ProjectRow:
    return orm.ProjectRow(**_dump(project))


def project_from_row(row: orm.ProjectRow) -> Project:
    return Project.model_validate(row_dict(row))


def character_to_row(character: Character) -> orm.CharacterRow:
    return orm.CharacterRow(**character.model_dump())


def character_from_row(row: orm.CharacterRow) -> Character:
    return Character.model_validate(row_dict(row))


def reference_to_row(ref: CharacterReference) -> orm.CharacterReferenceRow:
    return orm.CharacterReferenceRow(**_dump(ref, primary="primary_flag"))


def reference_from_row(row: orm.CharacterReferenceRow) -> CharacterReference:
    data = row_dict(row)
    data["primary"] = data.pop("primary_flag")
    return CharacterReference.model_validate(data)


def script_to_row(script: ScriptVersion) -> orm.ScriptVersionRow:
    return orm.ScriptVersionRow(**script.model_dump())


def script_from_row(row: orm.ScriptVersionRow) -> ScriptVersion:
    return ScriptVersion.model_validate(row_dict(row))


def scene_to_row(scene: Scene) -> orm.SceneRow:
    return orm.SceneRow(**scene.model_dump())


def scene_from_row(row: orm.SceneRow) -> Scene:
    return Scene.model_validate(row_dict(row))


def scene_version_to_row(version: SceneVersion) -> orm.SceneVersionRow:
    return orm.SceneVersionRow(**version.model_dump())


def scene_version_from_row(row: orm.SceneVersionRow) -> SceneVersion:
    return SceneVersion.model_validate(row_dict(row))


def asset_to_row(asset: Asset) -> orm.AssetRow:
    return orm.AssetRow(**_dump(asset))


def asset_from_row(row: orm.AssetRow) -> Asset:
    return Asset.model_validate(row_dict(row))


def asset_version_to_row(version: AssetVersion) -> orm.AssetVersionRow:
    return orm.AssetVersionRow(**version.model_dump())


def asset_version_from_row(row: orm.AssetVersionRow) -> AssetVersion:
    return AssetVersion.model_validate(row_dict(row))


def plan_to_row(plan: GenerationPlan) -> orm.GenerationPlanRow:
    data = plan.model_dump()
    data["items"] = [item.model_dump(mode="json") for item in plan.items]
    return orm.GenerationPlanRow(**data)


def plan_from_row(row: orm.GenerationPlanRow) -> GenerationPlan:
    payload = row_dict(row)
    payload["items"] = [
        GenerationPlanItem.model_validate(item) for item in (payload["items"] or [])
    ]
    return GenerationPlan.model_validate(payload)


def plan_item_rows(plan: GenerationPlan) -> list[orm.GenerationPlanItemRow]:
    rows = []
    for index, item in enumerate(plan.items):
        rows.append(
            orm.GenerationPlanItemRow(
                id=new_id(),
                plan_id=plan.id,
                position=index,
                type=item.type.value,
                model=item.model,
                quantity=item.quantity,
                estimated_provider_usd=item.estimated_provider_usd,
                customer_stars=item.customer_stars,
                dependencies=item.dependencies,
                scene_id=item.scene_id,
            )
        )
    return rows


def quote_to_row(quote: StarQuote) -> orm.StarQuoteRow:
    return orm.StarQuoteRow(**_dump(quote))


def quote_from_row(row: orm.StarQuoteRow) -> StarQuote:
    return StarQuote.model_validate(row_dict(row))


def job_to_row(job: GenerationJob) -> orm.GenerationJobRow:
    return orm.GenerationJobRow(**_dump(job))


def job_from_row(row: orm.GenerationJobRow) -> GenerationJob:
    return GenerationJob.model_validate(row_dict(row))


def attempt_to_row(attempt: GenerationAttempt) -> orm.GenerationAttemptRow:
    return orm.GenerationAttemptRow(**_dump(attempt))


def attempt_from_row(row: orm.GenerationAttemptRow) -> GenerationAttempt:
    return GenerationAttempt.model_validate(row_dict(row))


def render_to_row(render: Render) -> orm.RenderRow:
    return orm.RenderRow(**render.model_dump())


def render_from_row(row: orm.RenderRow) -> Render:
    return Render.model_validate(row_dict(row))


def txn_to_row(txn: StarTransaction) -> orm.StarTransactionRow:
    return orm.StarTransactionRow(**_dump(txn))


def txn_from_row(row: orm.StarTransactionRow) -> StarTransaction:
    return StarTransaction.model_validate(row_dict(row))


def payment_to_row(payment: TelegramPayment) -> orm.TelegramPaymentRow:
    return orm.TelegramPaymentRow(**_dump(payment))


def payment_from_row(row: orm.TelegramPaymentRow) -> TelegramPayment:
    return TelegramPayment.model_validate(row_dict(row))


def intent_to_row(intent: PaymentIntent) -> orm.PaymentIntentRow:
    return orm.PaymentIntentRow(**_dump(intent))


def intent_from_row(row: orm.PaymentIntentRow) -> PaymentIntent:
    return PaymentIntent.model_validate(row_dict(row))


def outbox_to_row(note: NotificationOutbox) -> orm.NotificationOutboxRow:
    return orm.NotificationOutboxRow(**_dump(note, kind="event_type", attempts="attempt_count"))


def outbox_from_row(row: orm.NotificationOutboxRow) -> NotificationOutbox:
    data = row_dict(row)
    data["kind"] = data.pop("event_type")
    data["attempts"] = data.pop("attempt_count")
    return NotificationOutbox.model_validate(data)


def idem_to_row(record: IdempotencyRecord) -> orm.IdempotencyRecordRow:
    return orm.IdempotencyRecordRow(
        id=record.id,
        user_id=record.user_id,
        action=record.action,
        idempotency_key=record.key,
        request_hash=record.request_hash,
        result_type=record.result_type,
        result_id=record.result_id,
        status_code=record.status_code,
        response_snapshot=record.body,
        created_at=record.created_at,
    )


def idem_from_row(row: orm.IdempotencyRecordRow) -> IdempotencyRecord:
    return IdempotencyRecord(
        id=row.id,
        key=row.idempotency_key,
        user_id=row.user_id,
        action=row.action,
        request_hash=row.request_hash,
        result_type=row.result_type,
        result_id=row.result_id,
        status_code=row.status_code,
        body=row.response_snapshot or {},
        created_at=row.created_at,
    )


def worker_to_row(beat: WorkerHeartbeat) -> orm.WorkerHeartbeatRow:
    return orm.WorkerHeartbeatRow(**beat.model_dump())


def worker_from_row(row: orm.WorkerHeartbeatRow) -> WorkerHeartbeat:
    return WorkerHeartbeat.model_validate(row_dict(row))


FLUSH_ORDER: list[tuple[str, type, Callable[[Any], Any], Callable[[Any], Any]]] = [
    ("users", orm.TelegramUserRow, user_to_row, user_from_row),
    ("projects", orm.ProjectRow, project_to_row, project_from_row),
    ("characters", orm.CharacterRow, character_to_row, character_from_row),
    ("references", orm.CharacterReferenceRow, reference_to_row, reference_from_row),
    ("scripts", orm.ScriptVersionRow, script_to_row, script_from_row),
    ("scenes", orm.SceneRow, scene_to_row, scene_from_row),
    ("scene_versions", orm.SceneVersionRow, scene_version_to_row, scene_version_from_row),
    ("assets", orm.AssetRow, asset_to_row, asset_from_row),
    ("asset_versions", orm.AssetVersionRow, asset_version_to_row, asset_version_from_row),
    ("plans", orm.GenerationPlanRow, plan_to_row, plan_from_row),
    ("quotes", orm.StarQuoteRow, quote_to_row, quote_from_row),
    ("intents", orm.PaymentIntentRow, intent_to_row, intent_from_row),
    ("payments", orm.TelegramPaymentRow, payment_to_row, payment_from_row),
    ("jobs", orm.GenerationJobRow, job_to_row, job_from_row),
    ("attempts", orm.GenerationAttemptRow, attempt_to_row, attempt_from_row),
    ("renders", orm.RenderRow, render_to_row, render_from_row),
    ("transactions", orm.StarTransactionRow, txn_to_row, txn_from_row),
    ("outbox", orm.NotificationOutboxRow, outbox_to_row, outbox_from_row),
    ("idempotency", orm.IdempotencyRecordRow, idem_to_row, idem_from_row),
    ("workers", orm.WorkerHeartbeatRow, worker_to_row, worker_from_row),
]
