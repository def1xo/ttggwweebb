from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin_user, get_db
from app.db import models
from app.services.importer_notifications import slugify
from app.services.supplier_intelligence import (
    SupplierOffer,
    estimate_market_price,
    extract_catalog_items,
    fetch_tabular_preview,
    generate_youth_description,
    map_category,
    pick_best_offer,
    suggest_sale_price,
)

router = APIRouter(tags=["admin_supplier_intelligence"])


class SupplierSourceIn(BaseModel):
    source_url: str = Field(min_length=5, max_length=2000)
    supplier_name: str | None = Field(default=None, max_length=255)
    manager_name: str | None = Field(default=None, max_length=255)
    manager_contact: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class SupplierSourcePatchIn(BaseModel):
    source_url: str | None = Field(default=None, min_length=5, max_length=2000)
    supplier_name: str | None = Field(default=None, max_length=255)
    manager_name: str | None = Field(default=None, max_length=255)
    manager_contact: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    active: bool | None = None


class SupplierSourceOut(BaseModel):
    id: int
    source_url: str
    supplier_name: str | None = None
    manager_name: str | None = None
    manager_contact: str | None = None
    note: str | None = None
    active: bool


class SupplierSourceBulkEntryIn(BaseModel):
    source_url: str = Field(min_length=5, max_length=2000)
    supplier_name: str | None = Field(default=None, max_length=255)
    manager_name: str | None = Field(default=None, max_length=255)
    manager_contact: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class SupplierSourceBulkUpsertIn(BaseModel):
    entries: list[SupplierSourceBulkEntryIn] = Field(default_factory=list, min_items=1, max_items=200)


class SupplierSourceBulkUpsertOut(BaseModel):
    created: int
    updated: int
    skipped: int
    items: list[SupplierSourceOut] = Field(default_factory=list)


class AnalyzeLinksIn(BaseModel):
    links: list[str] = Field(default_factory=list, min_items=1, max_items=30)


class AnalyzeStoredSourcesIn(BaseModel):
    source_ids: list[int] = Field(default_factory=list, min_items=1, max_items=50)


class AnalyzeLinksOut(BaseModel):
    url: str
    ok: bool
    kind: str | None = None
    status_code: int | None = None
    rows_count_preview: int | None = None
    sample_rows: list[list[str]] = Field(default_factory=list)
    mapped_categories_sample: list[str] = Field(default_factory=list)
    error: str | None = None


class AnalyzeStoredSourceOut(AnalyzeLinksOut):
    source_id: int
    supplier_name: str | None = None
    manager_name: str | None = None
    manager_contact: str | None = None


def _to_source_out(x: models.SupplierSource) -> SupplierSourceOut:
    return SupplierSourceOut(
        id=int(x.id),
        source_url=str(x.source_url),
        supplier_name=getattr(x, "supplier_name", None),
        manager_name=getattr(x, "manager_name", None),
        manager_contact=getattr(x, "manager_contact", None),
        note=getattr(x, "note", None),
        active=bool(getattr(x, "active", True)),
    )


def _analyze_url(url: str) -> AnalyzeLinksOut:
    data = fetch_tabular_preview(url)
    rows = data.get("rows_preview") or []
    sample_titles: list[str] = []
    for r in rows[:8]:
        if r:
            sample_titles.append(str(r[0]))
    categories = [map_category(t) for t in sample_titles if t]
    return AnalyzeLinksOut(
        url=url,
        ok=True,
        kind=str(data.get("kind") or ""),
        status_code=int(data.get("status_code") or 0),
        rows_count_preview=int(data.get("rows_count_preview") or 0),
        sample_rows=rows[:8],
        mapped_categories_sample=categories,
    )


@router.get("/supplier-intelligence/sources", response_model=list[SupplierSourceOut])
def list_supplier_sources(_admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    items = (
        db.query(models.SupplierSource)
        .order_by(models.SupplierSource.active.desc(), models.SupplierSource.id.desc())
        .all()
    )
    return [_to_source_out(x) for x in items]


@router.post("/supplier-intelligence/sources", response_model=SupplierSourceOut)
def create_supplier_source(payload: SupplierSourceIn, _admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    source_url = payload.source_url.strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url is required")

    item = models.SupplierSource(
        source_url=source_url,
        supplier_name=(payload.supplier_name or "").strip() or None,
        manager_name=(payload.manager_name or "").strip() or None,
        manager_contact=(payload.manager_contact or "").strip() or None,
        note=(payload.note or "").strip() or None,
        active=True,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="source_url already exists")
    db.refresh(item)
    return _to_source_out(item)




@router.post("/supplier-intelligence/sources/bulk-upsert", response_model=SupplierSourceBulkUpsertOut)
def bulk_upsert_supplier_sources(
    payload: SupplierSourceBulkUpsertIn,
    _admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    created = 0
    updated = 0
    skipped = 0
    changed_items: list[models.SupplierSource] = []

    for entry in payload.entries:
        url = (entry.source_url or "").strip()
        if not url:
            skipped += 1
            continue

        item = db.query(models.SupplierSource).filter(models.SupplierSource.source_url == url).one_or_none()
        if item is None:
            item = models.SupplierSource(
                source_url=url,
                supplier_name=(entry.supplier_name or "").strip() or None,
                manager_name=(entry.manager_name or "").strip() or None,
                manager_contact=(entry.manager_contact or "").strip() or None,
                note=(entry.note or "").strip() or None,
                active=True,
            )
            db.add(item)
            changed_items.append(item)
            created += 1
            continue

        before = (
            item.supplier_name,
            item.manager_name,
            item.manager_contact,
            item.note,
        )
        item.supplier_name = (entry.supplier_name or "").strip() or item.supplier_name
        item.manager_name = (entry.manager_name or "").strip() or item.manager_name
        item.manager_contact = (entry.manager_contact or "").strip() or item.manager_contact
        item.note = (entry.note or "").strip() or item.note
        after = (item.supplier_name, item.manager_name, item.manager_contact, item.note)
        if before != after:
            db.add(item)
            changed_items.append(item)
            updated += 1
        else:
            skipped += 1

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="bulk upsert conflict")

    for item in changed_items:
        try:
            db.refresh(item)
        except Exception:
            pass

    return SupplierSourceBulkUpsertOut(
        created=created,
        updated=updated,
        skipped=skipped,
        items=[_to_source_out(x) for x in changed_items],
    )


@router.patch("/supplier-intelligence/sources/{source_id}", response_model=SupplierSourceOut)
def patch_supplier_source(
    source_id: int,
    payload: SupplierSourcePatchIn,
    _admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    item = db.query(models.SupplierSource).filter(models.SupplierSource.id == int(source_id)).one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="source not found")

    if payload.source_url is not None:
        next_url = payload.source_url.strip()
        if not next_url:
            raise HTTPException(status_code=400, detail="source_url cannot be empty")
        item.source_url = next_url
    if payload.supplier_name is not None:
        item.supplier_name = (payload.supplier_name or "").strip() or None
    if payload.manager_name is not None:
        item.manager_name = (payload.manager_name or "").strip() or None
    if payload.manager_contact is not None:
        item.manager_contact = (payload.manager_contact or "").strip() or None
    if payload.note is not None:
        item.note = (payload.note or "").strip() or None
    if payload.active is not None:
        item.active = bool(payload.active)

    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="source_url already exists")
    db.refresh(item)
    return _to_source_out(item)


@router.delete("/supplier-intelligence/sources/{source_id}")
def delete_supplier_source(source_id: int, _admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    item = db.query(models.SupplierSource).filter(models.SupplierSource.id == int(source_id)).one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="source not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/supplier-intelligence/analyze-links", response_model=list[AnalyzeLinksOut])
def analyze_supplier_links(payload: AnalyzeLinksIn, _admin=Depends(get_current_admin_user)):
    out: list[AnalyzeLinksOut] = []
    for raw_url in payload.links:
        url = (raw_url or "").strip()
        if not url:
            continue
        try:
            out.append(_analyze_url(url))
        except Exception as exc:
            out.append(AnalyzeLinksOut(url=url, ok=False, error=str(exc)))
    return out


@router.post("/supplier-intelligence/analyze-sources", response_model=list[AnalyzeStoredSourceOut])
def analyze_stored_sources(payload: AnalyzeStoredSourcesIn, _admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    ids = [int(x) for x in payload.source_ids]
    if not ids:
        return []
    items = db.query(models.SupplierSource).filter(models.SupplierSource.id.in_(ids)).all()
    out: list[AnalyzeStoredSourceOut] = []
    for item in items:
        url = (item.source_url or "").strip()
        if not url:
            continue
        try:
            data = _analyze_url(url)
            out.append(
                AnalyzeStoredSourceOut(
                    source_id=int(item.id),
                    supplier_name=item.supplier_name,
                    manager_name=item.manager_name,
                    manager_contact=item.manager_contact,
                    **data.dict(),
                )
            )
        except Exception as exc:
            out.append(
                AnalyzeStoredSourceOut(
                    source_id=int(item.id),
                    supplier_name=item.supplier_name,
                    manager_name=item.manager_name,
                    manager_contact=item.manager_contact,
                    url=url,
                    ok=False,
                    error=str(exc),
                )
            )
    return out




class ImportProductsIn(BaseModel):
    source_ids: list[int] = Field(default_factory=list, min_items=1, max_items=100)
    max_items_per_source: int = Field(default=40, ge=1, le=200)
    dry_run: bool = True
    publish_visible: bool = False
    ai_style_description: bool = True


class ImportProductsOut(BaseModel):
    created_categories: int
    created_products: int
    updated_products: int
    created_variants: int
    source_reports: list[dict[str, object]] = Field(default_factory=list)


class OfferIn(BaseModel):
    supplier: str
    title: str
    dropship_price: float
    color: str | None = None
    size: str | None = None
    stock: int | None = None
    manager_url: str | None = None


class BestOfferIn(BaseModel):
    desired_color: str | None = None
    desired_size: str | None = None
    offers: list[OfferIn] = Field(default_factory=list, min_items=1, max_items=100)


class BestOfferOut(BaseModel):
    supplier: str
    title: str
    dropship_price: float
    color: str | None = None
    size: str | None = None
    stock: int | None = None
    manager_url: str | None = None


@router.post("/supplier-intelligence/best-offer", response_model=BestOfferOut)
def get_best_offer(payload: BestOfferIn, _admin=Depends(get_current_admin_user)):
    offers = [
        SupplierOffer(
            supplier=o.supplier,
            title=o.title,
            color=o.color,
            size=o.size,
            dropship_price=float(o.dropship_price),
            stock=o.stock,
            manager_url=o.manager_url,
        )
        for o in payload.offers
    ]
    best = pick_best_offer(offers, desired_color=payload.desired_color, desired_size=payload.desired_size)
    if not best:
        raise HTTPException(status_code=404, detail="no offers")
    return BestOfferOut(
        supplier=best.supplier,
        title=best.title,
        dropship_price=float(best.dropship_price),
        color=best.color,
        size=best.size,
        stock=best.stock,
        manager_url=best.manager_url,
    )




@router.post("/supplier-intelligence/import-products", response_model=ImportProductsOut)
def import_products_from_sources(
    payload: ImportProductsIn,
    _admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    source_ids = [int(x) for x in payload.source_ids]
    sources = (
        db.query(models.SupplierSource)
        .filter(models.SupplierSource.id.in_(source_ids))
        .filter(models.SupplierSource.active == True)  # noqa: E712
        .all()
    )

    created_categories = 0
    created_products = 0
    updated_products = 0
    created_variants = 0
    source_reports: list[dict[str, object]] = []

    def get_or_create_category(name: str) -> models.Category:
        nonlocal created_categories
        n = (name or "Разное").strip()[:255] or "Разное"
        slug = (slugify(n) or n.lower().replace(" ", "-"))[:255]
        c = db.query(models.Category).filter(models.Category.slug == slug).one_or_none()
        if not c:
            c = db.query(models.Category).filter(models.Category.name == n).one_or_none()
        if c:
            return c
        c = models.Category(name=n, slug=slug)
        db.add(c)
        db.flush()
        created_categories += 1
        return c

    def get_or_create_color(name: str | None) -> models.Color | None:
        nm = (name or "").strip()
        if not nm:
            return None
        s = (slugify(nm) or nm.lower())[:128]
        x = db.query(models.Color).filter((models.Color.slug == s) | (models.Color.name == nm)).first()
        if x:
            return x
        x = models.Color(name=nm, slug=s)
        db.add(x)
        db.flush()
        return x

    def get_or_create_size(name: str | None) -> models.Size | None:
        nm = (name or "").strip()
        if not nm:
            return None
        s = (slugify(nm) or nm.lower())[:64]
        x = db.query(models.Size).filter((models.Size.slug == s) | (models.Size.name == nm)).first()
        if x:
            return x
        x = models.Size(name=nm, slug=s)
        db.add(x)
        db.flush()
        return x

    for src in sources:
        src_url = (src.source_url or "").strip()
        if not src_url:
            continue
        report = {"source_id": int(src.id), "url": src_url, "imported": 0, "errors": 0}
        try:
            preview = fetch_tabular_preview(src_url, max_rows=max(5, payload.max_items_per_source + 1))
            rows = preview.get("rows_preview") or []
            items = extract_catalog_items(rows, max_items=payload.max_items_per_source)
        except Exception as exc:
            report["errors"] = 1
            report["error_message"] = str(exc)
            source_reports.append(report)
            continue

        for it in items:
            try:
                title = str(it.get("title") or "").strip()
                if not title:
                    continue
                ds_price = float(it.get("dropship_price") or 0)
                if ds_price <= 0:
                    continue
                cat_name = map_category(title)
                category = get_or_create_category(cat_name)
                slug_base = (slugify(title) or f"item-{category.id}")[:500]
                slug = slug_base
                p = db.query(models.Product).filter(models.Product.slug == slug).one_or_none()
                if not p:
                    p = db.query(models.Product).filter(models.Product.title == title, models.Product.category_id == category.id).one_or_none()

                desc = str(it.get("description") or "").strip()
                if payload.ai_style_description and not desc:
                    desc = generate_youth_description(title, cat_name, it.get("color"))
                sale_price = suggest_sale_price(ds_price)
                image_url = str(it.get("image_url") or "").strip() or None

                if not p:
                    # unique slug fallback
                    n = 2
                    while db.query(models.Product).filter(models.Product.slug == slug).first() is not None:
                        slug = f"{slug_base[:490]}-{n}"
                        n += 1
                    p = models.Product(
                        title=title,
                        slug=slug,
                        description=desc or None,
                        base_price=Decimal(str(sale_price)),
                        currency="RUB",
                        category_id=category.id,
                        default_image=image_url,
                        visible=bool(payload.publish_visible),
                    )
                    db.add(p)
                    db.flush()
                    created_products += 1
                else:
                    changed = False
                    if desc and not p.description:
                        p.description = desc
                        changed = True
                    if sale_price > 0 and float(p.base_price or 0) <= 0:
                        p.base_price = Decimal(str(sale_price))
                        changed = True
                    if image_url and not p.default_image:
                        p.default_image = image_url
                        changed = True
                    if changed:
                        db.add(p)
                        updated_products += 1

                size = get_or_create_size(it.get("size"))
                color = get_or_create_color(it.get("color"))
                variant = (
                    db.query(models.ProductVariant)
                    .filter(models.ProductVariant.product_id == p.id)
                    .filter(models.ProductVariant.size_id == (size.id if size else None))
                    .filter(models.ProductVariant.color_id == (color.id if color else None))
                    .one_or_none()
                )
                stock_qty = int(it.get("stock") or 0)
                if variant is None:
                    variant = models.ProductVariant(
                        product_id=p.id,
                        size_id=size.id if size else None,
                        color_id=color.id if color else None,
                        price=Decimal(str(sale_price)),
                        stock_quantity=max(0, stock_qty),
                        images=[image_url] if image_url else None,
                    )
                    db.add(variant)
                    db.flush()
                    created_variants += 1
                else:
                    if float(variant.price or 0) <= 0 and sale_price > 0:
                        variant.price = Decimal(str(sale_price))
                    if stock_qty > 0 and int(variant.stock_quantity or 0) <= 0:
                        variant.stock_quantity = stock_qty
                    if image_url and not variant.images:
                        variant.images = [image_url]
                    db.add(variant)

                report["imported"] = int(report.get("imported") or 0) + 1
            except Exception:
                report["errors"] = int(report.get("errors") or 0) + 1

        source_reports.append(report)

    if payload.dry_run:
        db.rollback()
    else:
        db.commit()

    return ImportProductsOut(
        created_categories=created_categories,
        created_products=created_products,
        updated_products=updated_products,
        created_variants=created_variants,
        source_reports=source_reports,
    )


class MarketPriceIn(BaseModel):
    prices: list[float] = Field(default_factory=list, min_items=1, max_items=300)


class MarketPriceOut(BaseModel):
    suggested_price: float | None


@router.post("/supplier-intelligence/estimate-market-price", response_model=MarketPriceOut)
def estimate_price(payload: MarketPriceIn, _admin=Depends(get_current_admin_user)):
    return MarketPriceOut(suggested_price=estimate_market_price(payload.prices))
