
from typing import Optional, List
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_admin_user
from app.db import models
from app.services import media_store
from app.services.importer_notifications import slugify

router = APIRouter(tags=["admin_products"])


def _money(v: Optional[str], default: Decimal = Decimal("0.00")) -> Decimal:
    if v is None:
        return default
    s = str(v).strip().replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return default


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
            "sizes": sizes,
            "colors": colors,
            "variants": [{"id": v.id, "price": float(v.price or p.base_price or 0)} for v in (p.variants or [])],
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
    if upload_list:
        saved_urls: List[str] = []
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

    # variants creation: sizes + optional color
    size_list = _parse_sizes(sizes)
    color_objs: List[models.Color] = []
    if color and str(color).strip():
        try:
            for c_name in _parse_colors(str(color)):
                color_objs.append(_get_or_create_color(db, c_name))
        except Exception as exc:
            raise HTTPException(400, detail=f"invalid color: {exc}")

    if not size_list:
        if color_objs:
            for c_obj in color_objs:
                db.add(models.ProductVariant(product_id=p.id, price=p.base_price, color_id=c_obj.id))
        else:
            db.add(models.ProductVariant(product_id=p.id, price=p.base_price, color_id=None))
    else:
        for sz in size_list:
            try:
                s_obj = _get_or_create_size(db, sz)
            except Exception as exc:
                raise HTTPException(400, detail=f"invalid size: {exc}")
            if color_objs:
                for c_obj in color_objs:
                    db.add(models.ProductVariant(product_id=p.id, price=p.base_price, size_id=s_obj.id, color_id=c_obj.id))
            else:
                db.add(models.ProductVariant(product_id=p.id, price=p.base_price, size_id=s_obj.id, color_id=None))

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
                            db.add(models.ProductVariant(product_id=p.id, price=p.base_price, size_id=s_obj.id, color_id=c_obj.id))
                    else:
                        db.add(models.ProductVariant(product_id=p.id, price=p.base_price, size_id=s_obj.id, color_id=None))
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
                        db.add(models.ProductVariant(product_id=p.id, price=p.base_price, color_id=c_obj.id))
                else:
                    db.add(models.ProductVariant(product_id=p.id, price=p.base_price, color_id=None))

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
