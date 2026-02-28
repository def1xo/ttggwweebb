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
    assert len(assignment["color_tokens"]) == 1


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
        variant = (
            db_session.query(ProductVariant)
            .filter(ProductVariant.product_id == product.id)
            .filter(ProductVariant.size_id.is_(None))
            .filter(ProductVariant.color_id == color.id)
            .one_or_none()
        )
        if variant is None:
            variant = ProductVariant(
                product_id=product.id,
                size_id=None,
                color_id=color.id,
                price=Decimal("1000"),
                stock_quantity=row["stock"],
                images=row["images"],
            )
            db_session.add(variant)
        else:
            variant.stock_quantity = row["stock"]
            variant.images = row["images"]
            db_session.add(variant)

    db_session.commit()

    variants = db_session.query(ProductVariant).filter(ProductVariant.product_id == product.id).all()
    assert len(variants) >= 2
    assert all(v.color_id is not None for v in variants)
    assert len({v.color_id for v in variants}) >= 2
    by_color = {v.color_id: v for v in variants}
    assert any("/uploads/b1.jpg" in (v.images or []) for v in by_color.values())
    assert any("/uploads/w1.jpg" in (v.images or []) for v in by_color.values())
