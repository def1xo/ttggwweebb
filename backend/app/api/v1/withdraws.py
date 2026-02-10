
from decimal import Decimal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Form, Body
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_user, get_current_admin_user, role_value
from app.db import models

router = APIRouter(tags=["withdraws"])


def _move_to_hold(db: Session, user: models.User, amount: Decimal):
    """Atomically move funds from available balance to hold."""
    u = db.query(models.User).filter(models.User.id == user.id).with_for_update().one()
    avail = Decimal(str(u.balance or 0))
    hold = Decimal(str(getattr(u, "balance_hold", 0) or 0))
    if avail < amount:
        raise HTTPException(400, detail="insufficient balance")
    u.balance = (avail - amount).quantize(Decimal("0.01"))
    u.balance_hold = (hold + amount).quantize(Decimal("0.01"))
    db.add(u)
    return u


def _release_hold(db: Session, user_id: int, amount: Decimal, to_available: bool):
    u = db.query(models.User).filter(models.User.id == user_id).with_for_update().one()
    avail = Decimal(str(u.balance or 0))
    hold = Decimal(str(getattr(u, "balance_hold", 0) or 0))
    if hold < amount:
        # safeguard against broken state
        raise HTTPException(409, detail="insufficient hold")
    u.balance_hold = (hold - amount).quantize(Decimal("0.01"))
    if to_available:
        u.balance = (avail + amount).quantize(Decimal("0.01"))
    db.add(u)
    return u


def _dec(s: str) -> Decimal:
    try:
        return Decimal(str(s).replace(",", ".")).quantize(Decimal("0.01"))
    except Exception:
        raise HTTPException(400, detail="invalid amount")


@router.get("/manager/withdraws")
@router.get("/withdraws/my")
def my_withdraws(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if role_value(user.role) not in ("manager", "assistant", "admin"):
        raise HTTPException(403, detail="forbidden")
    q = (
        db.query(models.WithdrawRequest)
        .filter(models.WithdrawRequest.requester_user_id == user.id)
        .order_by(models.WithdrawRequest.created_at.desc())
        .all()
    )
    return {
        "balance": float(user.balance or 0),
        "balance_hold": float(getattr(user, "balance_hold", 0) or 0),
        "items": [
            {
                "id": w.id,
                "amount": float(w.amount or 0),
                "currency": w.currency,
                "status": w.status,
                "created_at": w.created_at.isoformat() if w.created_at else None,
                "target_details": w.target_details,
            }
            for w in q
        ],
    }


@router.post("/manager/request_withdrawal")
@router.post("/manager/withdraws")
def manager_request_withdrawal(
    amount: str | None = Form(None),
    target_details: str | None = Form(None),
    body: dict | None = Body(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if role_value(user.role) not in ("manager", "admin"):
        raise HTTPException(403, detail="manager required")

    if body:
        a = _dec(body.get("amount"))
        td = body.get("target_details")
    else:
        a = _dec(amount)
        td = {"raw": target_details}
    if a <= 0:
        raise HTTPException(400, detail="invalid amount")

    # списываем сразу -> hold
    _move_to_hold(db, user, a)

    w = models.WithdrawRequest(
        requester_user_id=user.id,
        manager_user_id=user.id,
        amount=a,
        currency="RUB",
        target_details=td,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return {"ok": True, "withdraw_id": w.id, "balance": float(user.balance or 0), "balance_hold": float(getattr(user, "balance_hold", 0) or 0)}


@router.post("/assistant/request_withdraw")
@router.post("/assistant/withdraws")
def assistant_request_withdraw(
    amount: str | None = Form(None),
    target_details: str | None = Form(None),
    body: dict | None = Body(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if role_value(user.role) != "assistant":
        raise HTTPException(403, detail="assistant required")
    a = _dec(body.get("amount") if body else amount)
    if a <= 0:
        raise HTTPException(400, detail="invalid amount")
    # списываем сразу -> hold
    _move_to_hold(db, user, a)

    manager_user_id = getattr(user, "manager_id", None)
    if not manager_user_id:
        raise HTTPException(400, detail="no manager assigned")

    w = models.WithdrawRequest(
        requester_user_id=user.id,
        manager_user_id=manager_user_id,
        amount=a,
        currency="RUB",
        target_details=body.get("target_details") if body else {"raw": target_details},
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return {"ok": True, "withdraw_id": w.id, "balance": float(user.balance or 0), "balance_hold": float(getattr(user, "balance_hold", 0) or 0)}


@router.get("/admin/withdraws")
def admin_withdraws(db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    q = db.query(models.WithdrawRequest).order_by(models.WithdrawRequest.created_at.desc()).all()
    return {"items": [{
        "id": w.id,
        "requester_user_id": w.requester_user_id,
        "manager_user_id": w.manager_user_id,
        "amount": float(w.amount or 0),
        "currency": w.currency,
        "status": w.status,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "target_details": w.target_details,
    } for w in q]}


@router.post("/admin/approve_withdrawal/{withdraw_id}")
def admin_approve_withdrawal(withdraw_id: int, body: dict = Body(...), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    approve = bool(body.get("approve", True))
    w = db.query(models.WithdrawRequest).get(withdraw_id)
    if not w:
        raise HTTPException(404, detail="not found")
    if w.status != "pending":
        raise HTTPException(409, detail="already processed")

    if approve:
        # hold -> списано окончательно
        _release_hold(db, w.requester_user_id, Decimal(str(w.amount)), to_available=False)
        w.status = "approved"
        w.admin_user_id = admin.id
        w.approved_at = datetime.utcnow()
    else:
        # возврат hold -> available
        _release_hold(db, w.requester_user_id, Decimal(str(w.amount)), to_available=True)
        w.status = "canceled"
        w.admin_user_id = admin.id
        w.approved_at = datetime.utcnow()

    db.add(w)
    db.commit()
    return {"ok": True, "status": w.status}


@router.post("/admin/withdraws/{withdraw_id}/approve")
def admin_approve_alias(withdraw_id: int, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    return admin_approve_withdrawal(withdraw_id, {"approve": True}, db, admin)


@router.post("/admin/withdraws/{withdraw_id}/reject")
def admin_reject_alias(withdraw_id: int, body: dict = Body(None), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    return admin_approve_withdrawal(withdraw_id, {"approve": False, **(body or {})}, db, admin)


@router.post("/admin/withdraws/{withdraw_id}/mark_paid")
def admin_mark_paid(withdraw_id: int, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    w = db.query(models.WithdrawRequest).get(withdraw_id)
    if not w:
        raise HTTPException(404, detail="not found")
    if w.status != "approved":
        raise HTTPException(409, detail="must be approved before mark_paid")
    w.status = "paid"
    w.paid_at = datetime.utcnow()
    w.admin_user_id = admin.id
    db.add(w)
    db.commit()
    return {"ok": True, "status": w.status}
