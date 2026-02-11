# backend/app/api/v1/logs.py
from fastapi import APIRouter, Depends, Query, Request
import json
import os
from datetime import datetime

from app.api.dependencies import get_current_admin_user
from app.db import models

router = APIRouter()


def _append_jsonl(filepath: str, payload: dict) -> None:
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_jsonl(filepath: str):
    if not filepath or not os.path.exists(filepath):
        return []
    out = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out

@router.post("/client-error")
async def client_error(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": await request.body()}
    try:
        fn = os.environ.get("CLIENT_ERRORS_LOG", "/tmp/client_errors.log")
        _append_jsonl(fn, {"ts": datetime.utcnow().isoformat(), "payload": payload})
    except Exception as e:
        # не ломаем поведение, просто вернём ok
        print("Failed to write client error log:", e)
    return {"ok": True}


@router.post("/analytics-event")
async def analytics_event(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode("utf-8", errors="ignore")}
    try:
        fn = os.environ.get("ANALYTICS_EVENTS_LOG", "/tmp/analytics_events.log")
        _append_jsonl(fn, {"ts": datetime.utcnow().isoformat(), "payload": payload})
    except Exception as e:
        print("Failed to write analytics event:", e)
    return {"ok": True}


@router.get("/analytics-funnel")
def analytics_funnel(
    days: int = Query(30, ge=1, le=365),
    admin: models.User = Depends(get_current_admin_user),
):
    cutoff = datetime.utcnow().timestamp() - (days * 86400)
    fn = os.environ.get("ANALYTICS_EVENTS_LOG", "/tmp/analytics_events.log")
    rows = _read_jsonl(fn)

    counters = {
        "view_product": 0,
        "add_to_cart": 0,
        "begin_checkout": 0,
        "purchase": 0,
    }

    for row in rows:
        try:
            ts = row.get("ts")
            ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if ts else None
            if not ts_dt or ts_dt.timestamp() < cutoff:
                continue
        except Exception:
            continue

        payload = row.get("payload") or {}
        event_name = str((payload.get("event") or payload.get("name") or "")).strip()
        if event_name in counters:
            counters[event_name] += 1

    views = counters["view_product"]
    add_to_cart = counters["add_to_cart"]
    begin_checkout = counters["begin_checkout"]
    purchases = counters["purchase"]

    def _rate(num: int, den: int) -> float:
        if den <= 0:
            return 0.0
        return round((num / den) * 100, 2)

    return {
        "days": days,
        "events_file": fn,
        "counts": counters,
        "conversion": {
            "view_to_cart_percent": _rate(add_to_cart, views),
            "cart_to_checkout_percent": _rate(begin_checkout, add_to_cart),
            "checkout_to_purchase_percent": _rate(purchases, begin_checkout),
            "view_to_purchase_percent": _rate(purchases, views),
        },
    }
