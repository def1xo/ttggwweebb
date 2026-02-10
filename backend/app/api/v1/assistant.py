from fastapi import APIRouter, Depends, HTTPException, Path, Form
from sqlalchemy.orm import Session
from decimal import Decimal

from app.api.dependencies import get_db, get_current_user, role_value
from app.db import models

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/dashboard")
def assistant_dashboard(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if role_value(current_user.role) != "assistant":
        raise HTTPException(status_code=403, detail="assistant required")

    # commissions for assistant
    comps = db.query(models.Commission).filter(models.Commission.user_id == current_user.id, models.Commission.role == "assistant").order_by(models.Commission.created_at.desc()).all()
    commissions = [{"id": c.id, "order_id": c.order_id, "amount": float(c.amount), "created_at": c.created_at.isoformat(), "paid": getattr(c, "paid", False)} for c in comps]

    # referred users (user_manager_bindings)
    bindings = db.query(models.UserManagerBinding).filter(models.UserManagerBinding.owner_user_id == current_user.id, models.UserManagerBinding.owner_type == "assistant").order_by(models.UserManagerBinding.bound_at.desc()).all()
    referred = [{"user_id": b.user_id, "bound_at": b.bound_at.isoformat()} for b in bindings]

    return {"balance": float(current_user.balance or 0), "commissions": commissions, "referred": referred}


@router.post("/request_withdraw")
def assistant_request_withdraw(amount: Decimal = Form(...), target_details: str = Form(...), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if role_value(current_user.role) != "assistant":
        raise HTTPException(status_code=403, detail="assistant required")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="invalid amount")
    if Decimal(current_user.balance or 0) < amount:
        raise HTTPException(status_code=400, detail="insufficient balance")

    # find manager for assistant
    manager_id = current_user.manager_id
    if not manager_id:
        raise HTTPException(status_code=400, detail="no manager assigned")

    wr = models.WithdrawRequest(
        requester_user_id=current_user.id,
        manager_user_id=manager_id,
        amount=amount,
        target_details={"raw": target_details},
        status="pending",
    )
    db.add(wr)
    db.commit()
    db.refresh(wr)

    # optionally notify manager (via celery) - safe best-effort
    try:
        from app.core.celery_app import celery_app
        celery_app.send_task("tasks.notify_manager_withdraw_request", args=[wr.id])
    except Exception:
        pass

    return {"status": "requested", "withdraw_id": wr.id}
