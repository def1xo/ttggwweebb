# backend/app/migrations/versions/0001_initial_schema.py
"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2025-01-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # enums
    user_role = sa.Enum('admin', 'manager', 'assistant', 'customer', name='user_role')
    promo_type = sa.Enum('manager', 'assistant', 'admin', name='promo_type')
    order_status = sa.Enum('new', 'awaiting_payment', 'paid', 'processing', 'shipped', 'cancelled', name='order_status')

    user_role.create(op.get_bind(), checkfirst=True)
    promo_type.create(op.get_bind(), checkfirst=True)
    order_status.create(op.get_bind(), checkfirst=True)

    # categories
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=255), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index(op.f('ix_categories_slug'), 'categories', ['slug'], unique=False)

    # products
    op.create_table(
        'products',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=512), nullable=False),
        sa.Column('slug', sa.String(length=512), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('base_price', sa.Numeric(12, 2), nullable=False),
        sa.Column('currency', sa.String(length=8), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('default_image', sa.String(length=1024), nullable=True),
        sa.Column('channel_message_id', sa.String(length=128), nullable=True),
        sa.Column('visible', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index(op.f('ix_products_channel_message_id'), 'products', ['channel_message_id'], unique=False)
    op.create_index(op.f('ix_products_slug'), 'products', ['slug'], unique=True)

    # product_images
    op.create_table(
        'product_images',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=1024), nullable=False),
        sa.Column('alt', sa.String(length=255), nullable=True),
        sa.Column('sort', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )

    # colors & sizes
    op.create_table('colors',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('hex_code', sa.String(length=7), nullable=True)
    )
    op.create_table('sizes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('label', sa.String(length=64), nullable=False)
    )

    # product_variants
    op.create_table(
        'product_variants',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('sku', sa.String(length=128), nullable=True),
        sa.Column('size_id', sa.Integer(), nullable=True),
        sa.Column('color_id', sa.Integer(), nullable=True),
        sa.Column('price', sa.Numeric(12, 2), nullable=True),
        sa.Column('stock_quantity', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('images', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('product_id', 'size_id', 'color_id', name='uq_product_variant_unique')
    )
    op.create_index(op.f('ix_product_variants_sku'), 'product_variants', ['sku'], unique=True)

    # users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('telegram_id', sa.String(length=128), nullable=True, unique=True),
        sa.Column('username', sa.String(length=128), nullable=True),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=64), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('role', user_role, nullable=False, server_default='customer'),
        sa.Column('manager_id', sa.Integer(), nullable=True),
        sa.Column('assistant_id', sa.Integer(), nullable=True),
        sa.Column('balance', sa.Numeric(12, 2), nullable=False, server_default='0.00'),
        sa.Column('bound_owner_id', sa.Integer(), nullable=True),
        sa.Column('bound_owner_type', sa.String(length=32), nullable=True),
        sa.Column('bound_via_promo_id', sa.Integer(), nullable=True),
        sa.Column('bound_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )

    # managers & assistants
    op.create_table(
        'managers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False, unique=True),
        sa.Column('first_n_count', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('first_n_rate', sa.Numeric(5, 4), nullable=False, server_default='0.10'),
        sa.Column('ongoing_rate', sa.Numeric(5, 4), nullable=False, server_default='0.05'),
        sa.Column('assistant_max_rate', sa.Numeric(5, 4), nullable=False, server_default='0.10'),
    )
    op.create_table(
        'assistants',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False, unique=True),
        sa.Column('manager_id', sa.Integer(), nullable=False),
        sa.Column('assigned_rate', sa.Numeric(5, 4), nullable=False, server_default='0.00'),
    )

    # user_manager_bindings
    op.create_table(
        'user_manager_bindings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('owner_type', sa.String(length=16), nullable=False),
        sa.Column('via_promo_code_id', sa.Integer(), nullable=True),
        sa.Column('bound_at', sa.DateTime(), nullable=False),
    )

    # promo_codes & usage
    op.create_table(
        'promo_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(length=128), nullable=False, unique=True),
        sa.Column('type', promo_type, nullable=False, server_default='manager'),
        sa.Column('discount_percent', sa.Numeric(5,4), nullable=False, server_default='0.05'),
        sa.Column('owner_manager_id', sa.Integer(), nullable=True),
        sa.Column('owner_assistant_id', sa.Integer(), nullable=True),
        sa.Column('usage_limit', sa.Integer(), nullable=True),
        sa.Column('used_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'promo_usage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('promo_code_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=False),
    )

    # orders & items
    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', order_status, nullable=False, server_default='new'),
        sa.Column('total_amount', sa.Numeric(12,2), nullable=False),
        sa.Column('delivery_price', sa.Numeric(10,2), nullable=False, server_default='0.00'),
        sa.Column('delivery_type', sa.String(length=128), nullable=True),
        sa.Column('delivery_address', sa.Text(), nullable=True),
        sa.Column('fio', sa.String(length=255), nullable=True),
        sa.Column('promo_code_id', sa.Integer(), nullable=True),
        sa.Column('manager_id', sa.Integer(), nullable=True),
        sa.Column('assistant_id', sa.Integer(), nullable=True),
        sa.Column('payment_screenshot', sa.String(length=1024), nullable=True),
        sa.Column('manager_rate_applied', sa.Numeric(5,4), nullable=True),
        sa.Column('assistant_rate_applied', sa.Numeric(5,4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'order_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('variant_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('price', sa.Numeric(12,2), nullable=False),
    )

    # commission_records
    op.create_table(
        'commission_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('beneficiary_user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('amount', sa.Numeric(12,2), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='owed'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    # withdraw_requests
    op.create_table(
        'withdraw_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(12,2), nullable=False),
        sa.Column('target_details', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='requested'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('processed_by', sa.Integer(), nullable=True),
    )

    # product_costs
    op.create_table(
        'product_costs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('variant_id', sa.Integer(), nullable=False),
        sa.Column('cost_price', sa.Numeric(12,2), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    )

    # notification_logs & audit_logs
    op.create_table(
        'notification_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=255), nullable=False),
        sa.Column('resource', sa.String(length=255), nullable=True),
        sa.Column('resource_id', sa.Integer(), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    # foreign keys (add constraints for integrity)
    op.create_foreign_key(None, 'products', 'categories', ['category_id'], ['id'])
    op.create_foreign_key(None, 'product_images', 'products', ['product_id'], ['id'])
    op.create_foreign_key(None, 'product_variants', 'products', ['product_id'], ['id'])
    op.create_foreign_key(None, 'product_variants', 'sizes', ['size_id'], ['id'])
    op.create_foreign_key(None, 'product_variants', 'colors', ['color_id'], ['id'])
    op.create_foreign_key(None, 'managers', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'assistants', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'user_manager_bindings', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'promo_codes', 'managers', ['owner_manager_id'], ['id'])
    op.create_foreign_key(None, 'promo_codes', 'assistants', ['owner_assistant_id'], ['id'])
    op.create_foreign_key(None, 'promo_usage', 'promo_codes', ['promo_code_id'], ['id'])
    op.create_foreign_key(None, 'promo_usage', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'orders', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'orders', 'promo_codes', ['promo_code_id'], ['id'])
    op.create_foreign_key(None, 'orders', 'managers', ['manager_id'], ['id'])
    op.create_foreign_key(None, 'orders', 'assistants', ['assistant_id'], ['id'])
    op.create_foreign_key(None, 'order_items', 'orders', ['order_id'], ['id'])
    op.create_foreign_key(None, 'order_items', 'product_variants', ['variant_id'], ['id'])
    op.create_foreign_key(None, 'commission_records', 'orders', ['order_id'], ['id'])
    op.create_foreign_key(None, 'commission_records', 'users', ['beneficiary_user_id'], ['id'])
    op.create_foreign_key(None, 'withdraw_requests', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'product_costs', 'product_variants', ['variant_id'], ['id'])
    op.create_foreign_key(None, 'notification_logs', 'users', ['user_id'], ['id'])
    op.create_foreign_key(None, 'audit_logs', 'users', ['actor_user_id'], ['id'])


def downgrade():
    # drop in reverse order
    op.drop_table('audit_logs')
    op.drop_table('notification_logs')
    op.drop_table('product_costs')
    op.drop_table('withdraw_requests')
    op.drop_table('commission_records')
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('promo_usage')
    op.drop_table('promo_codes')
    op.drop_table('user_manager_bindings')
    op.drop_table('assistants')
    op.drop_table('managers')
    op.drop_table('users')
    op.drop_table('product_variants')
    op.drop_table('sizes')
    op.drop_table('colors')
    op.drop_table('product_images')
    op.drop_table('products')
    op.drop_table('categories')

    order_status = sa.Enum(name='order_status')
    promo_type = sa.Enum(name='promo_type')
    user_role = sa.Enum(name='user_role')

    order_status.drop(op.get_bind(), checkfirst=True)
    promo_type.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
