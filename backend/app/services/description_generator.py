from __future__ import annotations

import hashlib
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

PLACEHOLDER_SIGNATURES = (
    "лучший выбор для вашего гардероба",
    "стильный вариант на каждый день",
    "качественный материал и удобная посадка",
)


@dataclass
class DescriptionPayload:
    title: str
    brand: str | None = None
    category: str | None = None
    colors: list[str] | None = None
    key_features: list[str] | None = None
    materials: list[str] | None = None
    season: str | None = None
    style: str | None = None


class TemplateDescriptionGenerator:
    def generate(self, payload: DescriptionPayload) -> str:
        seed = int(hashlib.sha256((payload.title or "").encode("utf-8")).hexdigest()[:8], 16)
        rnd = random.Random(seed)
        mood = rnd.choice(["лаконичный", "аккуратный", "практичный", "современный"])
        color = ", ".join(payload.colors or []) or "базовой палитре"
        material = rnd.choice(payload.materials or ["износостойких материалов", "мягкого текстиля", "плотной основы"])
        feature = rnd.choice(payload.key_features or ["удобная посадка", "чистый силуэт", "комфорт на каждый день"])
        cat = payload.category or "товар"
        return (
            f"{payload.title} — {mood} {cat.lower()} в {color}. "
            f"Модель выполнена из {material} и делает акцент на {feature}. "
            f"Подходит для повседневных образов{f' в стиле {payload.style}' if payload.style else ''}."
        )


class OllamaDescriptionGenerator:
    def __init__(self, base_url: str, model: str = "llama3.1", timeout_sec: int = 8) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec

    def generate(self, payload: DescriptionPayload) -> str:
        prompt = (
            "Напиши описание товара на русском языке: 2-4 предложения, без воды и повторов, "
            "без рискованных заявлений. Данные: "
            f"title={payload.title}; brand={payload.brand or ''}; category={payload.category or ''}; "
            f"colors={', '.join(payload.colors or [])}; materials={', '.join(payload.materials or [])}; "
            f"features={', '.join(payload.key_features or [])}; season={payload.season or ''}; style={payload.style or ''}."
        )
        r = requests.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=self.timeout_sec,
        )
        r.raise_for_status()
        text = str((r.json() or {}).get("response") or "").strip()
        if not text:
            raise RuntimeError("empty ollama response")
        return text


def get_description_generator():
    enabled = str(os.getenv("OLLAMA_ENABLED", "")).lower() in {"1", "true", "yes"}
    url = str(os.getenv("OLLAMA_URL", "")).strip()
    if enabled or url:
        return OllamaDescriptionGenerator(base_url=url or "http://localhost:11434", model=os.getenv("OLLAMA_MODEL", "llama3.1"))
    return TemplateDescriptionGenerator()


def description_hash(value: str | None) -> str | None:
    t = str(value or "").strip()
    if not t:
        return None
    return hashlib.sha256(t.lower().encode("utf-8")).hexdigest()


def is_placeholder_description(value: str | None) -> bool:
    t = str(value or "").strip().lower()
    if not t:
        return True
    if any(sig in t for sig in PLACEHOLDER_SIGNATURES):
        return True
    return len(t) < 40


def should_regenerate_description(current: str | None, force_regen: bool = False) -> bool:
    if force_regen:
        return True
    return is_placeholder_description(current)


def generate_description(payload: DescriptionPayload) -> tuple[str, str, str, datetime]:
    fallback = TemplateDescriptionGenerator()
    generator = get_description_generator()
    try:
        text = generator.generate(payload)
        source = "ollama" if isinstance(generator, OllamaDescriptionGenerator) else "template"
    except Exception:
        text = fallback.generate(payload)
        source = "template"
    return text, source, description_hash(text) or "", datetime.now(timezone.utc)
