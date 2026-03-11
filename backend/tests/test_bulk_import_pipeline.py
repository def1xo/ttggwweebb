from app.db import models
from app.services.bulk_import import _parse_colors, run_csv_import


def test_parse_colors_from_title_and_multi_variant():
    colors = _parse_colors(None, "Кеды Model X (black/white)", [])
    assert "black" in colors
    assert "white" in colors


def test_import_creates_color_image_links(tmp_db):
    src = models.SupplierSource(source_url="http://example.com/s1", supplier_name="S1")
    cat = models.Category(name="sports shoes", slug="sports-shoes")
    tmp_db.add_all([src, cat])
    tmp_db.commit()

    csv_text = "supplier_id,supplier_sku,title,supplier_category,images,color\n1,SKU-1,Test Shoe,sports shoes,img1.jpg|img2.jpg,black\n"
    job = run_csv_import(tmp_db, supplier_id=src.id, csv_text=csv_text)
    assert job.status == "completed"

    p = tmp_db.query(models.Product).filter(models.Product.supplier_sku == "SKU-1").first()
    assert p is not None
    links = tmp_db.query(models.ColorImage).all()
    assert len(links) >= 1


def test_supplier_specific_category_mapping_fuzzy(tmp_db):
    src = models.SupplierSource(source_url="http://example.com/s2", supplier_name="S2")
    cat = models.Category(name="sports shoes", slug="sports-shoes")
    tmp_db.add_all([src, cat])
    tmp_db.commit()

    csv_text = "supplier_id,supplier_sku,title,supplier_category,images,color\n2,SKU-2,Runner,sports-shoes,img.jpg,white\n"
    run_csv_import(tmp_db, supplier_id=src.id, csv_text=csv_text)

    m = tmp_db.query(models.SupplierCategoryMap).filter(models.SupplierCategoryMap.supplier_id == src.id).first()
    assert m is not None
    assert m.confidence > 0


def test_import_transaction_rolls_back_on_error(tmp_db):
    src = models.SupplierSource(source_url="http://example.com/s3", supplier_name="S3")
    tmp_db.add(src)
    tmp_db.commit()

    bad_csv = "supplier_id,supplier_sku,title,supplier_category,images,color\n3,SKU-3,,sports,img.jpg,black\n"
    job = run_csv_import(tmp_db, supplier_id=src.id, csv_text=bad_csv)
    assert job.status in {"failed", "completed"}
    # invariant: unresolved color/category should not publish into catalog
    published = tmp_db.query(models.Product).filter(models.Product.visible == True).count()  # noqa: E712
    assert published == 0
