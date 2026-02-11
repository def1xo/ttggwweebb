from __future__ import annotations

import csv
import io
import re
import statistics
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, urlparse

import requests


CATEGORY_RULES: dict[str, tuple[str, ...]] = {
    "Кофты": ("худи", "zip", "зип", "толстов", "свитшот", "hoodie"),
    "Футболки": ("футбол", "tee", "t-shirt", "майка"),
    "Куртки": ("курт", "бомбер", "ветров", "пухов"),
    "Брюки": ("штаны", "брюк", "джинс", "карго", "sweatpants"),
    "Кроссовки": ("кросс", "sneaker", "кеды", "обув"),
    "Аксессуары": ("кепк", "шапк", "сумк", "ремень", "аксесс"),
}


@dataclass
class SupplierOffer:
    supplier: str
    title: str
    color: str | None
    size: str | None
    dropship_price: float
    stock: int | None = None
    manager_url: str | None = None


class _SimpleTableParser(HTMLParser):
    """Very small HTML table parser with no external deps."""

    def __init__(self) -> None:
        super().__init__()
        self._in_td = False
        self._in_th = False
        self._row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"td", "th"}:
            self._in_td = tag == "td"
            self._in_th = tag == "th"
        elif tag == "tr":
            self._row = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            self._in_td = False
            self._in_th = False
        elif tag == "tr":
            if any(x.strip() for x in self._row):
                self.rows.append([x.strip() for x in self._row])
            self._row = []

    def handle_data(self, data: str) -> None:
        if not (self._in_td or self._in_th):
            return
        value = data.strip()
        if not value:
            return
        if not self._row:
            self._row.append(value)
        else:
            self._row[-1] = f"{self._row[-1]} {value}".strip()


def detect_source_kind(url: str) -> str:
    u = (url or "").lower()
    if "docs.google.com/spreadsheets" in u:
        return "google_sheet"
    if "moysklad" in u:
        return "moysklad_catalog"
    if "t.me/" in u or "telegram.me/" in u:
        return "telegram_channel"
    return "generic_html"


def _normalize_google_sheet_csv(url: str) -> str:
    parsed = urlparse(url)
    if "docs.google.com" not in parsed.netloc or "/spreadsheets/" not in parsed.path:
        return url

    m = re.search(r"/d/([^/]+)/", parsed.path)
    if not m:
        return url
    sheet_id = m.group(1)
    q = parse_qs(parsed.query)
    gid = q.get("gid", [None])[0]

    export = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        export += f"&gid={gid}"
    return export


def fetch_tabular_preview(url: str, timeout_sec: int = 20, max_rows: int = 25) -> dict[str, Any]:
    kind = detect_source_kind(url)
    fetch_url = _normalize_google_sheet_csv(url) if kind == "google_sheet" else url

    headers = {"User-Agent": "defshop-intel-bot/1.0"}
    resp = requests.get(fetch_url, timeout=timeout_sec, headers=headers)
    resp.raise_for_status()

    ct = (resp.headers.get("content-type") or "").lower()
    body = resp.text

    rows: list[list[str]] = []
    if "text/csv" in ct or fetch_url.endswith("format=csv"):
        reader = csv.reader(io.StringIO(body))
        for i, row in enumerate(reader):
            rows.append([str(x).strip() for x in row])
            if i + 1 >= max_rows:
                break
    else:
        parser = _SimpleTableParser()
        parser.feed(body)
        rows = parser.rows[:max_rows]

    return {
        "kind": kind,
        "fetch_url": fetch_url,
        "status_code": resp.status_code,
        "content_type": ct,
        "rows_preview": rows,
        "rows_count_preview": len(rows),
    }


def map_category(raw_title: str) -> str:
    t = (raw_title or "").strip().lower()
    if not t:
        return "Разное"
    for cat, keywords in CATEGORY_RULES.items():
        if any(k in t for k in keywords):
            return cat
    return "Разное"


def _clean_market_price_values(values: Iterable[float]) -> list[float]:
    cleaned: list[float] = []
    for v in values:
        try:
            num = float(v)
        except Exception:
            continue
        if num <= 1 or num >= 1_000_000:
            continue
        cleaned.append(num)
    return cleaned


def estimate_market_price(values: Iterable[float]) -> Optional[float]:
    """
    Robust market price estimator:
    - drop fake outliers (<=1 and >=1_000_000)
    - trim by IQR fences
    - take median
    """
    arr = sorted(_clean_market_price_values(values))
    if not arr:
        return None
    if len(arr) < 4:
        return round(float(statistics.median(arr)), 2)

    q1 = statistics.quantiles(arr, n=4, method="inclusive")[0]
    q3 = statistics.quantiles(arr, n=4, method="inclusive")[2]
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr

    trimmed = [x for x in arr if low <= x <= high]
    if not trimmed:
        trimmed = arr
    return round(float(statistics.median(trimmed)), 2)


def pick_best_offer(
    offers: list[SupplierOffer],
    desired_color: str | None = None,
    desired_size: str | None = None,
) -> SupplierOffer | None:
    if not offers:
        return None

    color = (desired_color or "").strip().lower()
    size = (desired_size or "").strip().lower()

    def score(o: SupplierOffer) -> tuple[int, int, float]:
        color_ok = (not color) or ((o.color or "").strip().lower() == color)
        size_ok = (not size) or ((o.size or "").strip().lower() == size)
        stock = o.stock if isinstance(o.stock, int) else 0
        # better score => lower tuple
        return (
            0 if color_ok else 1,
            0 if size_ok else 1,
            float(o.dropship_price),
        )

    sorted_offers = sorted(offers, key=score)
    # if exact color/size required and nothing matches, fallback to cheapest available
    exact = [
        o
        for o in sorted_offers
        if (not color or (o.color or "").strip().lower() == color)
        and (not size or (o.size or "").strip().lower() == size)
    ]
    if exact:
        return min(exact, key=lambda x: float(x.dropship_price))
    in_stock = [o for o in sorted_offers if (o.stock or 0) > 0]
    if in_stock:
        return min(in_stock, key=lambda x: float(x.dropship_price))
    return min(sorted_offers, key=lambda x: float(x.dropship_price))
