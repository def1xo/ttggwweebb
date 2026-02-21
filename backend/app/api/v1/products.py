from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi import Path, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models
from app.services import media_store
from app.services.color_detection import normalize_color_key, detect_product_colors_from_photos

router = APIRouter(prefix="/products", tags=["products"])


def _images_overlap_ratio(a: list[str], b: list[str]) -> float:
    sa = {str(x).strip() for x in (a or []) if str(x).strip()}
    sb = {str(x).strip() for x in (b or []) if str(x).strip()}
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    base = max(1, min(len(sa), len(sb)))
    return inter / base


def _build_color_payload(p: models.Product) -> Dict[str, Any]:
    canonical = normalize_color_key(getattr(p, "detected_color", None)) if getattr(p, "detected_color", None) else None
    variants = list(getattr(p, "variants", []) or [])
    ordered_images = sorted((p.images or []), key=lambda x: ((x.sort or 0), x.id))
    base_images = [im.url for im in ordered_images]

    color_groups: Dict[str, Dict[str, Any]] = {}
    for v in variants:
        raw_color = (v.color.name if getattr(v, "color", None) and v.color and v.color.name else None) or getattr(p, "detected_color", None) or "unknown"
        color_name = normalize_color_key(raw_color) or str(raw_color)
        grp = color_groups.setdefault(color_name, {"color": color_name, "variant_ids": [], "images": []})
        grp["variant_ids"].append(v.id)
        for u in (v.images or []):
            if u and u not in grp["images"]:
                grp["images"].append(u)

    for grp in color_groups.values():
        if not grp["images"]:
            grp["images"] = list(base_images)

    available = sorted([k for k in color_groups.keys() if k and k != "unknown"])
    fallback_single = normalize_color_key(canonical or (available[0] if available else "multicolor")) or "multicolor"
    detected_map = detect_product_colors_from_photos(base_images)
    color_keys = [normalize_color_key(x) for x in (detected_map.get("color_keys") or []) if normalize_color_key(x)]
    if not color_keys:
        color_keys = [fallback_single]

    photo_keys = detected_map.get("photo_color_keys") or []
    images_by_color: Dict[str, list[str]] = {}
    if len(photo_keys) == len(base_images) and photo_keys:
        for idx, img in enumerate(base_images):
            key = normalize_color_key(photo_keys[idx]) or color_keys[0]
            images_by_color.setdefault(key, []).append(img)
    elif len(color_keys) == 1:
        images_by_color = {color_keys[0]: list(base_images)} if base_images else {}
    elif len(color_keys) == 2 and len(base_images) > 6:
        a, b = color_keys[0], color_keys[1]
        images_by_color = {
            a: [u for i, u in enumerate(base_images) if i <= 1 or (2 <= i < len(base_images) - 2)],
            b: [u for i, u in enumerate(base_images) if i >= len(base_images) - 2],
        }
    else:
        images_by_color = {k: list((color_groups.get(k) or {}).get("images") or []) for k in color_keys}

    selected = color_keys[0] if color_keys else fallback_single
    selected_images = list(images_by_color.get(selected, base_images)) if selected else list(base_images)

    return {
        "available_colors": available,
        "selected_color": selected,
        "color_variants": sorted(list(color_groups.values()), key=lambda x: str(x.get("color") or "")),
        "selected_color_images": selected_images,
        "colors": available,
        "default_color": selected,
        "images_by_color": images_by_color,
        "color_keys": color_keys,
    }


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
        color_payload = _build_color_payload(p)
        variants = []
        sizes = set()
        in_stock_sizes = set()
        colors = set()
        min_variant_price: float | None = None
        has_stock = False
        for v in (p.variants or []):
            try:
                if getattr(v, "size", None) and v.size and v.size.name:
                    size_name = v.size.name
                    sizes.add(size_name)
                    if int(getattr(v, "stock_quantity", 0) or 0) > 0:
                        in_stock_sizes.add(size_name)
                if getattr(v, "color", None) and v.color and v.color.name:
                    colors.add(normalize_color_key(v.color.name) or v.color.name)
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
                "sizes": sorted(list(in_stock_sizes or sizes), key=lambda x: float(x) if str(x).replace('.', '', 1).isdigit() else str(x)),
                "colors": sorted(list(colors)),
                "available_colors": color_payload["available_colors"],
                "selected_color": color_payload["selected_color"],
                "color_variants": color_payload["color_variants"],
                "default_color": color_payload["default_color"],
                "images_by_color": color_payload["images_by_color"],
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

    all_sizes = {(v.size.name if getattr(v, "size", None) and v.size else None) for v in (p.variants or []) if (getattr(v, "size", None) and v.size and v.size.name)}
    in_stock_sizes = {
        (v.size.name if getattr(v, "size", None) and v.size else None)
        for v in (p.variants or [])
        if (getattr(v, "size", None) and v.size and v.size.name and int(getattr(v, "stock_quantity", 0) or 0) > 0)
    }
    sizes = sorted((in_stock_sizes or all_sizes), key=lambda x: float(x) if str(x).replace('.', '', 1).isdigit() else str(x))
    colors = sorted({(normalize_color_key(v.color.name) or v.color.name) for v in (p.variants or []) if (getattr(v, "color", None) and v.color and v.color.name)})

    color_payload = _build_color_payload(p)
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
        "available_colors": color_payload["available_colors"],
        "selected_color": color_payload["selected_color"],
        "color_variants": color_payload["color_variants"],
        "selected_color_images": color_payload["selected_color_images"],
        "default_color": color_payload["default_color"],
        "images_by_color": color_payload["images_by_color"],
        "detected_color": getattr(p, "detected_color", None),
        "detected_color_confidence": (float(getattr(p, "detected_color_confidence", 0) or 0) if getattr(p, "detected_color_confidence", None) is not None else None),
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
