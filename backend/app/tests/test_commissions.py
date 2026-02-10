# backend/app/tests/test_commissions.py
import pytest
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, User, Manager, Assistant, Product, ProductVariant, Order, OrderItem, PromoCode
from app.services.commissions import calculate_and_record_commissions

# Use in-memory SQLite for tests
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


def test_manager_and_assistant_commission_simple(db_session):
    # create manager user
    manager_user = User(telegram_id="mgr1", username="mgr1", role='manager', balance=Decimal('0.00'))
    db_session.add(manager_user)
    db_session.flush()

    manager = Manager(user_id=manager_user.id, first_n_count=3, first_n_rate=Decimal('0.10'), ongoing_rate=Decimal('0.05'), assistant_max_rate=Decimal('0.10'))
    db_session.add(manager)
    db_session.flush()

    manager_user.manager_id = manager.id
    db_session.flush()

    # create assistant
    assistant_user = User(telegram_id="ast1", username="ast1", role='assistant', balance=Decimal('0.00'))
    db_session.add(assistant_user)
    db_session.flush()

    assistant = Assistant(user_id=assistant_user.id, manager_id=manager.id, assigned_rate=Decimal('0.10'))
    db_session.add(assistant)
    db_session.flush()

    assistant_user.assistant_id = assistant.id
    db_session.flush()

    # create customer and bind to assistant via promo (simulate binding)
    customer = User(telegram_id="cust1", username="cust1", role='customer', balance=Decimal('0.00'),
                    bound_owner_id=assistant_user.id, bound_owner_type='assistant')
    db_session.add(customer)
    db_session.flush()

    # create an order (first paid order)
    order = Order(user_id=customer.id, status='paid', total_amount=Decimal('10000.00'), manager_id=None, assistant_id=None)
    db_session.add(order)
    db_session.flush()

    # call commission calc
    calculate_and_record_commissions(db_session, order.id, commit=True)

    # reload entities
    db_session.refresh(manager_user)
    db_session.refresh(assistant_user)

    # manager should have received 10% of 10000 = 1000.00
    assert manager_user.balance == Decimal('1000.00')

    # Commission records: 2 entries (manager credited, assistant owed)
    records = db_session.query(models.CommissionRecord).filter(models.CommissionRecord.order_id == order.id).all()
    assert len(records) == 2
    mgr_rec = [r for r in records if r.role == 'manager'][0]
    ast_rec = [r for r in records if r.role == 'assistant'][0]
    assert mgr_rec.amount == Decimal('1000.00')
    # assistant gets 10% of manager gross = 1000 * 0.10 = 100.00
    assert ast_rec.amount == Decimal('100.00')


def test_manager_ongoing_rate_after_three(db_session):
    # create manager user and manager
    manager_user = User(telegram_id="mgr2", username="mgr2", role='manager', balance=Decimal('0.00'))
    db_session.add(manager_user)
    db_session.flush()
    manager = Manager(user_id=manager_user.id, first_n_count=3, first_n_rate=Decimal('0.10'), ongoing_rate=Decimal('0.05'), assistant_max_rate=Decimal('0.10'))
    db_session.add(manager)
    db_session.flush()
    manager_user.manager_id = manager.id
    db_session.flush()

    # customer bound to manager
    customer = User(telegram_id="cust2", username="cust2", role='customer', balance=Decimal('0.00'),
                    bound_owner_id=manager_user.id, bound_owner_type='manager')
    db_session.add(customer)
    db_session.flush()

    # create 3 prior paid orders for this customer under this manager
    for _ in range(3):
        past_order = Order(user_id=customer.id, status='paid', total_amount=Decimal('100.00'), manager_id=manager.id)
        db_session.add(past_order)
    db_session.flush()

    # new order (4th) should be at ongoing_rate 5%
    order = Order(user_id=customer.id, status='paid', total_amount=Decimal('200.00'))
    db_session.add(order)
    db_session.flush()

    calculate_and_record_commissions(db_session, order.id, commit=True)

    db_session.refresh(manager_user)
    # manager should be credited with 5% of 200 = 10.00
    assert manager_user.balance == Decimal('10.00')

