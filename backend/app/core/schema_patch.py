"""Best-effort lightweight schema patcher.

The project historically shipped without full Alembic migrations.
To keep `docker compose up` working with an existing Postgres volume,
we apply small additive patches on startup:

- add missing columns
- add missing enum values (Postgres)
- create missing singleton rows (payment settings)

This is NOT a replacement for real migrations.
"""

from __future__ import annotations

from sqlalchemy import inspect, text


def _is_postgres(engine) -> bool:
    try:
        return engine.dialect.name.lower() == "postgresql"
    except Exception:
        return False


def _add_column_pg(conn, table: str, col: str, col_ddl: str) -> None:
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_ddl}"))


def _create_index_pg(conn, name: str, table: str, expr: str) -> None:
    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({expr})"))


def _add_enum_value_pg(conn, enum_name: str, value: str) -> None:
    # Postgres doesn't support ADD VALUE IF NOT EXISTS on all versions, so we check first.
    q = text(
        """
        SELECT 1
        FROM pg_type t
        JOIN pg_enum e ON t.oid = e.enumtypid
        WHERE t.typname = :n AND e.enumlabel = :v
        LIMIT 1
        """
    )
    exists = conn.execute(q, {"n": enum_name, "v": value}).first() is not None
    if not exists:
        # value must be a single-quoted literal
        conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE '{value}'"))


def ensure_schema(engine) -> None:
    """Apply all best-effort patches."""
    ensure_columns(engine)
    ensure_singletons(engine)


def ensure_columns(engine) -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    # ---------- Postgres enum patches ----------
    if _is_postgres(engine):
        with engine.begin() as conn:
            try:
                _add_enum_value_pg(conn, "order_status", "delivered")
            except Exception:
                # enum may not exist yet (fresh DB) or dialect isn't PG
                pass
            try:
                _add_enum_value_pg(conn, "promo_type", "special")
            except Exception:
                pass

    # ---------- users ----------
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            # existing columns historically
            if "balance_hold" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "users", "balance_hold", "NUMERIC(12,2) NOT NULL DEFAULT 0")
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN balance_hold NUMERIC(12,2) DEFAULT 0"))

            # promo lifecycle & anti-abuse
            if "promo_used_at" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "users", "promo_used_at", "TIMESTAMPTZ")
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN promo_used_at DATETIME"))
            if "promo_used_code" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "users", "promo_used_code", "VARCHAR(64)")
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN promo_used_code VARCHAR(64)"))
            if "promo_pending_order_id" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "users", "promo_pending_order_id", "INTEGER")
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN promo_pending_order_id INTEGER"))
            if "promo_pending_code" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "users", "promo_pending_code", "VARCHAR(64)")
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN promo_pending_code VARCHAR(64)"))

            # manager commission settings
            if "first_n_count" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "users", "first_n_count", "INTEGER NOT NULL DEFAULT 3")
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN first_n_count INTEGER DEFAULT 3"))
            if "first_n_rate" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "users", "first_n_rate", "NUMERIC(5,4) NOT NULL DEFAULT 0.10")
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN first_n_rate NUMERIC(5,4) DEFAULT 0.10"))
            if "ongoing_rate" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "users", "ongoing_rate", "NUMERIC(5,4) NOT NULL DEFAULT 0.05")
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN ongoing_rate NUMERIC(5,4) DEFAULT 0.05"))

    # ---------- orders ----------
    if "orders" in tables:
        cols = {c["name"] for c in insp.get_columns("orders")}
        with engine.begin() as conn:
            def add(col: str, ddl_pg: str, ddl_other: str | None = None):
                if col in cols:
                    return
                if _is_postgres(engine):
                    _add_column_pg(conn, "orders", col, ddl_pg)
                else:
                    conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col} {ddl_other or ddl_pg}"))

            add("manager_id", "INTEGER", "INTEGER")
            if _is_postgres(engine):
                _create_index_pg(conn, "ix_orders_manager_id", "orders", "manager_id")
                _create_index_pg(conn, "ix_orders_assistant_id", "orders", "assistant_id")

            add("assistant_id", "INTEGER", "INTEGER")
            add("promo_code", "VARCHAR(64)", "VARCHAR(64)")
            add("subtotal_amount", "NUMERIC(12,2) NOT NULL DEFAULT 0", "NUMERIC(12,2) DEFAULT 0")
            add("discount_amount", "NUMERIC(12,2) NOT NULL DEFAULT 0", "NUMERIC(12,2) DEFAULT 0")
            add("promo_kind", "VARCHAR(32)", "VARCHAR(32)")
            add("promo_discount_percent", "NUMERIC(5,2)", "NUMERIC(5,2)")
            add("promo_owner_user_id", "INTEGER", "INTEGER")
            add("promo_special_id", "INTEGER", "INTEGER")
            add("payment_uploaded_at", "TIMESTAMPTZ", "DATETIME")
            add("note", "TEXT", "TEXT")

            if _is_postgres(engine):
                _create_index_pg(conn, "ix_orders_promo_code", "orders", "promo_code")

    # ---------- cart_items unique ----------
    if _is_postgres(engine) and "cart_items" in tables:
        with engine.begin() as conn:
            # unique index to prevent duplicates
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cart_user_variant ON cart_items(user_id, variant_id)"
                )
            )


def ensure_singletons(engine) -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "payment_settings" not in tables:
        return

    with engine.begin() as conn:
        # id=1 should exist
        row = conn.execute(text("SELECT id FROM payment_settings WHERE id = 1")).first()
        if not row:
            conn.execute(
                text(
                    """
                    INSERT INTO payment_settings (id, recipient_name, phone, card_number, bank_name, note)
                    VALUES (1, '', '', '', '', '')
                    """
                )
            )
