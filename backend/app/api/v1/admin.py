from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from decimal import Decimal

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Schemas ----------
class ProductOut(BaseModel):
    id: int
    title: str
    base_price: Decimal
    category_id: Optional[int] = None
    default_image: Optional[str] = None
    visible: bool

    class Config:
        orm_mode = True


class CategoryOut(BaseModel):
    id: int
    name: str
    slug: Optional[str] = None
    image_url: Optional[str] = None

    class Config:
        orm_mode = True


class OrderOut(BaseModel):
    id: int
    user_id: int
    status: str
    total_amount: Decimal
    fio: Optional[str] = None
    payment_screenshot: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        orm_mode = True


class WithdrawOut(BaseModel):
    id: int
    requester_user_id: int
    amount: Decimal
    status: str
    target_details: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None

    class Config:
        orm_mode = True


# ---------- Products ----------
@router.get("/products", response_model=List[ProductOut])
def admin_list_products(q: Optional[str] = Query(None), page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    query = db.query(models.Product)
    if q:
        query = query.filter(models.Product.title.ilike(f"%{q}%"))
    items = query.order_by(models.Product.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return items


@router.post("/products", response_model=ProductOut)
def admin_create_product(payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    title = payload.get("title") or payload.get("name")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    p = models.Product(
        title=title,
        slug=payload.get("slug") or None,
        description=payload.get("description"),
        base_price=Decimal(str(payload.get("base_price", payload.get("price", 0)))),
        currency=payload.get("currency", "RUB"),
        category_id=payload.get("category_id"),
        default_image=payload.get("default_image"),
        visible=bool(payload.get("visible", False)),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.patch("/products/{product_id}", response_model=ProductOut)
def admin_update_product(product_id: int = Path(...), payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    p = db.query(models.Product).get(product_id)
    if not p:
        raise HTTPException(status_code=404, detail="product not found")
    # allowed updates
    for fld in ("title", "slug", "description", "default_image", "visible", "currency"):
        if fld in payload:
            setattr(p, fld, payload[fld])
    if "base_price" in payload or "price" in payload:
        try:
            p.base_price = Decimal(str(payload.get("base_price", payload.get("price", p.base_price))))
        except Exception:
            pass
    if "category_id" in payload:
        p.category_id = payload.get("category_id")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/products/{product_id}")
def admin_delete_product(product_id: int = Path(...), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    p = db.query(models.Product).get(product_id)
    if not p:
        raise HTTPException(status_code=404, detail="product not found")
    db.delete(p)
    db.commit()
    return {"status": "deleted", "id": product_id}


# ---------- Categories ----------
@router.get("/categories", response_model=List[CategoryOut])
def admin_list_categories(db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    return db.query(models.Category).order_by(models.Category.name.asc()).all()


@router.post("/categories", response_model=CategoryOut)
def admin_create_category(payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    slug = payload.get("slug") or (name.lower().replace(" ", "-"))
    cat = models.Category(name=name, slug=slug, image_url=payload.get("image_url"))
    db.add(cat)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="category create failed (maybe duplicate)")
    db.refresh(cat)
    return cat


@router.delete("/categories/{category_id}")
def admin_delete_category(category_id: int = Path(...), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    c = db.query(models.Category).get(category_id)
    if not c:
        raise HTTPException(status_code=404, detail="category not found")
    db.delete(c)
    db.commit()
    return {"status": "deleted", "id": category_id}


# ---------- Orders ----------
@router.get("/orders", response_model=List[OrderOut])
def admin_list_orders(status: Optional[str] = Query(None), page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    q = db.query(models.Order)
    if status:
        q = q.filter(models.Order.status == status)
    items = q.order_by(models.Order.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return items


@router.post("/orders/{order_id}/confirm")
def admin_confirm_order(order_id: int = Path(...), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    order = db.query(models.Order).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    # order_status enum does not contain "confirmed".
    if order.status in ("paid", "processing", "sent", "received"):
        return {"status": "already_processed", "order_id": order.id}
    # try to compute commissions if service available
    try:
        from app.services.commissions import compute_and_apply_commissions
        comps = compute_and_apply_commissions(db, order, admin_user_id=admin.id)
        db.commit()
    except Exception:
        db.rollback()
        # fallback: just mark paid
        order.status = "paid"
        db.add(order)
        db.commit()
        return {"status": "marked_paid_manual", "order_id": order.id}
    # We mark the order as "paid" (or subsequent statuses); no separate "confirmed" status exists.
    return {"status": str(order.status), "order_id": order.id, "commissions_created": len(comps)}


# ---------- Withdrawals ----------
@router.get("/withdrawals", response_model=List[WithdrawOut])
def admin_list_withdrawals(page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    q = db.query(models.WithdrawRequest).order_by(models.WithdrawRequest.created_at.desc())
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return items


@router.post("/withdrawals/{withdraw_id}/mark_paid")
def admin_mark_withdraw_paid(withdraw_id: int = Path(...), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    wr = db.query(models.WithdrawRequest).get(withdraw_id)
    if not wr:
        raise HTTPException(status_code=404, detail="withdraw not found")
    if wr.status == "paid":
        return {"status": "already_paid", "withdraw_id": wr.id}
    # Debit requester balance if possible
    requester = db.query(models.User).get(wr.requester_user_id)
    if not requester:
        raise HTTPException(status_code=404, detail="requester not found")
    if Decimal(str(requester.balance or 0)) < Decimal(str(wr.amount or 0)):
        raise HTTPException(status_code=400, detail="insufficient balance")
    requester.balance = Decimal(str(requester.balance or 0)) - Decimal(str(wr.amount or 0))
    wr.status = "paid"
    wr.admin_user_id = admin.id
    wr.paid_at = wr.paid_at or None
    db.add(requester)
    db.add(wr)
    db.commit()
    return {"status": "paid", "withdraw_id": wr.id}
