# backend/app/api/v1/auth.py
import os
import time
import hmac
import hashlib
from typing import Optional, Dict

from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

import jwt

from app.db import models
from app.api.dependencies import get_db, get_current_user, role_value, is_admin_id
from app.services.telegram_webapp import verify_and_extract_user, get_bot_token

router = APIRouter()  # main app likely calls include_router(..., prefix="/api")

JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("SECRET_KEY", "replace_me"))
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")
JWT_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", 60 * 60 * 24 * 7))  # week
# Support both env var names (people often keep bot token as BOT_TOKEN in .env)
# NOTE: docker compose does NOT expand ${VAR} inside env_file; get_bot_token() guards this.
TELEGRAM_BOT_TOKEN = get_bot_token()
INITDATA_TTL = int(os.getenv("INITDATA_TTL_SECONDS", 86400))



class InitDataIn(BaseModel):
    init_data: str


class UserRead(BaseModel):
    id: int
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    balance: float = 0.0
    balance_hold: float = 0.0
    promo_code: Optional[str] = None
    manager_id: Optional[int] = None


def _parse_query_string(qs: str) -> Dict[str, str]:
    parts: Dict[str, str] = {}
    for item in qs.split("&"):
        if "=" in item:
            k, v = item.split("=", 1)
            parts[k] = v
    return parts


def verify_telegram_init_data(init_data: str) -> Dict[str, str]:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("telegram bot token not configured")

    parts = _parse_query_string(init_data)
    if "hash" not in parts:
        raise ValueError("hash missing")
    received_hash = parts.pop("hash")

    data_check_arr = [f"{k}={parts[k]}" for k in sorted(parts.keys())]
    data_check_string = "\n".join(data_check_arr).encode("utf-8")

    secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    hmac_hash = hmac.new(secret_key, data_check_string, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(hmac_hash, received_hash):
        raise ValueError("invalid hash")

    auth_date = parts.get("auth_date")
    if auth_date:
        try:
            auth_ts = int(auth_date)
            now = int(time.time())
            if abs(now - auth_ts) > INITDATA_TTL:
                raise ValueError("init_data expired")
        except ValueError:
            raise ValueError("invalid auth_date")

    return parts


def create_jwt(payload: dict) -> str:
    now = int(time.time())
    data = {"iat": now, "exp": now + JWT_EXPIRE_SECONDS, **payload}
    token = jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGO)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


class InitResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict


@router.post("/webapp_init", response_model=InitResponse)
@router.post("/auth/webapp_init", response_model=InitResponse)  # duplicate path to be robust
def webapp_init(payload_in: InitDataIn = Body(...), db: Session = Depends(get_db)):
    try:
        tg_user, parsed = verify_and_extract_user(
            payload_in.init_data,
            bot_token=(TELEGRAM_BOT_TOKEN or None),
            ttl_seconds=INITDATA_TTL,
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"invalid init_data: {e}")

    try:
        telegram_id = int(tg_user.get("id"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid telegram id")

    username = tg_user.get("username")
    first_name = tg_user.get("first_name")
    last_name = tg_user.get("last_name")
    photo_url = tg_user.get("photo_url")

    user = db.query(models.User).filter(or_(models.User.telegram_id == telegram_id,
                                           models.User.id == telegram_id)).one_or_none()
    created = False
    if not user:
        user = models.User(
            telegram_id=telegram_id,
            username=username,
            first_name=(first_name or "")[:64] if first_name else None,
            last_name=(last_name or "")[:64] if last_name else None,
            role=models.UserRole.admin if is_admin_id(telegram_id) else models.UserRole.user,
            balance=0,
        )
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
            created = True
        except IntegrityError:
            # Race condition: two parallel webapp_init requests for the same Telegram user.
            db.rollback()
            user = db.query(models.User).filter(models.User.telegram_id == telegram_id).one_or_none()
            if not user:
                raise HTTPException(status_code=500, detail="failed to initialize user")
    else:
        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if photo_url and getattr(user, "avatar_url", None) != photo_url:
            user.avatar_url = photo_url[:1024]
            changed = True
        if (first_name or last_name):
            new_first = (first_name or "")[:64]
            new_last = (last_name or "")[:64]
            if user.first_name != new_first or user.last_name != new_last:
                user.first_name = new_first
                user.last_name = new_last
                changed = True
        if is_admin_id(telegram_id) and role_value(user.role) != "admin":
            user.role = models.UserRole.admin
            changed = True
        if changed:
            db.add(user)
            db.commit()
            db.refresh(user)

    payload = {"sub": str(user.id), "user_id": user.id, "telegram_id": user.telegram_id, "role": role_value(user.role)}
    token = create_jwt(payload)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "role": role_value(user.role),
            "balance": float(user.balance or 0),
            "balance_hold": float(getattr(user, "balance_hold", 0) or 0),
            "promo_code": getattr(user, "promo_code", None),
            "manager_id": getattr(user, "manager_id", None),
            "created": created,
        },
    }


@router.get("/me", response_model=UserRead)
@router.get("/auth/me", response_model=UserRead)  # duplicate path to be robust
def me(current_user: models.User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return UserRead(
        id=current_user.id,
        telegram_id=int(current_user.telegram_id) if current_user.telegram_id is not None else 0,
        username=current_user.username,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        role=role_value(current_user.role),
        balance=float(current_user.balance or 0),
        balance_hold=float(getattr(current_user, "balance_hold", 0) or 0),
        promo_code=getattr(current_user, "promo_code", None),
        manager_id=getattr(current_user, "manager_id", None),
    )


class ProfilePatch(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    promo_code: Optional[str] = None
    avatar_url: Optional[str] = None


@router.patch("/me")
@router.patch("/auth/me")
def patch_me(body: ProfilePatch, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user:
        raise HTTPException(status_code=401, detail="unauthenticated")

    changed = False
    if body.username and body.username != current_user.username:
        current_user.username = body.username
        changed = True
    if (body.first_name is not None) and body.first_name != current_user.first_name:
        current_user.first_name = (body.first_name or "")[:64]
        changed = True
    if (body.last_name is not None) and body.last_name != current_user.last_name:
        current_user.last_name = (body.last_name or "")[:64]
        changed = True
    if body.display_name is not None and getattr(current_user, "display_name", None) != body.display_name:
        setattr(current_user, "display_name", body.display_name)
        changed = True

    # promo_code update (unique)
    # Only admin/manager may change it. For regular users ignore silently.
    role = role_value(getattr(current_user, "role", ""))
    can_edit_promo = role in ("admin", "manager") or is_admin_id(getattr(current_user, "telegram_id", None))
    if body.promo_code is not None and can_edit_promo:
        code = (body.promo_code or '').strip()
        if code == '':
            # allow clearing
            if getattr(current_user, 'promo_code', None) is not None:
                current_user.promo_code = None
                changed = True
        else:
            norm = ''.join(ch for ch in code.upper() if ch.isalnum() or ch in ('_', '-'))
            norm = norm[:64]
            if norm != code.upper():
                # keep only safe chars; if user entered invalid chars, still accept normalized
                pass
            if len(norm) < 3:
                raise HTTPException(status_code=400, detail='promo_code too short')
            # uniqueness check
            exists = db.query(models.User).filter(models.User.promo_code == norm, models.User.id != current_user.id).first()
            if exists:
                raise HTTPException(status_code=400, detail='promo_code already taken')
            if getattr(current_user, 'promo_code', None) != norm:
                current_user.promo_code = norm
                changed = True

    # avatar_url update (stored in users.avatar_url)
    if body.avatar_url is not None and getattr(current_user, 'avatar_url', None) != body.avatar_url:
        setattr(current_user, 'avatar_url', body.avatar_url)
        changed = True

    if changed:
        db.add(current_user)
        db.commit()
        db.refresh(current_user)

    return {"ok": True, "user": {"id": current_user.id, "username": current_user.username, "display_name": getattr(current_user, "display_name", None), "promo_code": getattr(current_user, 'promo_code', None), "avatar_url": getattr(current_user, 'avatar_url', None)}}
