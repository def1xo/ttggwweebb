from decimal import Decimal

from app.api.v1.categories import list_categories
from app.db import models


def test_categories_search_matches_product_title_but_returns_only_categories(tmp_db):
    cat_shoes = models.Category(name="Обувь", slug="obuv")
    cat_hoodies = models.Category(name="Худи", slug="hudi")
    tmp_db.add_all([cat_shoes, cat_hoodies])
    tmp_db.flush()

    tmp_db.add_all(
        [
            models.Product(
                title="Nike Dunk Low Panda",
                slug="nike-dunk-low-panda",
                base_price=Decimal("5000"),
                category_id=cat_shoes.id,
                visible=True,
            ),
            models.Product(
                title="Basic Black Hoodie",
                slug="basic-black-hoodie",
                base_price=Decimal("3500"),
                category_id=cat_hoodies.id,
                visible=True,
            ),
        ]
    )
    tmp_db.commit()

    out = list_categories(q="dunk", db=tmp_db)

    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["name"] == "Обувь"
    assert "title" not in out[0]


def test_categories_search_by_category_name_still_works(tmp_db):
    cat = models.Category(name="Аксессуары", slug="aksessuary")
    tmp_db.add(cat)
    tmp_db.commit()

    out = list_categories(q="aksess", db=tmp_db)

    assert len(out) == 1
    assert out[0]["slug"] == "aksessuary"
