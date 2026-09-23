# Peek — Product & BI Analyst Data Challenge

Federico Lira · September 2026
Dataset: `bigquery-public-data.thelook_ecommerce` · BigQuery Standard SQL

---

## TL;DR — the one thing leadership should know

**This business grows entirely by acquisition. Retention is effectively zero.**

Three independent analyses say the same thing, which is why I believe it:

| evidence | number |
|---|---|
| Share of monthly revenue from **returning** customers | **12–21%** |
| 90-day churn rate (last 12 measurable months) | **94.2%** |
| Cohort retention, month 1 after first purchase | **~3%**, flattening to ~1% |

Revenue is up and to the right — $46K/mo in Jul 2025 to $115K/mo in Aug 2026, +150% in 14
months. Every dollar of that growth is a new customer. The repeat business is a rounding
error.

That is a fragile shape. Revenue is a direct function of acquisition volume, so the day
acquisition cost rises or a channel saturates, revenue stops — there is no installed base
underneath to carry it.

And the upside is unusually cheap: **returning customers already spend more per head than
new ones** ($89.24 vs $79.65 in Aug 2026, +12%). The business is not failing to monetize
repeat customers. It is failing to produce them.

---

## Date ranges, and why

**Analysis window: 2019-01 through 2026-08.** Both ends are derived in SQL, never
hard-coded — see any `params` CTE.

The dataset does not simply "end", and two separate things go wrong at the boundary. QA.1
measures both:

```
first_date         2019-01-10
last_date          2026-09-27   <- four days in the future
max_observable     2026-09-23
partial_month      2026-09-01
future_dated_rows  1,154
```

1. **September 2026 is partial.** Reporting it beside complete months manufactures a
   collapse. Guard: exclude the current month.
2. **1,154 rows are dated later than today.** theLook is continuously generated, and the
   generator emits forward-dated rows. Nobody bought anything next Friday. Guard: cap every
   window at `LEAST(DATE(MAX(created_at)), CURRENT_DATE())`.

The second guard is the one that matters, because it survives the first: a future-dated row
can sit inside a month that is otherwise complete, where a "drop the last month" rule never
sees it.

---

## Definitions

Per the brief, restated here so every number is auditable.

| term | definition used |
|---|---|
| Completed sale | `order_items.status = 'Complete' AND returned_at IS NULL` |
| Revenue | `SUM(order_items.sale_price)` |
| COGS | `SUM(inventory_items.cost)` over the same line items |
| Gross profit | Revenue − COGS |
| Month | `DATE_TRUNC(DATE(order_items.created_at), MONTH)` |
| Order | `COUNT(DISTINCT order_id)` |
| Active customer | ≥1 completed order in the month |
| New customer | first-ever completed order falls in that month |
| Returning customer | active, and first purchase was in an earlier month |
| 90-day churn | active in month M, no completed order in the 90 days after M ends |

### Grain — the decision everything else rests on

`order_items` is **one row per line item, not per order.** Revenue and units aggregate at
that grain; orders and customers need `DISTINCT`. `inventory_items` joins 1:1 on
`inventory_item_id` — QA.2 proves it (45,373 rows before and after) — but `users` and
`products` would fan out, so those joins happen only after the order-level rollup.

### What the 'Complete' filter costs — measured, not assumed

QA.3 breaks revenue out by status:

| status | line items | revenue |
|---|---|---|
| Shipped | 54,731 | $3,282,437 |
| **Complete** | **45,373** | **$2,702,312** |
| Processing | 36,028 | $2,153,356 |
| Cancelled | 27,154 | $1,618,599 |
| Returned | 18,129 | $1,071,383 |

The brief's definition keeps **25% of line items**, and `Shipped` alone carries *more*
revenue than `Complete`. I use the brief's definition throughout, but every figure in this
repo is a quarter of gross merchandise flow, not the whole of it. In a real setting I would
report both and let finance pick the revenue-recognition point.

One detail I checked rather than assumed: the statuses are mutually exclusive, and only
`Returned` carries a non-null `returned_at`. So `AND returned_at IS NULL` adds nothing on
top of `status = 'Complete'` **in this dataset**. I kept it for fidelity to the brief, and
because it would matter the moment the upstream system allowed a returned-but-complete row.

### Alternative definitions I considered

- **New vs returning.** I used cohort-consistent: a customer is new exactly once, ever, so
  `new + returning = active` in every month (QA.4 asserts this). The common alternative —
  "returning = purchased in the last 12 months" — is better when the question is
  *reactivation* rather than *acquisition*, but it does not sum to active: a customer
  returning after 18 months is neither new nor recently-returning.
- **Churn.** A 90-day no-purchase window suits a business with a ~monthly cadence. For
  a lower-frequency catalogue it flags healthy customers as churned. Alternatives: a window
  derived from each customer's own observed interpurchase gap, or a survival model that
  yields a churn *probability* rather than a binary label.

---

## Limitation of the 90-day churn definition

**Churn for month M cannot be observed until 90 days after M ends.** Any month whose window
extends past the data is not measurable — and computing it anyway does not fail, it returns
a confident wrong answer: every customer looks churned because no window exists in which
they could have returned.

The output makes this concrete. August 2026 reports **churn = 100.0%** on 1,415 active
customers. That is not a churn event; it is the edge of the dataset wearing a crisis costume.

| month | active | churned | churn % | measurable |
|---|---|---|---|---|
| 2026-05 | 991 | 922 | 93.0% | **yes — last measurable** |
| 2026-06 | 1,102 | 1,035 | 93.9% | no |
| 2026-07 | 1,261 | 1,194 | 94.7% | no |
| 2026-08 | 1,415 | 1,415 | **100.0%** | no |

Task C therefore emits a `measurable` boolean rather than silently leaving the trap in
place. **89 of 92 months are measurable; the last measurable month is May 2026.**

**How I would refine it in a real product setting:** replace the fixed 90-day window with a
per-customer threshold derived from that customer's own purchase cadence (e.g. churned if
the gap exceeds the 90th percentile of their historical interpurchase time), and report
churn as a probability from a survival model so that the most recent cohorts contribute
censored observations instead of being dropped. That recovers the three months a fixed
window throws away, which for a fast-growing business are the three months you most want.

---

## Task D — free shipping over $100 (hypothetical, 2022-01-15)

The policy is not in the data: no `shipping_fee` column, no treatment flag. So nothing here
measures it. What the SQL does is lay out the structure I would use, and be explicit about
why the obvious approach misleads.

**Why pre/post alone fails here.** The business grows month over month throughout. A
before/after window will show a "lift" whether or not any policy ran, because it attributes
to the policy everything else that happened that January — seasonality, the post-holiday
trough, marketing, and the platform's own growth.

**The structure that works: difference-in-differences.** Orders already ≥$100 would have
been eligible (treated); orders <$100 would not (control). Comparing how the *gap* between
the groups changes across the date removes anything that moved both groups together.

±90 days around 2022-01-15:

| cohort | period | orders | AOV | gross margin |
|---|---|---|---|---|
| control <$100 | pre | 349 | $45.82 | 50.9% |
| control <$100 | post | 368 | $43.07 | 51.5% |
| treated ≥$100 | pre | 121 | $199.26 | 52.9% |
| treated ≥$100 | post | 152 | $198.33 | 53.0% |

Order growth: +25.6% treated vs +5.4% control — a +20pp difference-in-differences.

**I do not believe that number, and neither should the reader.** The treated group has 121
and 152 orders. That window holds ~990 completed orders in total, which is nowhere near
enough power to separate a policy effect from noise; a ±20pp swing is well within what this
sample produces by chance. The design is right and the data cannot carry it. Reporting the
+20pp as a finding would be the actual error here.

**Two assumptions, stated because they are load-bearing:**
1. Orders ≥$100 proxy for "would have been eligible". This proxy leaks by construction —
   the entire purpose of the policy is to push orders from below the threshold to above it,
   so the groups are not stable across the date. That contamination biases the estimate
   toward finding an effect.
2. Basket composition and shipping cost structure are otherwise unchanged across the window.

**What I would need to do this properly:** a `shipping_fee` per order, a treatment flag or
a staged rollout to give a genuine control group, cart-abandonment events (the policy should
move abandonment before it moves AOV), margin net of shipping cost — free shipping can lift
revenue while destroying contribution margin — and a pre-registered minimum detectable
effect so the sample size question is settled before the analysis, not after.

---

## Repo contents

```
sql/
  part1_queries.sql          all four tasks + stretch + QA, commented, the deliverable
  tasks/                     the same queries split one per file, for running
analysis/                    visuals and findings
data/                        query outputs as CSV (small, reproducible)
run_query.py                 runs a .sql file against BigQuery, saves CSV
```

### How to run

```bash
gcloud auth login
gcloud config set project <your-project>
python run_query.py sql/tasks/a_monthly_financials.sql data/a_monthly_financials.csv
```

`run_query.py` mints a short-lived OAuth token via gcloud and calls the BigQuery REST API.
**No service account key is created, stored, or committed** — `.gitignore` blocks `*.json`,
`.env` and anything matching `service-account*`. Every query is also runnable by pasting it
straight into the BigQuery console.

Cost: the full set scans roughly 50 MB, far inside the 1 TB/month free tier.

---

## Part 3 — How I used AI on this challenge

I used Claude Code as a pair, not as an oracle. Concretely:

- **Schema and boundary reconnaissance first.** Before writing a line of analysis I had it
  run the QA queries. That is where the 1,154 future-dated rows and the 75%-of-revenue-
  outside-`Complete` finding came from — neither was in the brief.
- **Drafting the SQL**, then arguing about the definitions. The cohort-consistent new/
  returning definition and the `measurable` flag on churn both came out of that argument.
- **Catching my own bug.** An earlier draft joined a slowly-changing dimension with
  `BETWEEN`, which includes both endpoints, and silently duplicated rows on the boundary
  date. The row-count check caught it. I would not have seen it by reading the query.

**An example prompt I used:**

> "Here is my Task C churn query. The last three months return a churn rate near 100%.
> Before assuming that is real: what in the data boundary could produce that artifact, and
> write me the check that would distinguish an artifact from a genuine churn spike."

Note the shape — I did not ask "fix my query." I asked for *the check that would tell me
which explanation is true*. An LLM asked to fix something will fix something, whether or not
it was broken.

**How I validate rather than trust:**

1. **Row counts before and after every join.** If they change without my deciding so, the
   join is duplicating or dropping data. This is one line of SQL and it catches the class of
   error nobody notices until finance disagrees with the dashboard.
2. **Identity assertions.** QA.4 asserts `new + returning = active` in every month and
   returns rows only when that is violated. A test that returns nothing is a passing test.
3. **Reconcile against a known total.** Every task's revenue has to tie back to the QA.3
   status breakdown.
4. **Treat anything suspiciously clean as a bug until proven otherwise.** A churn rate of
   exactly 100.0% is not a finding, it is a symptom.

The general rule I applied: **an LLM is fast at producing plausible SQL and has no way to
know whether the answer is true.** Everything it generated here had to survive a check that
could have failed. The QA section of `part1_queries.sql` is that audit trail, and it is in
the repo on purpose.

---

## Recommendation

**The problem is not monetization, it is that repeat customers barely exist.** Returning
customers already out-spend new ones by 12% per head. The lever is producing more of them,
not extracting more from them.

**What I would do:** a post-purchase lifecycle program targeted at the 30-day window after
first delivery, where the cohort curves show the drop-off is already complete by month 1.
Target first-time buyers in the highest-AOV acquisition channels first — they have the most
headroom and the lowest marginal cost to reach.

**How I would measure it:**
- *Primary:* month-1 repeat purchase rate for the treated cohort vs a holdout. It sits at
  ~3% today, and it is the number the whole thesis rests on.
- *Secondary:* 90-day churn for the treated cohort; share of monthly revenue from returning
  customers (12–21% today); AOV of second orders, to confirm we are not buying repeat
  purchases with discounts that destroy the margin advantage repeat customers already have.
- *Guardrail:* contribution margin per customer, so a lift in repeat rate that costs more
  than it earns shows up immediately rather than at the end of the quarter.
