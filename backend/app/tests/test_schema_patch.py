from sqlalchemy import create_engine, text, inspect

from app.core.schema_patch import ensure_columns


def test_ensure_columns_adds_legacy_users_fields():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY
                )
                """
            )
        )

    ensure_columns(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    required = {
        "telegram_id",
        "username",
        "first_name",
        "last_name",
        "display_name",
        "avatar_url",
        "role",
        "balance",
        "balance_hold",
        "promo_code",
        "manager_id",
        "created_at",
        "updated_at",
    }
    assert required.issubset(cols)
