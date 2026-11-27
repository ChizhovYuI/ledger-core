from __future__ import annotations

from dataclasses import dataclass

from ledger.money import Money


@dataclass(frozen=True)
class _EventBase:
    event_id: str
    account: str
    booked_day: int
    value_day: int


@dataclass(frozen=True)
class Credit(_EventBase):
    amount: Money
    instalments: int = 1


@dataclass(frozen=True)
class Debit(_EventBase):
    amount: Money


@dataclass(frozen=True)
class Authorization(_EventBase):
    auth_id: str
    amount: Money


@dataclass(frozen=True)
class Settlement(_EventBase):
    auth_id: str
    amount: Money


@dataclass(frozen=True)
class Reversal(_EventBase):
    target_event_id: str


Event = Credit | Debit | Authorization | Settlement | Reversal
