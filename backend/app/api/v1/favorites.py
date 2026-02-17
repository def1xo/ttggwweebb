from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_db, get_current_user
from app.db import models


router = APIRouter(prefix="/favorites", tags=["favorites"])


def _serialize_product(p: models.Product) -> Dict[str, Any]:
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

    img_urls: List[str] = []
    try:
        img_urls = [im.url for im in sorted((p.images or []), key=lambda x: (x.sort or 0, x.id))]
    except Exception:
        img_urls = []

    return {
        "id": p.id,
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


@router.get("/ids")
def list_favorite_ids(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        ids = [int(x[0]) for x in db.query(models.Favorite.product_id).filter(models.Favorite.user_id == user.id).all()]
    except Exception:
        return {"items": []}
    return {"items": ids}


@router.get("")
@router.get("/")
def list_favorites(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    try:
        favs = (
            db.query(models.Favorite)
            .options(
                joinedload(models.Favorite.product)
                .joinedload(models.Product.images),
                joinedload(models.Favorite.product)
                .joinedload(models.Product.variants)
                .joinedload(models.ProductVariant.size),
                joinedload(models.Favorite.product)
                .joinedload(models.Product.variants)
                .joinedload(models.ProductVariant.color),
            )
            .filter(models.Favorite.user_id == user.id)
            .order_by(models.Favorite.created_at.desc())
            .all()
        )
    except Exception:
        return {"items": []}
    products = []
    for f in favs:
        p = f.product
        if not p or not getattr(p, "visible", True):
            continue
        products.append(_serialize_product(p))
    return {"items": products}


@router.post("/{product_id}")
def add_favorite(
    product_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p = db.query(models.Product).get(product_id)
    if not p or not p.visible:
        raise HTTPException(status_code=404, detail="product not found")
    fav = models.Favorite(user_id=user.id, product_id=product_id)
    db.add(fav)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # already exists
    return {"ok": True}


@router.delete("/{product_id}")
def remove_favorite(
    product_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    db.query(models.Favorite).filter(models.Favorite.user_id == user.id, models.Favorite.product_id == product_id).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}
