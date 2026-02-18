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
