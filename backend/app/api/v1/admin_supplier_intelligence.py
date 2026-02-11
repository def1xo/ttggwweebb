from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl
from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_current_admin_user
from app.services.supplier_intelligence import (
    SupplierOffer,
    estimate_market_price,
    fetch_tabular_preview,
    map_category,
    pick_best_offer,
)

router = APIRouter(tags=["admin_supplier_intelligence"])


class AnalyzeLinksIn(BaseModel):
    links: list[str] = Field(default_factory=list, min_items=1, max_items=30)


class AnalyzeLinksOut(BaseModel):
    url: str
    ok: bool
    kind: str | None = None
    status_code: int | None = None
    rows_count_preview: int | None = None
    sample_rows: list[list[str]] = Field(default_factory=list)
    mapped_categories_sample: list[str] = Field(default_factory=list)
    error: str | None = None


@router.post("/supplier-intelligence/analyze-links", response_model=list[AnalyzeLinksOut])
def analyze_supplier_links(payload: AnalyzeLinksIn, _admin=Depends(get_current_admin_user)):
    out: list[AnalyzeLinksOut] = []
    for raw_url in payload.links:
        url = (raw_url or "").strip()
        if not url:
            continue
        try:
            data = fetch_tabular_preview(url)
            rows = data.get("rows_preview") or []
            sample_titles = []
            for r in rows[:8]:
                if r:
                    sample_titles.append(str(r[0]))
            categories = [map_category(t) for t in sample_titles if t]
            out.append(
                AnalyzeLinksOut(
                    url=url,
                    ok=True,
                    kind=str(data.get("kind") or ""),
                    status_code=int(data.get("status_code") or 0),
                    rows_count_preview=int(data.get("rows_count_preview") or 0),
                    sample_rows=rows[:8],
                    mapped_categories_sample=categories,
                )
            )
        except Exception as exc:
            out.append(
                AnalyzeLinksOut(
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
