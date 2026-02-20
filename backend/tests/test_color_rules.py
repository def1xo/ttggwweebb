from app.services import color_detection as cd


def test_grinch_green_hsv_maps_to_green():
    got = cd.canonical_color_from_lab_hsv(l=55, a=-35, b=28, h=0.33, s=0.72, v=0.74)
    assert got == "green"


def test_five_photos_forces_single_color(monkeypatch):
    votes = [
        cd.ImageColorResult(color="green", confidence=0.7, cluster_share=0.6, sat=0.6, light=54, lab_a=-20, lab_b=16, debug={}),
        cd.ImageColorResult(color="green", confidence=0.68, cluster_share=0.58, sat=0.58, light=53, lab_a=-18, lab_b=14, debug={}),
        cd.ImageColorResult(color="green", confidence=0.66, cluster_share=0.57, sat=0.57, light=55, lab_a=-17, lab_b=13, debug={}),
        cd.ImageColorResult(color="gray", confidence=0.41, cluster_share=0.45, sat=0.11, light=62, lab_a=1, lab_b=1, debug={}),
        cd.ImageColorResult(color="gray", confidence=0.38, cluster_share=0.42, sat=0.1, light=64, lab_a=1, lab_b=1, debug={}),
    ]
    it = iter(votes)
    monkeypatch.setattr(cd, "detect_color_from_image_source", lambda *_a, **_k: next(it))
    data = cd.detect_product_color(["u1", "u2", "u3", "u4", "u5"])
    assert data["color"] == "green"
