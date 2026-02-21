from __future__ import annotations

import colorsys
import io
import math
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from PIL import Image

logger = logging.getLogger("color_detection")

CANONICAL_COLORS: tuple[str, ...] = (
    "black", "white", "gray", "beige", "brown", "yellow", "orange",
    "red", "pink", "purple", "blue", "green", "multicolor",
)

COLOR_PRIORITY: tuple[str, ...] = (
    "black", "white", "gray", "beige", "brown", "yellow", "orange",
    "red", "pink", "purple", "blue", "green", "multicolor",
)


@dataclass
class ImageColorResult:
    color: str
    confidence: float
    cluster_share: float
    sat: float
    light: float
    lab_a: float
    lab_b: float
    debug: Dict[str, Any]


def _lab_distance(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def normalize_color_label(color: str | None) -> str:
    src = str(color or "").strip().lower()
    if not src:
        return ""
    for sep in (",", ";", "|", "\\", " и ", " & ", "-"):
        src = src.replace(sep, "/")
    src = "/".join(part.strip() for part in src.split("/") if part.strip())
    if not src:
        return ""
    out: list[str] = []
    seen: set[str] = set()
    for token in src.split("/"):
        if token not in CANONICAL_COLORS:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    if not out:
        return ""
    out = sorted(out, key=lambda x: COLOR_PRIORITY.index(x) if x in COLOR_PRIORITY else 999)[:2]
    return "/".join(out)


def _rgb_to_lab(rgb: Tuple[int, int, int]) -> Tuple[float, float, float]:
    def _pivot_rgb(v: float) -> float:
        v = v / 255.0
        return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92

    r, g, b = (_pivot_rgb(float(rgb[0])), _pivot_rgb(float(rgb[1])), _pivot_rgb(float(rgb[2])))
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505

    xr, yr, zr = x / 0.95047, y / 1.0, z / 1.08883

    def _pivot_xyz(v: float) -> float:
        return v ** (1 / 3) if v > 0.008856 else (7.787 * v) + (16 / 116)

    fx, fy, fz = _pivot_xyz(xr), _pivot_xyz(yr), _pivot_xyz(zr)
    l = (116 * fy) - 16
    a = 500 * (fx - fy)
    b2 = 200 * (fy - fz)
    return (l, a, b2)


def _download_or_open(source: str, timeout_sec: int = 12) -> Optional[Image.Image]:
    if not source:
        return None
    try:
        if source.lower().startswith(("http://", "https://")):
            r = requests.get(source, timeout=timeout_sec, headers={"User-Agent": "ColorDetection/1.0"})
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGB")
        return Image.open(source).convert("RGB")
    except Exception:
        return None


def _extract_subject_pixels(img: Image.Image) -> List[Tuple[int, int, int]]:
    w, h = img.size
    if w < 8 or h < 8:
        return []
    img = img.resize((220, 220))
    px = img.load()

    bw = max(10, int(220 * 0.10))
    edge_pixels: List[Tuple[int, int, int]] = []
    for y in range(220):
        for x in range(220):
            if x < bw or x >= 220 - bw or y < bw or y >= 220 - bw:
                edge_pixels.append(px[x, y])

    bg_clusters: List[Tuple[float, float, float]] = []
    if edge_pixels:
        edge_labs = [_rgb_to_lab(p) for p in edge_pixels[::3]]
        for c in _kmeans(edge_labs, k=2):
            bg_clusters.append(tuple(c["center"]))

    x0, x1 = 24, 196
    y0, y1 = 24, 196
    pixels: List[Tuple[int, int, int]] = []
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            r, g, b = px[x, y]
            lab = _rgb_to_lab((r, g, b))

            if bg_clusters:
                bg_dist = min(_lab_distance(lab, bg) for bg in bg_clusters)
                if bg_dist <= 8.5:
                    continue

            h1, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            center_dist = math.dist((x, y), (110, 110)) / 110.0
            center_weight = max(0.30, 1.0 - (center_dist ** 1.35))
            edge_strength = 0.0
            if 1 <= x < 219 and 1 <= y < 219:
                r2, g2, b2 = px[x + 1, y]
                r3, g3, b3 = px[x, y + 1]
                edge_strength = min(1.0, (abs(r - r2) + abs(g - g2) + abs(b - b2) + abs(r - r3) + abs(g - g3) + abs(b - b3)) / 180.0)

            keep_score = center_weight * 0.72 + edge_strength * 0.28
            if s >= 0.18:
                keep_score += 0.08
            if keep_score < 0.36:
                continue
            pixels.append((r, g, b))

    if len(pixels) > 2200:
        step = max(1, len(pixels) // 2200)
        pixels = pixels[::step]
    return pixels


def _kmeans(points: Sequence[Tuple[float, float, float]], k: int = 3, max_iter: int = 12) -> List[Dict[str, Any]]:
    if not points:
        return []
    uniq = list(dict.fromkeys(points))
    if len(uniq) <= 1:
        return [{"center": uniq[0], "count": len(points)}]
    k = max(1, min(k, len(uniq), 5))
    step = max(1, len(uniq) // k)
    centers = [tuple(map(float, uniq[i * step])) for i in range(k)]

    for _ in range(max_iter):
        groups: List[List[Tuple[float, float, float]]] = [[] for _ in range(k)]
        for p in points:
            idx = min(range(k), key=lambda i: (p[0] - centers[i][0]) ** 2 + (p[1] - centers[i][1]) ** 2 + (p[2] - centers[i][2]) ** 2)
            groups[idx].append(p)
        new_centers = []
        for i, g in enumerate(groups):
            if not g:
                new_centers.append(centers[i])
                continue
            ln = float(len(g))
            new_centers.append((sum(x for x, _, _ in g) / ln, sum(y for _, y, _ in g) / ln, sum(z for _, _, z in g) / ln))
        if all(math.dist(centers[i], new_centers[i]) < 1.0 for i in range(k)):
            centers = new_centers
            break
        centers = new_centers

    out = []
    for i in range(k):
        count = sum(1 for p in points if min(range(k), key=lambda j: (p[0] - centers[j][0]) ** 2 + (p[1] - centers[j][1]) ** 2 + (p[2] - centers[j][2]) ** 2) == i)
        if count > 0:
            out.append({"center": centers[i], "count": count})
    out.sort(key=lambda x: x["count"], reverse=True)
    return out


def canonical_color_from_lab_hsv(l: float, a: float, b: float, h: float, s: float, v: float) -> str:
    sat_low = s < 0.14
    sat_very_low = s < 0.08
    warm = b > 8 and a > -2

    if sat_very_low:
        if l >= 88:
            return "white"
        if l <= 28:
            return "black"
        if warm and l >= 62 and b >= 10:
            return "beige"
        if warm and l < 62:
            return "brown"
        return "gray"

    if sat_low:
        if warm and 58 <= l <= 88 and 8 <= b <= 26:
            return "beige"
        if warm and l < 58:
            return "brown"

    # hysteresis buffer: yellow hue with low sat goes beige
    if (0.10 <= h <= 0.18) and s < 0.28 and b < 28 and l > 55:
        return "beige"

    if b >= 34 and s >= 0.28 and (0.10 <= h <= 0.18):
        return "yellow"
    if 0.05 <= h < 0.10 and s >= 0.22:
        return "orange"
    if h >= 0.92 or h < 0.05:
        return "red"
    if 0.78 <= h < 0.92:
        return "pink" if l > 55 else "purple"
    if 0.66 <= h < 0.78:
        return "purple"
    if 0.52 <= h < 0.66:
        return "blue"
    if 0.24 <= h < 0.52:
        return "green"
    if warm:
        return "beige" if l >= 58 else "brown"
    return "gray"


def detect_color_from_image_source(source: str, timeout_sec: int = 12) -> Optional[ImageColorResult]:
    img = _download_or_open(source, timeout_sec=timeout_sec)
    if img is None:
        return None
    pixels = _extract_subject_pixels(img)
    if not pixels:
        return None

    lab_points = [_rgb_to_lab(p) for p in pixels]
    clusters = _kmeans(lab_points, k=4)
    if not clusters:
        return None

    total = max(1, sum(int(c["count"]) for c in clusters))
    main = clusters[0]
    l, a, b = main["center"]

    # HSV from Lab center approximation via nearest original pixel
    rr2, gg2, bb2 = min(pixels, key=lambda p: ( _rgb_to_lab(p)[0] - l) ** 2 + (_rgb_to_lab(p)[1] - a) ** 2 + (_rgb_to_lab(p)[2] - b) ** 2)
    h, s, v = colorsys.rgb_to_hsv(rr2 / 255.0, gg2 / 255.0, bb2 / 255.0)

    color = canonical_color_from_lab_hsv(l, a, b, h, s, v)
    share = float(main["count"]) / float(total)
    confidence = max(0.05, min(0.99, share * (0.65 + min(0.35, s))))
    top2: list[tuple[str, float]] = [(color, share)]

    if len(clusters) > 1:
        second = clusters[1]
        second_share = float(second["count"]) / float(total)
        l2, a2, b2 = second["center"]
        rr3, gg3, bb3 = min(pixels, key=lambda p: (_rgb_to_lab(p)[0] - l2) ** 2 + (_rgb_to_lab(p)[1] - a2) ** 2 + (_rgb_to_lab(p)[2] - b2) ** 2)
        h2, s2, v2 = colorsys.rgb_to_hsv(rr3 / 255.0, gg3 / 255.0, bb3 / 255.0)
        c2 = canonical_color_from_lab_hsv(l2, a2, b2, h2, s2, v2)
        top2.append((c2, second_share))
        if c2 != color:
            if {color, c2} == {"black", "white"} and (share + second_share) >= 0.65:
                color = "black/white"
                confidence = max(confidence, min(0.94, 0.62 + (share + second_share) * 0.28))
            elif share >= 0.30 and second_share >= 0.25:
                color = normalize_color_label(f"{color}/{c2}") or color
                confidence = max(confidence, min(0.93, 0.56 + (share + second_share) * 0.22))

    color = normalize_color_label(color) or color

    return ImageColorResult(
        color=color,
        confidence=confidence,
        cluster_share=share,
        sat=s,
        light=l,
        lab_a=a,
        lab_b=b,
        debug={
            "clusters": [{"center": [round(x, 2) for x in c["center"]], "count": int(c["count"])} for c in clusters],
            "top2": [{"color": c, "share": round(sv, 3)} for c, sv in top2],
        },
    )


def _compose_top_colors(score: Dict[str, float], total_score: float) -> str | None:
    if not score:
        return None
    top = sorted(score.items(), key=lambda x: x[1], reverse=True)
    c1, s1 = top[0]
    if len(top) == 1:
        return normalize_color_label(c1) or c1
    c2, s2 = top[1]
    share1 = s1 / max(0.001, total_score)
    share2 = s2 / max(0.001, total_score)
    if c1 != c2 and share1 >= 0.30 and share2 >= 0.25:
        if {c1, c2} == {"black", "white"}:
            return "black/white"
        if {c1, c2} <= {"beige", "yellow", "brown"}:
            return normalize_color_label(c1) or c1
        return normalize_color_label(f"{c1}/{c2}") or c1
    return normalize_color_label(c1) or c1


def detect_product_color(image_sources: Sequence[str]) -> Dict[str, Any]:
    valid = [str(x).strip() for x in (image_sources or []) if str(x or "").strip()]
    votes: List[ImageColorResult] = []
    for src in valid:
        res = detect_color_from_image_source(src)
        if res:
            votes.append(res)

    if not votes:
        return {"color": None, "confidence": 0.0, "debug": {"reason": "no_votes"}, "per_image": []}

    score: Dict[str, float] = defaultdict(float)
    by_color: Dict[str, int] = defaultdict(int)
    per_image: List[Dict[str, Any]] = []
    for idx, v in enumerate(votes):
        w = max(0.05, float(v.confidence))
        score[v.color] += w
        by_color[v.color] += 1
        per_image.append({"idx": idx, "color": v.color, "confidence": round(v.confidence, 3), "share": round(v.cluster_share, 3)})

    # 5 photos rule: force one stable result (single color or a composite pair)
    if len(valid) == 5:
        c1 = _compose_top_colors(score, sum(score.values()))
        top = sorted(score.items(), key=lambda x: x[1], reverse=True)
        s1 = top[0][1] if top else 0.0
        return {
            "color": c1,
            "confidence": round(min(0.99, s1 / max(0.001, sum(score.values())) + 0.15), 3),
            "debug": {"votes": dict(by_color), "scores": {k: round(v, 3) for k, v in score.items()}, "forced_single_for_5": True},
            "per_image": per_image,
        }

    top = sorted(score.items(), key=lambda x: x[1], reverse=True)
    color = _compose_top_colors(score, sum(score.values())) or top[0][0]
    conf = top[0][1] / max(0.001, sum(score.values()))

    return {
        "color": color,
        "confidence": round(min(0.99, conf), 3),
        "debug": {"votes": dict(by_color), "scores": {k: round(v, 3) for k, v in score.items()}, "forced_single_for_5": False},
        "per_image": per_image,
    }
