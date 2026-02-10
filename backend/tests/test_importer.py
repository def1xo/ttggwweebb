import pytest
from app.services.importer_notifications import parse_and_save_post
from app.db.session import SessionLocal
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
    # second post same name
    payload2 = {
        "message_id": 1004,
        "text": "#РєРѕС„С‚С‹\nBrandZ\nР¦РµРЅР°: 1600в‚Ѕ",
        "image_urls": ["https://example.com/2.jpg"]
    }
    p2 = parse_and_save_post(db, payload2)
    assert p2 is not None
    # original should be archived/hidden
    old = db.query(models.Product).filter(models.Product.id == p1.id).one_or_none()
    assert old is not None
    assert (getattr(old, 'visible', False) == False) or (getattr(old, 'archived_at', None) is not None)

