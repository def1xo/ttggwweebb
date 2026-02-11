from app.services.importer_notifications import _extract_stock_quantity


def test_extract_stock_prefers_payload_over_text():
    payload = {"stock_quantity": "12"}
    text = "Остаток: 3"
    assert _extract_stock_quantity(text, payload) == 12


def test_extract_stock_from_payload_aliases_and_clamps_negative():
    assert _extract_stock_quantity("", {"qty": 7}) == 7
    assert _extract_stock_quantity("", {"quantity": "-5"}) == 0


def test_extract_stock_from_text_russian_keywords():
    assert _extract_stock_quantity("В наличии: 15") == 15
    assert _extract_stock_quantity("Остаток-9") == 9


def test_extract_stock_from_text_english_keywords():
    assert _extract_stock_quantity("stock: 21") == 21


def test_extract_stock_returns_none_when_absent_or_invalid():
    assert _extract_stock_quantity("Наличие: много") is None
    assert _extract_stock_quantity("", {}) is None
    assert _extract_stock_quantity(None, None) is None
