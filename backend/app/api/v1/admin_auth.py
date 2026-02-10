# backend/app/api/v1/admin_auth.py
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_

import jwt

from app.api.dependencies import get_db
from app.db import models

router = APIRouter()  # main app likely does include_router(..., prefix="/api")

class AdminLoginRequest(BaseModel):
    user_id: int  # can be internal id or telegram id
    password: str


def _jwt_secret():
    return os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET") or "change-me"


@router.post("/login")
@router.post("/admin/login")  # duplicate to be robust for different includes
def admin_login(body: AdminLoginRequest, db: Session = Depends(get_db)):
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=500, detail="ADMIN_PASSWORD not set in environment")
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # treat provided id as telegram_id OR internal id: first try telegram_id, then id
    q = db.query(models.User).filter(or_(models.User.telegram_id == body.user_id, models.User.id == body.user_id))
    user = q.one_or_none()

    if not user:
        # create user row with telegram_id set to provided id; fill some defaults
        user = models.User(
            telegram_id=body.user_id,
            username=None,
            role="admin",
            first_name="Admin",
            display_name="Admin",
            balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if user.role != "admin":
            user.role = "admin"
            db.add(user)
            db.commit()
            db.refresh(user)

    SECRET = _jwt_secret()
    ALGO = os.getenv("JWT_ALGORITHM", "HS256")
    exp_hours = int(os.getenv("JWT_EXP_HOURS", 12))
    expire = datetime.utcnow() + timedelta(hours=exp_hours)
    payload = {"sub": str(user.id), "user_id": user.id, "telegram_id": user.telegram_id, "role": user.role, "exp": int(expire.timestamp())}
    token = jwt.encode(payload, SECRET, algorithm=ALGO)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return {"access_token": token, "token_type": "bearer", "user_id": user.id}
