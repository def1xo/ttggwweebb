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



def _create_unique_index_pg(conn, name: str, table: str, expr: str) -> None:
    conn.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table}({expr})"))


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
            def add_user_col(col: str, ddl_pg: str, ddl_other: str | None = None):
                if col in cols:
                    return
                if _is_postgres(engine):
                    _add_column_pg(conn, "users", col, ddl_pg)
                else:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl_other or ddl_pg}"))

            # Core profile/auth columns required by /auth/me and get_current_user
            add_user_col("telegram_id", "BIGINT", "BIGINT")
            add_user_col("username", "VARCHAR(64)", "VARCHAR(64)")
            add_user_col("first_name", "VARCHAR(128)", "VARCHAR(128)")
            add_user_col("last_name", "VARCHAR(128)", "VARCHAR(128)")
            add_user_col("display_name", "VARCHAR(255)", "VARCHAR(255)")
            add_user_col("avatar_url", "VARCHAR(1024)", "VARCHAR(1024)")
            add_user_col("role", "user_role NOT NULL DEFAULT 'user'", "VARCHAR(16) DEFAULT 'user'")
            add_user_col("balance", "NUMERIC(12,2) NOT NULL DEFAULT 0", "NUMERIC(12,2) DEFAULT 0")
            add_user_col("promo_code", "VARCHAR(64)", "VARCHAR(64)")
            add_user_col("manager_id", "INTEGER", "INTEGER")
            add_user_col("created_at", "TIMESTAMPTZ DEFAULT NOW()", "DATETIME")
            add_user_col("updated_at", "TIMESTAMPTZ DEFAULT NOW()", "DATETIME")

            # existing columns historically
            add_user_col("balance_hold", "NUMERIC(12,2) NOT NULL DEFAULT 0", "NUMERIC(12,2) DEFAULT 0")

            # promo lifecycle & anti-abuse
            add_user_col("promo_used_at", "TIMESTAMPTZ", "DATETIME")
            add_user_col("promo_used_code", "VARCHAR(64)", "VARCHAR(64)")
            add_user_col("promo_pending_order_id", "INTEGER", "INTEGER")
            add_user_col("promo_pending_code", "VARCHAR(64)", "VARCHAR(64)")

            # manager commission settings
            add_user_col("first_n_count", "INTEGER NOT NULL DEFAULT 3", "INTEGER DEFAULT 3")
            add_user_col("first_n_rate", "NUMERIC(5,4) NOT NULL DEFAULT 0.10", "NUMERIC(5,4) DEFAULT 0.10")
            add_user_col("ongoing_rate", "NUMERIC(5,4) NOT NULL DEFAULT 0.05", "NUMERIC(5,4) DEFAULT 0.05")

            if _is_postgres(engine):
                _create_index_pg(conn, "ix_users_username", "users", "username")
                _create_index_pg(conn, "ix_users_manager_id", "users", "manager_id")
                # Keep promo_code unique if table came from legacy schema
                _create_unique_index_pg(conn, "ux_users_promo_code", "users", "promo_code")

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




    # ---------- products ----------
    if "products" in tables:
        cols = {c["name"] for c in insp.get_columns("products")}
        with engine.begin() as conn:
            def add_prod_col(col: str, ddl_pg: str, ddl_other: str | None = None):
                if col in cols:
                    return
                if _is_postgres(engine):
                    _add_column_pg(conn, "products", col, ddl_pg)
                else:
                    conn.execute(text(f"ALTER TABLE products ADD COLUMN {col} {ddl_other or ddl_pg}"))

            add_prod_col("import_source_url", "VARCHAR(2000)", "VARCHAR(2000)")
            add_prod_col("import_source_kind", "VARCHAR(64)", "VARCHAR(64)")
            add_prod_col("import_supplier_name", "VARCHAR(255)", "VARCHAR(255)")
            add_prod_col("import_media_meta", "JSONB", "TEXT")
            add_prod_col("detected_color", "VARCHAR(32)", "VARCHAR(32)")
            add_prod_col("detected_color_confidence", "NUMERIC(5,4)", "NUMERIC(5,4)")
            add_prod_col("detected_color_debug", "JSONB", "TEXT")
            if _is_postgres(engine):
                _create_index_pg(conn, "ix_products_detected_color", "products", "detected_color")

    # ---------- supplier_sources ----------
    if "supplier_sources" in tables:
        cols = {c["name"] for c in insp.get_columns("supplier_sources")}
        with engine.begin() as conn:
            if "active" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "supplier_sources", "active", "BOOLEAN NOT NULL DEFAULT TRUE")
                else:
                    conn.execute(text("ALTER TABLE supplier_sources ADD COLUMN active BOOLEAN DEFAULT 1"))
            if _is_postgres(engine):
                _create_index_pg(conn, "ix_supplier_sources_active", "supplier_sources", "active")

    # ---------- product_variants dedupe guard ----------
    if _is_postgres(engine) and "product_variants" in tables:
        with engine.begin() as conn:
            _create_unique_index_pg(
                conn,
                "uq_product_variants_product_size_color",
                "product_variants",
                "product_id, size_id, color_id",
            )

    # ---------- cart_items unique ----------
    if _is_postgres(engine) and "cart_items" in tables:
        with engine.begin() as conn:
            # unique index to prevent duplicates
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cart_user_variant ON cart_items(user_id, variant_id)"
                )
            )

    # ---------- promo_codes owner ----------
    if "promo_codes" in tables:
        cols = {c["name"] for c in insp.get_columns("promo_codes")}
        with engine.begin() as conn:
            if "owner_user_id" not in cols:
                if _is_postgres(engine):
                    _add_column_pg(conn, "promo_codes", "owner_user_id", "INTEGER")
                else:
                    conn.execute(text("ALTER TABLE promo_codes ADD COLUMN owner_user_id INTEGER"))
            if _is_postgres(engine):
                _create_index_pg(conn, "ix_promo_codes_owner_user_id", "promo_codes", "owner_user_id")


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
