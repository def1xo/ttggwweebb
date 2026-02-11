from __future__ import annotations

import csv
import io
import re
import statistics
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, urlparse

import requests


def _safe_timeout(timeout_sec: int | float) -> tuple[float, float]:
    t = max(1.0, float(timeout_sec or 20))
    # split connect/read timeout to fail fast on bad endpoints
    return (min(5.0, t), max(1.0, t))


def _http_get_with_retries(
    url: str,
    *,
    timeout_sec: int = 20,
    headers: dict[str, str] | None = None,
    max_attempts: int = 3,
    backoff_sec: float = 0.35,
) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            resp = requests.get(url, timeout=_safe_timeout(timeout_sec), headers=headers)
            # retry on transient server/rate-limit responses
            if resp.status_code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                time.sleep(backoff_sec * attempt)
                continue
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            time.sleep(backoff_sec * attempt)
    raise RuntimeError(f"request failed after retries for {url}") from last_exc


def _download_image_bytes(url: str, timeout_sec: int = 20, max_bytes: int = 6_000_000) -> bytes:
    headers = {"User-Agent": "defshop-intel-bot/1.0"}
    r = _http_get_with_retries(url, timeout_sec=timeout_sec, headers=headers, max_attempts=3)
    content_type = (r.headers.get("content-type") or "").lower()
    if content_type and "image" not in content_type:
        raise RuntimeError("url is not an image resource")
    data = r.content or b""
    if len(data) > int(max_bytes):
        raise RuntimeError("image is too large for analysis")
    return data


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






def _fix_common_mojibake(value: str) -> str:
    s = str(value or "")
    if not s:
        return s
    if "Ð" in s or "Ñ" in s:
        try:
            repaired = s.encode("latin-1").decode("utf-8")
            if repaired.count("�") <= s.count("�"):
                return repaired
        except Exception:
            return s
    return s

def _response_text(resp: requests.Response) -> str:
    if not resp.content:
        return ""
    for enc in [resp.encoding, getattr(resp, "apparent_encoding", None), "utf-8", "cp1251", "latin-1"]:
        if not enc:
            continue
        try:
            return resp.content.decode(enc, errors="replace")
        except Exception:
            continue
    return resp.text

def fetch_tabular_preview(url: str, timeout_sec: int = 20, max_rows: int = 25) -> dict[str, Any]:
    kind = detect_source_kind(url)
    fetch_url = _normalize_google_sheet_csv(url) if kind == "google_sheet" else url

    headers = {"User-Agent": "defshop-intel-bot/1.0"}
    resp = _http_get_with_retries(fetch_url, timeout_sec=timeout_sec, headers=headers, max_attempts=3)

    ct = (resp.headers.get("content-type") or "").lower()
    body = _response_text(resp)

    rows: list[list[str]] = []
    if "text/csv" in ct or fetch_url.endswith("format=csv"):
        reader = csv.reader(io.StringIO(body))
        for i, row in enumerate(reader):
            rows.append([_fix_common_mojibake(str(x).strip()) for x in row])
            if i + 1 >= max_rows:
                break
    else:
        parser = _SimpleTableParser()
        parser.feed(body)
        rows = [[_fix_common_mojibake(x) for x in row] for row in parser.rows[:max_rows]]

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


def _norm(s: Any) -> str:
    return str(s or "").strip()


def _to_float(raw: Any) -> float | None:
    s = _norm(raw).replace(" ", "").replace("₽", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _to_int(raw: Any) -> int | None:
    f = _to_float(raw)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def _find_col(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    h = [x.strip().lower() for x in headers]
    for i, col in enumerate(h):
        if any(c in col for c in candidates):
            return i
    return None




def _find_col_priority(headers: list[str], groups: tuple[tuple[str, ...], ...]) -> int | None:
    lowered = [x.strip().lower() for x in headers]
    for group in groups:
        idx = _find_col(lowered, group)
        if idx is not None:
            return idx
    return None


def _pick_price_column(headers: list[str]) -> int | None:
    return _find_col_priority(
        headers,
        (
            ("дроп", "dropship", "drop ship", "ds"),
            ("drop",),
            ("price", "цена", "стоим"),
            ("опт", "wholesale"),
        ),
    )

def extract_catalog_items(rows: list[list[str]], max_items: int = 60) -> list[dict[str, Any]]:
    if not rows:
        return []

    headers = [str(x or "").strip() for x in rows[0]]
    body = rows[1:] if len(rows) > 1 else []

    idx_title = _find_col(headers, ("товар", "назв", "title", "item", "модель"))
    idx_price = _pick_price_column(headers)
    idx_color = _find_col(headers, ("цвет", "color"))
    idx_size = _find_col(headers, ("размер", "size"))
    idx_stock = _find_col(headers, ("остат", "налич", "stock", "qty", "кол-во"))
    idx_image = _find_col(headers, ("фото", "image", "img", "картин"))
    idx_desc = _find_col(headers, ("опис", "desc", "description"))

    # if header row is not real header, fallback to positional guess
    if idx_title is None and body:
        idx_title = 0
    if idx_price is None and len(headers) >= 2:
        idx_price = 1

    out: list[dict[str, Any]] = []
    for row in body:
        if len(out) >= max_items:
            break
        title = _norm(row[idx_title]) if idx_title is not None and idx_title < len(row) else ""
        if not title:
            continue
        price = _to_float(row[idx_price]) if idx_price is not None and idx_price < len(row) else None
        if price is None or price <= 0:
            continue
        color = _norm(row[idx_color]) if idx_color is not None and idx_color < len(row) else ""
        size = _norm(row[idx_size]) if idx_size is not None and idx_size < len(row) else ""
        stock = _to_int(row[idx_stock]) if idx_stock is not None and idx_stock < len(row) else None
        image_url = _norm(row[idx_image]) if idx_image is not None and idx_image < len(row) else ""
        description = _norm(row[idx_desc]) if idx_desc is not None and idx_desc < len(row) else ""

        out.append({
            "title": title,
            "dropship_price": float(price),
            "color": color or None,
            "size": size or None,
            "stock": stock,
            "image_url": image_url or None,
            "description": description or None,
        })
    return out


def generate_youth_description(title: str, category_name: str | None = None, color: str | None = None) -> str:
    t = _norm(title)
    cat = _norm(category_name) or "лук"
    clr = _norm(color)
    mood = ""
    if clr:
        mood = f" Цвет: {clr}."
    return (
        f"{t} — вайбовый {cat.lower()} для повседневного стрит-стайла. "
        f"Лёгко собирается в образ под универ, прогулки и вечерние вылазки.{mood} "
        f"Сидит актуально, смотрится дорого, а носится каждый день без заморочек."
    )


def suggest_sale_price(dropship_price: float) -> float:
    base = max(0.0, float(dropship_price))
    if base <= 0:
        return 0.0
    # conservative markup for retail target
    return round(base * 1.55, 0)


def extract_image_urls_from_html_page(url: str, timeout_sec: int = 20, limit: int = 20) -> list[str]:
    headers = {"User-Agent": "defshop-intel-bot/1.0"}
    r = _http_get_with_retries(url, timeout_sec=timeout_sec, headers=headers, max_attempts=3)
    html = r.text or ""

    urls: list[str] = []

    # og/twitter image meta
    for m in re.findall(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I):
        u = str(m).strip()
        if u and u not in urls:
            urls.append(u)

    # plain img src
    for m in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I):
        u = str(m).strip()
        if not u:
            continue
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("/"):
            parsed = urlparse(url)
            u = f"{parsed.scheme}://{parsed.netloc}{u}"
        if u not in urls:
            urls.append(u)
        if len(urls) >= limit:
            break
    return urls[:limit]


def _load_image_for_analysis(image_bytes: bytes):
    try:
        from PIL import Image  # type: ignore
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise RuntimeError("Pillow is required for image analysis. Add pillow to backend requirements.") from exc


def image_print_signature_from_url(url: str, timeout_sec: int = 20) -> str | None:
    try:
        img = _load_image_for_analysis(_download_image_bytes(url, timeout_sec=timeout_sec))

        # simple average hash 8x8
        gray = img.convert("L").resize((8, 8))
        px = list(gray.getdata())
        if not px:
            return None
        avg = sum(px) / len(px)
        bits = "".join("1" if p >= avg else "0" for p in px)
        # hex string
        out = ""
        for i in range(0, len(bits), 4):
            out += f"{int(bits[i:i+4], 2):x}"
        return out
    except Exception:
        return None


def dominant_color_name_from_url(url: str, timeout_sec: int = 20) -> str | None:
    try:
        img = _load_image_for_analysis(_download_image_bytes(url, timeout_sec=timeout_sec))

        small = img.resize((64, 64))
        rs = gs = bs = 0
        n = 0
        for (rr, gg, bb) in list(small.getdata()):
            rs += int(rr)
            gs += int(gg)
            bs += int(bb)
            n += 1
        if n <= 0:
            return None
        r_avg = rs / n
        g_avg = gs / n
        b_avg = bs / n

        # coarse color naming
        mx = max(r_avg, g_avg, b_avg)
        mn = min(r_avg, g_avg, b_avg)
        if mx < 45:
            return "черный"
        if mn > 215:
            return "белый"
        if abs(r_avg - g_avg) < 15 and abs(g_avg - b_avg) < 15:
            return "серый"
        if r_avg > g_avg * 1.18 and r_avg > b_avg * 1.18:
            return "красный"
        if g_avg > r_avg * 1.18 and g_avg > b_avg * 1.18:
            return "зеленый"
        if b_avg > r_avg * 1.18 and b_avg > g_avg * 1.18:
            return "синий"
        if r_avg > 150 and g_avg > 125 and b_avg < 120:
            return "желтый"
        if r_avg > 135 and b_avg > 120 and g_avg < 120:
            return "фиолетовый"
        return "мульти"
    except Exception:
        return None


def _extract_prices_from_text(text: str) -> list[float]:
    out: list[float] = []
    for m in re.findall(r"(\d[\d\s]{1,9})\s?₽", text or ""):
        s = str(m).replace(" ", "")
        try:
            out.append(float(s))
        except Exception:
            continue
    return out


def avito_market_scan(query: str, max_pages: int = 1, timeout_sec: int = 20) -> dict[str, Any]:
    """Best-effort scan of Avito search pages (can fail due to anti-bot)."""
    q = (query or "").strip()
    if not q:
        return {"query": q, "prices": [], "suggested": None, "errors": ["empty query"]}

    errors: list[str] = []
    prices: list[float] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Mobile Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    pages = max(1, min(int(max_pages or 1), 3))
    for page in range(1, pages + 1):
        try:
            url = f"https://www.avito.ru/rossiya?cd=1&p={page}&q={requests.utils.quote(q)}"
            r = _http_get_with_retries(url, timeout_sec=timeout_sec, headers=headers, max_attempts=3)
            txt = r.text or ""
            found = _extract_prices_from_text(txt)
            prices.extend(found)
            if not found:
                errors.append(f"page {page}: no prices parsed")
        except Exception as exc:
            errors.append(f"page {page}: {exc}")

    suggested = estimate_market_price(prices)
    return {
        "query": q,
        "pages": pages,
        "prices": prices,
        "suggested": suggested,
        "errors": errors,
    }


def print_signature_hamming(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    aa = str(a).strip().lower()
    bb = str(b).strip().lower()
    if len(aa) != len(bb):
        return None
    try:
        return sum(1 for x, y in zip(aa, bb) if x != y)
    except Exception:
        return None
