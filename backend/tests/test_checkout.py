import pytest
from app.api.v1.checkout import _quantize_money
from decimal import Decimal

def test_quantize_money():
    assert _quantize_money(Decimal('10')) == Decimal('10.00')
    assert _quantize_money(Decimal('10.129')) == Decimal('10.13')
    assert _quantize_money(Decimal('0')) == Decimal('0.00')

