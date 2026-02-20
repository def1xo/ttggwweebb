from types import SimpleNamespace

from app.api.v1.products import _build_color_payload


def _variant(vid: int, color: str, images: list[str]):
    return SimpleNamespace(
        id=vid,
        color=SimpleNamespace(name=color),
        images=images,
    )


def test_single_photoset_consolidates_to_one_color():
    p = SimpleNamespace(
        variants=[
            _variant(1, "green", ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg"]),
            _variant(2, "gray", ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg"]),
        ],
        images=[],
        detected_color="green",
        import_media_meta={},
    )
    payload = _build_color_payload(p)
    assert len(payload["colors"]) <= 1


def test_two_source_colors_are_preserved():
    p = SimpleNamespace(
        variants=[
            _variant(1, "green", ["g1.jpg", "g2.jpg"]),
            _variant(2, "black", ["b1.jpg", "b2.jpg"]),
        ],
        images=[],
        detected_color=None,
        import_media_meta={"colors_from_source_list": ["green", "black"]},
    )
    payload = _build_color_payload(p)
    assert sorted(payload["colors"]) == ["black", "green"]
