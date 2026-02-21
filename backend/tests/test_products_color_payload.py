from types import SimpleNamespace

from app.api.v1.products import _build_color_payload


def _img(url: str, sort: int = 0, iid: int = 1):
    return SimpleNamespace(url=url, sort=sort, id=iid)


def _variant(vid: int, color: str, images: list[str]):
    clr = SimpleNamespace(name=color)
    return SimpleNamespace(id=vid, color=clr, images=images)


def test_color_payload_keeps_photo_grouping_and_sets_single_color_key_for_5_photos():
    p = SimpleNamespace(
        detected_color="black/gray",
        images=[_img(f"u{i}", i, i) for i in range(5)],
        variants=[
            _variant(1, "black/gray", ["u0", "u1", "u2"]),
            _variant(2, "gray/beige", ["u3", "u4"]),
        ],
    )

    out = _build_color_payload(p)
    assert out["color_keys"] == ["black/gray"]
    assert set(out["images_by_color"].keys()) == {"black/gray", "gray/beige"}
    assert out["images_by_color"]["gray/beige"] == ["u3", "u4"]
