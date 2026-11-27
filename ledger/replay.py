from __future__ import annotations

from dataclasses import dataclass

from ledger.close import DayClose, close_day
from ledger.config import DEFAULT_CONFIG, LedgerConfig
from ledger.events import Event
from ledger.money import Money
from ledger.processor import Ledger, Outcome
from ledger.stream import STREAM, open_accounts


@dataclass(frozen=True)
class Arrival:
    event: Event
    outcome: Outcome
    late_arrival: bool = False


@dataclass(frozen=True)
class DayReport:
    day: int
    arrivals: tuple[Arrival, ...]
    close: DayClose

    @property
    def alerts(self) -> tuple[str, ...]:
        late = tuple(
            f"late_arrival: {a.event.event_id} booked day {a.event.booked_day}, "
            f"arrived on day {self.day}"
            for a in self.arrivals
            if a.late_arrival
        )
        return late + self.close.alerts


def _valid_day(day: object) -> bool:
    return isinstance(day, int) and not isinstance(day, bool) and day >= 1


class Replay:
    """Feeds events in arrival order. A day closes when an event of a later day
    arrives, and at `finish()`. Days with no event close too."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._open_day = 1
        self._since = ledger.journal.position
        self._arrivals: list[Arrival] = []
        self._reports: list[DayReport] = []
        self._last_booked = 0
        self._finished = False

    @property
    def reports(self) -> tuple[DayReport, ...]:
        return tuple(self._reports)

    @property
    def open_day(self) -> int:
        return self._open_day

    def feed(self, event: Event) -> Outcome:
        if self._finished:
            raise RuntimeError("the replay is finished")
        late = False
        accepted = not self.ledger.is_repeat(event) and self.ledger.precheck(event) is None
        if accepted and _valid_day(event.booked_day):
            while self._open_day < event.booked_day:
                self._close_open_day()
            late = event.booked_day < self._open_day
            self._last_booked = max(self._last_booked, event.booked_day)
        outcome = self.ledger.apply(event)
        self._arrivals.append(Arrival(event, outcome, late))
        return outcome

    def finish(self) -> tuple[DayReport, ...]:
        if not self._finished:
            last = max(self.ledger.config.window_days, self._last_booked)
            while self._open_day <= last:
                self._close_open_day()
            self._finished = True
        return self.reports

    def _close_open_day(self) -> None:
        close = close_day(self.ledger, self._open_day, self._since)
        self._reports.append(DayReport(self._open_day, tuple(self._arrivals), close))
        self._arrivals = []
        self._since = close.position
        self._open_day += 1

    def report(self, day: int) -> DayReport:
        for report in self._reports:
            if report.day == day:
                return report
        raise LookupError(f"day {day} is not closed")

    def as_known(self, account: str, day: int) -> Money:
        """The close of `day` as the ledger knew it at that day's close."""
        ref = self.ledger.journal.account(account)
        position = self.report(day).close.position
        return self.ledger.journal.balance(ref, value_day_upto=day, known_at=position)

    def restated(self, account: str, day: int) -> Money:
        """The close of `day` with every posting known now."""
        self.report(day)
        ref = self.ledger.journal.account(account)
        return self.ledger.journal.balance(ref, value_day_upto=day)


def replay_stream(config: LedgerConfig = DEFAULT_CONFIG) -> Replay:
    ledger = Ledger(config)
    open_accounts(ledger)
    replay = Replay(ledger)
    for event in STREAM:
        replay.feed(event)
    replay.finish()
    return replay
