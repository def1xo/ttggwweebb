from __future__ import annotations

import csv
import io
import json
import os
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
    "Куртки": ("курт", "бомбер", "ветров", "пухов", "жилет", "vest"),
    "Брюки": ("штаны", "брюк", "джинс", "карго", "sweatpants"),
    "Шорты": ("шорт", "shorts"),
    "Рубашки": ("рубаш", "shirt"),
    "Лонгсливы": ("лонгслив", "longsleeve", "long sleeve"),
    "Свитера": ("свитер", "джемпер", "pullover", "костюм", "suit", "set"),
    "Обувь": (
        "кросс", "sneaker", "кеды", "обув", "ботин", "лофер", "сланц",
        "new balance", "nb ", "nike", "adidas", "asics", "puma", "reebok", "jordan", "yeezy",
        "air force", "air max", "vomero", "retropy", "samba", "gazelle", "campus",
    ),
    "Аксессуары": ("кепк", "шапк", "сумк", "ремень", "аксесс", "рюкзак", "кошелек", "wallet", "bag"),
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
        return "Аксессуары"
    for cat, keywords in CATEGORY_RULES.items():
        if any(k in t for k in keywords):
            return cat
    return "Аксессуары"


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
    s = _norm(raw)
    if not s:
        return None
    s = s.replace(" ", " ").replace("₽", " ").replace("руб", " ").replace("RUB", " ")
    m = re.search(r"-?\d[\d\s.,]*", s)
    if not m:
        return None
    token = m.group(0).strip().replace(" ", "")
    if not token:
        return None

    # 1) explicit thousand grouping: 1,399 / 3.099 / 12 999
    if re.fullmatch(r"-?\d{1,3}(?:[.,]\d{3})+", token):
        try:
            return float(token.replace(",", "").replace(".", ""))
        except Exception:
            return None

    # 2) classic decimal forms: 1299.50 / 1299,50
    if re.fullmatch(r"-?\d+[.,]\d{1,2}", token):
        try:
            return float(token.replace(",", "."))
        except Exception:
            return None

    # 3) ambiguous single separator with 3 trailing digits (common thousand format in supplier sheets)
    if re.fullmatch(r"-?\d+[.,]\d{3}", token):
        try:
            return float(token.replace(",", "").replace(".", ""))
        except Exception:
            return None

    # 4) fallback: remove separators and parse as integer-like value
    compact = token.replace(",", "").replace(".", "")
    if not re.fullmatch(r"-?\d+", compact):
        return None
    try:
        return float(compact)
    except Exception:
        return None


def _price_candidates_from_row(row: list[Any], exclude_indices: set[int] | None = None) -> list[float]:
    ex = exclude_indices or set()
    out: list[float] = []
    for idx, cell in enumerate(row):
        if idx in ex:
            continue
        val = _to_float(cell)
        if val is None:
            continue
        if val <= 0 or val >= 500_000:
            continue
        out.append(float(val))
    return out


def _coerce_row_price(primary_price: float | None, row: list[Any], *, exclude_indices: set[int] | None = None) -> float | None:
    if primary_price is None:
        candidates = _price_candidates_from_row(row, exclude_indices=exclude_indices)
        if not candidates:
            return None
        primary_price = max(candidates)

    if primary_price >= 300:
        return float(primary_price)

    candidates = _price_candidates_from_row(row, exclude_indices=exclude_indices)
    large = [x for x in candidates if x >= 500]
    if large:
        return float(max(large))
    return float(primary_price)

def _to_int(raw: Any) -> int | None:
    f = _to_float(raw)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def _normalize_image_candidate(url: str) -> str | None:
    u = str(url or "").strip().strip("\"'()[]{}<>")
    if not u:
        return None
    if u.startswith("//"):
        u = "https:" + u
    elif u.lower().startswith("www."):
        u = "https://" + u
    if not re.match(r"^https?://", u, flags=re.I):
        return None
    return u


def _split_image_urls(raw: Any) -> list[str]:
    txt = _norm(raw)
    if not txt:
        return []

    out: list[str] = []

    # collect explicit urls first (handles markdown/text with punctuation)
    for m in re.findall(r'((?:https?:)?//[^\s,;|)\]>\'"]+)', txt, flags=re.I):
        u = _normalize_image_candidate(m)
        if u and u not in out:
            out.append(u)

    # fallback tokenization for plain cells
    for chunk in re.split(r"[\s,;|]+", txt):
        u = _normalize_image_candidate(chunk)
        if u and u not in out:
            out.append(u)

    return out


def _row_fallback_images(row: list[str]) -> list[str]:
    out: list[str] = []
    for cell in row:
        for u in _split_image_urls(cell):
            if u not in out:
                out.append(u)
    return out


def _extract_size_from_title(title: str) -> str | None:
    t = str(title or "")
    if not t:
        return None
    # textual sizes are safe to infer directly
    text_m = re.search(r"(?i)\b(XXS|XS|S|M|L|XL|XXL|XXXL)\b", t)
    if text_m:
        return str(text_m.group(1)).upper()

    # explicit numeric marker is highest priority
    num_m = re.search(r"(?i)\b(?:size|размер|eu|us|ru)\s*[:#-]?\s*(\d{2,3})\b", t)
    if num_m:
        try:
            val = int(num_m.group(1))
            if 18 <= val <= 60:
                return str(val)
        except Exception:
            return None

    # fallback for footwear-like titles: trailing 2-digit token (e.g. "NB 9060 black 42")
    # keeps model numbers in middle ("Yeezy 350 v2") from becoming size.
    if re.search(r"(?i)\b(yeezy|air\s*max|jordan|nike|adidas|new\s*balance|nb|sneaker|крос|кед)\b", t):
        tail_m = re.search(r"\b(\d{2})\s*$", t)
        if tail_m:
            try:
                val = int(tail_m.group(1))
                if 30 <= val <= 60:
                    return str(val)
            except Exception:
                return None

    return None


def _extract_size_from_row_text(row: list[str]) -> str | None:
    text = " ".join([_norm(x) for x in (row or []) if _norm(x)])
    if not text:
        return None

    # Parse sizes only from explicit size-marked fragments.
    # Avoid scanning the whole row blindly to prevent pollution by prices/codes
    # (e.g. 24/25/28 leaking into size grid).
    matches = re.findall(r"(?i)(?:размер(?:ы)?|size)\s*[:#-]?\s*([^\n]+)", text)
    out: list[str] = []
    for chunk in matches:
        cleaned = re.split(
            r"(?i)\b(?:цена|стоимость|руб|ррц|rrc|мрц|mrc|наличие|остаток|stock|арт(?:икул)?|код)\b",
            chunk,
            maxsplit=1,
        )[0]
        for tok in split_size_tokens(cleaned):
            if tok not in out:
                out.append(tok)
    if out:
        return " ".join(out[:12])
    return None


def split_size_tokens(raw: Any) -> list[str]:
    txt = _norm(raw).upper()
    if not txt:
        return []
    txt = re.sub(r"(?i)\b(?:РАЗМЕРЫ?|SIZE|SIZES?)\b", " ", txt)
    txt = txt.replace("–", "-").replace("—", "-").replace("−", "-")
    out: list[str] = []

    def _push(token: str) -> None:
        if token and token not in out:
            out.append(token)

    # numeric ranges in any textual form, e.g. "41-45", "41–45"
    for a, b in re.findall(r"\b(\d{2,3})\s*-\s*(\d{2,3})\b", txt):
        try:
            aa = int(a)
            bb = int(b)
        except Exception:
            continue
        if aa <= bb and bb - aa <= 20:
            for size_num in range(aa, bb + 1):
                _push(str(size_num))

    for chunk in re.split(r"[\s,;|/]+", txt):
        token = chunk.strip().strip(".")
        if not token:
            continue

        if "-" in token and re.match(r"^[0-9]{2,3}-[0-9]{2,3}$", token):
            continue

        cleaned = re.sub(r"[^A-Z0-9+-]", "", token)
        if not cleaned:
            continue
        if re.match(r"^(XXS|XS|S|M|L|XL|XXL|XXXL|\d{2,3})$", cleaned):
            _push(cleaned)

    # fallback parser for formats like "46(S)-✅ 48(M)-✅ 50(L)-✅"
    for token in re.findall(r"\b(XXS|XS|S|M|L|XL|XXL|XXXL|\d{2,3})\b", txt):
        _push(token)

    # If supplier row contains paired numeric + letter labels (e.g. 46(S)),
    # keep numeric sizes to avoid duplicate variants like 46 and S.
    numeric_count = sum(1 for x in out if re.fullmatch(r"\d{2,3}", x))
    if numeric_count >= 2:
        out = [x for x in out if re.fullmatch(r"\d{2,3}", x)]

    return out


_COLOR_CANONICAL_MAP: tuple[tuple[str, str], ...] = (
    ("крас", "красный"),
    ("red", "красный"),
    ("син", "синий"),
    ("blue", "синий"),
    ("голуб", "голубой"),
    ("green", "зеленый"),
    ("зелен", "зеленый"),
    ("black", "черный"),
    ("черн", "черный"),
    ("white", "белый"),
    ("бел", "белый"),
    ("gray", "серый"),
    ("grey", "серый"),
    ("сер", "серый"),
    ("pink", "розовый"),
    ("роз", "розовый"),
    ("beige", "бежевый"),
    ("беж", "бежевый"),
)




MIN_REASONABLE_DROPSHIP_PRICE = 300
MIN_ABSOLUTE_DROPSHIP_PRICE = 100


def _is_size_only_title(text: str) -> bool:
    t = str(text or "").strip().upper()
    if not t:
        return False
    compact = re.sub(r"[\s\-/]+", "", t)
    if re.fullmatch(r"\d{2,3}", compact):
        return True
    if re.fullmatch(r"(?:XXS|XS|S|M|L|XL|XXL|XXXL|\dXL|\dXl|\dxl)+", compact):
        return True
    if re.fullmatch(r"(?:XXS|XS|S|M|L|XL|XXL|XXXL|\dXL)(?:[,;/|](?:XXS|XS|S|M|L|XL|XXL|XXXL|\dXL))*", t):
        return True
    return False


def _is_noise_title(text: str) -> bool:
    t = str(text or "").strip().lower()
    if not t:
        return True
    noise_tokens = (
        "в наличии",
        "наличие",
        "дроп цена",
        "drop price",
        "оба цвета",
        "1 цвет",
        "2 цвет",
        "3 цвет",
        "4 цвет",
        "цена:",
        "цена ",
    )
    if any(tok in t for tok in noise_tokens):
        return True
    if _is_size_only_title(t):
        return True
    return False

def _looks_like_title(text: str) -> bool:
    t = str(text or "").strip()
    if len(t) < 3:
        return False
    if re.match(r"^https?://", t, flags=re.I):
        return False
    if re.fullmatch(r"[\d\s.,:/-]+", t):
        return False
    if _is_noise_title(t):
        return False
    return bool(re.search(r"[A-Za-zА-Яа-яЁё]", t))


def _row_fallback_title(row: list[str]) -> str:
    for cell in row:
        c = _norm(cell)
        if _looks_like_title(c):
            return c
    return ""


def _extract_color_from_title(title: str) -> tuple[str, str | None]:
    raw = str(title or "").strip()
    if not raw:
        return "", None

    tokens = [t for t in re.split(r"[\s/|,;()\[\]-]+", raw) if t]
    if not tokens:
        return raw, None

    last = tokens[-1].lower()
    color: str | None = None
    for needle, canonical in _COLOR_CANONICAL_MAP:
        if last.startswith(needle):
            color = canonical
            break

    if not color:
        return raw, None

    cleaned = re.sub(r"[\s/|,;()\[\]-]+$", "", raw)
    cleaned = re.sub(rf"(?i)(?:[\s/|,;()\[\]-]+){re.escape(tokens[-1])}$", "", cleaned).strip()
    return (cleaned or raw), color

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




def _is_non_purchase_price_header(header: str) -> bool:
    h = (header or "").strip().lower()
    if not h:
        return False
    blocked_tokens = ("ррц", "rrc", "мрц", "mrc", "розниц", "retail", "market")
    return any(token in h for token in blocked_tokens)

def _pick_price_column(headers: list[str]) -> int | None:
    normalized = [str(x or "").strip().lower() for x in headers]

    # 1) explicit dropship column always wins
    for i, col in enumerate(normalized):
        if any(token in col for token in ("дроп", "dropship", "drop ship", "drop")):
            return i

    # 2) fallback to generic purchase-like price columns, but skip RRC/MRC/retail
    generic = _find_col_priority(headers, (("price", "цена", "стоим", "опт", "wholesale"),))
    if generic is not None and not _is_non_purchase_price_header(normalized[generic]):
        return generic

    for i, col in enumerate(normalized):
        if _is_non_purchase_price_header(col):
            continue
        if any(token in col for token in ("опт", "wholesale", "price", "цена", "стоим")):
            return i
    return None

def extract_catalog_items(rows: list[list[str]], max_items: int = 60) -> list[dict[str, Any]]:
    if not rows:
        return []

    headers = [str(x or "").strip() for x in rows[0]]
    body = rows[1:] if len(rows) > 1 else []

    idx_title = _find_col(headers, ("товар", "назв", "title", "item", "модель", "наимен", "product", "позиц"))
    idx_price = _pick_price_column(headers)
    idx_rrc = _find_col(headers, ("ррц", "rrc", "мрц", "mrc", "розниц", "retail"))
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
        if not _looks_like_title(title):
            title = _row_fallback_title(row)
        if not _looks_like_title(title):
            continue

        raw_price = _to_float(row[idx_price]) if idx_price is not None and idx_price < len(row) else None
        excluded = {x for x in [idx_title, idx_size, idx_stock] if x is not None}
        price = _coerce_row_price(raw_price, row, exclude_indices=excluded)
        if price is None or price < MIN_ABSOLUTE_DROPSHIP_PRICE:
            continue

        # Some supplier sheets contain legitimately low wholesale prices
        # (e.g. accessories), so do not hard-drop them if they are >=100.
        if price < MIN_REASONABLE_DROPSHIP_PRICE:
            excluded_low = {x for x in [idx_title, idx_size, idx_stock] if x is not None}
            alt_low = [
                x
                for x in _price_candidates_from_row(row, exclude_indices=excluded_low)
                if x >= MIN_REASONABLE_DROPSHIP_PRICE
            ]
            if alt_low:
                price = float(max(alt_low))

        # Footwear sanity check: very low prices (e.g. 799) are often wrong columns
        # in mixed supplier sheets where wholesale is in another numeric field.
        if re.search(r"(?i)\b(new\s*balance|nb\s*\d|nike|adidas|jordan|yeezy|air\s*max|vomero|samba|gazelle|campus|574|9060|1906|2002)\b", title) and price < 1200:
            excluded_with_price = set(excluded)
            if idx_price is not None:
                excluded_with_price.add(idx_price)
            alt_footwear = [
                x
                for x in _price_candidates_from_row(row, exclude_indices=excluded_with_price)
                if 1200 <= x <= 9_999
            ]
            if alt_footwear:
                price = float(min(alt_footwear))

        # Guard against accidentally selected retail-like column.
        # If picked price is very high, but the row contains plausible purchase price,
        # prefer that lower candidate.
        if price >= 10_000:
            exclude_with_price = set(excluded)
            if idx_price is not None:
                exclude_with_price.add(idx_price)
            alt_candidates = [
                x
                for x in _price_candidates_from_row(row, exclude_indices=exclude_with_price)
                if 300 <= x <= 9_999
            ]
            if alt_candidates:
                price = float(max(alt_candidates))

        rrc_price = _to_float(row[idx_rrc]) if idx_rrc is not None and idx_rrc < len(row) else None
        color = _norm(row[idx_color]) if idx_color is not None and idx_color < len(row) else ""
        normalized_title, inferred_color = _extract_color_from_title(title)
        if _looks_like_title(normalized_title):
            title = normalized_title
        if not color and inferred_color:
            color = inferred_color

        size = _norm(row[idx_size]) if idx_size is not None and idx_size < len(row) else ""
        if not size:
            size = _extract_size_from_title(title) or ""
        if not size:
            size = _extract_size_from_row_text(row) or ""
        stock = _to_int(row[idx_stock]) if idx_stock is not None and idx_stock < len(row) else None
        raw_image = _norm(row[idx_image]) if idx_image is not None and idx_image < len(row) else ""
        image_urls = _split_image_urls(raw_image)
        if not image_urls:
            image_urls = _row_fallback_images(row)
        image_url = image_urls[0] if image_urls else None
        description = _norm(row[idx_desc]) if idx_desc is not None and idx_desc < len(row) else ""

        out.append({
            "title": title,
            "dropship_price": float(price),
            "color": color or None,
            "rrc_price": float(rrc_price) if rrc_price and rrc_price > 0 else None,
            "size": size or None,
            "stock": stock,
            "image_url": image_url,
            "image_urls": image_urls,
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


def generate_ai_product_description(
    title: str,
    category_name: str | None = None,
    color: str | None = None,
    *,
    max_chars: int = 420,
) -> str:
    """Generate unique product copy via OpenRouter.

    Returns empty string when AI generation is unavailable/failed,
    so caller can decide to keep description empty instead of шаблонного текста.
    """
    openrouter_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not openrouter_key:
        return ""

    prompt = {
        "title": _norm(title),
        "category": _norm(category_name) or "streetwear",
        "color": _norm(color) or "",
        "requirements": [
            "Пиши по-русски для аудитории 15-25",
            "Сделай описание уникальным, без шаблонных повторов",
            "2-4 коротких предложения",
            "Без мата, без обещаний медицинских/гарантийных эффектов",
            "Не используй markdown/emoji",
        ],
    }
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            timeout=(4.0, 25.0),
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("OPENROUTER_MODEL", "openrouter/auto"),
                "temperature": 0.9,
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты коммерческий копирайтер для e-commerce. Пиши нативно и уникально.",
                    },
                    {
                        "role": "user",
                        "content": "Сгенерируй описание товара в JSON с полем description. Данные: " + json.dumps(prompt, ensure_ascii=False),
                    },
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        txt = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        raw = str(txt or "").strip()
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                raw = str(parsed.get("description") or "").strip()
            except Exception:
                pass
        raw = " ".join(raw.split())
        if raw:
            return raw[:max_chars]
    except Exception:
        pass
    return ""


MIN_MARKUP_RATIO = 1.40
DEFAULT_MARKUP_RATIO = 1.55


def normalize_retail_price(price: float | None) -> float:
    p = max(0.0, float(price or 0.0))
    if p <= 0:
        return 0.0
    if p >= 1000:
        return float(max(99, int(round(p / 100.0) * 100 - 1)))
    return float(max(9, int(round(p / 10.0) * 10 - 1)))


def ensure_min_markup_price(candidate_price: float | None, dropship_price: float, min_markup_ratio: float = MIN_MARKUP_RATIO) -> float:
    base = max(0.0, float(dropship_price or 0.0))
    floor = round(base * float(min_markup_ratio), 0) if base > 0 else 0.0
    candidate = max(0.0, float(candidate_price or 0.0))
    if candidate <= 0:
        return float(floor)
    return float(max(candidate, floor))


def suggest_sale_price(dropship_price: float) -> float:
    base = max(0.0, float(dropship_price))
    if base <= 0:
        return 0.0
    # conservative markup for retail target
    suggested = round(base * DEFAULT_MARKUP_RATIO, 0)
    return ensure_min_markup_price(suggested, base)


def extract_image_urls_from_html_page(url: str, timeout_sec: int = 20, limit: int = 20) -> list[str]:
    headers = {"User-Agent": "defshop-intel-bot/1.0"}
    r = _http_get_with_retries(url, timeout_sec=timeout_sec, headers=headers, max_attempts=3)
    html = r.text or ""

    urls: list[str] = []

    def _push(raw_u: str | None, base_url: str | None = None) -> None:
        u = str(raw_u or "").strip().strip('"\'')
        if not u:
            return
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            parsed = urlparse(base_url or url)
            if parsed.scheme and parsed.netloc:
                u = f"{parsed.scheme}://{parsed.netloc}{u}"
        if u.lower().startswith(("http://", "https://")) and u not in urls:
            urls.append(u)

    # Telegram direct post pages often expose only one preview image in og:image.
    # Public /s/channel/id pages usually contain the full media set for that post.
    tg_m = re.search(r"https?://t\.me/(?:(?:s/)?)([A-Za-z0-9_]{3,})/(\d+)(?:\?.*)?$", str(url).strip(), flags=re.I)
    if tg_m:
        channel = tg_m.group(1)
        msg_id = tg_m.group(2)
        tg_public = f"https://t.me/s/{channel}/{msg_id}"
        try:
            tg_html = _http_get_with_retries(tg_public, timeout_sec=timeout_sec, headers=headers, max_attempts=2).text or ""
            marker = f'data-post="{channel}/{msg_id}"'
            pos = tg_html.find(marker)
            if pos >= 0:
                start = tg_html.rfind('<div class="tgme_widget_message_wrap', 0, pos)
                if start < 0:
                    start = pos
                end = tg_html.find('<div class="tgme_widget_message_wrap', pos + len(marker))
                block = tg_html[start:(end if end > start else len(tg_html))]

                for m in re.findall(r"background-image:url\(([^)]+)\)", block, flags=re.I):
                    _push(m, tg_public)

                for m in re.findall(r'https://cdn\d?\.telesco\.pe/file/[^"\'\s<)]+', block, flags=re.I):
                    _push(m, tg_public)
        except Exception:
            pass

    # og/twitter image meta
    for m in re.findall(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I):
        _push(m, url)

    # plain img src
    for m in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I):
        _push(m, url)
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




def search_image_urls_by_title(query: str, limit: int = 3, timeout_sec: int = 20) -> list[str]:
    q = (query or "").strip()
    if not q:
        return []
    url = f"https://www.bing.com/images/search?q={requests.utils.quote(q)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Mobile Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    try:
        r = _http_get_with_retries(url, timeout_sec=timeout_sec, headers=headers, max_attempts=2)
        txt = r.text or ""
    except Exception:
        return []

    out: list[str] = []
    # bing embeds source image in murl JSON snippets
    for m in re.findall(r'murl&quot;:&quot;(https?://[^&]+?)&quot;', txt, flags=re.I):
        u = m.replace('\/', '/')
        if u not in out:
            out.append(u)
        if len(out) >= max(1, int(limit)):
            break
    return out

def avito_market_scan(query: str, max_pages: int = 1, timeout_sec: int = 20, only_new: bool = True) -> dict[str, Any]:
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
            q_for_search = f"{q} новый" if only_new and "нов" not in q.lower() else q
            url = f"https://www.avito.ru/rossiya?cd=1&p={page}&q={requests.utils.quote(q_for_search)}"
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


def find_similar_images(
    reference_image_url: str,
    candidate_image_urls: list[str],
    *,
    max_hamming_distance: int = 8,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return visually similar images by average-hash signature + color hint."""
    ref_url = (reference_image_url or "").strip()
    if not ref_url:
        return []
    ref_sig = image_print_signature_from_url(ref_url)
    if not ref_sig:
        return []
    ref_color = dominant_color_name_from_url(ref_url)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in candidate_image_urls:
        cand_url = (raw or "").strip()
        if not cand_url or cand_url in seen or cand_url == ref_url:
            continue
        seen.add(cand_url)
        cand_sig = image_print_signature_from_url(cand_url)
        dist = print_signature_hamming(ref_sig, cand_sig)
        if dist is None or dist > int(max_hamming_distance):
            continue
        cand_color = dominant_color_name_from_url(cand_url)
        score = max(0.0, 1.0 - (float(dist) / max(1.0, float(max_hamming_distance))))
        if ref_color and cand_color and ref_color == cand_color:
            score = min(1.0, score + 0.08)
        out.append(
            {
                "image_url": cand_url,
                "distance": int(dist),
                "similarity": round(score, 4),
                "dominant_color": cand_color,
            }
        )

    out.sort(key=lambda x: (x.get("distance", 999), -float(x.get("similarity") or 0.0)))
    return out[: max(1, int(limit))]
