from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, conint
from sqlalchemy.orm import Session
from decimal import Decimal

from app.api.dependencies import get_db, get_current_manager_user, role_value
from app.db import models

router = APIRouter(prefix="/manager", tags=["manager"])


class AssistantCreate(BaseModel):
    user_id: int
    percent: conint(ge=0, le=100)


class AssistantPatch(BaseModel):
    percent: conint(ge=0, le=100)


@router.get("/assistants")
def list_assistants(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_manager_user)):
    if role_value(current_user.role) not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="manager required")
    recs = (
        db.query(models.ManagerAssistant, models.User)
        .join(models.User, models.User.id == models.ManagerAssistant.assistant_id)
        .filter(models.ManagerAssistant.manager_id == current_user.id)
        .all()
    )
    result = []
    for ma, user in recs:
        result.append(
            {
                "id": ma.id,
                "assistant_id": ma.assistant_id,
                "username": getattr(user, "username", None),
                "percent": ma.percent,
                "balance": float(getattr(user, "balance", 0) or 0),
            }
        )
    return result


@router.post("/assistants", status_code=201)
def add_assistant(payload: AssistantCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_manager_user)):
    if role_value(current_user.role) not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="manager required")
    user = db.query(models.User).filter(models.User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    # prevent assigning same assistant to another manager
    existing = db.query(models.ManagerAssistant).filter(models.ManagerAssistant.assistant_id == payload.user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="assistant already assigned")
    ma = models.ManagerAssistant(manager_id=current_user.id, assistant_id=payload.user_id, percent=payload.percent)
    db.add(ma)
    db.commit()
    db.refresh(ma)
    # audit
    try:
        db.add(models.AuditLog(actor_user_id=current_user.id, action="assign_assistant", target=str(payload.user_id), metadata={"percent": payload.percent}))
        db.commit()
    except Exception:
        db.rollback()
    return {"id": ma.id, "manager_id": ma.manager_id, "assistant_id": ma.assistant_id, "percent": ma.percent}


@router.patch("/assistants/{aid}")
def patch_assistant(aid: int = Path(...), payload: AssistantPatch = None, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_manager_user)):
    if role_value(current_user.role) not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="manager required")
    rec = db.query(models.ManagerAssistant).filter(models.ManagerAssistant.id == aid, models.ManagerAssistant.manager_id == current_user.id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="not found")
    rec.percent = payload.percent
    db.add(rec)
    db.commit()
    db.refresh(rec)
    try:
        db.add(models.AuditLog(actor_user_id=current_user.id, action="update_assistant_percent", target=str(rec.assistant_id), metadata={"percent": rec.percent}))
        db.commit()
    except Exception:
        db.rollback()
    return {"id": rec.id, "percent": rec.percent}


@router.get("/commissions")
def manager_commissions(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=500), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_manager_user)):
    if role_value(current_user.role) not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="manager required")
    q = db.query(models.Commission).filter(models.Commission.user_id == current_user.id).order_by(models.Commission.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return {"items": [{"id": c.id, "order_id": c.order_id, "amount": float(c.amount), "created_at": c.created_at.isoformat()} for c in items], "total": total, "page": page, "per_page": per_page}


@router.get("/withdraws")
def manager_withdraws(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_manager_user)):
    if role_value(current_user.role) not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="manager required")
    # manager should see their own withdraws and withdraws from assistants assigned to them
    subq = db.query(models.User.id).filter(models.User.manager_id == current_user.id).subquery()
    q = db.query(models.WithdrawRequest).filter(
        (models.WithdrawRequest.requester_user_id == current_user.id) |
        (models.WithdrawRequest.requester_user_id.in_(subq))
    ).order_by(models.WithdrawRequest.created_at.desc())
    items = q.all()
    return [{"id": w.id, "requester_user_id": w.requester_user_id, "amount": float(w.amount), "status": w.status, "created_at": w.created_at.isoformat(), "target_details": w.target_details} for w in items]


@router.get("/balance")
def manager_balance(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_manager_user)):
    return {"balance": float(current_user.balance or 0)}
