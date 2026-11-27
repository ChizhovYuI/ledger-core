#set document(title: "ledger-core: architecture and trade-offs", author: "Iurii Chizhov")
#set page(paper: "a4", margin: (x: 1.8cm, y: 1.6cm), numbering: "1 / 1")
#set text(font: "New Computer Modern", size: 10pt)
#set par(justify: true, leading: 0.55em, spacing: 0.75em)
#set heading(numbering: "1.")
#show heading.where(level: 1): set text(size: 12pt)
#show heading: set block(above: 1.0em, below: 0.55em)
#show raw: set text(size: 9pt)
#set table(inset: (x: 4pt, y: 3pt), stroke: 0.4pt + luma(160))
#show table: set text(size: 9pt)
#show table: set par(justify: false)

#align(center)[
  #text(size: 15pt, weight: "bold")[ledger-core: architecture and trade-offs] \
  #v(0.15em)
  Part 2 of the assessment · Iurii Chizhov · repository `ChizhovYuI/ledger-core`
]

Each claim is about the code in this repository at the commit of this file, or cites a
source from the list at the end. Day numbers are integers, as in the brief.

= Append-only at scale

*What breaks first: the balance query.* No balance is stored. `Journal.balance`
(`ledger/journal.py:186`) reads every posting of the journal for each call. The day
close (`close_day`, `ledger/close.py:42`) calls it once per account per checked day, and
`_check_day` reads the full journal two more times to find fees and refunds. A backdated
posting makes the close check each day from its value day again, and nothing limits how
far back that value day is. So the cost of one close is _accounts × checked days ×
journal size_. At 100× volume the journal is 100× larger and the account count also
grows: the close becomes quadratic.

`make timing` (`scripts/timing.py`) builds a journal over 100 accounts, adds one posting
booked on the last day and valued 30 days back, and times one balance call and one close. Best of 5 runs, Python
3.14.6, Apple M4 Pro. The numbers show the growth, not a capacity:

#align(center, table(
  columns: 3,
  align: (right, right, right),
  table.header([*postings*], [*one balance, ms*], [*one close, ms*]),
  [5,000 (1×)], [0.58], [90.7],
  [500,000 (100×)], [66.1], [10,958.1],
))

For 100× postings, the balance call grows 114× and the close 121×. Here the close makes 130
fee checks: 31 days for the account with the backdated posting, 1 day for each other
account. With 100× accounts it makes about 10,030 checks, 77× more, each on a 100× larger
journal. That is near 14 minutes for one close (an estimate, not a run).

*Unbounded state.* All in memory, and nothing is ever removed: the posting list and the
posting-id set (`Journal`); the event and outcome lists; the idempotency map
(`Ledger._first`, `ledger/processor.py:78`), whose keys never expire; the hold-change log
(`HoldBook`); the authorization map; the capitalization records. The journal must stay
append-only (records are kept and not erased, see section 2), so the fix is not to delete
but to stop reading all of it.

*Cheapest structural change: a balance checkpoint per account and closed value day.* A
balance query becomes the newest checkpoint at or before the value day, plus the
postings of that account after it. Index the postings by account, so that a close reads
only the account it checks. A backdated posting makes the checkpoints from its value day
forward stale; the close recomputes them from the last good one. This is the snapshot
and replay of Fowler's "Retroactive Event", and the recalculation "from that day to the
present" that Pismo describes. The control of section 2 limits how far back a posting
can go. So it also limits how many checkpoints one posting can make stale. Next steps,
in order of cost:
- Partition the journal by account. One account's close then never reads another's.
- Seal closed periods and move them to cold storage (Uber LedgerStore).
- Give idempotency keys an expiry window. Make it longer than the longest valid
  redelivery.

= Value-dated entries in production

A value-dated ledger lets an entry change the past balance of a day that is already
closed. Each such change reaches a customer, a regulator or a reconciliation:

- *Fees on closed days.* A backdated debit makes fees on days that closed with a
  positive balance; a reversal removes them. If the cause was the bank's own error, the
  refund "must be paid to the Consumer immediately", and the bank "must not benefit from
  any amounts due to their Error or omission" (CPS 5.1.1.38, 5.1.1.40). This code refunds
  at the next day close, not at the reversal, and it does not restore interest lost
  after capitalization (section 4).
- *No UAE rule on value dates.* No Central Bank rule was found that governs the value
  date of customer entries or backdating. The EU rule is the contrast: the debit value
  date must be "no earlier than the time at which the amount of the payment transaction
  is debited" (PSD2 Art. 87(3)). The US CFPB calls overdraft fees "on transactions that a
  consumer would not reasonably anticipate" likely unfair (Circular 2022-06). A fee for
  Day 2 that first appears on Day 5 is such a fee.
- *Statements and fee limits.* A statement must show a breakdown of all fees by amount
  and type (CPS 2.1.2.9); a fee and its refund are two lines. Fees must not exceed the
  Central Bank's maximum limits (CPS 5.1.1.20). No fee-cap line was found for a per-day
  fee on a negative balance. The rule also makes a fee on a fee (section 4).
- *Records.* Records "must be securely retained for a minimum of 5 years" (CPS
  6.1.6.1). Append-only fits. The journal must be durable, not in memory.
- *Reconciliation.* The operational risk regulation asks for regular reconciliation of
  transactions and accounts (C 1/2026 Art. 7.4.7). The zero-sum check does not find a
  posting to the wrong account. `card_settlement` must match the scheme settlement, and
  `external` the payment rails, each day.
- *Complaints.* Acknowledge in 2 business days, answer in 30 (CPS 8.1.3.6-7). The two
  closes per day (as known, restated) let an agent show what the bank knew on each day.
- *Islamic banking.* The brief's interest rule is applied as given. For Shari'ah-compliant
  financing, late payment fees or the charity commitment "must be based on an
  administrative cost" (CPS 2.1.3.12(b)); profit is distributed "between the IFIs
  (shareholders) and investment accountholders" (CPS 11.1.1.3). The author has no
  Islamic-banking experience; the product mapping is not attempted.

*The one control: a back-value limit with four-eyes approval over the limit.* A posting
with a value day earlier than its booked day minus N is not posted automatically. It
waits in a queue; a second person approves it; then it posts and the recheck runs. Core
banking products already have this setting: "Back Value Limit Days" in Oracle Banking
Payments, back-value days in Pismo. The Central Bank asks for "four-eyes" dual control
(Internal Controls Standards Art. 2(2)(c)). N = 10 days, the same as the hold
expiry (section 3). It is the bank's policy, not a rule. Cost: a 30-day lodging or
vehicle-rental clearing goes to the queue. Inside N a wrong entry still posts;
reconciliation and the refund rule above catch it. The control also limits the recheck
range and the checkpoint invalidation of section 1. It is not in the code.

= Authorization lifecycle

An authorization in this model is a hold, not a posting. `AuthState`
(`ledger/processor.py:26`) has `active`, `declined`, `settled`, `expired` and
`unmatched`; a settlement can carry a flag. Every end other than a matching settlement:

#table(
  columns: (1.25fr, 2fr, 2.6fr, 1.7fr),
  table.header([*End*], [*Real scenario*], [*Mandated behaviour*], [*In the code*]),
  [Declined], [Not enough available balance.],
  [No hold. Code 51 permits a retry (Visa Table 7-2); a sale completed after a decline is
   dispute 11.2.],
  [Yes: `declined`. Kept after its cause is reversed (the red test).],
  [Expired, never settled], [Cancelled sale; the merchant never clears.],
  [Release the hold after N days. Approval validity is 5 days card-present, 10
   card-absent, 30 lodging or rental (Table 5-11); the merchant must reverse within 24 h
   of its end (Table 5-13). No issuer deadline was found: N is policy.],
  [Yes: `expired` at the close, after `hold_expiry_days` = 10.],
  [Settled for less], [Final amount lower than the estimate.],
  [Post the final amount; release the full hold at once (as PSD2 Art. 75(2) requires in
   the EU).],
  [Yes: full release.],
  [Settled over the hold], [Tip, lodging extras.],
  [Post within the scheme tolerance (up to 15-20%, Table 7-10); over it, an exception.],
  [Posts with `over_hold`; no tolerance check.],
  [Settled twice], [Split shipment.],
  [Post each clearing with its Multiple Clearing Sequence Number (ID#0027756).],
  [Posts with `after_settlement`; no sequence number.],
  [Settled after expiry], [Late presentment.],
  [Post: the issuer must pay (ID#0006558). Dispute 11.3 if outside the validity period
   (Table 11-47).],
  [Posts with `after_expiry`. Can make an overdraft and a fee.],
  [No authorization (unmatched)], [Floor limit, deferred or in-transit authorization
   (§5.7.3.4), or an error.],
  [Post; open dispute 11.3 within 75 days (ID#0030270, Table 11-50). It needs the account
   flagged Credit Problem, Closed or Fraud (Table 11-51), so the money may not return.],
  [Posts with `unmatched` and an alert. No dispute record, no suspense.],
  [Settlement reversed], [Duplicate or wrong clearing.],
  [Reverse on receipt of the reversal information (ID#0008879).],
  [Money reversed; the state still reads `settled` or `unmatched`.],
)

*Ends the model does not have.* (1) Merchant reversal of an authorization. The rule:
"An Issuer must reverse an authorized Transaction from its Cardholder's account upon
receipt of a Reversal" (ID#0004383). The code rejects a reversal of an authorization
(`target_is_authorization`); the hold waits for expiry. Mandate: release at once. (2)
Incremental and partial approval: one authorization has one amount. (3) Stand-in
processing: "An Issuer is responsible for any Transaction approved or declined by
Stand-In Processing (STIP)" (ID#0004386). The ledger must post a decision that it did
not make. It must do this also when the balance is too low.

= What I cut and why

#table(
  columns: (2.1fr, 3fr),
  table.header([*Cut*], [*Production risk it defers*]),
  [No suspense account. An unmatched settlement debits the customer.],
  [The customer pays for the issuer's dispute while it runs, and can get an overdraft
   fee for it. Production: post to suspense, decide, then move.],
  [Interest is final at capitalization. No daily accrual postings.],
  [A late correction restates fees, not interest. Code run: the stream with the
   reversal on Day 7 gives four fees, all refunded, but interest 0.10 and final
   285.10 AED, not 285.80. The BHD account also loses its 0.008.],
  [Minimal double entry: four internal accounts, no chart of accounts.],
  [The zero-sum check does not find a wrong account or a wrong amount on both legs. The
   zero-sum property test cannot fail: `Posting` rejects unbalanced legs when it is
   made. Reconciliation is the real check.],
  [One hold expiry for all channels, no channel field.],
  [Card-present holds stay 5 days too long; 30-day lodging holds are released early, so
   the late clearing posts after expiry and can make an overdraft and a fee.],
  [Decisions are not linked to the data they used.],
  [After a reversal the money returns, the decision does not: a decline made on a
   wrong balance keeps no mark. `tests/test_known_gap.py` fails on this.],
  [The fee rule as given: no cap, no grace amount.],
  [Fee on a fee: a 1.00 debit on Day 1, paid back on Day 2, still gives six fees, 150.00
   by Day 6. After Day 1, only the fees keep the balance negative.],
  [No back-value limit in code.], [Any value day from Day 1 posts and rechecks all days since.],
  [No debit check against the balance; fee limits not enforced.],
  [A debit can make any overdraft. A fee table change is not checked against the
   Central Bank limits.],
  [Integer days; no time zone, cut-off time or business calendar.],
  [Cannot say which day a 23:59 event belongs to; weekends and holidays are not modelled.],
  [No FX; the fee exists for AED only.], [A negative BHD balance gets an alert, not a fee.],
  [In memory, one thread, no persistence.],
  [A restart loses everything. No locking: two writers on one account would race.],
  [Known code limits.],
  [A very large booked day makes the replay close each day up to it, so the run does not
   end. An amount near the `decimal` limit is accepted, then the close stops with
   `AmountPrecisionError`.],
)

#v(0.4em)
#line(length: 100%, stroke: 0.4pt + luma(160))
#text(size: 8.5pt)[
  *Sources.* Visa Core Rules and Visa Product and Service Rules, 24 October 2026 (rule IDs
  and tables as cited). CBUAE Consumer Protection Standards (N 1158/2021) 2.1.2.9,
  2.1.3.12(b), 5.1.1.20, 5.1.1.38, 5.1.1.40, 6.1.6.1, 8.1.3.6-7, 11.1.1.3. CBUAE Internal
  Controls, Compliance and Internal Audit Standards (C 161/2018) Art. 2(2)(c). CBUAE
  Operational Risk Management Regulation (C 1/2026) Art. 7.4.7. EU Directive
  2015/2366 (PSD2) Art. 75(2), 87(3). CFPB Circular 2022-06. Oracle Banking Payments 14.8,
  "Back Value Limit Days". Pismo, "Back-value dated transactions". M. Fowler, "Retroactive
  Event", 2005. Uber Engineering, "How LedgerStore Supports Trillions of Indexes", 2024.
]
