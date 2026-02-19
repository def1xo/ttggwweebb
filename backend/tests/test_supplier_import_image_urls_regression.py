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
