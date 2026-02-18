from app.db import models
from app.services.importer_notifications import parse_and_save_post, _normalize_image_urls
from app.api.v1.products import list_products, get_product


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


def test_product_api_sizes_include_only_in_stock_sizes_when_available(tmp_db):
    db = tmp_db
    prod = parse_and_save_post(
        db,
        {
            "message_id": 501,
            "text": "#sneakers\nStock by size\nsize 41(0),42(3)",
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
    assert {v.size.name: v.stock_quantity for v in variants} == {"41": 0, "42": 3}
