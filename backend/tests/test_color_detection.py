from PIL import Image

from app.services import color_detection as cd


def test_beige_vs_yellow_low_saturation_prefers_beige():
    color = cd.canonical_color_from_lab_hsv(l=72, a=4, b=16, h=0.14, s=0.18, v=0.82)
    assert color == "beige"


def test_yellow_requires_strong_saturation_and_lab_b():
    color = cd.canonical_color_from_lab_hsv(l=74, a=2, b=40, h=0.13, s=0.56, v=0.9)
    assert color == "yellow"


def test_white_vs_gray_split():
    assert cd.canonical_color_from_lab_hsv(l=92, a=0, b=1, h=0.0, s=0.03, v=0.96) == "white"
    assert cd.canonical_color_from_lab_hsv(l=67, a=0, b=1, h=0.0, s=0.03, v=0.72) == "gray"


def test_detect_product_color_for_5_images_forces_single(monkeypatch):
    class R:
        def __init__(self, color, conf, sat):
            self.color = color
            self.confidence = conf
            self.cluster_share = 0.6
            self.sat = sat
            self.light = 70
            self.lab_a = 1
            self.lab_b = 10
            self.debug = {}

    seq = [
        R("beige", 0.55, 0.2),
        R("yellow", 0.35, 0.18),
        R("beige", 0.50, 0.19),
        R("yellow", 0.30, 0.16),
        R("beige", 0.54, 0.21),
    ]

    def fake_detect(src):
        return seq.pop(0)

    monkeypatch.setattr(cd, "detect_color_from_image_source", fake_detect)
    out = cd.detect_product_color(["1", "2", "3", "4", "5"], supplier_profile="shop_vkus")
    assert out["color"] == "beige"
    assert out["debug"]["forced_single_for_5"] is True
    assert out["debug"]["palette_rule"] == "4_7_to_1"
    assert out["debug"]["palette_rule"] == "4_7_to_1"


def test_black_product_on_blue_background_is_not_blue(monkeypatch):
    img = Image.new("RGB", (220, 220), (30, 70, 150))
    for x in range(70, 150):
        for y in range(70, 150):
            img.putpixel((x, y), (15, 15, 15))

    monkeypatch.setattr(cd, "_download_or_open", lambda *_a, **_k: img)
    out = cd.detect_product_color(["mock://img"])
    assert out["color"] in {"black", "gray"}
    assert out["color"] != "blue"


def test_normalize_color_aliases_and_ru_display():
    assert cd.normalize_color_to_whitelist("grey") == "gray"
    assert cd.normalize_color_to_whitelist("серый") == "gray"
    assert cd.normalize_color_to_whitelist("red/white/black") == "black-white-red"
    assert cd.canonical_color_to_display_name("green") == "зеленый"


def test_detect_product_colors_from_photos_returns_canonical(monkeypatch):
    monkeypatch.setattr(cd, "detect_product_color", lambda *_a, **_k: {"color": "grey", "confidence": 0.81, "debug": {}, "per_image": []})
    out = cd.detect_product_colors_from_photos(["x"])
    assert out["color"] == "gray"
    assert out["display_color"] == "серый"


def test_detect_product_color_avoids_false_gray_for_black_white_mix(monkeypatch):
    class R:
        def __init__(self, color, conf=0.6):
            self.color = color
            self.confidence = conf
            self.cluster_share = 0.6
            self.sat = 0.18
            self.light = 62
            self.lab_a = 1
            self.lab_b = 1
            self.debug = {}

    seq = [
        R("gray", 0.62),
        R("black", 0.61),
        R("white", 0.59),
        R("black", 0.57),
        R("white", 0.55),
    ]

    def fake_detect(_src):
        return seq.pop(0)

    monkeypatch.setattr(cd, "detect_color_from_image_source", fake_detect)
    out = cd.detect_product_color(["1", "2", "3", "4", "5"], supplier_profile="shop_vkus")
    assert out["color"] == "black"
    assert out["color"] != "gray"


def test_detect_product_color_for_7_images_still_forces_single(monkeypatch):
    class R:
        def __init__(self, color, conf, sat):
            self.color = color
            self.confidence = conf
            self.cluster_share = 0.6
            self.sat = sat
            self.light = 70
            self.lab_a = 1
            self.lab_b = 10
            self.debug = {}

    seq = [
        R("gray", 0.62, 0.18),
        R("black", 0.61, 0.17),
        R("white", 0.59, 0.16),
        R("black", 0.57, 0.15),
        R("white", 0.55, 0.14),
        R("black", 0.56, 0.16),
        R("white", 0.53, 0.15),
    ]

    def fake_detect(_src):
        return seq.pop(0)

    monkeypatch.setattr(cd, "detect_color_from_image_source", fake_detect)
    out = cd.detect_product_color(["1", "2", "3", "4", "5", "6", "7"], supplier_profile="shop_vkus")
    assert out["color"] in {"black", "white", "purple", "gray", "beige", "yellow"}
    assert out["color"] not in {"multi", "black-white"}


def test_dark_neutral_prefers_black_over_gray():
    assert cd.canonical_color_from_lab_hsv(l=41, a=0, b=1, h=0.0, s=0.04, v=0.34) == "black"


def test_detect_product_color_for_10_images_forces_two_colors(monkeypatch):
    class R:
        def __init__(self, color, conf=0.65, share=0.66):
            self.color = color
            self.confidence = conf
            self.cluster_share = share
            self.sat = 0.2
            self.light = 68
            self.lab_a = 1
            self.lab_b = 1
            self.debug = {}

    seq = [
        R("white"), R("black"), R("white"), R("black"), R("white"),
        R("black"), R("white"), R("black"), R("gray", conf=0.3), R("gray", conf=0.28),
    ]

    monkeypatch.setattr(cd, "detect_color_from_image_source", lambda _src: seq.pop(0))
    out = cd.detect_product_color([str(i) for i in range(10)], supplier_profile="shop_vkus")
    assert out["color"] in {"black-white", "white-black"}
    assert out["debug"]["palette_rule"] == "10_14_to_2"


def test_detect_product_color_for_15_images_forces_three_colors(monkeypatch):
    class R:
        def __init__(self, color, conf=0.64, share=0.64):
            self.color = color
            self.confidence = conf
            self.cluster_share = share
            self.sat = 0.22
            self.light = 66
            self.lab_a = 1
            self.lab_b = 1
            self.debug = {}

    seq = [
        R("black"), R("white"), R("red"), R("black"), R("white"),
        R("red"), R("black"), R("white"), R("red"), R("black"),
        R("white"), R("red"), R("black"), R("white"), R("red"),
    ]

    monkeypatch.setattr(cd, "detect_color_from_image_source", lambda _src: seq.pop(0))
    out = cd.detect_product_color([str(i) for i in range(15)], supplier_profile="shop_vkus")
    assert out["color"] == "black-white-red"
    assert out["debug"]["palette_rule"] == "15_21_to_3"


def test_detect_product_color_photo_count_rules_not_global(monkeypatch):
    class R:
        def __init__(self, color, conf=0.65, share=0.66):
            self.color = color
            self.confidence = conf
            self.cluster_share = share
            self.sat = 0.2
            self.light = 68
            self.lab_a = 1
            self.lab_b = 1
            self.debug = {}

    seq = [
        R("white"), R("black"), R("white"), R("black"), R("white"),
        R("black"), R("white"), R("black"), R("gray", conf=0.3), R("gray", conf=0.28),
    ]

    monkeypatch.setattr(cd, "detect_color_from_image_source", lambda _src: seq.pop(0))
    out = cd.detect_product_color([str(i) for i in range(10)], supplier_profile="other_supplier")
    assert out["debug"]["palette_rule"] == "default"
    assert out["color"] not in {"black-white", "white-black"}


def test_detect_product_color_for_4_images_forces_single(monkeypatch):
    class R:
        def __init__(self, color, conf=0.6, sat=0.2):
            self.color = color
            self.confidence = conf
            self.cluster_share = 0.6
            self.sat = sat
            self.light = 70
            self.lab_a = 1
            self.lab_b = 8
            self.debug = {}

    seq = [R("gray",0.55), R("black",0.62), R("gray",0.56), R("black",0.61)]
    monkeypatch.setattr(cd, "detect_color_from_image_source", lambda _src: seq.pop(0))
    out = cd.detect_product_color(["1", "2", "3", "4"], supplier_profile="shop_vkus")
    assert out["color"] in {"black", "gray"}
    assert out["debug"]["palette_rule"] == "4_7_to_1"


def test_light_low_saturation_blue_prefers_sky_blue():
    assert cd.canonical_color_from_lab_hsv(l=68, a=-4, b=-8, h=0.58, s=0.11, v=0.62) == "sky_blue"


def test_dark_neutral_boundary_prefers_black_not_gray():
    assert cd.canonical_color_from_lab_hsv(l=45, a=0, b=1, h=0.0, s=0.05, v=0.40) == "black"
