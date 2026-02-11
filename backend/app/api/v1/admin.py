from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from decimal import Decimal
import os
import re

import requests

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models

router = APIRouter(prefix="/admin", tags=["admin"])


def _send_admin_telegram_message(text: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("ADMIN_TELEGRAM_CHAT_ID") or "").strip()
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


def _slug_to_hashtag(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9а-яё]+", "_", s, flags=re.I)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "разное"


def _build_order_supply_info(db: Session, order: models.Order) -> list[str]:
    lines: list[str] = []
    order_items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).all()
    if not order_items:
        return ["• Нет товарных позиций"]

    for idx, item in enumerate(order_items, start=1):
        variant = db.query(models.ProductVariant).get(item.variant_id) if item.variant_id else None
        product = db.query(models.Product).get(variant.product_id) if variant else None
        size_name = "—"
        color_name = "—"
        if variant and variant.size_id:
            size = db.query(models.Size).get(variant.size_id)
            size_name = (size.name if size else "—")
        if variant and variant.color_id:
            color = db.query(models.Color).get(variant.color_id)
            color_name = (color.name if color else "—")

        # optional estimated cost from latest ProductCost
        cost = None
        if variant:
            latest_cost = (
                db.query(models.ProductCost)
                .filter(models.ProductCost.variant_id == variant.id)
                .order_by(models.ProductCost.created_at.desc(), models.ProductCost.id.desc())
                .first()
            )
            cost = float(latest_cost.cost_price) if latest_cost and latest_cost.cost_price is not None else None

        retail = float(item.price or 0)
        qty = int(item.quantity or 0)
        cost_txt = f"{cost:.0f} ₽" if isinstance(cost, float) and cost > 0 else "н/д"
        lines.append(
            f"{idx}) {(product.title if product else 'Товар')} | size: {size_name} | color: {color_name}\n"
            f"   qty: {qty} • retail: {retail:.0f} ₽ • закупка(оценка): {cost_txt} • поставщик: не назначен"
        )
    return lines


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




class NewsManageIn(BaseModel):
    title: str
    text: str | None = None
    images: list[str] | None = None


class CatalogTelegramIn(BaseModel):
    template: str | None = None
    only_visible: bool = True
    limit: int = 200

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
    comps = []
    status_payload = {"status": "paid", "order_id": order.id, "commissions_created": 0}
    try:
        from app.services.commissions import compute_and_apply_commissions
        comps = compute_and_apply_commissions(db, order, admin_user_id=admin.id)
        db.commit()
        status_payload = {"status": str(order.status), "order_id": order.id, "commissions_created": len(comps)}
    except Exception:
        db.rollback()
        # fallback: just mark paid
        order.status = "paid"
        db.add(order)
        db.commit()
        status_payload = {"status": "marked_paid_manual", "order_id": order.id, "commissions_created": 0}

    base_url = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    proof = (order.payment_screenshot or "").strip()
    if proof.startswith("/") and base_url:
        proof_link = f"{base_url.rstrip('/')}{proof}"
    else:
        proof_link = proof or "—"
    supply_lines = _build_order_supply_info(db, order)
    msg = (
        f"✅ Заказ подтверждён #{order.id}\n"
        f"Сумма: {float(order.total_amount or 0):.0f} ₽\n"
        f"Клиент: {(order.fio or '—')} | {(order.phone or '—')}\n"
        f"Статус: {status_payload.get('status')}\n"
        f"Пруф: {proof_link}\n\n"
        f"Позиции / закупка:\n" + "\n".join(supply_lines)
    )
    sent = _send_admin_telegram_message(msg)
    status_payload["telegram_notified"] = bool(sent)
    return status_payload




# ---------- News management ----------
@router.get("/news")
def admin_list_news(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    items = db.query(models.News).order_by(models.News.created_at.desc()).limit(limit).all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "text": n.text,
            "images": getattr(n, "images", None) or [],
            "created_at": n.created_at.isoformat() if getattr(n, "created_at", None) else None,
        }
        for n in items
    ]


@router.post("/news")
def admin_create_news(payload: NewsManageIn, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    item = models.News(title=title, text=(payload.text or "").strip() or None, images=(payload.images or []) or None)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "title": item.title, "text": item.text, "images": item.images or []}


@router.patch("/news/{news_id}")
def admin_patch_news(news_id: int, payload: NewsManageIn, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    item = db.query(models.News).get(news_id)
    if not item:
        raise HTTPException(status_code=404, detail="news not found")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    item.title = title
    item.text = (payload.text or "").strip() or None
    item.images = (payload.images or []) or None
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "title": item.title, "text": item.text, "images": item.images or []}


@router.delete("/news/{news_id}")
def admin_delete_news(news_id: int, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    item = db.query(models.News).get(news_id)
    if not item:
        raise HTTPException(status_code=404, detail="news not found")
    db.delete(item)
    db.commit()
    return {"status": "deleted", "id": news_id}


@router.post("/catalog/send-to-telegram")
def admin_send_catalog_to_telegram(payload: CatalogTelegramIn, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    q = db.query(models.Product)
    if payload.only_visible:
        q = q.filter(models.Product.visible == True)
    products = q.order_by(models.Product.id.asc()).limit(max(1, min(int(payload.limit or 200), 500))).all()
    if not products:
        return {"ok": False, "sent": 0, "detail": "catalog empty"}

    tmpl = (payload.template or "").strip() or "#{category}\n{title}\nцена: {price} ₽"
    sent = 0
    for p in products:
        cat = db.query(models.Category).get(p.category_id) if p.category_id else None
        text = tmpl.format(
            category=_slug_to_hashtag(cat.slug if cat else None),
            title=p.title,
            price=f"{float(p.base_price or 0):.0f}",
            slug=p.slug or "",
            id=p.id,
        )
        if _send_admin_telegram_message(text):
            sent += 1
    return {"ok": sent > 0, "sent": sent, "total": len(products)}


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
