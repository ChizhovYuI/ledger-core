import decimal
from decimal import ROUND_HALF_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledger.config import LedgerConfig
from ledger.errors import PostingShapeError
from ledger.events import Credit, Debit
from ledger.interest import Capitalization, accrue, capitalize
from ledger.journal import AccountRef, InternalAccount, Leg, Posting, PostingKind
from ledger.money import AED, BHD, Currency, Money
from ledger.processor import Ledger, Status
from ledger.replay import Replay, replay_stream


def _aed(value: str) -> Money:
    return Money.of(value, AED)


def _bhd(value: str) -> Money:
    return Money.of(value, BHD)


def _capitalization(replay: Replay, code: str) -> Capitalization:
    return next(c for c in replay.report(6).close.interest if c.account == code)


def _interest_postings(ledger: Ledger) -> list[Posting]:
    return [p for p in ledger.journal.postings if p.kind is PostingKind.INTEREST]


def _expense(currency: Currency) -> AccountRef:
    return AccountRef.internal_for(InternalAccount.INTEREST_EXPENSE, currency)


def test_acc_001_accruals() -> None:
    replay = replay_stream()

    record = _capitalization(replay, "ACC-001")

    assert [a.day for a in record.accruals] == [1, 2, 3, 4, 5, 6]
    assert [a.base for a in record.accruals] == [
        _aed(v) for v in ("250", "250", "650", "285", "285", "285")
    ]
    assert [a.raw for a in record.accruals] == [
        Decimal(v) for v in ("0.100", "0.100", "0.260", "0.114", "0.114", "0.114")
    ]
    assert [a.rounded for a in record.accruals] == [
        _aed(v) for v in ("0.10", "0.10", "0.26", "0.11", "0.12", "0.11")
    ]
    assert record.exact == Decimal("0.802")
    assert record.total == _aed("0.80")
    assert record.carry_in == Decimal(0)
    assert record.carry_out == Decimal("0.002")
    assert record.posting_id == "INTEREST/ACC-001/D6"


def test_acc_002_accruals() -> None:
    replay = replay_stream()

    record = _capitalization(replay, "ACC-002")

    assert [a.base for a in record.accruals] == [_bhd("0")] * 4 + [_bhd("10.000")] * 2
    assert [a.rounded for a in record.accruals] == [_bhd("0")] * 4 + [_bhd("0.004")] * 2
    assert record.total == _bhd("0.008")
    assert record.carry_out == Decimal(0)
    assert record.posting_id == "INTEREST/ACC-002/D6"


def test_capitalization_posting() -> None:
    replay = replay_stream()
    journal = replay.ledger.journal

    postings = _interest_postings(replay.ledger)

    assert [p.posting_id for p in postings] == ["INTEREST/ACC-001/D6", "INTEREST/ACC-002/D6"]
    for posting, account, total in (
        (postings[0], journal.account("ACC-001"), _aed("0.80")),
        (postings[1], journal.account("ACC-002"), _bhd("0.008")),
    ):
        assert posting.value_day == 6
        assert posting.booked_day == 6
        assert posting.cause == "close-D6"
        assert posting.legs == (
            Leg(account, total),
            Leg(_expense(total.currency), -total),
        )
    for day in range(1, 6):
        assert replay.report(day).close.interest == ()


def test_carry_not_a_ledger_amount() -> None:
    replay = replay_stream()
    ledger = replay.ledger

    aed_expense = ledger.journal.balance(_expense(AED))
    bhd_expense = ledger.journal.balance(_expense(BHD))

    assert aed_expense == _aed("-0.80")
    assert bhd_expense == _bhd("-0.008")
    assert ledger.interest_carry["ACC-001"] == Decimal("0.002")
    ledger.journal.assert_balanced()


def test_negative_base_accrues_nothing() -> None:
    ledger = Ledger()
    ledger.open_account("c1", AED)
    ledger.apply(Credit("C1", "c1", booked_day=1, value_day=1, amount=_aed("100.00")))
    ledger.apply(Debit("D1", "c1", booked_day=2, value_day=2, amount=_aed("300.00")))
    ledger.apply(Credit("C2", "c1", booked_day=3, value_day=3, amount=_aed("300.00")))

    (record,) = capitalize(ledger, 3)

    assert [a.base for a in record.accruals] == [_aed("100.00"), _aed("-200.00"), _aed("100.00")]
    assert [a.raw for a in record.accruals] == [Decimal("0.04"), Decimal(0), Decimal("0.04")]
    assert record.total == _aed("0.08")


def test_capitalize_twice_posts_once() -> None:
    replay = replay_stream()
    ledger = replay.ledger
    postings = ledger.journal.postings
    carry = dict(ledger.interest_carry)

    again = capitalize(ledger, 6)

    assert again == replay.report(6).close.interest
    assert ledger.journal.postings == postings
    assert ledger.interest_carry == carry
    assert len(_interest_postings(ledger)) == 2


def test_zero_rate_posts_nothing() -> None:
    replay = replay_stream(LedgerConfig(daily_interest_rate=Decimal(0)))

    records = replay.report(6).close.interest

    assert [r.account for r in records] == ["ACC-001", "ACC-002"]
    for record in records:
        assert record.total.is_zero()
        assert record.posting_id is None
    assert _interest_postings(replay.ledger) == []


def test_interest_id_reserved() -> None:
    ledger = Ledger()
    ledger.open_account("ACC-001", AED)
    ledger.apply(Credit("C0", "ACC-001", booked_day=1, value_day=1, amount=_aed("1000.00")))
    postings = ledger.journal.postings

    outcome = ledger.apply(
        Debit("INTEREST/ACC-001/D6", "ACC-001", booked_day=1, value_day=1, amount=_aed("1.00"))
    )

    assert outcome.status is Status.REJECTED
    assert outcome.reason == "reserved_event_id"
    assert ledger.journal.postings == postings


def test_interest_kind_sign() -> None:
    customer = AccountRef("c1", AED)

    with pytest.raises(PostingShapeError):
        Posting(
            posting_id="INTEREST/c1/D6",
            kind=PostingKind.INTEREST,
            value_day=6,
            booked_day=6,
            legs=(Leg(customer, _aed("-0.80")), Leg(_expense(AED), _aed("0.80"))),
            cause="close-D6",
        )


_ROUNDING_MODES = sorted(
    getattr(decimal, name) for name in dir(decimal) if name.startswith("ROUND_")
)
_HALF_MODES = frozenset({ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_HALF_DOWN})


@st.composite
def _accrual_inputs(draw: st.DrawFn) -> tuple[list[tuple[int, Money]], Decimal, str, Decimal]:
    currency = draw(st.sampled_from([AED, BHD]))
    minor_units = draw(st.lists(st.integers(-(10**9), 10**9), min_size=1, max_size=10))
    bases = [
        (day, Money(Decimal(units).scaleb(-currency.scale), currency))
        for day, units in enumerate(minor_units, start=1)
    ]
    rate = Decimal(draw(st.integers(0, 10**6))).scaleb(-6)
    rounding = draw(st.sampled_from(_ROUNDING_MODES))
    half = currency.quantum / 2
    carry_in = Decimal(draw(st.integers(-50, 50))) * half / 50
    return bases, rate, rounding, carry_in


@given(_accrual_inputs())
def test_accrual_sum_rule(inputs: tuple[list[tuple[int, Money]], Decimal, str, Decimal]) -> None:
    bases, rate, rounding, carry_in = inputs
    currency = bases[0][1].currency
    LedgerConfig(rounding=rounding)

    accruals, total, carry_out = accrue(bases, rate, rounding, carry_in)

    assert sum((a.rounded for a in accruals), Money.zero(currency)) == total
    assert total.amount + carry_out == sum((a.raw for a in accruals), Decimal(0)) + carry_in
    assert all(not a.rounded.is_negative() for a in accruals)
    assert not total.is_negative()
    assert abs(carry_out) < currency.quantum
    if rounding in _HALF_MODES:
        assert abs(carry_out) <= currency.quantum / 2
    assert all(a.raw == 0 for (_, base), a in zip(bases, accruals, strict=True) if base.amount <= 0)


def test_round_up_negative_carry_posts_nothing_negative() -> None:
    ledger = Ledger(LedgerConfig(rounding=ROUND_UP))
    ledger.open_account("c1", AED)
    ledger.apply(Credit("C1", "c1", booked_day=1, value_day=1, amount=_aed("1.00")))
    (first,) = capitalize(ledger, 1)
    ledger.apply(Debit("D1", "c1", booked_day=2, value_day=2, amount=_aed("2.00")))
    postings = ledger.journal.postings

    (second,) = capitalize(ledger, 2)

    assert first.total == _aed("0.01")
    assert first.carry_out == Decimal("-0.0096")
    assert [a.rounded for a in second.accruals] == [_aed("0")]
    assert second.total.is_zero()
    assert second.posting_id is None
    assert second.carry_out == Decimal("-0.0096")
    assert ledger.interest_carry["c1"] == Decimal("-0.0096")
    assert ledger.journal.postings == postings
    assert [p.posting_id for p in _interest_postings(ledger)] == ["INTEREST/c1/D1"]
    ledger.journal.assert_balanced()
