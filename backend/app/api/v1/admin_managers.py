from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin_user, get_db
from app.db import models

router = APIRouter(tags=["admin_managers"])


def _as_float(v: Any) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _user_row(u: models.User) -> Dict[str, Any]:
    return {
        "id": u.id,
        "telegram_id": u.telegram_id,
        "username": u.username,
        "first_name": u.first_name,
        "role": str(getattr(u, "role", "user")),
        "balance": _as_float(getattr(u, "balance", 0)),
    }


@router.get("/managers")
def list_managers(
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    rows = (
        db.query(models.User)
        .filter(models.User.role.in_([models.UserRole.manager, models.UserRole.assistant, models.UserRole.admin]))
        .order_by(models.User.id.asc())
        .all()
    )
    return {"managers": [_user_row(u) for u in rows]}


@router.post("/managers")
def add_manager(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    user_id = payload.get("user_id")
    telegram_id = payload.get("telegram_id")

    user: Optional[models.User] = None
    if user_id is not None:
        try:
            user = db.query(models.User).get(int(user_id))
        except Exception:
            user = None

    if user is None and telegram_id is not None:
        try:
            user = db.query(models.User).filter(models.User.telegram_id == int(telegram_id)).first()
        except Exception:
            user = None

    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    user.role = models.UserRole.manager
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_row(user)


@router.patch("/managers/{manager_id}")
def patch_manager(
    manager_id: int = Path(...),
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    user = db.query(models.User).get(manager_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    if "role" in payload and payload.get("role") is not None:
        role = str(payload.get("role")).strip().lower()
        if role not in ("user", "manager", "assistant", "admin"):
            raise HTTPException(status_code=400, detail="invalid role")
        user.role = getattr(models.UserRole, role)

    if "balance" in payload and payload.get("balance") is not None:
        try:
            user.balance = Decimal(str(payload.get("balance")))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid balance")

    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_row(user)


@router.delete("/managers/{manager_id}")
def delete_manager(
    manager_id: int = Path(...),
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    user = db.query(models.User).get(manager_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    user.role = models.UserRole.user
    db.add(user)
    db.commit()
    return {"ok": True, "id": manager_id}
