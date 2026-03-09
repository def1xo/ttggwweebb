from types import SimpleNamespace

from app.routes import recommendations as rec


def test_serialize_product_marks_in_stock_when_any_variant_positive_stock():
    p = SimpleNamespace(
        id=11,
        title="Model",
        base_price=5000,
        default_image="/x.jpg",
        created_at=None,
        variants=[SimpleNamespace(stock_quantity=0), SimpleNamespace(stock_quantity=3)],
    )
    out = rec.serialize_product(p)
    assert out["has_stock"] is True


def test_serialize_product_marks_out_of_stock_when_no_positive_variants():
    p = SimpleNamespace(
        id=12,
        title="Model 2",
        base_price=5000,
        default_image="/x.jpg",
        created_at=None,
        variants=[SimpleNamespace(stock_quantity=0), SimpleNamespace(stock_quantity=0)],
    )
    out = rec.serialize_product(p)
    assert out["has_stock"] is False
