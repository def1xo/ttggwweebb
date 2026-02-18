from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SupplierProfile:
    key: str
    aliases: tuple[str, ...] = ()
    drop_title_tokens: tuple[str, ...] = ()


_PROFILES: tuple[SupplierProfile, ...] = (
    SupplierProfile(
        key="shop_vkus",
        aliases=("shop vkus", "shop_vkus", "шоп вкус"),
        drop_title_tokens=("топ качество", "premium", "премиум", "в наличии"),
    ),
    SupplierProfile(
        key="firmach_droppp",
        aliases=("фирмач дроп", "firmachdroppp", "firmach drop"),
        drop_title_tokens=("люкс", "топ", "в наличии"),
    ),
)


def normalize_supplier_key(raw_supplier: str | None) -> str:
    return re.sub(r"\s+", " ", str(raw_supplier or "").strip().lower())


def get_supplier_profile(raw_supplier: str | None) -> SupplierProfile | None:
    key = normalize_supplier_key(raw_supplier)
    if not key:
        return None
    for profile in _PROFILES:
        if key == profile.key or key in profile.aliases:
            return profile
    return None


def normalize_title_for_supplier(title: str | None, raw_supplier: str | None) -> str:
    t = str(title or "").strip()
    if not t:
        return ""

    # strip obvious metadata fragments that often vary between rows/import runs
    t = re.sub(r"(?i)\b(арт(?:икул)?|код)\s*[:#-]?\s*[A-Z0-9_-]+", " ", t)
    t = re.sub(r"(?i)\b(в\s*наличии|нет\s*в\s*наличии|размер(?:ы)?\s*[:#-]?.*)$", " ", t)
    t = re.sub(r"\[[^\]]{0,120}\]", " ", t)
    t = re.sub(r"\([^\)]{0,120}\)", " ", t)

    profile = get_supplier_profile(raw_supplier)
    if profile:
        for token in profile.drop_title_tokens:
            if token:
                t = re.sub(re.escape(token), " ", t, flags=re.I)

    t = re.sub(r"\s+", " ", t).strip(" -_.,;")
    return t
