from __future__ import annotations

from ledger.events import Authorization, Credit, Debit, Event, Reversal, Settlement
from ledger.money import AED, BHD, Money
from ledger.processor import Ledger


def _aed(value: str) -> Money:
    return Money.of(value, AED)


STREAM: tuple[Event, ...] = (
    Credit("E1", "ACC-001", booked_day=1, value_day=1, amount=_aed("1200.00")),
    Debit("E2", "ACC-001", booked_day=1, value_day=1, amount=_aed("950.00")),
    Authorization(
        "E3", "ACC-001", booked_day=2, value_day=2, auth_id="Auth-A", amount=_aed("200.00")
    ),
    Credit("E4", "ACC-001", booked_day=3, value_day=3, amount=_aed("400.00")),
    Settlement("E5", "ACC-001", booked_day=4, value_day=4, auth_id="Auth-A", amount=_aed("185.00")),
    Settlement("E6", "ACC-001", booked_day=4, value_day=4, auth_id="Auth-Z", amount=_aed("180.00")),
    Debit("E7", "ACC-001", booked_day=5, value_day=2, amount=_aed("620.00")),
    Authorization(
        "E8", "ACC-001", booked_day=5, value_day=5, auth_id="Auth-B", amount=_aed("90.00")
    ),
    Reversal("E9", "ACC-001", booked_day=6, value_day=2, target_event_id="E7"),
    Credit(
        "E10", "ACC-002", booked_day=5, value_day=5, amount=Money.of("10.000", BHD), instalments=3
    ),
)


def open_accounts(ledger: Ledger) -> None:
    ledger.open_account("ACC-001", AED)
    ledger.open_account("ACC-002", BHD)
