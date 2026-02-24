from decimal import Decimal
from io import BytesIO

from fastapi import UploadFile

from app.api.v1 import admin_products as ap
from app.db import models


class _Admin:
    id = 1


def _png_file(name: str = "test.png") -> UploadFile:
    # tiny valid png payload header; content is irrelevant because media save is stubbed in tests.
    data = BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return UploadFile(filename=name, file=data, headers={"content-type": "image/png"})


def test_create_product_minimal_creates_variant(tmp_db):
    res = ap.create_product(
        title="Basic product",
        base_price="1990",
        price=None,
        description=None,
        category_id=None,
        visible=True,
        image=None,
        images=None,
        sizes=None,
        color=None,
        stock_quantity=None,
        cost_price=None,
        payload=None,
        db=tmp_db,
        admin=_Admin(),
    )

    assert res["ok"] is True
    p = tmp_db.query(models.Product).filter(models.Product.title == "Basic product").one()
    assert Decimal(p.base_price) == Decimal("1990")
    variants = tmp_db.query(models.ProductVariant).filter(models.ProductVariant.product_id == p.id).all()
    assert len(variants) == 1
    assert variants[0].color_id is None


def test_create_product_detects_color_from_image_when_missing_color(tmp_db, monkeypatch, tmp_path):
    # Keep media save deterministic so create_product can run without touching real uploads.
    green_path = tmp_path / "green.png"
    green_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 32)

    monkeypatch.setattr(ap.media_store, "save_upload_file_to_local", lambda *_a, **_k: str(green_path))
    monkeypatch.setattr(
        ap,
        "detect_product_colors_from_photos",
        lambda *_a, **_k: {"color": "green", "confidence": 0.92, "debug": {"votes": {"green": 1}}},
    )

    res = ap.create_product(
        title="Detected color",
        base_price="2500",
        price=None,
        description=None,
        category_id=None,
        visible=True,
        image=_png_file(),
        images=None,
        sizes=None,
        color=None,
        stock_quantity=None,
        cost_price=None,
        payload=None,
        db=tmp_db,
        admin=_Admin(),
    )

    assert res["ok"] is True
    p = tmp_db.query(models.Product).filter(models.Product.title == "Detected color").one()
    assert p.detected_color == "green"
    assert float(p.detected_color_confidence or 0) > 0.5

    variants = tmp_db.query(models.ProductVariant).filter(models.ProductVariant.product_id == p.id).all()
    assert len(variants) == 1
    color = tmp_db.query(models.Color).get(variants[0].color_id)
    assert color is not None
    assert color.name == "green"
