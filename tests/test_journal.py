import dataclasses
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledger.errors import (
    CurrencyMismatchError,
    DuplicatePostingError,
    PostingShapeError,
    UnbalancedPostingError,
    UnknownAccountError,
    UnknownCurrencyError,
)
from ledger.journal import AccountRef, InternalAccount, Journal, Leg, Posting, PostingKind
from ledger.money import AED, BHD, Currency, Money

_counter = iter(range(10**9))


def _external(currency: Currency) -> AccountRef:
    return AccountRef.internal_for(InternalAccount.EXTERNAL, currency)


def _credit(
    account: AccountRef,
    amount: str,
    value_day: int,
    booked_day: int | None = None,
    posting_id: str | None = None,
) -> Posting:
    money = Money.of(amount, account.currency)
    return Posting(
        posting_id=posting_id or f"p{next(_counter)}",
        kind=PostingKind.CREDIT,
        value_day=value_day,
        booked_day=value_day if booked_day is None else booked_day,
        legs=(Leg(account, money), Leg(_external(account.currency), -money)),
        cause="test",
    )


def _fee(customer: AccountRef, fee: AccountRef, amount: str) -> Posting:
    money = Money.of(amount, customer.currency)
    return _posting(PostingKind.DEBIT, (Leg(customer, -money), Leg(fee, money)))


def _posting(kind: PostingKind, legs: tuple[Leg, ...]) -> Posting:
    return Posting(
        posting_id=f"p{next(_counter)}",
        kind=kind,
        value_day=1,
        booked_day=1,
        legs=legs,
        cause="test",
    )


def test_unbalanced_posting_rejected() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)

    with pytest.raises(UnbalancedPostingError):
        Posting(
            posting_id="p1",
            kind=PostingKind.CREDIT,
            value_day=1,
            booked_day=1,
            legs=(Leg(customer, Money.of("10", AED)), Leg(_external(AED), Money.of("-9", AED))),
            cause="test",
        )


def test_balance_value_axis() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    journal.append(_credit(customer, "10", value_day=1))
    journal.append(_credit(customer, "20", value_day=2))
    journal.append(_credit(customer, "40", value_day=5))

    assert journal.balance(customer, value_day_upto=2) == Money.of("30", AED)
    assert journal.balance(customer) == Money.of("70", AED)


def test_balance_known_axis() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    journal.append(_credit(customer, "10", value_day=1))
    journal.append(_credit(customer, "20", value_day=3))
    journal.append(_credit(customer, "5", value_day=2))

    assert journal.balance(customer, value_day_upto=2, known_at=2) == Money.of("10", AED)
    assert journal.balance(customer, value_day_upto=2, known_at=3) == Money.of("15", AED)


def test_balance_both_axes_e10_shape() -> None:
    journal = Journal()
    customer = journal.open_account("c1", BHD)
    journal.append(_credit(customer, "7", value_day=6))
    position_before = journal.position
    journal.append(_credit(customer, "3", value_day=5, booked_day=5))

    as_known = journal.balance(customer, value_day_upto=5, known_at=position_before)
    restated = journal.balance(customer, value_day_upto=5)

    assert str(as_known.amount) == "0.000"
    assert restated == Money.of("3", BHD)


def test_records_cannot_change() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    posting = _credit(customer, "10", value_day=1)
    journal.append(posting)

    with pytest.raises(dataclasses.FrozenInstanceError):
        posting.value_day = 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        posting.legs[0].amount = Money.of("1", AED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        posting.legs[0].amount.amount = 1
    assert isinstance(journal.postings, tuple)
    for name in ("delete", "remove", "update", "__setitem__", "__delitem__"):
        assert not hasattr(journal, name)


def test_duplicate_posting_id_rejected() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    journal.append(_credit(customer, "10", value_day=1, posting_id="p1"))

    with pytest.raises(DuplicatePostingError):
        journal.append(_credit(customer, "5", value_day=1, posting_id="p1"))


def test_internal_account_per_currency() -> None:
    journal = Journal()
    customer_aed = journal.open_account("c1", AED)
    customer_bhd = journal.open_account("c2", BHD)
    fee_aed = AccountRef.internal_for(InternalAccount.FEE_INCOME, AED)
    fee_bhd = AccountRef.internal_for(InternalAccount.FEE_INCOME, BHD)
    journal.append(_fee(customer_aed, fee_aed, "25"))
    journal.append(_fee(customer_bhd, fee_bhd, "1"))

    assert fee_aed != fee_bhd
    assert journal.balance(fee_aed) == Money.of("25", AED)
    assert journal.balance(fee_bhd) == Money.of("1", BHD)


def test_unknown_customer_account_rejected() -> None:
    journal = Journal()
    stranger = AccountRef("ghost", AED)

    with pytest.raises(UnknownAccountError):
        journal.append(_credit(stranger, "10", value_day=1))
    assert journal.position == 0


def test_leg_currency_must_match_account() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)

    with pytest.raises(CurrencyMismatchError):
        Leg(customer, Money.of("1", BHD))


@pytest.mark.parametrize("known_at", [-1, 2])
def test_known_at_out_of_range(known_at: int) -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    journal.append(_credit(customer, "10", value_day=1))

    with pytest.raises(ValueError):
        journal.balance(customer, known_at=known_at)


def test_zero_amount_leg_rejected() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    zero = Money.zero(AED)

    with pytest.raises(ValueError):
        Posting(
            posting_id="p1",
            kind=PostingKind.CREDIT,
            value_day=1,
            booked_day=1,
            legs=(Leg(customer, zero), Leg(_external(AED), zero)),
            cause="test",
        )


def test_same_account_in_two_legs_rejected() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    ten = Money.of("10", AED)

    with pytest.raises(ValueError):
        Posting(
            posting_id="p1",
            kind=PostingKind.CREDIT,
            value_day=1,
            booked_day=1,
            legs=(Leg(customer, ten), Leg(customer, -ten)),
            cause="test",
        )


def test_balance_of_unknown_account_rejected() -> None:
    journal = Journal()
    journal.open_account("ACC-001", AED)

    with pytest.raises(UnknownAccountError):
        journal.balance(AccountRef("ACC-001", BHD))
    with pytest.raises(UnknownAccountError):
        journal.balance(AccountRef("ghost", AED))


def test_account_currency_must_be_registered() -> None:
    with pytest.raises(UnknownCurrencyError):
        AccountRef("c1", Currency("USD", 2))
    with pytest.raises(CurrencyMismatchError):
        AccountRef("c1", Currency("AED", 3))


def test_unknown_account_error_message() -> None:
    assert str(UnknownAccountError("x")) == "x"


def _ten() -> Money:
    return Money.of("10", AED)


@pytest.mark.parametrize(
    ("kind", "customer_sign"),
    [
        (PostingKind.CREDIT, -1),
        (PostingKind.DEBIT, 1),
        (PostingKind.SETTLEMENT, 1),
        (PostingKind.FEE, 1),
        (PostingKind.FEE_REFUND, -1),
    ],
)
def test_kind_sign_rejected(kind: PostingKind, customer_sign: int) -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    amount = _ten() if customer_sign > 0 else -_ten()

    with pytest.raises(PostingShapeError):
        _posting(kind, (Leg(customer, amount), Leg(_external(AED), -amount)))


@pytest.mark.parametrize(
    ("kind", "customer_sign"),
    [(PostingKind.FEE, -1), (PostingKind.FEE_REFUND, 1)],
)
def test_fee_kind_sign_accepted(kind: PostingKind, customer_sign: int) -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    fee = AccountRef.internal_for(InternalAccount.FEE_INCOME, AED)
    amount = _ten() if customer_sign > 0 else -_ten()

    journal.append(_posting(kind, (Leg(customer, amount), Leg(fee, -amount))))

    assert journal.balance(customer) == amount
    assert journal.balance(fee) == -amount


def test_shape_two_customer_legs_rejected() -> None:
    journal = Journal()
    first = journal.open_account("c1", AED)
    second = journal.open_account("c2", AED)

    with pytest.raises(PostingShapeError):
        _posting(PostingKind.CREDIT, (Leg(first, _ten()), Leg(second, -_ten())))


def test_shape_two_internal_legs_rejected() -> None:
    fee = AccountRef.internal_for(InternalAccount.FEE_INCOME, AED)

    with pytest.raises(PostingShapeError):
        _posting(PostingKind.CREDIT, (Leg(fee, _ten()), Leg(_external(AED), -_ten())))


def test_shape_three_legs_rejected() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)
    fee = AccountRef.internal_for(InternalAccount.FEE_INCOME, AED)
    five = Money.of("5", AED)

    with pytest.raises(PostingShapeError):
        _posting(
            PostingKind.CREDIT,
            (Leg(customer, _ten()), Leg(_external(AED), -five), Leg(fee, -five)),
        )


def test_unknown_kind_rejected() -> None:
    journal = Journal()
    customer = journal.open_account("c1", AED)

    with pytest.raises(PostingShapeError):
        _posting("penalty", (Leg(customer, -_ten()), Leg(_external(AED), _ten())))


_CUSTOMER_CODES = {AED: ("a1", "a2"), BHD: ("b1", "b2")}

_nonzero_minor = st.integers(-(10**9), 10**9).filter(bool)
_posting_shapes = st.tuples(
    st.sampled_from([AED, BHD]),
    st.integers(0, len(_CUSTOMER_CODES[AED]) - 1),
    st.sampled_from(list(InternalAccount)),
    _nonzero_minor,
)


def _account_pool(journal: Journal, currency: Currency) -> list[AccountRef]:
    customers = [journal.account(code) for code in _CUSTOMER_CODES[currency]]
    internals = [AccountRef.internal_for(kind, currency) for kind in InternalAccount]
    return customers + internals


@given(st.lists(_posting_shapes, max_size=20))
def test_zero_sum_property(
    shapes: list[tuple[Currency, int, InternalAccount, int]],
) -> None:
    journal = Journal()
    for currency, codes in _CUSTOMER_CODES.items():
        for code in codes:
            journal.open_account(code, currency)
    for number, (currency, customer_index, internal, minor) in enumerate(shapes):
        customer = journal.account(_CUSTOMER_CODES[currency][customer_index])
        amount = Money(Decimal(minor).scaleb(-currency.scale), currency)
        journal.append(
            Posting(
                posting_id=f"p{number}",
                kind=PostingKind.CREDIT if minor > 0 else PostingKind.DEBIT,
                value_day=1 + number,
                booked_day=1 + number,
                legs=(
                    Leg(customer, amount),
                    Leg(AccountRef.internal_for(internal, currency), -amount),
                ),
                cause="property",
            )
        )

    assert all(total.is_zero() for total in journal.totals_by_currency().values())
    journal.assert_balanced()
    for currency in (AED, BHD):
        balances = [journal.balance(account) for account in _account_pool(journal, currency)]
        assert sum(balances, start=Money.zero(currency)).is_zero()
