from __future__ import annotations

import re

CANONICAL_COLORS = {
    "black", "white", "gray", "beige", "brown", "blue", "navy", "green", "olive",
    "red", "burgundy", "pink", "purple", "yellow", "orange", "multicolor", "unknown",
}

_ALIASES = {
    "чёрный": "black", "черный": "black", "black": "black",
    "белый": "white", "молочный": "white", "white": "white",
    "серый": "gray", "графит": "gray", "grey": "gray", "gray": "gray",
    "бежевый": "beige", "беж": "beige", "кремовый": "beige", "beige": "beige",
    "коричневый": "brown", "brown": "brown",
    "синий": "blue", "голубой": "blue", "blue": "blue",
    "темно-синий": "navy", "тёмно-синий": "navy", "navy": "navy",
    "зеленый": "green", "зелёный": "green", "green": "green", "лайм": "green", "lime": "green",
    "оливковый": "olive", "хаки": "olive", "olive": "olive",
    "красный": "red", "red": "red",
    "бордовый": "burgundy", "марсала": "burgundy", "burgundy": "burgundy",
    "розовый": "pink", "pink": "pink",
    "фиолетовый": "purple", "purple": "purple",
    "желтый": "yellow", "жёлтый": "yellow", "yellow": "yellow",
    "оранжевый": "orange", "orange": "orange",
    "мульти": "multicolor", "разноцветный": "multicolor", "multicolor": "multicolor",
}


def normalize_color(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    raw = re.sub(r"[\[\](){}]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if raw in _ALIASES:
        return _ALIASES[raw]
    for key, mapped in _ALIASES.items():
        if key in raw:
            return mapped
    token = raw.replace(" ", "-")
    if token in CANONICAL_COLORS:
        return token
    return "unknown"
