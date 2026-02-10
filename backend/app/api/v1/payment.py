from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_user, get_current_admin_user
from app.db import models


router = APIRouter(tags=["payment"])


class PaymentRequisitesOut(BaseModel):
    recipient_name: Optional[str] = None
    phone: Optional[str] = None
    card_number: Optional[str] = None
    bank_name: Optional[str] = None
    note: Optional[str] = None
    updated_at: Optional[datetime] = None


class PaymentSettingsPatchIn(BaseModel):
    recipient_name: Optional[str] = None
    phone: Optional[str] = None
    card_number: Optional[str] = None
    bank_name: Optional[str] = None
    note: Optional[str] = None


def _get_or_create_singleton(db: Session) -> models.PaymentSettings:
    ps = db.query(models.PaymentSettings).filter(models.PaymentSettings.id == 1).one_or_none()
    if not ps:
        ps = models.PaymentSettings(id=1)
        db.add(ps)
        db.flush()
    return ps


@router.get("/payment/requisites", response_model=PaymentRequisitesOut)
def get_requisites(
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    ps = _get_or_create_singleton(db)
    db.commit()
    return PaymentRequisitesOut(
        recipient_name=ps.recipient_name,
        phone=ps.phone,
        card_number=ps.card_number,
        bank_name=ps.bank_name,
        note=ps.note,
        updated_at=ps.updated_at,
    )


@router.get("/admin/payment-settings", response_model=PaymentRequisitesOut)
def admin_get_payment_settings(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_current_admin_user),
):
    ps = _get_or_create_singleton(db)
    db.commit()
    return PaymentRequisitesOut(
        recipient_name=ps.recipient_name,
        phone=ps.phone,
        card_number=ps.card_number,
        bank_name=ps.bank_name,
        note=ps.note,
        updated_at=ps.updated_at,
    )


@router.patch("/admin/payment-settings", response_model=PaymentRequisitesOut)
def admin_patch_payment_settings(
    payload: PaymentSettingsPatchIn,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_current_admin_user),
):
    ps = _get_or_create_singleton(db)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="no fields to update")
    for k, v in data.items():
        setattr(ps, k, v)
    db.add(ps)
    db.commit()
    db.refresh(ps)
    return PaymentRequisitesOut(
        recipient_name=ps.recipient_name,
        phone=ps.phone,
        card_number=ps.card_number,
        bank_name=ps.bank_name,
        note=ps.note,
        updated_at=ps.updated_at,
    )
