"""Time the balance query and one day close at 1x and 100x journal size.

The numbers show how the cost grows with the journal. They are not a capacity.
"""

from __future__ import annotations

import platform
import sys
import time
from collections.abc import Callable
from functools import partial

from ledger.close import close_day
from ledger.config import LedgerConfig
from ledger.journal import AccountRef, InternalAccount, Leg, Posting, PostingKind
from ledger.money import AED, Money
from ledger.processor import Ledger

ACCOUNTS = 100
DAYS = 60
BACKDATE = 30
SIZES = (5_000, 500_000)


def _credit(
    ledger: Ledger, posting_id: str, account: AccountRef, day: int, booked: int | None = None
) -> None:
    amount = Money.of("10.00", AED)
    external = AccountRef.internal_for(InternalAccount.EXTERNAL, AED)
    ledger.journal.append(
        Posting(
            posting_id=posting_id,
            kind=PostingKind.CREDIT,
            value_day=day,
            booked_day=day if booked is None else booked,
            legs=(Leg(account, amount), Leg(external, -amount)),
            cause=posting_id,
        )
    )


def _build(n: int) -> tuple[Ledger, int]:
    ledger = Ledger(LedgerConfig(window_days=DAYS + 1))
    accounts = [ledger.open_account(f"A{i:03}", AED) for i in range(ACCOUNTS)]
    for i in range(n):
        _credit(ledger, f"P{i}", accounts[i % ACCOUNTS], 1 + i * DAYS // n)
    since = ledger.journal.position
    _credit(ledger, "BACKDATED", accounts[0], DAYS - BACKDATE, booked=DAYS)
    return ledger, since


def _best_ms(runs: int, action: Callable[[], object]) -> float:
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        action()
        best = min(best, time.perf_counter() - start)
    return best * 1000


def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
    if len(sys.argv) > 1 and (not sys.argv[1].isdigit() or runs < 1):
        sys.exit("usage: timing.py [runs >= 1]")
    print(f"Python {platform.python_version()}, {platform.machine()}, best of {runs}")
    print(f"{'postings':>10} {'balance ms':>12} {'close ms':>12}")
    for n in SIZES:
        ledger, since = _build(n)
        account = ledger.journal.account("A000")
        balance_ms = _best_ms(runs, partial(ledger.journal.balance, account, DAYS))
        close_ms = _best_ms(runs, partial(close_day, ledger, DAYS, since))
        print(f"{n:>10,} {balance_ms:>12.2f} {close_ms:>12.1f}")


if __name__ == "__main__":
    main()
