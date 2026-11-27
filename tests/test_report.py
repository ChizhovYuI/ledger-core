import pytest

from ledger.__main__ import main
from ledger.events import Debit
from ledger.money import BHD, Money
from ledger.processor import Ledger
from ledger.replay import Replay, replay_stream
from ledger.report import render
from ledger.stream import STREAM, open_accounts


def _days(text: str) -> dict[int, str]:
    blocks = [b for b in text.split("\n\n") if b.strip()]
    return {int(b.splitlines()[0].removeprefix("Day ")): b for b in blocks}


@pytest.fixture(scope="module")
def days() -> dict[int, str]:
    return _days(render(replay_stream()))


def test_render_day_lines(days: dict[int, str]) -> None:
    acc_001 = [
        ("250.00", "250.00"),
        ("250.00", "250.00"),
        ("650.00", "650.00"),
        ("285.00", "285.00"),
        ("-410.00", "285.00"),
        ("285.80", "285.80"),
    ]
    acc_002 = [("0.000", "0.000")] * 4 + [("0.000", "10.000"), ("10.008", "10.008")]

    assert sorted(days) == [1, 2, 3, 4, 5, 6]
    for day in range(1, 7):
        known, restated = acc_001[day - 1]
        assert f"ACC-001  close as known {known} AED  restated {restated} AED" in days[day]
        known, restated = acc_002[day - 1]
        assert f"ACC-002  close as known {known} BHD  restated {restated} BHD" in days[day]
    day5_fees = [line.strip() for line in days[5].splitlines() if "FEE/" in line]
    assert day5_fees == [
        "ACC-001 day 2 check -370.00 AED: fee FEE/ACC-001/D2/1 -25.00 AED value day 2 booked day 5",
        "ACC-001 day 4 check -360.00 AED: fee FEE/ACC-001/D4/1 -25.00 AED value day 4 booked day 5",
        "ACC-001 day 5 check -385.00 AED: fee FEE/ACC-001/D5/1 -25.00 AED value day 5 booked day 5",
    ]
    day6_refunds = [line for line in days[6].splitlines() if ": refund REFUND/" in line]
    assert len(day6_refunds) == 3
    assert all("25.00 AED" in line and "booked day 6" in line for line in day6_refunds)


def test_render_empty_lines(days: dict[int, str]) -> None:
    lines = [line.strip() for line in days[1].splitlines()]

    assert "fees: none" in lines
    assert "authorizations: none" in lines
    assert "errors: none" in lines
    assert "alerts: none" in lines
    assert all(f"{name}:" in days[d] for d in days for name in ("fees", "authorizations", "errors"))


def test_render_auth_states(days: dict[int, str]) -> None:
    assert "authorizations: Auth-A active\n" in days[2]
    assert "authorizations: Auth-A settled, Auth-Z unmatched\n" in days[4]
    assert "Auth-B declined (E8: ledger -335.00 AED, available after -425.00 AED)" in days[5]
    assert "E6: settlement with no approved authorization" in days[4]
    assert "late_arrival: E10 booked day 5, arrived on day 6" in days[6]


def test_render_interest(days: dict[int, str]) -> None:
    assert "interest:" in days[6]
    assert all("interest:" not in days[d] for d in range(1, 6))
    assert (
        "ACC-001 daily 0.10, 0.10, 0.26, 0.11, 0.12, 0.11 total 0.80 AED carry 0.002"
        " posting INTEREST/ACC-001/D6"
    ) in days[6]
    assert "ACC-002 daily 0.000, 0.000, 0.000, 0.000, 0.004, 0.004 total 0.008 BHD" in days[6]


def test_main_overrides(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--fee", "12.50"]) == 0
    out = capsys.readouterr().out
    assert out.count(": fee FEE/") == 3
    assert out.count("-12.50 AED value day") == 3

    for argv in (["--hold-expiry", "0"], ["--rate", "-1"], ["--fee", "0"], ["--fee", "1.001"]):
        with pytest.raises(SystemExit) as exit_info:
            main(argv)
        assert exit_info.value.code == 2
    assert "usage:" in capsys.readouterr().err


@pytest.mark.parametrize("rate", ["NaN", "sNaN", "Infinity", "1e30", "abc"])
def test_main_bad_rate_exits_2(rate: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--rate", rate])
    assert exit_info.value.code == 2


def test_render_repeat_delivery_alerts_once() -> None:
    ledger = Ledger()
    open_accounts(ledger)
    replay = Replay(ledger)
    for event in STREAM[:8]:
        replay.feed(event)
    replay.feed(STREAM[5])
    replay.feed(STREAM[7])
    replay.finish()

    days = _days(render(replay))

    assert "E6: settlement with no approved authorization" in days[4]
    assert "E6: settlement with no approved authorization" not in days[5]
    assert "E6: repeat delivery, ignored" in days[5]
    assert days[5].count("Auth-B declined (E8:") == 1


def test_render_no_fee_currency_only_in_alerts() -> None:
    ledger = Ledger()
    open_accounts(ledger)
    replay = Replay(ledger)
    replay.feed(Debit("B1", "ACC-002", 1, 1, Money.of("1.000", BHD)))
    replay.finish()

    day1 = _days(render(replay))[1]

    assert "fees: none" in day1
    assert "no_fee_configured: ACC-002 day 1 closes at -1.000 BHD" in day1


def test_main_rate_override(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--rate", "0"]) == 0
    out = capsys.readouterr().out
    assert "ACC-001  close as known 285.00 AED  restated 285.00 AED" in _days(out)[6]
    assert "total 0.00 AED carry 0 posting none" in out
