from __future__ import annotations

import logging
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
    ensure_min_markup_price,
    estimate_market_price,
    avito_market_scan,
    dominant_color_name_from_url,
    extract_catalog_items,
    extract_image_urls_from_html_page,
    fetch_tabular_preview,
    generate_ai_product_description,
    generate_youth_description,
    image_print_signature_from_url,
    map_category,
    pick_best_offer,
    print_signature_hamming,
    suggest_sale_price,
)

router = APIRouter(tags=["admin_supplier_intelligence"])
logger = logging.getLogger(__name__)

ERROR_CODE_NETWORK_TIMEOUT = "network_timeout"
ERROR_CODE_INVALID_IMAGE = "invalid_image"
ERROR_CODE_PARSE_FAILED = "parse_failed"
ERROR_CODE_DB_CONFLICT = "db_conflict"
ERROR_CODE_UNKNOWN = "unknown"
TOP_FAILING_SOURCES_LIMIT = 5
ERROR_SAMPLES_LIMIT = 3
ERROR_MESSAGE_MAX_LEN = 500


def _normalize_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).strip().split())
    if len(message) > ERROR_MESSAGE_MAX_LEN:
        return f"{message[:ERROR_MESSAGE_MAX_LEN - 3]}..."
    return message


def _classify_import_error(exc: Exception) -> str:
    if isinstance(exc, IntegrityError):
        return ERROR_CODE_DB_CONFLICT
    message = str(exc).lower()
    if any(token in message for token in ("timeout", "timed out", "connection", "429", "too many requests")):
        return ERROR_CODE_NETWORK_TIMEOUT
    if "not an image" in message or "invalid image" in message:
        return ERROR_CODE_INVALID_IMAGE
    if "parse" in message:
        return ERROR_CODE_PARSE_FAILED
    return ERROR_CODE_UNKNOWN


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
    ai_description_provider: str = Field(default="openrouter", max_length=64)
    ai_description_enabled: bool = True
    use_avito_pricing: bool = True
    avito_max_pages: int = Field(default=1, ge=1, le=3)


class ImportSourceReport(BaseModel):
    source_id: int
    url: str
    imported: int = 0
    errors: int = 0
    error_codes: dict[str, int] = Field(default_factory=dict)
    error_samples: list[str] = Field(default_factory=list)
    last_error_message: str | None = None


class ImportProductsOut(BaseModel):
    created_categories: int
    created_products: int
    updated_products: int
    created_variants: int
    source_reports: list[ImportSourceReport] = Field(default_factory=list)


def _new_source_report(source_id: int, source_url: str) -> ImportSourceReport:
    return ImportSourceReport(source_id=source_id, url=source_url)


def _register_source_error(report: ImportSourceReport, exc: Exception) -> None:
    code = _classify_import_error(exc)
    message = _normalize_error_message(exc)
    report.errors += 1
    report.last_error_message = message
    report.error_codes[code] = int(report.error_codes.get(code) or 0) + 1
    if message and message not in report.error_samples and len(report.error_samples) < ERROR_SAMPLES_LIMIT:
        report.error_samples.append(message)




class AvitoMarketScanIn(BaseModel):
    query: str = Field(min_length=2, max_length=255)
    max_pages: int = Field(default=1, ge=1, le=3)


class AvitoMarketScanOut(BaseModel):
    query: str
    pages: int
    prices: list[float] = Field(default_factory=list)
    suggested: float | None = None
    errors: list[str] = Field(default_factory=list)


class TelegramMediaPreviewIn(BaseModel):
    urls: list[str] = Field(default_factory=list, min_items=1, max_items=50)


class TelegramMediaPreviewOut(BaseModel):
    url: str
    image_urls: list[str] = Field(default_factory=list)
    error: str | None = None


class ImageAnalysisIn(BaseModel):
    image_urls: list[str] = Field(default_factory=list, min_items=1, max_items=50)


class ImageAnalysisOut(BaseModel):
    image_url: str
    print_signature: str | None = None
    dominant_color: str | None = None




@router.post("/supplier-intelligence/avito-market-scan", response_model=AvitoMarketScanOut)
def avito_scan(payload: AvitoMarketScanIn, _admin=Depends(get_current_admin_user)):
    data = avito_market_scan(payload.query, max_pages=payload.max_pages)
    return AvitoMarketScanOut(
        query=str(data.get("query") or ""),
        pages=int(data.get("pages") or payload.max_pages),
        prices=[float(x) for x in (data.get("prices") or [])],
        suggested=(float(data.get("suggested")) if data.get("suggested") is not None else None),
        errors=[str(x) for x in (data.get("errors") or [])],
    )


@router.post("/supplier-intelligence/telegram-media-preview", response_model=list[TelegramMediaPreviewOut])
def telegram_media_preview(payload: TelegramMediaPreviewIn, _admin=Depends(get_current_admin_user)):
    out: list[TelegramMediaPreviewOut] = []
    for raw in payload.urls:
        url = (raw or "").strip()
        if not url:
            continue
        try:
            imgs = extract_image_urls_from_html_page(url, limit=15)
            out.append(TelegramMediaPreviewOut(url=url, image_urls=imgs))
        except Exception as exc:
            out.append(TelegramMediaPreviewOut(url=url, image_urls=[], error=str(exc)))
    return out


@router.post("/supplier-intelligence/analyze-images", response_model=list[ImageAnalysisOut])
def analyze_images(payload: ImageAnalysisIn, _admin=Depends(get_current_admin_user)):
    out: list[ImageAnalysisOut] = []
    for raw in payload.image_urls:
        url = (raw or "").strip()
        if not url:
            continue
        sig = image_print_signature_from_url(url)
        color = dominant_color_name_from_url(url)
        out.append(ImageAnalysisOut(image_url=url, print_signature=sig, dominant_color=color))
    return out


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
    source_reports: list[ImportSourceReport] = []
    signature_product_map: dict[str, int] = {}
    avito_price_cache: dict[str, float | None] = {}

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

    def find_product_by_signature(sig: str | None) -> models.Product | None:
        if not sig:
            return None
        if sig in signature_product_map:
            return db.query(models.Product).filter(models.Product.id == signature_product_map[sig]).one_or_none()
        # fuzzy match for same print with minor image differences
        for known_sig, pid in signature_product_map.items():
            dist = print_signature_hamming(sig, known_sig)
            if dist is not None and dist <= 6:
                return db.query(models.Product).filter(models.Product.id == pid).one_or_none()
        return None

    def pick_sale_price(title: str, dropship_price: float) -> float:
        if payload.use_avito_pricing:
            key = (title or "").strip().lower()
            if key not in avito_price_cache:
                scan = avito_market_scan(title, max_pages=payload.avito_max_pages, only_new=True)
                avito_price_cache[key] = float(scan.get("suggested")) if scan.get("suggested") is not None else None
            suggested = avito_price_cache.get(key)
            if suggested and suggested > 0:
                return ensure_min_markup_price(float(suggested), dropship_price)
        return suggest_sale_price(dropship_price)

    for src in sources:
        src_url = (src.source_url or "").strip()
        if not src_url:
            continue
        report = _new_source_report(source_id=int(src.id), source_url=src_url)
        try:
            preview = fetch_tabular_preview(src_url, max_rows=max(5, payload.max_items_per_source + 1))
            rows = preview.get("rows_preview") or []
            items = extract_catalog_items(rows, max_items=payload.max_items_per_source)
            if not items and "t.me/" in src_url:
                # fallback for telegram channels/pages: create image-first pseudo items
                imgs = extract_image_urls_from_html_page(src_url, limit=min(payload.max_items_per_source, 30))
                items = [
                    {"title": f"Позиция из TG #{i+1}", "dropship_price": 0.0, "image_url": u}
                    for i, u in enumerate(imgs)
                ]
        except Exception as exc:
            _register_source_error(report, exc)
            source_reports.append(report)
            continue

        for it in items:
            try:
                title = str(it.get("title") or "").strip()
                if not title:
                    continue
                ds_price = float(it.get("dropship_price") or 0)
                if ds_price <= 0:
                    # if no dropship price in source row, keep minimal placeholder for dry-run/preview flows
                    ds_price = 1.0
                cat_name = map_category(title)
                category = get_or_create_category(cat_name)
                slug_base = (slugify(title) or f"item-{category.id}")[:500]
                slug = slug_base
                p = db.query(models.Product).filter(models.Product.slug == slug).one_or_none()
                if not p:
                    p = db.query(models.Product).filter(models.Product.title == title, models.Product.category_id == category.id).one_or_none()

                desc = str(it.get("description") or "").strip()
                if payload.ai_style_description and not desc:
                    if payload.ai_description_enabled and payload.ai_description_provider.lower() == "openrouter":
                        desc = generate_ai_product_description(title, cat_name, it.get("color"))
                    else:
                        desc = generate_youth_description(title, cat_name, it.get("color"))
                sale_price = pick_sale_price(title, ds_price)
                image_url = str(it.get("image_url") or "").strip() or None
                if not image_url and "t.me/" in src_url:
                    try:
                        tg_imgs = extract_image_urls_from_html_page(src_url, limit=3)
                        image_url = tg_imgs[0] if tg_imgs else None
                    except Exception:
                        image_url = None

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

                # image-based analysis: same print with different colors -> same product, new color variants
                sig = image_print_signature_from_url(image_url) if image_url else None
                same_print_product = find_product_by_signature(sig)
                if same_print_product and (not p or p.id != same_print_product.id):
                    p = same_print_product
                elif sig and p:
                    signature_product_map[sig] = int(p.id)

                detected_color = dominant_color_name_from_url(image_url) if image_url else None
                src_color = it.get("color") or detected_color

                size = get_or_create_size(it.get("size"))
                color = get_or_create_color(src_color)
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
                    try:
                        with db.begin_nested():
                            db.add(variant)
                            db.flush()
                        created_variants += 1
                    except IntegrityError:
                        variant = (
                            db.query(models.ProductVariant)
                            .filter(models.ProductVariant.product_id == p.id)
                            .filter(models.ProductVariant.size_id == (size.id if size else None))
                            .filter(models.ProductVariant.color_id == (color.id if color else None))
                            .one_or_none()
                        )
                        if variant is None:
                            raise
                else:
                    if float(variant.price or 0) <= 0 and sale_price > 0:
                        variant.price = Decimal(str(sale_price))
                    if stock_qty > 0 and int(variant.stock_quantity or 0) <= 0:
                        variant.stock_quantity = stock_qty
                    if image_url and not variant.images:
                        variant.images = [image_url]
                    db.add(variant)

                report.imported += 1
            except Exception as exc:
                _register_source_error(report, exc)

        source_reports.append(report)

    top_failing_sources = sorted(
        (x for x in source_reports if x.errors > 0),
        key=lambda x: x.errors,
        reverse=True,
    )[:TOP_FAILING_SOURCES_LIMIT]
    if top_failing_sources:
        logger.warning(
            "supplier import top failures: %s",
            [
                {"source_id": x.source_id, "url": x.url, "errors": x.errors, "error_codes": x.error_codes}
                for x in top_failing_sources
            ],
        )

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
