from __future__ import annotations

import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Literal

from app.services.color_detection import detect_color_from_image_source, normalize_color_to_whitelist

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DEFAULTS = {
    "shoes": "data/vision_shoes/color_clf.joblib",
    "clothes": "data/vision_clothes/color_clf.joblib",
}
MODEL_ENV_KEYS = {
    "shoes": "COLOR_MODEL_SHOES_PATH",
    "clothes": "COLOR_MODEL_CLOTHES_PATH",
}

_MODELS: dict[str, object | None] = {"shoes": None, "clothes": None}
_MODEL_LOAD_ATTEMPTED: dict[str, bool] = {"shoes": False, "clothes": False}
_CLIP_STATE: dict[str, object | None] = {"model": None, "preprocess": None, "tokenizer": None, "device": None}
_CLIP_LOAD_ATTEMPTED = False


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, str(default))).strip())
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, str(default))).strip())
    except Exception:
        return float(default)


def _resolve_model_path(kind: Literal["shoes", "clothes"]) -> Path:
    raw = os.getenv(MODEL_ENV_KEYS[kind], MODEL_DEFAULTS[kind])
    path = Path(str(raw).strip())
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _ensure_clip_loaded() -> bool:
    global _CLIP_LOAD_ATTEMPTED
    if _CLIP_LOAD_ATTEMPTED:
        return bool(_CLIP_STATE["model"] and _CLIP_STATE["preprocess"])
    _CLIP_LOAD_ATTEMPTED = True
    try:
        import torch
        import open_clip

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        tokenizer = open_clip.get_tokenizer("ViT-B-32")
        model = model.to(device)
        model.eval()
        _CLIP_STATE.update({"model": model, "preprocess": preprocess, "tokenizer": tokenizer, "device": device})
        return True
    except Exception as exc:
        logger.info("color_ml: CLIP unavailable, fallback to cv detector: %s", exc)
        return False


def _ensure_model_loaded(kind: Literal["shoes", "clothes"]) -> bool:
    if _MODEL_LOAD_ATTEMPTED[kind]:
        return _MODELS[kind] is not None
    _MODEL_LOAD_ATTEMPTED[kind] = True
    try:
        import joblib

        model_path = _resolve_model_path(kind)
        if not model_path.exists():
            logger.info("color_ml: model file not found for %s at %s", kind, model_path)
            return False
        _MODELS[kind] = joblib.load(model_path)
        return _MODELS[kind] is not None
    except Exception as exc:
        logger.info("color_ml: model unavailable for %s, fallback to cv detector: %s", kind, exc)
        _MODELS[kind] = None
        return False


def _download_image(url: str):
    import io
    import requests
    from PIL import Image

    if not str(url or "").strip():
        return None
    if str(url).lower().startswith(("http://", "https://")):
        resp = requests.get(url, timeout=15, headers={"User-Agent": "color-ml/1.0"})
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    return Image.open(url).convert("RGB")


def _predict_with_ml(url: str, kind: Literal["shoes", "clothes"]) -> dict | None:
    if not _ensure_clip_loaded() or not _ensure_model_loaded(kind):
        return None
    try:
        import torch

        img = _download_image(url)
        if img is None:
            return None
        preprocess = _CLIP_STATE["preprocess"]
        model = _CLIP_STATE["model"]
        device = _CLIP_STATE["device"]
        assert preprocess is not None and model is not None and device is not None

        with torch.no_grad():
            image_t = preprocess(img).unsqueeze(0).to(device)
            emb = model.encode_image(image_t)
            emb = emb / emb.norm(dim=-1, keepdim=True)

        clf = _MODELS[kind]
        if clf is None:
            return None
        probs_arr = clf.predict_proba(emb.detach().cpu().numpy())[0]
        classes = [str(c) for c in getattr(clf, "classes_", [])]
        if not classes:
            return None

        probs = {normalize_color_to_whitelist(cls): float(prob) for cls, prob in zip(classes, probs_arr)}
        probs = {k: v for k, v in probs.items() if k}
        if not probs:
            return None
        best_color, best_prob = max(probs.items(), key=lambda kv: kv[1])
        return {
            "color": best_color,
            "confidence": float(best_prob),
            "probs": probs,
            "debug": {"source": "ml", "kind": kind},
        }
    except Exception as exc:
        logger.info("color_ml: predict failed for %s (%s), fallback to cv", kind, exc)
        return None


def _predict_with_fallback(url: str, kind: Literal["shoes", "clothes"]) -> dict:
    res = detect_color_from_image_source(url)
    color = normalize_color_to_whitelist(getattr(res, "color", "") if res else "")
    conf = float(getattr(res, "confidence", 0.0) if res else 0.0)
    return {
        "color": color,
        "confidence": conf,
        "probs": ({color: conf} if color else {}),
        "debug": {"source": "cv_fallback", "kind": kind, "raw": (res.debug if res else {"reason": "no_result"})},
    }


def predict_color_for_image_url(url: str, kind: Literal["shoes", "clothes"]) -> dict:
    ml = _predict_with_ml(url, kind)
    if ml is not None:
        return ml
    return _predict_with_fallback(url, kind)


def _is_localized_upload_url(url: str) -> bool:
    u = str(url or "").strip().lower()
    return u.startswith("/uploads/") or "/uploads/" in u


def split_images_by_color(
    image_urls: list[str],
    kind: Literal["shoes", "clothes"],
    min_conf: float | None = None,
    min_images_per_color: int | None = None,
    expected_colors: list[str] | None = None,
) -> dict[str, list[str]]:
    min_images = int(min_images_per_color or _env_int("COLOR_ML_MIN_IMAGES_PER_COLOR", 4))
    strict_thr = float(min_conf if min_conf is not None else _env_float("COLOR_ML_MIN_CONF_STRICT", 0.55))
    soft_thr = float(_env_float("COLOR_ML_MIN_CONF_SOFT", 0.35))
    topk = int(_env_int("COLOR_ML_TOPK_PER_COLOR", 12))

    rows: list[dict[str, object]] = []
    for url in [str(x).strip() for x in (image_urls or []) if str(x).strip()]:
        pred = predict_color_for_image_url(url, kind)
        probs = {
            normalize_color_to_whitelist(k): float(v)
            for k, v in dict(pred.get("probs") or {}).items()
            if normalize_color_to_whitelist(k)
        }
        best_color = normalize_color_to_whitelist(pred.get("color"))
        best_conf = float(pred.get("confidence") or 0.0)
        if best_color and best_color not in probs:
            probs[best_color] = best_conf
        rows.append({"url": url, "probs": probs, "best_color": best_color})

    if not rows:
        return {}

    candidate_colors: set[str] = set()
    exp_norm = [normalize_color_to_whitelist(c) for c in (expected_colors or []) if normalize_color_to_whitelist(c)]
    if exp_norm:
        candidate_colors.update(exp_norm)
    else:
        for r in rows:
            for c in (r.get("probs") or {}).keys():
                if c and c != "multi":
                    candidate_colors.add(str(c))

    out: dict[str, list[str]] = {}
    for color in sorted(candidate_colors):
        strict_hits: list[str] = []
        soft_pool: list[tuple[str, float]] = []
        top_pool: list[tuple[str, float]] = []

        for r in rows:
            url = str(r.get("url") or "").strip()
            probs = dict(r.get("probs") or {})
            p = float(probs.get(color, 0.0) or 0.0)
            if p >= strict_thr:
                strict_hits.append(url)
            elif p >= soft_thr:
                soft_pool.append((url, p))
            top_pool.append((url, p))

        selected: list[str] = []
        seen: set[str] = set()

        for u in strict_hits:
            if u not in seen:
                selected.append(u)
                seen.add(u)

        if len(selected) < min_images:
            for u, _p in sorted(soft_pool, key=lambda x: x[1], reverse=True):
                if u in seen:
                    continue
                selected.append(u)
                seen.add(u)
                if len(selected) >= min_images:
                    break

        if len(selected) < min_images:
            for u, _p in sorted(top_pool, key=lambda x: x[1], reverse=True)[:max(1, topk)]:
                if u in seen:
                    continue
                if not _is_localized_upload_url(u):
                    continue
                row = next((x for x in rows if str(x.get("url") or "") == u), None)
                if not row:
                    continue
                if normalize_color_to_whitelist(row.get("best_color")) != color:
                    continue
                if float(dict(row.get("probs") or {}).get(color, 0.0) or 0.0) <= 0:
                    continue
                selected.append(u)
                seen.add(u)
                if len(selected) >= min_images:
                    break

        if len(selected) >= min_images:
            out[color] = selected

    return dict(sorted(out.items(), key=lambda kv: len(kv[1]), reverse=True))
