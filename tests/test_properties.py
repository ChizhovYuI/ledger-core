from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from ledger.events import Authorization, Credit, Debit, Event, Reversal, Settlement
from ledger.journal import _sum_by_currency
from ledger.money import AED, BHD, Money
from ledger.processor import Ledger
from ledger.replay import Replay
from ledger.stream import open_accounts

_ACCOUNTS = {"ACC-001": AED, "ACC-002": BHD}
_AUTH_IDS = ("Auth-1", "Auth-2", "Auth-3")


@st.composite
def _streams(draw: st.DrawFn) -> list[Event]:
    events: list[Event] = []
    for index in range(draw(st.integers(1, 12))):
        event_id = f"G{index}"
        account = draw(st.sampled_from(sorted(_ACCOUNTS)))
        ccy = _ACCOUNTS[account]
        booked = draw(st.integers(1, 6))
        value = draw(st.integers(1, booked))
        minor = draw(st.integers(1, 100_000))
        amount = Money(Decimal(minor).scaleb(-ccy.scale), ccy)
        kind = draw(st.sampled_from(("credit", "debit", "auth", "settle", "reverse")))
        if kind == "credit":
            events.append(Credit(event_id, account, booked, value, amount, draw(st.integers(1, 3))))
        elif kind == "debit":
            events.append(Debit(event_id, account, booked, value, amount))
        elif kind == "auth":
            auth_id = draw(st.sampled_from(_AUTH_IDS))
            events.append(Authorization(event_id, account, booked, value, auth_id, amount))
        elif kind == "settle":
            auth_id = draw(st.sampled_from(_AUTH_IDS))
            events.append(Settlement(event_id, account, booked, value, auth_id, amount))
        elif events:
            target = draw(st.sampled_from([e.event_id for e in events]))
            events.append(Reversal(event_id, account, booked, value, target))
    return events


@settings(max_examples=200, deadline=None)
@given(_streams())
def test_zero_sum_on_generated_streams(events: list[Event]) -> None:
    ledger = Ledger()
    open_accounts(ledger)
    replay = Replay(ledger)

    for event in events:
        replay.feed(event)
    replay.finish()

    for posting in ledger.journal.postings:
        assert all(t.is_zero() for t in _sum_by_currency(posting.legs).values())
    assert all(t.is_zero() for t in ledger.journal.totals_by_currency().values())
    ledger.journal.assert_balanced()
