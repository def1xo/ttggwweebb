from app.services.supplier_importers import (
    ImporterContext,
    TabularSupplierImporter,
    get_importer_for_source,
    resolve_tg_photos,
)


def test_tabular_importer_contract():
    importer = TabularSupplierImporter(
        fetch_preview_fn=lambda *args, **kwargs: {"rows_preview": [["title", "price"], ["Nike", "4900"]]},
        extract_items_fn=lambda rows, max_items=60: [{"title": "Nike", "dropship_price": 4900, "image_urls": ["a", "a"], "size": "41 42"}],
    )


    ctx = ImporterContext(source_url="https://docs.google.com/spreadsheets/d/abc/edit", supplier_name="shop_vkus", max_items=10, fetch_timeout_sec=10)
    rows = importer.fetch_rows(ctx)
    parsed = importer.parse_row(rows[0], ctx)
    grouped = importer.group_rows([parsed], ctx)

    assert parsed is not None
    assert parsed["dropship_price"] == 4900
    assert parsed["image_urls"] == ["a"]
    assert parsed["size_tokens"] == ["41", "42"]
    assert grouped and grouped[0]["title"] == "Nike"


def test_resolve_tg_photos_graceful_pending():
    photos, status = resolve_tg_photos(["https://t.me/shop_vkus/1"], lambda *_args, **_kwargs: [])
    assert photos == []
    assert status == "pending"


def test_registry_returns_firmach_importer():
    importer = get_importer_for_source("https://docs.google.com/spreadsheets/d/abc/edit", "Фирмач дроп")
    assert importer.__class__.__name__ == "FirmachDropImporter"


def test_shop_vkus_contract_uses_unified_methods_without_breaking_parse():
    importer = get_importer_for_source("https://docs.google.com/spreadsheets/d/abc/edit", "shop_vkus")
    ctx = ImporterContext(source_url="https://docs.google.com/spreadsheets/d/abc/edit", supplier_name="shop_vkus", max_items=5, fetch_timeout_sec=10)

    importer._fetch_preview_fn = lambda *_a, **_k: {"rows_preview": [["title", "price"], ["Yeezy", "5000"]]}
    importer._extract_items_fn = lambda *_a, **_k: [{"title": "Yeezy", "dropship_price": 5000, "image_urls": ["x", "x"], "size": "42 43"}]

    rows = importer.fetch(ctx)
    parsed = importer.normalize(rows[0], ctx)
    grouped = importer.group([parsed], ctx)

    assert importer.__class__.__name__ == "ShopVkusImporter"
    assert grouped[0]["title"] == "Yeezy"
    assert grouped[0]["size_tokens"] == ["42", "43"]
