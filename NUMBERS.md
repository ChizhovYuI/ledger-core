# Numbers

Every constant is a field of `LedgerConfig` (`ledger/config.py`) or a constant in
`ledger/money.py`. Each half and double below comes from a real run
(`make replay ARGS="..."`) or from the named test.

## Chosen by the author

| Constant | Value | Why this value | Half / double |
|---|---|---|---|
| `hold_expiry_days` | 10 | Visa approval validity for a card-absent transaction is 10 calendar days (Table 5-11, ID#0031022). The event gives no channel, so the longer window. No issuer rule with a number of days was found. Issuer policies seen: 7 (Mambu, Adyen), 12-16 (two UAE banks). | 5: the hold is released while a valid card-absent clearing can still arrive; that clearing can make an overdraft and a fee. 20: the money stays blocked after no valid clearing is possible. Never fires in this stream: the 5, 10 and 20 runs print the same output. `test_hold_expiry[5/10/20]` |
| `rounding` | `ROUND_HALF_EVEN` | Ties go to the even minor unit, so ties do not all push one way. Python `decimal` default. | Not a number. No exact tie occurs in this stream: `ROUND_HALF_UP` and `ROUND_HALF_DOWN` print the same output. `ROUND_UP` gives 0.81 and a negative carry. `test_accrual_sum_rule` |
| `split` remainder | earliest part | Largest-remainder split: the parts sum exactly to the amount; a tie goes to the earliest part. | Not a number. 10.000 BHD in 3 = 3.334 + 3.333 + 3.333. `test_split_bhd_ten_in_three`, `test_split_property` |
| interest carry | kept | The fraction lost by rounding moves to the next day and stays in the accrual state after capitalization. It is never a ledger amount. | Not a number. ACC-001 carry 0.002 AED, ACC-002 carry 0. `test_carry_not_a_ledger_amount` |
| back-value limit | none | Not chosen: any value day from Day 1 is accepted. This is a gap, not a decision. | — |

## Given by the brief

| Constant | Value | Half | Double |
|---|---|---|---|
| `overdraft_fee` (AED) | 25.00 | 12.50: the same three fee days; Day 5 as known −372.50 | 50.00: a fourth fee, on Day 3 (check −20.00); Day 5 as known −535.00 |
| `daily_interest_rate` | 0.0004 | 0.0002: total 0.40, final 285.40 AED, 10.004 BHD | 0.0008: total 1.60, final 286.60 AED, 10.016 BHD |
| `window_days` | 6 | — | — |
| AED scale | 2 | — | — |
| BHD scale | 3 | — | — |

- The fee changes the fee days only above 30.00. Day 3 before its own fee is
  30.00 − fee: at 30.00 it is 0.00, no fee; at 30.01 it is −0.01, a fee.
- The scales are the ISO 4217 minor units. They are not a choice.
- The window is the brief's Day 1 to Day 6. Capitalization runs at its last close.
- No BHD overdraft fee is configured. See [AMBIGUITIES.md](AMBIGUITIES.md).

## Why the interest total is 0.80 and not 0.79

ACC-001 exact interest is 0.802. Daily accruals with carry: 0.10, 0.10, 0.26, 0.11,
0.12, 0.11 = 0.80. Each day is rounded after the carry is added, so the total stays
within half a minor unit of the exact value.

Rounding each day on its own and adding the results gives 0.79 here: it loses 0.012.
That error grows with the number of days. `test_acc_001_accruals`
