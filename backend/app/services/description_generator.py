from __future__ import annotations

import hashlib
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import requests


@dataclass
class DescriptionPayload:
    title: str
    brand: str | None = None
    category: str | None = None
    colors: list[str] | None = None
    key_features: list[str] | None = None
    materials: list[str] | None = None
    season_style: list[str] | None = None


def _norm(v: str | None) -> str:
    return " ".join(str(v or "").strip().split())


def _norm_list(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for x in (values or []):
        s = _norm(str(x))
        if s and s not in out:
            out.append(s)
    return out


def description_hash(text: str | None) -> str:
    payload = _norm(text).lower().encode("utf-8", errors="ignore")
    return hashlib.sha1(payload).hexdigest()


_PLACEHOLDER_PATTERNS = [
    re.compile(r"вайбов", re.I),
    re.compile(r"стрит-стайл", re.I),
    re.compile(r"каждый день без заморочек", re.I),
]


def is_placeholder_description(text: str | None) -> bool:
    t = _norm(text)
    if not t:
        return True
    for p in _PLACEHOLDER_PATTERNS:
        if p.search(t):
            return True
    return False


class TemplateDescriptionGenerator:
    source = "template"

    _opens = [
        "{title} — модель для аккуратного повседневного образа.",
        "{title} — практичный вариант на каждый день.",
        "{title} — универсальная пара для города.",
    ]
    _middles = [
        "Силуэт легко сочетается с базовым гардеробом и спортивными вещами.",
        "Посадка и форма рассчитаны на комфорт в течение дня.",
        "Дизайн без лишней перегрузки, поэтому модель легко комбинировать.",
    ]
    _features = [
        "Материалы: {materials}.",
        "Ключевые детали: {features}.",
        "По цвету: {colors}.",
        "Подходит под сезон/стиль: {style}.",
    ]
    _closers = [
        "Хорошо работает и в повседневных, и в более собранных образах.",
        "Подойдёт для активного ритма и долгой носки в течение дня.",
        "Оптимальный выбор, если нужен чистый и понятный силуэт без перегибов.",
    ]

    def generate(self, payload: DescriptionPayload) -> str:
        title = _norm(payload.title) or "Товар"
        brand = _norm(payload.brand)
        category = _norm(payload.category)
        colors = _norm_list(payload.colors)
        features = _norm_list(payload.key_features)
        materials = _norm_list(payload.materials)
        style = _norm_list(payload.season_style)

        seed_src = "|".join([
            title.lower(),
            brand.lower(),
            category.lower(),
            ",".join(colors).lower(),
            ",".join(features).lower(),
            ",".join(materials).lower(),
            ",".join(style).lower(),
        ])
        rnd = random.Random(int(hashlib.sha1(seed_src.encode("utf-8")).hexdigest()[:10], 16))

        line1 = rnd.choice(self._opens).format(title=title)
        if brand:
            line1 = f"{line1} Бренд: {brand}."
        if category:
            line1 = f"{line1} Категория: {category.lower()}."

        parts = [line1, rnd.choice(self._middles)]

        feature_pool = []
        if materials:
            feature_pool.append(self._features[0].format(materials=", ".join(materials[:3])))
        if features:
            feature_pool.append(self._features[1].format(features=", ".join(features[:3])))
        if colors:
            feature_pool.append(self._features[2].format(colors=", ".join(colors[:3])))
        if style:
            feature_pool.append(self._features[3].format(style=", ".join(style[:2])))

        if feature_pool:
            parts.append(rnd.choice(feature_pool))

        parts.append(rnd.choice(self._closers))
        text = " ".join(parts)
        text = re.sub(r"\s+", " ", text).strip()
        return text


class OllamaDescriptionGenerator:
    source = "ollama"

    def __init__(self, ollama_url: str, model: str = "llama3.1:8b", timeout_sec: float = 8.0):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.template_fallback = TemplateDescriptionGenerator()

    def generate(self, payload: DescriptionPayload) -> str:
        prompt = {
            "title": _norm(payload.title),
            "brand": _norm(payload.brand),
            "category": _norm(payload.category),
            "colors": _norm_list(payload.colors),
            "key_features": _norm_list(payload.key_features),
            "materials": _norm_list(payload.materials),
            "season_style": _norm_list(payload.season_style),
            "rules": [
                "Пиши по-русски",
                "2-4 предложения",
                "без повторов и воды",
                "без матерщины",
                "без рискованных обещаний типа 100% оригинал",
                "без слова вайбовый",
            ],
        }
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                timeout=(2.5, self.timeout_sec),
                json={
                    "model": self.model,
                    "stream": False,
                    "prompt": f"Сгенерируй описание товара. Данные: {prompt}",
                },
            )
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            text = _norm(str(data.get("response") or ""))
            if not text:
                return self.template_fallback.generate(payload)
            return text
        except Exception:
            return self.template_fallback.generate(payload)


def build_description_generator():
    enabled = str(os.getenv("OLLAMA_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}
    ollama_url = str(os.getenv("OLLAMA_URL", "")).strip()
    if enabled or ollama_url:
        return OllamaDescriptionGenerator(
            ollama_url=ollama_url or "http://localhost:11434",
            model=str(os.getenv("OLLAMA_MODEL", "llama3.1:8b")).strip() or "llama3.1:8b",
            timeout_sec=float(os.getenv("OLLAMA_TIMEOUT_SEC", "8") or 8),
        )
    return TemplateDescriptionGenerator()


def should_regenerate_description(
    current_description: str | None,
    current_hash: str | None,
    *,
    force_regen: bool = False,
) -> bool:
    if force_regen:
        return True
    if not _norm(current_description):
        return True
    if is_placeholder_description(current_description):
        return True
    if current_hash and current_hash == description_hash(current_description):
        return False
    return False


def generated_meta(text: str, source: str) -> dict[str, str]:
    return {
        "description_hash": description_hash(text),
        "description_source": source,
        "description_generated_at": datetime.utcnow().isoformat(),
    }
