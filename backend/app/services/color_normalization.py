from __future__ import annotations

import re

CANONICAL_COLOR_POOL: tuple[str, ...] = (
    "black", "white", "gray", "beige", "brown", "blue", "navy", "green", "olive",
    "red", "burgundy", "pink", "purple", "yellow", "orange", "multicolor", "unknown",
)

_SYNONYMS: tuple[tuple[str, str], ...] = (
    ("чёр", "black"), ("черн", "black"), ("black", "black"),
    ("бел", "white"), ("молоч", "white"), ("white", "white"),
    ("сер", "gray"), ("графит", "gray"), ("gray", "gray"), ("grey", "gray"),
    ("беж", "beige"), ("крем", "beige"), ("beige", "beige"),
    ("корич", "brown"), ("шоколад", "brown"), ("brown", "brown"),
    ("темно-син", "navy"), ("тёмно-син", "navy"), ("navy", "navy"),
    ("син", "blue"), ("blue", "blue"),
    ("хаки", "olive"), ("олив", "olive"), ("olive", "olive"),
    ("лайм", "green"), ("зелен", "green"), ("зелён", "green"), ("green", "green"),
    ("бордов", "burgundy"), ("burgundy", "burgundy"),
    ("крас", "red"), ("red", "red"),
    ("роз", "pink"), ("pink", "pink"),
    ("фиолет", "purple"), ("сирен", "purple"), ("purple", "purple"),
    ("желт", "yellow"), ("yellow", "yellow"),
    ("оранж", "orange"), ("orange", "orange"),
    ("мульти", "multicolor"), ("разноц", "multicolor"), ("multicolor", "multicolor"),
)


def normalize_color(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    raw = re.sub(r"[^\w\s\-]+", " ", raw, flags=re.U)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return None
    for needle, canon in _SYNONYMS:
        if needle in raw:
            return canon
    return None
