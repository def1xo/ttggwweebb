from app.db import models
from app.services.importer_notifications import parse_and_save_post


def test_existing_product_update_by_message_id_updates_title_and_stock(tmp_db):
    db = tmp_db
    message_id = 777

    initial_payload = {
        "message_id": message_id,
        "text": "#tops\nInitial title\nprice: 1000\nstock: 2",
        "image_urls": ["https://example.com/a.jpg"],
    }
    first = parse_and_save_post(db, initial_payload)
    assert first is not None

    first_variant = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == first.id).first()
    assert first_variant is not None
    assert first_variant.stock_quantity == 2

    update_payload = {
        "message_id": message_id,
        "text": "#tops\nUpdated title\nprice: 1500\nstock: 9",
        "image_urls": ["https://example.com/b.jpg"],
    }
    updated = parse_and_save_post(db, update_payload)
    assert updated is not None
    assert updated.id == first.id
    assert updated.title == "Updated title"

    refreshed_variants = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == updated.id).all()
    assert refreshed_variants
    assert all(v.stock_quantity == 9 for v in refreshed_variants)


def test_existing_product_update_prefers_payload_stock_quantity(tmp_db):
    db = tmp_db
    message_id = 778

    payload = {
        "message_id": message_id,
        "text": "#tops\nPayload stock title\nstock: 1",
        "stock_quantity": 6,
        "image_urls": ["https://example.com/c.jpg"],
    }
    prod = parse_and_save_post(db, payload)
    assert prod is not None

    variant = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == prod.id).first()
    assert variant is not None
    assert variant.stock_quantity == 6


def test_import_post_uses_rrc_minus_300_and_default_stock(tmp_db):
    db = tmp_db
    payload = {
        "message_id": 990,
        "text": "#tops\nRRC title\nРРЦ: 5300",
        "image_urls": ["https://example.com/rrc.jpg"],
    }
    prod = parse_and_save_post(db, payload)
    assert prod is not None
    assert float(getattr(prod, "base_price", 0) or 0) == 5000.0

    variant = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == prod.id).first()
    assert variant is not None
    assert int(variant.stock_quantity or 0) == 9999
