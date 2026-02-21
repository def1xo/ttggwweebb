from PIL import Image, ImageDraw

from app.services import color_detection as cd


def test_beige_vs_yellow_low_saturation_prefers_beige():
    # low sat + warm Lab should remain beige even in yellow-ish hue window
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
    out = cd.detect_product_color(["1", "2", "3", "4", "5"])
    assert out["color"] == "beige"
    assert out["debug"]["forced_single_for_5"] is True


def test_extract_subject_pixels_keeps_black_and_white_subject():
    img = Image.new("RGB", (220, 220), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((40, 70, 180, 150), fill="black")
    pixels = cd._extract_subject_pixels(img)
    assert len(pixels) > 100


def test_detect_color_from_image_red_object_white_background(tmp_path):
    img = Image.new("RGB", (360, 360), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((90, 90, 270, 270), fill=(212, 30, 28))
    p = tmp_path / "red_center.png"
    img.save(p)
    out = cd.detect_color_from_image_source(str(p))
    assert out is not None
    assert out.color == "red"


def test_detect_product_color_black_white_composite(monkeypatch):
    class R:
        def __init__(self, color, conf, sat=0.1):
            self.color = color
            self.confidence = conf
            self.cluster_share = 0.58
            self.sat = sat
            self.light = 64
            self.lab_a = 0
            self.lab_b = 0
            self.debug = {}

    seq = [R("black", 0.64), R("white", 0.62), R("black", 0.65), R("white", 0.63), R("black", 0.60)]
    monkeypatch.setattr(cd, "detect_color_from_image_source", lambda _src: seq.pop(0))
    out = cd.detect_product_color(["1", "2", "3", "4", "5"])
    assert out["color"] == "black/white"
    assert out["color"] != "multicolor"
    assert out["color"] is not None


def test_normalize_color_label_deduplicates_and_limits_parts():
    assert cd.normalize_color_label("White / black / black") == "black/white"


def test_normalize_color_label_maps_ru_and_aliases():
    assert cd.normalize_color_label("фиолетовый") == "purple"
    assert cd.normalize_color_label("grey/purple") == "gray/purple"


def test_detect_color_from_image_green_object_white_background(tmp_path):
    img = Image.new("RGB", (360, 360), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((90, 90, 270, 270), fill=(25, 165, 55))
    p = tmp_path / "green_center.png"
    img.save(p)
    out = cd.detect_color_from_image_source(str(p))
    assert out is not None
    assert out.color == "green"


def test_detect_color_from_image_black_white_object(tmp_path):
    img = Image.new("RGB", (360, 360), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((80, 100, 170, 280), fill=(12, 12, 12))
    d.rectangle((190, 100, 280, 280), fill=(245, 245, 245))
    p = tmp_path / "bw_center.png"
    img.save(p)
    out = cd.detect_color_from_image_source(str(p))
    assert out is not None
    assert out.color == "black/white"


def test_detect_product_color_prefers_purple_over_gray_noise(monkeypatch):
    class R:
        def __init__(self, color, conf):
            self.color = color
            self.confidence = conf
            self.cluster_share = 0.55
            self.sat = 0.3
            self.light = 60
            self.lab_a = 20
            self.lab_b = -25
            self.debug = {}

    seq = [R("purple", 0.62), R("purple", 0.66), R("gray", 0.25), R("purple", 0.64), R("gray", 0.20)]
    monkeypatch.setattr(cd, "detect_color_from_image_source", lambda _src: seq.pop(0))
    out = cd.detect_product_color(["1", "2", "3", "4", "5"])
    assert out["color"] == "purple"
