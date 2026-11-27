import pytest

from ledger.processor import Status
from ledger.replay import replay_stream


@pytest.mark.known_gap
def test_decline_is_marked_when_its_cause_is_reversed() -> None:
    # Intentional failing test. E8 (Auth-B) is declined at -335.00 because of E7; E9
    # reverses E7, so restated Day 5 is 285.00 and a 90.00 hold would pass. A reversal
    # restates money, not decisions: nothing links E9 to the decisions made on E7's
    # data, so the decline keeps no mark. Not fixed: an
    # approval cannot be made after the fact, and the mark needs a decision log.
    replay = replay_stream()

    e8 = next(o for o in replay.ledger.outcomes if o.event_id == "E8")

    assert e8.status is Status.DECLINED
    assert "cause_reversed" in e8.flags
