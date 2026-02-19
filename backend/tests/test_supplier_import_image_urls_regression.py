from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.admin_supplier_intelligence import ImportProductsIn, import_products_from_sources
from app.db import models
from app.db.models import Base
import app.api.v1.admin_supplier_intelligence as asi


def test_import_products_does_not_fail_when_source_item_uses_only_image_url(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Фото", "Размер", "Наличие"],
                    ["Nike SB Dunk", "4900", "https://t.me/shop_vkus/15972?single", "42", "42(1шт)"],
                ]
            }

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "extract_image_urls_from_html_page", lambda *a, **k: [
            "https://cdn.example.com/a.jpg",
            "https://cdn.example.com/b.jpg",
        ])
        monkeypatch.setattr(asi, "_prefer_local_image_url", lambda url, **kwargs: url)

        out = import_products_from_sources(
            ImportProductsIn(
                source_ids=[int(src.id)],
                dry_run=False,
                use_avito_pricing=False,
                ai_style_description=False,
                ai_description_enabled=False,
                max_items_per_source=10,
            ),
            _admin=None,
            db=db,
        )

        assert out.created_products >= 1
        assert len(out.source_reports) == 1
        assert out.source_reports[0].errors == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)



def test_import_products_unknown_stock_does_not_mark_all_sizes_in_stock(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-2/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Фото", "Размер"],
                    ["Model X", "4900", "https://cdn.example.com/one.jpg", "41,42,43"],
                ]
            }

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "_prefer_local_image_url", lambda url, **kwargs: url)

        out = import_products_from_sources(
            ImportProductsIn(
                source_ids=[int(src.id)],
                dry_run=False,
                use_avito_pricing=False,
                ai_style_description=False,
                ai_description_enabled=False,
                max_items_per_source=10,
            ),
            _admin=None,
            db=db,
        )

        assert out.created_products >= 1
        variants = db.query(models.ProductVariant).all()
        assert variants
        assert all(int(v.stock_quantity or 0) == 0 for v in variants)
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_replaces_single_existing_image_with_full_gallery(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        cat = models.Category(name="Обувь", slug="obuv")
        db.add(cat)
        db.flush()
        p = models.Product(
            title="Nike SB Dunk",
            slug="nike-sb-dunk",
            base_price=5000,
            currency="RUB",
            category_id=cat.id,
            default_image="https://t.me/shop_vkus/15972?single",
            visible=True,
        )
        db.add(p)
        db.flush()
        db.add(models.ProductImage(product_id=p.id, url="https://t.me/shop_vkus/15972?single", sort=0))
        db.commit()

        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-3/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Фото", "Размер", "Наличие"],
                    ["Nike SB Dunk", "4900", "https://t.me/shop_vkus/15972?single", "42", "42(1шт)"],
                ]
            }

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "extract_image_urls_from_html_page", lambda *a, **k: [
            "https://cdn.example.com/a.jpg",
            "https://cdn.example.com/b.jpg",
            "https://cdn.example.com/c.jpg",
        ])
        monkeypatch.setattr(asi, "_prefer_local_image_url", lambda url, **kwargs: url)

        out = import_products_from_sources(
            ImportProductsIn(
                source_ids=[int(src.id)],
                dry_run=False,
                use_avito_pricing=False,
                ai_style_description=False,
                ai_description_enabled=False,
                max_items_per_source=10,
            ),
            _admin=None,
            db=db,
        )

        db.refresh(p)
        imgs = [x.url for x in db.query(models.ProductImage).filter(models.ProductImage.product_id == p.id).order_by(models.ProductImage.sort.asc()).all()]
        assert imgs[:3] == [
            "https://cdn.example.com/a.jpg",
            "https://cdn.example.com/b.jpg",
            "https://cdn.example.com/c.jpg",
        ]
        assert p.default_image == "https://cdn.example.com/a.jpg"
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_plain_available_sizes_keep_only_those_sizes_in_stock(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-4/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Ссылка"],
                    ["Nike SB Dunk", "4900", "41-45", "42", "https://t.me/shop_vkus/15972?single"],
                ]
            }

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "extract_image_urls_from_html_page", lambda *a, **k: [
            "https://cdn.example.com/a.jpg",
            "https://cdn.example.com/b.jpg",
        ])
        monkeypatch.setattr(asi, "_prefer_local_image_url", lambda url, **kwargs: url)

        out = import_products_from_sources(
            ImportProductsIn(
                source_ids=[int(src.id)],
                dry_run=False,
                use_avito_pricing=False,
                ai_style_description=False,
                ai_description_enabled=False,
                max_items_per_source=10,
            ),
            _admin=None,
            db=db,
        )

        assert out.created_products >= 1
        variants = db.query(models.ProductVariant).all()
        assert len(variants) == 5
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 1
        assert by_size["41"] == 0
        assert by_size["43"] == 0
        assert by_size["44"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_rerank_gallery_images_shop_vkus_drops_first_two_and_caps_to_seven():
    urls = [f"https://cdn.example.com/{i}.jpg" for i in range(1, 11)]
    out = asi._rerank_gallery_images(urls, supplier_key="shop_vkus")
    assert len(out) == 7
    assert "https://cdn.example.com/1.jpg" not in out
    assert "https://cdn.example.com/2.jpg" not in out




def test_rerank_gallery_images_shop_vkus_drops_first_two_for_short_gallery_when_leading_pair_is_suspicious():
    urls = [
        "https://cdn.example.com/pair-front.jpg",
        "https://cdn.example.com/shop_vkus_card.jpg",
        "https://cdn.example.com/side.jpg",
        "https://cdn.example.com/back.jpg",
        "https://cdn.example.com/pair-front.jpg",
    ]
    out = asi._rerank_gallery_images(urls, supplier_key="shop_vkus")
    assert out == [
        "https://cdn.example.com/side.jpg",
        "https://cdn.example.com/back.jpg",
    ]


def test_rerank_gallery_images_shop_vkus_keeps_short_clean_gallery_intact():
    urls = [f"https://cdn.example.com/{i}.jpg" for i in range(1, 6)]
    out = asi._rerank_gallery_images(urls, supplier_key="shop_vkus")
    assert out == urls

def test_import_products_shop_vkus_detected_from_row_link_even_if_supplier_name_differs(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-5/htmlview",
            supplier_name="def shop",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Ссылка"],
                    ["Nike SB Dunk", "4900", "41-45", "42", "https://t.me/shop_vkus/15972?single"],
                ]
            }

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "extract_image_urls_from_html_page", lambda *a, **k: [
            "https://cdn.example.com/p1.jpg",
            "https://cdn.example.com/p2.jpg",
        ])
        monkeypatch.setattr(asi, "_prefer_local_image_url", lambda url, **kwargs: url)

        out = import_products_from_sources(
            ImportProductsIn(
                source_ids=[int(src.id)],
                dry_run=False,
                use_avito_pricing=False,
                ai_style_description=False,
                ai_description_enabled=False,
                max_items_per_source=10,
            ),
            _admin=None,
            db=db,
        )

        assert out.created_products >= 1
        variants = db.query(models.ProductVariant).all()
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size.get("42") == 1
        assert by_size.get("41") == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)
