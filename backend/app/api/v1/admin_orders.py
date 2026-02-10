from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

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
    return order
