from __future__ import annotations

import os
import re
import logging
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
from app.services.supplier_intelligence import split_size_tokens, _extract_size_stock_map as _sheet_extract_size_stock_map

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

IMPORT_FALLBACK_STOCK_QTY = 1
RRC_DISCOUNT_RUB = Decimal("300")


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
        tokens = split_size_tokens(chunk)
        if tokens:
            found.extend(tokens)
            continue
        parts = re.split(r'[;,/\\\n]', chunk)
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
    return _sheet_extract_size_stock_map(text)


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

def _normalize_image_urls(payload: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    if isinstance(payload.get("image_urls"), list):
        urls.extend([u for u in payload["image_urls"] if isinstance(u, str)])
    if isinstance(payload.get("photos"), list):
        urls.extend([u for u in payload["photos"] if isinstance(u, str)])
    if isinstance(payload.get("media"), list):
        for mi in payload["media"]:
            if isinstance(mi, dict):
                for key in ("url", "file_url", "photo_url", "thumb", "src"):
                    v = mi.get(key)
                    if isinstance(v, str) and v:
                        urls.append(v)
            elif isinstance(mi, str):
                urls.append(mi)
    if isinstance(payload.get("image"), str):
        urls.append(payload["image"])
    seen = set()
    out: List[str] = []
    for u in urls:
        if not u:
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
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
    images = _normalize_image_urls(payload)
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
    colors = _extract_colors(text)
    hashtags = _extract_hashtags(text)
    stock_quantity = _extract_stock_quantity(text, payload)
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
        if sizes and colors:
            for s in sizes:
                size_obj = _get_or_create_size(db, s)
                per_size_stock = max(0, int(size_stock_map.get(str(s), effective_stock_quantity))) if size_stock_map else effective_stock_quantity
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
                    }
                    if variant_has_cost_column and cost_price is not None:
                        v_kwargs["cost_price"] = cost_price
                    v = models.ProductVariant(**{k: v for k, v in v_kwargs.items() if v is not None})
                    db.add(v)
        elif sizes:
            for s in sizes:
                size_obj = _get_or_create_size(db, s)
                per_size_stock = max(0, int(size_stock_map.get(str(s), effective_stock_quantity))) if size_stock_map else effective_stock_quantity
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
