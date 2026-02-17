from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi import Path, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models
from app.services import media_store

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products(
    category_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    try:
        query = db.query(models.Product).filter(models.Product.visible == True)
        if category_id:
            query = query.filter(models.Product.category_id == category_id)
        if q:
            query = query.filter(models.Product.title.ilike(f"%{q}%"))
        total = query.count()
        items = (
            query.order_by(models.Product.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
    except Exception:
        return {"items": [], "total": 0, "page": page, "per_page": per_page}
    result = []
    for p in items:
        variants = []
        sizes = set()
        colors = set()
        min_variant_price: float | None = None
        has_stock = False
        for v in (p.variants or []):
            try:
                if getattr(v, "size", None) and v.size and v.size.name:
                    sizes.add(v.size.name)
                if getattr(v, "color", None) and v.color and v.color.name:
                    colors.add(v.color.name)
            except Exception:
                pass
            variants.append(
                {
                    "id": v.id,
                    "price": float(v.price or 0),
                    "stock": v.stock_quantity,
                    "size": (v.size.name if getattr(v, "size", None) and v.size else None),
                    "color": (v.color.name if getattr(v, "color", None) and v.color else None),
                    "images": (v.images or None),
                }
            )
            vp = float(v.price or 0)
            if vp > 0:
                min_variant_price = vp if min_variant_price is None else min(min_variant_price, vp)
            if int(v.stock_quantity or 0) > 0:
                has_stock = True

        img_urls = []
        try:
            img_urls = [im.url for im in sorted((p.images or []), key=lambda x: (x.sort or 0, x.id))]
        except Exception:
            img_urls = []
        result.append(
            {
                "id": p.id,
                # alias for frontend compatibility
                "name": p.title,
                "title": p.title,
                "slug": p.slug,
                "base_price": float(p.base_price or 0),
                "price": float(p.base_price or 0),
                "currency": getattr(p, "currency", "RUB"),
                "default_image": p.default_image,
                "images": img_urls,
                "gallery_count": len(img_urls),
                "category_id": p.category_id,
                "min_variant_price": min_variant_price,
                "has_stock": has_stock,
                "sizes": sorted(list(sizes), key=lambda x: float(x) if str(x).replace('.', '', 1).isdigit() else str(x)),
                "colors": sorted(list(colors)),
                "variants": variants,
            }
        )
    return {"items": result, "total": total, "page": page, "per_page": per_page}


@router.get("/{product_id}")
def get_product(product_id: int = Path(...), db: Session = Depends(get_db)):
    p = db.query(models.Product).get(product_id)
    if not p or not p.visible:
        raise HTTPException(status_code=404, detail="product not found")
    img_urls = []
    try:
        img_urls = [im.url for im in sorted((p.images or []), key=lambda x: (x.sort or 0, x.id))]
    except Exception:
        img_urls = []

    sizes = sorted({(v.size.name if getattr(v, "size", None) and v.size else None) for v in (p.variants or []) if (getattr(v, "size", None) and v.size and v.size.name)}, key=lambda x: float(x) if str(x).replace('.', '', 1).isdigit() else str(x))
    colors = sorted({(v.color.name if getattr(v, "color", None) and v.color else None) for v in (p.variants or []) if (getattr(v, "color", None) and v.color and v.color.name)})

    return {
        "id": p.id,
        "name": p.title,
        "title": p.title,
        "description": p.description,
        "base_price": float(p.base_price or 0),
        "price": float(p.base_price or 0),
        "default_image": p.default_image,
        "images": img_urls,
        "sizes": sizes,
        "colors": colors,
        "variants": [
            {
                "id": v.id,
                "price": float(v.price or 0),
                "stock": v.stock_quantity,
                "size": (v.size.name if getattr(v, "size", None) and v.size else None),
                "color": (v.color.name if getattr(v, "color", None) and v.color else None),
                "images": v.images,
            }
            for v in p.variants
        ],
    }


@router.get("/{product_id}/related")
def get_related_products(
    product_id: int = Path(...),
    limit: int = Query(8, ge=1, le=24),
    db: Session = Depends(get_db),
):
    p = db.query(models.Product).get(product_id)
    if not p or not p.visible:
        raise HTTPException(status_code=404, detail="product not found")

    # 1) co-purchase candidates from historical orders
    source_variant_ids = [v.id for v in (p.variants or [])]
    ranked_product_ids: List[int] = []

    if source_variant_ids:
        order_ids_q = (
            db.query(models.OrderItem.order_id)
            .filter(models.OrderItem.variant_id.in_(source_variant_ids))
            .distinct()
        )
        order_ids = [row[0] for row in order_ids_q.all()]

        if order_ids:
            rows = (
                db.query(
                    models.ProductVariant.product_id,
                    func.sum(models.OrderItem.quantity).label("score"),
                )
                .join(models.OrderItem, models.OrderItem.variant_id == models.ProductVariant.id)
                .filter(models.OrderItem.order_id.in_(order_ids))
                .filter(models.ProductVariant.product_id != p.id)
                .group_by(models.ProductVariant.product_id)
                .order_by(func.sum(models.OrderItem.quantity).desc())
                .limit(limit * 3)
                .all()
            )
            ranked_product_ids = [int(r[0]) for r in rows if r and r[0]]

    # 2) materialize co-purchase products preserving rank
    selected: List[models.Product] = []
    selected_ids = set()
    if ranked_product_ids:
        candidates = (
            db.query(models.Product)
            .filter(models.Product.visible == True, models.Product.id.in_(ranked_product_ids))
            .all()
        )
        by_id = {x.id: x for x in candidates}
        for pid in ranked_product_ids:
            x = by_id.get(pid)
            if not x:
                continue
            selected.append(x)
            selected_ids.add(x.id)
            if len(selected) >= limit:
                break

    # 3) fallback to same-category newest if not enough
    if len(selected) < limit:
        q = db.query(models.Product).filter(models.Product.visible == True, models.Product.id != p.id)
        if p.category_id:
            q = q.filter(models.Product.category_id == p.category_id)
        fallback = q.order_by(models.Product.created_at.desc()).limit(limit * 3).all()
        for x in fallback:
            if x.id in selected_ids:
                continue
            selected.append(x)
            selected_ids.add(x.id)
            if len(selected) >= limit:
                break

    result = []
    for rp in selected[:limit]:
        img_urls = []
        try:
            img_urls = [im.url for im in sorted((rp.images or []), key=lambda x: (x.sort or 0, x.id))]
        except Exception:
            img_urls = []

        result.append(
            {
                "id": rp.id,
                "name": rp.title,
                "title": rp.title,
                "slug": rp.slug,
                "base_price": float(rp.base_price or 0),
                "price": float(rp.base_price or 0),
                "default_image": rp.default_image,
                "images": img_urls,
                "category_id": rp.category_id,
            }
        )

    return {"items": result, "total": len(result)}


# Admin endpoints for product images/files (multipart)
@router.post("/admin/{product_id}/upload_image")
def upload_product_image(product_id: int = Path(...), file: UploadFile = File(...), db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    p = db.query(models.Product).get(product_id)
    if not p:
        raise HTTPException(status_code=404, detail="product not found")
    # save file (local uploads)
    try:
        url = media_store.save_upload_file_to_local(file, folder="products")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    img = models.ProductImage(product_id=product_id, url=url)
    db.add(img)
    db.commit()
    db.refresh(img)
    return {"id": img.id, "url": img.url}
