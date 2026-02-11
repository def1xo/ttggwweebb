from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin_user, get_db
from app.db import models
from app.services.supplier_intelligence import (
    SupplierOffer,
    estimate_market_price,
    fetch_tabular_preview,
    map_category,
    pick_best_offer,
)

router = APIRouter(tags=["admin_supplier_intelligence"])


class SupplierSourceIn(BaseModel):
    source_url: str = Field(min_length=5, max_length=2000)
    supplier_name: str | None = Field(default=None, max_length=255)
    manager_name: str | None = Field(default=None, max_length=255)
    manager_contact: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class SupplierSourcePatchIn(BaseModel):
    source_url: str | None = Field(default=None, min_length=5, max_length=2000)
    supplier_name: str | None = Field(default=None, max_length=255)
    manager_name: str | None = Field(default=None, max_length=255)
    manager_contact: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    active: bool | None = None


class SupplierSourceOut(BaseModel):
    id: int
    source_url: str
    supplier_name: str | None = None
    manager_name: str | None = None
    manager_contact: str | None = None
    note: str | None = None
    active: bool


class AnalyzeLinksIn(BaseModel):
    links: list[str] = Field(default_factory=list, min_items=1, max_items=30)


class AnalyzeStoredSourcesIn(BaseModel):
    source_ids: list[int] = Field(default_factory=list, min_items=1, max_items=50)


class AnalyzeLinksOut(BaseModel):
    url: str
    ok: bool
    kind: str | None = None
    status_code: int | None = None
    rows_count_preview: int | None = None
    sample_rows: list[list[str]] = Field(default_factory=list)
    mapped_categories_sample: list[str] = Field(default_factory=list)
    error: str | None = None


class AnalyzeStoredSourceOut(AnalyzeLinksOut):
    source_id: int
    supplier_name: str | None = None
    manager_name: str | None = None
    manager_contact: str | None = None


def _to_source_out(x: models.SupplierSource) -> SupplierSourceOut:
    return SupplierSourceOut(
        id=int(x.id),
        source_url=str(x.source_url),
        supplier_name=getattr(x, "supplier_name", None),
        manager_name=getattr(x, "manager_name", None),
        manager_contact=getattr(x, "manager_contact", None),
        note=getattr(x, "note", None),
        active=bool(getattr(x, "active", True)),
    )


def _analyze_url(url: str) -> AnalyzeLinksOut:
    data = fetch_tabular_preview(url)
    rows = data.get("rows_preview") or []
    sample_titles: list[str] = []
    for r in rows[:8]:
        if r:
            sample_titles.append(str(r[0]))
    categories = [map_category(t) for t in sample_titles if t]
    return AnalyzeLinksOut(
        url=url,
        ok=True,
        kind=str(data.get("kind") or ""),
        status_code=int(data.get("status_code") or 0),
        rows_count_preview=int(data.get("rows_count_preview") or 0),
        sample_rows=rows[:8],
        mapped_categories_sample=categories,
    )


@router.get("/supplier-intelligence/sources", response_model=list[SupplierSourceOut])
def list_supplier_sources(_admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    items = (
        db.query(models.SupplierSource)
        .order_by(models.SupplierSource.active.desc(), models.SupplierSource.id.desc())
        .all()
    )
    return [_to_source_out(x) for x in items]


@router.post("/supplier-intelligence/sources", response_model=SupplierSourceOut)
def create_supplier_source(payload: SupplierSourceIn, _admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    source_url = payload.source_url.strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url is required")

    item = models.SupplierSource(
        source_url=source_url,
        supplier_name=(payload.supplier_name or "").strip() or None,
        manager_name=(payload.manager_name or "").strip() or None,
        manager_contact=(payload.manager_contact or "").strip() or None,
        note=(payload.note or "").strip() or None,
        active=True,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="source_url already exists")
    db.refresh(item)
    return _to_source_out(item)


@router.patch("/supplier-intelligence/sources/{source_id}", response_model=SupplierSourceOut)
def patch_supplier_source(
    source_id: int,
    payload: SupplierSourcePatchIn,
    _admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    item = db.query(models.SupplierSource).filter(models.SupplierSource.id == int(source_id)).one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="source not found")

    if payload.source_url is not None:
        next_url = payload.source_url.strip()
        if not next_url:
            raise HTTPException(status_code=400, detail="source_url cannot be empty")
        item.source_url = next_url
    if payload.supplier_name is not None:
        item.supplier_name = (payload.supplier_name or "").strip() or None
    if payload.manager_name is not None:
        item.manager_name = (payload.manager_name or "").strip() or None
    if payload.manager_contact is not None:
        item.manager_contact = (payload.manager_contact or "").strip() or None
    if payload.note is not None:
        item.note = (payload.note or "").strip() or None
    if payload.active is not None:
        item.active = bool(payload.active)

    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="source_url already exists")
    db.refresh(item)
    return _to_source_out(item)


@router.delete("/supplier-intelligence/sources/{source_id}")
def delete_supplier_source(source_id: int, _admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    item = db.query(models.SupplierSource).filter(models.SupplierSource.id == int(source_id)).one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="source not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/supplier-intelligence/analyze-links", response_model=list[AnalyzeLinksOut])
def analyze_supplier_links(payload: AnalyzeLinksIn, _admin=Depends(get_current_admin_user)):
    out: list[AnalyzeLinksOut] = []
    for raw_url in payload.links:
        url = (raw_url or "").strip()
        if not url:
            continue
        try:
            out.append(_analyze_url(url))
        except Exception as exc:
            out.append(AnalyzeLinksOut(url=url, ok=False, error=str(exc)))
    return out


@router.post("/supplier-intelligence/analyze-sources", response_model=list[AnalyzeStoredSourceOut])
def analyze_stored_sources(payload: AnalyzeStoredSourcesIn, _admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    ids = [int(x) for x in payload.source_ids]
    if not ids:
        return []
    items = db.query(models.SupplierSource).filter(models.SupplierSource.id.in_(ids)).all()
    out: list[AnalyzeStoredSourceOut] = []
    for item in items:
        url = (item.source_url or "").strip()
        if not url:
            continue
        try:
            data = _analyze_url(url)
            out.append(
                AnalyzeStoredSourceOut(
                    source_id=int(item.id),
                    supplier_name=item.supplier_name,
                    manager_name=item.manager_name,
                    manager_contact=item.manager_contact,
                    **data.dict(),
                )
            )
        except Exception as exc:
            out.append(
                AnalyzeStoredSourceOut(
                    source_id=int(item.id),
                    supplier_name=item.supplier_name,
                    manager_name=item.manager_name,
                    manager_contact=item.manager_contact,
                    url=url,
                    ok=False,
                    error=str(exc),
                )
            )
    return out


class OfferIn(BaseModel):
    supplier: str
    title: str
    dropship_price: float
    color: str | None = None
    size: str | None = None
    stock: int | None = None
    manager_url: str | None = None


class BestOfferIn(BaseModel):
    desired_color: str | None = None
    desired_size: str | None = None
    offers: list[OfferIn] = Field(default_factory=list, min_items=1, max_items=100)


class BestOfferOut(BaseModel):
    supplier: str
    title: str
    dropship_price: float
    color: str | None = None
    size: str | None = None
    stock: int | None = None
    manager_url: str | None = None


@router.post("/supplier-intelligence/best-offer", response_model=BestOfferOut)
def get_best_offer(payload: BestOfferIn, _admin=Depends(get_current_admin_user)):
    offers = [
        SupplierOffer(
            supplier=o.supplier,
            title=o.title,
            color=o.color,
            size=o.size,
            dropship_price=float(o.dropship_price),
            stock=o.stock,
            manager_url=o.manager_url,
        )
        for o in payload.offers
    ]
    best = pick_best_offer(offers, desired_color=payload.desired_color, desired_size=payload.desired_size)
    if not best:
        raise HTTPException(status_code=404, detail="no offers")
    return BestOfferOut(
        supplier=best.supplier,
        title=best.title,
        dropship_price=float(best.dropship_price),
        color=best.color,
        size=best.size,
        stock=best.stock,
        manager_url=best.manager_url,
    )


class MarketPriceIn(BaseModel):
    prices: list[float] = Field(default_factory=list, min_items=1, max_items=300)


class MarketPriceOut(BaseModel):
    suggested_price: float | None


@router.post("/supplier-intelligence/estimate-market-price", response_model=MarketPriceOut)
def estimate_price(payload: MarketPriceIn, _admin=Depends(get_current_admin_user)):
    return MarketPriceOut(suggested_price=estimate_market_price(payload.prices))
