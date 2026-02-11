from datetime import datetime
from enum import Enum
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    Numeric,
    DateTime,
    ForeignKey,
    Boolean,
    JSON,
    UniqueConstraint,
    Index,
    Enum as SAEnum,
)
from sqlalchemy.orm import relationship
from app.db.base import Base


# ---- Enums ----
class UserRole(str, Enum):
    user = "user"
    manager = "manager"
    assistant = "assistant"
    admin = "admin"


class OrderStatus(str, Enum):
    awaiting_payment = "awaiting_payment"
    paid = "paid"
    processing = "processing"
    sent = "sent"
    received = "received"
    delivered = "delivered"
    cancelled = "cancelled"


class PromoType(str, Enum):
    manager = "manager"
    assistant = "assistant"
    admin = "admin"
    special = "special"


# ---- Core models ----
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # NOTE: keep UNIQUE, but don't also create an explicit index.
    # In Postgres, UNIQUE creates the required index automatically.
    telegram_id = Column(BigInteger, unique=True, nullable=True)
    username = Column(String(64), nullable=True, index=True)
    first_name = Column(String(128), nullable=True)
    last_name = Column(String(128), nullable=True)
    display_name = Column(String(255), nullable=True)  # editable display name
    avatar_url = Column(String(1024), nullable=True)  # avatar URL (uploaded or tg)
    role = Column(SAEnum(UserRole, name="user_role"), nullable=False, default=UserRole.user.value, index=True)
    # balance = доступно к выводу/использованию
    balance = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    # balance_hold = зарезервировано под заявки на вывод (pending)
    balance_hold = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    promo_code = Column(String(64), unique=True, nullable=True)
    promo_used_at = Column(DateTime(timezone=True), nullable=True)
    promo_used_code = Column(String(64), nullable=True)
    # IMPORTANT: keep this as a plain integer (no FK) to avoid a circular FK dependency
    # between users <-> orders that breaks initial migrations on fresh DBs.
    promo_pending_order_id = Column(Integer, nullable=True)
    promo_pending_code = Column(String(64), nullable=True)
    # Commission settings (editable per manager)
    first_n_count = Column(Integer, nullable=False, default=3)
    first_n_rate = Column(Numeric(5, 4), nullable=False, default=Decimal("0.10"))
    ongoing_rate = Column(Numeric(5, 4), nullable=False, default=Decimal("0.05"))
    manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    manager = relationship(
        "User",
        remote_side=[id],
        backref="assistants",
        foreign_keys=[manager_id],
    )

    # NOTE: Order has multiple FKs to users (user_id/manager_id/assistant_id),
    # so we must disambiguate the relationship.
    orders = relationship(
        "Order",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Order.user_id",
    )
    commissions = relationship("Commission", back_populates="user", cascade="all, delete-orphan")
    cart_items = relationship("CartItem", back_populates="user", cascade="all, delete-orphan")

    withdraw_requests = relationship(
        "WithdrawRequest",
        back_populates="requester",
        foreign_keys="WithdrawRequest.requester_user_id",
        cascade="all, delete-orphan",
    )

    notification_logs = relationship(
        "NotificationLog",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    slug = Column(String(255), nullable=True, unique=True)
    description = Column(Text, nullable=True)
    image_url = Column(String(1024), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    products = relationship("Product", back_populates="category", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(512), nullable=False)
    slug = Column(String(512), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    base_price = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    currency = Column(String(8), nullable=False, default="RUB")
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    default_image = Column(String(1024), nullable=True)
    channel_message_id = Column(String(128), nullable=True, index=True)
    visible = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category", back_populates="products")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")


class ProductImage(Base):
    __tablename__ = "product_images"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(1024), nullable=False)
    sort = Column(Integer, nullable=True, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="images")


class Color(Base):
    __tablename__ = "colors"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    slug = Column(String(128), nullable=True)


class Size(Base):
    __tablename__ = "sizes"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)
    slug = Column(String(64), nullable=True)


class ProductVariant(Base):
    __tablename__ = "product_variants"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    size_id = Column(Integer, ForeignKey("sizes.id"), nullable=True)
    color_id = Column(Integer, ForeignKey("colors.id"), nullable=True)
    sku = Column(String(128), nullable=True, index=True)
    price = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    stock_quantity = Column(Integer, nullable=False, default=0)
    images = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="variants")
    # convenience relationships (used by API serializers)
    size = relationship("Size")
    color = relationship("Color")


class ProductCost(Base):
    __tablename__ = "product_costs"
    id = Column(Integer, primary_key=True, index=True)
    variant_id = Column(Integer, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    cost_price = Column(Numeric(12, 2), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ---- Content / News ----
class News(Base):
    """News/posts for the WebApp.

    The frontend calls /api/news and expects items with: id, title, text, date, images[].
    """

    __tablename__ = "news"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(512), nullable=False)
    text = Column(Text, nullable=True)
    # store list of image URLs (or any metadata) as JSON
    images = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # attribution for commissions
    manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assistant_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    promo_code = Column(String(64), nullable=True, index=True)
    subtotal_amount = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    discount_amount = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    promo_kind = Column(String(32), nullable=True)
    promo_discount_percent = Column(Numeric(5, 2), nullable=True)
    promo_owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    promo_special_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="SET NULL"), nullable=True)
    payment_uploaded_at = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=True)
    status = Column(SAEnum(OrderStatus, name="order_status"), nullable=False, default=OrderStatus.awaiting_payment.value, index=True)
    total_amount = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    delivery_price = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    delivery_type = Column(String(128), nullable=True)
    fio = Column(String(255), nullable=True)
    phone = Column(String(64), nullable=True)
    delivery_address = Column(Text, nullable=True)
    payment_screenshot = Column(String(1024), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="orders", foreign_keys=[user_id])
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    commissions = relationship("Commission", back_populates="order", cascade="all, delete-orphan")
    status_logs = relationship("OrderStatusLog", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(Integer, ForeignKey("product_variants.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    price = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    order = relationship("Order", back_populates="items")
    variant = relationship("ProductVariant")


class Commission(Base):
    __tablename__ = "commissions"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    role = Column(String(20), nullable=False)
    base_amount = Column(Numeric(12, 2), nullable=True)
    percent = Column(Numeric(5, 2), nullable=True)
    amount = Column(Numeric(12, 2), nullable=False)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    order = relationship("Order", back_populates="commissions")
    user = relationship("User", back_populates="commissions")


class UserManagerBinding(Base):
    __tablename__ = "user_manager_bindings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_type = Column(String(20), nullable=False)
    bound_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    via_promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=True)


class ManagerAssistant(Base):
    __tablename__ = "manager_assistants"
    id = Column(Integer, primary_key=True, index=True)
    manager_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assistant_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    percent = Column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("assistant_id", name="uq_manager_assistant_assistant_id"),)


class PromoCode(Base):
    __tablename__ = "promo_codes"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), nullable=False, unique=True, index=True)
    type = Column(SAEnum(PromoType, name="promo_type"), nullable=False)
    value = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="RUB")
    expires_at = Column(DateTime, nullable=True)
    usage_limit = Column(Integer, nullable=True)
    used_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class PromoUsage(Base):
    __tablename__ = "promo_usage"
    id = Column(Integer, primary_key=True, index=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class WithdrawRequest(Base):
    __tablename__ = "withdraw_requests"

    id = Column(Integer, primary_key=True, index=True)

    requester_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    manager_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    admin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(8), default="RUB")
    target_details = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    admin_note = Column(Text, nullable=True)

    requester = relationship(
        "User",
        back_populates="withdraw_requests",
        foreign_keys=[requester_user_id],
    )

    manager = relationship(
        "User",
        foreign_keys=[manager_user_id],
    )

    admin = relationship(
        "User",
        foreign_keys=[admin_user_id],
    )


class OrderStatusLog(Base):
    __tablename__ = "order_status_logs"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(String(64), nullable=False)
    new_status = Column(String(64), nullable=False)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    order = relationship("Order", back_populates="status_logs")


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    message = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    sent_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="notification_logs")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(255), nullable=False)
    target = Column(String(255), nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("user_id", "variant_id", name="uq_cart_user_variant"),
    )
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(Integer, ForeignKey("product_variants.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    added_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="cart_items")
    variant = relationship("ProductVariant")


# ---- Extra helpful table for fast sales reporting ----


class PaymentSettings(Base):
    __tablename__ = "payment_settings"
    # singleton row: id=1
    id = Column(Integer, primary_key=True, default=1)
    recipient_name = Column(String(255), nullable=True)
    phone = Column(String(64), nullable=True)
    card_number = Column(String(64), nullable=True)
    bank_name = Column(String(128), nullable=True)
    note = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class Favorite(Base):
    __tablename__ = "favorites"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_favorites_user_product"),
    )

    user = relationship("User")
    product = relationship("Product")


class CartState(Base):
    __tablename__ = "cart_state"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    promo_code = Column(String(64), nullable=True)
    referral_code = Column(String(64), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class PromoReservation(Base):
    __tablename__ = "promo_reservations"
    id = Column(Integer, primary_key=True, index=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reserved_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)

    promo_code = relationship("PromoCode")
    user = relationship("User")
    order = relationship("Order")


class OrderSale(Base):
    __tablename__ = "order_sales"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=True, index=True)
    total = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    cost = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    manager_percent = Column(Numeric(5, 2), nullable=True)
    manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # optional relationships
    order = relationship("Order")
    manager = relationship("User", foreign_keys=[manager_id])


class SupplierSource(Base):
    __tablename__ = "supplier_sources"

    id = Column(Integer, primary_key=True, index=True)
    source_url = Column(String(2000), nullable=False, unique=True)
    supplier_name = Column(String(255), nullable=True)
    manager_name = Column(String(255), nullable=True)
    manager_contact = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


# ---- Indexes for performance ----
Index("ix_products_slug", Product.slug)
Index("ix_categories_name", Category.name)
