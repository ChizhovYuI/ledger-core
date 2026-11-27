from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ledger.holds import HoldChange
from ledger.journal import AccountRef, InternalAccount, Journal, Leg, Posting, PostingKind
from ledger.money import Money
from ledger.processor import Ledger

_FEE_KINDS = frozenset({PostingKind.FEE, PostingKind.FEE_REFUND})


class FeeAction(StrEnum):
    FEE = "fee"
    REFUND = "refund"
    NONE = "none"
    NO_FEE_CONFIGURED = "no_fee_configured"


@dataclass(frozen=True)
class FeeCheck:
    account: str
    day: int
    check: Money
    action: FeeAction
    posting_id: str | None = None


@dataclass(frozen=True)
class DayClose:
    day: int
    position: int
    expired: tuple[HoldChange, ...]
    checks: tuple[FeeCheck, ...]
    alerts: tuple[str, ...]


def close_day(ledger: Ledger, day: int, since_position: int) -> DayClose:
    """Expire holds, then re-run the fee check for each day that the postings
    appended since `since_position` can have changed (D1), oldest day first."""
    if isinstance(day, bool) or not isinstance(day, int) or day < 1:
        raise ValueError(f"day must be a positive int, not {day!r}")
    journal = ledger.journal
    if not 0 <= since_position <= journal.position:
        raise ValueError(f"since_position {since_position} outside 0..{journal.position}")
    expired = ledger.expire_holds(day)
    new = [p for p in journal.postings[since_position:] if p.kind not in _FEE_KINDS]
    checks: list[FeeCheck] = []
    alerts: list[str] = []
    for account in ledger.customer_accounts():
        own = [p for p in new if p.customer_leg.account == account]
        start = min([day, *(p.value_day for p in own)])
        for d in range(start, day + 1):
            links = _unique(p.cause for p in own if p.value_day <= d)
            fee_check = _check_day(ledger, account, d, day, links)
            if fee_check.action is FeeAction.NO_FEE_CONFIGURED:
                alerts.append(
                    f"no_fee_configured: {account.code} day {d} closes at {fee_check.check}"
                )
            checks.append(fee_check)
    return DayClose(day, journal.position, expired, tuple(checks), tuple(alerts))


def _check_day(
    ledger: Ledger, account: AccountRef, d: int, closing_day: int, links: tuple[str, ...]
) -> FeeCheck:
    journal = ledger.journal
    own_day = [
        p
        for p in journal.postings
        if p.kind in _FEE_KINDS and p.value_day == d and p.customer_leg.account == account
    ]
    # D2b: a fee counts in later days, not in the check of its own day.
    check = journal.balance(account, value_day_upto=d)
    for posting in own_day:
        check -= posting.customer_leg.amount
    fee = ledger.config.fee_for(account.currency)
    fees = [p for p in own_day if p.kind is PostingKind.FEE]
    refunded = {p.links[0] for p in journal.postings if p.kind is PostingKind.FEE_REFUND}
    open_fees = [p for p in fees if p.posting_id not in refunded]
    want = check.is_negative()
    if want and fee is None:
        return FeeCheck(account.code, d, check, FeeAction.NO_FEE_CONFIGURED)
    if want and fee is not None and not open_fees:
        posting_id = f"FEE/{account.code}/D{d}/{len(fees) + 1}"
        _post(journal, posting_id, PostingKind.FEE, account, -fee, d, closing_day, links)
        return FeeCheck(account.code, d, check, FeeAction.FEE, posting_id)
    if not want and open_fees:
        target = open_fees[0]
        posting_id = f"REFUND/{target.posting_id}"
        amount = -target.customer_leg.amount
        refund_links = (target.posting_id, *links)
        _post(
            journal,
            posting_id,
            PostingKind.FEE_REFUND,
            account,
            amount,
            d,
            closing_day,
            refund_links,
        )
        return FeeCheck(account.code, d, check, FeeAction.REFUND, posting_id)
    return FeeCheck(account.code, d, check, FeeAction.NONE)


def _post(
    journal: Journal,
    posting_id: str,
    kind: PostingKind,
    account: AccountRef,
    customer: Money,
    value_day: int,
    booked_day: int,
    links: tuple[str, ...],
) -> None:
    income = AccountRef.internal_for(InternalAccount.FEE_INCOME, account.currency)
    journal.append(
        Posting(
            posting_id=posting_id,
            kind=kind,
            value_day=value_day,
            booked_day=booked_day,
            legs=(Leg(account, customer), Leg(income, -customer)),
            cause=f"close-D{booked_day}",
            links=links,
        )
    )


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))
