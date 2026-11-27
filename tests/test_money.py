import dataclasses
from decimal import Decimal

import pytest

from ledger.config import LedgerConfig
from ledger.errors import AmountPrecisionError, CurrencyMismatchError
from ledger.money import AED, BHD, Money, quantize


def test_currency_scale() -> None:
    assert AED.scale == 2
    assert BHD.scale == 3
    assert str(Money.of("1200", AED)) == "1200.00 AED"
    assert str(Money.of("10", BHD).amount) == "10.000"


def test_too_fine_amount_rejected() -> None:
    with pytest.raises(AmountPrecisionError):
        Money.of("10.001", AED)
    with pytest.raises(AmountPrecisionError):
        Money.of("3.3333", BHD)
    with pytest.raises(TypeError):
        Money(1.5, AED)
    with pytest.raises(TypeError):
        Money.of(1.5, AED)
    with pytest.raises(TypeError):
        Money.of(True, AED)
    with pytest.raises(AmountPrecisionError):
        Money.of("1e26", AED)


def test_currency_mismatch() -> None:
    with pytest.raises(CurrencyMismatchError):
        Money.of("1", AED) + Money.of("1", BHD)


@pytest.mark.parametrize(("raw", "expected"), [("0.125", "0.12"), ("0.135", "0.14")])
def test_quantize_half_even(raw: str, expected: str) -> None:
    assert quantize(Decimal(raw), AED) == Money.of(expected, AED)


def test_config_defaults() -> None:
    config = LedgerConfig()

    assert config.fee_for(AED) == Money.of("25.00", AED)
    assert config.fee_for(BHD) is None
    assert config.daily_interest_rate == Decimal("0.0004")
    assert config.hold_expiry_days == 10
    assert config.window_days == 6


def test_config_override() -> None:
    config = dataclasses.replace(LedgerConfig(), hold_expiry_days=3)

    assert config.hold_expiry_days == 3
    assert config.window_days == 6
    assert config.fee_for(AED) == Money.of("25.00", AED)


@pytest.mark.parametrize(
    "override",
    [
        {"hold_expiry_days": True},
        {"window_days": 1.5},
        {"rounding": "bogus"},
        {"daily_interest_rate": 0.0004},
    ],
)
def test_config_rejects_bad_values(override: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        LedgerConfig(**override)
