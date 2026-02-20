from app.services.color_detection import canonical_color_from_lab_hsv


def test_green_hsv_maps_to_green():
    assert canonical_color_from_lab_hsv(l=56, a=-25, b=20, h=0.33, s=0.62, v=0.70) == "green"
