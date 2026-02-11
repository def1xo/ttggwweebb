from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_db, get_current_user
from app.db import models

router = APIRouter(prefix="/cart", tags=["cart"])

PROMO_TTL_HOURS = 2
REFERRAL_DISCOUNT_PERCENT = Decimal("5")


# ----- schemas -----
class CartItemOut(BaseModel):
    variant_id: int
    quantity: int
    price: Decimal
    product_id: int
    title: str
    image: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None


class PromoOut(BaseModel):
    code: str
    kind: str  # "special" | "referral"
    discount_percent: Optional[Decimal] = None
    discount_amount: Optional[Decimal] = None
    expires_at: Optional[datetime] = None


class CartOut(BaseModel):
    items: List[CartItemOut]
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    promo: Optional[PromoOut] = None


class CartSetItemIn(BaseModel):
    variant_id: int
    quantity: int = Field(..., ge=0)


class CartAddItemIn(BaseModel):
    variant_id: int
    quantity: int = Field(1, ge=1)


class ApplyPromoIn(BaseModel):
    code: str


# ----- helpers -----
def _now() -> datetime:
    return datetime.utcnow()


def _get_or_create_state(db: Session, user_id: int) -> models.CartState:
    st = db.query(models.CartState).filter(models.CartState.user_id == user_id).one_or_none()
    if not st:
        st = models.CartState(user_id=user_id)
        db.add(st)
        db.flush()
    return st


def _release_reservation(db: Session, user_id: int, promo_code: str) -> None:
    if not promo_code:
        return
    pc = (
        db.query(models.PromoCode)
        .filter(models.PromoCode.code.ilike(promo_code))
        .one_or_none()
    )
    if not pc:
        return
    # delete only temporary reservations (no order, not used)
    db.query(models.PromoReservation).filter(
        models.PromoReservation.user_id == user_id,
        models.PromoReservation.promo_code_id == pc.id,
        models.PromoReservation.used_at.is_(None),
        models.PromoReservation.order_id.is_(None),
    ).delete(synchronize_session=False)


def _cleanup_expired_reservations(db: Session, user_id: int) -> None:
    now = _now()
    db.query(models.PromoReservation).filter(
        models.PromoReservation.user_id == user_id,
        models.PromoReservation.used_at.is_(None),
        models.PromoReservation.order_id.is_(None),
        models.PromoReservation.expires_at.isnot(None),
        models.PromoReservation.expires_at < now,
    ).delete(synchronize_session=False)


def _active_reservation(db: Session, user_id: int, promo_code_id: int) -> Optional[models.PromoReservation]:
    now = _now()
    return (
        db.query(models.PromoReservation)
        .filter(
            models.PromoReservation.user_id == user_id,
            models.PromoReservation.promo_code_id == promo_code_id,
            models.PromoReservation.used_at.is_(None),
            models.PromoReservation.order_id.is_(None),
            ((models.PromoReservation.expires_at.is_(None)) | (models.PromoReservation.expires_at > now)),
        )
        .order_by(models.PromoReservation.reserved_at.desc())
        .first()
    )


def _normalize_code(code: str) -> str:
    return (code or "").strip()


def _resolve_referral_owner(db: Session, code: str) -> Optional[models.User]:
    if not code:
        return None
    return db.query(models.User).filter(models.User.promo_code.ilike(code)).one_or_none()


def _resolve_special_promo(db: Session, code: str) -> Optional[models.PromoCode]:
    if not code:
        return None
    return (
        db.query(models.PromoCode)
        .filter(models.PromoCode.code.ilike(code), models.PromoCode.type == models.PromoType.special)
        .one_or_none()
    )


def _promo_is_active(pc: models.PromoCode) -> bool:
    if not pc:
        return False
    if pc.expires_at and pc.expires_at < _now():
        return False
    if pc.usage_limit is not None and pc.used_count >= pc.usage_limit:
        return False
    return True


def _promo_value_to_percent(raw) -> Decimal:
    """Accept both 0.10 and 10 as '10%'."""
    try:
        v = Decimal(str(raw or 0))
    except Exception:
        v = Decimal("0")
    if v <= 0:
        return Decimal("0")
    if v <= 1:
        return (v * Decimal("100")).quantize(Decimal("0.01"))
    return v.quantize(Decimal("0.01"))


def _calc_cart(db: Session, user: models.User) -> CartOut:
    _cleanup_expired_reservations(db, user.id)
    st = _get_or_create_state(db, user.id)

    # if state points to expired reservation -> drop
    promo_out: Optional[PromoOut] = None
    discount = Decimal("0.00")

    items = (
        db.query(models.CartItem)
        .options(joinedload(models.CartItem.variant).joinedload(models.ProductVariant.product))
        .filter(models.CartItem.user_id == user.id)
        .all()
    )

    out_items: List[CartItemOut] = []
    subtotal = Decimal("0.00")
    for ci in items:
        v = ci.variant
        p = v.product if v else None
        price = Decimal(str(getattr(v, "price", 0) or 0))
        qty = int(ci.quantity or 0)
        subtotal += price * qty
        # try to get a primary image
        image = None
        try:
            imgs = getattr(p, "images", None)
            if isinstance(imgs, list) and imgs:
                first = imgs[0]
                image = first.get("url") if isinstance(first, dict) else str(first)
        except Exception:
            image = None

        size = None
        color = None
        try:
            size = getattr(v.size, "name", None) if v and getattr(v, "size", None) else None
        except Exception:
            size = None
        try:
            color = getattr(v.color, "name", None) if v and getattr(v, "color", None) else None
        except Exception:
            color = None

        out_items.append(
            CartItemOut(
                variant_id=int(ci.variant_id),
                quantity=qty,
                price=price,
                product_id=int(getattr(p, "id", 0) or 0),
                title=str(getattr(p, "title", None) or getattr(p, "name", "Товар")),
                image=image,
                size=size,
                color=color,
            )
        )

    # discount promo
    if st.promo_code:
        pc = _resolve_special_promo(db, st.promo_code)
        if not pc or not _promo_is_active(pc):
            # drop invalid
            _release_reservation(db, user.id, st.promo_code)
            st.promo_code = None
            db.add(st)
            db.flush()
        else:
            resv = _active_reservation(db, user.id, pc.id)
            if not resv:
                st.promo_code = None
                db.add(st)
                db.flush()
            else:
                percent = _promo_value_to_percent(pc.value)
                discount = (subtotal * percent / Decimal("100")).quantize(Decimal("0.01"))
                promo_out = PromoOut(
                    code=pc.code,
                    kind="special",
                    discount_percent=percent,
                    discount_amount=discount,
                    expires_at=resv.expires_at,
                )

    # referral promo (fixed discount)
    if not promo_out and st.referral_code:
        owner = _resolve_referral_owner(db, st.referral_code)
        if not owner:
            st.referral_code = None
            db.add(st)
            db.flush()
        else:
            percent = REFERRAL_DISCOUNT_PERCENT
            discount = (subtotal * percent / Decimal("100")).quantize(Decimal("0.01"))
            promo_out = PromoOut(code=st.referral_code, kind="referral", discount_percent=percent, discount_amount=discount)

    total = (subtotal - discount).quantize(Decimal("0.01"))
    return CartOut(items=out_items, subtotal=subtotal.quantize(Decimal("0.01")), discount=discount, total=total, promo=promo_out)


# ----- endpoints -----
@router.get("", response_model=CartOut)
@router.get("/", response_model=CartOut)
def get_cart(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _calc_cart(db, user)


@router.post("/items", response_model=CartOut)
def set_item(payload: CartSetItemIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    ci = db.query(models.CartItem).filter(models.CartItem.user_id == user.id, models.CartItem.variant_id == payload.variant_id).one_or_none()
    if payload.quantity <= 0:
        if ci:
            db.delete(ci)
            db.commit()
        return _calc_cart(db, user)

    # validate variant exists
    var = db.query(models.ProductVariant).filter(models.ProductVariant.id == payload.variant_id).one_or_none()
    if not var:
        raise HTTPException(status_code=404, detail="variant not found")

    if not ci:
        ci = models.CartItem(user_id=user.id, variant_id=payload.variant_id, quantity=payload.quantity)
        db.add(ci)
    else:
        ci.quantity = payload.quantity
        db.add(ci)
    db.commit()
    return _calc_cart(db, user)


@router.post("/items/add", response_model=CartOut)
def add_item(payload: CartAddItemIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    # validate variant exists
    var = db.query(models.ProductVariant).filter(models.ProductVariant.id == payload.variant_id).one_or_none()
    if not var:
        raise HTTPException(status_code=404, detail="variant not found")

    ci = db.query(models.CartItem).filter(models.CartItem.user_id == user.id, models.CartItem.variant_id == payload.variant_id).one_or_none()
    if not ci:
        ci = models.CartItem(user_id=user.id, variant_id=payload.variant_id, quantity=payload.quantity)
        db.add(ci)
    else:
        ci.quantity = int(ci.quantity or 0) + int(payload.quantity or 0)
        db.add(ci)
    db.commit()
    return _calc_cart(db, user)


@router.delete("/items/{variant_id}", response_model=CartOut)
def delete_item(variant_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.query(models.CartItem).filter(models.CartItem.user_id == user.id, models.CartItem.variant_id == variant_id).delete(synchronize_session=False)
    db.commit()
    return _calc_cart(db, user)


@router.delete("/clear", response_model=CartOut)
def clear_cart(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    st = _get_or_create_state(db, user.id)
    if st.promo_code:
        _release_reservation(db, user.id, st.promo_code)
    st.promo_code = None
    st.referral_code = None
    db.query(models.CartItem).filter(models.CartItem.user_id == user.id).delete(synchronize_session=False)
    db.add(st)
    db.commit()
    return _calc_cart(db, user)


@router.post("/promo", response_model=CartOut)
def apply_promo(payload: ApplyPromoIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    code = _normalize_code(payload.code)
    if not code:
        raise HTTPException(status_code=400, detail="empty promo code")

    st = _get_or_create_state(db, user.id)

    # enforce one promo per user lifetime (including referral)
    if user.promo_used_code:
        raise HTTPException(status_code=400, detail="promo already used")

    # prevent switching promos while pending
    if user.promo_pending_code and user.promo_pending_code.strip() and user.promo_pending_code.strip().lower() != code.lower():
        raise HTTPException(status_code=400, detail="you already have a pending promo for another order")

    # referral code
    owner = _resolve_referral_owner(db, code)
    if owner and owner.id != user.id:
        st.referral_code = code
        if st.promo_code:
            _release_reservation(db, user.id, st.promo_code)
        st.promo_code = None
        db.add(st)
        db.commit()
        return _calc_cart(db, user)

    # special discount code
    pc = _resolve_special_promo(db, code)
    if not pc:
        raise HTTPException(status_code=404, detail="promo not found")
    if not _promo_is_active(pc):
        raise HTTPException(status_code=400, detail="promo not active")

    # make / refresh reservation
    now = _now()
    resv = _active_reservation(db, user.id, pc.id)
    if not resv:
        resv = models.PromoReservation(
            promo_code_id=pc.id,
            user_id=user.id,
            reserved_at=now,
            expires_at=now + timedelta(hours=PROMO_TTL_HOURS),
        )
        db.add(resv)
    else:
        resv.expires_at = now + timedelta(hours=PROMO_TTL_HOURS)
        db.add(resv)

    # store state
    st.promo_code = pc.code
    st.referral_code = None
    db.add(st)
    db.commit()

    return _calc_cart(db, user)


@router.delete("/promo", response_model=CartOut)
def remove_promo(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    st = _get_or_create_state(db, user.id)
    if st.promo_code:
        _release_reservation(db, user.id, st.promo_code)
    st.promo_code = None
    st.referral_code = None
    db.add(st)
    db.commit()
    return _calc_cart(db, user)
