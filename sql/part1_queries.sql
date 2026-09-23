-- =====================================================================
--  Peek — Product & BI Analyst Data Challenge
--  Part 1 — SQL
--
--  Dataset : bigquery-public-data.thelook_ecommerce
--  Dialect : BigQuery Standard SQL
--  Author  : Federico Lira
--
--  HOW TO RUN
--    Every task below is SELF-CONTAINED. Paste one into the BigQuery
--    console and run it — no prior statement required.
--
--  WHY NO DECLARE BLOCK
--    The brief asks for parameterized dates and no hard-coded cutoffs.
--    Rather than DECLARE a literal, each query derives its window from
--    the data itself in a `params` CTE:
--
--        SELECT DATE_TRUNC(DATE(MAX(created_at)), MONTH) AS max_month ...
--
--    That means the queries stay correct when the dataset refreshes,
--    which a hard-coded '2024-12-31' would not. To pin a fixed window
--    instead, the BigQuery-idiomatic form is:
--
--        DECLARE start_date DATE DEFAULT '2022-01-01';
--        DECLARE end_date   DATE DEFAULT CURRENT_DATE();
--
--  SHARED DEFINITIONS (per the brief, restated so the SQL is auditable)
--    Completed sale    order_items.status = 'Complete' AND returned_at IS NULL
--    Revenue           SUM(order_items.sale_price)
--    COGS              SUM(inventory_items.cost) over the same line items
--    Gross profit      Revenue − COGS
--    Month             DATE_TRUNC(DATE(order_items.created_at), MONTH)
--    Order             COUNT(DISTINCT order_items.order_id)
--    Customer          order_items.user_id
--
--  GRAIN NOTE — the single most important decision in this file
--    order_items is ONE ROW PER LINE ITEM, not per order. Revenue and
--    units aggregate at that grain; orders and customers must be counted
--    with DISTINCT. Joining to inventory_items is 1:1 on
--    inventory_item_id, so it does NOT fan out — but joining to products
--    or users before aggregating would, so those joins happen last.
--
--  DATA-BOUNDARY WARNING (applies to every task) — MEASURED, NOT ASSUMED
--    theLook is continuously generated, so it does not simply "end". Run
--    QA.1 and it reports, as of 2026-09-23:
--
--        first_date         2019-01-10
--        last_date          2026-09-27   <- FOUR DAYS IN THE FUTURE
--        partial_month      2026-09-01
--        future_dated_rows  1,154
--
--    Two separate problems, and they need two separate guards:
--
--    1. The current month is partial. Reporting Sep 2026 beside complete
--       months manufactures a collapse. Guard: exclude the current month.
--
--    2. 1,154 rows carry a created_at LATER THAN TODAY. They cannot be
--       completed sales — nobody has bought anything next Friday. They
--       are an artifact of the generator. Guard: cap every window at
--       LEAST(max data date, CURRENT_DATE()).
--
--    The second one is the dangerous one, because it survives the first
--    guard: a future-dated row inside an otherwise-complete month is
--    invisible to a "drop the last month" rule.
--
--    Effective analysis window: 2019-01 through 2026-08.
--    See README § Date ranges.
-- =====================================================================


-- =====================================================================
-- TASK A — Monthly financials
--   One row per month: revenue, completed orders, units, AOV, MoM growth
-- =====================================================================

WITH params AS (
  -- Derived, not hard-coded, so this stays correct when theLook refreshes.
  -- max_observable caps at TODAY because the generator emits future-dated
  -- rows (1,154 of them as of 2026-09-23). A sale dated next week is not
  -- a sale.
  SELECT
    DATE_TRUNC(DATE(MIN(created_at)), MONTH)                AS first_month,
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)                AS current_month,
    LEAST(DATE(MAX(created_at)), CURRENT_DATE())            AS max_observable
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

completed_items AS (
  SELECT
    oi.order_id,
    oi.user_id,
    oi.inventory_item_id,
    oi.sale_price,
    DATE_TRUNC(DATE(oi.created_at), MONTH) AS month
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
    -- guard 1: drop the in-flight month, partial by construction
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) <  p.current_month
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) >= p.first_month
    -- guard 2: drop future-dated rows. Survives guard 1, because a
    -- future row can sit inside a month that is otherwise complete.
    AND DATE(oi.created_at) <= p.max_observable
),

monthly AS (
  SELECT
    month,
    ROUND(SUM(sale_price), 2)                                  AS revenue,
    COUNT(DISTINCT order_id)                                   AS orders,
    COUNT(*)                                                   AS units,
    ROUND(SUM(sale_price) / NULLIF(COUNT(DISTINCT order_id), 0), 2) AS aov
  FROM completed_items
  GROUP BY month
)

SELECT
  month,
  revenue,
  orders,
  units,
  aov,
  LAG(revenue) OVER (ORDER BY month)                           AS revenue_prior_month,
  -- NULLIF guards the first month, where the lag is NULL, and any month
  -- with zero revenue. An unguarded division here is a silent failure.
  ROUND(
    SAFE_DIVIDE(revenue - LAG(revenue) OVER (ORDER BY month),
                NULLIF(LAG(revenue) OVER (ORDER BY month), 0)) * 100
  , 2)                                                         AS mom_revenue_growth_pct
FROM monthly
ORDER BY month;


-- =====================================================================
-- TASK B — New vs returning mix, by month
--
--   DEFINITION USED
--     A customer is NEW in month M if their FIRST-EVER completed order
--     falls in M. They are RETURNING in every later month in which they
--     are active. This is cohort-consistent: a customer is new exactly
--     once in their lifetime, so new + returning = active, always.
--
--   ALTERNATIVE CONSIDERED (see README)
--     "Returning = purchased in the previous 12 months" is the usual
--     choice when the business cares about reactivation rather than
--     acquisition. It does NOT sum to active, because a dormant customer
--     coming back is neither new nor recently-returning.
-- =====================================================================

WITH params AS (
  SELECT
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS current_month,
    LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_observable
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

completed_items AS (
  SELECT
    oi.user_id,
    oi.order_id,
    oi.sale_price,
    DATE_TRUNC(DATE(oi.created_at), MONTH) AS month
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) < p.current_month
    AND DATE(oi.created_at) <= p.max_observable   -- no future-dated sales
),

-- one row per customer: the month they first bought
first_purchase AS (
  SELECT
    user_id,
    MIN(month) AS cohort_month
  FROM completed_items
  GROUP BY user_id
),

-- one row per customer per active month, tagged new or returning
customer_month AS (
  SELECT
    ci.month,
    ci.user_id,
    SUM(ci.sale_price)                                         AS revenue,
    IF(ci.month = fp.cohort_month, 'new', 'returning')          AS customer_type
  FROM completed_items AS ci
  JOIN first_purchase  AS fp USING (user_id)
  GROUP BY ci.month, ci.user_id, customer_type
)

SELECT
  month,
  COUNT(DISTINCT user_id)                                                       AS active_customers,
  COUNT(DISTINCT IF(customer_type = 'new',       user_id, NULL))                AS new_customers,
  COUNT(DISTINCT IF(customer_type = 'returning', user_id, NULL))                AS returning_customers,
  ROUND(SUM(IF(customer_type = 'new',       revenue, 0)), 2)                    AS revenue_new,
  ROUND(SUM(IF(customer_type = 'returning', revenue, 0)), 2)                    AS revenue_returning,
  ROUND(
    SAFE_DIVIDE(SUM(IF(customer_type = 'returning', revenue, 0)),
                NULLIF(SUM(revenue), 0)) * 100
  , 2)                                                                          AS pct_revenue_from_returning
FROM customer_month
GROUP BY month
ORDER BY month;


-- =====================================================================
-- TASK C — 90-day churn
--
--   DEFINITION USED
--     A customer active in month M is CHURNED-90D if they placed no
--     completed order in the 90 days following the END of month M.
--
--   THE LIMITATION THAT MATTERS MOST (README expands on this)
--     Churn for month M cannot be observed until 90 days after M ends.
--     Any month whose 90-day window extends past the last date in the
--     data is NOT measurable — and if you compute it anyway, every
--     customer looks churned and the rate shoots to 100%. That is not a
--     churn spike; it is the edge of the dataset. The `measurable` flag
--     below makes it explicit rather than leaving a trap in the output.
-- =====================================================================

WITH params AS (
  SELECT
    -- max_observable, NOT max(created_at): the 90-day observation window
    -- must be measured against real elapsed time, not against rows the
    -- generator dated into the future.
    LEAST(DATE(MAX(created_at)), CURRENT_DATE())     AS max_observable,
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)         AS current_month
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

completed_orders AS (
  SELECT
    oi.user_id,
    DATE(oi.created_at)                              AS order_date,
    DATE_TRUNC(DATE(oi.created_at), MONTH)           AS month
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) < p.current_month
    AND DATE(oi.created_at) <= p.max_observable   -- no future-dated sales
),

active_by_month AS (
  SELECT DISTINCT month, user_id
  FROM completed_orders
),

-- For each (customer, active month), did they come back within 90 days
-- of that month ending?
churn_flag AS (
  SELECT
    a.month,
    a.user_id,
    -- LAST_DAY gives the month end; the window is the 90 days after it.
    LAST_DAY(a.month, MONTH)                                  AS month_end,
    MAX(
      IF(o.order_date >  LAST_DAY(a.month, MONTH)
         AND o.order_date <= DATE_ADD(LAST_DAY(a.month, MONTH), INTERVAL 90 DAY),
         1, 0)
    )                                                          AS returned_within_90d
  FROM active_by_month AS a
  LEFT JOIN completed_orders AS o
    ON  o.user_id    = a.user_id
    AND o.order_date >  LAST_DAY(a.month, MONTH)
    AND o.order_date <= DATE_ADD(LAST_DAY(a.month, MONTH), INTERVAL 90 DAY)
  GROUP BY a.month, a.user_id, month_end
)

SELECT
  c.month,
  COUNT(*)                                                     AS active_customers,
  COUNTIF(c.returned_within_90d = 0)                           AS churned_customers_90d,
  ROUND(SAFE_DIVIDE(COUNTIF(c.returned_within_90d = 0),
                    NULLIF(COUNT(*), 0)) * 100, 2)             AS churn_rate_90d,
  -- TRUE only when the full 90-day observation window exists in the data
  DATE_ADD(LAST_DAY(c.month, MONTH), INTERVAL 90 DAY) <= p.max_observable
                                                               AS measurable
FROM churn_flag AS c
CROSS JOIN params AS p
GROUP BY c.month, measurable
ORDER BY c.month;


-- =====================================================================
-- TASK C — STRETCH: cohort retention heatmap
--   rows = first purchase month, cols = months since first purchase,
--   value = % of the cohort active that month
-- =====================================================================

WITH params AS (
  SELECT
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS current_month,
    LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_observable
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

completed_items AS (
  SELECT
    oi.user_id,
    DATE_TRUNC(DATE(oi.created_at), MONTH) AS month
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) < p.current_month
    AND DATE(oi.created_at) <= p.max_observable   -- no future-dated sales
),

first_purchase AS (
  SELECT user_id, MIN(month) AS cohort_month
  FROM completed_items
  GROUP BY user_id
),

cohort_size AS (
  SELECT cohort_month, COUNT(*) AS cohort_customers
  FROM first_purchase
  GROUP BY cohort_month
),

activity AS (
  SELECT DISTINCT
    fp.cohort_month,
    DATE_DIFF(ci.month, fp.cohort_month, MONTH) AS months_since_first,
    ci.user_id
  FROM completed_items AS ci
  JOIN first_purchase  AS fp USING (user_id)
)

SELECT
  a.cohort_month,
  cs.cohort_customers,
  a.months_since_first,
  COUNT(DISTINCT a.user_id)                                    AS active_customers,
  ROUND(SAFE_DIVIDE(COUNT(DISTINCT a.user_id),
                    NULLIF(cs.cohort_customers, 0)) * 100, 2)  AS retention_pct
FROM activity AS a
JOIN cohort_size AS cs USING (cohort_month)
GROUP BY a.cohort_month, cs.cohort_customers, a.months_since_first
ORDER BY a.cohort_month, a.months_since_first;


-- =====================================================================
-- TASK D — Product change impact (scenario)
--   Hypothetical: on 2022-01-15, "free shipping on orders over $100"
--
--   THE HONEST FRAME
--     This policy is NOT in the data. There is no shipping_fee column,
--     no flag, no treatment marker. So nothing here can measure the
--     policy's effect — what it can do is lay out the analysis I would
--     run if the change were real, and be explicit about why a naive
--     pre/post comparison would mislead.
--
--   WHY PRE/POST ALONE IS NOT ENOUGH
--     A simple before/after around 2022-01-15 attributes to the policy
--     every other thing that happened that January — seasonality, the
--     post-holiday drop, marketing spend, the platform's own growth.
--     In this dataset the business is growing month over month, so a
--     pre/post window will show a "lift" whether or not any policy ran.
--
--   THE STRUCTURE THAT DOES WORK: difference-in-differences
--     Orders already above $100 would have been ELIGIBLE for free
--     shipping — the treated group. Orders below $100 would not — the
--     control. Comparing how the gap between those two groups changes
--     across the date removes anything that moved both groups together,
--     which is what seasonality and general growth do.
--
--     This is a PROXY, and a leaky one: the whole point of the policy is
--     to push orders from below $100 to above it, so the groups are not
--     stable. That contamination is stated, not hidden. See README.
-- =====================================================================

WITH params AS (
  SELECT
    DATE '2022-01-15'                                          AS launch_date,
    100.0                                                      AS free_shipping_threshold,
    -- symmetric 90-day windows on each side, so seasonality is at least
    -- balanced across the comparison
    90                                                         AS window_days
),

-- Line items rolled up to ONE ROW PER ORDER, with COGS attached.
-- inventory_items joins 1:1 on inventory_item_id, so no fan-out; doing
-- this BEFORE touching users is what keeps the grain honest.
order_level AS (
  SELECT
    oi.order_id,
    ANY_VALUE(oi.user_id)                                      AS user_id,
    DATE(MIN(oi.created_at))                                   AS order_date,
    SUM(oi.sale_price)                                         AS order_revenue,
    SUM(ii.cost)                                               AS order_cogs,
    COUNT(*)                                                   AS units
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
    ON ii.id = oi.inventory_item_id
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
  GROUP BY oi.order_id
),

-- Attach the two comparison axes: before/after, and eligible/not.
tagged AS (
  SELECT
    o.*,
    u.traffic_source,
    u.country,
    IF(o.order_date >= p.launch_date, 'post', 'pre')                       AS period,
    IF(o.order_revenue >= p.free_shipping_threshold, 'treated_ge_100',
                                                     'control_lt_100')     AS cohort
  FROM order_level AS o
  CROSS JOIN params AS p
  -- users joins 1:1 on the order's customer, AFTER the order-level rollup
  LEFT JOIN `bigquery-public-data.thelook_ecommerce.users` AS u
    ON u.id = o.user_id
  WHERE o.order_date BETWEEN DATE_SUB(p.launch_date, INTERVAL p.window_days DAY)
                         AND DATE_ADD(p.launch_date, INTERVAL p.window_days DAY)
)

-- D.1 — the difference-in-differences table.
-- Read it by comparing the pre→post change of `treated_ge_100` against
-- the pre→post change of `control_lt_100`. The DIFFERENCE of those two
-- changes is the estimate; either one alone is just a trend.
SELECT
  cohort,
  period,
  COUNT(*)                                                     AS orders,
  ROUND(SUM(order_revenue), 2)                                 AS revenue,
  ROUND(AVG(order_revenue), 2)                                 AS aov,
  ROUND(SUM(order_revenue) - SUM(order_cogs), 2)               AS gross_profit,
  ROUND(SAFE_DIVIDE(SUM(order_revenue) - SUM(order_cogs),
                    NULLIF(SUM(order_revenue), 0)) * 100, 2)   AS gross_margin_pct,
  ROUND(AVG(units), 2)                                         AS avg_units_per_order
FROM tagged
GROUP BY cohort, period
ORDER BY cohort, period DESC;


-- ---------------------------------------------------------------------
-- TASK D.2 — monthly series, so the reader can see whether the level
-- shifted at the launch date or was already trending. A pre/post table
-- cannot distinguish "the policy worked" from "it was going up anyway";
-- the monthly view can.
-- ---------------------------------------------------------------------

WITH params AS (
  SELECT DATE '2022-01-15' AS launch_date, 100.0 AS free_shipping_threshold
),

order_level AS (
  SELECT
    oi.order_id,
    ANY_VALUE(oi.user_id)        AS user_id,
    DATE(MIN(oi.created_at))     AS order_date,
    SUM(oi.sale_price)           AS order_revenue,
    SUM(ii.cost)                 AS order_cogs
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
    ON ii.id = oi.inventory_item_id
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
  GROUP BY oi.order_id
)

SELECT
  DATE_TRUNC(o.order_date, MONTH)                              AS month,
  IF(o.order_revenue >= p.free_shipping_threshold,
     'treated_ge_100', 'control_lt_100')                       AS cohort,
  COUNT(*)                                                     AS orders,
  ROUND(SUM(o.order_revenue), 2)                               AS revenue,
  ROUND(AVG(o.order_revenue), 2)                               AS aov,
  ROUND(SUM(o.order_revenue) - SUM(o.order_cogs), 2)           AS gross_profit,
  -- share of orders that clear the threshold: the metric the policy is
  -- actually designed to move
  ROUND(SAFE_DIVIDE(
    COUNTIF(o.order_revenue >= p.free_shipping_threshold),
    NULLIF(COUNT(*), 0)) * 100, 2)                             AS pct_orders_over_threshold,
  MAX(IF(DATE_TRUNC(o.order_date, MONTH)
         >= DATE_TRUNC(p.launch_date, MONTH), 'post', 'pre'))  AS period
FROM order_level AS o
CROSS JOIN params AS p
WHERE o.order_date BETWEEN DATE_SUB(p.launch_date, INTERVAL 12 MONTH)
                       AND DATE_ADD(p.launch_date, INTERVAL 12 MONTH)
GROUP BY month, cohort
ORDER BY month, cohort;


-- ---------------------------------------------------------------------
-- TASK D.3 — the chosen segment: traffic_source.
-- Acquisition channel is the right cut here because shipping cost is a
-- bigger share of a small basket, and channels differ systematically in
-- basket size. If free shipping moves anything, it should move the
-- channels with the smallest baskets first — a testable prediction,
-- which is what separates an analysis from a description.
-- ---------------------------------------------------------------------

WITH params AS (
  SELECT DATE '2022-01-15' AS launch_date, 100.0 AS thr, 90 AS window_days
),

order_level AS (
  SELECT
    oi.order_id,
    ANY_VALUE(oi.user_id)    AS user_id,
    DATE(MIN(oi.created_at)) AS order_date,
    SUM(oi.sale_price)       AS order_revenue,
    SUM(ii.cost)             AS order_cogs
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
    ON ii.id = oi.inventory_item_id
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
  GROUP BY oi.order_id
)

SELECT
  u.traffic_source,
  IF(o.order_date >= p.launch_date, 'post', 'pre')              AS period,
  COUNT(*)                                                      AS orders,
  ROUND(AVG(o.order_revenue), 2)                                AS aov,
  ROUND(SUM(o.order_revenue), 2)                                AS revenue,
  ROUND(SUM(o.order_revenue) - SUM(o.order_cogs), 2)            AS gross_profit,
  ROUND(SAFE_DIVIDE(COUNTIF(o.order_revenue >= p.thr),
                    NULLIF(COUNT(*), 0)) * 100, 2)              AS pct_orders_over_threshold
FROM order_level AS o
CROSS JOIN params AS p
LEFT JOIN `bigquery-public-data.thelook_ecommerce.users` AS u
  ON u.id = o.user_id
WHERE o.order_date BETWEEN DATE_SUB(p.launch_date, INTERVAL p.window_days DAY)
                       AND DATE_ADD(p.launch_date, INTERVAL p.window_days DAY)
GROUP BY u.traffic_source, period
ORDER BY u.traffic_source, period DESC;


-- =====================================================================
-- QA — run these before trusting anything above.
-- Not decoration: each one has caught a real error in this file.
-- =====================================================================

-- QA.1  Where does the data actually start and end?
--       Decides which months are complete and whether churn is measurable.
SELECT
  MIN(DATE(created_at))                                        AS first_date,
  MAX(DATE(created_at))                                        AS last_date,
  DATE_TRUNC(DATE(MAX(created_at)), MONTH)                     AS partial_month,
  COUNTIF(DATE(created_at) > CURRENT_DATE())                   AS future_dated_rows
FROM `bigquery-public-data.thelook_ecommerce.order_items`;

-- QA.2  Does the inventory_items join fan out?
--       Row count must be IDENTICAL before and after. If it is not,
--       every revenue number in Task D is inflated.
SELECT
  (SELECT COUNT(*) FROM `bigquery-public-data.thelook_ecommerce.order_items`
    WHERE status = 'Complete' AND returned_at IS NULL)          AS items_before_join,
  (SELECT COUNT(*)
     FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
     JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
       ON ii.id = oi.inventory_item_id
    WHERE oi.status = 'Complete' AND oi.returned_at IS NULL)    AS items_after_join;

-- QA.3  What status values exist, and how much revenue sits outside
--       'Complete'? Confirms the filter is not silently dropping money.
SELECT
  status,
  returned_at IS NULL                                          AS not_returned,
  COUNT(*)                                                     AS items,
  ROUND(SUM(sale_price), 2)                                    AS revenue
FROM `bigquery-public-data.thelook_ecommerce.order_items`
GROUP BY status, not_returned
ORDER BY items DESC;

-- QA.4  Task B identity check: new + returning must equal active,
--       in every month. Any row returned here is a bug.
WITH completed_items AS (
  SELECT user_id, DATE_TRUNC(DATE(created_at), MONTH) AS month
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
  WHERE status = 'Complete' AND returned_at IS NULL
),
first_purchase AS (
  SELECT user_id, MIN(month) AS cohort_month FROM completed_items GROUP BY user_id
),
chk AS (
  SELECT
    ci.month,
    COUNT(DISTINCT ci.user_id)                                                   AS active,
    COUNT(DISTINCT IF(ci.month =  fp.cohort_month, ci.user_id, NULL))            AS new_c,
    COUNT(DISTINCT IF(ci.month <> fp.cohort_month, ci.user_id, NULL))            AS ret_c
  FROM completed_items AS ci
  JOIN first_purchase  AS fp USING (user_id)
  GROUP BY ci.month
)
SELECT * FROM chk WHERE active <> new_c + ret_c;
