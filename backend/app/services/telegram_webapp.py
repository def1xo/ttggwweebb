import os
import time
import hmac
import hashlib
import json
from typing import Dict, Any, Optional, Tuple
from urllib.parse import parse_qsl


def get_bot_token() -> str:
    """Telegram bot token from env (TELEGRAM_BOT_TOKEN or BOT_TOKEN)."""
    tg = os.getenv("TELEGRAM_BOT_TOKEN")
    bot = os.getenv("BOT_TOKEN")

    def _is_placeholder(v: Optional[str]) -> bool:
        # docker compose does NOT expand ${VAR} inside env_file, so people often
        # end up with TELEGRAM_BOT_TOKEN='${BOT_TOKEN}' which breaks hash checks.
        if not v:
            return True
        vv = v.strip()
        return ("${" in vv) or vv.startswith("$")

    # Prefer explicit TELEGRAM_BOT_TOKEN only if it's not a placeholder.
    if tg and not _is_placeholder(tg):
        return tg
    if bot and not _is_placeholder(bot):
        return bot
    return tg or bot or ""


def get_ttl_seconds() -> int:
    """TTL in seconds for initData validation."""
    return int(os.getenv("INITDATA_TTL_SECONDS") or os.getenv("INITDATA_TTL") or "86400")


def parse_init_data(init_data: str) -> Dict[str, str]:
    if not init_data:
        return {}
    return dict(parse_qsl(init_data, keep_blank_values=True))


def verify_init_data(
    init_data: str,
    *,
    bot_token: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> Dict[str, str]:
    token = bot_token or get_bot_token()
    if not token:
        raise ValueError("telegram bot token not configured")

    ttl = get_ttl_seconds() if ttl_seconds is None else int(ttl_seconds)
    data = parse_init_data(init_data)
    if not data:
        raise ValueError("empty init_data")

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("hash missing")

    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys())).encode("utf-8")
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calc_hash, received_hash):
        raise ValueError("invalid hash")

    if ttl > 0 and data.get("auth_date"):
        try:
            auth_ts = int(data["auth_date"])
        except Exception:
            raise ValueError("invalid auth_date")
        now = int(time.time())
        if auth_ts - now > 300:
            raise ValueError("auth_date in future")
        if now - auth_ts > ttl:
            raise ValueError("init_data expired")

    return data


def extract_user(data: Dict[str, str]) -> Dict[str, Any]:
    # Telegram WebApp provides user as JSON in `user` parameter
    if data.get("user"):
        try:
            u = json.loads(data["user"])
            if isinstance(u, dict):
                return u
        except Exception:
            pass

    # Fallback for flattened formats
    out: Dict[str, Any] = {}
    for k in ("id", "username", "first_name", "last_name", "photo_url"):
        if data.get(k) is not None:
            out[k] = data[k]

    if "id" in out:
        try:
            out["id"] = int(out["id"])
        except Exception:
            pass

    return out


def verify_and_extract_user(
    init_data: str,
    *,
    bot_token: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    parsed = verify_init_data(init_data, bot_token=bot_token, ttl_seconds=ttl_seconds)
    user = extract_user(parsed)
    if not user or "id" not in user:
        raise ValueError("telegram user missing in init_data")
    return user, parsed
