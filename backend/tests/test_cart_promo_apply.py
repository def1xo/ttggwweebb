from fastapi import HTTPException

from app.api.v1 import cart
from app.db import models


class _Payload:
    def __init__(self, code: str):
        self.code = code


def test_apply_promo_returns_400_for_own_referral_code(tmp_db):
    user = models.User(telegram_id=101, role=models.UserRole.user, promo_code="MYREF")
    tmp_db.add(user)
    tmp_db.commit()
    tmp_db.refresh(user)

    try:
        cart.apply_promo(_Payload("MYREF"), db=tmp_db, user=user)
        raised = None
    except HTTPException as exc:
        raised = exc

    assert raised is not None
    assert raised.status_code == 400
    assert raised.detail == "you cannot apply your own referral code"


def test_apply_promo_applies_referral_of_another_user(tmp_db):
    owner = models.User(telegram_id=201, role=models.UserRole.manager, promo_code="OWNERREF")
    buyer = models.User(telegram_id=202, role=models.UserRole.user)
    tmp_db.add_all([owner, buyer])
    tmp_db.commit()
    tmp_db.refresh(buyer)

    out = cart.apply_promo(_Payload("OWNERREF"), db=tmp_db, user=buyer)
    st = tmp_db.query(models.CartState).filter(models.CartState.user_id == buyer.id).one()

    assert st.referral_code == "OWNERREF"
    assert out.promo is not None
    assert out.promo.kind == "referral"
