from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.v1.admin_supplier_intelligence as asi
from app.db.models import Base, Product, ProductVariant, Color


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_build_color_assignment_returns_combo_for_significant_two_tone(monkeypatch):
    predictions = {
        "img1": {"color": "black", "confidence": 0.9, "probs": {"black": 0.9, "white": 0.45}},
        "img2": {"color": "black", "confidence": 0.8, "probs": {"black": 0.8, "white": 0.35}},
        "img3": {"color": "black", "confidence": 0.7, "probs": {"black": 0.7, "white": 0.3}},
        "img4": {"color": "black", "confidence": 0.6, "probs": {"black": 0.6, "white": 0.25}},
    }

    monkeypatch.setattr(asi, "predict_color_for_image_url", lambda url, kind: predictions[url])
    monkeypatch.setattr(asi, "_score_gallery_image", lambda url: 100.0)

    assignment = asi._build_color_assignment(
        title="Nike Air Max",
        supplier_key="any",
        src_url="https://supplier.example/item",
        item={"title": "Nike Air Max", "color": ""},
        image_urls=["img1", "img2", "img3", "img4"],
    )

    assert assignment["detected_color"] == "black-white"
    assert assignment["color_tokens"] == ["black-white"]


def test_build_color_assignment_with_empty_detection_keeps_color_empty(monkeypatch):
    monkeypatch.setattr(asi, "predict_color_for_image_url", lambda url, kind: {"color": "multi", "confidence": 0.9, "probs": {"multi": 0.9}})
    monkeypatch.setattr(asi, "_score_gallery_image", lambda url: 100.0)

    assignment = asi._build_color_assignment(
        title="Nike Air Max",
        supplier_key="any",
        src_url="https://supplier.example/item",
        item={"title": "Nike Air Max", "color": ""},
        image_urls=["img1", "img2"],
    )

    assert assignment["detected_color"] == ""
    assert assignment["color_tokens"] == []
    assert assignment["detected_color"] != "multi"


def test_two_colorways_create_distinct_non_null_color_variants(db_session):
    product = Product(title="Yeezy 350", slug="yeezy-350", base_price=Decimal("1000"), visible=True)
    db_session.add(product)
    db_session.flush()

    def get_or_create_color(name: str) -> Color:
        row = db_session.query(Color).filter(Color.name == name).one_or_none()
        if row:
            return row
        row = Color(name=name)
        db_session.add(row)
        db_session.flush()
        return row

    rows = [
        {"token": "black", "images": ["/uploads/b1.jpg", "/uploads/b2.jpg"], "stock": 5},
        {"token": "white", "images": ["/uploads/w1.jpg", "/uploads/w2.jpg"], "stock": 7},
    ]

    for row in rows:
        color = get_or_create_color(row["token"])
        variant = ProductVariant(
            product_id=product.id,
            size_id=None,
            color_id=color.id,
            price=Decimal("1000"),
            stock_quantity=row["stock"],
            images=row["images"],
        )
        db_session.add(variant)

    db_session.commit()

    variants = db_session.query(ProductVariant).filter(ProductVariant.product_id == product.id).all()
    assert len(variants) >= 2
    assert all(v.color_id is not None for v in variants)
    assert len({v.color_id for v in variants}) >= 2


def test_build_color_assignment_allows_any_canonical_pair(monkeypatch):
    predictions = {
        "img1": {"color": "blue", "confidence": 0.9, "probs": {"blue": 0.9, "red": 0.45}},
        "img2": {"color": "blue", "confidence": 0.8, "probs": {"blue": 0.8, "red": 0.35}},
    }

    monkeypatch.setattr(asi, "predict_color_for_image_url", lambda url, kind: predictions[url])
    monkeypatch.setattr(asi, "_score_gallery_image", lambda url: 100.0)

    assignment = asi._build_color_assignment(
        title="Nike Air Max",
        supplier_key="any",
        src_url="https://supplier.example/item",
        item={"title": "Nike Air Max", "color": ""},
        image_urls=["img1", "img2"],
    )

    assert assignment["detected_color"] == "blue-red"
    assert assignment["color_tokens"] == ["blue-red"]


def test_build_color_assignment_falls_back_to_cv_aggregate_when_ml_empty(monkeypatch):
    monkeypatch.setattr(asi, "predict_color_for_image_url", lambda url, kind: {"color": "", "confidence": 0.0, "probs": {}})
    monkeypatch.setattr(asi, "detect_product_colors_from_photos", lambda urls, supplier_profile=None: {"color": "gray", "confidence": 0.63})
    monkeypatch.setattr(asi, "_score_gallery_image", lambda url: 100.0)

    assignment = asi._build_color_assignment(
        title="Nite Jogger",
        supplier_key="any",
        src_url="https://supplier.example/item",
        item={"title": "Nite Jogger", "color": ""},
        image_urls=["img1", "img2", "img3", "img4", "img5"],
    )

    assert assignment["detected_color"] == "gray"
    assert assignment["color_tokens"] == ["gray"]
    assert assignment["detected_color_debug"]["images_used"] >= 4


def test_build_color_assignment_falls_back_to_text_when_image_signals_absent(monkeypatch):
    monkeypatch.setattr(asi, "predict_color_for_image_url", lambda url, kind: {"color": "", "confidence": 0.0, "probs": {}})
    monkeypatch.setattr(asi, "detect_product_colors_from_photos", lambda urls, supplier_profile=None: {"color": "", "confidence": 0.0})
    monkeypatch.setattr(asi, "dominant_color_name_from_url", lambda url: "")
    monkeypatch.setattr(asi, "_score_gallery_image", lambda url: 100.0)

    assignment = asi._build_color_assignment(
        title="Nite Jogger",
        supplier_key="any",
        src_url="https://supplier.example/item",
        item={"title": "Nite Jogger", "description": "Кроссовки черный белый"},
        image_urls=["img1", "img2", "img3", "img4"],
    )

    assert assignment["detected_color"] == "black-white"
    assert assignment["color_tokens"] == ["black-white"]


def test_rerank_shop_vkus_does_not_collapse_gallery_below_four(monkeypatch):
    monkeypatch.setattr(asi, "_is_likely_product_image", lambda _u: False)
    monkeypatch.setattr(asi, "_filter_gallery_main_signature_cluster", lambda urls: urls[:1])

    urls = [f"https://cdn.example/{i}.jpg" for i in range(7)]
    out = asi._rerank_gallery_images(urls, supplier_key="shop_vkus")

    assert len(out) >= 4


def test_build_color_assignment_debug_contains_min_images_target(monkeypatch):
    monkeypatch.setattr(asi, "predict_color_for_image_url", lambda url, kind: {"color": "black", "confidence": 0.8, "probs": {"black": 0.8}})
    monkeypatch.setattr(asi, "_score_gallery_image", lambda url: 100.0)

    assignment = asi._build_color_assignment(
        title="Nike Air Max",
        supplier_key="any",
        src_url="https://supplier.example/item",
        item={"title": "Nike Air Max", "color": ""},
        image_urls=["img1", "img2", "img3", "img4", "img5"],
    )

    assert assignment["detected_color_debug"]["target_min_images"] == 4


def test_rerank_shop_vkus_drops_first_two_and_keeps_up_to_seven(monkeypatch):
    monkeypatch.setattr(asi, "_is_likely_product_image", lambda _u: True)
    monkeypatch.setattr(asi, "_score_gallery_image", lambda _u: 10.0)

    urls = [f"https://cdn.example/{i}.jpg" for i in range(10)]
    out = asi._rerank_gallery_images(urls, supplier_key="shop_vkus")

    assert all(u not in out for u in urls[:2])
    assert len(out) == 7
