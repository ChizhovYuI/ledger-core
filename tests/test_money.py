import dataclasses
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledger.config import LedgerConfig
from ledger.errors import AmountPrecisionError, CurrencyMismatchError
from ledger.money import AED, BHD, Currency, Money, quantize, split


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
        {"overdraft_fee": {AED: Money.of("-25.00", AED)}},
        {"overdraft_fee": {AED: Money.of("0.00", AED)}},
    ],
)
def test_config_rejects_bad_values(override: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        LedgerConfig(**override)


def test_split_bhd_ten_in_three() -> None:
    parts = split(Money.of("10.000", BHD), 3)

    assert parts == (
        Money.of("3.334", BHD),
        Money.of("3.333", BHD),
        Money.of("3.333", BHD),
    )


@given(
    st.sampled_from([AED, BHD]),
    st.integers(-(10**12), 10**12),
    st.integers(1, 50),
)
def test_split_property(currency: Currency, minor: int, count: int) -> None:
    money = Money(Decimal(minor).scaleb(-currency.scale), currency)

    parts = split(money, count)

    assert len(parts) == count
    assert sum(parts, start=Money.zero(currency)) == money
    sizes = [abs(part.amount) for part in parts]
    assert max(sizes) - min(sizes) <= currency.quantum
    assert sizes == sorted(sizes, reverse=True)
    assert all(part.currency == currency for part in parts)


@pytest.mark.parametrize("count", [0, -1, True, 1.5])
def test_split_parts_below_one_rejected(count: object) -> None:
    with pytest.raises(ValueError):
        split(Money.of("10", AED), count)
