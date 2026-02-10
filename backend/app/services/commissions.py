from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.db import models


def _d(v) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _round_money(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _get_user_rate(user: models.User, field: str, default: Decimal) -> Decimal:
    try:
        raw = getattr(user, field, None)
        if raw is None:
            return default
        d = _d(raw)
        if d <= 0:
            return default
        # stored as fraction (0.10) OR percent (10)
        if d > 1:
            return (d / Decimal("100")).quantize(Decimal("0.0001"))
        return d
    except Exception:
        return default


def _get_first_n_count(user: models.User, default: int = 3) -> int:
    try:
        n = int(getattr(user, "first_n_count", default) or default)
        return max(1, min(1000, n))
    except Exception:
        return default


def compute_and_apply_commissions(
    db: Session,
    order: models.Order,
    admin_user_id: Optional[int] = None,
    update_order_status: bool = True,
) -> List[models.Commission]:
    """Create commission records + update balances.

    Notes:
    - This function does NOT commit; caller should commit/rollback.
    - Manager commission is paid on all orders tied to `order.manager_id`.
      (Assistant-linked orders should set manager_id as well.)
    - Manager rate is:
        * first N orders of the buyer: manager.first_n_rate (default 10%)
        * afterwards: manager.ongoing_rate (default 5%)
    - Assistant receives a share of the manager commission ONLY for the buyer's first N orders.
      Share is taken from ManagerAssistant.percent (0..100), i.e. percent of manager commission.
    """

    if not order:
        raise ValueError("order is required")

    total = _d(getattr(order, "total_amount", getattr(order, "total", 0) or 0))
    if total <= 0:
        raise ValueError("order total must be > 0")

    # Count buyer's already-confirmed orders (excluding current).
    buyer_id = getattr(order, "user_id", None)
    confirmed_statuses = ("paid", "processing", "sent", "received", "delivered")
    confirmed_count = 0
    if buyer_id:
        try:
            confirmed_count = (
                db.query(models.Order)
                .filter(
                    models.Order.user_id == buyer_id,
                    models.Order.status.in_(confirmed_statuses),
                    models.Order.id != order.id,
                )
                .count()
            )
        except DataError:
            # legacy enum, fallback
            confirmed_count = (
                db.query(models.Order)
                .filter(
                    models.Order.user_id == buyer_id,
                    models.Order.status == "paid",
                    models.Order.id != order.id,
                )
                .count()
            )

    manager_user: Optional[models.User] = None
    assistant_user: Optional[models.User] = None
    if getattr(order, "manager_id", None):
        manager_user = (
            db.query(models.User)
            .filter(models.User.id == int(order.manager_id))
            .with_for_update()
            .one_or_none()
        )
    if getattr(order, "assistant_id", None):
        assistant_user = (
            db.query(models.User)
            .filter(models.User.id == int(order.assistant_id))
            .with_for_update()
            .one_or_none()
        )

    # Determine N and whether this order is within first N for the buyer.
    first_n_count = _get_first_n_count(manager_user) if manager_user else 3
    is_first_n = confirmed_count < first_n_count

    # Determine manager rate.
    manager_first_rate = _get_user_rate(manager_user, "first_n_rate", Decimal("0.10")) if manager_user else Decimal("0")
    manager_ongoing_rate = _get_user_rate(manager_user, "ongoing_rate", Decimal("0.05")) if manager_user else Decimal("0")
    manager_rate = manager_first_rate if is_first_n else manager_ongoing_rate

    manager_commission_gross = _round_money(total * manager_rate)

    # Assistant share (percent of manager commission) — ONLY for first N.
    assistant_amount = Decimal("0.00")
    assistant_percent_val = Decimal("0")
    if manager_user and assistant_user and is_first_n and manager_commission_gross > 0:
        mapping = (
            db.query(models.ManagerAssistant)
            .filter(
                models.ManagerAssistant.manager_id == manager_user.id,
                models.ManagerAssistant.assistant_id == assistant_user.id,
            )
            .with_for_update()
            .one_or_none()
        )
        if mapping is not None:
            try:
                assistant_percent_val = _d(mapping.percent)
            except Exception:
                assistant_percent_val = Decimal("0")
            if assistant_percent_val < 0:
                assistant_percent_val = Decimal("0")
            if assistant_percent_val > 100:
                assistant_percent_val = Decimal("100")
            assistant_amount = _round_money(manager_commission_gross * (assistant_percent_val / Decimal("100")))

    manager_amount_net = _round_money(manager_commission_gross - assistant_amount)

    # Remainder goes to admin (or stays unassigned if admin_user_id is None).
    admin_amount = _round_money(total - manager_commission_gross)
    if admin_amount < 0:
        admin_amount = Decimal("0.00")

    created: List[models.Commission] = []
    now = datetime.utcnow()

    # Manager commission record
    if manager_user and manager_commission_gross > 0:
        mc = models.Commission(
            order_id=order.id,
            user_id=manager_user.id,
            role="manager",
            base_amount=manager_commission_gross,
            percent=float((manager_rate * Decimal("100")).quantize(Decimal("0.01"))),
            amount=manager_amount_net,
            meta={
                "is_first_n": bool(is_first_n),
                "first_n_count": int(first_n_count),
                "assistant_amount": str(assistant_amount),
                "assistant_percent": str(assistant_percent_val),
            },
            created_at=now,
        )
        db.add(mc)
        created.append(mc)
        manager_user.balance = _d(getattr(manager_user, "balance", 0)) + manager_amount_net
        db.add(manager_user)

    # Assistant commission record
    if assistant_user and assistant_amount > 0:
        ac = models.Commission(
            order_id=order.id,
            user_id=assistant_user.id,
            role="assistant",
            base_amount=manager_commission_gross,
            percent=float(assistant_percent_val),
            amount=assistant_amount,
            meta={"from_manager_id": manager_user.id if manager_user else None, "is_first_n": bool(is_first_n)},
            created_at=now,
        )
        db.add(ac)
        created.append(ac)
        assistant_user.balance = _d(getattr(assistant_user, "balance", 0)) + assistant_amount
        db.add(assistant_user)

    # Admin commission record (optional)
    adm = models.Commission(
        order_id=order.id,
        user_id=admin_user_id,
        role="admin",
        base_amount=total,
        percent=None,
        amount=admin_amount,
        meta={},
        created_at=now,
    )
    db.add(adm)
    created.append(adm)

    if update_order_status:
        # Keep enum-safe values only.
        try:
            order.status = models.OrderStatus.paid
        except Exception:
            order.status = "paid"
        db.add(order)

    db.flush()
    return created
