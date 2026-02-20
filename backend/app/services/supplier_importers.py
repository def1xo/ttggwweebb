from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.services.supplier_intelligence import detect_source_kind, extract_catalog_items, fetch_tabular_preview, split_size_tokens


@dataclass
class ImporterContext:
    source_url: str
    supplier_name: str | None
    max_items: int
    fetch_timeout_sec: int


class BaseSupplierImporter:
    """Unified importer contract for supplier sources."""

    def fetch(self, ctx: ImporterContext) -> list[dict[str, Any]]:
        return self.fetch_rows(ctx)

    def fetch_rows(self, ctx: ImporterContext) -> list[dict[str, Any]]:
        raise NotImplementedError

    def parse_row(self, row: dict[str, Any], ctx: ImporterContext) -> dict[str, Any] | None:
        raise NotImplementedError

    def normalize(self, row: dict[str, Any], ctx: ImporterContext) -> dict[str, Any] | None:
        return self.parse_row(row, ctx)

    def group_rows(self, rows: list[dict[str, Any]], ctx: ImporterContext) -> list[dict[str, Any]]:
        return rows

    def group(self, rows: list[dict[str, Any]], ctx: ImporterContext) -> list[dict[str, Any]]:
        return self.group_rows(rows, ctx)

    def upsert(self, row: dict[str, Any], upsert_fn, ctx: ImporterContext) -> Any:
        return upsert_fn(row, ctx)

    def resolve_photos(self, links: list[str], resolver_fn, limit: int = 20) -> tuple[list[str], str]:
        return resolve_tg_photos(links, resolver_fn, limit=limit)

    def normalize_price(self, raw: Any) -> float:
        try:
            v = float(raw or 0)
        except Exception:
            return 0.0
        return max(0.0, v)

    def normalize_sizes(self, raw: Any) -> list[str]:
        vals = [str(x).strip() for x in split_size_tokens(raw) if str(x).strip()]
        seen: set[str] = set()
        out: list[str] = []
        for x in vals:
            k = x.replace(",", ".")
            if k in seen:
                continue
            seen.add(k)
            out.append(k)
        return out

    def dedup_images(self, urls: Iterable[Any]) -> list[str]:
        out: list[str] = []
        for u in urls:
            s = str(u or "").strip()
            if not s or s in out:
                continue
            out.append(s)
        return out


class TabularSupplierImporter(BaseSupplierImporter):
    def __init__(self, fetch_preview_fn=None, extract_items_fn=None):
        self._fetch_preview_fn = fetch_preview_fn or fetch_tabular_preview
        self._extract_items_fn = extract_items_fn or extract_catalog_items

    def fetch_rows(self, ctx: ImporterContext) -> list[dict[str, Any]]:
        preview = self._fetch_preview_fn(
            ctx.source_url,
            timeout_sec=ctx.fetch_timeout_sec,
            max_rows=max(5, ctx.max_items + 1),
        )
        rows = preview.get("rows_preview") or []
        return self._extract_items_fn(rows, max_items=ctx.max_items)

    def parse_row(self, row: dict[str, Any], ctx: ImporterContext) -> dict[str, Any] | None:
        title = str(row.get("title") or "").strip()
        if not title:
            return None
        parsed = dict(row)
        parsed["dropship_price"] = self.normalize_price(parsed.get("dropship_price"))
        parsed["size_tokens"] = self.normalize_sizes(parsed.get("size"))
        parsed["image_urls"] = self.dedup_images(parsed.get("image_urls") or [])
        return parsed


class ShopVkusImporter(TabularSupplierImporter):
    pass


class FirmachDropImporter(TabularSupplierImporter):
    pass


class ProfitDropImporter(TabularSupplierImporter):
    pass


class VenomImporter(TabularSupplierImporter):
    pass


class EmpireImporter(TabularSupplierImporter):
    pass


class OptobazaImporter(TabularSupplierImporter):
    pass


class HHHBImporter(TabularSupplierImporter):
    pass


def resolve_tg_photos(links: list[str], resolver_fn, limit: int = 20) -> tuple[list[str], str]:
    refs = [str(x).strip() for x in links if str(x or "").strip()]
    if not refs:
        return ([], "pending")
    out: list[str] = []
    for ref in refs:
        if not re.search(r"(?:t\.me|telegram\.me)/", ref, flags=re.I):
            continue
        try:
            photos = resolver_fn(ref, limit=limit) or []
        except Exception:
            photos = []
        for u in photos:
            su = str(u or "").strip()
            if su and su not in out:
                out.append(su)
    return (out, "resolved" if out else "pending")


def get_supplier_importer(supplier_name: str | None) -> BaseSupplierImporter:
    key = re.sub(r"\s+", " ", str(supplier_name or "").strip().lower())
    if key == "shop_vkus":
        return ShopVkusImporter()
    if key in {"фирмач дроп", "firmachdroppp", "firmach drop"}:
        return FirmachDropImporter()
    if key in {"профит дроп", "profit drop", "profitdrop"}:
        return ProfitDropImporter()
    if key == "venom":
        return VenomImporter()
    if key == "empire":
        return EmpireImporter()
    if key in {"оптобаза", "optobaza"}:
        return OptobazaImporter()
    if key in {"hhhb", "hhhв"}:
        return HHHBImporter()
    return TabularSupplierImporter()


def get_importer_for_source(source_url: str, supplier_name: str | None) -> BaseSupplierImporter:
    if detect_source_kind(source_url) in {"google_sheet", "moysklad_catalog", "generic_html"}:
        return get_supplier_importer(supplier_name)
    return TabularSupplierImporter()
