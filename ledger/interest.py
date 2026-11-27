from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from ledger.journal import AccountRef, InternalAccount, Leg, Posting, PostingKind
from ledger.money import Money, quantize
from ledger.processor import Ledger


@dataclass(frozen=True)
class Accrual:
    day: int
    base: Money
    raw: Decimal
    rounded: Money
    carry: Decimal


@dataclass(frozen=True)
class Capitalization:
    account: str
    day: int
    accruals: tuple[Accrual, ...]
    exact: Decimal
    total: Money
    carry_in: Decimal
    carry_out: Decimal
    posting_id: str | None


def accrue(
    bases: Sequence[tuple[int, Money]],
    rate: Decimal,
    rounding: str,
    carry_in: Decimal,
) -> tuple[tuple[Accrual, ...], Money, Decimal]:
    """Round each day's accrual after adding the carry; the lost fraction moves to the
    next day (D6). The sum of the rounded values is the total, by construction.
    A rounded value is never below zero: a negative remainder stays in the carry."""
    if not bases:
        raise ValueError("bases must not be empty")
    currency = bases[0][1].currency
    carry = carry_in
    total = Money.zero(currency)
    accruals: list[Accrual] = []
    for day, base in bases:
        raw = base.amount * rate if base.amount > 0 else Decimal(0)
        rounded = quantize(raw + carry, currency, rounding)
        if rounded.is_negative():
            rounded = Money.zero(currency)
        carry = raw + carry - rounded.amount
        total += rounded
        accruals.append(Accrual(day, base, raw, rounded, carry))
    return tuple(accruals), total, carry


def capitalize(ledger: Ledger, day: int) -> tuple[Capitalization, ...]:
    """Post one interest credit per customer account for the days since its last
    capitalization, on value-dated balances as known now (D5)."""
    if isinstance(day, bool) or not isinstance(day, int) or day < 1:
        raise ValueError(f"day must be a positive int, not {day!r}")
    journal = ledger.journal
    config = ledger.config
    records: list[Capitalization] = []
    for account in ledger.customer_accounts():
        key = (account.code, day)
        done = ledger.capitalizations.get(key)
        if done is not None:
            records.append(done)
            continue
        start = 1 + max(
            (d for code, d in ledger.capitalizations if code == account.code), default=0
        )
        if start > day:
            continue
        bases = [(d, journal.balance(account, value_day_upto=d)) for d in range(start, day + 1)]
        carry_in = ledger.interest_carry.get(account.code, Decimal(0))
        accruals, total, carry_out = accrue(
            bases, config.daily_interest_rate, config.rounding, carry_in
        )
        posting_id = None
        if not total.is_zero():
            posting_id = f"INTEREST/{account.code}/D{day}"
            journal.append(_posting(posting_id, account, total, day))
        record = Capitalization(
            account=account.code,
            day=day,
            accruals=accruals,
            exact=sum((a.raw for a in accruals), Decimal(0)),
            total=total,
            carry_in=carry_in,
            carry_out=carry_out,
            posting_id=posting_id,
        )
        ledger.interest_carry[account.code] = carry_out
        ledger.capitalizations[key] = record
        records.append(record)
    return tuple(records)


def _posting(posting_id: str, account: AccountRef, total: Money, day: int) -> Posting:
    expense = AccountRef.internal_for(InternalAccount.INTEREST_EXPENSE, account.currency)
    return Posting(
        posting_id=posting_id,
        kind=PostingKind.INTEREST,
        value_day=day,
        booked_day=day,
        legs=(Leg(account, total), Leg(expense, -total)),
        cause=f"close-D{day}",
    )
