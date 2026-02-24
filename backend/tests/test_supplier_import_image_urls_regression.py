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



def test_import_products_unknown_stock_shop_vkus_marks_listed_sizes_as_default_in_stock(monkeypatch):
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
        assert all(int(v.stock_quantity or 0) == 9999 for v in variants)
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
        assert by_size["42"] == 9999
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


def test_rerank_gallery_images_shop_vkus_keeps_clean_five_image_gallery():
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
        assert by_size.get("42") == 9999
        assert by_size.get("41") == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_rerank_gallery_images_shop_vkus_drops_outlier_signature_cluster(monkeypatch):
    urls = [
        "https://cdn.example.com/main-1.jpg",
        "https://cdn.example.com/main-2.jpg",
        "https://cdn.example.com/main-3.jpg",
        "https://cdn.example.com/main-4.jpg",
        "https://cdn.example.com/outlier-1.jpg",
        "https://cdn.example.com/outlier-2.jpg",
    ]

    sig_map = {
        "https://cdn.example.com/main-1.jpg": "aaaa",
        "https://cdn.example.com/main-2.jpg": "aaab",
        "https://cdn.example.com/main-3.jpg": "aaac",
        "https://cdn.example.com/main-4.jpg": "aaad",
        "https://cdn.example.com/outlier-1.jpg": "ffff",
        "https://cdn.example.com/outlier-2.jpg": "fffe",
    }

    monkeypatch.setattr(asi, "image_print_signature_from_url", lambda u: sig_map.get(u))
    monkeypatch.setattr(
        asi,
        "print_signature_hamming",
        lambda a, b: 1 if (str(a).startswith("a") and str(b).startswith("a")) or (str(a).startswith("f") and str(b).startswith("f")) else 16,
    )

    out = asi._rerank_gallery_images(urls, supplier_key="shop_vkus")
    assert out == [
        "https://cdn.example.com/main-1.jpg",
        "https://cdn.example.com/main-2.jpg",
        "https://cdn.example.com/main-3.jpg",
        "https://cdn.example.com/main-4.jpg",
    ]


def test_import_products_shop_vkus_extracts_sizes_from_description_when_size_cell_empty(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-6/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Описание", "Фото"],
                    [
                        "Adidas Campus",
                        "3900",
                        "",
                        "",
                        "Размеры: 41 42 43",
                        "https://cdn.example.com/campus.jpg",
                    ],
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
        names = sorted(
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else "")
            for v in variants
        )
        assert names == ["41", "42", "43"]
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_non_numeric_stock_list_sets_default_in_stock_only_for_listed_sizes(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-7/htmlview",
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
                    ["Nike SB Dunk", "4900", "41-45", "42,44", "https://t.me/shop_vkus/15972?single"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["44"] == 9999
        assert by_size["41"] == 0
        assert by_size["43"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_rerank_gallery_images_shop_vkus_drops_first_two_when_second_suspicious_and_first_duplicated(monkeypatch):
    urls = [
        "https://cdn.example.com/cover.jpg",
        "https://cdn.example.com/card.jpg",
        "https://cdn.example.com/p2.jpg",
        "https://cdn.example.com/p3.jpg",
        "https://cdn.example.com/p4.jpg",
        "https://cdn.example.com/cover.jpg",
        "https://cdn.example.com/p5.jpg",
    ]

    monkeypatch.setattr(asi, "_is_likely_product_image", lambda u: not str(u).endswith("card.jpg"))
    monkeypatch.setattr(asi, "_score_gallery_image", lambda u: -10.0 if str(u).endswith("card.jpg") else 10.0)

    out = asi._rerank_gallery_images(urls, supplier_key="shop_vkus")
    assert "https://cdn.example.com/card.jpg" not in out
    assert "https://cdn.example.com/cover.jpg" not in out


def test_rerank_gallery_images_shop_vkus_keeps_short_clean_gallery_order():
    urls = [f"https://cdn.example.com/{i}.jpg" for i in range(1, 8)]
    out = asi._rerank_gallery_images(urls, supplier_key="shop_vkus")
    assert out == urls


def test_rerank_gallery_images_shop_vkus_drops_first_two_when_cover_duplicated_in_five_plus():
    urls = [
        "https://cdn.example.com/cover.jpg",
        "https://cdn.example.com/clean2.jpg",
        "https://cdn.example.com/p2.jpg",
        "https://cdn.example.com/p3.jpg",
        "https://cdn.example.com/cover.jpg",
        "https://cdn.example.com/p4.jpg",
    ]
    out = asi._rerank_gallery_images(urls, supplier_key="shop_vkus")
    assert "https://cdn.example.com/clean2.jpg" not in out


def test_import_products_shop_vkus_stock_range_marks_all_range_sizes_as_default_in_stock(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-8/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["Nike SB Dunk", "4900", "", "41-45", "https://cdn.example.com/a.jpg"],
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
        assert all(int(v.stock_quantity or 0) == 9999 for v in variants)
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_stock_word_in_stock_marks_all_listed_sizes_default_in_stock(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-9/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["Nike SB Dunk", "4900", "41-45", "в наличии", "https://cdn.example.com/a.jpg"],
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
        assert all(int(v.stock_quantity or 0) == 9999 for v in variants)
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_stock_text_with_specific_size_marks_only_that_size(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-10/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["Nike SB Dunk", "4900", "41-45", "в наличии 42", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["41"] == 0
        assert by_size["43"] == 0
        assert by_size["44"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_stock_text_with_specific_size_marks_only_that_size(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-10/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["Nike SB Dunk", "4900", "41-45", "в наличии 42", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["41"] == 0
        assert by_size["43"] == 0
        assert by_size["44"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_like_row_without_link_uses_availability_sizes_only(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-11/htmlview",
            supplier_name="def shop",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["SB DUNK LOW REMASTERED", "4900", "41-45", "42 (1шт)", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["41"] == 0
        assert by_size["43"] == 0
        assert by_size["44"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)



def test_import_products_shop_vkus_like_row_without_link_and_plain_size_list_uses_only_listed_sizes(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-12/htmlview",
            supplier_name="def shop",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["ASICS GEL KAHANA 8", "4900", "41-45", "42,43,44", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["43"] == 9999
        assert by_size["44"] == 9999
        assert by_size["41"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_stock_text_with_specific_size_marks_only_that_size(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-10/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["Nike SB Dunk", "4900", "41-45", "в наличии 42", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["41"] == 0
        assert by_size["43"] == 0
        assert by_size["44"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_generic_single_half_size_stock_token_marks_it_in_stock(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-10c/htmlview",
            supplier_name="def shop",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["Nike Zoom", "4900", "43.5", "43.5", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["43.5"] > 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_single_half_size_stock_token_marks_it_in_stock(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-10b/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["Nike SB Dunk", "4900", "43.5", "43.5", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["43.5"] > 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_like_row_without_link_uses_availability_sizes_only(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-11/htmlview",
            supplier_name="def shop",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["SB DUNK LOW REMASTERED", "4900", "41-45", "42 (1шт)", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["41"] == 0
        assert by_size["43"] == 0
        assert by_size["44"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)



def test_import_products_shop_vkus_like_row_without_link_and_plain_size_list_uses_only_listed_sizes(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-12/htmlview",
            supplier_name="def shop",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["ASICS GEL KAHANA 8", "4900", "41-45", "42,43,44", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["43"] == 9999
        assert by_size["44"] == 9999
        assert by_size["41"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)



def test_import_products_row_with_expanded_size_list_and_single_available_size_marks_only_one(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-13/htmlview",
            supplier_name="def shop",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["NIKE AIR FORCE 1", "4900", "41 42 43 44 45", "42", "https://cdn.example.com/a.jpg"],
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
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["41"] == 0
        assert by_size["43"] == 0
        assert by_size["44"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)



def test_import_products_prefers_row_dropship_markup_over_rrc_discount(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-13a/htmlview",
            supplier_name="def shop",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "РРЦ", "Размер", "Наличие", "Фото"],
                    ["NIKE zoom vomero 5", "дроп 2099 / Слив:2000", "2400", "41-45", "42", "https://cdn.example.com/vomero.jpg"],
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
        product = db.query(models.Product).filter(models.Product.import_source_url == src.source_url).one()
        assert int(float(product.base_price or 0)) == 2799
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_infers_single_colors_per_row_when_color_cell_empty(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-13b/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["ADIDAS NITEBALL", "2700", "41-45", "42", "https://cdn.example.com/white.jpg"],
                    ["ADIDAS NITEBALL", "2700", "41-45", "42", "https://cdn.example.com/black.jpg"],
                ]
            }

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "_prefer_local_image_url", lambda url, **kwargs: url)
        monkeypatch.setattr(
            asi,
            "dominant_color_name_from_url",
            lambda u: "белый" if "white" in str(u or "") else "черный",
        )

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
        color_names = {
            (db.query(models.Color).filter(models.Color.id == v.color_id).one().name if v.color_id else "")
            for v in variants
        }
        assert "белый" in color_names
        assert "черный" in color_names
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_overwrites_old_positive_sizes_not_listed_in_availability(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        cat = models.Category(name="Обувь", slug="obuv-stale")
        db.add(cat)
        db.flush()

        p = models.Product(
            title="Nike SB Dunk Low x Travis Scott Cactus",
            slug="nike-sb-dunk-low-travis-scott-cactus-stale",
            base_price=5000,
            currency="RUB",
            category_id=cat.id,
            default_image="https://cdn.example.com/a.jpg",
            visible=True,
            import_supplier_name="shop_vkus",
            import_source_kind="google_sheet",
            import_source_url="https://docs.google.com/spreadsheets/d/test-sheet-14/htmlview",
        )
        db.add(p)
        db.flush()

        sizes = {}
        for sn in ["41", "42", "43", "44", "45"]:
            sz = models.Size(name=sn)
            db.add(sz)
            db.flush()
            sizes[sn] = sz

        # stale positives from previous bad import
        db.add(models.ProductVariant(product_id=p.id, size_id=sizes["41"].id, color_id=None, price=4900, stock_quantity=9999))
        db.add(models.ProductVariant(product_id=p.id, size_id=sizes["45"].id, color_id=None, price=4900, stock_quantity=9999))
        db.commit()

        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-14/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["№", "название", "фото", "ЦЕНА ДРОП/ШТУЧНО", "РАЗМЕРЫ", "НАЛИЧИЕ", "Ссылка"],
                    ["2", "Nike SB Dunk Low x Travis Scott Cactus", "", "2000", "41-45", "42 (1шт)", "https://t.me/shop_vkus/15972?single"],
                ]
            }

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "extract_image_urls_from_html_page", lambda *a, **k: ["https://cdn.example.com/a.jpg"])
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

        assert out.created_products >= 0
        variants = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == p.id).all()
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["41"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)



def test_import_products_shop_vkus_overwrites_stale_sizes_across_colors_when_availability_explicit(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        cat = models.Category(name="Обувь", slug="obuv-stale-colors")
        db.add(cat)
        db.flush()

        p = models.Product(
            title="Nike SB Dunk Low x Travis Scott Cactus",
            slug="nike-sb-dunk-low-travis-scott-cactus-stale-colors",
            base_price=5000,
            currency="RUB",
            category_id=cat.id,
            default_image="https://cdn.example.com/a.jpg",
            visible=True,
            import_supplier_name="shop_vkus",
            import_source_kind="google_sheet",
            import_source_url="https://docs.google.com/spreadsheets/d/test-sheet-15/htmlview",
        )
        db.add(p)
        db.flush()

        size41 = models.Size(name="41")
        size42 = models.Size(name="42")
        size45 = models.Size(name="45")
        color_black = models.Color(name="Черный")
        db.add_all([size41, size42, size45, color_black])
        db.flush()

        db.add(models.ProductVariant(product_id=p.id, size_id=size41.id, color_id=color_black.id, price=4900, stock_quantity=9999))
        db.add(models.ProductVariant(product_id=p.id, size_id=size45.id, color_id=color_black.id, price=4900, stock_quantity=9999))
        db.commit()

        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-15/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["№", "название", "фото", "ЦЕНА ДРОП/ШТУЧНО", "РАЗМЕРЫ", "НАЛИЧИЕ", "Ссылка"],
                    ["2", "Nike SB Dunk Low x Travis Scott Cactus", "", "2000", "41-45", "42 (1шт)", "https://t.me/shop_vkus/15972?single"],
                ]
            }

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "extract_image_urls_from_html_page", lambda *a, **k: ["https://cdn.example.com/a.jpg"])
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

        assert out.created_products >= 0
        variants = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == p.id).all()
        by_size = {
            (db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""): int(v.stock_quantity or 0)
            for v in variants
        }
        assert by_size["42"] == 9999
        assert by_size["41"] == 0
        assert by_size["45"] == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_splits_two_rows_by_post_link_into_two_colorways(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-split/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото", "Ссылка"],
                    ["Nike ZoomX", "4900", "41-43", "41", "https://t.me/shop_vkus/1001?single", "https://t.me/shop_vkus/1001?single"],
                    ["Nike ZoomX", "4900", "42-44", "44", "https://t.me/shop_vkus/1002?single", "https://t.me/shop_vkus/1002?single"],
                ]
            }

        def _fake_extract(url, *args, **kwargs):
            if "1001" in str(url):
                return [
                    "https://cdn.example.com/a1.jpg",
                    "https://cdn.example.com/a2.jpg",
                    "https://cdn.example.com/a3.jpg",
                    "https://cdn.example.com/a4.jpg",
                ]
            return [
                "https://cdn.example.com/b1.jpg",
                "https://cdn.example.com/b2.jpg",
                "https://cdn.example.com/b3.jpg",
                "https://cdn.example.com/b4.jpg",
            ]

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "extract_image_urls_from_html_page", _fake_extract)
        monkeypatch.setattr(asi, "_prefer_local_image_url", lambda url, **kwargs: url)
        monkeypatch.setattr(
            asi,
            "dominant_color_name_from_url",
            lambda u: "white" if "/a" in str(u or "") else "black",
        )

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
        products = db.query(models.Product).all()
        assert len(products) == 1
        p = products[0]
        p_images = [x.url for x in (p.images or [])]
        assert len(p_images) > 6
        variants = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == p.id).all()
        colors = {db.query(models.Color).filter(models.Color.id == v.color_id).one().name for v in variants if v.color_id}
        assert len(colors) == 2
        by_color_images = {}
        by_color_sizes = {}
        for v in variants:
            c = db.query(models.Color).filter(models.Color.id == v.color_id).one().name
            by_color_images.setdefault(c, set()).update(v.images or [])
            s = db.query(models.Size).filter(models.Size.id == v.size_id).one().name if v.size_id else ""
            by_color_sizes.setdefault(c, set()).add(s)
        assert by_color_images["белый"] == {
            "https://cdn.example.com/a1.jpg",
            "https://cdn.example.com/a2.jpg",
            "https://cdn.example.com/a3.jpg",
            "https://cdn.example.com/a4.jpg",
        }
        assert by_color_images["черный"] == {
            "https://cdn.example.com/b1.jpg",
            "https://cdn.example.com/b2.jpg",
            "https://cdn.example.com/b3.jpg",
            "https://cdn.example.com/b4.jpg",
        }
        assert by_color_sizes["белый"] == {"41", "42", "43"}
        assert by_color_sizes["черный"] == {"42", "43", "44"}
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_import_products_shop_vkus_single_row_keeps_single_colorway_for_four_to_six_photos(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        src = models.SupplierSource(
            source_url="https://docs.google.com/spreadsheets/d/test-sheet-single/htmlview",
            supplier_name="shop_vkus",
            active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)

        def _fake_preview(*args, **kwargs):
            return {
                "rows_preview": [
                    ["Товар", "Дроп цена", "Размер", "Наличие", "Фото"],
                    ["NB 9060", "3900", "41-44", "42", "https://t.me/shop_vkus/2001?single"],
                ]
            }

        monkeypatch.setattr(asi, "fetch_tabular_preview", _fake_preview)
        monkeypatch.setattr(asi, "extract_image_urls_from_html_page", lambda *a, **k: [
            "https://cdn.example.com/c1.jpg",
            "https://cdn.example.com/c2.jpg",
            "https://cdn.example.com/c3.jpg",
            "https://cdn.example.com/c4.jpg",
            "https://cdn.example.com/c5.jpg",
        ])
        monkeypatch.setattr(asi, "_prefer_local_image_url", lambda url, **kwargs: url)
        monkeypatch.setattr(asi, "dominant_color_name_from_url", lambda u: "white")

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
        products = db.query(models.Product).all()
        assert len(products) == 1
        p = products[0]
        variants = db.query(models.ProductVariant).filter(models.ProductVariant.product_id == p.id).all()
        colors = {db.query(models.Color).filter(models.Color.id == v.color_id).one().name for v in variants if v.color_id}
        assert colors == {"white"}
        merged_images = set()
        for v in variants:
            merged_images.update(v.images or [])
        assert merged_images == {
            "https://cdn.example.com/c1.jpg",
            "https://cdn.example.com/c2.jpg",
            "https://cdn.example.com/c3.jpg",
            "https://cdn.example.com/c4.jpg",
            "https://cdn.example.com/c5.jpg",
        }
    finally:
        db.close()
        Base.metadata.drop_all(engine)
