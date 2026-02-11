from app.services.supplier_intelligence import SupplierOffer, detect_source_kind, estimate_market_price, map_category, pick_best_offer


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
