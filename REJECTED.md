# Rejected

## Refused criteria

Each test is in `tests/test_criteria.py`.

### 2. "E7 causes exactly one overdraft fee to be assessed, on Day 2."

- Wrong: the fee rule uses "all entries with value_date ≤ that day". E7 is valued Day 2,
  so it is in the closes of Days 2 to 5, not only Day 2.
- Day 2 check −370.00: fee. Day 3: +5.00, after the Day 2 fee: no fee. Day 4: −360.00:
  fee. Day 5: −385.00: fee.
- The code posts three fees of 25.00, value days 2, 4, 5, booked Day 5.
- Test: `test_criterion_2_three_fees_not_one`.

### 4. "Any settlement referencing an authorization ID not present in the ledger must be rejected and the funds must not leave the account."

- Wrong: a settlement is a clearing from the card scheme, not a request that the issuer
  can refuse. Visa: "An Issuer must pay the Acquirer the amount due for a Transaction
  occurring with the use of a valid Card." (Visa Core Rules, ID#0006558)
- The remedy is a dispute after payment: condition 11.3, "A valid Authorization was
  required but was not obtained" (ID#0030270), within 75 calendar days.
- Limit: 11.3 needs a certification that the account was flagged "Credit Problem",
  "Closed" or "Fraud" (Table 11-51). So the money may not come back.
- The code posts E6 (−180.00), flags it `unmatched`, and alerts "open dispute 11.3".
  Auth-Z state: `unmatched`.
- Test: `test_criterion_4_unmatched_settlement_posts`.

### 6. "After E9, all balances and fees return to their pre-E7 values."

- Wrong for the word "all". The money returns:
  - each restated close equals the stream without E7 and E9;
  - each fee gets a linked refund; `fee_income` nets to 0.00.
- These do not return:
  - the journal: E7, E9, three fees and three refunds stay (append-only);
  - the Day 5 close as known: −410.00, not 285.00;
  - the Auth-B decline: made at −335.00; with no E7 it is approved.
- The ledger restates money, not decisions. The intentional failing test
  (`tests/test_known_gap.py`) shows the gap: the decline keeps no mark.
- Test: `test_criterion_6_reversal_restates_money_not_decisions`.

### 7. "The three BHD instalments in E10 must each be BHD 3.334."

- Wrong: 3 × 3.334 = 10.002, not the 10.000 credited. The customer would get 0.002 BHD
  that nobody paid in.
- The code splits 10.000 into 3.334 + 3.333 + 3.333 (largest remainder, the extra unit to
  the earliest part).
- Test: `test_criterion_7_instalments_sum_to_the_amount`.

### 8. "If the rounded daily interest accruals do not sum to the capitalized total, the remainder is discarded."

- Wrong: the rule says the rounded accruals "must sum exactly to the capitalized total".
  So no remainder exists between them.
- The remainder against the exact interest is kept, not discarded: 0.802 exact, 0.80
  credited, 0.002 carried to the next period. To discard it moves money from the
  customer to the bank on each period.
- Test: `test_criterion_8_remainder_is_carried`.

## Abandoned approaches

Each one was used or recommended, then dropped. The date is the day of the decision.

| Approach | Dropped | Why |
|---|---|---|
| Keep the fees after a reversal (first recommendation) | 2026-11-26 | The prototype ran each option set. With fees kept, a late credit leaves fees that the final history does not support. Only "recheck + fee on its own day + refund" passed all three properties: arrival-order independence, an idempotent close, fees that match the final history. |
| Value the late fee on the check day | 2026-11-26 | Day 3 would not see the Day 2 fee. It changes the restated closes and interest. |
| No recheck of closed days | 2026-11-26 | Against "all entries with value_date ≤ that day". One fee, on Day 5. |
| Reject an unmatched settlement | 2026-11-26 | Against the scheme rule above. The issuer pays anyway, and the balance would not show it. |
| Post an unmatched settlement to a suspense account | 2026-11-26 | Customer balance unchanged; the money is still paid. Kept as a production step, not for this model. |
| Interest on each day as known, never corrected | 2026-11-26 | Two definitions of a close. After E9 the customer would lose the interest of the days that E7 made negative. |
| Interest = sum of rounded days | 2026-11-26 | 0.79 against 0.802 exact; the error grows with the days. |
| Single entry | 2026-11-27 | No zero-sum check; nothing shows where money came from. |
| No hold expiry | 2026-11-27 | A hold with no settlement blocks money for ever. |
| Print one close per day | 2026-11-27 | One number hides either the decision basis or the final history. |
| Failing test on arrival order | 2026-11-27 | With refunds, arrival order no longer changes the fees, so the test passed. |
| Mark the failing test `xfail`, or exclude it in `addopts` | 2026-11-27 | It would hide the red test from a plain `pytest` run. Only the Makefile excludes it. |
| Capitalize interest after the Day 6 close | 2026-11-27 | Two definitions of the Day 6 close. Replaced: the credit has value day 6 and is in the Day 6 close. |
