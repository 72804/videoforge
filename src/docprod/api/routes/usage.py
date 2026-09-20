from __future__ import annotations

from fastapi import APIRouter, Depends

from docprod.api.dependencies import current_user, get_service
from docprod.api.schemas import UsageTxnView, UsageView
from docprod.product.enums import StarTxnType
from docprod.product.models import TelegramUser
from docprod.product.services import ProductService

router = APIRouter(tags=["usage"])


@router.get("/usage", response_model=UsageView, operation_id="getUsage")
def get_usage(
    user: TelegramUser = Depends(current_user),
    service: ProductService = Depends(get_service),
) -> UsageView:
    txns = [t for t in service.repo.transactions.values() if t.user_id == user.id]
    views = []
    purchased = 0
    debited = 0
    for txn in txns:
        simulated = bool(txn.telegram_payment_id and txn.telegram_payment_id.startswith("sim:"))
        views.append(
            UsageTxnView(
                id=txn.id,
                type=txn.type.value,
                stars=txn.stars,
                simulated=simulated,
                created_at=txn.created_at.isoformat(),
                project_id=txn.project_id,
            )
        )
        if txn.type is StarTxnType.PURCHASE:
            purchased += txn.stars
        if txn.type is StarTxnType.GENERATION_DEBIT:
            debited += txn.stars
    return UsageView(transactions=views, stars_debited=debited, stars_purchased=purchased)
