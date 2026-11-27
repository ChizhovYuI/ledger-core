from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledger.close import FeeAction, close_day
from ledger.config import LedgerConfig
from ledger.events import Authorization, Credit, Debit, Event
from ledger.journal import Journal, Leg, PostingKind
from ledger.money import AED, BHD, Currency, Money
from ledger.processor import Ledger, Status
from ledger.replay import Replay

_FEE_KINDS = (PostingKind.FEE, PostingKind.FEE_REFUND)


def _aed(value: str) -> Money:
    return Money.of(value, AED)


def _ledger(config: LedgerConfig | None = None, currency: Currency = AED) -> Ledger:
    ledger = Ledger() if config is None else Ledger(config)
    ledger.open_account("c1", currency)
    return ledger


def _credit(event_id: str, amount: str, booked_day: int, value_day: int | None = None) -> Credit:
    value = booked_day if value_day is None else value_day
    return Credit(event_id, "c1", booked_day=booked_day, value_day=value, amount=_aed(amount))


def _debit(event_id: str, amount: str, booked_day: int, value_day: int | None = None) -> Debit:
    value = booked_day if value_day is None else value_day
    return Debit(event_id, "c1", booked_day=booked_day, value_day=value, amount=_aed(amount))


def _totals(legs: list[Leg]) -> dict[Currency, Money]:
    totals: dict[Currency, Money] = {}
    for leg in legs:
        currency = leg.amount.currency
        totals[currency] = totals.get(currency, Money.zero(currency)) + leg.amount
    return totals


def _fee_ids(journal: Journal) -> list[str]:
    return [p.posting_id for p in journal.postings if p.kind is PostingKind.FEE]


def test_close_twice_no_second_fee() -> None:
    ledger = _ledger(LedgerConfig(hold_expiry_days=1))
    ledger.apply(_credit("C1", "100.00", booked_day=1))
    auth = Authorization("A1", "c1", booked_day=1, value_day=1, auth_id="H1", amount=_aed("50.00"))
    assert ledger.apply(auth).status is Status.APPROVED
    ledger.apply(_debit("D1", "150.00", booked_day=2))
    first = close_day(ledger, 2, 0)
    postings = ledger.journal.postings

    again_new = close_day(ledger, 2, first.position)
    again_old = close_day(ledger, 2, 0)

    assert [c.action for c in first.checks] == [FeeAction.NONE, FeeAction.FEE]
    assert len(first.expired) == 1
    for again in (again_new, again_old):
        assert again.expired == ()
        assert all(c.action is FeeAction.NONE for c in again.checks)
        assert again.position == first.position
    assert ledger.journal.postings == postings
    assert _fee_ids(ledger.journal) == ["FEE/c1/D2/1"]


def test_skipped_day_is_closed() -> None:
    ledger = _ledger()
    replay = Replay(ledger)
    replay.feed(_debit("D1", "1.00", booked_day=1))

    replay.feed(_credit("C4", "100.00", booked_day=4))

    assert [r.day for r in replay.reports] == [1, 2, 3]
    for day, check in ((1, "-1.00"), (2, "-26.00"), (3, "-51.00")):
        (fee_check,) = replay.report(day).close.checks
        assert fee_check.day == day
        assert fee_check.check == _aed(check)
        assert fee_check.action is FeeAction.FEE
        assert fee_check.posting_id == f"FEE/c1/D{day}/1"
    assert replay.report(2).arrivals == ()
    fees = [p for p in ledger.journal.postings if p.kind is PostingKind.FEE]
    assert [(p.value_day, p.booked_day, p.links) for p in fees] == [
        (1, 1, ("D1",)),
        (2, 2, ()),
        (3, 3, ()),
    ]
    replay.finish()
    assert [r.day for r in replay.reports] == [1, 2, 3, 4, 5, 6]


def test_no_fee_currency_alert() -> None:
    ledger = _ledger(currency=BHD)
    ledger.apply(Debit("D1", "c1", booked_day=1, value_day=1, amount=Money.of("1.000", BHD)))
    position = ledger.journal.position

    close = close_day(ledger, 1, 0)

    (check,) = close.checks
    assert check.action is FeeAction.NO_FEE_CONFIGURED
    assert check.check == Money.of("-1.000", BHD)
    assert check.posting_id is None
    assert len(close.alerts) == 1
    assert close.alerts[0].startswith("no_fee_configured: c1 day 1")
    assert ledger.journal.position == position == close.position


def test_hold_expires_at_close() -> None:
    ledger = _ledger(LedgerConfig(hold_expiry_days=3))
    ledger.apply(_credit("C1", "100.00", booked_day=1))
    auth = Authorization("A1", "c1", booked_day=1, value_day=1, auth_id="H1", amount=_aed("40.00"))
    assert ledger.apply(auth).status is Status.APPROVED
    since = close_day(ledger, 1, 0).position
    since = close_day(ledger, 2, since).position

    day3 = close_day(ledger, 3, since)
    available_after_day3 = ledger.available("c1")
    day4 = close_day(ledger, 4, day3.position)

    assert day3.expired == ()
    assert available_after_day3 == _aed("60.00")
    assert [(h.auth_id, h.day) for h in day4.expired] == [("H1", 4)]
    assert ledger.available("c1") == _aed("100.00")


def test_refund_then_new_fee() -> None:
    ledger = _ledger()
    replay = Replay(ledger)
    replay.feed(_debit("D1", "10.00", booked_day=1))
    replay.feed(_credit("C2", "50.00", booked_day=2, value_day=1))

    replay.feed(_debit("D3", "100.00", booked_day=3, value_day=1))
    replay.feed(_credit("C4", "1000.00", booked_day=4))

    day1_checks = [
        (r.day, c.action, c.posting_id)
        for r in replay.reports
        for c in r.close.checks
        if c.day == 1
    ]
    assert day1_checks == [
        (1, FeeAction.FEE, "FEE/c1/D1/1"),
        (2, FeeAction.REFUND, "REFUND/FEE/c1/D1/1"),
        (3, FeeAction.FEE, "FEE/c1/D1/2"),
    ]
    second = next(p for p in ledger.journal.postings if p.posting_id == "FEE/c1/D1/2")
    assert (second.value_day, second.booked_day, second.links) == (1, 3, ("D3",))
    assert replay.report(3).close.checks[0].check == _aed("-60.00")


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        pytest.param(
            Debit("X9", "ghost", booked_day=9, value_day=9, amount=_aed("1.00")),
            "unknown_account",
            id="unknown_account",
        ),
        pytest.param(
            Debit("X9", "c1", booked_day=9, value_day=9, amount=Money.of("1.000", BHD)),
            "currency_mismatch",
            id="currency_mismatch",
        ),
        pytest.param(_debit("X9", "0.00", booked_day=9), "non_positive_amount", id="zero_amount"),
        pytest.param(_debit("FEE/c1/D9/1", "1.00", booked_day=9), "reserved_event_id", id="fee_id"),
        pytest.param(
            _debit("X9", "1.00", booked_day=9, value_day=0), "invalid_day", id="invalid_value_day"
        ),
    ],
)
def test_rejected_event_closes_no_day(event: Event, reason: str) -> None:
    ledger = _ledger()
    replay = Replay(ledger)
    replay.feed(_debit("D1", "10.00", booked_day=1))

    outcome = replay.feed(event)

    assert outcome.status is Status.REJECTED
    assert outcome.reason == reason
    assert replay.reports == ()
    assert replay.open_day == 1
    assert _fee_ids(ledger.journal) == []
    replay.feed(_credit("C2", "100.00", booked_day=2))
    assert [r.day for r in replay.reports] == [1]
    assert all(not a.late_arrival for a in replay.report(1).arrivals)
    replay.finish()
    (arrival,) = replay.report(2).arrivals
    assert arrival.event.event_id == "C2"
    assert arrival.late_arrival is False
    assert [r.day for r in replay.reports] == [1, 2, 3, 4, 5, 6]


def test_repeat_delivery_is_not_late() -> None:
    ledger = _ledger(LedgerConfig(daily_interest_rate=Decimal(0)))
    replay = Replay(ledger)
    first = replay.feed(_credit("C1", "10.00", booked_day=1))
    replay.feed(_credit("C2", "20.00", booked_day=3))

    again = replay.feed(_credit("C1", "10.00", booked_day=1))
    replay.finish()

    assert again == first
    repeat = replay.report(3).arrivals[-1]
    assert repeat.event.event_id == "C1"
    assert repeat.late_arrival is False
    assert not any(a.startswith("late_arrival") for a in replay.report(3).alerts)
    assert ledger.journal.balance(ledger.journal.account("c1")) == _aed("30.00")


_movements = st.lists(
    st.tuples(
        st.booleans(),
        st.integers(1, 50_000),
        st.integers(1, 6),
        st.integers(0, 5),
    ),
    max_size=12,
)


def _events(movements: list[tuple[bool, int, int, int]], code: str = "c1") -> list[Event]:
    events: list[Event] = []
    for number, (is_credit, minor, booked_day, lag) in enumerate(movements):
        currency = AED if code == "c1" else BHD
        amount = Money(Decimal(minor).scaleb(-currency.scale), currency)
        value_day = max(1, booked_day - lag)
        kind = Credit if is_credit else Debit
        events.append(kind(f"{code}-{number}", code, booked_day, value_day, amount))
    return events


def _in_booked_order(events: list[Event]) -> list[Event]:
    return sorted(events, key=lambda event: event.booked_day)


@settings(max_examples=60, deadline=None)
@given(_movements)
def test_fees_match_final_history(movements: list[tuple[bool, int, int, int]]) -> None:
    ledger = _ledger()
    replay = Replay(ledger)
    for event in _in_booked_order(_events(movements)):
        replay.feed(event)
    replay.finish()

    journal = ledger.journal
    account = journal.account("c1")
    refunded = {
        link for p in journal.postings if p.kind is PostingKind.FEE_REFUND for link in p.links
    }
    for report in replay.reports:
        day = report.day
        own_day = [p for p in journal.postings if p.kind in _FEE_KINDS and p.value_day == day]
        check = journal.balance(account, value_day_upto=day)
        for posting in own_day:
            check -= posting.customer_leg.amount
        open_fees = [
            p for p in own_day if p.kind is PostingKind.FEE and p.posting_id not in refunded
        ]
        assert len(open_fees) == (1 if check.is_negative() else 0), (day, check)


@settings(max_examples=60, deadline=None)
@given(_movements, _movements)
def test_journal_balances(
    aed_movements: list[tuple[bool, int, int, int]],
    bhd_movements: list[tuple[bool, int, int, int]],
) -> None:
    ledger = _ledger()
    ledger.open_account("c2", BHD)
    replay = Replay(ledger)
    events = _events(aed_movements) + _events(bhd_movements, code="c2")
    for event in _in_booked_order(events):
        replay.feed(event)
    replay.finish()

    postings = ledger.journal.postings
    for report in replay.reports:
        legs = [leg for p in postings[: report.close.position] for leg in p.legs]
        assert all(total.is_zero() for total in _totals(legs).values()), report.day
    ledger.journal.assert_balanced()
