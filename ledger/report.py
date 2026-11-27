from __future__ import annotations

from decimal import Decimal

from ledger.close import FeeAction, FeeCheck
from ledger.events import Authorization
from ledger.interest import Capitalization
from ledger.journal import Posting
from ledger.processor import AuthState, Status
from ledger.replay import DayReport, Replay


def render(replay: Replay) -> str:
    """The per-day report of a finished replay."""
    postings = {p.posting_id: p for p in replay.ledger.journal.postings}
    accounts = [ref.code for ref in replay.ledger.customer_accounts()]
    lines: list[str] = []
    for report in replay.reports:
        lines.append(f"Day {report.day}")
        for code in accounts:
            lines.append(
                f"  {code}  close as known {replay.as_known(code, report.day)}"
                f"  restated {replay.restated(code, report.day)}"
            )
        lines += _section(
            "fees",
            [
                _fee(c, postings)
                for c in report.close.checks
                if c.action in (FeeAction.FEE, FeeAction.REFUND)
            ],
        )
        lines.append(f"  authorizations: {_auths(report)}")
        new = [a for a in report.arrivals if not a.repeat]
        lines += _section(
            "errors",
            [
                f"{a.event.event_id} rejected: {a.outcome.reason}"
                for a in new
                if a.outcome.status is Status.REJECTED
            ],
        )
        lines += _section(
            "alerts",
            [
                *(
                    f"{a.event.event_id}: repeat delivery, ignored"
                    for a in report.arrivals
                    if a.repeat
                ),
                *(f"{a.event.event_id}: {alert}" for a in new for alert in a.outcome.alerts),
                *report.alerts,
            ],
        )
        if report.close.interest:
            lines += _section("interest", [_interest(c) for c in report.close.interest])
        lines.append("")
    return "\n".join(lines)


def _section(name: str, items: list[str]) -> list[str]:
    if not items:
        return [f"  {name}: none"]
    return [f"  {name}:", *(f"    {item}" for item in items)]


def _fee(check: FeeCheck, postings: dict[str, Posting]) -> str:
    head = f"{check.account} day {check.day} check {check.check}: {check.action}"
    if check.posting_id is None:
        return head
    posting = postings[check.posting_id]
    return (
        f"{head} {posting.posting_id} {posting.customer_leg.amount}"
        f" value day {posting.value_day} booked day {posting.booked_day}"
    )


def _auths(report: DayReport) -> str:
    if not report.auth_states:
        return "none"
    declined = {
        a.event.auth_id: a.outcome
        for a in report.arrivals
        if not a.repeat
        and a.outcome.status is Status.DECLINED
        and isinstance(a.event, Authorization)
    }
    parts = []
    for auth_id, state in report.auth_states:
        text = f"{auth_id} {state}"
        outcome = declined.get(auth_id)
        if state is AuthState.DECLINED and outcome is not None:
            text += (
                f" ({outcome.event_id}: ledger {outcome.ledger},"
                f" available after {outcome.available_after})"
            )
        parts.append(text)
    return ", ".join(parts)


def _interest(cap: Capitalization) -> str:
    daily = ", ".join(str(a.rounded.amount) for a in cap.accruals)
    return (
        f"{cap.account} daily {daily} total {cap.total}"
        f" carry {_plain(cap.carry_out)} posting {cap.posting_id or 'none'}"
    )


def _plain(value: Decimal) -> str:
    return f"{value.normalize():f}"
