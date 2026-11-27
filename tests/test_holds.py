import dataclasses

import pytest

from ledger.config import LedgerConfig
from ledger.events import Authorization, Credit
from ledger.holds import HoldBook, HoldChange, HoldChangeKind
from ledger.money import AED, Money
from ledger.processor import AuthState, Ledger


def _aed(value: str) -> Money:
    return Money.of(value, AED)


def _ledger_with_hold(expiry_days: int) -> Ledger:
    ledger = Ledger(LedgerConfig(hold_expiry_days=expiry_days))
    ledger.open_account("ACC-001", AED)
    ledger.apply(Credit("C0", "ACC-001", booked_day=1, value_day=1, amount=_aed("500.00")))
    ledger.apply(
        Authorization(
            "A0", "ACC-001", booked_day=1, value_day=1, auth_id="Auth-1", amount=_aed("200.00")
        )
    )
    return ledger


@pytest.mark.parametrize("expiry_days", [5, 10, 20])
def test_hold_expiry(expiry_days: int) -> None:
    ledger = _ledger_with_hold(expiry_days)

    still_active = ledger.expire_holds(expiry_days)

    assert still_active == ()
    assert ledger.auth_state("Auth-1") is AuthState.ACTIVE
    assert ledger.available("ACC-001") == _aed("300.00")

    expired = ledger.expire_holds(1 + expiry_days)

    assert [change.kind for change in expired] == [HoldChangeKind.EXPIRED]
    assert ledger.auth_state("Auth-1") is AuthState.EXPIRED
    assert ledger.available("ACC-001") == _aed("500.00")
    changes = ledger.holds.changes

    assert ledger.expire_holds(2 + expiry_days) == ()
    assert ledger.holds.changes == changes


def test_hold_log_append_only() -> None:
    book = HoldBook()
    placed = HoldChange("Auth-1", "ACC-001", _aed("10.00"), HoldChangeKind.PLACED, 1, "A0")
    book.append(placed)
    first = book.changes

    with pytest.raises(dataclasses.FrozenInstanceError):
        placed.kind = HoldChangeKind.EXPIRED
    assert isinstance(first, tuple)

    book.expire(day=20, expiry_days=10)

    assert book.changes[: len(first)] == first
    assert len(book.changes) == len(first) + 1
    assert book.changes[-1].kind is HoldChangeKind.EXPIRED
    assert placed.kind is HoldChangeKind.PLACED
    for name in ("delete", "remove", "update", "__setitem__", "__delitem__"):
        assert not hasattr(book, name)
