-- Generated from sql/part1_queries.sql by run_all.py - edit that file, not this one.

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
