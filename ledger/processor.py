from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from ledger.config import DEFAULT_CONFIG, LedgerConfig
from ledger.errors import LedgerError, RejectedEvent, UnknownAccountError
from ledger.events import Authorization, Credit, Debit, Event, Reversal, Settlement
from ledger.holds import HoldBook, HoldChange, HoldChangeKind
from ledger.journal import AccountRef, InternalAccount, Journal, Leg, Posting, PostingKind
from ledger.money import Currency, Money, split

if TYPE_CHECKING:
    from ledger.interest import Capitalization


class Status(StrEnum):
    POSTED = "posted"
    APPROVED = "approved"
    DECLINED = "declined"
    REJECTED = "rejected"


class AuthState(StrEnum):
    ACTIVE = "active"
    DECLINED = "declined"
    SETTLED = "settled"
    EXPIRED = "expired"
    UNMATCHED = "unmatched"


@dataclass(frozen=True)
class Outcome:
    event_id: str
    status: Status
    reason: str | None = None
    posting_ids: tuple[str, ...] = ()
    flags: frozenset[str] = field(default_factory=frozenset)
    alerts: tuple[str, ...] = ()
    ledger: Money | None = None
    available_after: Money | None = None


_ALERTS = {
    "unmatched": "settlement with no approved authorization: posted, open dispute 11.3",
    "after_expiry": "settlement after its hold expired: posted",
    "after_settlement": "second settlement for one authorization: posted",
    "over_hold": "settlement higher than its hold: posted",
    "value_day_differs": "reversal value day differs from the target's",
}


# Posting ids that the day close makes; an event must not use them.
RESERVED_ID_PREFIXES = ("FEE/", "REFUND/", "INTEREST/")


@dataclass(frozen=True)
class _Plan:
    postings: tuple[Posting, ...] = ()
    holds: tuple[HoldChange, ...] = ()
    status: Status = Status.POSTED
    flags: frozenset[str] = frozenset()
    ledger: Money | None = None
    available_after: Money | None = None


class Ledger:
    """Applies events. Each handler builds all its records first, then appends them."""

    def __init__(self, config: LedgerConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.journal = Journal()
        self.holds = HoldBook()
        self._events: list[Event] = []
        self._outcomes: list[Outcome] = []
        self._first: dict[str, tuple[Event, Outcome]] = {}
        self._auth_events: dict[str, Authorization] = {}
        self._reversed: set[str] = set()
        # Accrual state: never a ledger amount.
        self.interest_carry: dict[str, Decimal] = {}
        self.capitalizations: dict[tuple[str, int], Capitalization] = {}

    @property
    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    @property
    def outcomes(self) -> tuple[Outcome, ...]:
        return tuple(self._outcomes)

    def open_account(self, code: str, currency: Currency) -> AccountRef:
        return self.journal.open_account(code, currency)

    def customer_accounts(self) -> tuple[AccountRef, ...]:
        return self.journal.accounts

    def apply(self, event: Event) -> Outcome:
        seen = self._first.get(event.event_id)
        if seen is not None and seen[0] == event:
            return seen[1]
        try:
            if seen is not None:
                raise RejectedEvent("event_id_reused", event.event_id)
            plan = self._plan(event)
        except RejectedEvent as rejected:
            outcome = Outcome(event.event_id, Status.REJECTED, reason=rejected.code)
        except LedgerError as error:
            outcome = Outcome(event.event_id, Status.REJECTED, reason=type(error).__name__)
        else:
            for posting in plan.postings:
                self.journal.append(posting)
            for change in plan.holds:
                self.holds.append(change)
            if isinstance(event, Reversal):
                self._reversed.add(event.target_event_id)
            if isinstance(event, Authorization):
                self._auth_events[event.auth_id] = event
            outcome = Outcome(
                event.event_id,
                plan.status,
                posting_ids=tuple(p.posting_id for p in plan.postings),
                flags=plan.flags,
                alerts=tuple(_ALERTS[flag] for flag in sorted(plan.flags)),
                ledger=plan.ledger,
                available_after=plan.available_after,
            )
        self._events.append(event)
        self._outcomes.append(outcome)
        if seen is None:
            self._first[event.event_id] = (event, outcome)
        return outcome

    def available(self, account: str) -> Money:
        ref = self.journal.account(account)
        return self.journal.balance(ref) - self.holds.active_total(account, ref.currency)

    def auth_state(self, auth_id: str) -> AuthState | None:
        auth = self._auth_events.get(auth_id)
        if auth is not None:
            outcome = self._first[auth.event_id][1]
            if outcome.status is Status.DECLINED:
                return AuthState.DECLINED
            kind = self.holds.state(auth_id)
            return {
                HoldChangeKind.PLACED: AuthState.ACTIVE,
                HoldChangeKind.SETTLED: AuthState.SETTLED,
                HoldChangeKind.EXPIRED: AuthState.EXPIRED,
            }[kind]
        if any(
            isinstance(e, Settlement) and e.auth_id == auth_id and o.status is Status.POSTED
            for e, o in self._first.values()
        ):
            return AuthState.UNMATCHED
        return None

    def auth_ids(self) -> tuple[str, ...]:
        """Every auth id seen, in arrival order: authorizations, and settlements with
        no authorization."""
        ids = (
            e.auth_id
            for e, o in self._first.values()
            if isinstance(e, Authorization | Settlement) and o.status is not Status.REJECTED
        )
        return tuple(dict.fromkeys(ids))

    def expire_holds(self, day: int) -> tuple[HoldChange, ...]:
        return self.holds.expire(day, self.config.hold_expiry_days)

    def is_repeat(self, event: Event) -> bool:
        seen = self._first.get(event.event_id)
        return seen is not None and seen[0] == event

    def precheck(self, event: Event) -> str | None:
        """The reject code of a check that does not depend on ledger state, or None."""
        try:
            self._static(event)
        except RejectedEvent as rejected:
            return rejected.code
        return None

    def _static(self, event: Event) -> AccountRef:
        if event.event_id.startswith(RESERVED_ID_PREFIXES):
            raise RejectedEvent("reserved_event_id", event.event_id)
        for name in ("booked_day", "value_day"):
            day = getattr(event, name)
            if isinstance(day, bool) or not isinstance(day, int) or day < 1:
                raise RejectedEvent("invalid_day", f"{name}={day!r}")
        try:
            account = self.journal.account(event.account)
        except UnknownAccountError:
            raise RejectedEvent("unknown_account", event.account) from None
        if not isinstance(event, Reversal):
            if event.amount.currency != account.currency:
                raise RejectedEvent("currency_mismatch", str(event.amount))
            if event.amount.amount <= 0:
                raise RejectedEvent("non_positive_amount", str(event.amount))
        return account

    def _plan(self, event: Event) -> _Plan:
        account = self._static(event)
        if isinstance(event, Reversal):
            plan = self._reversal(event, account)
        else:
            if isinstance(event, Credit):
                plan = self._credit(event, account)
            elif isinstance(event, Debit):
                plan = _Plan(postings=(self._posting(event, account, PostingKind.DEBIT),))
            elif isinstance(event, Authorization):
                plan = self._authorization(event, account)
            else:
                plan = self._settlement(event, account)
        for posting in plan.postings:
            if self.journal.has_posting(posting.posting_id):
                raise RejectedEvent("posting_id_collision", posting.posting_id)
        return plan

    def _posting(
        self,
        event: Credit | Debit | Settlement,
        account: AccountRef,
        kind: PostingKind,
        amount: Money | None = None,
        posting_id: str | None = None,
        flags: frozenset[str] = frozenset(),
    ) -> Posting:
        money = event.amount if amount is None else amount
        internal = (
            InternalAccount.CARD_SETTLEMENT
            if kind is PostingKind.SETTLEMENT
            else (InternalAccount.EXTERNAL)
        )
        customer = money if kind is PostingKind.CREDIT else -money
        return Posting(
            posting_id=posting_id or event.event_id,
            kind=kind,
            value_day=event.value_day,
            booked_day=event.booked_day,
            legs=(
                Leg(account, customer),
                Leg(AccountRef.internal_for(internal, account.currency), -customer),
            ),
            cause=event.event_id,
            flags=flags,
        )

    def _credit(self, event: Credit, account: AccountRef) -> _Plan:
        n = event.instalments
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise RejectedEvent("invalid_instalments", repr(n))
        if n == 1:
            return _Plan(postings=(self._posting(event, account, PostingKind.CREDIT),))
        parts = split(event.amount, n)
        if any(part.is_zero() for part in parts):
            raise RejectedEvent("instalment_below_minor_unit", f"{event.amount} in {n}")
        return _Plan(
            postings=tuple(
                self._posting(event, account, PostingKind.CREDIT, part, f"{event.event_id}-{i}")
                for i, part in enumerate(parts, start=1)
            )
        )

    def _authorization(self, event: Authorization, account: AccountRef) -> _Plan:
        if event.auth_id in self._auth_events or self.auth_state(event.auth_id) is not None:
            raise RejectedEvent("auth_id_reused", event.auth_id)
        ledger = self.journal.balance(account)
        after = self.available(account.code) - event.amount
        if after.is_negative():
            return _Plan(status=Status.DECLINED, ledger=ledger, available_after=after)
        hold = HoldChange(
            event.auth_id,
            account.code,
            event.amount,
            HoldChangeKind.PLACED,
            event.booked_day,
            event.event_id,
        )
        return _Plan(holds=(hold,), status=Status.APPROVED, ledger=ledger, available_after=after)

    def _settlement(self, event: Settlement, account: AccountRef) -> _Plan:
        known = self._auth_events.get(event.auth_id)
        if known is not None and known.account != account.code:
            raise RejectedEvent("auth_on_other_account", event.auth_id)
        state = self.auth_state(event.auth_id)
        flags: set[str] = set()
        holds: tuple[HoldChange, ...] = ()
        if state is AuthState.ACTIVE:
            placed = self.holds.active(account.code)
            hold = next((h for h in placed if h.auth_id == event.auth_id), None)
            if hold is None:
                raise RejectedEvent("auth_on_other_account", event.auth_id)
            if event.amount.amount > hold.amount.amount:
                flags.add("over_hold")
            holds = (
                HoldChange(
                    event.auth_id,
                    account.code,
                    hold.amount,
                    HoldChangeKind.SETTLED,
                    event.booked_day,
                    event.event_id,
                ),
            )
        elif state is AuthState.SETTLED:
            flags.add("after_settlement")
        elif state is AuthState.EXPIRED:
            flags.add("after_expiry")
        else:
            flags.add("unmatched")
        frozen = frozenset(flags)
        posting = self._posting(event, account, PostingKind.SETTLEMENT, flags=frozen)
        return _Plan(postings=(posting,), holds=holds, flags=frozen)

    def _reversal(self, event: Reversal, account: AccountRef) -> _Plan:
        seen = self._first.get(event.target_event_id)
        if seen is None:
            raise RejectedEvent("unknown_target", event.target_event_id)
        target, outcome = seen
        if isinstance(target, Reversal):
            raise RejectedEvent("target_is_reversal", target.event_id)
        if isinstance(target, Authorization):
            raise RejectedEvent("target_is_authorization", target.event_id)
        if outcome.status is Status.REJECTED:
            raise RejectedEvent("target_rejected", target.event_id)
        if target.event_id in self._reversed:
            raise RejectedEvent("already_reversed", target.event_id)
        if event.booked_day < target.booked_day:
            raise RejectedEvent("reversal_before_target", target.event_id)
        if target.account != account.code:
            raise RejectedEvent("target_on_other_account", target.event_id)
        originals = [p for p in self.journal.postings if p.posting_id in outcome.posting_ids]
        flags: set[str] = set()
        postings = []
        for index, original in enumerate(originals, start=1):
            posting_id = event.event_id if len(originals) == 1 else f"{event.event_id}-{index}"
            own = (
                frozenset({"value_day_differs"})
                if (original.value_day != event.value_day)
                else frozenset()
            )
            flags |= own
            postings.append(
                Posting(
                    posting_id=posting_id,
                    kind=PostingKind.REVERSAL,
                    value_day=event.value_day,
                    booked_day=event.booked_day,
                    legs=tuple(Leg(leg.account, -leg.amount) for leg in original.legs),
                    cause=event.event_id,
                    links=(original.posting_id,),
                    flags=own,
                )
            )
        return _Plan(postings=tuple(postings), flags=frozenset(flags))
