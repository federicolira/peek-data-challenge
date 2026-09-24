-- Generated from sql/part1_queries.sql by run_all.py - edit that file, not this one.

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
--    QA.1 and it reports:
--
--                         run on 2026-09-23    run on 2026-09-24 (UTC)
--        first_date       2019-01-10           2019-01-10
--        last_date        2026-09-27           2026-09-27   <- in the future
--        partial_month    2026-09-01           2026-09-01
--        future rows      1,154                632
--
--    The future-row count shrinks every day as "today" catches up with rows
--    the generator dated ahead of time — which is itself the proof that they
--    are not real sales. data/_as_of.csv records the date the checked-in
--    outputs were produced (run_all.py regenerates them in one pass).
--
--    Two separate problems, and they need two separate guards:
--
--    1. The current month is partial. Reporting Sep 2026 beside complete
--       months manufactures a collapse. Guard: exclude the current month.
--
--    2. Hundreds of rows carry a created_at LATER THAN TODAY. They cannot be
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
  -- rows (632 of them on 2026-09-24; see the header). A sale dated next week is not
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
