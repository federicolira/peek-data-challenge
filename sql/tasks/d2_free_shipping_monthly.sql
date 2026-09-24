-- Generated from sql/part1_queries.sql by run_all.py - edit that file, not this one.

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

-- GRAIN: one row per MONTH, with the two cohorts as columns.
-- An earlier version grouped by (month, cohort) and computed the share of
-- orders over the threshold inside each cohort — which is 100% for the
-- treated cohort and 0% for the control BY DEFINITION. The share only
-- means something across all orders of the month, so the grain is the month.
SELECT
  DATE_TRUNC(o.order_date, MONTH)                                        AS month,
  IF(DATE_TRUNC(o.order_date, MONTH) >= DATE_TRUNC(p.launch_date, MONTH),
     'post', 'pre')                                                      AS period,
  COUNT(*)                                                               AS orders,
  COUNTIF(o.order_revenue >= p.free_shipping_threshold)                  AS orders_ge_100,
  -- the metric the policy is actually designed to move
  ROUND(SAFE_DIVIDE(COUNTIF(o.order_revenue >= p.free_shipping_threshold),
                    NULLIF(COUNT(*), 0)) * 100, 2)                       AS pct_orders_over_threshold,
  ROUND(SUM(o.order_revenue), 2)                                         AS revenue,
  ROUND(AVG(o.order_revenue), 2)                                         AS aov,
  ROUND(AVG(IF(o.order_revenue >= p.free_shipping_threshold,
               o.order_revenue, NULL)), 2)                               AS aov_ge_100,
  ROUND(AVG(IF(o.order_revenue <  p.free_shipping_threshold,
               o.order_revenue, NULL)), 2)                               AS aov_lt_100,
  ROUND(SUM(o.order_revenue) - SUM(o.order_cogs), 2)                     AS gross_profit
FROM order_level AS o
CROSS JOIN params AS p
WHERE o.order_date BETWEEN DATE_SUB(p.launch_date, INTERVAL 12 MONTH)
                       AND DATE_ADD(p.launch_date, INTERVAL 12 MONTH)
GROUP BY month, period
ORDER BY month;
