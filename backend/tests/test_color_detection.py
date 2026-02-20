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
