from __future__ import annotations

import os
import re
import logging
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv

load_dotenv()

import requests
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.db import models
from app.db.session import SessionLocal
from app.services.supplier_intelligence import (
    split_size_tokens,
    _extract_size_stock_map as _sheet_extract_size_stock_map,
    extract_image_urls_from_html_page,
)
from app.services.color_detection import detect_product_color
from app.services import media_store

logger = logging.getLogger("tg_importer")
logger.setLevel(logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

PRICE_CURRENCY_RE = re.compile(
    r'(\d+(?:[ \u00A0]\d{3})*(?:[.,]\d{1,2})?)\s*(?:₽|руб|rur|rub)?',
    flags=re.IGNORECASE,
)
PRICE_KEYWORDS_RE = re.compile(r'(?:цена|продажа|стоимость)[:\s\-]*([0-9\s,.\u00A0]+)', flags=re.IGNORECASE)
COST_KEYWORDS_RE = re.compile(r'(?:закуп|себест|себестоимость|cost)[:\s\-]*([0-9\s,.\u00A0]+)', flags=re.IGNORECASE)
SIZE_RE = re.compile(r'размер(?:ы)?[:\s]*([^\n#]+)', flags=re.IGNORECASE)
COLOR_RE = re.compile(r'цвет(?:а|ов)?[:\s]*([A-Za-zА-Яа-яЁё0-9,#\s\-]+)', flags=re.IGNORECASE)
HASHTAG_RE = re.compile(r'#([\w\-А-Яа-яёЁ]+)', flags=re.UNICODE)
STOCK_RE = re.compile(r'(?:остаток|в\s*наличии|наличие|stock|склад|qty|кол-?во|количество)[:\s\-]*([0-9]{1,5})', flags=re.IGNORECASE)
RRC_KEYWORDS_RE = re.compile(r'(?:ррц|rrc|мрц|mrc|розниц(?:а|ная)?\s*цена|retail)[:\s\-]*([0-9][0-9\s,.\u00A0]*)', flags=re.IGNORECASE)
URL_RE = re.compile(r'https?://[^\s<>"\']+', flags=re.IGNORECASE)

IMPORT_FALLBACK_STOCK_QTY = 9_999
RRC_DISCOUNT_RUB = Decimal("300")
LOCALIZE_IMPORTED_IMAGES = str(os.getenv("LOCALIZE_IMPORTED_IMAGES", "1")).strip().lower() not in {"0", "false", "no", "off"}
MIN_IMAGE_SIDE_PX = 600
MIN_IMAGE_FILE_SIZE_BYTES = 40 * 1024
MAX_IMAGE_ASPECT_RATIO = 5.0


def _send_telegram_message(chat_id: str, text: str) -> Optional[Dict[str, Any]]:
    if not TELEGRAM_API_URL or not chat_id:
        return None
    url = f"{TELEGRAM_API_URL}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=6)
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code}
    except Exception:
        return None


def _log_notification(db: Session, user_id: Optional[int], message: str, payload: Optional[Dict[str, Any]] = None):
    try:
        nl = models.NotificationLog(user_id=user_id, message=message, payload=payload or {}, sent_at=datetime.utcnow())
        db.add(nl)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def notify_admin_new_order(order_id: int):
    db = SessionLocal()
    try:
        order = db.query(models.Order).get(order_id)
        if not order:
            return {"ok": False, "reason": "order_not_found"}
        admin_chat = os.getenv("ADMIN_CHAT_ID")
        if not admin_chat:
            return {"ok": False, "reason": "no_admin_chat"}
        user = db.query(models.User).get(order.user_id) if getattr(order, "user_id", None) else None
        manager_user = None
        assistant_user = None
        try:
            if getattr(order, "manager_id", None):
                manager_user = db.query(models.User).get(order.manager_id)
        except Exception:
            manager_user = None
        try:
            if getattr(order, "assistant_id", None):
                assistant_user = db.query(models.User).get(order.assistant_id)
        except Exception:
            assistant_user = None
        promo_code = getattr(order, "promo_code", None) or "-"
        total_amount = getattr(order, "total_amount", None) or getattr(order, "total", None) or getattr(order, "base_price", None) or "-"
        txt = (
            f"Новый заказ #{order.id}\n"
            f"Клиент: {getattr(user, 'username', None) or getattr(user, 'full_name', None) or getattr(user, 'telegram_id', None)} (id: {getattr(user, 'id', '-')})\n"
            f"Сумма: {total_amount}\n"
            f"Менеджер: {getattr(manager_user, 'username', '-') if manager_user else '-'}\n"
            f"Подручный: {getattr(assistant_user, 'username', '-') if assistant_user else '-'}\n"
            f"Промокод: {promo_code}\n"
            f"Скрин: {getattr(order, 'payment_screenshot', '-')}\n"
            f"Ссылка: /admin/orders/{order.id}"
        )
        res = _send_telegram_message(admin_chat, txt)
        _log_notification(db, None, txt, {"order_id": order.id})
        return {"ok": True, "tg": res}
    except Exception as exc:
        logger.exception("notify_admin_new_order_task failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


def slugify(text: str) -> str:
    if not text:
        return ""
    txt = text.strip().lower()
    txt = re.sub(r'[^0-9a-zа-яё\- ]', '', txt, flags=re.IGNORECASE)
    txt = re.sub(r'\s+', '-', txt).strip('-')
    return txt[:200]


def _parse_money(raw: Optional[str]) -> Optional[Decimal]:
    if not raw:
        return None
    s = raw.strip().replace('\u00A0', '').replace(' ', '').replace(',', '.')
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _extract_sale_price(text: Optional[str]) -> Optional[Decimal]:
    if not text:
        return None
    m = PRICE_KEYWORDS_RE.search(text)
    if m:
        p = _parse_money(m.group(1))
        if p is not None:
            return p

    best: Optional[Decimal] = None
    for m2 in PRICE_CURRENCY_RE.finditer(text):
        p = _parse_money(m2.group(1))
        if p is None:
            continue
        if best is None or p > best:
            best = p
    return best




def _extract_rrc_price(text: Optional[str]) -> Optional[Decimal]:
    if not text:
        return None
    for m in RRC_KEYWORDS_RE.finditer(text):
        p = _parse_money(m.group(1))
        if p is not None:
            return p
    return None

def _extract_cost_price(text: Optional[str]) -> Optional[Decimal]:
    if not text:
        return None
    m = COST_KEYWORDS_RE.search(text)
    if m:
        return _parse_money(m.group(1))
    return None


def _extract_sizes(text: Optional[str]) -> List[str]:
    if not text:
        return []
    found: List[str] = []
    for m in SIZE_RE.finditer(text):
        chunk = (m.group(1) or "").strip()
        if not chunk:
            continue
        chunk = re.split(r'\b(?:цвет(?:а|ов)?|цена|наличие|остаток|склад|арт(?:икул)?|код)\b', chunk, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,.;:-")
        if not chunk:
            continue

        inline_size_stock_map = _sheet_extract_size_stock_map(chunk)
        if inline_size_stock_map:
            found.extend(list(inline_size_stock_map.keys()))
            continue

        cleaned_chunk = re.sub(r"\((?:\s*\d+\s*(?:шт|pcs|pc)?\s*)\)", "", chunk, flags=re.IGNORECASE)
        tokens = split_size_tokens(cleaned_chunk)
        if tokens:
            found.extend(tokens)
            continue
        parts = re.split(r'[;,/\\\n]', cleaned_chunk)
        for p in parts:
            token = re.sub(r'\s+', ' ', p).strip()
            if token:
                found.append(token)
    out: List[str] = []
    seen = set()
    for s in found:
        key = str(s or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(s))
    return out


def _extract_size_stock_map(text: Optional[str]) -> Dict[str, int]:
    parsed = _sheet_extract_size_stock_map(text)
    if parsed:
        return parsed
    if not text:
        return {}

    # Conservative fallback for patterns like "41(0шт), 42(1шт)".
    # Keep this strict to avoid treating price lines as size-stock rows.
    out: Dict[str, int] = {}
    for m in re.finditer(r"(?<!\d)(\d{2,3}(?:[.,]5)?)\s*\(\s*(\d{1,4})\s*(?:шт|pcs|pc)?\s*\)", text, flags=re.IGNORECASE):
        size = str(m.group(1) or "").replace(",", ".").strip()
        qty_raw = str(m.group(2) or "").strip()
        if not size or not qty_raw:
            continue
        try:
            qty = max(0, int(qty_raw))
        except Exception:
            continue
        out[size] = qty
    return out


def _extract_colors(text: Optional[str]) -> List[str]:
    if not text:
        return []
    m = COLOR_RE.search(text)
    if m:
        parts = re.split(r'[;,/\\\n]', m.group(1))
        return [p.strip() for p in parts if p.strip()]
    tags = HASHTAG_RE.findall(text or "")
    return tags


def _extract_hashtags(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return HASHTAG_RE.findall(text)



def _extract_stock_quantity(text: Optional[str], payload: Optional[Dict[str, Any]] = None) -> Optional[int]:
    # explicit payload field has priority
    if isinstance(payload, dict):
        for key in ("stock_quantity", "stock", "qty", "quantity"):
            if key in payload:
                try:
                    v = int(payload.get(key))
                    return max(0, v)
                except Exception:
                    pass

    if not text:
        return None
    m = STOCK_RE.search(text)
    if m:
        try:
            return max(0, int(m.group(1)))
        except Exception:
            return None
    return None


def _extract_urls_from_text(text: Optional[str]) -> List[str]:
    if not text:
        return []
    out: List[str] = []
    seen = set()
    for m in URL_RE.finditer(text):
        u = str(m.group(0) or "").strip().rstrip(").,;!")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _detect_supplier_from_payload(payload: Dict[str, Any], text: Optional[str] = None) -> Optional[str]:
    raw_candidates: List[str] = []
    for key in ("supplier", "supplier_name", "import_supplier_name"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            raw_candidates.append(v.strip().lower())
    txt = str(text or payload.get("text") or payload.get("caption") or "").lower()
    all_links = _split_image_candidates(payload.get("image_urls")) + _split_image_candidates(payload.get("image")) + _extract_urls_from_text(txt)
    raw_candidates.extend(all_links)
    raw_candidates.append(txt)

    for c in raw_candidates:
        if "shop_vkus" in c or "shop-vkus" in c or "shopvkus" in c or "t.me/shop_vkus" in c:
            return "shop_vkus"
    return None

def _split_image_candidates(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        out: List[str] = []
        for item in raw:
            out.extend(_split_image_candidates(item))
        return out
    if isinstance(raw, dict):
        out: List[str] = []
        for key in ("url", "file_url", "photo_url", "src", "image", "image_url", "thumb"):
            if key in raw:
                out.extend(_split_image_candidates(raw.get(key)))
        return out
    value = str(raw or "").strip()
    if not value:
        return []
    parts = [p.strip() for p in re.split(r"[\n\r\t,;|\s]+", value) if p and p.strip()]
    if len(parts) <= 1:
        return [value]
    return [p for p in parts if re.match(r"(?i)^https?://", p) or p.startswith("/")]


def _looks_like_thumbnail(url: str) -> bool:
    u = str(url or "").lower()
    if not u:
        return False
    if any(x in u for x in ("thumb", "thumbnail", "preview", "_small", "/small/")):
        return True
    return bool(re.search(r"(?:^|[?&])(w|width|h|height|q|quality|size|name)=", u))


def _is_probable_image_url(url: str) -> bool:
    u = str(url or "").lower()
    return bool(re.search(r"\.(?:jpe?g|png|webp|gif|avif)(?:[?#].*)?$", u))


def _strip_gallery_single_param(url: str) -> str:
    try:
        parsed = urlparse(url)
        pairs = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in {"single", "single_image", "img", "photo"}
        ]
        query = urlencode(pairs, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))
    except Exception:
        return url


def _upgrade_image_url_quality(url: str) -> str:
    try:
        parsed = urlparse(url)
        pairs = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in {"w", "width", "h", "height", "q", "quality", "size", "name", "single"}
        ]
        query = urlencode(pairs, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))
    except Exception:
        return url


def _extract_images_from_html(base_url: str, html: str) -> List[str]:
    urls: List[str] = []
    for m in re.finditer(r'(?:src|data-src|href|content)\s*=\s*["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
        cand = (m.group(1) or "").strip()
        if not cand:
            continue
        if cand.startswith("//"):
            cand = f"https:{cand}"
        cand = urljoin(base_url, cand)
        if _is_probable_image_url(cand):
            urls.append(cand)
    for m in re.finditer(r'["\'](https?://[^"\']+\.(?:jpg|jpeg|png|webp|avif|gif)(?:\?[^"\']*)?)["\']', html, flags=re.IGNORECASE):
        urls.append((m.group(1) or "").strip())
    out: List[str] = []
    seen = set()
    for u in urls:
        uq = _upgrade_image_url_quality(u)
        if uq and uq not in seen:
            seen.add(uq)
            out.append(uq)
    return out


def _expand_gallery_url_to_images(url: str) -> List[str]:
    clean_url = _strip_gallery_single_param(url)
    candidates = [clean_url]
    if clean_url != url:
        candidates.append(url)

    # Supplier-specific strategy: shop_vkus pages are often JS-heavy.
    # Reuse robust extractor from supplier_intelligence first.
    if any(x in clean_url.lower() for x in ("shop_vkus", "shop-vkus", "shopvkus")):
        try:
            rich = extract_image_urls_from_html_page(clean_url, timeout_sec=20, limit=20)
            if rich:
                return [_upgrade_image_url_quality(x) for x in rich if str(x or "").strip()]
        except Exception:
            logger.exception("shop_vkus specific image expansion failed: %s", clean_url)

    headers = {"User-Agent": "Mozilla/5.0 (compatible; TGImporter/1.0)"}
    for target in candidates:
        try:
            resp = requests.get(target, timeout=8, headers=headers)
            if int(getattr(resp, "status_code", 0) or 0) >= 400:
                continue
            html = resp.text or ""
            found = _extract_images_from_html(target, html)
            if found:
                return found
        except Exception:
            continue
    return []


def _image_passes_quality_gate(url: str) -> bool:
    u = str(url or "").strip()
    if not u:
        return False

    if u.lower().startswith(("http://", "https://")):
        try:
            head = requests.head(u, timeout=6, allow_redirects=True, headers={"User-Agent": "TGImporter/1.0"})
            clen = int(head.headers.get("Content-Length") or 0)
            if clen and clen < MIN_IMAGE_FILE_SIZE_BYTES:
                return False
        except Exception:
            pass

    try:
        from PIL import Image
        from io import BytesIO

        if u.lower().startswith(("http://", "https://")):
            resp = requests.get(u, timeout=10, stream=True, headers={"User-Agent": "TGImporter/1.0"})
            resp.raise_for_status()
            data = resp.content
            if data and len(data) < MIN_IMAGE_FILE_SIZE_BYTES:
                return False
            img = Image.open(BytesIO(data))
        else:
            local_path = u.lstrip("/") if u.startswith("/") else u
            img = Image.open(local_path)

        w, h = img.size
        if min(w, h) < MIN_IMAGE_SIDE_PX:
            return False
        ratio = max(w, h) / max(1, min(w, h))
        if ratio > MAX_IMAGE_ASPECT_RATIO:
            return False
    except Exception:
        return True

    return True


def _normalize_image_urls(payload: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    urls.extend(_split_image_candidates(payload.get("image_urls")))
    urls.extend(_split_image_candidates(payload.get("photos")))
    if isinstance(payload.get("media"), list):
        for mi in payload["media"]:
            urls.extend(_split_image_candidates(mi))
    urls.extend(_split_image_candidates(payload.get("image")))

    expanded_urls: List[str] = []
    for u in urls:
        cu = str(u or "").strip()
        if not cu:
            continue
        if _is_probable_image_url(cu):
            expanded_urls.append(_upgrade_image_url_quality(cu))
            continue
        gallery_images = _expand_gallery_url_to_images(cu)
        if gallery_images:
            expanded_urls.extend(gallery_images)
        else:
            expanded_urls.append(_upgrade_image_url_quality(cu))

    seen = set()
    out: List[str] = []
    thumbs: List[str] = []
    for u in expanded_urls:
        if not u:
            continue
        if u in seen:
            continue
        seen.add(u)
        if _looks_like_thumbnail(u):
            thumbs.append(u)
        else:
            out.append(u)
    quality = [u for u in out if _image_passes_quality_gate(u)]
    if quality:
        return quality
    thumbs_quality = [u for u in thumbs if _image_passes_quality_gate(u)]
    if thumbs_quality:
        return thumbs_quality
    if out:
        return out
    return thumbs

def _localize_image_urls(urls: List[str], title_hint: Optional[str] = None) -> List[str]:
    out: List[str] = []
    seen = set()
    for idx, u in enumerate(urls or []):
        cand = str(u or "").strip()
        if not cand:
            continue
        localized = cand
        if LOCALIZE_IMPORTED_IMAGES and cand.lower().startswith(("http://", "https://")):
            try:
                localized = media_store.save_remote_image_to_local(
                    cand,
                    folder="products",
                    timeout_sec=20,
                    filename_hint=(title_hint or f"imported-{idx+1}"),
                    referer=cand,
                )
            except Exception:
                logger.exception("Could not localize imported image url: %s", cand)
                localized = cand
        if localized not in seen:
            seen.add(localized)
            out.append(localized)
    return out



def _get_or_create_category(db: Session, tag: str):
    slug = slugify(tag)
    cat = db.query(models.Category).filter(getattr(models.Category, "slug") == slug).one_or_none()
    if cat:
        return cat
    cat = models.Category(name=tag, slug=slug)
    db.add(cat)
    db.flush()
    return cat


def _get_or_create_color(db: Session, name: str):
    name_clean = name.strip()
    col = None
    if hasattr(models.Color, "name"):
        col = db.query(models.Color).filter(models.Color.name == name_clean).one_or_none()
    if not col and hasattr(models.Color, "slug"):
        col = db.query(models.Color).filter(models.Color.slug == slugify(name_clean)).one_or_none()
    if col:
        return col
    kwargs = {}
    if hasattr(models.Color, "name"):
        kwargs["name"] = name_clean
    if hasattr(models.Color, "slug"):
        kwargs["slug"] = slugify(name_clean)
    col = models.Color(**kwargs)
    db.add(col)
    db.flush()
    return col


def _get_or_create_size(db: Session, label: str):
    label_clean = label.strip()
    size = None
    if hasattr(models.Size, "label"):
        size = db.query(models.Size).filter(models.Size.label == label_clean).one_or_none()
    if not size and hasattr(models.Size, "name"):
        size = db.query(models.Size).filter(models.Size.name == label_clean).one_or_none()
    if size:
        return size
    kwargs = {}
    if hasattr(models.Size, "label"):
        kwargs["label"] = label_clean
    else:
        kwargs["name"] = label_clean
    size = models.Size(**kwargs)
    db.add(size)
    db.flush()
    return size


def parse_and_save_post(db: Session, payload: Dict[str, Any], is_draft: bool = False) -> Optional[models.Product]:
    text = (payload.get("text") or payload.get("caption") or "") or ""
    payload_with_text_links = dict(payload or {})
    text_links = _extract_urls_from_text(text)
    if text_links:
        merged = list(payload_with_text_links.get("image_urls") or []) + text_links
        payload_with_text_links["image_urls"] = merged
    images = _normalize_image_urls(payload_with_text_links)
    images = _localize_image_urls(images, title_hint=(payload.get("title") or ""))
    title = None
    for line in (text.splitlines() if text else []):
        ln = line.strip()
        if not ln:
            continue
        if ln.startswith("#"):
            continue
        title = ln
        break
    if not title:
        title = payload.get("title") or f"product-{int(datetime.utcnow().timestamp())}"
    sale_price = _extract_sale_price(text) or Decimal("0.00")
    rrc_price = _extract_rrc_price(text)
    if rrc_price is not None and rrc_price > 0:
        sale_price = max(Decimal("1.00"), rrc_price - RRC_DISCOUNT_RUB)
    cost_price = _extract_cost_price(text)
    sizes = _extract_sizes(text)
    size_stock_map = _extract_size_stock_map(text)
    if size_stock_map and not sizes:
        sizes = sorted(size_stock_map.keys(), key=lambda x: float(x) if str(x).replace(".", "", 1).isdigit() else str(x))
    hashtags = _extract_hashtags(text)
    stock_quantity = _extract_stock_quantity(text, payload)
    supplier_name = _detect_supplier_from_payload(payload_with_text_links, text=text)
    color_detection = detect_product_color(
        images,
        supplier_profile="shop_vkus" if str(supplier_name or "").strip().lower() == "shop_vkus" else None,
    ) if images else {"color": None, "confidence": 0.0, "debug": {"reason": "no_images"}, "per_image": []}
    colors = _extract_colors(text)
    if not colors and color_detection.get("color"):
        colors = [str(color_detection.get("color"))]
    effective_stock_quantity = max(0, int(stock_quantity)) if stock_quantity is not None else IMPORT_FALLBACK_STOCK_QTY
    visible = False if (is_draft or len(hashtags) == 0) else True
    category = None
    if hashtags:
        try:
            category = _get_or_create_category(db, hashtags[0])
        except Exception:
            logger.exception("Failed to get/create category from hashtag")
    channel_message_id = None
    if payload.get("media_group_id"):
        channel_message_id = f"media_group:{str(payload.get('media_group_id')).strip()}"
    elif payload.get("message_id"):
        channel_message_id = str(payload.get("message_id"))
    try:
        existing = None
        if channel_message_id:
            existing = db.query(models.Product).filter(getattr(models.Product, "channel_message_id") == channel_message_id).one_or_none()
        if existing:
            if hasattr(existing, "title"):
                existing.title = title
            elif hasattr(existing, "name"):
                existing.name = title
            if hasattr(existing, "description"):
                existing.description = text[:4000]
            if hasattr(existing, "base_price"):
                existing.base_price = sale_price
            elif hasattr(existing, "price"):
                existing.price = sale_price
            if images and hasattr(existing, "default_image"):
                try:
                    existing.default_image = images[0]
                except Exception:
                    pass
            if hasattr(existing, "updated_at"):
                existing.updated_at = datetime.utcnow()
            if supplier_name and hasattr(existing, "import_supplier_name"):
                existing.import_supplier_name = supplier_name
            if hasattr(existing, "detected_color"):
                existing.detected_color = color_detection.get("color")
            if hasattr(existing, "detected_color_confidence"):
                existing.detected_color_confidence = float(color_detection.get("confidence") or 0.0)
            if hasattr(existing, "detected_color_debug"):
                existing.detected_color_debug = color_detection
            existing.visible = visible
            if category:
                if hasattr(existing, "category"):
                    existing.category = category
                elif hasattr(existing, "category_id"):
                    existing.category_id = category.id
            try:
                existing_urls = {img.url for img in getattr(existing, "images", [])}
            except Exception:
                existing_urls = set()
            for u in images:
                if u not in existing_urls:
                    pi_kwargs = {"product_id": existing.id, "url": u}
                    if hasattr(models.ProductImage, "sort"):
                        pi_kwargs["sort"] = len(existing_urls)
                    if hasattr(models.ProductImage, "created_at"):
                        pi_kwargs["created_at"] = datetime.utcnow()
                    if hasattr(models.ProductImage, "updated_at"):
                        pi_kwargs["updated_at"] = datetime.utcnow()
                    db.add(models.ProductImage(**pi_kwargs))
                    existing_urls.add(u)
            if cost_price is not None:
                for v in getattr(existing, "variants", []):
                    if hasattr(v, "cost_price"):
                        try:
                            v.cost_price = cost_price
                            db.add(v)
                        except Exception:
                            logger.exception("Could not set variant.cost_price")
                    else:
                        if hasattr(models, "ProductCost"):
                            try:
                                pc = models.ProductCost(variant_id=v.id, cost_price=cost_price, created_at=datetime.utcnow())
                                db.add(pc)
                            except Exception:
                                logger.exception("Could not create ProductCost")
            if stock_quantity is not None or size_stock_map:
                for v in getattr(existing, "variants", []):
                    try:
                        if size_stock_map:
                            size_name = str(getattr(getattr(v, "size", None), "name", "") or "").strip()
                            if size_name:
                                v.stock_quantity = max(0, int(size_stock_map.get(size_name, 0)))
                            elif stock_quantity is not None:
                                v.stock_quantity = max(0, int(stock_quantity))
                        elif stock_quantity is not None:
                            v.stock_quantity = max(0, int(stock_quantity))
                        db.add(v)
                    except Exception:
                        logger.exception("Could not set variant.stock_quantity")
            logger.info(
                "import_color_detection product_id=%s color=%s confidence=%.3f votes=%s",
                existing.id,
                color_detection.get("color"),
                float(color_detection.get("confidence") or 0.0),
                (color_detection.get("debug") or {}).get("votes"),
            )
            db.flush()
            db.commit()
            db.refresh(existing)
            return existing
        title_field = getattr(models.Product, "title", None) or getattr(models.Product, "name", None)
        duplicate = db.query(models.Product).filter(title_field == title).one_or_none() if title_field is not None else None
        if duplicate:
            duplicate_title = getattr(duplicate, "title", None) or getattr(duplicate, "name", None)
            logger.info("Deleting duplicate product id=%s title=%s", duplicate.id, duplicate_title)
            try:
                db.delete(duplicate)
                db.flush()
            except Exception:
                db.rollback()
                logger.exception("Failed to delete duplicate product; aborting import")
                return None
        base_slug = slugify(title)
        slug = base_slug or f"product-{int(datetime.utcnow().timestamp())}"
        idx = 1
        while db.query(models.Product).filter(getattr(models.Product, "slug") == slug).count() > 0:
            slug = f"{base_slug}-{idx}"
            idx += 1
        now = datetime.utcnow()
        prod_kwargs: Dict[str, Any] = {
            "title": title,
            "slug": slug,
            "channel_message_id": channel_message_id,
            "visible": visible,
            "created_at": now,
            "updated_at": now,
            "import_supplier_name": supplier_name,
            "import_source_kind": "telegram_channel_post",
        }
        if hasattr(models.Product, "description"):
            prod_kwargs["description"] = text[:4000]
        if hasattr(models.Product, "base_price"):
            prod_kwargs["base_price"] = sale_price
            if hasattr(models.Product, "currency"):
                prod_kwargs["currency"] = "RUB"
        elif hasattr(models.Product, "price"):
            prod_kwargs["price"] = sale_price
        if images and hasattr(models.Product, "default_image"):
            prod_kwargs["default_image"] = images[0]
        if category and hasattr(models.Product, "category_id"):
            prod_kwargs["category_id"] = category.id
        if hasattr(models.Product, "detected_color"):
            prod_kwargs["detected_color"] = color_detection.get("color")
        if hasattr(models.Product, "detected_color_confidence"):
            prod_kwargs["detected_color_confidence"] = float(color_detection.get("confidence") or 0.0)
        if hasattr(models.Product, "detected_color_debug"):
            prod_kwargs["detected_color_debug"] = color_detection
        prod = models.Product(**{k: v for k, v in prod_kwargs.items() if v is not None})
        db.add(prod)
        db.flush()
        if category and not hasattr(models.Product, "category_id") and hasattr(prod, "category"):
            prod.category = category
        for i, u in enumerate(images):
            pi_kwargs = {"product_id": prod.id, "url": u}
            if hasattr(models.ProductImage, "sort"):
                pi_kwargs["sort"] = i
            if hasattr(models.ProductImage, "created_at"):
                pi_kwargs["created_at"] = now
            if hasattr(models.ProductImage, "updated_at"):
                pi_kwargs["updated_at"] = now
            db.add(models.ProductImage(**pi_kwargs))
        try:
            variant_has_cost_column = "cost_price" in getattr(models.ProductVariant, "__table__").columns.keys()
        except Exception:
            variant_has_cost_column = False
        image_groups: Dict[str, List[str]] = {}
        for idx, meta in enumerate(color_detection.get("per_image") or []):
            try:
                c = str(meta.get("color") or "").strip()
                img_idx = int(meta.get("idx"))
                if c and 0 <= img_idx < len(images):
                    image_groups.setdefault(c, []).append(images[img_idx])
            except Exception:
                continue

        if sizes and colors:
            for s in sizes:
                size_obj = _get_or_create_size(db, s)
                per_size_stock = max(0, int(size_stock_map.get(str(s), 0))) if size_stock_map else effective_stock_quantity
                for c in colors:
                    color_obj = _get_or_create_color(db, c)
                    v_kwargs = {
                        "product_id": prod.id,
                        "price": sale_price,
                        "stock_quantity": per_size_stock,
                        "created_at": now,
                        "updated_at": now,
                        "size_id": getattr(size_obj, "id", None),
                        "color_id": getattr(color_obj, "id", None),
                        "images": image_groups.get(c) or None,
                    }
                    if variant_has_cost_column and cost_price is not None:
                        v_kwargs["cost_price"] = cost_price
                    v = models.ProductVariant(**{k: v for k, v in v_kwargs.items() if v is not None})
                    db.add(v)
        elif sizes:
            for s in sizes:
                size_obj = _get_or_create_size(db, s)
                per_size_stock = max(0, int(size_stock_map.get(str(s), 0))) if size_stock_map else effective_stock_quantity
                v_kwargs = {
                    "product_id": prod.id,
                    "price": sale_price,
                    "stock_quantity": per_size_stock,
                    "created_at": now,
                    "updated_at": now,
                    "size_id": getattr(size_obj, "id", None),
                }
                if variant_has_cost_column and cost_price is not None:
                    v_kwargs["cost_price"] = cost_price
                v = models.ProductVariant(**{k: v for k, v in v_kwargs.items() if v is not None})
                db.add(v)
        elif colors:
            for c in colors:
                color_obj = _get_or_create_color(db, c)
                v_kwargs = {
                    "product_id": prod.id,
                    "price": sale_price,
                    "stock_quantity": effective_stock_quantity,
                    "created_at": now,
                    "updated_at": now,
                    "color_id": getattr(color_obj, "id", None),
                    "images": image_groups.get(c) or None,
                }
                if variant_has_cost_column and cost_price is not None:
                    v_kwargs["cost_price"] = cost_price
                v = models.ProductVariant(**{k: v for k, v in v_kwargs.items() if v is not None})
                db.add(v)
        else:
            v_kwargs = {
                "product_id": prod.id,
                "price": sale_price,
                "stock_quantity": effective_stock_quantity,
                "created_at": now,
                "updated_at": now,
            }
            if variant_has_cost_column and cost_price is not None:
                v_kwargs["cost_price"] = cost_price
            v = models.ProductVariant(**{k: v for k, v in v_kwargs.items() if v is not None})
            db.add(v)
        db.flush()
        logger.info(
            "import_color_detection product_id=%s color=%s confidence=%.3f votes=%s",
            prod.id,
            color_detection.get("color"),
            float(color_detection.get("confidence") or 0.0),
            (color_detection.get("debug") or {}).get("votes"),
        )
        if cost_price is not None and not variant_has_cost_column and hasattr(models, "ProductCost"):
            try:
                for variant in db.query(models.ProductVariant).filter(models.ProductVariant.product_id == prod.id).all():
                    pc = models.ProductCost(variant_id=variant.id, cost_price=cost_price, created_at=now)
                    db.add(pc)
            except Exception:
                logger.exception("Failed to create ProductCost records")
        db.commit()
        db.refresh(prod)
        try:
            admin_chat = os.getenv("ADMIN_CHAT_ID")
            if admin_chat and TELEGRAM_API_URL:
                notify_text = f"Новый импорт товара: {getattr(prod, 'name', getattr(prod, 'title', prod.id))} (id={prod.id}). visible={getattr(prod, 'visible', False)}"
                requests.post(
                    f"{TELEGRAM_API_URL}/sendMessage",
                    json={"chat_id": admin_chat, "text": notify_text},
                    timeout=5,
                )
        except Exception:
            logger.exception("Failed to send admin notification")
        return prod
    except SQLAlchemyError:
        logger.exception("Database error during import; rolling back")
        try:
            db.rollback()
        except Exception:
            pass
        return None
    except Exception:
        logger.exception("Unexpected error during import; rolling back")
        try:
            db.rollback()
        except Exception:
            pass
        return None
