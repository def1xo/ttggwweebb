from app.db import models
from app.services import importer_notifications as importer
from app.services.importer_notifications import parse_and_save_post, _normalize_image_urls
from app.api.v1.products import list_products, get_product


class _Resp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


def test_normalize_image_urls_expands_gallery_link_and_removes_single_param(monkeypatch):
    calls = []

    def fake_get(url, timeout=0, headers=None):
        calls.append(url)
        if "single=true" in url:
            return _Resp('<html><img src="https://cdn.example.com/one.jpg?width=320&quality=20"></html>')
        return _Resp(
            '<html>'
            '<img src="https://cdn.example.com/p1.jpg?width=320&quality=20">'
            '<img src="https://cdn.example.com/p2.jpg?single=1&w=200">'
            '</html>'
        )

    monkeypatch.setattr(importer.requests, "get", fake_get)

    payload = {"image_urls": ["https://shop-vkus.example/item/123?single=true"]}
    urls = _normalize_image_urls(payload)

    assert urls == [
        "https://cdn.example.com/p1.jpg",
        "https://cdn.example.com/p2.jpg",
    ]
    assert calls[0] == "https://shop-vkus.example/item/123"


def test_product_api_sizes_respect_format_42_1sht(tmp_db):
    db = tmp_db
    prod = parse_and_save_post(
        db,
        {
            "message_id": 501,
            "text": "#sneakers\nРазмеры: 41(0шт), 42(1шт), 43(0шт)",
            "image_urls": ["https://example.com/full.jpg"],
        },
    )
    assert prod is not None

    listing = list_products(category_id=None, q=None, page=1, per_page=50, db=db)
    item = next(x for x in listing["items"] if x["id"] == prod.id)
    assert item["sizes"] == ["42"]

    details = get_product(product_id=prod.id, db=db)
    assert details["sizes"] == ["42"]

    variants = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == prod.id).all()
    assert {v.size.name: v.stock_quantity for v in variants} == {"41": 0, "42": 1, "43": 0}


def test_normalize_image_urls_splits_and_prefers_non_thumbnail_urls():
    payload = {
        "image_urls": [
            "https://cdn.example.com/a.jpg, https://cdn.example.com/b.jpg",
            "https://cdn.example.com/only-thumb.jpg?width=320&quality=30",
        ],
        "media": [
            {"thumb": "https://cdn.example.com/thumb.jpg?width=200"},
            {"url": "https://cdn.example.com/c.jpg"},
        ],
    }

    urls = _normalize_image_urls(payload)

    assert urls == [
        "https://cdn.example.com/a.jpg",
        "https://cdn.example.com/b.jpg",
        "https://cdn.example.com/c.jpg",
    ]



def test_parse_and_save_post_uses_shop_link_from_text_when_no_direct_images(tmp_db, monkeypatch):
    db = tmp_db

    def fake_expand(url: str):
        assert "shop-vkus.example" in url
        return ["https://cdn.example.com/full-1.jpg", "https://cdn.example.com/full-2.jpg"]

    monkeypatch.setattr(importer, "_expand_gallery_url_to_images", fake_expand)

    prod = parse_and_save_post(
        db,
        {
            "message_id": 77701,
            "text": "#sneakers\nКроссы\nhttps://shop-vkus.example/item/abc?single=true",
            "image_urls": [],
        },
    )
    assert prod is not None
    assert prod.default_image == "https://cdn.example.com/full-1.jpg"

    urls = [x.url for x in (prod.images or [])]
    assert urls == ["https://cdn.example.com/full-1.jpg", "https://cdn.example.com/full-2.jpg"]



def test_extract_size_stock_map_fallback_for_42_1sht():
    parsed = importer._extract_size_stock_map("в наличии: 41(0шт), 42(1шт), 43(0шт)")
    assert parsed == {"41": 0, "42": 1, "43": 0}
