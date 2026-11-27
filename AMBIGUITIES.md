# Ambiguities

Each entry: the brief's words, the reading chosen, the effect on the numbers, the test.
"Reading" = how the author reads the brief's text. "Chosen" = the author's policy.

## Fees

**Backdated entry and closed days.** E7 (booked Day 5) has value day 2. Brief: closing
balance is "all entries with value_date ≤ that day". Reading: the close checks each day
again, from the earliest value day of its new postings. Effect: fees on Days 2, 4, 5; one
fee per day at most. `test_criterion_2_three_fees_not_one`, `test_close_twice_no_second_fee`

**Value day of a late fee.** Brief: "Booked with value_date equal to the day assessed".
Reading: "assessed" = the day the fee is for, not the day the check runs. The Day 2 fee
has value day 2, booked day 5. Effect: it counts in Day 3's check (+5.00, no fee).
`test_day5_fee_checks`

**A fee in later checks.** Brief: criterion 1 says "before any fee is assessed". Reading:
a fee counts in the checks of later days, not in the check of its own day. Effect: Day 4
check −360.00 includes the Day 2 fee. `test_criterion_1_day2_check_before_any_fee`

**Fees after a reversal.** The brief does not say. Chosen: when a day is no longer
negative, the close posts a refund linked to the fee and to the cause. Effect: three
refunds of 25.00 on Day 6; `fee_income` nets to 0.00. `test_day6_refunds`

**Fee only for AED.** Brief: AED 25.00 "per day per account". Reading: the fee is an AED
amount; no exchange rate is invented. A negative BHD close gives a `no_fee_configured`
alert and no fee. No effect here: ACC-002 never closes negative. `test_no_fee_currency_alert`

**Recheck range.** Chosen: the close checks each day from the earliest value day among
the postings since the last close, to the closing day. Fee and refund postings do not
start a recheck. `test_refund_then_new_fee`

**A day with no event still closes.** Chosen: the replay closes every day up to the
event's booked day, and at the end each day up to Day 6. `test_skipped_day_is_closed`

**A refund is not a reversal.** Chosen: a refund is a new posting of kind `fee_refund`,
linked to its fee (first link) and to the postings that changed the day. The fee record
stays. `test_criterion_6_reversal_restates_money_not_decisions`

## Interest

**Which balances.** Brief: "on the closing ledger balance". Reading: value-dated balances
as known at capitalization, the same definition as the fee rule. Effect: the bases are
the restated closes 250, 250, 650, 285, 285, 285; total 0.80. `test_acc_001_accruals`

**Sum exactly.** Brief: accruals "must sum exactly to the capitalized total". Chosen:
round each day after adding the carry. 0.802 exact, 0.80 credited, 0.002 carried. The
carry is not money: it has more decimals and stays in the accrual state for the next
period. Each ledger amount has its currency scale. `test_accrual_sum_rule`,
`test_criterion_8_remainder_is_carried`, `test_carry_not_a_ledger_amount`

**Capitalization and the Day 6 close.** Brief: "a single credit at end of Day 6".
Chosen: value day 6, posted at the end of the Day 6 close, after the fee checks. Both
Day 6 closes include it. The Day 6 fee check does not see the interest: a fee can stay on
a day that the interest makes positive. No effect here. `test_capitalization_posting`

**Interest at an Islamic bank.** The brief names interest. The rule is applied as given.
The author has no basis to map it to a profit-sharing product, and does not try. With
double entry, a charge of another kind goes to another internal account.

## Rounding and amounts

**Rounding mode.** Brief: "rounded to their own precision", no mode. Chosen: half-even.
No exact tie occurs in this stream. `test_quantize_half_even`

**Three equal instalments.** Brief: "three equal instalments" of 10.000 BHD. Reading:
equal to the minor unit, and the parts sum to the amount: 3.334 + 3.333 + 3.333. The
extra unit goes to the earliest part. `test_e10_instalments`

**An instalment below the minor unit.** Chosen: reject with
`instalment_below_minor_unit` (for example 0.001 BHD in 3). `test_instalment_below_minor_unit_rejected`

## Order and time

**Order.** Brief: "replayed in this order". Chosen: the listed order; never sorted.
`test_as_known_closes`

**E10 arrives late.** E10 is booked Day 5 but listed after E9 (Day 6). Chosen: it keeps
booked day 5 and is reported as a late arrival on Day 6. Effect: ACC-002 as known on
Day 5 is 0.000; restated 10.000. `test_e10_late_arrival`

**When the close runs.** Brief: criterion 1 says "evaluated at end of Day 5". Chosen:
fees, refunds and hold expiry run at the day close. A day closes when an event of a later
day arrives, and at the end of the stream. A rejected event closes no day.
`test_auth_b_declined_before_fees`, `test_rejected_event_closes_no_day`

**Two closes per day.** Brief: "closing ledger balance", one number. Chosen: print the
close as known (primary; taken at the close, in arrival order) and the restated close.
`test_as_known_closes`, `test_restated_closes`

## Authorizations

**Available balance.** Brief: "ledger balance minus active holds". Reading: all booked
entries, also future-valued, minus active holds, at the time of the event. Effect: Auth-B
declined at ledger −335.00, available after −425.00. `test_e8_auth_b_declined`

**Settled for less.** E5 settles 185.00 on a 200.00 hold. Chosen: post 185.00 and release
the full hold. `test_criterion_3_settle_lower_releases_full_hold`

**Settlement with no active hold.** Chosen: post it with a flag: `unmatched` (no
approved authorization, E6), `after_expiry`, `after_settlement`, `over_hold`. Each flag
gives an alert. `test_settlement_after_expiry_flagged`, `test_settlement_over_hold_flagged`

**Hold with no settlement.** Brief: "Auth-B is never settled". Chosen: a hold made on
day d expires at the close of day d + 10. Never fires here. `test_hold_expiry`

**Auth state after a reversal.** Chosen: a decision is not changed later. Auth-B stays
`declined` after E9. `tests/test_known_gap.py` asks for a mark and fails.

**Criterion 5.** The premise is false in this stream: Auth-B is declined. Accepted as a
rule, shown by Auth-A and by the stream without E7. `test_criterion_5_approved_hold_reduces_available_only`

## Event checks

**Three outcomes.** Chosen: `declined` is a business answer, `rejected` is an invalid
event (no posting), an alert is posted and flagged. `test_rejected_event_changes_nothing`

**Reject codes.** `unknown_account`, `currency_mismatch`, `non_positive_amount`,
`invalid_day`, `unknown_target`, `already_reversed`, `target_is_reversal`,
`target_is_authorization`, `target_rejected`, `target_on_other_account`,
`invalid_instalments`, `posting_id_collision`. `test_rejected_event_changes_nothing`

**Repeat delivery.** Chosen: the same id with the same content returns the first
outcome, also a rejection. So an event rejected for its order (`unknown_target`) needs a
new id. The same id with other content is rejected (`event_id_reused`).
`test_same_event_twice_same_outcome`, `test_event_id_reused_with_other_content_rejected`

**A debit and the balance.** The brief checks only authorizations. Chosen: a debit is not
checked against the balance. E7 posts and makes the balance negative. `test_e7_backdated`

**Reversal.** Chosen: reverse each posting of the target, with the reversal's own value
day. A different value day gives `value_day_differs`. A reversal booked before its target
is rejected (`reversal_before_target`). `test_reversal_value_day_differs_flagged`

**Auth ids.** Chosen: an authorization reuses no auth id (`auth_id_reused`), also one
first seen on an unmatched settlement. A settlement for an auth on another account is
rejected (`auth_on_other_account`). `test_auth_id_first_used_by_unmatched_settlement_rejected`

**Reserved ids.** Chosen: event ids that start with `FEE/`, `REFUND/` or `INTEREST/` are
rejected (`reserved_event_id`): the close makes those posting ids. `test_interest_id_reserved`

**Known limits of the code.** An event with a very large booked day makes the replay close
each day up to it, so the run does not end in practice. An amount near the `decimal` limit
is accepted, then the close stops with `AmountPrecisionError`. No effect here.

## Known risks of the rule

**Interest is final at capitalization.** A posting valued Day 6 or earlier that arrives
after the Day 6 close restates the fees, not the interest. No effect here.

**Fee on a fee.** While a balance stays negative, each day's fee makes the next day more
negative. A 1.00 debit on Day 1, paid back by a 1.00 credit on Day 2, still gives six
fees: 150.00 by Day 6. After Day 1, only the fees keep the balance negative. The rule
says nothing to stop it.

**Backdated fees on closed days.** The rule charges a day after it closed. The US CFPB
says fees "on transactions that a consumer would not reasonably anticipate are likely
unfair" (Circular 2022-06). In the EU the debit value date must be "no earlier than the
time at which the amount of the payment transaction is debited" (PSD2 Art. 87(3)). No UAE
Central Bank rule on value dates or backdating was found.
