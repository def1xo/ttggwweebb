from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi import Path, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from decimal import Decimal

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models
from app.services import media_store
from app.services.color_detection import normalize_color_to_whitelist, canonical_color_to_display_name

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
    """Build color payload from already-stored DB data.

    CRITICAL: Must NEVER download images or do heavy I/O.
    Called for every product in every list_products response.
    Live color detection only happens during import.
    """
    variants = list(getattr(p, "variants", []) or [])
    base_images = [im.url for im in sorted((p.images or []), key=lambda x: ((x.sort or 0), x.id)) if getattr(im, "url", None)]

    import_media_meta = getattr(p, "import_media_meta", None) or {}
    stored_images_by_key = import_media_meta.get("images_by_color_key") if isinstance(import_media_meta, dict) else None
    general_images = list(import_media_meta.get("general_images") or []) if isinstance(import_media_meta, dict) else []

    def _append_unique(dst: list[str], seen: set[str], values: list[Any]) -> None:
        for val in values or []:
            u = str(val or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            dst.append(u)

    base_gallery: list[str] = []
    base_seen: set[str] = set()
    _append_unique(base_gallery, base_seen, base_images)
    _append_unique(base_gallery, base_seen, general_images)
    for v in variants:
        _append_unique(base_gallery, base_seen, list(getattr(v, "images", None) or []))

    color_groups: Dict[str, Dict[str, Any]] = {}
    for v in variants:
        raw_name = (v.color.name if getattr(v, "color", None) and v.color and v.color.name else None) or ""
        color_key = normalize_color_to_whitelist(raw_name)
        if not color_key:
            continue
        grp = color_groups.setdefault(color_key, {"color": color_key, "variant_ids": [], "images": []})
        grp["variant_ids"].append(v.id)
        _append_unique(grp["images"], set(grp["images"]), list(v.images or []))

    if isinstance(stored_images_by_key, dict):
        for k, imgs in stored_images_by_key.items():
            key = normalize_color_to_whitelist(k)
            if not key:
                continue
            grp = color_groups.setdefault(key, {"color": key, "variant_ids": [], "images": []})
            _append_unique(grp["images"], set(grp["images"]), list(imgs or []))

    for grp in color_groups.values():
        if not grp["images"] and general_images:
            grp["images"] = list(general_images)

    available = list(color_groups.keys())
    detected_color_key = normalize_color_to_whitelist(getattr(p, "detected_color", None)) if getattr(p, "detected_color", None) else ""
    if detected_color_key == "multi":
        detected_color_key = ""
    is_single_color = len(available) <= 1 and (bool(available) or bool(detected_color_key) or not any(getattr(v, "color_id", None) for v in variants))

    selected = detected_color_key
    if available:
        if selected not in available:
            selected = available[0]
    elif is_single_color and selected:
        available = [selected]

    selected_images = color_groups.get(selected, {}).get("images") if selected else []
    if is_single_color:
        selected_images = list(base_gallery)
    if not selected_images:
        selected_images = list(general_images)
    if not selected_images and available:
        selected_images = list(color_groups.get(available[0], {}).get("images") or [])
    if not selected_images:
        selected_images = list(base_gallery or base_images)

    images_by_color = {k: list(v.get("images") or []) for k, v in color_groups.items()}
    color_key_to_display = {k: canonical_color_to_display_name(k) for k in available}

    return {
        "available_colors": available,
        "selected_color": selected,
        "color_variants": sorted(list(color_groups.values()), key=lambda x: str(x.get("color") or "")),
        "selected_color_images": selected_images,
        "colors": available,
        "default_color": selected,
        "images_by_color": images_by_color,
        "color_keys": available,
        "available_color_keys": available,
        "selected_color_key": selected,
        "color_key_to_display": color_key_to_display,
        "images_by_color_key": images_by_color,
        "general_images": general_images,
    }


@router.get("")
def list_products(
    category_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=50),
    per_page: Optional[int] = Query(None, ge=1, le=500),
    db: Session = Depends(get_db),
):
    effective_limit = min(50, int(per_page or limit or 25))
    try:
        query = db.query(models.Product).filter(models.Product.visible == True)
        if category_id:
            query = query.filter(models.Product.category_id == category_id)
        if q:
            search = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    models.Product.title.ilike(search),
                    models.Product.slug.ilike(search),
                    models.Product.variants.any(models.ProductVariant.sku.ilike(search)),
                )
            )
        total = query.count()
        items = (
            query.order_by(models.Product.created_at.desc())
            .offset((page - 1) * effective_limit)
            .limit(effective_limit)
            .all()
        )
    except Exception:
        return {"items": [], "total": 0, "page": page, "limit": effective_limit, "pages": 0}
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
                    "color_key": normalize_color_to_whitelist((v.color.name if getattr(v, "color", None) and v.color else None)),
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
                "color_keys": color_payload["color_keys"],
                "available_color_keys": color_payload["available_color_keys"],
                "selected_color_key": color_payload["selected_color_key"],
                "color_key_to_display": color_payload["color_key_to_display"],
                "images_by_color_key": color_payload["images_by_color_key"],
                "general_images": color_payload["general_images"],
                "variants": variants,
            }
        )
    pages = (total + effective_limit - 1) // effective_limit if total > 0 else 0
    return {"items": result, "total": total, "page": page, "limit": effective_limit, "pages": pages}


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
    colors = sorted({(v.color.name if getattr(v, "color", None) and v.color else None) for v in (p.variants or []) if (getattr(v, "color", None) and v.color and v.color.name)})

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
        "color_keys": color_payload["color_keys"],
        "available_color_keys": color_payload["available_color_keys"],
        "selected_color_key": color_payload["selected_color_key"],
        "color_key_to_display": color_payload["color_key_to_display"],
        "images_by_color_key": color_payload["images_by_color_key"],
        "general_images": color_payload["general_images"],
        "detected_color": getattr(p, "detected_color", None),
        "detected_color_confidence": (float(getattr(p, "detected_color_confidence", 0) or 0) if getattr(p, "detected_color_confidence", None) is not None else None),
        "variants": [
            {
                "id": v.id,
                "price": float(v.price or 0),
                "stock": v.stock_quantity,
                "size": (v.size.name if getattr(v, "size", None) and v.size else None),
                "color": (v.color.name if getattr(v, "color", None) and v.color else None),
                "color_key": normalize_color_to_whitelist((v.color.name if getattr(v, "color", None) and v.color else None)),
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
    try:
        url = media_store.save_upload_file_to_local(file, folder="products")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    img = models.ProductImage(product_id=product_id, url=url)
    db.add(img)
    db.commit()
    db.refresh(img)
    return {"id": img.id, "url": img.url}
