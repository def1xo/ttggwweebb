
from typing import Optional, List
from decimal import Decimal
from pathlib import Path
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models
from app.services import media_store
from app.services.importer_notifications import slugify
from app.services.color_detection import detect_product_colors_from_photos, canonical_color_to_display_name

router = APIRouter(tags=["admin_products"])
logger = logging.getLogger("admin_products")


def _money(v: Optional[str], default: Decimal = Decimal("0.00")) -> Decimal:
    if v is None:
        return default
    s = str(v).strip().replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return default


def _upsert_product_cost(db: Session, variant_id: int, cost_price: Decimal) -> None:
    try:
        latest = (
            db.query(models.ProductCost)
            .filter(models.ProductCost.variant_id == int(variant_id))
            .order_by(models.ProductCost.created_at.desc(), models.ProductCost.id.desc())
            .first()
        )
        if latest and latest.cost_price == cost_price:
            return
        db.add(models.ProductCost(variant_id=int(variant_id), cost_price=cost_price))
    except Exception:
        # cost history is best-effort and must not break product save
        return


def _parse_colors(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    src = str(raw).strip()
    if not src:
        return []
    vals: List[str] = []
    for part in src.replace("\n", ",").replace("/", ",").replace(";", ",").split(","):
        name = str(part).strip()
        if name:
            vals.append(name[:128])
    uniq: List[str] = []
    seen = set()
    for v in vals:
        k = v.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(v)
    return uniq


def _parse_sizes(raw: Optional[str]) -> List[str]:
    """Parse sizes from admin input.

    Examples:
      "40-45" -> ["40","41","42","43","44","45"]
      "40-45, 40.5" -> ["40","40.5","41","42","43","44","45"]
    """
    if not raw:
        return []
    s = str(raw).strip()
    if not s:
        return []
    s = s.replace("–", "-").replace("—", "-")

    parts: List[str] = []
    for chunk in s.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        # allow spaces around dash
        if "-" in chunk and chunk.count("-") == 1:
            a, b = [x.strip() for x in chunk.split("-", 1)]
            try:
                af = float(a.replace(",", "."))
                bf = float(b.replace(",", "."))
                # range is intended for integer step sizes
                if af.is_integer() and bf.is_integer():
                    start = int(af)
                    end = int(bf)
                    if start <= end and end - start <= 200:
                        for v in range(start, end + 1):
                            parts.append(str(v))
                        continue
            except Exception:
                pass

        # single value
        chunk = chunk.replace(",", ".")
        parts.append(chunk)

    # normalize: unique + numeric sort
    seen = set()
    uniq: List[str] = []
    for x in parts:
        x = x.strip()
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)

    def _key(v: str):
        try:
            return (0, float(v))
        except Exception:
            return (1, v)

    uniq.sort(key=_key)
    return uniq


def _get_or_create_size(db: Session, name: str) -> models.Size:
    name = str(name).strip()[:64]
    if not name:
        raise ValueError("empty size")
    s = db.query(models.Size).filter(models.Size.name == name).first()
    if s:
        return s
    s = models.Size(name=name, slug=slugify(name)[:64] if slugify(name) else None)
    db.add(s)
    db.flush()
    return s


def _get_or_create_color(db: Session, name: str) -> models.Color:
    name = str(name).strip()[:128]
    if not name:
        raise ValueError("empty color")
    # try by slug first for stability
    slug = (slugify(name) or "")[:128]
    q = db.query(models.Color)
    c = None
    if slug:
        c = q.filter(models.Color.slug == slug).first()
    if not c:
        c = q.filter(models.Color.name == name).first()
    if c:
        return c
    c = models.Color(name=name, slug=slug or None)
    db.add(c)
    db.flush()
    return c


@router.get("/products")
def list_products(db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    items = db.query(models.Product).order_by(models.Product.created_at.desc()).all()
    out = []
    for p in items:
        sizes = []
        colors = []
        variant_ids = [int(v.id) for v in (p.variants or []) if getattr(v, "id", None)]
        latest_cost_by_variant: dict[int, float] = {}
        if variant_ids:
            rows = (
                db.query(models.ProductCost)
                .filter(models.ProductCost.variant_id.in_(variant_ids))
                .order_by(models.ProductCost.variant_id.asc(), models.ProductCost.created_at.desc(), models.ProductCost.id.desc())
                .all()
            )
            for r in rows:
                vid = int(getattr(r, "variant_id", 0) or 0)
                if vid <= 0 or vid in latest_cost_by_variant:
                    continue
                latest_cost_by_variant[vid] = float(getattr(r, "cost_price", 0) or 0)
        try:
            sizes = sorted({(v.size.name if getattr(v, "size", None) else None) for v in (p.variants or []) if (getattr(v, "size", None) and v.size.name)})
            colors = sorted({(v.color.name if getattr(v, "color", None) else None) for v in (p.variants or []) if (getattr(v, "color", None) and v.color.name)})
        except Exception:
            sizes, colors = [], []
        out.append({
            "id": p.id,
            "title": p.title,
            "name": p.title,
            "slug": p.slug,
            "base_price": float(p.base_price or 0),
            "currency": getattr(p, "currency", "RUB"),
            "visible": bool(getattr(p, "visible", False)),
            "category_id": p.category_id,
            "description": p.description,
            "default_image": p.default_image,
            "import_source_url": getattr(p, "import_source_url", None),
            "import_source_kind": getattr(p, "import_source_kind", None),
            "import_supplier_name": getattr(p, "import_supplier_name", None),
            "image_count": len(getattr(p, "images", []) or []),
            "sizes": sizes,
            "colors": colors,
            "variants": [{"id": v.id, "price": float(v.price or p.base_price or 0), "stock_quantity": int(v.stock_quantity or 0)} for v in (p.variants or [])],
            "cost_price": (round(sum(latest_cost_by_variant.values()) / len(latest_cost_by_variant), 2) if latest_cost_by_variant else None),
        })
    return {"products": out}


@router.post("/products")
def create_product(
    title: Optional[str] = Form(None),
    base_price: Optional[str] = Form(None),
    price: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    visible: Optional[bool] = Form(True),
    # Backward compatible single file + multi-file
    image: Optional[UploadFile] = File(None),
    images: Optional[List[UploadFile]] = File(None),
    sizes: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    stock_quantity: Optional[int] = Form(None),
    cost_price: Optional[str] = Form(None),
    payload: Optional[dict] = Body(None),
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    # allow JSON too
    if payload and title is None:
        title = payload.get("title")
        base_price = payload.get("base_price")
        price = payload.get("price")
        description = payload.get("description")
        category_id = payload.get("category_id")
        visible = payload.get("visible", True)
        sizes = payload.get("sizes")
        color = payload.get("color")
        if "stock_quantity" in payload:
            stock_quantity = payload.get("stock_quantity")
        if "cost_price" in payload:
            cost_price = payload.get("cost_price")

    if not title or not str(title).strip():
        raise HTTPException(400, detail="title required")

    p = models.Product(
        title=str(title).strip()[:512],
        slug=slugify(str(title)) or f"product-{admin.id}",
        description=description,
        base_price=_money(base_price or price),
        category_id=category_id,
        visible=bool(visible),
    )

    # collect images (support both `image` and `images[]`)
    upload_list: List[UploadFile] = []
    if image is not None:
        upload_list.append(image)
    if images:
        upload_list.extend([f for f in images if f is not None])
    saved_urls: List[str] = []
    if upload_list:
        for f in upload_list:
            try:
                saved_urls.append(media_store.save_upload_file_to_local(f, folder="products"))
            except Exception as exc:
                raise HTTPException(400, detail=str(exc))
        if saved_urls:
            p.default_image = saved_urls[0]

    db.add(p)
    db.flush()

    # persist additional images
    if upload_list and p.default_image:
        try:
            # saved_urls is defined above when upload_list exists
            for idx, url in enumerate(saved_urls):
                db.add(models.ProductImage(product_id=p.id, url=url, sort=idx))
        except Exception:
            # non-fatal
            pass

    stock_value = int(stock_quantity) if stock_quantity is not None else 9_999
    cost_value = _money(cost_price, default=Decimal("0")) if cost_price is not None else None
    if stock_value < 0:
        stock_value = 0

    # variants creation: sizes + optional color
    size_list = _parse_sizes(sizes)
    color_objs: List[models.Color] = []
    if color and str(color).strip():
        try:
            for c_name in _parse_colors(str(color)):
                color_objs.append(_get_or_create_color(db, c_name))
        except Exception as exc:
            raise HTTPException(400, detail=f"invalid color: {exc}")

    if not color_objs and saved_urls:
        # IMPORTANT: if admin did not set a color manually, infer it from uploaded photos
        # so product variants keep a usable color_id for storefront filters.
        local_sources: List[str] = []
        for u in saved_urls:
            pth = Path(str(u).lstrip("/"))
            local_sources.append(str(pth if pth.exists() else u))
        detected = detect_product_colors_from_photos(local_sources)
        canonical = str(detected.get("color") or "none")
        if canonical and canonical != "none":
            color_name = canonical_color_to_display_name(canonical)
            if color_name:
                color_objs.append(_get_or_create_color(db, color_name))
                p.detected_color = canonical
                p.detected_color_confidence = Decimal(str(detected.get("confidence") or 0))
                p.detected_color_debug = detected.get("debug")
                logger.info("create_product color-detect: product=%s color=%s confidence=%s photos=%s", p.id, canonical, detected.get("confidence"), len(local_sources))

    if not size_list:
        if color_objs:
            for c_obj in color_objs:
                db.add(models.ProductVariant(product_id=p.id, price=p.base_price, color_id=c_obj.id, stock_quantity=stock_value))
        else:
            db.add(models.ProductVariant(product_id=p.id, price=p.base_price, color_id=None, stock_quantity=stock_value))
    else:
        for sz in size_list:
            try:
                s_obj = _get_or_create_size(db, sz)
            except Exception as exc:
                raise HTTPException(400, detail=f"invalid size: {exc}")
            if color_objs:
                for c_obj in color_objs:
                    db.add(models.ProductVariant(product_id=p.id, price=p.base_price, size_id=s_obj.id, color_id=c_obj.id, stock_quantity=stock_value))
            else:
                db.add(models.ProductVariant(product_id=p.id, price=p.base_price, size_id=s_obj.id, color_id=None, stock_quantity=stock_value))

    if cost_value is not None and cost_value >= 0:
        for v in (p.variants or []):
            if getattr(v, "id", None):
                _upsert_product_cost(db, int(v.id), cost_value)

    db.commit()
    db.refresh(p)

    return {
        "ok": True,
        "product": {
            "id": p.id,
            "title": p.title,
            "base_price": float(p.base_price or 0),
            "default_image": p.default_image,
            "category_id": p.category_id,
            "sizes": size_list,
            "colors": [c.name for c in color_objs],
            "stock_quantity": stock_value,
            "cost_price": float(cost_value or 0) if cost_value is not None else None,
        },
    }


@router.patch("/products/{product_id}")
def update_product(
    product_id: int,
    title: Optional[str] = Form(None),
    base_price: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    visible: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    images: Optional[List[UploadFile]] = File(None),
    sizes: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    stock_quantity: Optional[int] = Form(None),
    cost_price: Optional[str] = Form(None),
    payload: Optional[dict] = Body(None),
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    p = db.query(models.Product).get(product_id)
    if not p:
        raise HTTPException(404, detail="not found")

    if payload and title is None:
        title = payload.get("title")
        base_price = payload.get("base_price")
        description = payload.get("description")
        category_id = payload.get("category_id")
        if "visible" in payload:
            visible = str(int(bool(payload.get("visible"))))
        sizes = payload.get("sizes")
        color = payload.get("color")
        if "stock_quantity" in payload:
            stock_quantity = payload.get("stock_quantity")
        if "cost_price" in payload:
            cost_price = payload.get("cost_price")

    if title is not None:
        p.title = str(title).strip()[:512]
        if p.title:
            p.slug = slugify(p.title) or p.slug

    if base_price is not None:
        p.base_price = _money(base_price, default=p.base_price)
        # sync first variant if exists
        if p.variants:
            p.variants[0].price = p.base_price

    if description is not None:
        p.description = description

    if stock_quantity is not None:
        try:
            sq = int(stock_quantity)
        except Exception:
            raise HTTPException(400, detail="invalid stock_quantity")
        if sq < 0:
            sq = 0
        stock_value = sq
        for v in (p.variants or []):
            v.stock_quantity = sq
            db.add(v)

    if category_id is not None:
        p.category_id = category_id

    if visible is not None:
        p.visible = str(visible).strip() not in ("0", "false", "False", "")

    if image is not None:
        try:
            p.default_image = media_store.save_upload_file_to_local(image, folder="products")
        except Exception as exc:
            raise HTTPException(400, detail=str(exc))

    # additional images
    if images:
        saved: List[str] = []
        for f in images:
            if f is None:
                continue
            try:
                saved.append(media_store.save_upload_file_to_local(f, folder="products"))
            except Exception as exc:
                raise HTTPException(400, detail=str(exc))
        if saved:
            # if no default image set (or admin wants to update via multi-upload)
            if not p.default_image:
                p.default_image = saved[0]
            # append to images table
            try:
                start_sort = 0
                if p.images:
                    start_sort = max([(im.sort or 0) for im in p.images] + [0]) + 1
                for idx, url in enumerate(saved):
                    db.add(models.ProductImage(product_id=p.id, url=url, sort=start_sort + idx))
            except Exception:
                pass

    stock_value = int((p.variants[0].stock_quantity if p.variants else 0) or 0)

    # variants adjustments
    if sizes is not None or color is not None:
        size_list = _parse_sizes(sizes) if sizes is not None else []
        color_objs: List[models.Color] = []
        if color is not None and str(color).strip():
            for c_name in _parse_colors(str(color)):
                color_objs.append(_get_or_create_color(db, c_name))

        if p.variants is None:
            p.variants = []

        # map existing by size name
        existing_by_size: dict[str, models.ProductVariant] = {}
        for v in p.variants:
            try:
                nm = v.size.name if getattr(v, "size", None) else ""
                if nm and nm not in existing_by_size:
                    existing_by_size[nm] = v
            except Exception:
                pass

        if size_list:
            for sz in size_list:
                s_obj = _get_or_create_size(db, sz)
                v = existing_by_size.get(s_obj.name)
                if v:
                    if color_objs:
                        v.color_id = color_objs[0].id
                    # keep stock, sync price
                    v.price = p.base_price
                    db.add(v)
                else:
                    if color_objs:
                        for c_obj in color_objs:
                            db.add(models.ProductVariant(product_id=p.id, price=p.base_price, size_id=s_obj.id, color_id=c_obj.id, stock_quantity=stock_value))
                    else:
                        db.add(models.ProductVariant(product_id=p.id, price=p.base_price, size_id=s_obj.id, color_id=None, stock_quantity=stock_value))
        else:
            # no size list supplied: at least update first variant color/price
            if p.variants:
                v0 = p.variants[0]
                v0.price = p.base_price
                if color_objs:
                    v0.color_id = color_objs[0].id
                db.add(v0)
            else:
                if color_objs:
                    for c_obj in color_objs:
                        db.add(models.ProductVariant(product_id=p.id, price=p.base_price, color_id=c_obj.id, stock_quantity=stock_value))
                else:
                    db.add(models.ProductVariant(product_id=p.id, price=p.base_price, color_id=None, stock_quantity=stock_value))

    cost_value = _money(cost_price, default=Decimal("0")) if cost_price is not None else None
    if cost_value is not None and cost_value >= 0:
        for v in (p.variants or []):
            if getattr(v, "id", None):
                _upsert_product_cost(db, int(v.id), cost_value)

    db.add(p)
    db.commit()
    db.refresh(p)

    sizes_out = sorted({(v.size.name if getattr(v, "size", None) else None) for v in (p.variants or []) if (getattr(v, "size", None) and v.size.name)})
    colors_out = sorted({(v.color.name if getattr(v, "color", None) else None) for v in (p.variants or []) if (getattr(v, "color", None) and v.color.name)})

    return {
        "ok": True,
        "product": {
            "id": p.id,
            "title": p.title,
            "base_price": float(p.base_price or 0),
            "default_image": p.default_image,
            "category_id": p.category_id,
            "sizes": sizes_out,
            "colors": colors_out,
            "stock_quantity": int((p.variants[0].stock_quantity if p.variants else 0) or 0),
            "cost_price": float(cost_value or 0) if cost_value is not None else None,
        },
    }


@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    p = db.query(models.Product).get(product_id)
    if not p:
        return {"ok": True}
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    cats = db.query(models.Category).order_by(models.Category.id.asc()).all()
    return {"items": [{"id": c.id, "name": c.name, "slug": c.slug, "image_url": c.image_url} for c in cats]}


@router.post("/categories")
def create_category(
    name: str = Form(...),
    slug: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user),
):
    c = models.Category(name=name.strip()[:255], slug=(slugify(slug) if slug else slugify(name)))
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"ok": True, "category": {"id": c.id, "name": c.name, "slug": c.slug}}


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin_user)):
    c = db.query(models.Category).get(category_id)
    if not c:
        return {"ok": True}
    db.delete(c)
    db.commit()
    return {"ok": True}
