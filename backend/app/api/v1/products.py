from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi import Path, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models
from app.services import media_store
from app.services.color_detection import normalize_color_to_whitelist, detect_product_colors_from_photos

router = APIRouter(prefix="/products", tags=["products"])


def _is_none_like_color_token(raw: str | None) -> bool:
    txt = str(raw or "").strip().lower()
    return txt in {"", "none", "null", "n/a", "na", "unknown", "нет", "без цвета", "-", "—"}


def _images_overlap_ratio(a: list[str], b: list[str]) -> float:
    sa = {str(x).strip() for x in (a or []) if str(x).strip()}
    sb = {str(x).strip() for x in (b or []) if str(x).strip()}
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    base = max(1, min(len(sa), len(sb)))
    return inter / base


def _build_color_payload(p: models.Product) -> Dict[str, Any]:
    """Build color payload from already-stored DB data."""
    variants = list(getattr(p, "variants", []) or [])

    raw_base_images = [im.url for im in sorted((p.images or []), key=lambda x: ((x.sort or 0), x.id))]
    base_images: List[str] = []
    for u in raw_base_images:
        uu = str(u or "").strip()
        if uu and uu not in base_images:
            base_images.append(uu)

    # Prefer precomputed detector mapping for local/non-http sources (no remote downloads in API path).
    non_http_images = [u for u in base_images if not str(u).lower().startswith(("http://", "https://"))]
    try:
        detected = detect_product_colors_from_photos(non_http_images) if non_http_images else {}
    except Exception:
        detected = {}

    det_keys = [str(x).strip() for x in (detected.get("color_keys") or []) if str(x).strip()]
    det_photos = [str(x).strip() for x in (detected.get("ordered_photos") or []) if str(x).strip()]
    det_photo_keys = [str(x).strip() for x in (detected.get("photo_color_keys") or []) if str(x).strip()]
    if det_keys and det_photos and len(det_photos) == len(det_photo_keys):
        images_by_color: Dict[str, List[str]] = {k: [] for k in det_keys}
        for img, ck in zip(det_photos, det_photo_keys):
            key = ck if ck in images_by_color else (det_keys[0] if det_keys else ck)
            if key not in images_by_color:
                images_by_color[key] = []
            if img not in images_by_color[key]:
                images_by_color[key].append(img)

        selected = det_keys[0]
        return {
            "available_colors": det_keys,
            "selected_color": selected,
            "color_variants": [
                {"color": k, "variant_ids": [], "images": list(images_by_color.get(k) or [])}
                for k in det_keys
            ],
            "selected_color_images": list(images_by_color.get(selected) or base_images),
            "colors": det_keys,
            "default_color": selected,
            "images_by_color": images_by_color,
            "color_keys": det_keys,
        }

    # Fallback: variant-based color groups.
    color_groups: Dict[str, Dict[str, Any]] = {}
    for v in variants:
        raw_color_name = (v.color.name if getattr(v, "color", None) and v.color and v.color.name else None)
        color_name = "unknown" if _is_none_like_color_token(raw_color_name) else str(raw_color_name or "unknown")
        grp = color_groups.setdefault(color_name, {"color": color_name, "variant_ids": [], "images": []})
        grp["variant_ids"].append(v.id)
        for u in (v.images or []):
            if u and u not in grp["images"]:
                grp["images"].append(u)

    for grp in color_groups.values():
        if not grp["images"]:
            grp["images"] = list(base_images)

    groups = list(color_groups.values())
    if len(groups) > 1:
        ref_images = max(groups, key=lambda g: len(g.get("images") or [])).get("images") or []
        same_set = all(_images_overlap_ratio(ref_images, g.get("images") or []) >= 0.8 for g in groups)
        if same_set:
            merged_ids: list[int] = []
            for g in groups:
                merged_ids.extend([int(x) for x in (g.get("variant_ids") or [])])
            single_color = (getattr(p, "detected_color", None) or groups[0].get("color") or "unknown")
            color_groups = {
                str(single_color): {
                    "color": str(single_color),
                    "variant_ids": sorted(set(merged_ids)),
                    "images": list(ref_images or base_images),
                }
            }

    available = sorted([k for k in color_groups.keys() if k and k != "unknown" and not _is_none_like_color_token(k)])
    selected = available[0] if available else None
    selected_images = color_groups[selected]["images"] if selected and selected in color_groups else list(base_images)

    images_by_color = {
        str(k): list(v.get("images") or [])
        for k, v in color_groups.items()
        if k and k != "unknown" and not _is_none_like_color_token(str(k))
    }
    color_keys: List[str] = []
    normalized_images_by_color: Dict[str, List[str]] = {}
    for orig_name in available:
        if _is_none_like_color_token(orig_name):
            continue
        ck = normalize_color_to_whitelist(orig_name)
        if ck and ck not in color_keys:
            color_keys.append(ck)
        imgs = images_by_color.get(orig_name) or []
        if ck not in normalized_images_by_color:
            normalized_images_by_color[ck] = []
        for u in imgs:
            if u not in normalized_images_by_color[ck]:
                normalized_images_by_color[ck].append(u)

    return {
        "available_colors": available,
        "selected_color": selected,
        "color_variants": sorted(list(color_groups.values()), key=lambda x: str(x.get("color") or "")),
        "selected_color_images": selected_images,
        "colors": available,
        "default_color": selected,
        "images_by_color": normalized_images_by_color or images_by_color,
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
        # Local co-purchase fallback across ALL categories (not only current one).
        popular_rows = (
            db.query(
                models.ProductVariant.product_id,
                func.sum(models.OrderItem.quantity).label("score"),
            )
            .join(models.OrderItem, models.OrderItem.variant_id == models.ProductVariant.id)
            .filter(models.ProductVariant.product_id != p.id)
            .group_by(models.ProductVariant.product_id)
            .order_by(func.sum(models.OrderItem.quantity).desc())
            .limit(limit * 8)
            .all()
        )
        popular_ids = [int(r[0]) for r in popular_rows if r and r[0] and int(r[0]) not in selected_ids]
        if popular_ids:
            pop_products = (
                db.query(models.Product)
                .filter(models.Product.visible == True, models.Product.id.in_(popular_ids))
                .all()
            )
            by_id = {x.id: x for x in pop_products}
            for pid in popular_ids:
                x = by_id.get(pid)
                if not x or x.id in selected_ids:
                    continue
                selected.append(x)
                selected_ids.add(x.id)
                if len(selected) >= limit:
                    break

    if len(selected) < limit:
        fallback = (
            db.query(models.Product)
            .filter(models.Product.visible == True, models.Product.id != p.id)
            .order_by(models.Product.created_at.desc())
            .limit(limit * 6)
            .all()
        )
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
