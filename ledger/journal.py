from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ledger.errors import (
    CurrencyMismatchError,
    DuplicateAccountError,
    DuplicatePostingError,
    PostingShapeError,
    UnbalancedJournalError,
    UnbalancedPostingError,
    UnknownAccountError,
)
from ledger.money import Currency, Money, currency


class InternalAccount(StrEnum):
    EXTERNAL = "external"
    CARD_SETTLEMENT = "card_settlement"
    FEE_INCOME = "fee_income"
    INTEREST_EXPENSE = "interest_expense"


@dataclass(frozen=True)
class AccountRef:
    code: str
    currency: Currency
    internal: bool = False

    def __post_init__(self) -> None:
        if currency(self.currency.code) != self.currency:
            raise CurrencyMismatchError(f"{self.currency} is not the registered currency")
        if self.internal and self.code not in set(InternalAccount):
            raise UnknownAccountError(f"no internal account {self.code!r}")

    @classmethod
    def internal_for(cls, kind: InternalAccount, currency: Currency) -> AccountRef:
        return cls(kind.value, currency, internal=True)

    def __str__(self) -> str:
        return f"{self.code}/{self.currency.code}" if self.internal else self.code


@dataclass(frozen=True)
class Leg:
    account: AccountRef
    amount: Money

    def __post_init__(self) -> None:
        if self.amount.currency != self.account.currency:
            raise CurrencyMismatchError(f"leg on {self.account} is in {self.amount.currency.code}")


class PostingKind(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"
    SETTLEMENT = "settlement"
    REVERSAL = "reversal"


# Sign of the customer leg per kind; None = either sign.
CUSTOMER_SIGN: dict[PostingKind, int | None] = {
    PostingKind.CREDIT: 1,
    PostingKind.DEBIT: -1,
    PostingKind.SETTLEMENT: -1,
    PostingKind.REVERSAL: None,
}


def _is_day(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


@dataclass(frozen=True)
class Posting:
    """An entry: a money movement with a value day and a booked day; legs sum to zero."""

    posting_id: str
    kind: PostingKind
    value_day: int
    booked_day: int
    legs: tuple[Leg, ...]
    cause: str
    links: tuple[str, ...] = ()
    flags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "legs", tuple(self.legs))
        object.__setattr__(self, "links", tuple(self.links))
        object.__setattr__(self, "flags", frozenset(self.flags))
        if not _is_day(self.value_day) or not _is_day(self.booked_day):
            raise ValueError("value_day and booked_day must be positive int")
        if len(self.legs) < 2:
            raise UnbalancedPostingError(f"{self.posting_id}: a posting needs 2 or more legs")
        if any(leg.amount.is_zero() for leg in self.legs):
            raise ValueError(f"{self.posting_id}: a leg must not be zero")
        if len({leg.account for leg in self.legs}) != len(self.legs):
            raise ValueError(f"{self.posting_id}: an account appears in two legs")
        for ccy, total in _sum_by_currency(self.legs).items():
            if not total.is_zero():
                raise UnbalancedPostingError(
                    f"{self.posting_id}: legs sum to {total} in {ccy.code}"
                )
        internal = [leg for leg in self.legs if leg.account.internal]
        if len(self.legs) != 2 or len(internal) != 1:
            raise PostingShapeError(
                f"{self.posting_id}: needs one customer leg and one internal leg"
            )
        if self.kind not in CUSTOMER_SIGN:
            raise PostingShapeError(f"{self.posting_id}: unknown kind {self.kind!r}")
        sign = CUSTOMER_SIGN[self.kind]
        if sign is not None and (self.customer_leg.amount.amount > 0) != (sign > 0):
            raise PostingShapeError(
                f"{self.posting_id}: customer leg sign does not match kind {self.kind}"
            )

    @property
    def customer_leg(self) -> Leg:
        return next(leg for leg in self.legs if not leg.account.internal)


def _sum_by_currency(legs: tuple[Leg, ...] | list[Leg]) -> dict[Currency, Money]:
    totals: dict[Currency, Money] = {}
    for leg in legs:
        ccy = leg.amount.currency
        totals[ccy] = totals.get(ccy, Money.zero(ccy)) + leg.amount
    return totals


class Journal:
    """Append-only list of postings. Balances are computed on each query, never stored."""

    def __init__(self) -> None:
        self._postings: list[Posting] = []
        self._ids: set[str] = set()
        self._accounts: dict[str, AccountRef] = {}

    def open_account(self, code: str, currency: Currency) -> AccountRef:
        if code in self._accounts or code in set(InternalAccount):
            raise DuplicateAccountError(code)
        ref = AccountRef(code, currency)
        self._accounts[code] = ref
        return ref

    def account(self, code: str) -> AccountRef:
        try:
            return self._accounts[code]
        except KeyError:
            raise UnknownAccountError(code) from None

    def append(self, posting: Posting) -> int:
        if posting.posting_id in self._ids:
            raise DuplicatePostingError(posting.posting_id)
        for leg in posting.legs:
            self._check_known(leg.account)
        self._postings.append(posting)
        self._ids.add(posting.posting_id)
        return len(self._postings)

    def _check_known(self, account: AccountRef) -> None:
        if not account.internal and self._accounts.get(account.code) != account:
            raise UnknownAccountError(str(account))

    def has_posting(self, posting_id: str) -> bool:
        return posting_id in self._ids

    @property
    def postings(self) -> tuple[Posting, ...]:
        return tuple(self._postings)

    @property
    def position(self) -> int:
        return len(self._postings)

    def balance(
        self,
        account: AccountRef,
        value_day_upto: int | None = None,
        known_at: int | None = None,
    ) -> Money:
        """Sum of the account's legs valued on or before `value_day_upto`,
        among the first `known_at` postings (a journal position, not a day)."""
        self._check_known(account)
        if known_at is not None and not 0 <= known_at <= len(self._postings):
            raise ValueError(f"known_at {known_at} outside 0..{len(self._postings)}")
        total = Money.zero(account.currency)
        for posting in self._postings[:known_at]:
            if value_day_upto is not None and posting.value_day > value_day_upto:
                continue
            for leg in posting.legs:
                if leg.account == account:
                    total += leg.amount
        return total

    def totals_by_currency(self) -> dict[Currency, Money]:
        totals: dict[Currency, Money] = {}
        for posting in self._postings:
            for ccy, amount in _sum_by_currency(posting.legs).items():
                totals[ccy] = totals.get(ccy, Money.zero(ccy)) + amount
        return totals

    def assert_balanced(self) -> None:
        unbalanced = {
            c.code: str(t) for c, t in self.totals_by_currency().items() if not t.is_zero()
        }
        if unbalanced:
            raise UnbalancedJournalError(f"legs do not sum to zero: {unbalanced}")
