from __future__ import annotations

import logging
import os
from decimal import Decimal
import re
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, Depends, HTTPException
from celery.result import AsyncResult

from app.tasks.celery_app import celery_app
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin_user, get_db
from app.db import models
from app.services.importer_notifications import slugify
from app.services import media_store
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
    find_similar_images,
    pick_best_offer,
    print_signature_hamming,
    split_size_tokens,
    suggest_sale_price,
    normalize_retail_price,
    search_image_urls_by_title,
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
IMPORT_FALLBACK_STOCK_QTY = 1
RRC_DISCOUNT_RUB = 300
MAX_TELEGRAM_MEDIA_EXPANSIONS_PER_IMPORT = 40


def _looks_like_direct_image_url(url: str | None) -> bool:
    u = str(url or "").strip().lower()
    if not u:
        return False
    if any(ext in u for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif")):
        return True
    return any(token in u for token in ("/file/", "/image/", "/photo/"))


def _normalize_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).strip().split())
    if len(message) > ERROR_MESSAGE_MAX_LEN:
        return f"{message[:ERROR_MESSAGE_MAX_LEN - 3]}..."
    return message


def _split_color_tokens(raw: str | None) -> list[str]:
    txt = str(raw or "").strip()
    if not txt:
        return []
    out: list[str] = []
    for part in re.split(r"[,;/|]+|\s{2,}|\s+-\s+", txt):
        token = " ".join(part.strip().split())
        if token and token not in out:
            out.append(token)
    return out


def _resolve_source_image_url(raw_url: str | None, source_url: str) -> str | None:
    raw = str(raw_url or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low.startswith(("data:", "blob:")):
        return None
    if low.startswith("//"):
        return f"https:{raw}"
    if low.startswith(("http://", "https://", "/uploads/", "uploads/")):
        return raw
    src = str(source_url or "").strip()
    if not src:
        return raw
    try:
        parsed = urlparse(src)
        if not parsed.scheme or not parsed.netloc:
            return raw
        return urljoin(src, raw)
    except Exception:
        return raw


def _prefer_local_image_url(url: str | None, *, title_hint: str | None = None, source_page_url: str | None = None) -> str | None:
    normalized_u = _resolve_source_image_url(url, source_page_url or "") or ""
    if not normalized_u:
        return None
    if not normalized_u.lower().startswith(("http://", "https://")):
        return normalized_u
    try:
        local_candidate = media_store.save_remote_image_to_local(
            normalized_u,
            folder="products/photos",
            filename_hint=title_hint,
            referer=source_page_url,
        )
        if local_candidate:
            return local_candidate
    except Exception:
        pass
    return normalized_u


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _default_max_items_per_source() -> int:
    return _env_int("SUPPLIER_IMPORT_MAX_ITEMS_PER_SOURCE", 1_000_000)


def _default_fetch_timeout_sec() -> int:
    return _env_int("SUPPLIER_IMPORT_FETCH_TIMEOUT_SEC", 180)


def _default_tg_fallback_limit() -> int:
    return _env_int("SUPPLIER_IMPORT_TG_FALLBACK_LIMIT", 1_000_000)


def _default_pre_scan_rows_cap() -> int:
    return _env_int("SUPPLIER_IMPORT_PRE_SCAN_ROWS_CAP", 5_000)


def _default_auto_import_max_items_per_source() -> int:
    return _env_int("SUPPLIER_AUTO_IMPORT_MAX_ITEMS_PER_SOURCE", 10_000)


def _default_auto_import_fetch_timeout_sec() -> int:
    return _env_int("SUPPLIER_AUTO_IMPORT_FETCH_TIMEOUT_SEC", 180)


def _default_auto_import_tg_fallback_limit() -> int:
    return _env_int("SUPPLIER_AUTO_IMPORT_TG_FALLBACK_LIMIT", 5_000)


def _force_sync_auto_import() -> bool:
    return str(os.getenv("SUPPLIER_AUTO_IMPORT_FORCE_SYNC") or "").strip().lower() in {"1", "true", "yes", "on"}


def _has_online_celery_workers() -> bool:
    try:
        insp = celery_app.control.inspect(timeout=1.0)
        if not insp:
            return False
        ping = insp.ping() or {}
        return bool(ping)
    except Exception:
        return False


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
    entries: list[SupplierSourceBulkEntryIn] = Field(default_factory=list, min_length=1, max_length=200)


class SupplierSourceBulkUpsertOut(BaseModel):
    created: int
    updated: int
    skipped: int
    items: list[SupplierSourceOut] = Field(default_factory=list)


class AnalyzeLinksIn(BaseModel):
    links: list[str] = Field(default_factory=list, min_length=1, max_length=30)


class AnalyzeStoredSourcesIn(BaseModel):
    source_ids: list[int] = Field(default_factory=list, min_length=1, max_length=50)


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
    source_ids: list[int] = Field(default_factory=list, min_length=1, max_length=1_000_000)
    max_items_per_source: int = Field(default_factory=_default_max_items_per_source, ge=1, le=1_000_000)
    fetch_timeout_sec: int = Field(default_factory=_default_fetch_timeout_sec, ge=10, le=3600)
    tg_fallback_limit: int = Field(default_factory=_default_tg_fallback_limit, ge=1, le=1_000_000)
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


class AutoImportNowOut(BaseModel):
    queued: bool
    source_count: int = 0
    task: str = ""
    task_id: str | None = None
    status: str | None = None
    created_products: int = 0
    updated_products: int = 0
    created_variants: int = 0
    created_categories: int = 0
    source_reports: list[ImportSourceReport] = Field(default_factory=list)


class SupplierImportTaskStatusOut(BaseModel):
    task_id: str
    status: str
    ready: bool
    successful: bool
    failed: bool
    result: dict | None = None


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
    urls: list[str] = Field(default_factory=list, min_length=1, max_length=50)


class TelegramMediaPreviewOut(BaseModel):
    url: str
    image_urls: list[str] = Field(default_factory=list)
    error: str | None = None


class ImageAnalysisIn(BaseModel):
    image_urls: list[str] = Field(default_factory=list, min_length=1, max_length=50)


class ImageAnalysisOut(BaseModel):
    image_url: str
    print_signature: str | None = None
    dominant_color: str | None = None


class SimilarImagesIn(BaseModel):
    reference_image_url: str = Field(min_length=5, max_length=2000)
    source_ids: list[int] = Field(default_factory=list, min_length=1, max_length=200)
    per_source_limit: int = Field(default=15, ge=1, le=60)
    max_hamming_distance: int = Field(default=8, ge=1, le=20)
    max_results: int = Field(default=20, ge=1, le=100)


class SimilarImageOut(BaseModel):
    source_id: int
    source_url: str
    image_url: str
    distance: int
    similarity: float
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


@router.post("/supplier-intelligence/find-similar-images", response_model=list[SimilarImageOut])
def find_similar_images_in_sources(
    payload: SimilarImagesIn,
    _admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    source_ids = [int(x) for x in payload.source_ids if int(x) > 0]
    if not source_ids:
        return []
    sources = (
        db.query(models.SupplierSource)
        .filter(models.SupplierSource.id.in_(source_ids), models.SupplierSource.active.is_(True))
        .all()
    )
    out: list[SimilarImageOut] = []
    for src in sources:
        src_url = (src.source_url or "").strip()
        if not src_url:
            continue
        try:
            candidate_urls = extract_image_urls_from_html_page(src_url, limit=payload.per_source_limit)
            matches = find_similar_images(
                payload.reference_image_url,
                candidate_urls,
                max_hamming_distance=payload.max_hamming_distance,
                limit=payload.max_results,
            )
            for item in matches:
                out.append(
                    SimilarImageOut(
                        source_id=int(src.id),
                        source_url=src_url,
                        image_url=str(item.get("image_url") or ""),
                        distance=int(item.get("distance") or 0),
                        similarity=float(item.get("similarity") or 0.0),
                        dominant_color=(str(item.get("dominant_color")) if item.get("dominant_color") else None),
                    )
                )
        except Exception:
            continue
    out.sort(key=lambda x: (x.distance, -x.similarity))
    return out[: payload.max_results]


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
    offers: list[OfferIn] = Field(default_factory=list, min_length=1, max_length=100)


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
    title_product_candidates: dict[str, list[tuple[int, str | None]]] = {}
    avito_price_cache: dict[str, float | None] = {}
    source_items_map: dict[int, list[dict[str, object]]] = {}
    title_min_dropship: dict[str, float] = {}
    known_image_urls: list[str] = []
    known_item_by_image_url: dict[str, dict[str, object]] = {}
    telegram_media_cache: dict[str, list[str]] = {}
    telegram_media_expand_count = 0
    pre_scan_error_messages: dict[int, str] = {}

    def _title_key(raw_title: str | None) -> str:
        return re.sub(r"\s+", " ", str(raw_title or "").strip().lower())

    def _is_placeholder_title(raw_title: str | None) -> bool:
        return _title_key(raw_title).startswith("позиция из tg #")

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
        try:
            with db.begin_nested():
                db.add(c)
                db.flush()
            created_categories += 1
            return c
        except IntegrityError:
            c2 = db.query(models.Category).filter(models.Category.slug == slug).one_or_none()
            if not c2:
                c2 = db.query(models.Category).filter(models.Category.name == n).one_or_none()
            if c2:
                return c2
            raise

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


    def _group_title(raw_title: str | None) -> str:
        return re.sub(r"\s+", " ", str(raw_title or "").strip())

    def _pick_product_id_by_signature(
        candidates: list[tuple[int, str | None]],
        sig: str | None,
        max_distance: int = 6,
    ) -> int | None:
        if not candidates:
            return None
        if not sig:
            return int(candidates[0][0])

        for pid, known_sig in candidates:
            if known_sig and known_sig == sig:
                return int(pid)

        for pid, known_sig in candidates:
            if not known_sig:
                continue
            dist = print_signature_hamming(sig, known_sig)
            if dist is not None and dist <= max_distance:
                return int(pid)

        return int(candidates[0][0])

    def remember_product_candidate(base_key: str, product_id: int, sig: str | None) -> None:
        if not base_key:
            return
        bucket = title_product_candidates.setdefault(base_key, [])
        item = (int(product_id), sig or None)
        if item in bucket:
            return
        bucket.append(item)
        if len(bucket) > 25:
            del bucket[:-25]

    def pick_sale_price(
        title: str,
        dropship_price: float,
        min_dropship_price: float | None = None,
        rrc_price: float | None = None,
    ) -> float:
        base = float(min_dropship_price or 0) if float(min_dropship_price or 0) > 0 else float(dropship_price or 0)
        if base <= 0:
            base = float(dropship_price or 0)

        # Top priority: supplier RRC/RRP minus fixed discount.
        if rrc_price is not None:
            try:
                rrc_val = float(rrc_price)
                if rrc_val > 0:
                    return normalize_retail_price(max(1.0, round(rrc_val - RRC_DISCOUNT_RUB, 0)))
            except Exception:
                pass

        if payload.use_avito_pricing:
            key = (title or "").strip().lower()
            if key not in avito_price_cache:
                try:
                    scan = avito_market_scan(title, max_pages=payload.avito_max_pages, only_new=True)
                    avito_price_cache[key] = float(scan.get("suggested")) if scan.get("suggested") is not None else None
                except Exception:
                    # Avito pricing is best-effort: if scan fails we must still import product
                    avito_price_cache[key] = None
            suggested = avito_price_cache.get(key)
            if suggested and suggested > 0:
                return normalize_retail_price(ensure_min_markup_price(float(suggested), base))
        return normalize_retail_price(ensure_min_markup_price(round(base * 1.4, 0), base))

    # pre-scan all selected sources to get minimal закупка per title and known image pool
    for src in sources:
        src_url = (src.source_url or "").strip()
        if not src_url:
            source_items_map[int(src.id)] = []
            continue
        try:
            preview = fetch_tabular_preview(
                src_url,
                timeout_sec=payload.fetch_timeout_sec,
                max_rows=max(5, min(payload.max_items_per_source + 1, _default_pre_scan_rows_cap())),
            )
            rows = preview.get("rows_preview") or []
            items = extract_catalog_items(rows, max_items=payload.max_items_per_source)
            if not items and "t.me/" in src_url:
                imgs = extract_image_urls_from_html_page(src_url, limit=min(payload.max_items_per_source, payload.tg_fallback_limit))
                items = [
                    {
                        "title": f"Позиция из TG #{i+1}",
                        "dropship_price": 0.0,
                        "image_url": u,
                        "image_urls": [u],
                        "__tg_fallback__": True,
                    }
                    for i, u in enumerate(imgs)
                ]
            source_items_map[int(src.id)] = items
            for it in items:
                title = str(it.get("title") or "").strip()
                ds_price = float(it.get("dropship_price") or 0)
                if title and ds_price > 0 and not _is_placeholder_title(title):
                    k = _title_key(title)
                    prev = title_min_dropship.get(k)
                    title_min_dropship[k] = ds_price if prev is None else min(prev, ds_price)
                row_image_urls = [str(x).strip() for x in (it.get("image_urls") or []) if str(x).strip()]
                image_url = str(it.get("image_url") or "").strip()
                pool = [image_url, *row_image_urls]
                if title and ds_price > 0 and not _is_placeholder_title(title):
                    for u in pool:
                        uu = str(u or "").strip()
                        if not uu:
                            continue
                        if uu not in known_item_by_image_url:
                            known_item_by_image_url[uu] = dict(it)
                            known_image_urls.append(uu)
        except Exception as exc:
            src_id = int(src.id)
            source_items_map[src_id] = []
            pre_scan_error_messages[src_id] = _normalize_error_message(exc)
            logger.exception("Supplier pre-scan failed for source_id=%s url=%s", src_id, src_url)

    for src in sources:
        src_url = (src.source_url or "").strip()
        if not src_url:
            continue
        report = _new_source_report(source_id=int(src.id), source_url=src_url)
        try:
            items = source_items_map.get(int(src.id), [])
        except Exception as exc:
            _register_source_error(report, exc)
            source_reports.append(report)
            continue

        pre_scan_error = pre_scan_error_messages.get(int(src.id))
        if pre_scan_error and not items:
            _register_source_error(report, RuntimeError(f"pre-scan failed: {pre_scan_error}"))

        for it in items:
            try:
                title = str(it.get("title") or "").strip()
                ds_price = float(it.get("dropship_price") or 0)
                is_tg_fallback = bool(it.get("__tg_fallback__")) or _is_placeholder_title(title)
                if is_tg_fallback:
                    fallback_ref = str(it.get("image_url") or "").strip()
                    if not fallback_ref:
                        fallback_images = [str(x).strip() for x in (it.get("image_urls") or []) if str(x).strip()]
                        fallback_ref = fallback_images[0] if fallback_images else ""
                    matched_item: dict[str, object] | None = None
                    if fallback_ref and known_image_urls:
                        try:
                            best = find_similar_images(
                                fallback_ref,
                                known_image_urls,
                                max_hamming_distance=7,
                                limit=1,
                            )
                        except Exception:
                            best = []
                        if best:
                            matched_item = known_item_by_image_url.get(str(best[0].get("image_url") or ""))
                    if matched_item:
                        if not title or _is_placeholder_title(title):
                            title = str(matched_item.get("title") or "").strip()
                        if ds_price <= 0:
                            ds_price = float(matched_item.get("dropship_price") or 0)
                        if not it.get("color") and matched_item.get("color"):
                            it["color"] = matched_item.get("color")
                        if not it.get("size") and matched_item.get("size"):
                            it["size"] = matched_item.get("size")
                        if not it.get("description") and matched_item.get("description"):
                            it["description"] = matched_item.get("description")

                if not title or ds_price <= 0:
                    # skip generic TG placeholders and unresolved items instead of polluting catalog
                    continue

                base_title_key = _title_key(title)
                title_for_group = _group_title(title)
                min_dropship = title_min_dropship.get(base_title_key)
                cat_name = map_category(title)
                category = get_or_create_category(cat_name)
                effective_title = (title_for_group or title).strip()
                slug_base = (slugify(effective_title) or f"item-{category.id}")[:500]
                slug = slug_base
                p = db.query(models.Product).filter(models.Product.slug == slug).one_or_none()
                if not p:
                    p = db.query(models.Product).filter(models.Product.title == effective_title, models.Product.category_id == category.id).one_or_none()

                desc = str(it.get("description") or "").strip()
                if payload.ai_style_description and not desc:
                    if payload.ai_description_enabled and payload.ai_description_provider.lower() == "openrouter":
                        desc = generate_ai_product_description(title, cat_name, it.get("color"))
                    else:
                        desc = generate_youth_description(title, cat_name, it.get("color"))
                sale_price = pick_sale_price(title, ds_price, min_dropship_price=min_dropship, rrc_price=(it.get("rrc_price") if isinstance(it, dict) else None))
                row_image_urls = [str(x).strip() for x in (it.get("image_urls") or []) if str(x).strip()]
                image_url = str(it.get("image_url") or "").strip() or None
                if not image_url and row_image_urls:
                    image_url = row_image_urls[0]
                if not image_url and "t.me/" in src_url:
                    try:
                        tg_imgs = extract_image_urls_from_html_page(src_url, limit=3)
                        image_url = tg_imgs[0] if tg_imgs else None
                        if tg_imgs:
                            row_image_urls = [str(x).strip() for x in tg_imgs if str(x).strip()]
                    except Exception:
                        image_url = None

                image_urls: list[str] = []
                for u in [image_url, *row_image_urls]:
                    uu = _resolve_source_image_url(u, src_url)
                    if uu and uu not in image_urls:
                        image_urls.append(uu)

                # expand telegram post links into direct image URLs with safety caps,
                # otherwise large imports can spend minutes on network lookups.
                expanded_image_urls: list[str] = []
                has_direct_image = any(_looks_like_direct_image_url(u) for u in image_urls)
                for candidate in image_urls:
                    cu = str(candidate or "").strip()
                    if not cu:
                        continue
                    if ("t.me/" in cu or "telegram.me/" in cu) and not has_direct_image:
                        tg_media = telegram_media_cache.get(cu)
                        if tg_media is None:
                            if telegram_media_expand_count >= MAX_TELEGRAM_MEDIA_EXPANSIONS_PER_IMPORT:
                                tg_media = []
                            else:
                                telegram_media_expand_count += 1
                                try:
                                    tg_media = extract_image_urls_from_html_page(cu, limit=8)
                                except Exception:
                                    tg_media = []
                                telegram_media_cache[cu] = list(tg_media)
                        if tg_media:
                            for media_u in tg_media:
                                uu = _resolve_source_image_url(media_u, cu)
                                if uu and uu not in expanded_image_urls:
                                    expanded_image_urls.append(uu)
                            continue
                    if cu not in expanded_image_urls:
                        expanded_image_urls.append(cu)

                if expanded_image_urls:
                    image_urls = expanded_image_urls
                    image_url = image_urls[0]

                # store supplier images locally when possible so they are stable
                # across devices and not affected by source-side hotlink limits.
                localized_image_urls: list[str] = []
                for img_u in image_urls:
                    local_u = _prefer_local_image_url(img_u, title_hint=title, source_page_url=src_url)
                    if local_u and local_u not in localized_image_urls:
                        localized_image_urls.append(local_u)

                if localized_image_urls:
                    image_urls = localized_image_urls
                    image_url = image_urls[0]

                # Last-resort quality step: if supplier didn't provide any image,
                # search by title and download a few images to local storage.
                if not image_urls:
                    try:
                        searched = search_image_urls_by_title(title, limit=3)
                    except Exception:
                        searched = []
                    for remote_u in searched:
                        try:
                            local_u = media_store.save_remote_image_to_local(remote_u, folder="products/photos", filename_hint=title, referer=src_url)
                        except Exception:
                            continue
                        if local_u and local_u not in image_urls:
                            image_urls.append(local_u)
                    if image_urls:
                        image_url = image_urls[0]

                # auto-enrich item gallery with similar photos from known supplier pool
                if image_url and known_image_urls:
                    try:
                        sim_items = find_similar_images(image_url, known_image_urls, max_hamming_distance=5, limit=8)
                        for sim in sim_items:
                            sim_url = str(sim.get("image_url") or "").strip()
                            if not sim_url:
                                continue
                            matched_meta = known_item_by_image_url.get(sim_url) or {}
                            if _title_key(str(matched_meta.get("title") or "")) != _title_key(title):
                                continue
                            final_sim_url = _prefer_local_image_url(sim_url, title_hint=title, source_page_url=src_url)
                            if not final_sim_url or final_sim_url in image_urls:
                                continue
                            image_urls.append(final_sim_url)
                            if len(image_urls) >= 8:
                                break
                    except Exception:
                        pass

                if not p:
                    # unique slug fallback
                    n = 2
                    while db.query(models.Product).filter(models.Product.slug == slug).first() is not None:
                        slug = f"{slug_base[:490]}-{n}"
                        n += 1
                    p = models.Product(
                        title=effective_title,
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
                    if image_urls:
                        for idx, img_u in enumerate(image_urls[:8]):
                            db.add(models.ProductImage(product_id=p.id, url=img_u, sort=idx))
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
                    if image_urls:
                        existing_urls = {
                            str(x.url).strip()
                            for x in db.query(models.ProductImage).filter(models.ProductImage.product_id == p.id).all()
                            if str(x.url).strip()
                        }
                        next_sort = int(
                            db.query(models.ProductImage)
                            .filter(models.ProductImage.product_id == p.id)
                            .count()
                        )
                        for img_u in image_urls[:8]:
                            if img_u in existing_urls:
                                continue
                            db.add(models.ProductImage(product_id=p.id, url=img_u, sort=next_sort))
                            next_sort += 1
                            changed = True
                    if changed:
                        db.add(p)
                        updated_products += 1

                try:
                    sig = image_print_signature_from_url(image_url) if image_url else None
                except Exception:
                    sig = None
                candidate_pid = _pick_product_id_by_signature(
                    title_product_candidates.get(base_title_key, []),
                    sig,
                    max_distance=6,
                )
                if candidate_pid and (not p or int(p.id) != int(candidate_pid)):
                    matched_p = db.query(models.Product).filter(models.Product.id == int(candidate_pid)).one_or_none()
                    if matched_p is not None:
                        p = matched_p

                # image-based analysis: same print with different colors -> same product, new color variants
                same_print_product = find_product_by_signature(sig)
                if same_print_product and (not p or p.id != same_print_product.id):
                    p = same_print_product
                elif sig and p:
                    signature_product_map[sig] = int(p.id)

                if p:
                    remember_product_candidate(base_title_key, int(p.id), sig)

                try:
                    detected_color = dominant_color_name_from_url(image_url) if image_url else None
                except Exception:
                    detected_color = None
                src_color = it.get("color") or detected_color
                color_tokens = _split_color_tokens(src_color)
                if not color_tokens and detected_color:
                    color_tokens = [detected_color]
                if not color_tokens:
                    color_tokens = [""]

                size_tokens = split_size_tokens(it.get("size"))
                if not size_tokens:
                    size_tokens = [""]

                raw_stock = it.get("stock") if isinstance(it, dict) else None
                try:
                    stock_qty = int(raw_stock) if raw_stock is not None else IMPORT_FALLBACK_STOCK_QTY
                except Exception:
                    stock_qty = IMPORT_FALLBACK_STOCK_QTY
                if stock_qty <= 0:
                    stock_qty = IMPORT_FALLBACK_STOCK_QTY
                combinations = max(1, len(size_tokens) * len(color_tokens))
                per_variant_stock = stock_qty // combinations if stock_qty > 0 and combinations > 1 else stock_qty

                for color_name in color_tokens:
                    color = get_or_create_color(color_name) if color_name else None
                    for size_name in size_tokens:
                        size = get_or_create_size(size_name) if size_name else None
                        variant = (
                            db.query(models.ProductVariant)
                            .filter(models.ProductVariant.product_id == p.id)
                            .filter(models.ProductVariant.size_id == (size.id if size else None))
                            .filter(models.ProductVariant.color_id == (color.id if color else None))
                            .one_or_none()
                        )
                        if variant is None:
                            variant = models.ProductVariant(
                                product_id=p.id,
                                size_id=size.id if size else None,
                                color_id=color.id if color else None,
                                price=Decimal(str(sale_price)),
                                stock_quantity=max(0, per_variant_stock),
                                images=image_urls or ([image_url] if image_url else None),
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
                            if per_variant_stock > 0 and int(variant.stock_quantity or 0) <= 0:
                                variant.stock_quantity = per_variant_stock
                            if image_urls and not variant.images:
                                variant.images = image_urls
                            elif image_url and not variant.images:
                                variant.images = [image_url]
                            db.add(variant)


                report.imported += 1
            except Exception as exc:
                _register_source_error(report, exc)

        if not payload.dry_run:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
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

    return ImportProductsOut(
        created_categories=created_categories,
        created_products=created_products,
        updated_products=updated_products,
        created_variants=created_variants,
        source_reports=source_reports,
    )


@router.post("/supplier-intelligence/auto-import-now", response_model=AutoImportNowOut)
def run_auto_import_now(
    _admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    source_ids = [
        int(x.id)
        for x in db.query(models.SupplierSource)
        .filter(models.SupplierSource.active == True)  # noqa: E712
        .all()
        if getattr(x, "id", None)
    ]
    if not source_ids:
        raise HTTPException(status_code=400, detail="Нет активных источников")

    payload = {
        "source_ids": source_ids,
        "dry_run": False,
        "publish_visible": True,
        "ai_style_description": True,
        "ai_description_enabled": True,
        "use_avito_pricing": False,
        "avito_max_pages": 1,
        "max_items_per_source": _default_auto_import_max_items_per_source(),
        "fetch_timeout_sec": _default_auto_import_fetch_timeout_sec(),
        "tg_fallback_limit": _default_auto_import_tg_fallback_limit(),
    }

    if _force_sync_auto_import() or not _has_online_celery_workers():
        result = import_products_from_sources(
            payload=ImportProductsIn(**payload),
            _admin=True,
            db=db,
        )
        return AutoImportNowOut(
            queued=False,
            source_count=len(source_ids),
            task="tasks.supplier_import_from_sources",
            status="SUCCESS",
            created_categories=int(getattr(result, "created_categories", 0) or 0),
            created_products=int(getattr(result, "created_products", 0) or 0),
            updated_products=int(getattr(result, "updated_products", 0) or 0),
            created_variants=int(getattr(result, "created_variants", 0) or 0),
            source_reports=list(getattr(result, "source_reports", []) or []),
        )

    task = celery_app.send_task("tasks.supplier_import_from_sources", kwargs={"payload": payload})

    return AutoImportNowOut(
        queued=True,
        source_count=len(source_ids),
        task="tasks.supplier_import_from_sources",
        task_id=str(task.id),
        status="PENDING",
    )


@router.get("/supplier-intelligence/tasks/{task_id}", response_model=SupplierImportTaskStatusOut)
def get_supplier_import_task_status(
    task_id: str,
    _admin=Depends(get_current_admin_user),
):
    result = AsyncResult(task_id, app=celery_app)
    payload = result.result if isinstance(result.result, dict) else None
    return SupplierImportTaskStatusOut(
        task_id=task_id,
        status=str(result.status),
        ready=bool(result.ready()),
        successful=bool(result.successful()),
        failed=bool(result.failed()),
        result=payload,
    )


class MarketPriceIn(BaseModel):
    prices: list[float] = Field(default_factory=list, min_length=1, max_length=300)


class MarketPriceOut(BaseModel):
    suggested_price: float | None


@router.post("/supplier-intelligence/estimate-market-price", response_model=MarketPriceOut)
def estimate_price(payload: MarketPriceIn, _admin=Depends(get_current_admin_user)):
    return MarketPriceOut(suggested_price=estimate_market_price(payload.prices))
