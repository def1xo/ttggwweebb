"""import review and supplier mapping models

Revision ID: 0002_import_reviews_and_mappings
Revises: 0001_initial
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_import_reviews_and_mappings"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("supplier_sku", sa.String(length=255), nullable=True))
    op.add_column("products", sa.Column("external_id", sa.String(length=255), nullable=True))
    op.add_column("products", sa.Column("requires_color_review", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("products", sa.Column("requires_category_review", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("products", sa.Column("review_reason", sa.String(length=255), nullable=True))
    op.create_index("ix_products_supplier_sku", "products", ["supplier_sku"], unique=False)
    op.create_index("ix_products_external_id", "products", ["external_id"], unique=False)
    op.create_index("ix_products_requires_color_review", "products", ["requires_color_review"], unique=False)
    op.create_index("ix_products_requires_category_review", "products", ["requires_category_review"], unique=False)

    op.create_table(
        "color_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("color_id", sa.Integer(), sa.ForeignKey("colors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_image_id", sa.Integer(), sa.ForeignKey("product_images.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("color_id", "product_image_id", name="uq_color_image_pair"),
    )
    op.create_index("ix_color_images_color_id", "color_images", ["color_id"], unique=False)
    op.create_index("ix_color_images_product_image_id", "color_images", ["product_image_id"], unique=False)

    op.create_table(
        "supplier_category_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_category_raw", sa.String(length=255), nullable=False),
        sa.Column("mapped_category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("supplier_id", "supplier_category_raw", name="uq_supplier_category_raw"),
    )

    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_dump_path", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "import_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_job_id", sa.Integer(), sa.ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_sku", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "import_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_job_id", sa.Integer(), sa.ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("import_logs")
    op.drop_table("import_items")
    op.drop_table("import_jobs")
    op.drop_table("supplier_category_map")
    op.drop_index("ix_color_images_product_image_id", table_name="color_images")
    op.drop_index("ix_color_images_color_id", table_name="color_images")
    op.drop_table("color_images")

    op.drop_index("ix_products_requires_category_review", table_name="products")
    op.drop_index("ix_products_requires_color_review", table_name="products")
    op.drop_index("ix_products_external_id", table_name="products")
    op.drop_index("ix_products_supplier_sku", table_name="products")
    op.drop_column("products", "review_reason")
    op.drop_column("products", "requires_category_review")
    op.drop_column("products", "requires_color_review")
    op.drop_column("products", "external_id")
    op.drop_column("products", "supplier_sku")
