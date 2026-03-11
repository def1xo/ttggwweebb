from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import Image
from sqlalchemy.orm import Session

from app.db import models
from app.services.importer_notifications import slugify

logger = logging.getLogger("bulk_import")

COLOR_ALIASES = {
    "red": ["red", "красн", "бордо"],
    "black": ["black", "черн", "чёрн"],
    "white": ["white", "бел"],
    "blue": ["blue", "син"],
    "green": ["green", "зел"],
    "gray": ["gray", "grey", "сер"],
    "brown": ["brown", "корич"],
    "beige": ["beige", "беж"],
}


@dataclass
class ImportConfig:
    category_match_threshold: float = float(os.getenv("CATEGORY_MATCH_THRESHOLD", "0.8"))
    auto_confirm_category_threshold: float = float(os.getenv("AUTO_CONFIRM_CATEGORY_THRESHOLD", "0.9"))
    importer_dry_run: bool = str(os.getenv("IMPORTER_DRY_RUN", "0")).lower() in {"1", "true", "yes"}


def _tokenize(v: str) -> list[str]:
    return [t for t in re.split(r"[^a-zа-я0-9]+", (v or "").lower()) if t]


def _normalize_color_token(v: str) -> str | None:
    vv = (v or "").strip().lower()
    for canonical, aliases in COLOR_ALIASES.items():
        for a in aliases:
            if a in vv:
                return canonical
    return None


def _parse_colors(raw_explicit: str | None, title: str, image_names: Iterable[str]) -> list[str]:
    # 1) explicit
    found: list[str] = []
    for chunk in re.split(r"[,/;|]", raw_explicit or ""):
        c = _normalize_color_token(chunk)
        if c and c not in found:
            found.append(c)
    # 2) title regex
    if not found:
        for tok in _tokenize(title):
            c = _normalize_color_token(tok)
            if c and c not in found:
                found.append(c)
    # 3) image file names
    if not found:
        for nm in image_names:
            c = _normalize_color_token(str(nm))
            if c and c not in found:
                found.append(c)
    return found


def _dominant_color_name(path: str) -> str | None:
    try:
        with Image.open(path) as img:
            small = img.convert("RGB").resize((50, 50))
            hist = small.histogram()
            r = sum(i * hist[i] for i in range(256)) / max(1, sum(hist[:256]))
            g = sum(i * hist[256 + i] for i in range(256)) / max(1, sum(hist[256:512]))
            b = sum(i * hist[512 + i] for i in range(256)) / max(1, sum(hist[512:]))
            if r > g and r > b:
                return "red"
            if g > r and g > b:
                return "green"
            if b > r and b > g:
                return "blue"
            if abs(r - g) < 15 and abs(g - b) < 15:
                return "gray"
            if r < 60 and g < 60 and b < 60:
                return "black"
            if r > 220 and g > 220 and b > 220:
                return "white"
    except Exception:
        return None
    return None


def _get_or_create_color(db: Session, color_name: str) -> models.Color:
    slug = slugify(color_name)[:128]
    color = db.query(models.Color).filter((models.Color.slug == slug) | (models.Color.name == color_name)).one_or_none()
    if color:
        return color
    color = models.Color(name=color_name, slug=slug)
    db.add(color)
    db.flush()
    return color


def _simple_category_match(db: Session, supplier_category_raw: str) -> tuple[models.Category | None, float]:
    cats = db.query(models.Category).all()
    src_tokens = set(_tokenize(supplier_category_raw))
    best = None
    best_score = 0.0
    for c in cats:
        cand_tokens = set(_tokenize(c.name or "")) | set(_tokenize(c.slug or ""))
        if not cand_tokens:
            continue
        inter = len(src_tokens & cand_tokens)
        score = inter / max(1, len(src_tokens | cand_tokens))
        if score > best_score:
            best_score = score
            best = c
    return best, best_score


def _dump_failed_payload(job_id: int, payload: dict) -> str:
    base = Path("backend/import_failures")
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"import_job_{job_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _job_log(db: Session, job_id: int, level: str, message: str, context: dict | None = None):
    db.add(models.ImportLog(import_job_id=job_id, level=level, message=message, context=context or {}))


def run_csv_import(db: Session, *, supplier_id: int, csv_text: str, force_publish: bool = False) -> models.ImportJob:
    cfg = ImportConfig()
    job = models.ImportJob(supplier_id=supplier_id, status="running", payload={"supplier_id": supplier_id})
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
                sku = (row.get("supplier_sku") or "").strip() or None
                title = (row.get("title") or "").strip()
                if not title:
                    raise ValueError("title is required")
                supplier_cat = (row.get("supplier_category") or "").strip()
                image_list_raw = (row.get("images") or "").strip()
                image_names = [x.strip() for x in re.split(r"[|,]", image_list_raw) if x.strip()]
                detected_colors = _parse_colors(row.get("color"), title, image_names)

                if not detected_colors:
                    for candidate in image_names:
                        if os.path.exists(candidate):
                            fallback = _dominant_color_name(candidate)
                            if fallback:
                                detected_colors = [fallback]
                                break

                item = models.ImportItem(import_job_id=job.id, supplier_sku=sku, status="pending", payload=row)
                db.add(item)
                db.flush()

                mapped = db.query(models.SupplierCategoryMap).filter(
                    models.SupplierCategoryMap.supplier_id == supplier_id,
                    models.SupplierCategoryMap.supplier_category_raw == supplier_cat,
                ).one_or_none()

                category = None
                confidence = 0.0
                if mapped and mapped.mapped_category_id:
                    category = db.query(models.Category).filter(models.Category.id == mapped.mapped_category_id).one_or_none()
                    confidence = float(mapped.confidence or 0)
                else:
                    category, confidence = _simple_category_match(db, supplier_cat)
                    if category:
                        db.add(models.SupplierCategoryMap(
                            supplier_id=supplier_id,
                            supplier_category_raw=supplier_cat,
                            mapped_category_id=category.id,
                            confidence=confidence,
                            is_confirmed=confidence >= cfg.auto_confirm_category_threshold,
                            last_used=datetime.utcnow(),
                        ))

                needs_color_review = len(detected_colors) == 0
                needs_category_review = (not category) or confidence < cfg.category_match_threshold
                publish = bool(force_publish and not cfg.importer_dry_run and not needs_color_review and not needs_category_review)

                color_variants = detected_colors or [None]
                for color_name in color_variants:
                    color_obj = _get_or_create_color(db, color_name) if color_name else None
                    base_slug = slugify(f"{title}-{sku or 'nosku'}-{color_name or 'nocolor'}")
                    product = db.query(models.Product).filter(
                        (models.Product.supplier_sku == sku) & (models.Product.slug == base_slug)
                    ).one_or_none()
                    if not product:
                        product = models.Product(slug=base_slug, title=title[:512])
                        db.add(product)
                    product.supplier_sku = sku
                    product.import_supplier_name = str(supplier_id)
                    product.category_id = category.id if category and not needs_category_review else None
                    product.requires_color_review = needs_color_review
                    product.requires_category_review = needs_category_review
                    product.review_reason = "unknown_color" if needs_color_review else ("unknown_category" if needs_category_review else None)
                    product.visible = publish

                    db.flush()

                    if color_obj:
                        var = db.query(models.ProductVariant).filter(
                            models.ProductVariant.product_id == product.id,
                            models.ProductVariant.color_id == color_obj.id,
                        ).one_or_none()
                        if not var:
                            db.add(models.ProductVariant(product_id=product.id, color_id=color_obj.id, price=0, stock_quantity=0))

                    for idx, img in enumerate(image_names):
                        pimg = db.query(models.ProductImage).filter(models.ProductImage.product_id == product.id, models.ProductImage.url == img).one_or_none()
                        if not pimg:
                            pimg = models.ProductImage(product_id=product.id, url=img, sort=idx)
                            db.add(pimg)
                            db.flush()
                        if color_obj:
                            exists = db.query(models.ColorImage).filter(
                                models.ColorImage.color_id == color_obj.id,
                                models.ColorImage.product_image_id == pimg.id,
                            ).one_or_none()
                            if not exists:
                                db.add(models.ColorImage(color_id=color_obj.id, product_image_id=pimg.id))

                item.status = "requires_review" if (needs_color_review or needs_category_review) else "imported"
                item.reason = "color" if needs_color_review else ("category" if needs_category_review else None)

        _job_log(db, job.id, "INFO", "Import finished", {"supplier_id": supplier_id})
        job.status = "completed"
        db.commit()
    except Exception as exc:
        db.rollback()
        dump_path = _dump_failed_payload(job.id, {"supplier_id": supplier_id, "error": str(exc), "csv": csv_text[:5000]})
        job.status = "failed"
        job.error_message = str(exc)
        job.input_dump_path = dump_path
        db.add(job)
        db.commit()
        # keep jsonl file for parsers
        log_dir = Path("backend/import_failures")
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "errors.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"job_id": job.id, "error": str(exc), "path": dump_path, "at": datetime.utcnow().isoformat()}, ensure_ascii=False) + "\n")
        logger.exception("import failed job=%s", job.id)
    return job
