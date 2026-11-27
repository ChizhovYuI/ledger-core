from __future__ import annotations

import decimal
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from types import MappingProxyType

from ledger.money import AED, Currency, Money

_ROUNDING_MODES = frozenset(
    getattr(decimal, name) for name in dir(decimal) if name.startswith("ROUND_")
)


def _default_fees() -> Mapping[Currency, Money]:
    return {AED: Money.of("25.00", AED)}


@dataclass(frozen=True)
class LedgerConfig:
    # No BHD entry: a negative close in a currency with no fee gives an alert, not a fee.
    overdraft_fee: Mapping[Currency, Money] = field(default_factory=_default_fees)
    daily_interest_rate: Decimal = Decimal("0.0004")
    hold_expiry_days: int = 10
    rounding: str = ROUND_HALF_EVEN
    window_days: int = 6

    def __post_init__(self) -> None:
        fees = dict(self.overdraft_fee)
        for ccy, fee in fees.items():
            if fee.currency != ccy:
                raise ValueError(f"fee for {ccy.code} is in {fee.currency.code}")
            if fee.is_negative() or fee.is_zero():
                raise ValueError(f"fee for {ccy.code} must be positive")
        if not isinstance(self.daily_interest_rate, Decimal) or self.daily_interest_rate < 0:
            raise ValueError("daily_interest_rate must be a Decimal, not negative")
        for name in ("hold_expiry_days", "window_days"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an int of at least 1")
        if self.rounding not in _ROUNDING_MODES:
            raise ValueError(f"unknown rounding mode {self.rounding!r}")
        object.__setattr__(self, "overdraft_fee", MappingProxyType(fees))

    def fee_for(self, currency: Currency) -> Money | None:
        return self.overdraft_fee.get(currency)


DEFAULT_CONFIG = LedgerConfig()
