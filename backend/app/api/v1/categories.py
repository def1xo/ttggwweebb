
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.api.dependencies import get_db
from app.db import models

router = APIRouter(tags=["categories"])

@router.get("/categories")
def list_categories(q: str | None = Query(None), db: Session = Depends(get_db)):
    try:
        query = db.query(models.Category)
        if q and q.strip():
            search = f"%{q.strip()}%"
            query = query.filter(or_(models.Category.name.ilike(search), models.Category.slug.ilike(search)))
        cats = query.order_by(models.Category.id.asc()).all()
    except Exception:
        # Keep catalog shell renderable even when DB schema/connection is temporarily broken.
        return []
    return [{"id": c.id, "name": c.name, "slug": c.slug, "image_url": c.image_url} for c in cats]

@router.get("/categories/{id_or_slug}")
def get_category(id_or_slug: str, db: Session = Depends(get_db)):
    q = None
    try:
        if id_or_slug.isdigit():
            q = db.query(models.Category).filter(models.Category.id == int(id_or_slug)).one_or_none()
        if not q:
            q = db.query(models.Category).filter(models.Category.slug == id_or_slug).one_or_none()
    except Exception:
        raise HTTPException(503, detail="database unavailable")
    if not q:
        raise HTTPException(404, detail="not found")
    return {"id": q.id, "name": q.name, "slug": q.slug, "image_url": q.image_url}
