from app.services.importer_notifications import parse_and_save_post
from app.db import models

def test_import_with_hashtags_creates_visible_product(tmp_db):  # tmp_db is fixture to provide DB session
    db = tmp_db
    payload = {
        "message_id": 1001,
        "text": "#РєРѕС„С‚С‹\nBrandX\nР¦РµРЅР°: 1999в‚Ѕ\nР Р°Р·РјРµСЂС‹: S/M/L\nР¦РІРµС‚: black, white",
        "image_urls": ["https://example.com/black.jpg", "https://example.com/white.jpg"]
    }
    prod = parse_and_save_post(db, payload)
    assert prod is not None
    assert prod.visible is True or getattr(prod, 'visible', True) == True

def test_import_without_hashtags_creates_hidden_product(tmp_db):
    db = tmp_db
    payload = {
        "message_id": 1002,
        "text": "BrandY\nР¦РµРЅР°: 2999в‚Ѕ\nР Р°Р·РјРµСЂС‹: M/L",
        "image_urls": ["https://example.com/img.jpg"]
    }
    prod = parse_and_save_post(db, payload)
    assert prod is not None
    assert prod.visible is False or getattr(prod, 'visible', False) == False


def test_duplicate_name_archives_old_and_creates_new(tmp_db):
    db = tmp_db
    payload1 = {
        "message_id": 1003,
        "text": "#РєРѕС„С‚С‹\nBrandZ\nР¦РµРЅР°: 1500в‚Ѕ",
        "image_urls": ["https://example.com/1.jpg"]
    }
    p1 = parse_and_save_post(db, payload1)
    assert p1 is not None

    payload2 = {
        "message_id": 1004,
        "text": "#РєРѕС„С‚С‹\nBrandZ\nР¦РµРЅР°: 1600в‚Ѕ",
        "image_urls": ["https://example.com/2.jpg"]
    }
    p2 = parse_and_save_post(db, payload2)
    assert p2 is not None

    # Duplicate flow should leave a single current product for this title/message.
    current = db.query(models.Product).filter(models.Product.channel_message_id == str(payload2["message_id"])).one_or_none()
    assert current is not None
    assert getattr(current, "title", "") == "BrandZ"

    count = db.query(models.Product).filter(models.Product.title == "BrandZ").count()
    assert count == 1

def test_import_parses_size_range_and_size_stock_map(tmp_db):
    db = tmp_db
    payload = {
        "message_id": 2001,
        "text": "#Обувь\nNike SB Dunk\nЦена: 2999\nРазмеры: 41-43\nНаличие: 41(0шт) 42(2шт) 43(1шт)",
        "image_urls": ["https://example.com/a.jpg"],
    }
    prod = parse_and_save_post(db, payload)
    assert prod is not None
    variants = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == prod.id).all()
    stocks = {
        (v.size.name if getattr(v, "size", None) else ""): int(v.stock_quantity or 0)
        for v in variants
    }
    assert stocks.get("41") == 0
    assert stocks.get("42") == 2
    assert stocks.get("43") == 1


def test_media_group_payload_updates_single_product_and_merges_images(tmp_db):
    db = tmp_db
    payload1 = {
        "media_group_id": "grp-123",
        "message_id": 3101,
        "text": "#Обувь\nNike SB Dunk\nЦена: 2999\nРазмеры: 42",
        "image_urls": ["https://example.com/1.jpg"],
    }
    payload2 = {
        "media_group_id": "grp-123",
        "message_id": 3102,
        "text": "",
        "image_urls": ["https://example.com/2.jpg", "https://example.com/3.jpg"],
    }
    p1 = parse_and_save_post(db, payload1)
    assert p1 is not None
    p2 = parse_and_save_post(db, payload2)
    assert p2 is not None
    assert p1.id == p2.id

    db.refresh(p2)
    assert p2.channel_message_id == "media_group:grp-123"
    image_urls = [im.url for im in sorted((p2.images or []), key=lambda x: (getattr(x, "sort", 0), x.id))]
    assert image_urls == [
        "https://example.com/1.jpg",
        "https://example.com/2.jpg",
        "https://example.com/3.jpg",
    ]
