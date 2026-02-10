# backend/app/api/v1/checkout.py
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi import status
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_current_user
from app.db import models
from app.services.media_store import upload_uploadfile_to_s3
from app.services.importer_notifications import notify_admin_new_order

router = APIRouter(prefix='/api', tags=['checkout'])

def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

@router.post('/orders')
async def create_order(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Create order. Supports both:
      - JSON body: { items: [...], fio, delivery_type, delivery_address, promo_code?, payment_screenshot_key? }
      - multipart/form-data: fields 'items_json' (stringified list), fio, delivery_type, delivery_address, promo_code (optional)
        and file field 'payment_screenshot' (UploadFile)
    """
    # Determine content type
    content_type = request.headers.get('content-type', '')
    # parse inputs depending on content type
    if 'multipart/form-data' in content_type:
        form = await request.form()
        items_json = form.get('items_json')
        if not items_json:
            raise HTTPException(status_code=400, detail='items_json required')
        try:
            import json
            items = json.loads(items_json)
        except Exception:
            raise HTTPException(status_code=400, detail='Invalid items_json')
        fio = form.get('fio')
        delivery_type = form.get('delivery_type')
        delivery_address = form.get('delivery_address')
        promo_code = form.get('promo_code')
        payment_screenshot_file = form.get('payment_screenshot')  # may be UploadFile
        payment_screenshot_key = None
        if payment_screenshot_file and hasattr(payment_screenshot_file, 'filename'):
            # Upload to S3 (synchronous) - media_store handles S3
            try:
                url = upload_uploadfile_to_s3(payment_screenshot_file, prefix='payments')
                payment_screenshot_key = url  # store url as screenshot; or store key if you prefer
            except Exception as exc:
                raise HTTPException(status_code=500, detail='Failed to upload screenshot')
    else:
        # expect JSON payload
        payload = await request.json()
        items = payload.get('items')
        fio = payload.get('fio')
        delivery_type = payload.get('delivery_type')
        delivery_address = payload.get('delivery_address')
        promo_code = payload.get('promo_code')
        payment_screenshot_key = payload.get('payment_screenshot_key')  # key from presign flow (recommended)
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail='Invalid items payload')

    if not items or len(items) == 0:
        raise HTTPException(status_code=400, detail='Items required')
    if not fio:
        raise HTTPException(status_code=400, detail='FIO required')

    # compute total
    total = Decimal('0.00')
    order_items = []
    for it in items:
        try:
            variant_id = int(it.get('variant_id'))
            qty = int(it.get('quantity', 1))
        except Exception:
            raise HTTPException(status_code=400, detail='Invalid item payload')
        variant = db.query(models.ProductVariant).get(variant_id)
        if not variant:
            raise HTTPException(status_code=404, detail=f'Variant {variant_id} not found')
        unit_price = Decimal(variant.price) if variant.price is not None else Decimal(variant.product.base_price)
        line = unit_price * qty
        total += line
        order_items.append({'variant': variant, 'quantity': qty, 'price': unit_price})

    # apply promo
    applied_promo = None
    discount_amount = Decimal('0.00')
    if promo_code:
        promo = db.query(models.PromoCode).filter(models.PromoCode.code == promo_code).one_or_none()
        if not promo:
            raise HTTPException(status_code=400, detail='Promo code not found')
        if promo.type == 'admin':
            discount_amount = _quantize_money(total * Decimal(promo.discount_percent))
            applied_promo = promo
            db.add(models.PromoUsage(promo_code_id=promo.id, user_id=current_user.id))
        else:
            # manager/assistant promo binding logic (as earlier)
            binding = db.query(models.UserManagerBinding).filter(models.UserManagerBinding.user_id == current_user.id).one_or_none()
            owner_user_id = None
            owner_type = None
            if promo.owner_manager_id:
                owner_user_id = db.query(models.Manager).get(promo.owner_manager_id).user_id
                owner_type = 'manager'
            elif promo.owner_assistant_id:
                owner = db.query(models.Assistant).get(promo.owner_assistant_id)
                owner_user_id = owner.user_id
                owner_type = 'assistant'

            if binding is None:
                umb = models.UserManagerBinding(user_id=current_user.id, owner_user_id=owner_user_id, owner_type=owner_type, via_promo_code_id=promo.id, bound_at=datetime.utcnow())
                db.add(umb)
                db.flush()
                current_user.bound_owner_id = owner_user_id
                current_user.bound_owner_type = owner_type
                current_user.bound_via_promo_id = promo.id
                current_user.bound_at = umb.bound_at
            else:
                if binding.owner_user_id != owner_user_id:
                    raise HTTPException(status_code=400, detail='You are already bound to another manager/assistant')
            prior_usage = db.query(models.PromoUsage).filter(models.PromoUsage.promo_code_id == promo.id, models.PromoUsage.user_id == current_user.id).count()
            if prior_usage == 0:
                discount_amount = _quantize_money(total * Decimal(promo.discount_percent))
            applied_promo = promo
            db.add(models.PromoUsage(promo_code_id=promo.id, user_id=current_user.id))

    total_after_discount = _quantize_money(total - discount_amount)

    # create Order
    order = models.Order(
        user_id=current_user.id,
        status='awaiting_payment',
        total_amount=total_after_discount,
        delivery_price=Decimal('0.00'),
        delivery_type=delivery_type,
        delivery_address=delivery_address,
        fio=fio,
        promo_code_id=applied_promo.id if applied_promo else None,
        payment_screenshot=payment_screenshot_key
    )
    db.add(order)
    db.flush()

    # order items + adjust stock
    for oi in order_items:
        v = oi['variant']
        qty = oi['quantity']
        price = oi['price']
        order_item = models.OrderItem(order_id=order.id, variant_id=v.id, quantity=qty, price=price)
        db.add(order_item)
        # decrement stock if tracked
        try:
            if v.stock_quantity is not None:
                v.stock_quantity = max(0, v.stock_quantity - qty)
        except Exception:
            pass

    db.flush()
    db.commit()

    # notify admin (async or sync)
    try:
        notify_admin_new_order(db, order)
    except Exception:
        pass

    return {'status': 'ok', 'order_id': order.id}

