# Work log

One line per entry: `time — tag — what`. Tags: `own` (the author's own work or
decision), `AI` (written by an AI assistant), `both`. An AI entry stays
`AI, not read` until the author has read the change.

## 2026-11-26 to 2026-11-27, before this repository (reconstructed from notes)

These entries are rebuilt from the decision notes of the plan and the file times of the
planning notes. The times are file times, not the exact times of the decisions.

- 2026-11-26 19:51 +07 — both — Read the brief; listed each open rule as a decision with options.
- 2026-11-26 21:49 +07 — both — Throwaway prototype: replayed the stream under each option set for backdating, the fee value day and fees after a reversal; property search with Hypothesis. Not in this repository.
- 2026-11-26 21:52 +07 — own — Decided the six rules below.
  - A backdated entry re-checks each closed day from its value day.
  - A late fee has the value day of the day it is for. Its booked day is the day of the check.
  - When the cause of a fee is reversed, new linked entries refund the fee.
  - A settlement with no authorization posts. It is flagged as unmatched.
  - Interest uses value-dated balances as known at capitalization.
  - Daily accruals carry the rounding fraction to the next day.
- 2026-11-27 12:24 +07 — own — Decided the six rules below.
  - Minimal double entry, with four internal accounts per currency.
  - Hold expiry is a parameter. The default is 10 days.
  - Each day line prints two closes: the close as known that day, and the restated close.
  - Python with `decimal`.
  - The intentional failing test: a decline stays unmarked after its cause is reversed.
  - Criterion 5 is accepted as a rule.
- 2026-11-27 12:28 +07 — own — Approved the plan; step 1 planned.

## 2026-11-27

- 2026-11-27 12:33 +07 — AI, read by the owner — Step 1: repository, `Money` with currency scale, config, append-only journal with signed two-leg postings and one balance query on two axes (value day, journal position).
- 2026-11-27 12:53 +07 — AI, read by the owner — Step 2: event handlers (credit, debit, authorization, settlement, reversal, instalments), append-only hold log with expiry, D7 posting shape and per-kind sign check, the stream E1-E10 as data.
- 2026-11-27 13:13 +07 — own — Replayed E1-E10 by hand on paper: closes as known and restated, the Day 5 fee checks, the refunds, interest with carry, ACC-002. All numbers match the plan.
- 2026-11-27 13:18 +07 — AI, read by the owner — Step 3: replay driver and day close. At each close: hold expiry, then the fee check again from the earliest value day of the new postings. A fee for a negative day; a linked refund when that day is no longer negative. An alert for a negative close in a currency with no fee. A late arrival is marked.
- 2026-11-27 13:38 +07 — own — Decided: the interest credit has value day 6. It is posted at the end of the Day 6 close, after the fee checks. The time is the file time of the step plan.
- 2026-11-27 13:38 +07 — AI, read by the owner — Step 4: interest.
  - At the Day 6 close, the ledger makes one accrual for each day. It uses the value-dated balances as known at that time.
  - It rounds each day after it adds the carry. The lost fraction moves to the next day.
  - Each account gets one capitalization credit with an `interest_expense` leg.
  - The carry stays in the accrual state. It is never a ledger amount.
- 2026-11-27 13:54 +07 — AI, read by the owner — Step 5: replay output and tests.
  - `make replay` prints each day: both closes, fee checks, authorization states, errors, alerts. Day 6 also prints interest.
  - Overrides: `--fee`, `--rate`, `--hold-expiry`.
  - One test for each criterion, with accept or refuse and the reason.
  - A zero-sum property over generated streams.
  - The intentional failing test, run by `make failing`.
- 2026-11-27 14:29 +07 — AI, read by the owner — Step 6: README, `NUMBERS.md`, `AMBIGUITIES.md`, `REJECTED.md`. Each half and double is from a real run.
