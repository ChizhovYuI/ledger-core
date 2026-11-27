import dataclasses
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledger.errors import (
    CurrencyMismatchError,
    DuplicatePostingError,
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
    fee_aed = AccountRef.internal_for(InternalAccount.FEE_INCOME, AED)
    fee_bhd = AccountRef.internal_for(InternalAccount.FEE_INCOME, BHD)
    journal.append(_credit(fee_aed, "25", value_day=1))
    journal.append(_credit(fee_bhd, "1", value_day=1))

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


_CUSTOMER_CODES = {AED: ("a1", "a2"), BHD: ("b1", "b2")}
_POOL_SIZE = len(_CUSTOMER_CODES[AED]) + len(InternalAccount)

_nonzero_minor = st.integers(-(10**9), 10**9).filter(bool)
_posting_shapes = st.tuples(
    st.sampled_from([AED, BHD]),
    st.lists(st.integers(0, _POOL_SIZE - 1), min_size=2, max_size=_POOL_SIZE, unique=True),
    st.lists(_nonzero_minor, min_size=_POOL_SIZE - 1, max_size=_POOL_SIZE - 1),
)


def _account_pool(journal: Journal, currency: Currency) -> list[AccountRef]:
    customers = [journal.account(code) for code in _CUSTOMER_CODES[currency]]
    internals = [AccountRef.internal_for(kind, currency) for kind in InternalAccount]
    return customers + internals


def _balanced_legs(
    pool: list[AccountRef], currency: Currency, indexes: list[int], minors: list[int]
) -> tuple[Leg, ...]:
    *open_indexes, closing_index = indexes
    minors = minors[: len(open_indexes)]
    if sum(minors) == 0:
        minors[0] *= 2
    legs = [
        Leg(pool[index], Money(Decimal(minor).scaleb(-currency.scale), currency))
        for index, minor in zip(open_indexes, minors, strict=True)
    ]
    total = sum((leg.amount for leg in legs), start=Money.zero(currency))
    return (*legs, Leg(pool[closing_index], -total))


@given(st.lists(_posting_shapes, max_size=20))
def test_zero_sum_property(shapes: list[tuple[Currency, list[int], list[int]]]) -> None:
    journal = Journal()
    for currency, codes in _CUSTOMER_CODES.items():
        for code in codes:
            journal.open_account(code, currency)
    for number, (currency, indexes, minors) in enumerate(shapes):
        legs = _balanced_legs(_account_pool(journal, currency), currency, indexes, minors)
        journal.append(
            Posting(
                posting_id=f"p{number}",
                kind=PostingKind.DEBIT,
                value_day=1 + number,
                booked_day=1 + number,
                legs=legs,
                cause="property",
            )
        )

    assert all(total.is_zero() for total in journal.totals_by_currency().values())
    journal.assert_balanced()
    for currency in (AED, BHD):
        balances = [journal.balance(account) for account in _account_pool(journal, currency)]
        assert sum(balances, start=Money.zero(currency)).is_zero()
