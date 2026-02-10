import os
from typing import Generator, Optional

import logging

from fastapi import Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
import jwt

from app.db.session import SessionLocal
from app.db import models
from app.services.telegram_webapp import verify_and_extract_user

logger = logging.getLogger("uvicorn.error")

JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "replace_me"
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")
ADMIN_TELEGRAM_IDS = os.getenv("ADMIN_TELEGRAM_IDS", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")


def _build_admin_id_set() -> set[str]:
    ids: set[str] = set()
    try:
        for x in (ADMIN_TELEGRAM_IDS or "").split(","):
            x = (x or "").strip()
            if x:
                ids.add(x)
    except Exception:
        pass
    try:
        x = (ADMIN_CHAT_ID or "").strip()
        if x:
            ids.add(x)
    except Exception:
        pass
    return ids


_ADMIN_ID_SET = _build_admin_id_set()


def is_admin_id(telegram_id: int | str | None) -> bool:
    """Return True if telegram_id belongs to admin list (ADMIN_TELEGRAM_IDS or ADMIN_CHAT_ID)."""
    if telegram_id is None:
        return False
    try:
        return str(int(telegram_id)) in _ADMIN_ID_SET
    except Exception:
        try:
            return str(telegram_id) in _ADMIN_ID_SET
        except Exception:
            return False


def role_value(role) -> str:
    """Normalize role field (Enum/str) to plain string."""
    if role is None:
        return ""
    if hasattr(role, "value"):
        return str(role.value)
    return str(role)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_token_from_auth_header(authorization: Optional[str]) -> Optional[str]:
    """Parse Authorization header. Expect 'Bearer <token>'."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token


def _decode_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        if not isinstance(payload, dict):
            raise HTTPException(status_code=401, detail="invalid token payload")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")


def _find_user_from_payload(db: Session, payload: dict) -> Optional[models.User]:
    """Try multiple lookup strategies for JWT payload."""
    user = None

    uid = payload.get("user_id")
    if uid is not None:
        try:
            user = db.query(models.User).filter(models.User.id == int(uid)).one_or_none()
            if user:
                return user
        except Exception:
            pass

    sub = payload.get("sub")
    if sub is not None:
        try:
            user = db.query(models.User).filter(models.User.id == int(sub)).one_or_none()
            if user:
                return user
        except Exception:
            pass

    tgid = payload.get("telegram_id")
    if tgid is not None:
        for cast in (int, str):
            try:
                user = db.query(models.User).filter(models.User.telegram_id == cast(tgid)).one_or_none()
                if user:
                    return user
            except Exception:
                pass

    return None


def _is_admin_telegram_id(telegram_id: int) -> bool:
    # backward compatible alias
    return is_admin_id(telegram_id)


def _get_or_create_user_from_tg(db: Session, tg_user: dict) -> models.User:
    telegram_id = int(tg_user.get("id"))
    username = tg_user.get("username")
    first_name = tg_user.get("first_name")
    last_name = tg_user.get("last_name")
    photo_url = tg_user.get("photo_url")

    user = db.query(models.User).filter(models.User.telegram_id == telegram_id).one_or_none()
    if not user:
        user = models.User(
            telegram_id=telegram_id,
            username=username,
            first_name=(first_name or "")[:128] if first_name else None,
            last_name=(last_name or "")[:128] if last_name else None,
            role=models.UserRole.admin if is_admin_id(telegram_id) else models.UserRole.user,
        )
        if photo_url and hasattr(user, "avatar_url"):
            user.avatar_url = str(photo_url)[:1024]
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    changed = False
    if username and user.username != username:
        user.username = username
        changed = True
    if first_name is not None:
        new_first = (first_name or "")[:128]
        if user.first_name != new_first:
            user.first_name = new_first
            changed = True
    if last_name is not None:
        new_last = (last_name or "")[:128]
        if user.last_name != new_last:
            user.last_name = new_last
            changed = True
    if photo_url and getattr(user, "avatar_url", None) != photo_url:
        user.avatar_url = str(photo_url)[:1024]
        changed = True
    if is_admin_id(telegram_id) and role_value(user.role) != "admin":
        user.role = models.UserRole.admin
        changed = True
    if changed:
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    db: Session = Depends(get_db),
) -> models.User:
    """Current user by JWT or Telegram WebApp initData."""
    token = _get_token_from_auth_header(authorization)
    if token:
        payload = _decode_jwt(token)
        user = _find_user_from_payload(db, payload)
        if not user:
            raise HTTPException(status_code=401, detail="user not found")
        # Auto-promote: if env marks this telegram_id as admin but DB role is still user.
        try:
            tid = getattr(user, "telegram_id", None)
            if tid is not None and is_admin_id(tid) and role_value(getattr(user, "role", "")) != "admin":
                user.role = models.UserRole.admin
                db.add(user)
                db.commit()
                db.refresh(user)
        except Exception:
            # non-fatal
            pass
        return user

    init_data = x_telegram_init_data
    if not init_data:
        init_data = request.query_params.get("initData") or request.query_params.get("init_data")

    if init_data:
        try:
            tg_user, _parsed = verify_and_extract_user(init_data)
            return _get_or_create_user_from_tg(db, tg_user)
        except Exception as e:
            try:
                logger.warning("Telegram initData auth failed: %s (len=%s)", e, len(init_data or ""))
            except Exception:
                pass
            raise HTTPException(status_code=401, detail="invalid telegram init_data")

    logger.warning("Telegram auth missing: no Authorization header and no X-Telegram-Init-Data")
    raise HTTPException(status_code=401, detail="missing authorization")


def _require_role(user: models.User, allowed: set[str]) -> models.User:
    role = role_value(getattr(user, "role", ""))
    # allow admin to pass most gated endpoints by default
    if role == "admin":
        return user
    if role not in allowed:
        raise HTTPException(status_code=403, detail="forbidden")
    return user


def get_current_admin_user(current_user: models.User = Depends(get_current_user)) -> models.User:
    """Admin-only dependency (also allows admin via ADMIN_TELEGRAM_IDS auto-role)."""
    role = role_value(getattr(current_user, "role", ""))
    if role != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return current_user


def get_current_manager_user(current_user: models.User = Depends(get_current_user)) -> models.User:
    """Manager-only dependency (admin is also allowed)."""
    return _require_role(current_user, {"manager"})
