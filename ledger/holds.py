from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ledger.money import Currency, Money


class HoldChangeKind(StrEnum):
    PLACED = "placed"
    SETTLED = "settled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class HoldChange:
    auth_id: str
    account: str
    amount: Money
    kind: HoldChangeKind
    day: int
    event_id: str | None


class HoldBook:
    """Append-only log of hold changes. A hold is active while its last change is PLACED."""

    def __init__(self) -> None:
        self._changes: list[HoldChange] = []

    @property
    def changes(self) -> tuple[HoldChange, ...]:
        return tuple(self._changes)

    def append(self, change: HoldChange) -> None:
        self._changes.append(change)

    def _last(self) -> dict[str, HoldChange]:
        last: dict[str, HoldChange] = {}
        for change in self._changes:
            last[change.auth_id] = change
        return last

    def state(self, auth_id: str) -> HoldChangeKind | None:
        change = self._last().get(auth_id)
        return None if change is None else change.kind

    def active(self, account: str | None = None) -> tuple[HoldChange, ...]:
        return tuple(
            change
            for change in self._last().values()
            if change.kind is HoldChangeKind.PLACED
            and (account is None or change.account == account)
        )

    def active_total(self, account: str, currency: Currency) -> Money:
        return sum((h.amount for h in self.active(account)), start=Money.zero(currency))

    def expire(self, day: int, expiry_days: int) -> tuple[HoldChange, ...]:
        expired = tuple(
            HoldChange(h.auth_id, h.account, h.amount, HoldChangeKind.EXPIRED, day, None)
            for h in self.active()
            if h.day + expiry_days <= day
        )
        self._changes.extend(expired)
        return expired
