from ledger.close import FeeAction
from ledger.events import Credit
from ledger.journal import AccountRef, InternalAccount, Posting, PostingKind
from ledger.money import AED, BHD, Money
from ledger.processor import Ledger, Status
from ledger.replay import Replay, replay_stream
from ledger.stream import STREAM, open_accounts


def _aed(value: str) -> Money:
    return Money.of(value, AED)


def _bhd(value: str) -> Money:
    return Money.of(value, BHD)


def _posting(replay: Replay, posting_id: str) -> Posting:
    return next(p for p in replay.ledger.journal.postings if p.posting_id == posting_id)


def _internal(replay: Replay, kind: InternalAccount, known_at: int | None = None) -> Money:
    ref = AccountRef.internal_for(kind, AED)
    return replay.ledger.journal.balance(ref, known_at=known_at)


def test_day5_fee_checks() -> None:
    replay = replay_stream()

    checks = [c for c in replay.report(5).close.checks if c.account == "ACC-001"]

    assert [(c.day, c.check, c.action) for c in checks] == [
        (2, _aed("-370.00"), FeeAction.FEE),
        (3, _aed("5.00"), FeeAction.NONE),
        (4, _aed("-360.00"), FeeAction.FEE),
        (5, _aed("-385.00"), FeeAction.FEE),
    ]
    fees = [_posting(replay, c.posting_id) for c in checks if c.posting_id is not None]
    assert [f.posting_id for f in fees] == [
        "FEE/ACC-001/D2/1",
        "FEE/ACC-001/D4/1",
        "FEE/ACC-001/D5/1",
    ]
    for fee, value_day in zip(fees, (2, 4, 5), strict=True):
        assert fee.kind is PostingKind.FEE
        assert fee.customer_leg.amount == _aed("-25.00")
        assert fee.value_day == value_day
        assert fee.booked_day == 5
        assert fee.links == ("E7",)
        assert fee.cause == "close-D5"


def test_day6_refunds() -> None:
    replay = replay_stream()

    checks = replay.report(6).close.checks
    refunds = [_posting(replay, c.posting_id) for c in checks if c.action is FeeAction.REFUND]

    assert [r.value_day for r in refunds] == [2, 4, 5]
    for refund in refunds:
        fee_id = f"FEE/ACC-001/D{refund.value_day}/1"
        assert refund.posting_id == f"REFUND/{fee_id}"
        assert refund.kind is PostingKind.FEE_REFUND
        assert refund.customer_leg.amount == _aed("25.00")
        assert refund.booked_day == 6
        assert refund.links == (fee_id, "E9")
        assert refund.cause == "close-D6"
    assert [c.action for c in checks if c.action in (FeeAction.FEE, FeeAction.REFUND)] == [
        FeeAction.REFUND
    ] * 3


def test_as_known_closes() -> None:
    replay = replay_stream()

    acc_001 = [replay.as_known("ACC-001", day) for day in range(1, 7)]
    acc_002 = [replay.as_known("ACC-002", day) for day in range(1, 7)]

    assert acc_001 == [
        _aed(v) for v in ("250.00", "250.00", "650.00", "285.00", "-410.00", "285.80")
    ]
    assert acc_002 == [_bhd("0.000")] * 5 + [_bhd("10.008")]
    assert str(acc_002[4].amount) == "0.000"


def test_restated_closes() -> None:
    replay = replay_stream()

    acc_001 = [replay.restated("ACC-001", day) for day in range(1, 7)]
    acc_002 = [replay.restated("ACC-002", day) for day in range(1, 7)]

    assert acc_001 == [
        _aed(v) for v in ("250.00", "250.00", "650.00", "285.00", "285.00", "285.80")
    ]
    assert acc_002 == [_bhd("0.000")] * 4 + [_bhd("10.000"), _bhd("10.008")]


def test_auth_b_declined_before_fees() -> None:
    replay = replay_stream()

    e8 = next(a for a in replay.report(5).arrivals if a.event.event_id == "E8")

    assert e8.outcome.status is Status.DECLINED
    assert e8.outcome.ledger == _aed("-335.00")
    assert e8.outcome.available_after == _aed("-425.00")
    assert e8.late_arrival is False


def test_e10_late_arrival() -> None:
    replay = replay_stream()

    day6 = replay.report(6)
    e10 = next(a for a in day6.arrivals if a.event.event_id == "E10")

    assert e10.late_arrival is True
    assert e10.outcome.status is Status.POSTED
    assert [a for a in day6.alerts if a.startswith("late_arrival")] == [
        "late_arrival: E10 booked day 5, arrived on day 6"
    ]
    assert all(not a.late_arrival for a in replay.report(5).arrivals)
    assert str(replay.as_known("ACC-002", 5).amount) == "0.000"


def test_end_state() -> None:
    replay = replay_stream()
    journal = replay.ledger.journal

    day5_position = replay.report(5).close.position

    assert _internal(replay, InternalAccount.FEE_INCOME) == _aed("0.00")
    assert _internal(replay, InternalAccount.FEE_INCOME, known_at=day5_position) == _aed("75.00")
    assert journal.balance(journal.account("ACC-001")) == _aed("285.80")
    assert _internal(replay, InternalAccount.CARD_SETTLEMENT) == _aed("365.00")
    assert _internal(replay, InternalAccount.EXTERNAL) == _aed("-650.00")
    assert _internal(replay, InternalAccount.INTEREST_EXPENSE) == _aed("-0.80")
    bhd_expense = AccountRef.internal_for(InternalAccount.INTEREST_EXPENSE, BHD)
    assert journal.balance(bhd_expense) == _bhd("-0.008")
    bhd_external = AccountRef.internal_for(InternalAccount.EXTERNAL, BHD)
    assert journal.balance(bhd_external) == _bhd("-10.000")
    assert journal.balance(journal.account("ACC-002")) == _bhd("10.008")
    assert [r.day for r in replay.reports] == [1, 2, 3, 4, 5, 6]
    journal.assert_balanced()


def test_rejected_late_event_after_stream() -> None:
    ledger = Ledger()
    open_accounts(ledger)
    replay = Replay(ledger)
    for event in STREAM:
        replay.feed(event)
    late = Credit("E11", "ACC-001", booked_day=9, value_day=9, amount=_aed("10.00"), instalments=0)

    outcome = replay.feed(late)
    replay.finish()

    assert outcome.status is Status.REJECTED
    assert outcome.reason == "invalid_instalments"
    assert [r.day for r in replay.reports] == [1, 2, 3, 4, 5, 6]
    assert sorted(ledger.capitalizations) == [("ACC-001", 6), ("ACC-002", 6)]
    journal = ledger.journal
    assert journal.balance(journal.account("ACC-001")) == _aed("285.80")
    assert journal.balance(journal.account("ACC-002")) == _bhd("10.008")
