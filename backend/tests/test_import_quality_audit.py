from decimal import Decimal

from app.api.v1 import admin_supplier_intelligence as asi
from app.db import models


def test_import_quality_audit_counts_issues(tmp_db):
    db = tmp_db

    cat = models.Category(name="Обувь", slug="obuv")
    db.add(cat)
    db.flush()

    p1 = models.Product(title="Nike Dunk", slug="nike-dunk-1", base_price=Decimal("3999"), category_id=cat.id, visible=True, default_image="/img/a.jpg")
    p2 = models.Product(title="Nike Dunk", slug="nike-dunk-2", base_price=Decimal("3999"), category_id=cat.id, visible=True)
    p3 = models.Product(title="Asics Gel", slug="asics-gel", base_price=Decimal("4999"), category_id=cat.id, visible=True)
    db.add_all([p1, p2, p3])
    db.flush()

    s42 = models.Size(name="42", slug="42")
    db.add(s42)
    db.flush()

    # p1: has size and stock > 0
    db.add(models.ProductVariant(product_id=p1.id, size_id=s42.id, price=Decimal("3999"), stock_quantity=2))
    # p2: no size + no stock
    db.add(models.ProductVariant(product_id=p2.id, price=Decimal("3999"), stock_quantity=0))
    # p3: has size but no stock
    db.add(models.ProductVariant(product_id=p3.id, size_id=s42.id, price=Decimal("4999"), stock_quantity=0))
    db.commit()

    out = asi.import_quality_audit(sample_limit=20, _admin=True, db=db)

    assert out.total_visible == 3
    assert out.one_photo_count >= 2
    assert out.no_size_count >= 1
    assert out.duplicate_title_count >= 2
    assert out.no_stock_count >= 2
    assert len(out.sample_items) > 0
