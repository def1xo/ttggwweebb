from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.api.dependencies import get_db
from app.db import models

router = APIRouter(tags=["news"])

@router.get("/news")
def list_news(limit: int = 10, db: Session = Depends(get_db)):
    # If the News model/table is absent (older DB), return an empty list instead of crashing.
    try:
        q = (
            db.query(models.News)
            .order_by(models.News.created_at.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        return []

    def _row(n):
        images = getattr(n, "images", None) or []
        return {
            "id": n.id,
            "title": n.title,
            "text": n.text,
            "date": n.created_at.strftime("%Y-%m-%d") if getattr(n, "created_at", None) else None,
            "images": images,
        }

    return [_row(n) for n in q]

@router.get("/news/{news_id}")
def get_news(news_id: int, db: Session = Depends(get_db)):
    try:
        n = db.get(models.News, news_id)
    except Exception:
        n = None
    if not n:
        raise HTTPException(404, "Not found")
    return {
        "id": n.id,
        "title": n.title,
        "text": n.text,
        "date": n.created_at.strftime("%Y-%m-%d") if getattr(n, "created_at", None) else None,
        "images": getattr(n, "images", None) or [],
    }
