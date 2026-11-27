from __future__ import annotations

import argparse
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from ledger.config import DEFAULT_CONFIG, LedgerConfig
from ledger.errors import LedgerError
from ledger.money import AED, Money
from ledger.replay import replay_stream
from ledger.report import render


def _decimal(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a decimal: {value!r}") from None
    if not result.is_finite():
        raise argparse.ArgumentTypeError(f"not a finite decimal: {value!r}")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ledger", description="Replay the 10-event stream and print each day."
    )
    parser.add_argument("--fee", metavar="AMOUNT", help="overdraft fee in AED (default 25.00)")
    parser.add_argument("--rate", type=_decimal, help="daily interest rate (default 0.0004)")
    parser.add_argument("--hold-expiry", type=int, metavar="DAYS", help="default 10")
    args = parser.parse_args(argv)

    try:
        config = LedgerConfig(
            overdraft_fee=(
                {AED: Money.of(args.fee, AED)}
                if args.fee is not None
                else DEFAULT_CONFIG.overdraft_fee
            ),
            daily_interest_rate=(
                args.rate if args.rate is not None else DEFAULT_CONFIG.daily_interest_rate
            ),
            hold_expiry_days=(
                args.hold_expiry
                if args.hold_expiry is not None
                else DEFAULT_CONFIG.hold_expiry_days
            ),
        )
        output = render(replay_stream(config))
    except (ValueError, LedgerError) as error:
        parser.error(str(error))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
