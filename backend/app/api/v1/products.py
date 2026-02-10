from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi import Path, Query
from sqlalchemy.orm import Session
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
    result = []
    for p in items:
        variants = []
        sizes = set()
        colors = set()
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
                "category_id": p.category_id,
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
