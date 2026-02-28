"""Cleanup script: remove bogus detected_color='multi' and fix media meta buckets.

Usage (inside backend container / venv):
  PYTHONPATH=. python scripts/fix_multicolor_products.py

This script is intentionally conservative:
- It does NOT try to re-detect colors (no downloads, no heavy I/O).
- It only removes the generic 'multi' label and moves any images bucketed under 'multi'
  into general_images so the storefront still shows the full gallery.
"""

from __future__ import annotations

from typing import Any

from app.db.session import SessionLocal
from app.db import models
from app.services.color_detection import normalize_color_to_whitelist


def _uniq_extend(dst: list[str], items: list[str]) -> None:
    seen = set(dst)
    for u in items:
        uu = str(u or "").strip()
        if not uu or uu in seen:
            continue
        dst.append(uu)
        seen.add(uu)


def main() -> None:
    db = SessionLocal()
    try:
        products = (
            db.query(models.Product)
            .filter(models.Product.detected_color == "multi")
            .all()
        )

        touched = 0
        for p in products:
            p.detected_color = None
            p.detected_color_confidence = None

            meta: Any = getattr(p, "import_media_meta", None) or {}
            if isinstance(meta, dict):
                by_key = meta.get("images_by_color_key")
                if isinstance(by_key, dict) and by_key.get("multi"):
                    moved = [str(x).strip() for x in (by_key.get("multi") or []) if str(x).strip()]
                    by_key.pop("multi", None)
                    meta["images_by_color_key"] = by_key
                    general = [str(x).strip() for x in (meta.get("general_images") or []) if str(x).strip()]
                    _uniq_extend(general, moved)
                    meta["general_images"] = general
                    p.import_media_meta = meta

            db.add(p)
            touched += 1

        db.commit()
        print(f"OK: cleaned {touched} products")

    finally:
        db.close()


if __name__ == "__main__":
    main()
