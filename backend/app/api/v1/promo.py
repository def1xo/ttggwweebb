from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_user, role_value
from app.db import models

router = APIRouter(tags=["promo"])


class PromoApplyIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    total: Optional[Decimal] = None  # optional order subtotal for discount calculation


class PromoApplyOut(BaseModel):
    found: bool
    code: str
    discount: float = 0.0
    currency: str = "RUB"
    kind: str = "none"  # promo_code | user_referral
    owner_role: Optional[str] = None
    owner_user_id: Optional[int] = None


def _normalize(code: str) -> str:
    return (code or "").strip()


@router.post("/promo/apply", response_model=PromoApplyOut)
@router.post("/promos/apply", response_model=PromoApplyOut)
def apply_promo(
    payload: PromoApplyIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    code = _normalize(payload.code)
    if not code:
        raise HTTPException(status_code=400, detail="Promo code required")

    # 1) Try explicit promo_codes table (admin-created / discount codes).
    promo = (
        db.query(models.PromoCode)
        .filter(func.lower(models.PromoCode.code) == func.lower(code))
        .one_or_none()
    )
    if promo is not None:
        # basic validity checks
        if promo.expires_at is not None and promo.expires_at < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Promo code expired")
        if promo.usage_limit is not None and promo.used_count is not None and promo.used_count >= promo.usage_limit:
            raise HTTPException(status_code=400, detail="Promo code usage limit reached")

        discount_val = Decimal(str(getattr(promo, "value", 0) or 0))
        total = payload.total
        if total is not None:
            try:
                total = Decimal(str(total))
            except Exception:
                total = None
        # Treat promo.value as *flat* discount amount (money).
        if total is not None and discount_val > total:
            discount_val = total
        return PromoApplyOut(
            found=True,
            code=code,
            discount=float(discount_val or 0),
            currency=getattr(promo, "currency", "RUB") or "RUB",
            kind="promo_code",
            owner_role=str(getattr(promo, "type", "promo")),
            owner_user_id=None,
        )

    # 2) Try manager/assistant/admin referral promo code stored on users.
    owner = (
        db.query(models.User)
        .filter(models.User.promo_code.isnot(None))
        .filter(func.lower(models.User.promo_code) == func.lower(code))
        .one_or_none()
    )
    if owner is not None:
        return PromoApplyOut(
            found=True,
            code=code,
            discount=0.0,
            currency="RUB",
            kind="user_referral",
            owner_role=role_value(getattr(owner, "role", None)),
            owner_user_id=int(owner.id),
        )

    raise HTTPException(status_code=404, detail="Промокод не найден")
