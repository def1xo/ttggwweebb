from types import SimpleNamespace

from app.api.v1.products import _build_color_payload
from app.services.color_detection import normalize_color_key, normalize_combo_color_key


def _img(url: str, sort: int = 0, iid: int = 1):
    return SimpleNamespace(url=url, sort=sort, id=iid)


def _variant(vid: int, color: str, images: list[str]):
    clr = SimpleNamespace(name=color)
    return SimpleNamespace(id=vid, color=clr, images=images)


def test_normalize_color_key_and_combo():
    assert normalize_color_key("чёрный") == "black"
    assert normalize_color_key("графит") == "gray"
    assert normalize_combo_color_key(["white", "black"]) == "black-white"
    assert normalize_combo_color_key(["red", "black", "white"]) == "black-white"


def test_color_payload_uses_canonical_keys_and_images_by_key():
    p = SimpleNamespace(
        detected_color="white-black",
        import_media_meta={"images_by_color_key": {"white-black": ["u0", "u1"]}, "general_images": ["g0"]},
        images=[_img("u0", 0, 1), _img("u1", 1, 2), _img("u2", 2, 3)],
        variants=[_variant(1, "чёрный/белый", ["u0", "u1"]), _variant(2, "красный", ["u2"])],
    )

    out = _build_color_payload(p)
    assert "black-white" in out["available_color_keys"]
    assert out["selected_color_key"] in out["available_color_keys"]
    assert out["images_by_color_key"]["black-white"] == ["u0", "u1"]
    assert out["color_key_to_display"]["black-white"].lower().startswith("чер")


def test_color_payload_fallback_to_general_images_then_first_color():
    p = SimpleNamespace(
        detected_color="blue",
        import_media_meta={"images_by_color_key": {"black": ["b0"]}, "general_images": ["g0", "g1"]},
        images=[_img("p0", 0, 1)],
        variants=[_variant(1, "black", [])],
    )

    out = _build_color_payload(p)
    assert out["selected_color_images"] == ["b0"]
