# backend/app/api/v1/logs.py
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
import json
import os
from datetime import datetime

from app.api.dependencies import get_current_admin_user, get_db
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


def _event_ts(row: dict):
    ts = row.get("ts")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _iter_recent_events(filepath: str, cutoff_ts: float):
    rows = _read_jsonl(filepath)
    for row in rows:
        ts = _event_ts(row)
        if ts is None or ts < cutoff_ts:
            continue
        payload = row.get("payload") if isinstance(row, dict) else None
        if isinstance(payload, dict):
            yield payload


def _safe_int(value):
    try:
        n = int(value)
        return n if n > 0 else None
    except Exception:
        return None

@router.post("/client-error")
async def client_error(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode("utf-8", errors="ignore")}
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

    counters = {
        "view_product": 0,
        "add_to_cart": 0,
        "begin_checkout": 0,
        "purchase": 0,
    }

    source_breakdown = {}

    for payload in _iter_recent_events(fn, cutoff):
        event_name = str((payload.get("event") or payload.get("name") or "")).strip()
        if event_name in counters:
            counters[event_name] += 1

        source = str(payload.get("source") or "unknown").strip() or "unknown"
        if source not in source_breakdown:
            source_breakdown[source] = {"view_product": 0, "add_to_cart": 0, "begin_checkout": 0, "purchase": 0}
        if event_name in source_breakdown[source]:
            source_breakdown[source][event_name] += 1

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
        "source_breakdown": source_breakdown,
    }


@router.get("/analytics-top-products")
def analytics_top_products(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=100),
    admin: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    cutoff = datetime.utcnow().timestamp() - (days * 86400)
    fn = os.environ.get("ANALYTICS_EVENTS_LOG", "/tmp/analytics_events.log")

    counters = {}

    for payload in _iter_recent_events(fn, cutoff):
        event_name = str((payload.get("event") or payload.get("name") or "")).strip()
        if event_name not in ("view_product", "add_to_cart", "purchase"):
            continue
        product_id = _safe_int(payload.get("product_id"))
        if not product_id:
            continue
        if product_id not in counters:
            counters[product_id] = {"product_id": product_id, "view_product": 0, "add_to_cart": 0, "purchase": 0}
        counters[product_id][event_name] += 1

    scored = []
    for item in counters.values():
        views = item["view_product"]
        adds = item["add_to_cart"]
        purchases = item["purchase"]
        add_rate = round((adds / views) * 100, 2) if views > 0 else 0.0
        purchase_rate = round((purchases / views) * 100, 2) if views > 0 else 0.0
        item["add_rate_percent"] = add_rate
        item["purchase_rate_percent"] = purchase_rate
        item["score"] = purchases * 1000 + adds * 10 + views
        scored.append(item)

    scored.sort(key=lambda x: (x["score"], x["purchase"], x["add_to_cart"], x["view_product"]), reverse=True)
    top = scored[:limit]

    ids = [x["product_id"] for x in top]
    title_map = {}
    if ids:
        rows = db.query(models.Product.id, models.Product.title).filter(models.Product.id.in_(ids)).all()
        title_map = {int(r[0]): str(r[1] or f"#{r[0]}") for r in rows}

    for item in top:
        pid = item["product_id"]
        item["title"] = title_map.get(pid, f"Товар #{pid}")

    return {
        "days": days,
        "limit": limit,
        "events_file": fn,
        "items": top,
    }
