from decimal import Decimal

from app.api.v1.products import _build_color_payload
from app.db import models


def test_build_color_payload_single_color_uses_full_base_gallery():
    product = models.Product(
        title="Кроссовки Alpha",
        slug="krossovki-alpha",
        base_price=Decimal("4990.00"),
        detected_color="Черный",
        import_media_meta={"general_images": ["https://img/general-1.jpg", "https://img/general-2.jpg"]},
    )
    product.images = [
        models.ProductImage(url="https://img/base-1.jpg", sort=0),
        models.ProductImage(url="https://img/base-2.jpg", sort=1),
        models.ProductImage(url="https://img/base-3.jpg", sort=2),
        models.ProductImage(url="https://img/base-4.jpg", sort=3),
    ]
    product.variants = [
        models.ProductVariant(images=["https://img/variant-1.jpg", "https://img/base-2.jpg"]),
        models.ProductVariant(images=["https://img/variant-2.jpg"]),
    ]

    payload = _build_color_payload(product)

    assert payload["selected_color"] == "black"
    assert len(payload["selected_color_images"]) >= 4
    assert payload["selected_color_images"] == [
        "https://img/base-1.jpg",
        "https://img/base-2.jpg",
        "https://img/base-3.jpg",
        "https://img/base-4.jpg",
        "https://img/general-1.jpg",
        "https://img/general-2.jpg",
        "https://img/variant-1.jpg",
        "https://img/variant-2.jpg",
    ]
