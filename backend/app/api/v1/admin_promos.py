from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models


router = APIRouter(tags=["admin_promos"])


class PromoOut(BaseModel):
    id: int
    code: str
    value: float
    currency: str = "RUB"
    expires_at: Optional[datetime] = None
    usage_limit: Optional[int] = None
    used_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PromoCreateIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    # Value can be percent (10) or fraction (0.10)
    value: float = Field(..., ge=0)
    currency: str = Field(default="RUB", max_length=8)
    expires_at: Optional[datetime] = None
    usage_limit: Optional[int] = Field(default=None, ge=1)


class PromoPatchIn(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    value: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=8)
    expires_at: Optional[datetime] = None
    usage_limit: Optional[int] = Field(default=None, ge=1)


@router.get("/promos", response_model=List[PromoOut])
def list_special_promos(
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_current_admin_user),
):
    query = db.query(models.PromoCode).filter(models.PromoCode.type == models.PromoType.special)
    if q:
        query = query.filter(func.lower(models.PromoCode.code).like(f"%{q.lower()}%"))
    items = query.order_by(models.PromoCode.created_at.desc()).all()
    return [
        PromoOut(
            id=p.id,
            code=p.code,
            value=float(p.value or 0),
            currency=p.currency or "RUB",
            expires_at=p.expires_at,
            usage_limit=p.usage_limit,
            used_count=int(p.used_count or 0),
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in items
    ]


@router.post("/promos", response_model=PromoOut)
def create_special_promo(
    payload: PromoCreateIn,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_current_admin_user),
):
    code = (payload.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code required")
    existing = db.query(models.PromoCode).filter(func.lower(models.PromoCode.code) == func.lower(code)).one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="promo code already exists")
    pc = models.PromoCode(
        code=code,
        type=models.PromoType.special,
        value=payload.value,
        currency=payload.currency or "RUB",
        expires_at=payload.expires_at,
        usage_limit=payload.usage_limit,
    )
    db.add(pc)
    db.commit()
    db.refresh(pc)
    return PromoOut(
        id=pc.id,
        code=pc.code,
        value=float(pc.value or 0),
        currency=pc.currency or "RUB",
        expires_at=pc.expires_at,
        usage_limit=pc.usage_limit,
        used_count=int(pc.used_count or 0),
        created_at=pc.created_at,
        updated_at=pc.updated_at,
    )


@router.patch("/promos/{promo_id}", response_model=PromoOut)
def patch_special_promo(
    promo_id: int = Path(..., ge=1),
    payload: PromoPatchIn = None,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_current_admin_user),
):
    pc = db.query(models.PromoCode).get(promo_id)
    if not pc or pc.type != models.PromoType.special:
        raise HTTPException(status_code=404, detail="promo not found")
    data = (payload or PromoPatchIn()).model_dump(exclude_unset=True)
    if "code" in data:
        code = (data["code"] or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="code required")
        exists = db.query(models.PromoCode).filter(func.lower(models.PromoCode.code) == func.lower(code), models.PromoCode.id != pc.id).one_or_none()
        if exists:
            raise HTTPException(status_code=400, detail="promo code already exists")
        pc.code = code
    for k in ("value", "currency", "expires_at", "usage_limit"):
        if k in data:
            setattr(pc, k, data[k])
    db.add(pc)
    db.commit()
    db.refresh(pc)
    return PromoOut(
        id=pc.id,
        code=pc.code,
        value=float(pc.value or 0),
        currency=pc.currency or "RUB",
        expires_at=pc.expires_at,
        usage_limit=pc.usage_limit,
        used_count=int(pc.used_count or 0),
        created_at=pc.created_at,
        updated_at=pc.updated_at,
    )


@router.delete("/promos/{promo_id}")
def delete_special_promo(
    promo_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_current_admin_user),
):
    pc = db.query(models.PromoCode).get(promo_id)
    if not pc or pc.type != models.PromoType.special:
        raise HTTPException(status_code=404, detail="promo not found")
    db.delete(pc)
    db.commit()
    return {"ok": True, "id": promo_id}
