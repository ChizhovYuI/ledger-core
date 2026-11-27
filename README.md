# ledger-core

An in-memory account ledger. It replays 10 events over 6 days on two accounts.

- Each entry has a **value day** and a **booked day**.
- One query gives every balance: `balance(account, value_day_upto, known_at)`.
  No running balance is stored.
- Double entry, minimal: each posting has one customer leg and one internal leg
  (`external`, `card_settlement`, `fee_income`, `interest_expense`). Amounts are signed.
  All legs sum to zero per currency. A hold is not a leg.
- The journal and the hold log are append-only. A correction is a new linked entry.

## One test is red on purpose

`tests/test_known_gap.py` fails on an assertion. It shows a gap in this design: a decline
keeps no mark after its cause is reversed. `make check` excludes it. `make failing` and a
plain `pytest` run show it.

## Run

Python 3.12 or later. With `uv`, or with plain `pip` from the repository root:

```sh
make install    # uv sync           | pip install pytest hypothesis
make replay     # print the 6 days  | python -m ledger
make check      # ruff, tests       | python -m pytest -m "not known_gap"
make failing    # the red test only
make replay ARGS="--fee 12.50 --rate 0.0008 --hold-expiry 5"
```

## Read the output

Day 5 from `make replay`:

```text
Day 5
  ACC-001  close as known -410.00 AED  restated 285.00 AED
  ACC-002  close as known 0.000 BHD  restated 10.000 BHD
  fees:
    ACC-001 day 2 check -370.00 AED: fee FEE/ACC-001/D2/1 -25.00 AED value day 2 booked day 5
    ACC-001 day 4 check -360.00 AED: fee FEE/ACC-001/D4/1 -25.00 AED value day 4 booked day 5
    ACC-001 day 5 check -385.00 AED: fee FEE/ACC-001/D5/1 -25.00 AED value day 5 booked day 5
  authorizations: Auth-A settled, Auth-Z unmatched, Auth-B declined (E8: ledger -335.00 AED, available after -425.00 AED)
  errors: none
  alerts: none
```

- **close as known** is the primary close. It is the balance at the day close, from the
  postings known at that time. Decisions were made on it.
- **restated** is the same day under the final history. The two differ on Day 5 only:
  E9 reverses E7 and its fees, and E10 arrives after the Day 5 close.
- **fees**: one line per fee or refund that the close posted. A backdated entry makes the
  close check each day again from its value day. `check` is the day's balance without
  that day's own fee. Day 3 (+5.00) gets no fee, so it has no line.
- **authorizations**: the state of each auth id; a decline shows its balances.
- **errors**: rejected events and their codes. **alerts**: flagged postings, late
  arrivals, repeat deliveries, negative closes with no fee configured.
- Day 6 also prints **interest**: the daily accruals, the total and the carry.

## The 8 criteria

| # | Result | Reason | Test in `tests/test_criteria.py` |
|---|---|---|---|
| 1 | accept | Day 2 check at the Day 5 close is −370.00 | `test_criterion_1_day2_check_before_any_fee` |
| 2 | refuse | three fees (Days 2, 4, 5), not one | `test_criterion_2_three_fees_not_one` |
| 3 | accept | posts 185.00, releases the full 200.00 hold | `test_criterion_3_settle_lower_releases_full_hold` |
| 4 | refuse | the issuer must pay; posted, flagged, dispute | `test_criterion_4_unmatched_settlement_posts` |
| 5 | accept | true as a rule; Auth-B is declined in the stream | `test_criterion_5_approved_hold_reduces_available_only` |
| 6 | refuse | money returns; decisions and records do not | `test_criterion_6_reversal_restates_money_not_decisions` |
| 7 | refuse | 3 × 3.334 = 10.002 | `test_criterion_7_instalments_sum_to_the_amount` |
| 8 | refuse | the remainder is carried, not discarded | `test_criterion_8_remainder_is_carried` |

The reasons for each refusal are in [REJECTED.md](REJECTED.md).

## Layout

| Module in `ledger/` | Content |
|---|---|
| `money`, `config` | `Money` at currency scale, `split`; `LedgerConfig` with every constant |
| `journal`, `holds` | postings, legs, the balance query; the append-only hold log |
| `events`, `stream`, `processor` | event types, E1-E10, handlers: posted / approved / declined / rejected |
| `close`, `interest` | day close: hold expiry, fee checks, refunds; accrual with carry |
| `replay`, `report`, `__main__` | replay driver, output, command line |

`tests/` has one file per module, plus `test_criteria.py`, `test_properties.py` and
`test_known_gap.py`.

Also: [NUMBERS.md](NUMBERS.md) (constants), [AMBIGUITIES.md](AMBIGUITIES.md) (open
rules), [REJECTED.md](REJECTED.md) (refusals, abandoned approaches),
[WORKLOG.md](WORKLOG.md) (the work, with times).
