from types import SimpleNamespace

from app.api.v1 import products as products_api
from app.api.v1.products import _build_color_payload
from app.services import color_detection


def _img(url: str, sort: int = 0, iid: int = 1):
    return SimpleNamespace(url=url, sort=sort, id=iid)


def _variant(vid: int, color: str, images: list[str]):
    clr = SimpleNamespace(name=color)
    return SimpleNamespace(id=vid, color=clr, images=images)


def test_color_payload_len5_forces_single_color_and_assigns_all_photos(monkeypatch):
    monkeypatch.setattr(
        products_api,
        "detect_product_colors_from_photos",
        lambda photos: {
            "color_keys": ["black/gray"],
            "photo_color_keys": ["black/gray"] * len(photos),
            "ordered_photos": photos,
        },
    )
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
    assert set(out["images_by_color"].keys()) == {"black/gray"}
    assert out["images_by_color"]["black/gray"] == [f"u{i}" for i in range(5)]


def test_color_payload_len8_uses_two_anchor_colors_without_third(monkeypatch):
    monkeypatch.setattr(
        products_api,
        "detect_product_colors_from_photos",
        lambda photos: {
            "color_keys": ["black/gray", "gray/beige"],
            "photo_color_keys": [
                "black/gray",
                "black/gray",
                "black/gray",
                "black/gray",
                "black/gray",
                "black/gray",
                "gray/beige",
                "gray/beige",
            ],
            "ordered_photos": photos,
        },
    )
    p = SimpleNamespace(
        detected_color="black/gray",
        images=[_img(f"u{i}", i, i) for i in range(8)],
        variants=[
            _variant(1, "black/gray", ["u0", "u1", "u2", "u3"]),
            _variant(2, "gray/beige", ["u4", "u5", "u6", "u7"]),
            _variant(3, "red", ["u3"]),
        ],
    )

    out = _build_color_payload(p)
    assert out["color_keys"] == ["black/gray", "gray/beige"]
    assert set(out["images_by_color"].keys()) == {"black/gray", "gray/beige"}
    assert out["images_by_color"]["black/gray"][:2] == ["u0", "u1"]
    assert out["images_by_color"]["gray/beige"][-2:] == ["u6", "u7"]


def test_detect_len5_suppresses_single_photo_noise(monkeypatch):
    colors = ["black", "black/gray", "black/gray", "gray", "beige"]

    def _fake(_src, timeout_sec=12):
        color = colors.pop(0)
        return color_detection.ImageColorResult(
            color=color,
            confidence=0.6,
            cluster_share=0.6,
            sat=0.4,
            light=0.4,
            lab_a=0.0,
            lab_b=0.0,
            coverage=0.5,
            zoom_flag=False,
            debug={},
        )

    monkeypatch.setattr(color_detection, "detect_color_from_image_source", _fake)
    out = color_detection.detect_product_colors_from_photos(["a", "b", "c", "d", "e"])
    assert out["color_keys"] == ["black/gray"]
    assert len(set(out["photo_color_keys"])) == 1



def test_color_payload_uses_unique_uploaded_photo_count_for_rules(monkeypatch):
    calls = {}

    def _fake_detect(photos):
        calls["photos"] = list(photos)
        return {
            "color_keys": ["black/gray"],
            "photo_color_keys": ["black/gray"] * len(photos),
            "ordered_photos": photos,
        }

    monkeypatch.setattr(products_api, "detect_product_colors_from_photos", _fake_detect)
    p = SimpleNamespace(
        detected_color="black/gray",
        images=[
            _img("u0", 0, 1),
            _img("u1", 1, 2),
            _img("u2", 2, 3),
            _img("u3", 3, 4),
            _img("u4", 4, 5),
            _img("u0", 5, 6),
            _img("u1", 6, 7),
        ],
        variants=[_variant(1, "black/gray", ["u0", "u1", "u2", "u3", "u4"])],
    )

    out = _build_color_payload(p)
    assert calls["photos"] == ["u0", "u1", "u2", "u3", "u4"]
    assert out["color_keys"] == ["black/gray"]
    assert out["images_by_color"]["black/gray"] == ["u0", "u1", "u2", "u3", "u4"]
