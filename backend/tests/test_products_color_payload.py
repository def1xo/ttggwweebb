from types import SimpleNamespace

from app.api.v1.products import _build_color_payload


def _variant(color: str, images: list[str]):
    return SimpleNamespace(id=1, color=SimpleNamespace(name=color), images=images)


def test_five_images_one_colorset_consolidates_to_single_color():
    p = SimpleNamespace(
        variants=[
            _variant("green", [f"/img/{i}.jpg" for i in range(5)]),
            _variant("olive", [f"/img/{i}.jpg" for i in range(5)]),
        ],
        images=[SimpleNamespace(url=f"/img/{i}.jpg", sort=i, id=i) for i in range(5)],
        detected_color=None,
    )
    payload = _build_color_payload(p)
    assert len(payload["available_colors"]) == 1


def test_two_source_colors_kept_when_different_photosets():
    p = SimpleNamespace(
        variants=[
            _variant("green", ["/g1.jpg", "/g2.jpg"]),
            _variant("red", ["/r1.jpg", "/r2.jpg"]),
        ],
        images=[SimpleNamespace(url="/g1.jpg", sort=0, id=1), SimpleNamespace(url="/r1.jpg", sort=1, id=2)],
        detected_color=None,
    )
    payload = _build_color_payload(p)
    assert sorted(payload["available_colors"]) == ["green", "red"]
