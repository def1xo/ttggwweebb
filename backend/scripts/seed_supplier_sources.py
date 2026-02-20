from __future__ import annotations

from dataclasses import dataclass

from app.db import models
from app.db.base import Base
from app.db.session import engine, SessionLocal


@dataclass(frozen=True)
class SupplierSeed:
    supplier_name: str
    manager_contact: str
    tg_channel_url: str | None
    table_url: str | None


SEED: tuple[SupplierSeed, ...] = (
    SupplierSeed("shop_vkus", "@Manager_Shop_Vkus", "https://t.me/shop_vkus", "https://docs.google.com/spreadsheets/d/1Pv_iyCw5WCbBHXvhdH5w7pRjxfsjTbCm3SjHPElC_wA/edit?usp=sharing"),
    SupplierSeed("Фирмач дроп", "@evs17", "https://t.me/firmachdroppp", "https://docs.google.com/spreadsheets/d/1JQ5p32JknAm34W42fiTXzAFKYOhb9QEcMFAwSernwI4/htmlview"),
    SupplierSeed("Профит дроп", "@managerProfitDROP", "https://t.me/+b-xpNhKNEVE0ZjRi", "https://docs.google.com/spreadsheets/d/1Xfjpx1Bs9GDUlgKalrzzm3u2M6dpxwuHZQwCqihjw2Q/htmlview"),
    SupplierSeed("Venom", "@manager_venom", "https://t.me/venomopt12", "https://docs.google.com/spreadsheets/d/1wfZJPJMO34WfcbGNxP-IWl5w0V1vEDf6FHakAqoJsBw/htmlview"),
    SupplierSeed("Empire", "@manager111_0", "https://t.me/dropempire1", "https://docs.google.com/spreadsheets/d/1fvLjH86AAD2upGbQ9npo-mtUbFAsl3cmx8wDIczTCeE/htmlview"),
    SupplierSeed("Оптобаза", "@dropbazaadmin", "https://t.me/optobaza", "https://b2b.moysklad.ru/public/oWXBoG49bkuB/catalog"),
    SupplierSeed("HHHB", "@HANISPIRIT", "https://t.me/HHHB_STORE", None),
)


def _upsert_source(db, *, source_url: str, supplier_name: str, manager_contact: str, role_note: str) -> str:
    item = db.query(models.SupplierSource).filter(models.SupplierSource.source_url == source_url).one_or_none()
    if item is None:
        item = models.SupplierSource(
            source_url=source_url,
            supplier_name=supplier_name,
            manager_name=manager_contact.lstrip("@"),
            manager_contact=manager_contact,
            note=role_note,
            active=True,
        )
        db.add(item)
        return "created"

    changed = False
    if item.supplier_name != supplier_name:
        item.supplier_name = supplier_name
        changed = True
    if item.manager_contact != manager_contact:
        item.manager_contact = manager_contact
        changed = True
    manager_name = manager_contact.lstrip("@")
    if item.manager_name != manager_name:
        item.manager_name = manager_name
        changed = True
    if item.note != role_note:
        item.note = role_note
        changed = True
    if not bool(getattr(item, "active", True)):
        item.active = True
        changed = True
    if changed:
        db.add(item)
        return "updated"
    return "skipped"


def run_seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        counters = {"created": 0, "updated": 0, "skipped": 0}
        for src in SEED:
            if src.table_url:
                res = _upsert_source(
                    db,
                    source_url=src.table_url,
                    supplier_name=src.supplier_name,
                    manager_contact=src.manager_contact,
                    role_note="seed: стартовый набор • role=price_stock_table",
                )
                counters[res] += 1
            if src.tg_channel_url:
                res = _upsert_source(
                    db,
                    source_url=src.tg_channel_url,
                    supplier_name=src.supplier_name,
                    manager_contact=src.manager_contact,
                    role_note="seed: стартовый набор • role=tg_media",
                )
                counters[res] += 1
        db.commit()
        print(f"supplier seed done: created={counters['created']} updated={counters['updated']} skipped={counters['skipped']}")
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
