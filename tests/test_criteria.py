"""One test per acceptance criterion of the brief. Each docstring says accept or
refuse, and why."""

from collections.abc import Iterable
from decimal import Decimal

from ledger.close import FeeAction
from ledger.events import Event
from ledger.holds import HoldChangeKind
from ledger.journal import AccountRef, InternalAccount, PostingKind
from ledger.money import AED, BHD, Money, split
from ledger.processor import AuthState, Ledger, Status
from ledger.replay import Replay, replay_stream
from ledger.stream import STREAM, open_accounts


def _aed(value: str) -> Money:
    return Money.of(value, AED)


def _replay(events: Iterable[Event]) -> Replay:
    ledger = Ledger()
    open_accounts(ledger)
    replay = Replay(ledger)
    for event in events:
        replay.feed(event)
    replay.finish()
    return replay


def _without(*event_ids: str) -> Replay:
    return _replay(e for e in STREAM if e.event_id not in event_ids)


def _outcome(replay: Replay, event_id: str):
    return next(o for o in replay.ledger.outcomes if o.event_id == event_id)


def test_criterion_1_day2_check_before_any_fee() -> None:
    """Accept. At the Day 5 close, the Day 2 check is -370.00: E7 is in it, and no fee
    is, because a fee does not count in the check of its own day."""
    replay = replay_stream()

    day2 = next(c for c in replay.report(5).close.checks if c.day == 2)

    assert day2.check == _aed("-370.00")
    assert day2.action is FeeAction.FEE


def test_criterion_2_three_fees_not_one() -> None:
    """Refuse. Backdated E7 makes Days 2, 4 and 5 negative, so the rule gives three
    fees, not one (D1)."""
    replay = replay_stream()

    fees = [p for p in replay.ledger.journal.postings if p.kind is PostingKind.FEE]

    assert [(f.value_day, f.booked_day) for f in fees] == [(2, 5), (4, 5), (5, 5)]
    assert all(f.customer_leg.amount == _aed("-25.00") for f in fees)


def test_criterion_3_settle_lower_releases_full_hold() -> None:
    """Accept. E5 posts 185.00, Auth-A is settled, and the full 200.00 hold is
    released."""
    replay = replay_stream()
    ledger = replay.ledger

    e5 = next(p for p in ledger.journal.postings if p.posting_id == "E5")
    settled = [c for c in ledger.holds.changes if c.kind is HoldChangeKind.SETTLED]

    assert e5.customer_leg.amount == _aed("-185.00")
    assert ledger.auth_state("Auth-A") is AuthState.SETTLED
    assert [(c.auth_id, c.amount) for c in settled] == [("Auth-A", _aed("200.00"))]
    assert ledger.holds.active_total("ACC-001", AED) == _aed("0.00")


def test_criterion_4_unmatched_settlement_posts() -> None:
    """Refuse. A settlement with no authorization is posted, flagged unmatched, and a
    dispute is opened (D4). The issuer must pay the acquirer."""
    replay = replay_stream()

    e6 = _outcome(replay, "E6")
    posting = next(p for p in replay.ledger.journal.postings if p.posting_id == "E6")

    assert e6.status is Status.POSTED
    assert e6.flags == frozenset({"unmatched"})
    assert any("dispute 11.3" in alert for alert in e6.alerts)
    assert posting.customer_leg.amount == _aed("-180.00")
    assert replay.ledger.auth_state("Auth-Z") is AuthState.UNMATCHED


def test_criterion_5_approved_hold_reduces_available_only() -> None:
    """Accept as a rule (D15). In the stream the premise is false: Auth-B is declined.
    The stream without E7 approves it: ledger 285.00, available 195.00."""
    assert _outcome(replay_stream(), "E8").status is Status.DECLINED

    replay = _without("E7")
    e8 = _outcome(replay, "E8")

    assert e8.status is Status.APPROVED
    assert e8.ledger == _aed("285.00")
    assert e8.available_after == _aed("195.00")
    assert replay.ledger.available("ACC-001") == _aed("195.80")
    assert replay.ledger.journal.balance(replay.ledger.journal.account("ACC-001")) == _aed("285.80")


def test_criterion_6_reversal_restates_money_not_decisions() -> None:
    """Refuse, for the word "all". The money returns: restated closes equal the stream
    without E7 and E9, and the fee income nets to 0. The as-known Day 5 close, the
    Auth-B decline and the journal records do not return."""
    replay = replay_stream()
    clean = _without("E7", "E9")
    journal = replay.ledger.journal

    for day in range(1, 7):
        for account in ("ACC-001", "ACC-002"):
            assert replay.restated(account, day) == clean.restated(account, day)
    fee_income = AccountRef.internal_for(InternalAccount.FEE_INCOME, AED)
    assert journal.balance(fee_income) == _aed("0.00")

    assert replay.as_known("ACC-001", 5) == _aed("-410.00")
    assert clean.as_known("ACC-001", 5) == _aed("285.00")
    assert _outcome(replay, "E8").status is Status.DECLINED
    assert _outcome(clean, "E8").status is Status.APPROVED
    ids = [p.posting_id for p in journal.postings]
    assert {"E7", "E9"} <= set(ids)
    assert sum(1 for p in journal.postings if p.kind is PostingKind.FEE) == 3
    assert sum(1 for p in journal.postings if p.kind is PostingKind.FEE_REFUND) == 3


def test_criterion_7_instalments_sum_to_the_amount() -> None:
    """Refuse. 10.000 BHD in three is 3.334 + 3.333 + 3.333. Three of 3.334 make
    10.002, which is not the credit."""
    replay = replay_stream()
    parts = [p.customer_leg.amount for p in replay.ledger.journal.postings if p.cause == "E10"]

    assert parts == list(split(Money.of("10.000", BHD), 3))
    assert [str(p.amount) for p in parts] == ["3.334", "3.333", "3.333"]
    assert sum((p.amount for p in parts), Decimal(0)) == Decimal("10.000")
    assert 3 * Decimal("3.334") == Decimal("10.002")


def test_criterion_8_remainder_is_carried() -> None:
    """Refuse. The rule needs the daily accruals to sum exactly to the credit, so the
    remainder is carried, not discarded: 0.802 exact, 0.80 credited, 0.002 kept."""
    replay = replay_stream()

    cap = next(c for c in replay.report(6).close.interest if c.account == "ACC-001")

    assert cap.exact == Decimal("0.802")
    assert cap.total == _aed("0.80")
    assert sum((a.rounded for a in cap.accruals), Money.zero(AED)) == cap.total
    assert cap.carry_out == Decimal("0.002")
    assert replay.ledger.interest_carry["ACC-001"] == Decimal("0.002")
