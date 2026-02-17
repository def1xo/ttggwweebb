import os
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

import requests
from celery import shared_task
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, joinedload

from app.db import models

logger = logging.getLogger(__name__)
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URI")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set for Celery tasks")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or None
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def _send_telegram_message(chat_id: str, text: str, parse_mode: str = "HTML") -> Dict[str, Any]:
    if not TELEGRAM_API_URL:
        logger.warning("BOT_TOKEN not configured; skipping telegram message")
        return {}
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    try:
        r = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=10)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code}
    except Exception as exc:
        logger.exception("Failed to send telegram message: %s", exc)
        return {"error": str(exc)}


def _log_notification(db, user_id: Optional[int], message: str, payload: Optional[dict] = None) -> None:
    try:
        if hasattr(models, "NotificationLog"):
            nl = models.NotificationLog(user_id=user_id, message=message, payload=payload or {}, sent_at=datetime.utcnow())
            db.add(nl)
            db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception("Failed to persist notification log")


@shared_task(bind=True, name="tasks.send_telegram_and_log")
def send_telegram_and_log(self, chat_id: str, message: str, user_id: Optional[int] = None, payload: Optional[dict] = None):
    db = SessionLocal()
    try:
        res = _send_telegram_message(chat_id, message)
        _log_notification(db, user_id, message, payload)
        return {"ok": True, "telegram": res}
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=30, max_retries=3)
    finally:
        db.close()


@shared_task(name="tasks.notify_admin_new_product")
def notify_admin_new_product_task(product_id: int):
    db = SessionLocal()
    try:
        product = db.query(models.Product).get(product_id)
        if not product:
            return {"ok": False, "reason": "product_not_found"}
        admin_chat = os.getenv("ADMIN_CHAT_ID")
        if not admin_chat:
            return {"ok": False, "reason": "no_admin_chat"}
        category = getattr(product, "category", None)
        txt = (
            f"Новый импорт товара:\n<b>{getattr(product, 'name', getattr(product, 'title', product.id))}</b>\n"
            f"Цена: {getattr(product, 'base_price', getattr(product, 'price', '—'))} {getattr(product, 'currency', '')}\n"
            f"Категория: {getattr(category, 'name', '-')}\n"
            f"Ссылка: /admin/products/{product.id}"
        )
        res = _send_telegram_message(admin_chat, txt)
        _log_notification(db, None, txt, {"product_id": product.id})
        return {"ok": True, "tg": res}
    except Exception as exc:
        logger.exception("notify_admin_new_product_task failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


@shared_task(name="tasks.notify_admin_new_order")
def notify_admin_new_order_task(order_id: int):
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
        total_amount = getattr(order, "total_amount", None) or getattr(order, "total", None) or "-"
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


@shared_task(name="tasks.notify_admin_payment_proof")
def notify_admin_payment_proof_task(order_id: int):
    """Notify admin chat that a user uploaded a payment proof for an order.

    Требование: уведомлять админа ТОЛЬКО после того, как пользователь оплатил и загрузил пруф.
    Сообщение: клиент, контакты, доставка, состав заказа, ссылка на файл.
    """
    db = SessionLocal()
    try:
        order = (
            db.query(models.Order)
            .options(
                joinedload(models.Order.items)
                .joinedload(models.OrderItem.variant)
                .joinedload(models.ProductVariant.product)
            )
            .get(order_id)
        )
        if not order:
            return {"ok": False, "reason": "order_not_found"}

        admin_chat = os.getenv("ADMIN_CHAT_ID")
        if not admin_chat:
            return {"ok": False, "reason": "no_admin_chat"}

        user = db.query(models.User).get(order.user_id) if getattr(order, "user_id", None) else None

        proof = getattr(order, "payment_screenshot", None) or "-"
        uploaded_at = getattr(order, "payment_uploaded_at", None) or getattr(order, "updated_at", None) or "-"

        fio = getattr(order, "fio", None) or "-"
        phone = getattr(order, "phone", None) or "-"
        delivery_type = getattr(order, "delivery_type", None) or "-"
        delivery_address = getattr(order, "delivery_address", None) or "-"
        note = (getattr(order, "note", None) or "").strip()
        promo_code = getattr(order, "promo_code", None) or "-"
        total_amount = getattr(order, "total_amount", None) or getattr(order, "total", None) or "-"

        item_lines = []
        for it in (getattr(order, "items", None) or []):
            v = getattr(it, "variant", None)
            p = getattr(v, "product", None) if v else None
            title = getattr(p, "title", None) or getattr(p, "name", None) or f"variant #{getattr(it, 'variant_id', '-')}"
            size = getattr(v, "size", None) if v else None
            color = getattr(v, "color", None) if v else None
            attrs = " • ".join([x for x in [f"размер {size}" if size else None, f"цвет {color}" if color else None] if x])
            qty = int(getattr(it, "quantity", 0) or 0)
            price = getattr(it, "price", None) or (getattr(v, "price", None) if v else None) or "-"
            if attrs:
                item_lines.append(f"- {title} ({attrs}) x{qty} | {price}")
            else:
                item_lines.append(f"- {title} x{qty} | {price}")

        items_block = "\n".join(item_lines) if item_lines else "- (позиции не загрузились)"

        who = getattr(user, "username", None) or getattr(user, "full_name", None) or getattr(user, "telegram_id", None) or "-"
        who_id = getattr(user, "id", "-") if user else "-"

        parts = [
            f"✅ Поступил чек по заказу #{order.id}",
            f"Клиент: {who} (user_id: {who_id})",
            f"ФИО: {fio}",
            f"Телефон: {phone}",
            f"Доставка: {delivery_type}",
            f"Адрес/ПВЗ: {delivery_address}",
            f"Сумма: {total_amount}",
            f"Промо: {promo_code}",
            "",
            "🧾 Состав заказа:",
            items_block,
            "",
            f"📎 Файл: {proof}",
            f"🕒 Время: {uploaded_at}",
            "",
            f"➡️ Админка: /admin (Заказы → #{order.id})",
        ]
        if note:
            parts.extend(["", f"📝 Комментарий: {note}"])

        txt = "\n".join(parts)
        res = _send_telegram_message(admin_chat, txt)
        _log_notification(db, None, txt, {"order_id": order.id, "payment_proof": proof})
        return {"ok": True, "tg": res}
    except Exception as exc:
        logger.exception("notify_admin_payment_proof_task failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()

@shared_task(name="tasks.notify_admin_withdraw_request")
def notify_admin_withdraw_request_task(withdraw_id: int):
    db = SessionLocal()
    try:
        wr = db.query(models.WithdrawRequest).get(withdraw_id)
        if not wr:
            return {"ok": False, "reason": "withdraw_not_found"}
        admin_chat = os.getenv("ADMIN_CHAT_ID")
        if not admin_chat:
            return {"ok": False, "reason": "no_admin_chat"}
        requester = db.query(models.User).get(getattr(wr, "requester_user_id", None))
        txt = (
            f"Заявка на вывод от {getattr(requester, 'username', None) or getattr(requester, 'full_name', None) or getattr(requester, 'telegram_id', None)}\n"
            f"Сумма: {getattr(wr, 'amount', '-')}\n"
            f"Реквизиты: {getattr(wr, 'target_details', '-')}\n"
            f"Ссылка: /admin/withdraws/{wr.id}"
        )
        res = _send_telegram_message(admin_chat, txt)
        _log_notification(db, None, txt, {"withdraw_id": wr.id})
        return {"ok": True, "tg": res}
    except Exception as exc:
        logger.exception("notify_admin_withdraw_request_task failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


@shared_task(name="tasks.notify_manager_rate_change")
def notify_manager_rate_change_task(manager_id: int):
    db = SessionLocal()
    try:
        mgr_user = None
        try:
            mgr = db.query(models.Manager).get(manager_id)
        except Exception:
            mgr = None
        if mgr and getattr(mgr, "user", None):
            mgr_user = getattr(mgr, "user")
        if not mgr_user:
            mgr_user = db.query(models.User).get(manager_id)
        if not mgr_user or not getattr(mgr_user, "telegram_id", None):
            return {"ok": False, "reason": "manager_not_found_or_no_telegram"}
        first_percent = "?"
        ongoing_percent = "?"
        try:
            if mgr and getattr(mgr, "first_n_rate", None) is not None:
                first_percent = str((Decimal(mgr.first_n_rate) * 100).normalize())
            elif hasattr(mgr_user, "first_n_rate") and getattr(mgr_user, "first_n_rate", None) is not None:
                first_percent = str((Decimal(mgr_user.first_n_rate) * 100).normalize())
        except Exception:
            first_percent = "?"
        try:
            if mgr and getattr(mgr, "ongoing_rate", None) is not None:
                ongoing_percent = str((Decimal(mgr.ongoing_rate) * 100).normalize())
            elif hasattr(mgr_user, "ongoing_rate") and getattr(mgr_user, "ongoing_rate", None) is not None:
                ongoing_percent = str((Decimal(mgr_user.ongoing_rate) * 100).normalize())
        except Exception:
            ongoing_percent = "?"
        txt = (
            f"Поздравляем, {getattr(mgr_user, 'username', None) or getattr(mgr_user, 'full_name', None) or getattr(mgr_user, 'telegram_id', None)}!\n"
            f"Вам изменили процент: первые {getattr(mgr, 'first_n_count', getattr(mgr_user, 'first_n_count', '?'))} заказов — {first_percent}%,\n"
            f"далее — {ongoing_percent}%.\nПроверьте панель менеджера."
        )
        res = _send_telegram_message(str(getattr(mgr_user, "telegram_id")), txt)
        _log_notification(db, getattr(mgr_user, "id", None), txt, {"manager_id": manager_id})
        return {"ok": True, "tg": res}
    except Exception as exc:
        logger.exception("notify_manager_rate_change_task failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


@shared_task(name="tasks.import_post")
def import_post_task(payload: dict):
    db = SessionLocal()
    try:
        from app.services import importer_notifications
        prod = importer_notifications.parse_and_save_post(db, payload, is_draft=False)
        return {"ok": True, "product_id": getattr(prod, "id", None)}
    except Exception as exc:
        logger.exception("import_post_task failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


@shared_task(name="tasks.supplier_auto_import_24h")
def supplier_auto_import_24h_task():
    db = SessionLocal()
    try:
        from app.api.v1.admin_supplier_intelligence import ImportProductsIn, import_products_from_sources

        source_ids = [
            int(x.id)
            for x in db.query(models.SupplierSource)
            .filter(models.SupplierSource.active == True)  # noqa: E712
            .all()
            if getattr(x, "id", None)
        ]
        if not source_ids:
            return {"ok": True, "source_count": 0, "message": "no active supplier sources"}

        payload = ImportProductsIn(
            source_ids=source_ids,
            dry_run=False,
            publish_visible=True,
            ai_style_description=True,
            ai_description_enabled=True,
            use_avito_pricing=True,
            avito_max_pages=1,
            max_items_per_source=40,
        )
        res = import_products_from_sources(payload=payload, _admin=True, db=db)
        return {
            "ok": True,
            "source_count": len(source_ids),
            "created_products": int(getattr(res, "created_products", 0) or 0),
            "updated_products": int(getattr(res, "updated_products", 0) or 0),
        }
    except Exception as exc:
        logger.exception("supplier_auto_import_24h_task failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()
