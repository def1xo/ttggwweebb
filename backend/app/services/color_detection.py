from __future__ import annotations

import colorsys
import io
import math
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from PIL import Image

logger = logging.getLogger("color_detection")


_COLOR_ALIASES: Dict[str, str] = {
    "grey": "gray",
    "серый": "gray",
    "сер": "gray",
    "чёрный": "black",
    "черный": "black",
    "белый": "white",
    "white_single": "white",
    "зелёный": "green",
    "зеленый": "green",
    "синий": "blue",
    "голубой": "sky_blue",
    "бежевый": "beige",
    "коричневый": "brown",
    "красный": "red",
    "розовый": "pink",
    "black_single": "black",
    "gray_single": "gray",
    "grey_single": "gray",
    "графит": "gray",
    "молочный": "white",
    "молоко": "white",
    "айвори": "white",
}

_CANONICAL_TO_RU: Dict[str, str] = {
    "black": "черный", "white": "белый", "gray": "серый", "beige": "бежевый",
    "brown": "коричневый", "blue": "синий", "red": "красный", "green": "зеленый",
    "yellow": "желтый", "orange": "оранжевый", "purple": "фиолетовый", "pink": "розовый",
    "off_white": "молочный", "cream": "кремовый", "olive": "оливковый", "mint": "мятный",
}

CANONICAL_COLORS: tuple[str, ...] = (
    "black", "white", "gray", "beige", "brown", "blue", "navy", "sky_blue", "green", "olive", "lime",
    "yellow", "orange", "red", "burgundy", "pink", "purple", "lavender", "khaki", "cream", "silver",
    "gold", "multi",
)

_COLOR_PRIORITY: tuple[str, ...] = (
    "black", "white", "gray", "beige", "brown", "blue", "navy", "sky_blue", "green", "olive", "lime",
    "yellow", "orange", "red", "burgundy", "pink", "purple", "lavender", "khaki", "cream", "silver", "gold", "multi",
)


def _allowed_combo_pairs() -> set[tuple[str, str]]:
    raw = os.getenv("COLOR_ALLOWED_PAIRS", "black-white")
    out: set[tuple[str, str]] = set()
    for token in str(raw or "").split(","):
        parts = [normalize_color_key(x) for x in re.split(r"[-/|;]+", token.strip()) if normalize_color_key(x)]
        if len(parts) != 2 or "multi" in parts:
            continue
        a, b = parts[0], parts[1]
        if a == b:
            continue
        out.add(tuple(sorted((a, b))))
    if not out:
        out.add(("black", "white"))
    return out


def normalize_color_key(raw: Optional[str]) -> str:
    txt = str(raw or "").strip().lower()
    if not txt:
        return ""
    txt = txt.replace("ё", "е")
    txt = re.sub(r"[()\[\]{}]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip().replace(" ", "_")
    txt = re.sub(r"_single$", "", txt)
    txt = _COLOR_ALIASES.get(txt, txt)
    return txt if txt in CANONICAL_COLORS else ""


def normalize_combo_color_key(keys: Sequence[str]) -> str:
    normalized: list[str] = []
    for k in (keys or []):
        nk = normalize_color_key(k)
        if not nk or nk == "multi" or nk in normalized:
            continue
        normalized.append(nk)
    if not normalized:
        return ""

    order = {c: i for i, c in enumerate(_COLOR_PRIORITY)}
    normalized.sort(key=lambda x: order.get(x, 999))
    primary = normalized[0]
    if len(normalized) == 1:
        return primary

    secondary = normalized[1]
    pair = tuple(sorted((primary, secondary)))
    if pair in _allowed_combo_pairs():
        return f"{primary}-{secondary}"
    return primary


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

    x0, x1 = 52, 168
    y0, y1 = 52, 168
    pixels: List[Tuple[int, int, int]] = []
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            r, g, b = px[x, y]
            h1, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            if v > 0.95 and s < 0.10:
                continue
            if v < 0.03:
                continue
            # keep more saturated/contrasty pixels, but allow warm neutrals and dark neutral product zones
            if s < 0.06 and v > 0.25 and not (r > g >= b and (r - b) > 8):
                continue
            pixels.append((r, g, b))
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
        if l >= 90:
            return "white"
        if l <= 46:
            return "black"
        if 0.52 <= h < 0.66 and l >= 62 and v >= 0.56:
            return "sky_blue"
        if warm and l >= 62 and b >= 10:
            return "beige"
        if warm and l < 62:
            return "brown"
        # low-saturation dark regions should not drift to blue
        return "gray"

    if sat_low:
        if 0.52 <= h < 0.66 and l >= 60 and v >= 0.54:
            return "sky_blue"
        if warm and 58 <= l <= 88 and 8 <= b <= 26:
            return "beige"
        if warm and l < 58:
            return "brown"
        if l < 56 and v < 0.50:
            return "black"

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
        # anti false-blue: dark/neutral regions must stay neutral
        if s < 0.22 or l < 42 or v < 0.35:
            return "black" if (l < 32 or v < 0.24) else "gray"
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

    # anti false-blue: if a strong dark neutral cluster exists, prefer black/gray over blue.
    if color == "blue" and len(clusters) > 1:
        for cl in clusters[1:]:
            l2, a2, b2 = cl["center"]
            rr3, gg3, bb3 = min(pixels, key=lambda p: (_rgb_to_lab(p)[0] - l2) ** 2 + (_rgb_to_lab(p)[1] - a2) ** 2 + (_rgb_to_lab(p)[2] - b2) ** 2)
            _h2, s2, v2 = colorsys.rgb_to_hsv(rr3 / 255.0, gg3 / 255.0, bb3 / 255.0)
            neutral_like = s2 < 0.16 and (v2 < 0.30 or l2 < 40)
            if neutral_like and float(cl.get("count") or 0) / float(total) >= 0.25:
                color = "black" if (v2 < 0.24 or l2 < 32) else "gray"
                break

    secondary_candidate: Optional[dict[str, Any]] = None
    if len(clusters) > 1:
        second = clusters[1]
        second_share = float(second["count"]) / float(total)
        l2, a2, b2 = second["center"]
        rr3, gg3, bb3 = min(pixels, key=lambda p: (_rgb_to_lab(p)[0] - l2) ** 2 + (_rgb_to_lab(p)[1] - a2) ** 2 + (_rgb_to_lab(p)[2] - b2) ** 2)
        h2, s2, v2 = colorsys.rgb_to_hsv(rr3 / 255.0, gg3 / 255.0, bb3 / 255.0)
        c2 = canonical_color_from_lab_hsv(l2, a2, b2, h2, s2, v2)
        # NOTE: never return generic "multi" at per-image level; keep primary color,
        # but record a secondary candidate for the aggregator/debug UI.
        if c2 != color and share <= 0.68 and second_share >= 0.32 and confidence >= 0.45:
            secondary_candidate = {
                "color": c2,
                "share": round(second_share, 3),
                "sat": round(float(s2), 3),
                "light": round(float(l2), 2),
            }

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
            **({"secondary": secondary_candidate} if secondary_candidate else {}),
        },
    )


def _weighted_color_score(v: ImageColorResult) -> float:
    # Prefer the dominant sneaker body color over tiny accent details.
    share_boost = 0.65 + max(0.0, min(0.35, float(v.cluster_share)))
    sat_penalty = 1.0
    if v.sat > 0.62 and v.cluster_share < 0.50:
        sat_penalty = 0.88
    return max(0.05, float(v.confidence)) * share_boost * sat_penalty


def _compose_palette_color(top: List[tuple[str, float]], total_score: float, target_count: int) -> str:
    usable = [(c, s) for c, s in top if c not in {"none", "multi"}]
    if not usable:
        return "none"

    chosen: List[str] = []
    for c, s in usable:
        share = s / max(0.001, total_score)
        if share < 0.12 and chosen:
            continue
        if c not in chosen:
            chosen.append(c)
        if len(chosen) >= target_count:
            break

    if not chosen:
        chosen = [usable[0][0]]

    if target_count <= 1 or len(chosen) == 1:
        return chosen[0]
    return normalize_combo_color_key(chosen[:2])


def detect_product_color(image_sources: Sequence[str], supplier_profile: Optional[str] = None) -> Dict[str, Any]:
    valid = [str(x).strip() for x in (image_sources or []) if str(x or "").strip()]
    votes: List[ImageColorResult] = []
    for src in valid:
        res = detect_color_from_image_source(src)
        if res:
            votes.append(res)

    if not votes:
        return {"color": "none", "confidence": 0.0, "debug": {"reason": "no_votes"}, "per_image": []}

    score: Dict[str, float] = defaultdict(float)
    by_color: Dict[str, int] = defaultdict(int)
    per_image: List[Dict[str, Any]] = []
    for idx, v in enumerate(votes):
        w = _weighted_color_score(v)
        score[v.color] += w
        by_color[v.color] += 1
        per_image.append({"idx": idx, "color": v.color, "confidence": round(v.confidence, 3), "share": round(v.cluster_share, 3)})

    top = sorted(score.items(), key=lambda x: x[1], reverse=True)
    color = top[0][0]
    total_score = max(0.001, sum(score.values()))
    conf = top[0][1] / total_score

    # 4..7 photos: force ONE main sneaker color (shop_vkus profile only).
    if supplier_profile == "shop_vkus" and 4 <= len(valid) <= 7:
        c1, s1 = top[0]
        c2, s2 = top[1] if len(top) > 1 else (None, 0.0)
        if c2:
            if {c1, c2} <= {"beige", "yellow"}:
                mean_sat = sum(v.sat for v in votes if v.color in {"beige", "yellow"}) / max(1, sum(1 for v in votes if v.color in {"beige", "yellow"}))
                if mean_sat < 0.26:
                    c1 = "beige"
            if c1 in {"white", "gray", "black"} and (s1 - s2) < 0.2:
                alt_conf = sum(v.confidence for v in votes if v.color == c1) / max(1, by_color[c1])
                if alt_conf < 0.55:
                    c1 = c2

        black_s = float(score.get("black", 0.0))
        white_s = float(score.get("white", 0.0))
        purple_s = float(score.get("purple", 0.0)) + float(score.get("pink", 0.0))

        if black_s >= 0.30 * total_score and white_s >= 0.24 * total_score and (black_s + white_s) >= 0.62 * total_score:
            c1 = "black" if black_s >= white_s else "white"
        elif c1 == "gray" and purple_s >= 0.24 * total_score:
            c1 = "purple"
        elif c1 == "gray" and black_s >= 0.26 * total_score:
            c1 = "black"
        elif c1 == "gray" and white_s >= 0.26 * total_score:
            c1 = "white"

        result = {
            "color": c1,
            "confidence": round(min(0.99, s1 / total_score + 0.15), 3),
            "debug": {
                "votes": dict(by_color),
                "scores": {k: round(v, 3) for k, v in score.items()},
                "palette_rule": "4_7_to_1",
                "forced_single_for_5": True,
            },
            "per_image": per_image,
        }
        logger.info("detect_product_color: photos=%s color=%s confidence=%.3f top2=%s", len(valid), result["color"], result["confidence"], top[:2])
        return result

    # 10..14 photos: force TWO colors. 15..21 photos: force THREE colors (shop_vkus profile only).
    if supplier_profile == "shop_vkus" and 10 <= len(valid) <= 14:
        palette = _compose_palette_color(top, total_score, target_count=2)
        result = {
            "color": palette,
            "confidence": round(min(0.99, (top[0][1] + (top[1][1] if len(top) > 1 else 0.0)) / total_score), 3),
            "debug": {
                "votes": dict(by_color),
                "scores": {k: round(v, 3) for k, v in score.items()},
                "palette_rule": "10_14_to_2",
                "forced_single_for_5": False,
            },
            "per_image": per_image,
        }
        logger.info("detect_product_color: photos=%s color=%s confidence=%.3f top3=%s", len(valid), result["color"], result["confidence"], top[:3])
        return result

    if supplier_profile == "shop_vkus" and 15 <= len(valid) <= 21:
        palette = _compose_palette_color(top, total_score, target_count=3)
        top3_score = sum(v for _, v in top[:3])
        result = {
            "color": palette,
            "confidence": round(min(0.99, top3_score / total_score), 3),
            "debug": {
                "votes": dict(by_color),
                "scores": {k: round(v, 3) for k, v in score.items()},
                "palette_rule": "15_21_to_3",
                "forced_single_for_5": False,
            },
            "per_image": per_image,
        }
        logger.info("detect_product_color: photos=%s color=%s confidence=%.3f top4=%s", len(valid), result["color"], result["confidence"], top[:4])
        return result

    # Anti-false-gray: avoid collapsing black/white/purple mixes into neutral gray.
    if color == "gray":
        black_s = float(score.get("black", 0.0))
        white_s = float(score.get("white", 0.0))
        purple_s = float(score.get("purple", 0.0)) + float(score.get("pink", 0.0))

        if black_s >= 0.28 * total_score and white_s >= 0.22 * total_score and (black_s + white_s) >= 0.60 * total_score:
            color = "black-white"
            conf = max(conf, min(0.98, (black_s + white_s) / total_score))
        elif purple_s >= 0.22 * total_score and purple_s >= float(score.get("gray", 0.0)) * 0.60:
            color = "purple"
            conf = max(conf, min(0.95, purple_s / total_score))
        elif black_s >= 0.28 * total_score and black_s >= float(score.get("gray", 0.0)) * 0.65:
            color = "black"
            conf = max(conf, min(0.95, black_s / total_score))
        elif white_s >= 0.28 * total_score and white_s >= float(score.get("gray", 0.0)) * 0.65:
            color = "white"
            conf = max(conf, min(0.95, white_s / total_score))

    if len(top) > 1:
        c1, s1 = top[0]
        c2, s2 = top[1]
        # Avoid generic "multi" as a final label: either keep a dominant color,
        # or use an allowed two-tone combo (e.g. black-white).
        if c1 != c2 and c1 not in {"", "multi"} and c2 not in {"", "multi"}:
            share1 = float(s1) / float(total_score)
            share2 = float(s2) / float(total_score)
            if share1 <= 0.72 and share2 >= 0.26 and (share1 + share2) >= 0.72:
                combo = normalize_combo_color_key([c1, c2])
                if combo:
                    color = combo
                    conf = max(conf, min(0.98, share1 + share2))

    result = {
        "color": color,
        "confidence": round(min(0.99, conf), 3),
        "debug": {
            "votes": dict(by_color),
            "scores": {k: round(v, 3) for k, v in score.items()},
            "palette_rule": "default",
            "forced_single_for_5": False,
        },
        "per_image": per_image,
    }
    logger.info("detect_product_color: photos=%s color=%s confidence=%.3f top2=%s", len(valid), result["color"], result["confidence"], top[:2])
    return result


def normalize_color_to_whitelist(name: Optional[str]) -> str:
    raw = str(name or "").strip().lower()
    if not raw:
        return ""
    if re.search(r"[-/|,;]", raw):
        parts = [x for x in re.split(r"[-/|,;]+", raw) if str(x).strip()]
        return normalize_combo_color_key(parts)
    return normalize_color_key(raw)


def canonical_color_to_display_name(name: Optional[str]) -> str:
    canonical = normalize_color_to_whitelist(name)
    if not canonical:
        return ""
    if "-" in canonical:
        parts = [p for p in canonical.split("-") if p]
        labels = [_CANONICAL_TO_RU.get(p, p.replace("_", " ")) for p in parts]
        return "-".join([l.capitalize() if i == 0 else l for i, l in enumerate(labels)])
    if canonical in _CANONICAL_TO_RU:
        return _CANONICAL_TO_RU[canonical]
    return canonical.replace("_", " ")


def detect_product_colors_from_photos(image_sources: Sequence[str], supplier_profile: Optional[str] = None) -> Dict[str, Any]:
    detected = detect_product_color(image_sources, supplier_profile=supplier_profile)
    canonical = normalize_color_to_whitelist(detected.get("color"))
    return {**detected, "color": canonical, "display_color": canonical_color_to_display_name(canonical)}
