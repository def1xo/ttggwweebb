"""initial schema"""

from alembic import op
from sqlalchemy import inspect

# Import models so Base.metadata is populated
from app.db.base import Base
import app.db.models  # noqa: F401

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # If runtime schema patcher already created tables/indexes in an existing DB volume,
    # make the initial migration idempotent to avoid DuplicateTable/DuplicateIndex errors.
    try:
      insp = inspect(bind)
      if insp.has_table("users"):
        return
    except Exception:
      pass
    # Create all tables and enum types from SQLAlchemy models.
    # NOTE: we avoid circular FKs in models (users<->orders) so this is stable.
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
