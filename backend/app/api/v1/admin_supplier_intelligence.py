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
from app.services.supplier_profiles import normalize_title_for_supplier
from app.services.supplier_intelligence import (
    SupplierOffer,
    ensure_min_markup_price,
    estimate_market_price,
    avito_market_scan,
    dominant_color_name_from_url,
    detect_source_kind,
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
    _extract_size_stock_map as extract_size_stock_map,
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
IMPORT_FALLBACK_STOCK_QTY = 9_999
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






def _extract_shop_vkus_color_tokens(item: dict, image_urls: list[str] | None = None) -> list[str]:
    palette = (
        "черный", "чёрный", "белый", "серый", "красный", "синий", "голубой", "зеленый", "зелёный",
        "бежевый", "коричневый", "розовый", "фиолетовый", "желтый", "оранжевый",
        "black", "white", "grey", "gray", "red", "blue", "green", "beige", "brown", "pink", "purple", "yellow", "orange",
    )
    blob_parts: list[str] = []
    for key in ("color", "title", "description", "text", "notes"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            blob_parts.append(v)
    blob = " ".join(blob_parts).lower()
    found: list[str] = []
    for c in palette:
        if re.search(rf"(?<!\w){re.escape(c)}(?!\w)", blob):
            if c not in found:
                found.append(c)

    if len(found) >= 2:
        return found[:3]

    # Fallback: infer up to 2 dominant colors from gallery, only for strong repeated signals.
    color_hits: dict[str, int] = {}
    for u in (image_urls or [])[:12]:
        try:
            nm = dominant_color_name_from_url(u)
        except Exception:
            nm = None
        key = str(nm or "").strip().lower()
        if not key or key in {"мульти"}:
            continue
        color_hits[key] = int(color_hits.get(key, 0) or 0) + 1
    ranked = [k for k, _ in sorted(color_hits.items(), key=lambda x: x[1], reverse=True)]
    strong = [k for k, v in sorted(color_hits.items(), key=lambda x: x[1], reverse=True) if v >= 2]
    if len(strong) >= 2:
        return strong[:3]
    if strong:
        return strong[:1]
    if found:
        return found[:1]
    if ranked:
        return ranked[:1]
    return []

def _extract_shop_vkus_stock_map(item: dict) -> dict[str, int]:
    def _iter_stock_like_values(src: dict) -> list[str]:
        vals: list[str] = []
        for k, v in (src or {}).items():
            if not isinstance(v, str) or not v.strip():
                continue
            key_low = str(k or "").strip().lower()
            if key_low in {"stock", "stock_text", "availability", "наличие"} or any(
                marker in key_low for marker in ("availability", "налич", "stock")
            ):
                vals.append(v)
        return vals

    blob_parts: list[str] = []
    for key in ("size", "sizes", "stock", "stock_text", "title", "description", "text", "notes"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            blob_parts.append(v)
    blob_parts.extend(_iter_stock_like_values(item))
    blob = "\n".join(blob_parts)
    if not blob:
        return {}

    def _normalize_map(raw_map: dict[str, int]) -> dict[str, int]:
        out: dict[str, int] = {}
        for k, v in (raw_map or {}).items():
            kk = str(k or "").strip().replace(",", ".")
            try:
                vv = max(0, int(v))
            except Exception:
                continue
            if kk:
                out[kk] = vv
        return out

    # Prefer explicit availability fragments to avoid mixing in full size ranges
    # from neighboring text like "Размеры: 41-45".
    availability_chunks = [
        str(m.group(1) or "").strip()
        for m in re.finditer(r"(?i)(?:наличие|в\s*наличии|stock)\s*[:\-]?\s*([^\n]+)", blob)
        if str(m.group(1) or "").strip()
    ]
    def _parse_plain_available_sizes(text: str) -> dict[str, int]:
        raw = str(text or "")
        if not raw.strip():
            return {}
        low = raw.lower()
        if any(marker in low for marker in ("нет", "out of stock", "sold out", "распродан", "законч")):
            return {}
        # Ignore explicit quantity notations to avoid overriding richer parsers.
        if re.search(r"\b\d{2,3}\s*[:=]\s*\d{1,4}\b|\b\d{2,3}\s*\(\s*\d{1,4}", raw):
            return {}
        # For shop_vkus, plain size lists like "41 42 44" or "41,42,44" mean in-stock sizes.
        # Do not treat ranges like "41-45" as stock map.
        if not re.search(r"[,;/\s]", raw):
            return {}
        has_list_delimiter = bool(re.search(r"[,;/]", raw))
        has_range = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\s*[-–—]\s*\d{2,3}(?:[.,]5)?\b", raw))
        if has_range and not has_list_delimiter:
            return {}
        out: dict[str, int] = {}
        for m in re.finditer(r"(?<!\d)(\d{2,3}(?:[.,]5)?)(?!\d)", raw):
            token = str(m.group(1) or "").replace(",", ".").strip()
            if not token:
                continue
            try:
                v = float(token)
            except Exception:
                continue
            if v < 20 or v > 60:
                continue
            key = str(int(v)) if v.is_integer() else token
            out[key] = 1
        return out

    def _is_plain_range_only(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        has_range = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\s*[-–—]\s*\d{2,3}(?:[.,]5)?\b", raw))
        if not has_range:
            return False
        # Treat comma/semicolon/slash lists as explicit available sizes; plain range is ambiguous.
        has_list_delimiter = bool(re.search(r"[,;/]", raw))
        has_qty_markers = bool(re.search(r"\b\d{2,3}\s*[:=]\s*\d{1,4}\b|\b\d{2,3}\s*\(\s*\d{1,4}", raw))
        return has_range and not has_list_delimiter and not has_qty_markers

    for chunk in availability_chunks:
        plain_available_chunk = _parse_plain_available_sizes(chunk)
        if plain_available_chunk:
            return plain_available_chunk
        # Do not expand ambiguous ranges like "41-45" from availability text into all sizes in stock.
        if _is_plain_range_only(chunk):
            continue
        parsed_chunk = _normalize_map(extract_size_stock_map(chunk))
        if parsed_chunk:
            return parsed_chunk

    stock_only_parts: list[str] = _iter_stock_like_values(item)
    if stock_only_parts:
        stock_blob = "\n".join(stock_only_parts)
        parsed_stock_only = _normalize_map(extract_size_stock_map(stock_blob))
        if _is_plain_range_only(stock_blob):
            parsed_stock_only = {}
        if parsed_stock_only:
            return parsed_stock_only
        plain_available_stock_only = _parse_plain_available_sizes("\n".join(stock_only_parts))
        if plain_available_stock_only:
            return plain_available_stock_only

    strict: dict[str, int] = {}
    for m in re.finditer(r"(?<!\d)(\d{2,3}(?:[.,]5)?)\s*\(\s*(\d{1,4})\s*(?:шт|pcs|pc)?\s*\)", blob, flags=re.IGNORECASE):
        sz = str(m.group(1) or "").replace(",", ".").strip()
        try:
            qty = max(0, int(m.group(2) or 0))
        except Exception:
            continue
        if sz:
            strict[sz] = qty
    return strict

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



def _is_shop_vkus_item_context(supplier_key: str | None, source_url: str, item: dict | None = None) -> bool:
    if str(supplier_key or "").strip().lower() == "shop_vkus":
        return True
    src = str(source_url or "").lower()
    if "shop_vkus" in src:
        return True
    if not isinstance(item, dict):
        return False
    for key in ("image_url", "source_url", "url", "text", "description", "notes", "stock", "stock_text"):
        val = item.get(key)
        if isinstance(val, str) and "shop_vkus" in val.lower():
            return True
    for u in (item.get("image_urls") or []):
        if "shop_vkus" in str(u or "").lower():
            return True

    # Heuristic fallback for feeds without explicit shop_vkus link/label:
    # rows with footwear size range and per-item availability sizes in stock cell
    # should be parsed like shop_vkus (keep only listed sizes in stock).
    size_raw = str(item.get("size") or "").strip()
    stock_raw = str(item.get("stock_text") or item.get("availability") or item.get("stock") or "").strip()
    size_has_range = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\s*[-–—]\s*\d{2,3}(?:[.,]5)?\b", size_raw))
    stock_has_sizes = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\b", stock_raw))
    # Even without explicit words/units, shop_vkus-like sheets store remaining sizes in stock cell.
    if size_has_range and stock_has_sizes:
        return True

    return False


def _is_likely_product_image(url: str) -> bool:
    low = str(url or "").strip().lower()
    if not low:
        return False
    if any(tok in low for tok in ("emoji", "sticker", "logo", "banner", "promo", "avatar", "icon", "watermark")):
        return False

    local_path: str | None = None
    if low.startswith("/"):
        local_path = str(url).lstrip("/")
    elif low.startswith("uploads/"):
        local_path = str(url)

    if local_path:
        try:
            from PIL import Image, ImageStat  # type: ignore
            with Image.open(local_path) as img:
                w, h = img.size
                if w < 320 or h < 320:
                    return False
                gray = img.convert("L")
                stat = ImageStat.Stat(gray)
                std = float(stat.stddev[0] if stat.stddev else 0.0)
                try:
                    entropy = float(gray.entropy())
                except Exception:
                    entropy = 0.0
                if entropy < 2.9 and std < 14.0:
                    return False
        except Exception:
            pass

    return True

def _score_gallery_image(url: str | None) -> float:
    u = str(url or "").strip()
    if not u:
        return -1e9

    low = u.lower()
    score = 0.0

    # URL-level heuristics
    if any(k in low for k in ("logo", "avatar", "sticker", "emoji", "icon", "banner", "watermark")):
        score -= 80.0
    if any(k in low for k in ("shop-vkus", "shop_vkus")) and any(k in low for k in ("logo", "banner", "promo")):
        score -= 60.0
    if any(ext in low for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif")):
        score += 5.0

    # Local-file quality heuristics (if localized and Pillow is available)
    local_path: str | None = None
    if low.startswith("/"):
        local_path = u.lstrip("/")
    elif low.startswith("uploads/"):
        local_path = u

    if local_path:
        try:
            from PIL import Image, ImageStat  # type: ignore
            with Image.open(local_path) as img:
                w, h = img.size
                pixels = max(1, int(w) * int(h))
                mp = pixels / 1_000_000.0
                score += min(40.0, mp * 20.0)

                gray = img.convert("L")
                stat = ImageStat.Stat(gray)
                std = float(stat.stddev[0] if stat.stddev else 0.0)
                score += min(30.0, std * 0.8)

                try:
                    entropy = float(gray.entropy())
                except Exception:
                    entropy = 0.0
                score += min(20.0, max(0.0, entropy - 4.0) * 4.0)
                if entropy < 3.4:
                    score -= 55.0

                if pixels < 220_000:
                    score -= 70.0
                elif pixels < 500_000:
                    score -= 20.0

                ratio = (w / h) if h else 1.0
                if ratio < 0.45 or ratio > 2.4:
                    score -= 20.0
                if 0.85 <= ratio <= 1.15 and std < 18:
                    score -= 30.0
        except Exception:
            pass

    return score




def _filter_gallery_main_signature_cluster(image_urls: list[str]) -> list[str]:
    if len(image_urls) < 6:
        return image_urls

    sigs: list[tuple[str, str]] = []
    for u in image_urls:
        try:
            sig = image_print_signature_from_url(u)
        except Exception:
            sig = None
        if sig:
            sigs.append((u, sig))

    if len(sigs) < 4:
        return image_urls

    clusters: list[list[tuple[str, str]]] = []
    for item in sigs:
        placed = False
        for cl in clusters:
            rep = cl[0][1]
            d = print_signature_hamming(item[1], rep)
            if d is not None and d <= 8:
                cl.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])

    if not clusters:
        return image_urls
    clusters.sort(key=len, reverse=True)
    main = clusters[0]
    main_urls = {u for u, _ in main}

    # Drop outlier clusters only when the dominant cluster is clearly large enough.
    if len(main_urls) >= max(4, len(image_urls) // 2):
        return [u for u in image_urls if u in main_urls]
    return image_urls

def _rerank_gallery_images(image_urls: list[str], supplier_key: str | None = None) -> list[str]:
    if not image_urls:
        return []
    raw_norm: list[str] = [str(u or "").strip() for u in image_urls if str(u or "").strip()]

    uniq: list[str] = []
    seen = set()
    for uu in raw_norm:
        if uu in seen:
            continue
        seen.add(uu)
        uniq.append(uu)

    if len(uniq) <= 1:
        return uniq

    if supplier_key == "shop_vkus":
        # shop_vkus feeds often prepend two service frames in longer galleries.
        pre = list(uniq)
        source = raw_norm or uniq
        if len(source) >= 7:
            pre = uniq[2:]
        elif len(source) > 2:
            first_two = source[:2]
            rest = source[2:]
            has_supplier_marker = any(
                ("shop_vkus" in str(u or "").lower()) or ("shop-vkus" in str(u or "").lower())
                for u in first_two
            )
            leading_pair_suspicious = any((not _is_likely_product_image(u)) or (_score_gallery_image(u) < 0) for u in first_two)
            duplicated_cover = bool(first_two and first_two[0] in rest)
            second_is_suspicious = bool((not _is_likely_product_image(first_two[1])) or (_score_gallery_image(first_two[1]) < 0)) if len(first_two) >= 2 else False

            should_drop_pair = False
            if len(source) >= 6 and (has_supplier_marker or leading_pair_suspicious or duplicated_cover):
                should_drop_pair = True
            elif len(source) == 5 and (has_supplier_marker or leading_pair_suspicious or (duplicated_cover and second_is_suspicious)):
                should_drop_pair = True

            if should_drop_pair:
                pre = uniq[2:]

        filtered = [u for u in pre if _is_likely_product_image(u)]
        work = filtered if filtered else pre

        work = _filter_gallery_main_signature_cluster(work)
        if len(work) > 7:
            work = work[:7]
        return work

    ranked = sorted(uniq, key=lambda x: _score_gallery_image(x), reverse=True)
    return ranked


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
        # keep remote URL only when it already looks like a direct image link;
        # otherwise we may save broken t.me/page links into product gallery.
        if _looks_like_direct_image_url(normalized_u):
            return normalized_u
        return None
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


class ImportQualityAuditItem(BaseModel):
    product_id: int
    title: str
    category_id: int | None = None
    supplier: str | None = None
    issue: str


class ImportQualityAuditOut(BaseModel):
    total_visible: int
    one_photo_count: int
    no_size_count: int
    duplicate_title_count: int
    no_stock_count: int
    sample_items: list[ImportQualityAuditItem] = Field(default_factory=list)


def _new_source_report(source_id: int, source_url: str) -> ImportSourceReport:
    return ImportSourceReport(source_id=source_id, url=source_url)


def _register_source_error(report: ImportSourceReport, exc: Exception, context: str | None = None) -> None:
    code = _classify_import_error(exc)
    message = _normalize_error_message(exc)
    if context:
        message = f"{context}: {message}"
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
    supplier_has_table_source: dict[str, bool] = {}
    supplier_tg_images_by_title: dict[str, dict[str, list[str]]] = {}
    supplier_tg_fallback_images: dict[str, list[str]] = {}
    existing_product_by_supplier_title: dict[tuple[str, str], models.Product] = {}
    existing_product_by_global_title: dict[tuple[int, str], models.Product] = {}

    def _title_key(raw_title: str | None) -> str:
        return re.sub(r"\s+", " ", str(raw_title or "").strip().lower())

    def _supplier_key(raw_supplier: str | None) -> str:
        return re.sub(r"\s+", " ", str(raw_supplier or "").strip().lower())

    def _title_media_key(raw_title: str | None) -> str:
        txt = str(raw_title or "").lower()
        txt = re.sub(r"[^\w\s]+", " ", txt, flags=re.U)
        tokens = [t for t in re.split(r"\s+", txt) if t]
        stop = {
            "new", "balance", "nike", "adidas", "puma", "reebok", "asics", "nb",
            "муж", "жен", "унисекс", "кроссовки", "кеды", "обувь",
            "black", "white", "grey", "gray", "beige", "brown", "blue", "green", "red",
            "черный", "чёрный", "белый", "серый", "бежевый", "коричневый", "синий", "зеленый", "зелёный", "красный",
        }
        out: list[str] = []
        for t in tokens:
            if t in stop:
                continue
            if re.fullmatch(r"\d{1,2}", t):
                # likely a size
                continue
            out.append(t)
        return " ".join(out[:10]).strip()

    def _pick_tg_images_for_title(supplier_key: str, raw_title: str) -> list[str]:
        by_title = supplier_tg_images_by_title.get(supplier_key, {})
        if not by_title:
            return []
        exact_key = _title_key(raw_title)
        if exact_key in by_title:
            return list(by_title.get(exact_key) or [])

        # shop_vkus: avoid fuzzy cross-title merges that can mix different models in one gallery.
        if supplier_key == "shop_vkus":
            return []

        media_key = _title_media_key(raw_title)
        media_tokens = set(media_key.split())
        if not media_tokens:
            return []

        best_key = ""
        best_score = 0.0
        for k in by_title.keys():
            k_tokens = set(_title_media_key(k).split())
            if not k_tokens:
                continue
            inter = len(media_tokens & k_tokens)
            if inter <= 0:
                continue
            score = inter / max(1, len(media_tokens | k_tokens))
            if score > best_score:
                best_score = score
                best_key = k

        if best_key and best_score >= 0.45:
            return list(by_title.get(best_key) or [])
        return []

    def _is_placeholder_title(raw_title: str | None) -> bool:
        return _title_key(raw_title).startswith("позиция из tg #")


    def _find_existing_supplier_product(supplier_key: str, supplier_name: str | None, title_key: str) -> models.Product | None:
        cache_key = (supplier_key, title_key)
        cached = existing_product_by_supplier_title.get(cache_key)
        if cached is not None:
            return cached
        if not supplier_key or not title_key:
            return None
        rows = (
            db.query(models.Product)
            .filter(models.Product.import_supplier_name == supplier_name)
            .order_by(models.Product.id.desc())
            .limit(300)
            .all()
        )
        for cand in rows:
            cand_title_key = _title_key(_group_title(getattr(cand, "title", "") or getattr(cand, "title", "")) or getattr(cand, "title", ""))
            if cand_title_key == title_key:
                existing_product_by_supplier_title[cache_key] = cand
                return cand
        return None



    def _find_existing_global_product(category_id: int, title_key: str) -> models.Product | None:
        cache_key = (int(category_id), title_key)
        cached = existing_product_by_global_title.get(cache_key)
        if cached is not None:
            return cached
        if not title_key:
            return None
        rows = (
            db.query(models.Product)
            .filter(models.Product.category_id == int(category_id))
            .order_by(models.Product.id.desc())
            .limit(500)
            .all()
        )
        for cand in rows:
            cand_title_key = _title_key(_group_title(getattr(cand, "title", "") or getattr(cand, "title", "")) or getattr(cand, "title", ""))
            if cand_title_key == title_key:
                existing_product_by_global_title[cache_key] = cand
                return cand
        return None
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
        current_ds = float(dropship_price or 0)
        fallback_min_ds = float(min_dropship_price or 0)
        # Price for current row must stay authoritative when present.
        # Use minimal title-level dropship only as fallback for missing/invalid row price.
        base = current_ds if current_ds > 0 else fallback_min_ds

        # Use supplier RRC/RRP only when row dropship is missing; otherwise keep row-based markup flow.
        if base <= 0 and rrc_price is not None:
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
        src_kind = detect_source_kind(src_url)
        supplier_key = _supplier_key(getattr(src, "supplier_name", None))
        if supplier_key and src_kind in {"google_sheet", "moysklad_catalog"}:
            supplier_has_table_source[supplier_key] = True
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
                title = normalize_title_for_supplier(str(it.get("title") or "").strip(), getattr(src, "supplier_name", None))
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

                if supplier_key and src_kind == "telegram_channel":
                    resolved_pool: list[str] = []
                    for u in pool:
                        uu = _resolve_source_image_url(u, src_url)
                        if uu and uu not in resolved_pool:
                            resolved_pool.append(uu)
                    if resolved_pool:
                        fb = supplier_tg_fallback_images.setdefault(supplier_key, [])
                        for uu in resolved_pool:
                            if uu not in fb:
                                fb.append(uu)
                    if title and resolved_pool:
                        tg_bucket = supplier_tg_images_by_title.setdefault(supplier_key, {})
                        for tk in {_title_key(title), _title_media_key(title)}:
                            if not tk:
                                continue
                            slot = tg_bucket.setdefault(tk, [])
                            for uu in resolved_pool:
                                if uu not in slot:
                                    slot.append(uu)
        except Exception as exc:
            src_id = int(src.id)
            source_items_map[src_id] = []
            pre_scan_error_messages[src_id] = _normalize_error_message(exc)
            logger.exception("Supplier pre-scan failed for source_id=%s url=%s", src_id, src_url)

    for src in sources:
        src_url = (src.source_url or "").strip()
        if not src_url:
            continue
        src_kind = detect_source_kind(src_url)
        supplier_key = _supplier_key(getattr(src, "supplier_name", None))
        report = _new_source_report(source_id=int(src.id), source_url=src_url)
        touched_product_ids: set[int] = set()
        try:
            items = source_items_map.get(int(src.id), [])
        except Exception as exc:
            _register_source_error(report, exc)
            source_reports.append(report)
            continue

        pre_scan_error = pre_scan_error_messages.get(int(src.id))
        if pre_scan_error and not items:
            _register_source_error(report, RuntimeError(f"pre-scan failed: {pre_scan_error}"))

        # When supplier has a tabular feed, Telegram source is used only as media donor.
        # Price/stock/size authority remains the table rows.
        if supplier_key and src_kind == "telegram_channel" and supplier_has_table_source.get(supplier_key):
            source_reports.append(report)
            continue

        for it in items:
            # Keep media vars initialized for the whole item scope so any
            # future early references cannot crash with UnboundLocalError.
            image_url: str | None = None
            row_image_urls: list[str] = []
            image_urls: list[str] = []
            try:
                title = normalize_title_for_supplier(str(it.get("title") or "").strip(), getattr(src, "supplier_name", None))
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
                    # keep unresolved placeholders out of catalog; they are only media donors
                    continue

                base_title_key = _title_key(title)
                title_for_group = _group_title(title)
                min_dropship = title_min_dropship.get(base_title_key)
                cat_name = map_category(title)
                category = get_or_create_category(cat_name)
                effective_title = (title_for_group or title).strip()[:500]
                slug_base = (slugify(effective_title) or f"item-{category.id}")[:500]
                slug = slug_base
                p = db.query(models.Product).filter(models.Product.slug == slug).one_or_none()
                if image_urls:
                    image_urls = _rerank_gallery_images(image_urls, supplier_key=supplier_key)
                    image_url = image_urls[0]

                if not p:
                    p = db.query(models.Product).filter(models.Product.title == effective_title, models.Product.category_id == category.id).one_or_none()
                if not p and supplier_key:
                    p = _find_existing_supplier_product(supplier_key, getattr(src, "supplier_name", None), _title_key(effective_title))

                if not p:
                    p = _find_existing_global_product(int(category.id), _title_key(effective_title))

                desc = str(it.get("description") or "").strip()
                if payload.ai_style_description and not desc:
                    if payload.ai_description_enabled and payload.ai_description_provider.lower() == "openrouter":
                        desc = generate_ai_product_description(title, cat_name, it.get("color"))
                    else:
                        desc = generate_youth_description(title, cat_name, it.get("color"))
                # Guard against anomalously low supplier price parse (e.g. 799 for sneakers).
                # For footwear-like titles enforce a minimal wholesale floor before retail pricing.
                if re.search(r"(?i)\b(new\s*balance|nb\s*\d|nike|adidas|jordan|yeezy|air\s*max|vomero|samba|gazelle|campus|9060|574)\b", title):
                    ds_price = max(float(ds_price or 0), 1800.0)
                sale_price = pick_sale_price(title, ds_price, min_dropship_price=min_dropship, rrc_price=(it.get("rrc_price") if isinstance(it, dict) else None))
                row_image_urls = [str(x).strip() for x in (it.get("image_urls") or []) if str(x).strip()]
                image_url = str(it.get("image_url") or "").strip() or None
                if not image_url and row_image_urls:
                    image_url = row_image_urls[0]
                if not image_url and "t.me/" in src_url:
                    try:
                        tg_limit = 20 if supplier_key == "shop_vkus" else 3
                        tg_imgs = extract_image_urls_from_html_page(src_url, limit=tg_limit)
                        image_url = tg_imgs[0] if tg_imgs else None
                        if tg_imgs:
                            row_image_urls = [str(x).strip() for x in tg_imgs if str(x).strip()]
                    except Exception:
                        image_url = None

                image_urls = []
                for u in [image_url, *row_image_urls]:
                    uu = _resolve_source_image_url(u, src_url)
                    if uu and uu not in image_urls:
                        image_urls.append(uu)

                # Prefer Telegram channel photos for suppliers that have paired table+TG sources.
                if supplier_key and src_kind != "telegram_channel":
                    tg_images = _pick_tg_images_for_title(supplier_key, title)
                    if tg_images:
                        merged: list[str] = []
                        for u in [*tg_images, *image_urls]:
                            uu = str(u or "").strip()
                            if uu and uu not in merged:
                                merged.append(uu)
                        image_urls = merged
                        image_url = image_urls[0] if image_urls else image_url

                # expand telegram post links into direct image URLs with safety caps,
                # otherwise large imports can spend minutes on network lookups.
                expanded_image_urls: list[str] = []
                for candidate in image_urls:
                    cu = str(candidate or "").strip()
                    if not cu:
                        continue
                    if "t.me/" in cu or "telegram.me/" in cu:
                        tg_media = telegram_media_cache.get(cu)
                        if tg_media is None:
                            if telegram_media_expand_count >= MAX_TELEGRAM_MEDIA_EXPANSIONS_PER_IMPORT:
                                tg_media = []
                            else:
                                telegram_media_expand_count += 1
                                try:
                                    tg_limit = 20 if supplier_key == "shop_vkus" else 8
                                    tg_media = extract_image_urls_from_html_page(cu, limit=tg_limit)
                                except Exception:
                                    tg_media = []
                                telegram_media_cache[cu] = list(tg_media)
                        if tg_media:
                            for media_u in tg_media:
                                uu = _resolve_source_image_url(media_u, cu)
                                if uu and uu not in expanded_image_urls:
                                    expanded_image_urls.append(uu)
                            # do not keep telegram page URL in final media list
                            continue
                    uu = _resolve_source_image_url(cu, src_url)
                    if uu and uu not in expanded_image_urls:
                        expanded_image_urls.append(uu)

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
                    image_urls = _rerank_gallery_images(image_urls, supplier_key=supplier_key)
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
                        image_urls = _rerank_gallery_images(image_urls, supplier_key=supplier_key)
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

                if image_urls:
                    image_urls = _rerank_gallery_images(image_urls, supplier_key=supplier_key)
                    image_url = image_urls[0]

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
                        import_source_url=src_url,
                        import_source_kind=src_kind,
                        import_supplier_name=getattr(src, "supplier_name", None),
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
                    current_base = float(p.base_price or 0)
                    should_fix_low_price = bool(
                        current_base > 0
                        and sale_price > 0
                        and current_base < 1000
                        and re.search(r"(?i)\b(new\s*balance|nb\s*\d|nike|adidas|jordan|yeezy|air\s*max|vomero|samba|gazelle|campus|9060|574)\b", title)
                    )
                    # keep best offer among suppliers: if newly calculated sale is lower,
                    # update retail price downward as well (while keeping low-price guard).
                    if sale_price > 0 and (current_base <= 0 or should_fix_low_price or sale_price < current_base):
                        p.base_price = Decimal(str(sale_price))
                        changed = True
                    if image_url and (
                        not p.default_image
                        or "t.me/" in str(p.default_image)
                        or "telegram.me/" in str(p.default_image)
                    ):
                        p.default_image = image_url
                        changed = True
                    if not getattr(p, "import_source_url", None):
                        p.import_source_url = src_url
                        changed = True
                    if not getattr(p, "import_source_kind", None):
                        p.import_source_kind = src_kind
                        changed = True
                    if not getattr(p, "import_supplier_name", None) and getattr(src, "supplier_name", None):
                        p.import_supplier_name = getattr(src, "supplier_name", None)
                        changed = True
                    if image_urls:
                        existing_rows = db.query(models.ProductImage).filter(models.ProductImage.product_id == p.id).all()
                        existing_urls = [str(x.url).strip() for x in existing_rows if str(x.url).strip()]
                        should_reset_gallery = (
                            len(existing_urls) <= 1 and len(image_urls) >= 2
                        )
                        if should_reset_gallery:
                            for row in existing_rows:
                                db.delete(row)
                            db.flush()
                            for idx, img_u in enumerate(image_urls[:8]):
                                db.add(models.ProductImage(product_id=p.id, url=img_u, sort=idx))
                            changed = True
                        else:
                            known_urls = set(existing_urls)
                            next_sort = len(existing_urls)
                            for img_u in image_urls[:8]:
                                if img_u in known_urls:
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

                # image-based analysis: same print with different colors -> same product, new color variants.
                # Guard: do not cross-merge different models with coincidentally similar signatures.
                same_print_product = find_product_by_signature(sig)
                if same_print_product and (not p or p.id != same_print_product.id):
                    current_media_key = _title_media_key(title)
                    matched_media_key = _title_media_key(getattr(same_print_product, "title", ""))
                    same_supplier_ctx = (
                        supplier_key
                        and _supplier_key(getattr(same_print_product, "import_supplier_name", None)) == supplier_key
                    )
                    if current_media_key and matched_media_key and current_media_key == matched_media_key and same_supplier_ctx:
                        p = same_print_product
                elif sig and p:
                    signature_product_map[sig] = int(p.id)

                if p:
                    remember_product_candidate(base_title_key, int(p.id), sig)
                    touched_product_ids.add(int(p.id))
                    if supplier_key:
                        existing_product_by_supplier_title[(supplier_key, _title_key(effective_title))] = p
                    existing_product_by_global_title[(int(category.id), _title_key(effective_title))] = p

                # Color policy:
                # - if source has only one color, do not force color variants;
                # - for shop_vkus, allow fallback color inference from item text/gallery only when 2+ strong colors are detected.
                src_color = it.get("color")
                color_tokens = _split_color_tokens(src_color)
                if len(color_tokens) <= 1 and _is_shop_vkus_item_context(supplier_key, src_url, it if isinstance(it, dict) else None):
                    inferred_colors = _extract_shop_vkus_color_tokens(it if isinstance(it, dict) else {}, image_urls=image_urls)
                    if len(inferred_colors) >= 1:
                        color_tokens = inferred_colors
                if len(color_tokens) == 0:
                    color_tokens = [""]

                size_tokens = [str(x).strip()[:16] for x in split_size_tokens(re.sub(r"[,;/]+", " ", str(it.get("size") or ""))) if str(x).strip()[:16]]
                if _is_shop_vkus_item_context(supplier_key, src_url, it if isinstance(it, dict) else None) and size_tokens:
                    numeric_sizes = [s for s in size_tokens if re.fullmatch(r"\d{2,3}(?:[.,]5)?", s)]
                    if numeric_sizes:
                        size_tokens = numeric_sizes
                    elif all(not re.search(r"\d", s) for s in size_tokens):
                        # Avoid taking letter tokens from model names (e.g. "SB") as shoe sizes.
                        size_tokens = []
                if not size_tokens and _is_shop_vkus_item_context(supplier_key, src_url, it if isinstance(it, dict) else None):
                    blob_parts: list[str] = []
                    for key in ("title", "description", "text", "notes"):
                        v = it.get(key) if isinstance(it, dict) else None
                        if isinstance(v, str) and v.strip():
                            blob_parts.append(v)
                    fallback_sizes = split_size_tokens(" ".join(blob_parts))
                    size_tokens = [str(x).strip()[:16] for x in fallback_sizes if str(x).strip()[:16]]
                    if size_tokens:
                        numeric_sizes = [s for s in size_tokens if re.fullmatch(r"\d{2,3}(?:[.,]5)?", s)]
                        if numeric_sizes:
                            size_tokens = numeric_sizes
                        elif all(not re.search(r"\d", s) for s in size_tokens):
                            size_tokens = []

                raw_stock = it.get("stock") if isinstance(it, dict) else None
                has_any_stock_signal = False
                if isinstance(it, dict):
                    has_any_stock_signal = any(bool(str(it.get(k) or "").strip()) for k in ("stock", "stock_text", "availability", "наличие"))
                if _is_shop_vkus_item_context(supplier_key, src_url, it if isinstance(it, dict) else None) and (raw_stock is None or not str(raw_stock).strip()):
                    for k in ("stock_text", "availability", "наличие"):
                        v = it.get(k) if isinstance(it, dict) else None
                        if isinstance(v, str) and v.strip():
                            raw_stock = v
                            break
                raw_stock_str = str(raw_stock).strip() if raw_stock is not None else ""
                has_explicit_stock = bool(raw_stock_str)
                stock_qty_parse_failed = False
                try:
                    stock_qty = int(raw_stock_str) if has_explicit_stock else 0
                except Exception:
                    stock_qty = 0
                    stock_qty_parse_failed = has_explicit_stock
                if stock_qty < 0:
                    stock_qty = 0

                stock_map_raw = (it.get("stock_map") if isinstance(it, dict) else None) or {}
                stock_map: dict[str, int] = {}
                availability_sizes_locked = False
                if isinstance(stock_map_raw, dict):
                    for k, v in stock_map_raw.items():
                        kk = str(k or "").strip()
                        try:
                            vv = int(v)
                        except Exception:
                            continue
                        if kk and vv >= 0:
                            stock_map[kk] = vv

                # Guard: parser may map plain ranges like "41-45" into endpoint-only stock_map (41,45).
                # Such ambiguous ranges must not create in-stock sizes.
                raw_plain_range_only = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\s*[-–—]\s*\d{2,3}(?:[.,]5)?\b", raw_stock_str)) and not bool(re.search(r"[,;/]", raw_stock_str)) and not bool(re.search(r"\b\d{2,3}\s*[:=]\s*\d{1,4}\b|\b\d{2,3}\s*\(\s*\d{1,4}", raw_stock_str))
                if raw_plain_range_only and stock_map:
                    map_keys_norm = {str(k).replace(',', '.').strip() for k in stock_map.keys() if str(k).strip()}
                    range_tokens_norm = {str(x).replace(',', '.').strip() for x in split_size_tokens(raw_stock_str) if str(x).strip()}
                    if map_keys_norm and map_keys_norm.issubset(range_tokens_norm):
                        stock_map = {}

                # Generic per-row availability rule:
                # if row size set is explicit and stock cell lists specific sizes,
                # keep only listed sizes as available (default qty 9999 each).
                if size_tokens:
                    valid_sizes = {str(x).replace(",", ".").strip() for x in size_tokens if str(x).strip()}
                    stock_detail_parts: list[str] = []
                    if isinstance(it, dict):
                        for k in ("stock_text", "availability", "наличие"):
                            v = it.get(k)
                            if isinstance(v, str) and v.strip():
                                stock_detail_parts.append(v.strip())
                    if raw_stock_str:
                        stock_detail_parts.append(raw_stock_str)
                    stock_detail = " ".join(stock_detail_parts).strip()
                    range_only_stock = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\s*[-–—]\s*\d{2,3}(?:[.,]5)?\b", stock_detail)) and not bool(re.search(r"[,;/]", stock_detail)) and not bool(re.search(r"\b\d{2,3}\s*[:=]\s*\d{1,4}\b|\b\d{2,3}\s*\(\s*\d{1,4}", stock_detail))
                    listed_in_stock_raw = [str(m.group(1) or "").replace(",", ".").strip() for m in re.finditer(r"(?<!\d)(\d{2,3}(?:[.,]5)?)(?!\d)", stock_detail)]
                    listed_in_stock_raw = [x for x in listed_in_stock_raw if re.fullmatch(r"\d{2,3}(?:[.,]5)?", x)]
                    listed_in_stock_raw = [x for x in listed_in_stock_raw if 20 <= float(x) <= 60]
                    plain_range_only = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\s*[-–—]\s*\d{2,3}(?:[.,]5)?\b", stock_detail)) and not bool(re.search(r"[,;/]", stock_detail)) and not bool(re.search(r"\b\d{2,3}\s*[:=]\s*\d{1,4}\b|\b\d{2,3}\s*\(\s*\d{1,4}", stock_detail))
                    if plain_range_only:
                        listed_in_stock_raw = []
                    listed_in_stock = [x for x in listed_in_stock_raw if x in valid_sizes] if valid_sizes else list(listed_in_stock_raw)
                    if not listed_in_stock and listed_in_stock_raw and len(valid_sizes) >= 2:
                        # If row size parsing is imperfect, still trust explicit availability sizes.
                        listed_in_stock = list(listed_in_stock_raw)
                    if listed_in_stock and len(valid_sizes) >= 2 and not range_only_stock:
                        stock_map = {sz: int(IMPORT_FALLBACK_STOCK_QTY) for sz in dict.fromkeys(listed_in_stock)}
                        availability_sizes_locked = True
                    # Single explicit size token like "43.5" with matching row size should be treated as in stock.
                    elif (not listed_in_stock and len(valid_sizes) == 1 and stock_qty_parse_failed and re.fullmatch(r"\d{2,3}(?:[.,]5)?", raw_stock_str or "")):
                        token = str(raw_stock_str or "").replace(",", ".").strip()
                        if token in valid_sizes:
                            stock_map = {token: int(IMPORT_FALLBACK_STOCK_QTY)}
                            availability_sizes_locked = True

                if _is_shop_vkus_item_context(supplier_key, src_url, it if isinstance(it, dict) else None):
                    shop_vkus_map = _extract_shop_vkus_stock_map(it if isinstance(it, dict) else {})
                    if shop_vkus_map:
                        merged_map = dict(stock_map)
                        for sk, sv in shop_vkus_map.items():
                            merged_map[str(sk)] = max(int(merged_map.get(str(sk), 0) or 0), int(sv or 0))
                        stock_map = merged_map
                if _is_shop_vkus_item_context(supplier_key, src_url, it if isinstance(it, dict) else None):
                    # In shop_vkus plain size lists in stock cell mean available sizes with default open quantity.
                    # Example: "42 43" / "41,42,44".
                    qty_markers = bool(re.search(r"\b\d{2,3}\s*[:=]\s*\d{1,4}\b|\b\d{2,3}\s*\(\s*\d{1,4}", raw_stock_str))
                    size_raw = str((it.get("size") if isinstance(it, dict) else "") or "").strip()
                    size_range_like = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\s*[-–—]\s*\d{2,3}(?:[.,]5)?\b", size_raw))
                    size_list_like = bool(re.search(r"[,;/\s]", size_raw))

                    # Authoritative rule for size availability rows:
                    # when stock cell explicitly lists sizes from the row size set,
                    # keep only these sizes in stock.
                    valid_sizes = {str(x).replace(",", ".").strip() for x in size_tokens if str(x).strip()}
                    listed_in_stock_raw = [str(m.group(1) or "").replace(",", ".").strip() for m in re.finditer(r"(?<!\d)(\d{2,3}(?:[.,]5)?)(?!\d)", raw_stock_str)]
                    listed_in_stock_raw = [x for x in listed_in_stock_raw if re.fullmatch(r"\d{2,3}(?:[.,]5)?", x)]
                    listed_in_stock_raw = [x for x in listed_in_stock_raw if 20 <= float(x) <= 60]
                    plain_range_only = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\s*[-–—]\s*\d{2,3}(?:[.,]5)?\b", raw_stock_str)) and not bool(re.search(r"[,;/]", raw_stock_str)) and not bool(re.search(r"\b\d{2,3}\s*[:=]\s*\d{1,4}\b|\b\d{2,3}\s*\(\s*\d{1,4}", raw_stock_str))
                    if plain_range_only:
                        listed_in_stock_raw = []
                    listed_in_stock = [x for x in listed_in_stock_raw if x in valid_sizes] if valid_sizes else list(listed_in_stock_raw)
                    if not listed_in_stock and listed_in_stock_raw and len(valid_sizes) >= 2:
                        listed_in_stock = list(listed_in_stock_raw)
                    if listed_in_stock:
                        stock_map = {sz: int(IMPORT_FALLBACK_STOCK_QTY) for sz in dict.fromkeys(listed_in_stock)}
                        availability_sizes_locked = True

                    if stock_map and size_range_like and all(int(v or 0) <= 1 for v in stock_map.values()):
                        range_sizes = {str(x).replace(",", ".").strip() for x in split_size_tokens(size_raw) if str(x).strip()}
                        map_sizes = {str(k).replace(",", ".").strip() for k in stock_map.keys() if str(k).strip()}
                        stock_mentions_specific_sizes = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\b", raw_stock_str))
                        generic_in_stock = bool(raw_stock_str and re.search(r"(?i)\b(в\s*наличии|есть|in\s*stock|available)\b", raw_stock_str))
                        if map_sizes and map_sizes.issubset(range_sizes) and (generic_in_stock or raw_stock_str == ""):
                            # Generic stock text with a size range should not auto-enable all range sizes.
                            stock_map = {}
                    if stock_map and all(int(v or 0) <= 1 for v in stock_map.values()):
                        stock_map = {str(k): int(IMPORT_FALLBACK_STOCK_QTY) for k in stock_map.keys()}
                    elif not stock_map and stock_qty_parse_failed:
                        # Only treat plain separated size lists as "in stock" fallback.
                        # Avoid ranges like "41-45" turning all sizes into available.
                        list_like = bool(re.search(r"[,;/]", raw_stock_str))
                        range_like = bool(re.search(r"\b\d{2,3}(?:[.,]5)?\s*[-–—]\s*\d{2,3}(?:[.,]5)?\b", raw_stock_str))
                        if list_like and not range_like:
                            inferred_sizes = [str(x).strip()[:16] for x in split_size_tokens(re.sub(r"[,;/]+", " ", raw_stock_str)) if str(x).strip()[:16]]
                            if inferred_sizes:
                                stock_map = {sz: int(IMPORT_FALLBACK_STOCK_QTY) for sz in inferred_sizes}

                    # Single numeric stock token in shop_vkus is usually a specific available size (not quantity).
                    if not stock_map and raw_stock_str and re.fullmatch(r"\d{2,3}(?:[.,]5)?", raw_stock_str):
                        token = str(raw_stock_str).replace(",", ".").strip()
                        normalized_sizes = {str(x).replace(",", ".").strip() for x in size_tokens if str(x).strip()}
                        if token in normalized_sizes and (size_range_like or len(normalized_sizes) >= 1):
                            stock_map = {token: int(IMPORT_FALLBACK_STOCK_QTY)}

                    # If supplier says generic "in stock" and row has explicit numeric size list,
                    # apply default stock to those sizes only (do not expand numeric ranges).
                    if not stock_map and raw_stock_str and re.search(r"(?i)\b(в\s*наличии|есть|in\s*stock|available)\b", raw_stock_str):
                        listed_sizes = [str(x).strip()[:16] for x in split_size_tokens(re.sub(r"[,;/]+", " ", str(it.get("size") or ""))) if str(x).strip()[:16]]
                        listed_sizes = [s for s in listed_sizes if re.fullmatch(r"\d{2,3}(?:[.,]5)?", s)]
                        if listed_sizes and size_list_like and not size_range_like:
                            stock_map = {sz: int(IMPORT_FALLBACK_STOCK_QTY) for sz in listed_sizes}

                if not size_tokens and stock_map:
                    size_tokens = sorted(
                        stock_map.keys(),
                        key=lambda x: float(x) if str(x).replace(".", "", 1).isdigit() else str(x),
                    )
                if not size_tokens:
                    size_tokens = [""]

                combinations = max(1, len(size_tokens) * len(color_tokens))
                has_stock_map = bool(stock_map)
                has_explicit_stock_data = bool(has_stock_map or has_explicit_stock)
                base_stock = stock_qty // combinations if stock_qty > 0 and combinations > 1 else stock_qty
                remainder_stock = stock_qty % combinations if stock_qty > 0 and combinations > 1 else 0

                row_color_ids: set[int | None] = set()
                for color_name in color_tokens:
                    color = get_or_create_color(color_name) if color_name else None
                    row_color_ids.add(color.id if color else None)
                    for size_name in size_tokens:
                        size = get_or_create_size(size_name) if size_name else None
                        size_key = str(size_name or "").strip()
                        if has_stock_map:
                            per_variant_stock = int(stock_map.get(size_key, 0) or 0)
                        elif has_explicit_stock:
                            per_variant_stock = int(base_stock)
                            if remainder_stock > 0:
                                per_variant_stock += 1
                                remainder_stock -= 1
                        elif _is_shop_vkus_item_context(supplier_key, src_url, it if isinstance(it, dict) else None) and size_key and not has_any_stock_signal:
                            # shop_vkus default: listed sizes are available unless explicitly out of stock.
                            per_variant_stock = int(IMPORT_FALLBACK_STOCK_QTY)
                        else:
                            # Unknown stock should not become "all sizes in stock".
                            per_variant_stock = 0

                        variant = (
                            db.query(models.ProductVariant)
                            .filter(models.ProductVariant.product_id == p.id)
                            .filter(models.ProductVariant.size_id == (size.id if size else None))
                            .filter(models.ProductVariant.color_id == (color.id if color else None))
                            .one_or_none()
                        )

                        variant_images = image_urls or ([image_url] if image_url else None)
                        if color_tokens and color_name and image_urls:
                            color_key = str(color_name).strip().lower()
                            color_specific: list[str] = []
                            for iu in image_urls:
                                try:
                                    dom = str(dominant_color_name_from_url(iu) or "").strip().lower()
                                except Exception:
                                    dom = ""
                                if dom and (dom == color_key or color_key in dom or dom in color_key):
                                    color_specific.append(iu)
                            if len(color_specific) >= 2:
                                variant_images = color_specific

                        if variant is None:
                            variant = models.ProductVariant(
                                product_id=p.id,
                                size_id=size.id if size else None,
                                color_id=color.id if color else None,
                                price=Decimal(str(sale_price)),
                                stock_quantity=max(0, per_variant_stock),
                                images=variant_images,
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

                            # Stock update policy:
                            # - when stock map is explicit, always trust and overwrite;
                            # - when row has explicit zero stock, propagate zero;
                            # - otherwise keep previous positive stock unless empty.
                            if has_explicit_stock_data:
                                variant.stock_quantity = max(0, int(per_variant_stock))

                            existing_variant_images = [str(x).strip() for x in (variant.images or []) if str(x).strip()]
                            if variant_images:
                                desired_variant_images = [str(x).strip() for x in (variant_images or []) if str(x).strip()]
                                should_replace_variant_images = (
                                    not existing_variant_images
                                    or len(existing_variant_images) < len(desired_variant_images)
                                    or any(("t.me/" in u or "telegram.me/" in u) for u in existing_variant_images)
                                )
                                if should_replace_variant_images:
                                    variant.images = desired_variant_images
                            db.add(variant)

                if has_stock_map:
                    allowed_sizes = {str(k).replace(",", ".").strip() for k in stock_map.keys() if str(k).strip()}
                    if allowed_sizes:
                        row_variants = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == p.id).all()
                        size_cache: dict[int, str] = {}
                        for vv in row_variants:
                            if not availability_sizes_locked and vv.color_id not in row_color_ids:
                                continue
                            sz_name = ""
                            if vv.size_id:
                                sid = int(vv.size_id)
                                if sid not in size_cache:
                                    sz_obj = db.query(models.Size).filter(models.Size.id == sid).one_or_none()
                                    size_cache[sid] = str(getattr(sz_obj, "name", "") or "")
                                sz_name = size_cache.get(sid, "")
                            size_key_norm = str(sz_name).replace(",", ".").strip()
                            if size_key_norm not in allowed_sizes and int(vv.stock_quantity or 0) > 0:
                                vv.stock_quantity = 0
                                db.add(vv)

                report.imported += 1
                # persist each processed item immediately so long imports
                # don't lose all progress on later failures.
                if not payload.dry_run:
                    db.commit()
            except Exception as exc:
                if not payload.dry_run:
                    db.rollback()
                try:
                    ctx_title = str((it or {}).get("title") or "").strip()[:120] if isinstance(it, dict) else ""
                    ctx_image = str((it or {}).get("image_url") or "").strip()[:120] if isinstance(it, dict) else ""
                    ctx = f"item title='{ctx_title}' image='{ctx_image}'"
                except Exception:
                    ctx = None
                logger.exception("supplier import item failed source_id=%s url=%s", src.id, src_url)
                _register_source_error(report, exc, context=ctx)

        if not payload.dry_run and src_kind in {"google_sheet", "moysklad_catalog", "generic_html"} and items:
            stale_q = db.query(models.Product).filter(models.Product.import_source_url == src_url)
            if src_kind:
                stale_q = stale_q.filter(models.Product.import_source_kind == src_kind)
            if supplier_key:
                stale_q = stale_q.filter(models.Product.import_supplier_name == getattr(src, "supplier_name", None))
            if touched_product_ids:
                stale_q = stale_q.filter(~models.Product.id.in_(sorted(touched_product_ids)))
            stale_products = stale_q.all()
            if stale_products:
                for stale in stale_products:
                    for vv in (getattr(stale, "variants", []) or []):
                        vv.stock_quantity = 0
                        db.add(vv)
                db.commit()

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


@router.get("/supplier-intelligence/import-quality-audit", response_model=ImportQualityAuditOut)
def import_quality_audit(
    sample_limit: int = 60,
    _admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    sample_limit = max(1, min(int(sample_limit or 60), 300))
    products = db.query(models.Product).filter(models.Product.visible == True).all()  # noqa: E712

    one_photo = 0
    no_size = 0
    duplicate_title = 0
    no_stock = 0
    samples: list[ImportQualityAuditItem] = []

    title_buckets: dict[tuple[int | None, str], list[models.Product]] = {}
    for p in products:
        key = (getattr(p, "category_id", None), re.sub(r"\s+", " ", str(getattr(p, "title", "") or "").strip().lower()))
        title_buckets.setdefault(key, []).append(p)

    duplicate_ids: set[int] = set()
    for bucket in title_buckets.values():
        if len(bucket) > 1:
            duplicate_title += len(bucket)
            for p in bucket:
                if getattr(p, "id", None):
                    duplicate_ids.add(int(p.id))

    for p in products:
        pid = int(getattr(p, "id", 0) or 0)
        if pid <= 0:
            continue
        imgs = list(getattr(p, "images", []) or [])
        image_count = len(imgs)
        if not image_count and getattr(p, "default_image", None):
            image_count = 1
        if image_count <= 1:
            one_photo += 1
            if len(samples) < sample_limit:
                samples.append(ImportQualityAuditItem(product_id=pid, title=str(getattr(p, "title", "") or ""), category_id=getattr(p, "category_id", None), supplier=getattr(p, "import_supplier_name", None), issue="one_photo"))

        variants = list(getattr(p, "variants", []) or [])
        size_names = [str(getattr(getattr(v, "size", None), "name", "") or "").strip() for v in variants]
        if not any(size_names):
            no_size += 1
            if len(samples) < sample_limit:
                samples.append(ImportQualityAuditItem(product_id=pid, title=str(getattr(p, "title", "") or ""), category_id=getattr(p, "category_id", None), supplier=getattr(p, "import_supplier_name", None), issue="no_size"))

        has_stock = any(int(getattr(v, "stock_quantity", 0) or 0) > 0 for v in variants)
        if not has_stock:
            no_stock += 1
            if len(samples) < sample_limit:
                samples.append(ImportQualityAuditItem(product_id=pid, title=str(getattr(p, "title", "") or ""), category_id=getattr(p, "category_id", None), supplier=getattr(p, "import_supplier_name", None), issue="no_stock"))

        if pid in duplicate_ids and len(samples) < sample_limit:
            samples.append(ImportQualityAuditItem(product_id=pid, title=str(getattr(p, "title", "") or ""), category_id=getattr(p, "category_id", None), supplier=getattr(p, "import_supplier_name", None), issue="duplicate_title"))

    return ImportQualityAuditOut(
        total_visible=len(products),
        one_photo_count=one_photo,
        no_size_count=no_size,
        duplicate_title_count=duplicate_title,
        no_stock_count=no_stock,
        sample_items=samples,
    )


class MarketPriceIn(BaseModel):
    prices: list[float] = Field(default_factory=list, min_length=1, max_length=300)


class MarketPriceOut(BaseModel):
    suggested_price: float | None


@router.post("/supplier-intelligence/estimate-market-price", response_model=MarketPriceOut)
def estimate_price(payload: MarketPriceIn, _admin=Depends(get_current_admin_user)):
    return MarketPriceOut(suggested_price=estimate_market_price(payload.prices))
