from app.services.supplier_profiles import normalize_title_for_supplier


def test_normalize_title_for_supplier_strips_noise_tokens():
    raw = "Nike SB Dunk Low [в наличии] (арт: NK123) топ качество"
    out = normalize_title_for_supplier(raw, "shop_vkus")
    assert "арт" not in out.lower()
    assert "топ качество" not in out.lower()
    assert "nike sb dunk low" in out.lower()


def test_normalize_title_for_supplier_keeps_plain_title():
    raw = "ASICS GEL KAHANA 8"
    out = normalize_title_for_supplier(raw, "unknown")
    assert out == raw


def test_normalize_title_for_supplier_trims_only_trailing_variant_suffixes():
    assert normalize_title_for_supplier("NB 1906R #2", "shop_vkus") == "NB 1906R"
    assert normalize_title_for_supplier("Jordan 4 (2)", "shop_vkus") == "Jordan 4"
    assert normalize_title_for_supplier("Yeezy 350 v2", "shop_vkus") == "Yeezy 350 v2"
    assert normalize_title_for_supplier("NB 990v2", "shop_vkus") == "NB 990v2"
