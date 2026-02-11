import app.api.v1.admin_supplier_intelligence as asi
import app.services.supplier_intelligence as si
from app.services.supplier_intelligence import SupplierOffer, detect_source_kind, estimate_market_price, extract_catalog_items, generate_youth_description, map_category, pick_best_offer, print_signature_hamming, suggest_sale_price


def test_estimate_market_price_ignores_fake_outliers():
    prices = [1, 2, 4500, 4700, 4900, 5100, 1_000_000]
    got = estimate_market_price(prices)
    assert got is not None
    assert 4600 <= got <= 5000


def test_map_category_groups_hoodie_and_zip_to_sweaters():
    assert map_category("Худи oversize") == "Кофты"
    assert map_category("ZIP hoodie black") == "Кофты"


def test_pick_best_offer_prefers_exact_color_and_size_then_price():
    offers = [
        SupplierOffer(supplier="A", title="Худи", color="black", size="M", dropship_price=3100, stock=2),
        SupplierOffer(supplier="B", title="Худи", color="black", size="M", dropship_price=2900, stock=1),
        SupplierOffer(supplier="C", title="Худи", color="white", size="M", dropship_price=2500, stock=9),
    ]
    best = pick_best_offer(offers, desired_color="black", desired_size="M")
    assert best is not None
    assert best.supplier == "B"


def test_detect_source_kind_google_sheet():
    assert detect_source_kind("https://docs.google.com/spreadsheets/d/abc/edit") == "google_sheet"


def test_extract_catalog_items_by_header():
    rows = [
        ["Товар", "Дроп цена", "Цвет", "Размер", "Наличие"],
        ["Худи Alpha", "3990", "Черный", "M", "3"],
    ]
    items = extract_catalog_items(rows)
    assert len(items) == 1
    assert items[0]["title"] == "Худи Alpha"
    assert items[0]["dropship_price"] == 3990.0


def test_generate_youth_description_mentions_title():
    txt = generate_youth_description("Худи Alpha", "Кофты", "черный")
    assert "Худи Alpha" in txt
    assert "стрит" in txt.lower()


def test_suggest_sale_price_markup():
    assert suggest_sale_price(1000) >= 1500


def test_print_signature_hamming_distance():
    assert print_signature_hamming("aaaa", "aaab") == 1


def test_print_signature_hamming_returns_none_for_different_lengths():
    assert print_signature_hamming("aaaa", "aaa") is None


def test_extract_catalog_items_skips_non_positive_price_rows():
    rows = [
        ["Товар", "Дроп цена", "Цвет"],
        ["Худи Alpha", "0", "Черный"],
        ["Худи Beta", "1990", "Белый"],
    ]
    items = extract_catalog_items(rows)
    assert [it["title"] for it in items] == ["Худи Beta"]


def test_http_get_with_retries_retries_on_429(monkeypatch):
    calls = {"n": 0}

    class DummyResp:
        def __init__(self, code: int):
            self.status_code = code
            self.headers = {"content-type": "text/html"}
            self.text = "ok"
            self.content = b"ok"

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"status={self.status_code}")

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        return DummyResp(429 if calls["n"] == 1 else 200)

    monkeypatch.setattr(si.requests, "get", fake_get)
    monkeypatch.setattr(si.time, "sleep", lambda *_: None)

    resp = si._http_get_with_retries("https://example.com", max_attempts=3)
    assert resp.status_code == 200
    assert calls["n"] == 2


def test_download_image_bytes_rejects_non_image_content(monkeypatch):
    class DummyResp:
        status_code = 200
        headers = {"content-type": "text/html"}
        content = b"<html></html>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(si, "_http_get_with_retries", lambda *a, **k: DummyResp())

    try:
        si._download_image_bytes("https://example.com/not-image")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "not an image" in str(exc)


def test_classify_import_error_codes():
    assert asi._classify_import_error(RuntimeError("request timeout on supplier")) == asi.ERROR_CODE_NETWORK_TIMEOUT
    assert asi._classify_import_error(RuntimeError("content is not an image")) == asi.ERROR_CODE_INVALID_IMAGE
    assert asi._classify_import_error(RuntimeError("parse error on source row")) == asi.ERROR_CODE_PARSE_FAILED
    assert asi._classify_import_error(RuntimeError("429 too many requests")) == asi.ERROR_CODE_NETWORK_TIMEOUT


def test_register_source_error_tracks_error_codes():
    report = asi._new_source_report(source_id=7, source_url="https://example.com/feed")

    asi._register_source_error(report, RuntimeError("request timeout"))
    asi._register_source_error(report, RuntimeError("request timeout"))
    asi._register_source_error(report, RuntimeError("parse failed"))

    assert report.errors == 3
    assert report.error_codes[asi.ERROR_CODE_NETWORK_TIMEOUT] == 2
    assert report.error_codes[asi.ERROR_CODE_PARSE_FAILED] == 1
    assert report.last_error_message == "parse failed"
