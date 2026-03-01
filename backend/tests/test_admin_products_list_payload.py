from decimal import Decimal

from app.api.v1 import admin as admin_api
from app.db import models


class _Admin:
    id = 1


def test_admin_products_list_includes_colors_sizes_and_meta(tmp_db):
    color = models.Color(name="black")
    size = models.Size(name="42")
    product = models.Product(title="NB", slug="nb", base_price=Decimal("1000"), visible=True)
    tmp_db.add_all([color, size, product])
    tmp_db.flush()

    tmp_db.add(models.ProductImage(product_id=product.id, url="/uploads/1.jpg", sort=0))
    tmp_db.add(
        models.ProductVariant(
            product_id=product.id,
            size_id=size.id,
            color_id=color.id,
            price=Decimal("1000"),
            stock_quantity=3,
            images=["/uploads/1.jpg"],
        )
    )
    tmp_db.commit()

    out = admin_api.admin_list_products(db=tmp_db, admin=_Admin(), q=None, page=1, per_page=50)

    payload = out.model_dump()
    assert set(payload.keys()) == {"items", "total", "page", "pages", "limit"}
    assert payload["total"] == 1
    assert payload["items"][0]["sizes"] == ["42"]
    assert payload["items"][0]["colors"] == ["black"]
    assert payload["items"][0]["image_count"] == 1


def test_admin_products_list_falls_back_to_detected_color_when_variants_uncolored(tmp_db):
    product = models.Product(
        title="Yeezy",
        slug="yeezy",
        base_price=Decimal("1000"),
        visible=True,
        detected_color="black-white",
    )
    tmp_db.add(product)
    tmp_db.commit()

    out = admin_api.admin_list_products(db=tmp_db, admin=_Admin(), q=None, page=1, per_page=50)

    payload = out.model_dump()
    assert payload["items"][0]["colors"] == ["белый", "черный"]
