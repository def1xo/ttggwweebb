
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.api.dependencies import get_db
from app.db import models

router = APIRouter(tags=["categories"])

@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    cats = db.query(models.Category).order_by(models.Category.id.asc()).all()
    return [{"id": c.id, "name": c.name, "slug": c.slug, "image_url": c.image_url} for c in cats]

@router.get("/categories/{id_or_slug}")
def get_category(id_or_slug: str, db: Session = Depends(get_db)):
    q = None
    if id_or_slug.isdigit():
        q = db.query(models.Category).filter(models.Category.id == int(id_or_slug)).one_or_none()
    if not q:
        q = db.query(models.Category).filter(models.Category.slug == id_or_slug).one_or_none()
    if not q:
        raise HTTPException(404, detail="not found")
    return {"id": q.id, "name": q.name, "slug": q.slug, "image_url": q.image_url}
