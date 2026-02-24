from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import os
from typing import Optional

import requests

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models
from app.services.commissions import compute_and_apply_commissions

router = APIRouter(tags=["admin_orders"])


class OrderStatusUpdate(BaseModel):
    status: models.OrderStatus
    note: Optional[str] = None


def _now() -> datetime:
    return datetime.utcnow()


def _send_admin_telegram_message(text: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("ADMIN_TELEGRAM_CHAT_ID") or os.getenv("ADMIN_CHAT_ID") or "").strip()
    if not token or not chat_id or not text:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000]},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def _order_supply_lines(db: Session, order: models.Order) -> list[str]:
    lines: list[str] = []
    items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).all()
    for idx, item in enumerate(items, start=1):
        variant = db.query(models.ProductVariant).get(item.variant_id) if item.variant_id else None
        product = db.query(models.Product).get(variant.product_id) if variant else None
        size_name = "—"
        color_name = "—"
        if variant and variant.size_id:
            sz = db.query(models.Size).get(variant.size_id)
            size_name = sz.name if sz else "—"
        if variant and variant.color_id:
            clr = db.query(models.Color).get(variant.color_id)
            color_name = clr.name if clr else "—"

        latest_cost = None
        if variant:
            latest_cost = (
                db.query(models.ProductCost)
                .filter(models.ProductCost.variant_id == variant.id)
                .order_by(models.ProductCost.created_at.desc(), models.ProductCost.id.desc())
                .first()
            )
        cost_val = None
        if latest_cost and latest_cost.cost_price is not None:
            cost_val = float(latest_cost.cost_price)
        elif variant and getattr(variant, "cost_price", None) is not None:
            cost_val = float(getattr(variant, "cost_price", 0) or 0)
        elif product and getattr(product, "cost_price", None) is not None:
            cost_val = float(getattr(product, "cost_price", 0) or 0)

        supplier = (
            (str(getattr(product, "supplier_name", "") or "").strip() if product else "")
            or (str(getattr(product, "import_supplier_name", "") or "").strip() if product else "")
            or (str(getattr(product, "supplier", "") or "").strip() if product else "")
            or "не назначен"
        )

        cost_txt = f"{cost_val:.0f} ₽" if isinstance(cost_val, float) and cost_val > 0 else "н/д"
        lines.append(
            f"{idx}) {(product.title if product else 'Товар')} | size: {size_name} | color: {color_name}\n"
            f"   qty: {int(item.quantity or 0)} • retail: {float(item.price or 0):.0f} ₽ • закупка(оценка): {cost_txt} • поставщик: {supplier}"
        )
    return lines or ["• Нет товарных позиций"]


def _parse_status(raw: Optional[str]) -> Optional[models.OrderStatus]:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # accept both 'paid' and 'OrderStatus.paid'
    s = s.split('.')[-1]
    try:
        return models.OrderStatus[s]
    except Exception:
        try:
            return models.OrderStatus(s)
        except Exception:
            return None

def _log_status(db: Session, order: models.Order, old_status: str, new_status: str, changed_by: Optional[int], note: Optional[str] = None):
    try:
        db.add(
            models.OrderStatusLog(
                order_id=order.id,
                old_status=str(old_status),
                new_status=str(new_status),
                changed_by=changed_by,
                note=note,
            )
        )
    except Exception:
        # non-critical
        pass


@router.get("/orders")
def list_orders(
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    q = (
        db.query(models.Order)
        .options(
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.variant)
            .joinedload(models.ProductVariant.product)
        )
        .order_by(models.Order.created_at.desc())
    )
    st = _parse_status(status)
    if st is not None:
        q = q.filter(models.Order.status == st)
    items = q.offset(offset).limit(min(limit, 200)).all()
    return items


@router.get("/orders/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    order = (
        db.query(models.Order)
        .options(joinedload(models.Order.items).joinedload(models.OrderItem.variant).joinedload(models.ProductVariant.product))
        .get(order_id)
    )
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@router.post("/orders/{order_id}/confirm_payment")
def admin_confirm_payment(
    order_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    order = db.query(models.Order).options(joinedload(models.Order.items)).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order not found")

    if order.status not in (models.OrderStatus.paid, models.OrderStatus.processing, models.OrderStatus.sent, models.OrderStatus.received, models.OrderStatus.delivered):
        # if awaiting_payment -> no proof uploaded
        raise HTTPException(status_code=400, detail=f"cannot confirm payment for status={order.status}")

    # Apply commissions only once: if order already has commissions, skip.
    existing = db.query(models.Commission).filter(models.Commission.order_id == order.id).count()
    if existing == 0:
        compute_and_apply_commissions(db, order, update_order_status=False)

    # Finalize special promo
    if getattr(order, "promo_kind", None) == "special" and getattr(order, "promo_special_id", None):
        promo = db.query(models.PromoCode).get(order.promo_special_id)
        buyer = db.query(models.User).get(order.user_id)
        if promo and buyer:
            # increment usage
            try:
                if promo.used_count is None:
                    promo.used_count = 0
                promo.used_count = int(promo.used_count) + 1
            except Exception:
                pass

            # record usage
            try:
                used = models.PromoUsage(user_id=buyer.id, promo_code_id=promo.id, used_at=_now())
                db.add(used)
            except Exception:
                pass

            # mark user as used promo once-for-life
            buyer.promo_used_code = promo.code
            buyer.promo_used_at = _now()
            buyer.promo_pending_code = None
            buyer.promo_pending_order_id = None

            # mark reservation used
            try:
                resv = (
                    db.query(models.PromoReservation)
                    .filter(
                        models.PromoReservation.user_id == buyer.id,
                        models.PromoReservation.promo_code_id == promo.id,
                        models.PromoReservation.used_at.is_(None),
                    )
                    .order_by(models.PromoReservation.reserved_at.desc())
                    .first()
                )
                if resv:
                    resv.used_at = _now()
                    resv.order_id = order.id
                    resv.expires_at = None
                    db.add(resv)
            except Exception:
                pass

            db.add(promo)
            db.add(buyer)

    # Move to processing if still paid
    old_status = order.status
    if order.status == models.OrderStatus.paid:
        order.status = models.OrderStatus.processing
    db.add(order)
    _log_status(db, order, str(old_status), str(order.status), changed_by=admin.id, note="confirm_payment")
    db.commit()
    db.refresh(order)

    base_url = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    proof = (order.payment_screenshot or "").strip()
    if proof.startswith("/") and base_url:
        proof_link = f"{base_url.rstrip('/')}{proof}"
    else:
        proof_link = proof or "—"

    supply_lines = _order_supply_lines(db, order)
    title = "✅ Оплата подтверждена" if payload.status != models.OrderStatus.cancelled else "⚠️ Заказ отменён"
    msg = (
        f"{title} #{order.id}\n"
        f"Сумма: {float(order.total_amount or 0):.0f} ₽\n"
        f"Клиент: {(order.fio or '—')} | {(order.phone or '—')}\n"
        f"Статус: {order.status}\n"
        f"Пруф: {proof_link}\n\n"
        f"Позиции / закупка:\n" + "\n".join(supply_lines)
    )
    _send_admin_telegram_message(msg)
    return order


@router.post("/orders/{order_id}/status")
@router.patch("/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    order = db.query(models.Order).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order not found")

    old = order.status
    order.status = payload.status


    # If special promo was pending and the order gets cancelled, release the pending lock and reservation.
    if payload.status == models.OrderStatus.cancelled:
        try:
            if getattr(order, "promo_kind", None) == "special":
                buyer = db.query(models.User).get(getattr(order, "user_id", None))
                if buyer and getattr(buyer, "promo_pending_order_id", None) == order.id:
                    buyer.promo_pending_code = None
                    buyer.promo_pending_order_id = None
                    db.add(buyer)
                # release any reservation attached to this order
                try:
                    db.query(models.PromoReservation).filter(
                        models.PromoReservation.order_id == order.id,
                        models.PromoReservation.used_at.is_(None),
                    ).delete(synchronize_session=False)
                except Exception:
                    pass
        except Exception:
            pass
    db.add(order)
    _log_status(db, order, str(old), str(payload.status), changed_by=admin.id, note=payload.note)
    db.commit()
    db.refresh(order)

    base_url = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    proof = (order.payment_screenshot or "").strip()
    if proof.startswith("/") and base_url:
        proof_link = f"{base_url.rstrip('/')}{proof}"
    else:
        proof_link = proof or "—"

    supply_lines = _order_supply_lines(db, order)
    title = "✅ Оплата подтверждена" if payload.status != models.OrderStatus.cancelled else "⚠️ Заказ отменён"
    msg = (
        f"{title} #{order.id}\n"
        f"Сумма: {float(order.total_amount or 0):.0f} ₽\n"
        f"Клиент: {(order.fio or '—')} | {(order.phone or '—')}\n"
        f"Статус: {order.status}\n"
        f"Пруф: {proof_link}\n\n"
        f"Позиции / закупка:\n" + "\n".join(supply_lines)
    )
    _send_admin_telegram_message(msg)
    return order
