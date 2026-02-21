from __future__ import annotations

import colorsys
import io
import math
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from collections import deque

import requests
from PIL import Image

logger = logging.getLogger("color_detection")

CANONICAL_COLORS: tuple[str, ...] = (
    "black", "white", "gray",
    "beige", "brown",
    "navy", "blue", "light_blue", "teal", "turquoise",
    "green", "lime", "olive",
    "yellow", "orange",
    "red", "burgundy", "pink",
    "purple", "lavender",
    "silver", "gold",
    "multicolor",
)

COLOR_PRIORITY: tuple[str, ...] = (
    "black", "white", "gray", "navy", "blue", "light_blue", "teal", "turquoise",
    "green", "lime", "olive", "yellow", "orange", "red", "burgundy", "pink",
    "purple", "lavender", "beige", "brown", "silver", "gold", "multicolor",
)

COLOR_SYNONYMS: dict[str, str] = {
    "grey": "gray",
    "violet": "purple",
    "lilac": "lavender",
    "offwhite": "white",
    "off-white": "white",
    "cream": "beige",
    "sky": "light_blue",
    "mint": "teal",
    "aqua": "turquoise",
    "maroon": "burgundy",
    "lightgray": "gray",
    "darkgray": "gray",
    "dark-grey": "gray",
    "light-grey": "gray",
    "фиолетовый": "purple",
    "фиолет": "purple",
    "серый": "gray",
    "чёрный": "black",
    "черный": "black",
    "белый": "white",
    "зелёный": "green",
    "зеленый": "green",
    "красный": "red",
    "синий": "blue",
    "голубой": "blue",
    "темно-синий": "navy",
    "тёмно-синий": "navy",
    "бордовый": "burgundy",
    "лавандовый": "lavender",
    "бирюзовый": "turquoise",
    "оливковый": "olive",
    "лаймовый": "lime",
    "золотой": "gold",
    "серебристый": "silver",
    "розовый": "pink",
    "оранжевый": "orange",
    "желтый": "yellow",
    "жёлтый": "yellow",
    "коричневый": "brown",
    "бежевый": "beige",
}

LAB_PROTOTYPES: dict[str, Tuple[float, float, float]] = {
    "black": (18.0, 0.0, 0.0),
    "white": (96.0, 0.0, 0.0),
    "gray": (60.0, 0.0, 0.0),
    "silver": (77.0, 0.0, 0.0),
    "beige": (82.0, 2.0, 18.0),
    "brown": (45.0, 18.0, 24.0),
    "navy": (25.0, 8.0, -35.0),
    "blue": (44.0, 10.0, -48.0),
    "light_blue": (68.0, -8.0, -22.0),
    "teal": (58.0, -30.0, -6.0),
    "turquoise": (72.0, -34.0, -10.0),
    "green": (52.0, -40.0, 32.0),
    "lime": (86.0, -52.0, 74.0),
    "olive": (46.0, -10.0, 28.0),
    "yellow": (90.0, -5.0, 82.0),
    "orange": (72.0, 38.0, 66.0),
    "red": (52.0, 70.0, 44.0),
    "burgundy": (32.0, 44.0, 18.0),
    "pink": (74.0, 40.0, 6.0),
    "purple": (44.0, 48.0, -44.0),
    "lavender": (72.0, 24.0, -18.0),
    "gold": (76.0, 8.0, 72.0),
}


@dataclass
class ImageColorResult:
    color: str
    confidence: float
    cluster_share: float
    sat: float
    light: float
    lab_a: float
    lab_b: float
    coverage: float
    zoom_flag: bool
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
        token = COLOR_SYNONYMS.get(token, token)
        if token not in CANONICAL_COLORS:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    if not out:
        return "multicolor"
    out = sorted(out, key=lambda x: COLOR_PRIORITY.index(x) if x in COLOR_PRIORITY else 999)[:2]
    return "/".join(out)


def _nearest_canonical_from_lab(lab: Tuple[float, float, float]) -> str:
    best = "multicolor"
    best_d = 10e9
    for c, proto in LAB_PROTOTYPES.items():
        d = _lab_distance(lab, proto)
        if d < best_d:
            best_d = d
            best = c
    return best


def _keyword_fallback_color(title: str | None) -> str:
    t = str(title or "").strip().lower()
    if not t:
        return ""
    if "triple black" in t:
        return "black"
    if "oreo" in t:
        return "black/white"
    if "grinch" in t:
        return "green"
    return ""


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


def _extract_subject_pixels_with_meta(img: Image.Image) -> Tuple[List[Tuple[Tuple[int, int, int], float]], Dict[str, Any]]:
    w, h = img.size
    if w < 8 or h < 8:
        return []
    max_side = 256
    if max(img.size) > max_side:
        scale = max_side / float(max(img.size))
        nw = max(8, int(img.size[0] * scale))
        nh = max(8, int(img.size[1] * scale))
        img = img.resize((nw, nh))
    px = img.load()
    ww, hh = img.size

    bw = max(2, int(min(ww, hh) * 0.10))
    edge_pixels: List[Tuple[int, int, int]] = []
    for y in range(hh):
        for x in range(ww):
            if x < bw or x >= ww - bw or y < bw or y >= hh - bw:
                edge_pixels.append(px[x, y])

    bg_clusters: List[Tuple[float, float, float]] = []
    if edge_pixels:
        edge_labs = [_rgb_to_lab(p) for p in edge_pixels[::3]]
        for c in _kmeans(edge_labs, k=2):
            bg_clusters.append(tuple(c["center"]))

    cx, cy = ww / 2.0, hh / 2.0
    sigma = 0.35 * float(max(ww, hh))
    sigma2 = max(1.0, 2.0 * sigma * sigma)
    subject_mask: List[List[bool]] = [[False for _ in range(ww)] for _ in range(hh)]
    subject_candidate_count = 0
    for y in range(0, hh, 2):
        for x in range(0, ww, 2):
            r, g, b = px[x, y]
            lab = _rgb_to_lab((r, g, b))

            h1, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            center_weight = math.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / sigma2))
            if bg_clusters:
                bg_dist = min(_lab_distance(lab, bg) for bg in bg_clusters)
                if bg_dist <= 10.0 and center_weight < 0.82:
                    continue
            subject_mask[y][x] = True
            subject_candidate_count += 1

    # keep the largest connected component near center (anti-crop/noise)
    visited: set[Tuple[int, int]] = set()
    best_comp: List[Tuple[int, int]] = []
    center_box = (int(ww * 0.30), int(hh * 0.30), int(ww * 0.70), int(hh * 0.70))
    for y in range(0, hh, 2):
        for x in range(0, ww, 2):
            if (x, y) in visited or not subject_mask[y][x]:
                continue
            q = deque([(x, y)])
            visited.add((x, y))
            comp: List[Tuple[int, int]] = []
            touches_center = False
            while q:
                cx2, cy2 = q.popleft()
                comp.append((cx2, cy2))
                if center_box[0] <= cx2 <= center_box[2] and center_box[1] <= cy2 <= center_box[3]:
                    touches_center = True
                for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2)):
                    nx, ny = cx2 + dx, cy2 + dy
                    if nx < 0 or ny < 0 or nx >= ww or ny >= hh:
                        continue
                    if (nx, ny) in visited or not subject_mask[ny][nx]:
                        continue
                    visited.add((nx, ny))
                    q.append((nx, ny))
            if touches_center and len(comp) > len(best_comp):
                best_comp = comp

    best_set = set(best_comp)
    pixels: List[Tuple[Tuple[int, int, int], float]] = []
    for y in range(0, hh, 2):
        for x in range(0, ww, 2):
            if best_set and (x, y) not in best_set:
                continue
            if not best_set and not subject_mask[y][x]:
                continue
            r, g, b = px[x, y]
            edge_strength = 0.0
            if 1 <= x < (ww - 1) and 1 <= y < (hh - 1):
                r2, g2, b2 = px[x + 1, y]
                r3, g3, b3 = px[x, y + 1]
                edge_strength = min(1.0, (abs(r - r2) + abs(g - g2) + abs(b - b2) + abs(r - r3) + abs(g - g3) + abs(b - b3)) / 180.0)

            center_weight = math.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / sigma2))
            h1, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)

            keep_score = center_weight * 0.72 + edge_strength * 0.28
            if s >= 0.18:
                keep_score += 0.08
            if keep_score < 0.36:
                continue
            pixels.append(((r, g, b), max(0.08, min(1.0, keep_score))))

    if len(pixels) > 2200:
        step = max(1, len(pixels) // 2200)
        pixels = pixels[::step]
    sampled_total = max(1, (ww // 2) * (hh // 2))
    coverage = float(len(best_set) if best_set else subject_candidate_count) / float(sampled_total)
    meta = {
        "coverage": round(max(0.0, min(1.0, coverage)), 3),
        "zoom_flag": bool(coverage > 0.85),
        "small_mask_fallback": bool(coverage < 0.18),
    }
    return pixels, meta


def _extract_subject_pixels(img: Image.Image) -> List[Tuple[int, int, int]]:
    weighted, _meta = _extract_subject_pixels_with_meta(img)
    return [p for p, _w in weighted]


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
    weighted_pixels, mask_meta = _extract_subject_pixels_with_meta(img)
    pixels = [p for p, _w in weighted_pixels]
    weights = [float(w) for _p, w in weighted_pixels]
    if not pixels:
        return None

    lab_points = [_rgb_to_lab(p) for p in pixels]
    expanded_lab_points: list[Tuple[float, float, float]] = []
    for lp, w in zip(lab_points, weights):
        reps = max(1, min(5, int(round(w * 4.0))))
        for _ in range(reps):
            expanded_lab_points.append(lp)
    clusters = _kmeans(expanded_lab_points, k=3)
    if not clusters:
        return None

    total = max(1, sum(int(c["count"]) for c in clusters))
    main = clusters[0]
    l, a, b = main["center"]

    # HSV from Lab center approximation via nearest original pixel
    rr2, gg2, bb2 = min(pixels, key=lambda p: ( _rgb_to_lab(p)[0] - l) ** 2 + (_rgb_to_lab(p)[1] - a) ** 2 + (_rgb_to_lab(p)[2] - b) ** 2)
    h, s, v = colorsys.rgb_to_hsv(rr2 / 255.0, gg2 / 255.0, bb2 / 255.0)

    color = _nearest_canonical_from_lab((l, a, b))
    share = float(main["count"]) / float(total)
    confidence = max(0.05, min(0.99, share * (0.65 + min(0.35, s))))
    top2: list[tuple[str, float]] = [(color, share)]

    if len(clusters) > 1:
        second = clusters[1]
        second_share = float(second["count"]) / float(total)
        l2, a2, b2 = second["center"]
        rr3, gg3, bb3 = min(pixels, key=lambda p: (_rgb_to_lab(p)[0] - l2) ** 2 + (_rgb_to_lab(p)[1] - a2) ** 2 + (_rgb_to_lab(p)[2] - b2) ** 2)
        h2, s2, v2 = colorsys.rgb_to_hsv(rr3 / 255.0, gg3 / 255.0, bb3 / 255.0)
        c2 = _nearest_canonical_from_lab((l2, a2, b2))
        top2.append((c2, second_share))
        if c2 != color:
            if {color, c2} == {"black", "white"} and (share + second_share) >= 0.65:
                color = "black/white"
                confidence = max(confidence, min(0.94, 0.62 + (share + second_share) * 0.28))
            elif color == "gray" and c2 in {"green", "purple", "red", "blue", "lime", "turquoise", "teal"} and second_share >= 0.22 and confidence < 0.62:
                color = normalize_color_label(f"{color}/{c2}") or c2
                confidence = max(confidence, min(0.90, 0.52 + (share + second_share) * 0.20))
            elif share >= 0.30 and second_share >= 0.25:
                color = normalize_color_label(f"{color}/{c2}") or color
                confidence = max(confidence, min(0.93, 0.56 + (share + second_share) * 0.22))

    if (share < 0.32) and (len(clusters) > 1 and (float(clusters[1]["count"]) / float(total)) < 0.25) and confidence < 0.35:
        color = "multicolor"

    color = normalize_color_label(color) or color

    return ImageColorResult(
        color=color,
        confidence=confidence,
        cluster_share=share,
        sat=s,
        light=l,
        lab_a=a,
        lab_b=b,
        coverage=float(mask_meta.get("coverage") or 0.0),
        zoom_flag=bool(mask_meta.get("zoom_flag")),
        debug={
            "clusters": [{"center": [round(x, 2) for x in c["center"]], "count": int(c["count"])} for c in clusters],
            "top2": [{"color": c, "share": round(sv, 3)} for c, sv in top2],
            "mask": mask_meta,
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
    if share1 < 0.32 and share2 < 0.25:
        return "multicolor"
    return normalize_color_label(c1) or c1


def detect_product_color(image_sources: Sequence[str], title_hint: str | None = None) -> Dict[str, Any]:
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
        if bool(getattr(v, "zoom_flag", False)):
            w *= 0.6
        if "/" in str(v.color):
            parts = [p for p in str(v.color).split("/") if p]
            if parts:
                part_w = w / float(len(parts))
                for p in parts:
                    score[p] += part_w
            else:
                score[v.color] += w
        else:
            score[v.color] += w
        by_color[v.color] += 1
        per_image.append({"idx": idx, "color": v.color, "confidence": round(v.confidence, 3), "share": round(v.cluster_share, 3), "coverage": round(float(getattr(v, 'coverage', 0.0)), 3), "zoom_flag": bool(getattr(v, 'zoom_flag', False))})

    support_photos: Dict[str, int] = defaultdict(int)
    for v in votes:
        parts = [p for p in str(v.color or "").split("/") if p]
        for p in (parts or [str(v.color)]):
            support_photos[p] += 1

    # 5 photos rule: force one stable result (single color or a composite pair)
    if len(valid) == 5:
        total_s = sum(score.values())
        valid_score = {}
        for c, s in score.items():
            if support_photos.get(c, 0) >= 2 or s >= 0.55 * max(0.001, total_s):
                valid_score[c] = s
        c1 = _compose_top_colors(valid_score or score, sum((valid_score or score).values()))
        top = sorted(score.items(), key=lambda x: x[1], reverse=True)
        s1 = top[0][1] if top else 0.0
        out = {
            "color": c1,
            "confidence": round(min(0.99, s1 / max(0.001, sum(score.values())) + 0.15), 3),
            "debug": {"votes": dict(by_color), "scores": {k: round(v, 3) for k, v in score.items()}, "support_photos": dict(support_photos), "forced_single_for_5": True},
            "per_image": per_image,
        }
        if (not out["color"] or float(out.get("confidence") or 0) < 0.35):
            fb = _keyword_fallback_color(title_hint)
            if fb:
                out["color"] = fb
                out["debug"]["keyword_fallback"] = True
        return out

    top = sorted(score.items(), key=lambda x: x[1], reverse=True)
    total_s = sum(score.values())
    valid_score = {}
    for c, s in score.items():
        if support_photos.get(c, 0) >= 2 or s >= 0.55 * max(0.001, total_s):
            valid_score[c] = s
    color = _compose_top_colors(valid_score or score, sum((valid_score or score).values())) or top[0][0]
    conf = top[0][1] / max(0.001, sum(score.values()))

    out = {
        "color": color,
        "confidence": round(min(0.99, conf), 3),
        "debug": {"votes": dict(by_color), "scores": {k: round(v, 3) for k, v in score.items()}, "support_photos": dict(support_photos), "forced_single_for_5": False},
        "per_image": per_image,
    }
    if (not out["color"] or float(out.get("confidence") or 0) < 0.35):
        fb = _keyword_fallback_color(title_hint)
        if fb:
            out["color"] = fb
            out["debug"]["keyword_fallback"] = True
    return out
