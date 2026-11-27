import pytest

from ledger.events import Authorization, Credit, Debit, Event, Reversal, Settlement
from ledger.holds import HoldChange
from ledger.journal import AccountRef, InternalAccount, Posting, PostingKind
from ledger.money import AED, BHD, Money
from ledger.processor import AuthState, Ledger, Outcome, Status
from ledger.stream import STREAM, open_accounts


def _aed(value: str) -> Money:
    return Money.of(value, AED)


def _upto(event_id: str) -> tuple[Ledger, Outcome]:
    ledger = Ledger()
    open_accounts(ledger)
    for event in STREAM:
        outcome = ledger.apply(event)
        if event.event_id == event_id:
            return ledger, outcome
    raise AssertionError(f"{event_id} is not in the stream")


def _balance(ledger: Ledger, code: str, value_day_upto: int | None = None) -> Money:
    return ledger.journal.balance(ledger.journal.account(code), value_day_upto=value_day_upto)


def _internal(ledger: Ledger, kind: InternalAccount, code: str) -> Money:
    currency = ledger.journal.account(code).currency
    return ledger.journal.balance(AccountRef.internal_for(kind, currency))


def _posting(ledger: Ledger, posting_id: str) -> Posting:
    return next(p for p in ledger.journal.postings if p.posting_id == posting_id)


def _funded() -> Ledger:
    ledger = Ledger()
    ledger.open_account("ACC-001", AED)
    ledger.apply(Credit("C0", "ACC-001", booked_day=1, value_day=1, amount=_aed("1000.00")))
    return ledger


def _snapshot(ledger: Ledger) -> tuple[tuple[Posting, ...], tuple[HoldChange, ...]]:
    return ledger.journal.postings, ledger.holds.changes


def test_e1_e2() -> None:
    ledger, outcome = _upto("E2")

    assert outcome.status is Status.POSTED
    assert _balance(ledger, "ACC-001") == _aed("250.00")


def test_e3_auth_a_approved() -> None:
    ledger, outcome = _upto("E3")

    assert outcome.status is Status.APPROVED
    assert _balance(ledger, "ACC-001") == _aed("250.00")
    assert ledger.available("ACC-001") == _aed("50.00")
    assert ledger.auth_state("Auth-A") is AuthState.ACTIVE


def test_e4() -> None:
    ledger, _ = _upto("E4")

    assert _balance(ledger, "ACC-001") == _aed("650.00")


def test_e5_settles_less_releases_full_hold() -> None:
    ledger, outcome = _upto("E5")

    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset()
    posting = _posting(ledger, "E5")
    assert posting.kind is PostingKind.SETTLEMENT
    assert posting.customer_leg.amount == _aed("-185.00")
    assert ledger.holds.active("ACC-001") == ()
    assert ledger.available("ACC-001") == _balance(ledger, "ACC-001")
    assert ledger.auth_state("Auth-A") is AuthState.SETTLED


def test_e6_unmatched_posts_flagged() -> None:
    ledger, outcome = _upto("E6")

    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset({"unmatched"})
    assert len(outcome.alerts) == 1
    assert "dispute 11.3" in outcome.alerts[0]
    posting = _posting(ledger, "E6")
    assert posting.customer_leg.amount == _aed("-180.00")
    assert posting.flags == frozenset({"unmatched"})
    assert ledger.auth_state("Auth-Z") is AuthState.UNMATCHED
    assert _balance(ledger, "ACC-001") == _aed("285.00")


def test_e7_backdated() -> None:
    ledger, _ = _upto("E7")

    posting = _posting(ledger, "E7")
    assert posting.value_day == 2
    assert posting.booked_day == 5
    assert _balance(ledger, "ACC-001", value_day_upto=2) == _aed("-370.00")


def test_e8_auth_b_declined() -> None:
    ledger, _ = _upto("E7")
    changes = ledger.holds.changes

    outcome = ledger.apply(STREAM[7])

    assert outcome.status is Status.DECLINED
    assert outcome.ledger == _aed("-335.00")
    assert outcome.available_after == _aed("-425.00")
    assert ledger.auth_state("Auth-B") is AuthState.DECLINED
    assert ledger.holds.changes == changes
    assert ledger.holds.state("Auth-B") is None


def test_e9_reversal() -> None:
    ledger, outcome = _upto("E9")

    assert outcome.status is Status.POSTED
    posting = _posting(ledger, "E9")
    assert posting.kind is PostingKind.REVERSAL
    assert posting.customer_leg.amount == _aed("620.00")
    assert posting.value_day == 2
    assert posting.links == ("E7",)
    assert _balance(ledger, "ACC-001") == _aed("285.00")
    assert _balance(ledger, "ACC-001", value_day_upto=2) == _aed("250.00")


def test_e10_instalments() -> None:
    ledger, outcome = _upto("E10")

    assert outcome.posting_ids == ("E10-1", "E10-2", "E10-3")
    postings = [_posting(ledger, posting_id) for posting_id in outcome.posting_ids]
    assert [p.customer_leg.amount for p in postings] == [
        Money.of("3.334", BHD),
        Money.of("3.333", BHD),
        Money.of("3.333", BHD),
    ]
    assert all(p.value_day == 5 and p.booked_day == 5 for p in postings)
    assert _balance(ledger, "ACC-002") == Money.of("10.000", BHD)


def test_stream_end_state() -> None:
    ledger, _ = _upto("E10")

    assert _balance(ledger, "ACC-001") == _aed("285.00")
    assert _internal(ledger, InternalAccount.EXTERNAL, "ACC-001") == _aed("-650.00")
    assert _internal(ledger, InternalAccount.CARD_SETTLEMENT, "ACC-001") == _aed("365.00")
    assert _internal(ledger, InternalAccount.EXTERNAL, "ACC-002") == Money.of("-10.000", BHD)
    ledger.journal.assert_balanced()


def test_same_event_twice_same_outcome() -> None:
    ledger, _ = _upto("E3")
    first = ledger.outcomes
    before = _snapshot(ledger)

    again = [ledger.apply(event) for event in STREAM[:3]]

    assert all(a is b for a, b in zip(again, first, strict=True))
    assert _snapshot(ledger) == before


def test_event_id_reused_with_other_content_rejected() -> None:
    ledger = _funded()
    before = _snapshot(ledger)

    outcome = ledger.apply(Credit("C0", "ACC-001", booked_day=1, value_day=1, amount=_aed("5.00")))

    assert outcome.status is Status.REJECTED
    assert outcome.reason == "event_id_reused"
    assert _snapshot(ledger) == before


def _debit(event_id: str, amount: str = "10.00") -> Debit:
    return Debit(event_id, "ACC-001", booked_day=2, value_day=2, amount=_aed(amount))


def _reversal(event_id: str, target: str, value_day: int = 2) -> Reversal:
    return Reversal(event_id, "ACC-001", booked_day=3, value_day=value_day, target_event_id=target)


def _auth(event_id: str, auth_id: str, amount: str = "10.00", day: int = 1) -> Authorization:
    return Authorization(
        event_id, "ACC-001", booked_day=day, value_day=day, auth_id=auth_id, amount=_aed(amount)
    )


def _settle(event_id: str, auth_id: str, amount: str, day: int = 2) -> Settlement:
    return Settlement(
        event_id, "ACC-001", booked_day=day, value_day=day, auth_id=auth_id, amount=_aed(amount)
    )


_REJECTIONS = pytest.mark.parametrize(
    ("setup", "event", "reason"),
    [
        pytest.param(
            [],
            Debit("X1", "ghost", booked_day=1, value_day=1, amount=_aed("10.00")),
            "unknown_account",
            id="unknown_account",
        ),
        pytest.param(
            [],
            Debit("X1", "ACC-001", booked_day=1, value_day=1, amount=Money.of("1", BHD)),
            "currency_mismatch",
            id="currency_mismatch",
        ),
        pytest.param([], _debit("FEE/ACC-001/D2/1"), "reserved_event_id", id="reserved_fee_id"),
        pytest.param([], _debit("REFUND/X1"), "reserved_event_id", id="reserved_refund_id"),
        pytest.param([], _debit("X1", "0"), "non_positive_amount", id="zero_amount"),
        pytest.param([], _debit("X1", "-5.00"), "non_positive_amount", id="negative_amount"),
        pytest.param([], _reversal("X1", "nope"), "unknown_target", id="unknown_target"),
        pytest.param(
            [_debit("D0", "0")], _reversal("X1", "D0"), "target_rejected", id="target_rejected"
        ),
        pytest.param(
            [_debit("D0"), _reversal("R0", "D0")],
            _reversal("X1", "D0"),
            "already_reversed",
            id="already_reversed",
        ),
        pytest.param(
            [_debit("D0"), _reversal("R0", "D0")],
            _reversal("X1", "R0"),
            "target_is_reversal",
            id="target_is_reversal",
        ),
        pytest.param(
            [_auth("A0", "Auth-1")],
            _reversal("X1", "A0"),
            "target_is_authorization",
            id="target_is_authorization",
        ),
        pytest.param(
            [_auth("A0", "Auth-1")],
            _auth("X1", "Auth-1"),
            "auth_id_reused",
            id="auth_id_reused",
        ),
    ],
)


@_REJECTIONS
def test_rejected_event_changes_nothing(setup: list[Event], event: Event, reason: str) -> None:
    ledger = _funded()
    for prior in setup:
        ledger.apply(prior)
    before = _snapshot(ledger)

    outcome = ledger.apply(event)

    assert outcome.status is Status.REJECTED
    assert outcome.reason == reason
    assert outcome.posting_ids == ()
    assert _snapshot(ledger) == before


def _state(
    ledger: Ledger,
) -> tuple[int, tuple[HoldChange, ...], tuple[Outcome, ...], tuple[Event, ...]]:
    return ledger.journal.position, ledger.holds.changes, ledger.outcomes, ledger.events


@_REJECTIONS
def test_check_matches_apply_rejection(setup: list[Event], event: Event, reason: str) -> None:
    ledger = _funded()
    for prior in setup:
        ledger.apply(prior)
    before = _state(ledger)

    code = ledger.check(event)

    assert code == reason
    assert _state(ledger) == before
    assert ledger.apply(event).reason == code


def test_check_accepted_event_is_none() -> None:
    ledger = _funded()
    before = _state(ledger)

    code = ledger.check(_debit("X1"))

    assert code is None
    assert _state(ledger) == before
    assert ledger.apply(_debit("X1")).status is Status.POSTED


def test_check_repeat_of_rejected_gives_cached_reason() -> None:
    ledger = _funded()
    reversal = _reversal("X1", "D0")
    ledger.apply(reversal)
    ledger.apply(_debit("D0"))
    before = _state(ledger)

    code = ledger.check(reversal)

    assert code == "unknown_target"
    assert _state(ledger) == before


def test_check_repeat_of_accepted_is_none() -> None:
    ledger = _funded()
    ledger.apply(_debit("D0"))
    before = _state(ledger)

    code = ledger.check(_debit("D0"))

    assert code is None
    assert _state(ledger) == before


def test_settlement_over_hold_flagged() -> None:
    ledger = _funded()
    ledger.apply(_auth("A0", "Auth-1", "200.00"))

    outcome = ledger.apply(_settle("S1", "Auth-1", "250.00"))

    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset({"over_hold"})
    assert _posting(ledger, "S1").customer_leg.amount == _aed("-250.00")
    assert ledger.auth_state("Auth-1") is AuthState.SETTLED
    assert ledger.holds.active("ACC-001") == ()


def test_second_settlement_flagged() -> None:
    ledger = _funded()
    ledger.apply(_auth("A0", "Auth-1", "200.00"))
    ledger.apply(_settle("S1", "Auth-1", "200.00"))
    changes = ledger.holds.changes

    outcome = ledger.apply(_settle("S2", "Auth-1", "50.00", day=3))

    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset({"after_settlement"})
    assert _balance(ledger, "ACC-001") == _aed("750.00")
    assert ledger.holds.changes == changes


def test_settlement_on_declined_auth_unmatched() -> None:
    ledger = _funded()
    declined = ledger.apply(_auth("A0", "Auth-1", "2000.00"))

    outcome = ledger.apply(_settle("S1", "Auth-1", "50.00"))

    assert declined.status is Status.DECLINED
    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset({"unmatched"})
    assert ledger.auth_state("Auth-1") is AuthState.DECLINED
    assert _balance(ledger, "ACC-001") == _aed("950.00")


def test_settlement_after_expiry_flagged() -> None:
    ledger = _funded()
    ledger.apply(_auth("A0", "Auth-1", "200.00"))
    ledger.expire_holds(1 + ledger.config.hold_expiry_days)
    changes = ledger.holds.changes

    outcome = ledger.apply(_settle("S1", "Auth-1", "200.00", day=12))

    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset({"after_expiry"})
    assert ledger.auth_state("Auth-1") is AuthState.EXPIRED
    assert ledger.holds.changes == changes
    assert _balance(ledger, "ACC-001") == _aed("800.00")


def test_reversal_value_day_differs_flagged() -> None:
    ledger = _funded()
    ledger.apply(_debit("D0"))

    outcome = ledger.apply(_reversal("R0", "D0", value_day=3))

    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset({"value_day_differs"})
    posting = _posting(ledger, "R0")
    assert posting.flags == frozenset({"value_day_differs"})
    assert posting.value_day == 3
    assert _balance(ledger, "ACC-001") == _aed("1000.00")


def test_instalment_below_minor_unit_rejected() -> None:
    ledger = _funded()
    before = _snapshot(ledger)

    outcome = ledger.apply(
        Credit("C1", "ACC-001", booked_day=2, value_day=2, amount=_aed("0.02"), instalments=3)
    )

    assert outcome.status is Status.REJECTED
    assert outcome.reason == "instalment_below_minor_unit"
    assert _snapshot(ledger) == before
    assert len(ledger.events) == len(ledger.outcomes)


def test_settlement_on_other_account_for_settled_auth_rejected() -> None:
    ledger = _funded()
    ledger.open_account("ACC-003", AED)
    ledger.apply(_auth("A0", "Auth-A", "200.00"))
    ledger.apply(_settle("S1", "Auth-A", "200.00"))
    before = _snapshot(ledger)

    outcome = ledger.apply(
        Settlement(
            "S2", "ACC-003", booked_day=3, value_day=3, auth_id="Auth-A", amount=_aed("50.00")
        )
    )

    assert outcome.status is Status.REJECTED
    assert outcome.reason == "auth_on_other_account"
    assert _snapshot(ledger) == before


def test_auth_id_first_used_by_unmatched_settlement_rejected() -> None:
    ledger = _funded()
    ledger.apply(_settle("S1", "Auth-Z", "50.00", day=1))
    before = _snapshot(ledger)

    outcome = ledger.apply(_auth("A0", "Auth-Z", day=2))

    assert outcome.status is Status.REJECTED
    assert outcome.reason == "auth_id_reused"
    assert ledger.holds.state("Auth-Z") is None
    assert ledger.auth_state("Auth-Z") is AuthState.UNMATCHED
    assert _snapshot(ledger) == before


def _settle_on(
    account: str, event_id: str, auth_id: str, amount: Money, day: int = 2
) -> Settlement:
    return Settlement(
        event_id, account, booked_day=day, value_day=day, auth_id=auth_id, amount=amount
    )


def test_unmatched_settlement_claims_auth_id_for_its_account() -> None:
    ledger = _funded()
    ledger.open_account("ACC-003", AED)
    first = ledger.apply(_settle("S1", "H9", "50.00"))
    second = _settle_on("ACC-003", "S2", "H9", _aed("30.00"), day=3)
    before = _snapshot(ledger)
    balance_before = _balance(ledger, "ACC-003")

    code = ledger.check(second)
    outcome = ledger.apply(second)

    assert first.status is Status.POSTED
    assert first.flags == frozenset({"unmatched"})
    assert code == "auth_on_other_account"
    assert outcome.status is Status.REJECTED
    assert outcome.reason == "auth_on_other_account"
    assert _balance(ledger, "ACC-003") == balance_before
    assert _snapshot(ledger) == before


def test_rejected_settlement_does_not_claim_auth_id() -> None:
    ledger = _funded()
    ledger.open_account("ACC-003", AED)
    first = ledger.apply(_settle_on("ACC-001", "S1", "H9", Money.of("5.000", BHD)))

    outcome = ledger.apply(_settle_on("ACC-003", "S2", "H9", _aed("30.00"), day=3))

    assert first.status is Status.REJECTED
    assert first.reason == "currency_mismatch"
    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset({"unmatched"})
    assert _balance(ledger, "ACC-003") == _aed("-30.00")
    assert ledger.auth_state("H9") is AuthState.UNMATCHED


def test_repeat_unmatched_settlement_on_same_account_posts() -> None:
    ledger = _funded()
    ledger.apply(_settle("S1", "H9", "50.00"))

    outcome = ledger.apply(_settle("S2", "H9", "30.00", day=3))

    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset({"unmatched"})
    assert _posting(ledger, "S2").flags == frozenset({"unmatched"})
    assert _balance(ledger, "ACC-001") == _aed("920.00")
    assert ledger.auth_state("H9") is AuthState.UNMATCHED


def test_reversal_before_target_rejected() -> None:
    ledger = _funded()
    ledger.apply(_debit("D0"))
    before = _snapshot(ledger)

    outcome = ledger.apply(
        Reversal("R0", "ACC-001", booked_day=1, value_day=2, target_event_id="D0")
    )

    assert outcome.status is Status.REJECTED
    assert outcome.reason == "reversal_before_target"
    assert _snapshot(ledger) == before


def test_instalments_far_above_minor_units_rejected_before_split() -> None:
    ledger = _funded()
    before = _snapshot(ledger)

    outcome = ledger.apply(
        Credit("C1", "ACC-001", booked_day=2, value_day=2, amount=_aed("1.00"), instalments=10**9)
    )

    assert outcome.status is Status.REJECTED
    assert outcome.reason == "instalment_below_minor_unit"
    assert _snapshot(ledger) == before


def test_instalments_equal_to_minor_units_posts_one_unit_each() -> None:
    ledger = _funded()

    outcome = ledger.apply(
        Credit("C1", "ACC-001", booked_day=2, value_day=2, amount=_aed("1.00"), instalments=100)
    )

    assert outcome.status is Status.POSTED
    assert len(outcome.posting_ids) == 100
    postings = [_posting(ledger, posting_id) for posting_id in outcome.posting_ids]
    assert all(p.customer_leg.amount == _aed("0.01") for p in postings)
    assert _balance(ledger, "ACC-001") == _aed("1001.00")


def test_instalments_one_above_minor_units_rejected() -> None:
    ledger = _funded()
    before = _snapshot(ledger)

    outcome = ledger.apply(
        Credit("C1", "ACC-001", booked_day=2, value_day=2, amount=_aed("1.00"), instalments=101)
    )

    assert outcome.status is Status.REJECTED
    assert outcome.reason == "instalment_below_minor_unit"
    assert _snapshot(ledger) == before


def test_reversed_unmatched_settlement_releases_auth_id() -> None:
    ledger = _funded()
    ledger.open_account("ACC-003", AED)
    first = ledger.apply(_settle("S1", "H", "50.00"))
    reversal = ledger.apply(_reversal("R1", "S1"))

    outcome = ledger.apply(_settle_on("ACC-003", "S2", "H", _aed("30.00"), day=3))

    assert first.status is Status.POSTED
    assert reversal.status is Status.POSTED
    assert outcome.status is Status.POSTED
    assert outcome.flags == frozenset({"unmatched"})
    assert _balance(ledger, "ACC-003") == _aed("-30.00")


def test_unreversed_settlement_keeps_auth_id_after_other_reversed() -> None:
    ledger = _funded()
    ledger.open_account("ACC-003", AED)
    first = ledger.apply(_settle("S1", "H", "50.00"))
    second = ledger.apply(_settle("S2", "H", "30.00"))
    reversal = ledger.apply(_reversal("R1", "S1"))
    before = _snapshot(ledger)

    outcome = ledger.apply(_settle_on("ACC-003", "S3", "H", _aed("20.00"), day=3))

    assert first.status is Status.POSTED
    assert second.status is Status.POSTED
    assert reversal.status is Status.POSTED
    assert outcome.status is Status.REJECTED
    assert outcome.reason == "auth_on_other_account"
    assert _snapshot(ledger) == before
