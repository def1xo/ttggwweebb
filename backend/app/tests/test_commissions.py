from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Commission, ManagerAssistant, Order, User, UserRole
from app.services.commissions import compute_and_apply_commissions

TEST_DB = "sqlite:///:memory:"


@pytest.fixture()
def db_session():
    engine = create_engine(TEST_DB, echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_compute_and_apply_commissions_manager_and_assistant_first_n(db_session):
    manager_user = User(
        telegram_id=101,
        username="mgr1",
        role=UserRole.manager,
        balance=Decimal("0.00"),
        first_n_count=3,
        first_n_rate=Decimal("0.10"),
        ongoing_rate=Decimal("0.05"),
    )
    assistant_user = User(
        telegram_id=102,
        username="ast1",
        role=UserRole.assistant,
        balance=Decimal("0.00"),
    )
    customer_user = User(
        telegram_id=103,
        username="cust1",
        role=UserRole.user,
        balance=Decimal("0.00"),
    )
    db_session.add_all([manager_user, assistant_user, customer_user])
    db_session.flush()

    db_session.add(ManagerAssistant(manager_id=manager_user.id, assistant_id=assistant_user.id, percent=10))
    db_session.flush()

    order = Order(
        user_id=customer_user.id,
        manager_id=manager_user.id,
        assistant_id=assistant_user.id,
        status="paid",
        total_amount=Decimal("10000.00"),
    )
    db_session.add(order)
    db_session.flush()

    created = compute_and_apply_commissions(db_session, order, admin_user_id=None, update_order_status=True)
    db_session.commit()

    db_session.refresh(manager_user)
    db_session.refresh(assistant_user)

    assert manager_user.balance == Decimal("900.00")
    assert assistant_user.balance == Decimal("100.00")

    manager_record = next(c for c in created if c.role == "manager")
    assistant_record = next(c for c in created if c.role == "assistant")
    admin_record = next(c for c in created if c.role == "admin")

    assert manager_record.base_amount == Decimal("1000.00")
    assert manager_record.amount == Decimal("900.00")
    assert assistant_record.amount == Decimal("100.00")
    assert admin_record.amount == Decimal("9000.00")


def test_compute_and_apply_commissions_uses_ongoing_rate_after_first_n(db_session):
    manager_user = User(
        telegram_id=201,
        username="mgr2",
        role=UserRole.manager,
        balance=Decimal("0.00"),
        first_n_count=3,
        first_n_rate=Decimal("0.10"),
        ongoing_rate=Decimal("0.05"),
    )
    customer_user = User(
        telegram_id=202,
        username="cust2",
        role=UserRole.user,
        balance=Decimal("0.00"),
    )
    db_session.add_all([manager_user, customer_user])
    db_session.flush()

    for _ in range(3):
        db_session.add(
            Order(
                user_id=customer_user.id,
                manager_id=manager_user.id,
                status="paid",
                total_amount=Decimal("100.00"),
            )
        )
    db_session.flush()

    current_order = Order(
        user_id=customer_user.id,
        manager_id=manager_user.id,
        status="paid",
        total_amount=Decimal("200.00"),
    )
    db_session.add(current_order)
    db_session.flush()

    compute_and_apply_commissions(db_session, current_order, admin_user_id=None, update_order_status=True)
    db_session.commit()

    db_session.refresh(manager_user)
    assert manager_user.balance == Decimal("10.00")

    manager_commission = (
        db_session.query(Commission)
        .filter(Commission.order_id == current_order.id, Commission.role == "manager")
        .one()
    )
    assert manager_commission.amount == Decimal("10.00")
