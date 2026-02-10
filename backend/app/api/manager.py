# backend/app/api/manager.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from decimal import Decimal, InvalidOperation
from typing import List
import logging
from datetime import datetime

from app.api.dependencies import get_db, get_current_manager_user
from app.db import models

logger = logging.getLogger("manager_api")
router = APIRouter(prefix="/api/manager", tags=["manager"])

def _to_decimal(v) -> Decimal:
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid amount")

@router.get("/assistants_balances")
def assistants_balances(db: Session = Depends(get_db), current_manager = Depends(get_current_manager_user)):
    """
    Return assistants list for this manager and their balances.
    Implementation assumes Assistant model links to Manager via manager_id -> Managers table,
    and Manager has user_id referencing User.
    """
    # find manager row
    mgr_row = db.query(models.Manager).filter(models.Manager.user_id == current_manager.id).one_or_none()
    if not mgr_row:
        raise HTTPException(status_code=404, detail="Manager profile not found")

    # find assistants linked to this manager
    assistants = db.query(models.Assistant).filter(models.Assistant.manager_id == mgr_row.id).all()
    result = []
    total_assistants_balance = Decimal("0.00")
    for a in assistants:
        user = db.query(models.User).get(a.user_id)
        if not user:
            continue
        bal = Decimal(str(user.balance or 0))
        total_assistants_balance += bal
        result.append({
            "id": user.id,
            "username": getattr(user, "username", None),
            "full_name": getattr(user, "full_name", None) or getattr(user, "username", None),
            "balance": float(bal),
        })

    return {"manager_id": current_manager.id, "assistants": result, "total_assistants_balance": float(total_assistants_balance)}

@router.post("/pay_assistant")
def pay_assistant(assistant_id: int, amount: float, db: Session = Depends(get_db), current_manager = Depends(get_current_manager_user)):
    """
    Manager manually transfers funds to assistant.
    This is an immediate transfer: debit manager.balance and credit assistant.balance.
    Records a Payment row if model exists.
    """
    dec_amount = _to_decimal(amount)
    if dec_amount <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Amount must be > 0")

    # find manager profile row
    mgr_row = db.query(models.Manager).filter(models.Manager.user_id == current_manager.id).one_or_none()
    if not mgr_row:
        raise HTTPException(status_code=404, detail="Manager profile not found")

    # check assistant exists and linked to this manager
    assistant_row = db.query(models.Assistant).filter(models.Assistant.user_id == assistant_id, models.Assistant.manager_id == mgr_row.id).one_or_none()
    if not assistant_row:
        raise HTTPException(status_code=404, detail="Assistant not found or not linked to you")

    # load User rows with FOR UPDATE semantics if DB supports it
    manager_user = db.query(models.User).filter(models.User.id == current_manager.id).with_for_update().one()
    assistant_user = db.query(models.User).filter(models.User.id == assistant_id).with_for_update().one()

    manager_user.balance = (manager_user.balance or Decimal("0.00"))
    assistant_user.balance = (assistant_user.balance or Decimal("0.00"))

    if manager_user.balance < dec_amount:
        raise HTTPException(status_code=400, detail="Insufficient manager balance")

    manager_user.balance = manager_user.balance - dec_amount
    assistant_user.balance = assistant_user.balance + dec_amount

    # create Payment record if model exists
    try:
        if hasattr(models, "Payment"):
            p = models.Payment(manager_id=mgr_row.id, assistant_id=assistant_row.id, amount=dec_amount, note=f"Payout from manager {current_manager.id}", created_at=datetime.utcnow())
            db.add(p)
    except Exception:
        logger.exception("Failed to create Payment record, continuing")

    db.add(manager_user)
    db.add(assistant_user)
    db.commit()
    db.refresh(manager_user)
    db.refresh(assistant_user)

    return {"status": "ok", "manager_balance": float(manager_user.balance), "assistant_balance": float(assistant_user.balance)}
