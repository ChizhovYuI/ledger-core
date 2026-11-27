from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from ledger.errors import AmountPrecisionError, CurrencyMismatchError, UnknownCurrencyError


@dataclass(frozen=True)
class Currency:
    code: str
    scale: int

    @property
    def quantum(self) -> Decimal:
        return Decimal(1).scaleb(-self.scale)

    def __str__(self) -> str:
        return self.code


AED = Currency("AED", 2)
BHD = Currency("BHD", 3)

_CURRENCIES = {c.code: c for c in (AED, BHD)}


def currency(code: str) -> Currency:
    try:
        return _CURRENCIES[code]
    except KeyError:
        raise UnknownCurrencyError(code) from None


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        amount = self.amount
        if isinstance(amount, bool) or not isinstance(amount, Decimal | int):
            raise TypeError(f"amount must be Decimal or int, not {type(amount).__name__}")
        amount = Decimal(amount)
        if not amount.is_finite():
            raise AmountPrecisionError(f"amount is not finite: {amount}")
        try:
            scaled = amount.quantize(self.currency.quantum)
        except InvalidOperation:
            raise AmountPrecisionError(f"{amount} does not fit the decimal precision") from None
        if scaled != amount:
            raise AmountPrecisionError(
                f"{amount} is finer than {self.currency.code} scale {self.currency.scale}"
            )
        if scaled.is_zero():
            scaled = abs(scaled)
        object.__setattr__(self, "amount", scaled)

    @classmethod
    def of(cls, value: str | int | Decimal, currency: Currency) -> Money:
        if isinstance(value, float | bool):
            raise TypeError(f"amount must not be {type(value).__name__}")
        try:
            amount = Decimal(value)
        except InvalidOperation:
            raise ValueError(f"not a decimal amount: {value!r}") from None
        return cls(amount, currency)

    @classmethod
    def zero(cls, currency: Currency) -> Money:
        return cls(Decimal(0), currency)

    def _same_currency(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, not {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatchError(f"{self.currency.code} and {other.currency.code}")

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def is_negative(self) -> bool:
        return self.amount < 0

    def is_zero(self) -> bool:
        return self.amount.is_zero()

    def __str__(self) -> str:
        return f"{self.amount} {self.currency.code}"


def split(money: Money, parts: int) -> tuple[Money, ...]:
    """Equal parts at the currency scale; leftover minor units go to the earliest parts."""
    if isinstance(parts, bool) or not isinstance(parts, int) or parts < 1:
        raise ValueError(f"parts must be an int of at least 1, not {parts!r}")
    scale = money.currency.scale
    minor = int(money.amount.scaleb(scale))
    base, rest = divmod(abs(minor), parts)
    sign = -1 if minor < 0 else 1
    return tuple(
        Money(Decimal(sign * (base + (1 if index < rest else 0))).scaleb(-scale), money.currency)
        for index in range(parts)
    )


def quantize(raw: Decimal, currency: Currency, rounding: str = ROUND_HALF_EVEN) -> Money:
    """The one place where a computed value becomes an amount at the currency scale."""
    try:
        return Money(raw.quantize(currency.quantum, rounding=rounding), currency)
    except InvalidOperation:
        raise AmountPrecisionError(f"{raw} does not fit the decimal precision") from None
