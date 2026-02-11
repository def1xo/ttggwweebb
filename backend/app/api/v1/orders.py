from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body, Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_db, get_current_user, get_current_manager_user
from app.db import models
from app.services.media_store import save_upload_file_to_local

router = APIRouter(tags=["orders"])  # prefix is added in main.py


def _now() -> datetime:
    return datetime.utcnow()


def _to_decimal(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


FREE_DELIVERY_FROM = Decimal("5000")
DELIVERY_PRICE = Decimal("449")
REFERRAL_DISCOUNT_PERCENT = Decimal("5")


def _promo_value_to_percent(val: Decimal) -> Decimal:
    """PromoCode.value can be stored as 10 (percent) or 0.10 (fraction)."""
    if val is None:
        return Decimal("0")
    if val <= Decimal("1"):
        return (val * Decimal("100"))
    return val


def _resolve_referral(db: Session, code: str) -> Optional[models.User]:
    if not code:
        return None
    return db.query(models.User).filter(models.User.promo_code.ilike(code)).one_or_none()


def _get_cart_items(db: Session, user_id: int) -> List[models.CartItem]:
    return (
        db.query(models.CartItem)
        .options(joinedload(models.CartItem.variant).joinedload(models.ProductVariant.product))
        .filter(models.CartItem.user_id == user_id)
        .all()
    )


def _get_cart_state(db: Session, user_id: int) -> Optional[models.CartState]:
    return db.query(models.CartState).filter(models.CartState.user_id == user_id).one_or_none()


def _active_reservation(db: Session, user_id: int, promo_code_id: int) -> Optional[models.PromoReservation]:
    now = _now()
    q = (
        db.query(models.PromoReservation)
        .filter(models.PromoReservation.user_id == user_id)
        .filter(models.PromoReservation.promo_code_id == promo_code_id)
        .filter(models.PromoReservation.used_at.is_(None))
        .filter(
            (models.PromoReservation.expires_at.is_(None))
            | (models.PromoReservation.expires_at > now)
        )
        .order_by(models.PromoReservation.reserved_at.desc())
    )
    return q.first()


class OrderCreateIn(BaseModel):
    fio: str = Field(..., min_length=1, max_length=255)
    phone: Optional[str] = Field(None, max_length=64)
    delivery_type: Optional[str] = Field(None, max_length=128)
    delivery_address: Optional[str] = None
    note: Optional[str] = None
    promo_code: Optional[str] = Field(None, max_length=64)


class OrderItemOut(BaseModel):
    variant_id: int
    quantity: int
    price: Decimal

    class Config:
        orm_mode = True


class OrderOut(BaseModel):
    id: int
    status: str
    total_amount: Decimal
    subtotal_amount: Decimal
    discount_amount: Decimal
    promo_code: Optional[str] = None
    promo_kind: Optional[str] = None
    payment_screenshot: Optional[str] = None
    payment_uploaded_at: Optional[datetime] = None
    created_at: datetime
    items: List[OrderItemOut] = []

    class Config:
        orm_mode = True


@router.get("/orders/my", response_model=List[OrderOut])
@router.get("/orders/me", response_model=List[OrderOut])
def my_orders(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    items = (
        db.query(models.Order)
        .options(joinedload(models.Order.items))
        .filter(models.Order.user_id == user.id)
        .order_by(models.Order.created_at.desc())
        .all()
    )
    return items


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int = Path(..., ge=1), db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    order = (
        db.query(models.Order)
        .options(joinedload(models.Order.items))
        .filter(models.Order.id == order_id)
        .one_or_none()
    )
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    if order.user_id != user.id and str(getattr(user.role, "value", user.role)) != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return order


@router.post("/orders", response_model=OrderOut)
def create_order(
    payload: OrderCreateIn = Body(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # items from server cart
    cart_items = _get_cart_items(db, user.id)
    if not cart_items:
        raise HTTPException(status_code=400, detail="cart is empty")

    st = _get_cart_state(db, user.id)
    referral_code = (st.referral_code if st else None) or None
    promo_code_str = (st.promo_code if st else None) or None
    payload_code = str(payload.promo_code).strip() if payload.promo_code else None
    if not promo_code_str and payload_code:
        promo_code_str = payload_code

    subtotal = Decimal("0")
    for ci in cart_items:
        price = _to_decimal(getattr(ci.variant, "price", 0))
        subtotal += price * Decimal(int(ci.quantity or 0))

    discount = Decimal("0")
    promo_kind = None
    promo_special_id = None
    promo_discount_percent = None

    # Apply special promo (discount)
    if promo_code_str:
        promo = db.query(models.PromoCode).filter(models.PromoCode.code.ilike(promo_code_str)).one_or_none()
        promo_type = str(getattr(getattr(promo, "type", None), "value", getattr(promo, "type", ""))).lower() if promo else ""
        if promo and promo_type in {"special", "admin"}:
            # enforce "one promo per life" + pending lock
            if user.promo_used_code:
                raise HTTPException(status_code=400, detail="promo already used")
            if user.promo_pending_code and str(user.promo_pending_code).lower() != str(promo.code).lower():
                raise HTTPException(status_code=400, detail="another promo is pending")

            resv = _active_reservation(db, user.id, promo.id)
            if not resv:
                # Fallback: if promo came directly in payload (legacy clients / race),
                # still apply discount instead of dropping to 0 silently.
                # Pending lock will still be set below for created order.
                pass

            percent = _promo_value_to_percent(_to_decimal(promo.value))
            promo_discount_percent = percent
            discount = (subtotal * percent / Decimal("100")).quantize(Decimal("0.01"))
            promo_kind = "special"
            promo_special_id = promo.id
        else:
            # if promo is invalid for discount, ignore
            promo_code_str = None

    # If code is not a special promo, treat it as potential referral code fallback.
    if promo_code_str and not referral_code:
        owner = _resolve_referral(db, promo_code_str)
        if owner and owner.id != user.id:
            referral_code = promo_code_str

    # Apply referral promo discount (5%) if no special promo is active
    if discount == Decimal("0") and not referral_code and payload_code:
        # fallback for clients where cart state wasn't persisted but code was sent in payload
        owner = _resolve_referral(db, payload_code)
        if owner and owner.id != user.id:
            referral_code = payload_code

    if discount == Decimal("0") and referral_code:
        owner = _resolve_referral(db, referral_code)
        if owner and owner.id != user.id:
            promo_discount_percent = REFERRAL_DISCOUNT_PERCENT
            discount = (subtotal * promo_discount_percent / Decimal("100")).quantize(Decimal("0.01"))
            promo_kind = "referral"

    delivery_price = Decimal("0")
    if payload.delivery_address and subtotal < FREE_DELIVERY_FROM:
        delivery_price = DELIVERY_PRICE

    total_amount = (subtotal - discount + delivery_price).quantize(Decimal("0.01"))

    # Resolve commissions attribution by referral code
    manager_id = None
    assistant_id = None
    promo_owner_user_id = None
    if referral_code:
        owner = _resolve_referral(db, referral_code)
        if owner:
            promo_owner_user_id = owner.id
            role = str(getattr(owner.role, "value", owner.role))
            if role == "manager":
                manager_id = owner.id
            elif role == "assistant":
                assistant_id = owner.id
                manager_id = owner.manager_id

    order = models.Order(
        user_id=user.id,
        manager_id=manager_id,
        assistant_id=assistant_id,
        promo_code=promo_code_str or referral_code,
        promo_kind=promo_kind or ("referral" if referral_code else None),
        promo_discount_percent=promo_discount_percent,
        promo_owner_user_id=promo_owner_user_id,
        promo_special_id=promo_special_id,
        subtotal_amount=subtotal,
        discount_amount=discount,
        total_amount=total_amount,
        delivery_price=delivery_price,
        delivery_type=payload.delivery_type,
        delivery_address=payload.delivery_address,
        fio=payload.fio,
        phone=payload.phone,
        note=payload.note,
        status=models.OrderStatus.awaiting_payment,
    )
    db.add(order)
    db.flush()  # get order.id

    # items
    for ci in cart_items:
        price = _to_decimal(getattr(ci.variant, "price", 0))
        oi = models.OrderItem(order_id=order.id, variant_id=ci.variant_id, quantity=ci.quantity, price=price)
        db.add(oi)

    # promo pending lock (special promos only)
    if promo_kind == "special" and promo_code_str:
        user.promo_pending_code = promo_code_str
        user.promo_pending_order_id = order.id
        db.add(user)
        # attach reservation to order and make it non-expiring (until admin confirms or order cancelled)
        promo = db.query(models.PromoCode).filter(models.PromoCode.id == promo_special_id).one_or_none()
        if promo:
            resv = _active_reservation(db, user.id, promo.id)
            if resv:
                resv.order_id = order.id
                resv.expires_at = None
                db.add(resv)

    # clear cart + state
    db.query(models.CartItem).filter(models.CartItem.user_id == user.id).delete()
    if st:
        st.promo_code = None
        st.referral_code = None
        db.add(st)

    db.commit()
    db.refresh(order)
    order = db.query(models.Order).options(joinedload(models.Order.items)).get(order.id)

    # NOTE: Админу шлём уведомление только после загрузки чека (payment-proof).

    return order


@router.post("/orders/{order_id}/payment-proof")
def upload_payment_proof(
    order_id: int = Path(..., ge=1),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    order = db.query(models.Order).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")

    try:
        url = save_upload_file_to_local(file, folder="payment_proofs")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    order.payment_screenshot = url
    order.payment_uploaded_at = _now()
    order.status = models.OrderStatus.paid
    db.add(order)
    db.commit()

    # notify admin that proof uploaded
    try:
        from app.core.celery_app import celery_app

        celery_app.send_task("tasks.notify_admin_payment_proof", args=[order.id])
    except Exception:
        pass

    return {"ok": True, "order_id": order.id, "payment_screenshot": url, "status": str(order.status)}


# Legacy manager/admin endpoint (kept for compatibility): confirms payment (moves to processing + commissions)
@router.post("/orders/{order_id}/confirm_payment")
def confirm_payment_legacy(
    order_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    manager: models.User = Depends(get_current_manager_user),
):
    # delegate to admin logic: set processing + commissions
    from app.api.v1.admin_orders import admin_confirm_payment

    return admin_confirm_payment(order_id=order_id, db=db, admin=manager)
