from fastapi import APIRouter, Depends, Query, HTTPException
from typing import List, Dict, Any
from sqlalchemy.orm import Session

# корректный импорт get_db (в вашем проекте dependency лежит в app.api.dependencies)
try:
    from app.api.dependencies import get_db  # основной вариант
except Exception:
    try:
        # fallback: если в проекте есть db.session с SessionLocal
        from app.db.session import SessionLocal  # type: ignore

        def get_db():
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()
    except Exception:
        raise RuntimeError("Не найден get_db: добавьте app.api.dependencies.get_db или app.db.session.SessionLocal")

# импорт модели Product (в вашем проекте модель в app.db.models)
try:
    from app.db.models import Product  # основной вариант
except Exception:
    Product = None

router = APIRouter()


def serialize_product(p: Any) -> Dict[str, Any]:
    return {
        "id": getattr(p, "id", None),
        "title": getattr(p, "title", getattr(p, "name", None)),
        # project uses base_price
        "price": float(getattr(p, "base_price", getattr(p, "price", 0)) or 0),
        "image": getattr(p, "default_image", getattr(p, "image", None)),
        "created_at": getattr(p, "created_at", None),
    }


def _get_recommendations_impl(
    db: Session = Depends(get_db),
    limit_recent: int = Query(10, ge=1, le=200),
    result_count: int = Query(4, ge=1, le=50),
):
    if Product is None:
        raise HTTPException(status_code=500, detail="Product model not found in project (expected app.db.models.Product)")

    try:
        q = db.query(Product)
        if hasattr(Product, "visible"):
            q = q.filter(Product.visible == True)
        recent = q.order_by(Product.created_at.desc()).limit(limit_recent).all()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

    def price_val(p):
        try:
            return float(getattr(p, "base_price", getattr(p, "price", 0)) or 0)
        except Exception:
            return 0.0

    sorted_by_price = sorted(recent, key=price_val, reverse=True)
    top = sorted_by_price[:result_count]
    return [serialize_product(p) for p in top]


# Multiple route aliases (frontend tries different base prefixes)
@router.get("/recommendations", response_model=List[Dict[str, Any]])
@router.get("/v1/recommendations", response_model=List[Dict[str, Any]])
@router.get("/api/recommendations", response_model=List[Dict[str, Any]])
@router.get("/api/v1/recommendations", response_model=List[Dict[str, Any]])
def get_recommendations(
    db: Session = Depends(get_db),
    limit_recent: int = Query(10, ge=1, le=200),
    result_count: int = Query(4, ge=1, le=50),
):
    return _get_recommendations_impl(db=db, limit_recent=limit_recent, result_count=result_count)
