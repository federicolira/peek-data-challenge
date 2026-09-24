-- The funnel this dataset CAN support: a customer-lifecycle funnel at user level.
--
-- Stages (each a subset of the one before):
--   1. signed_up         users.created_at, account at least 365 days old
--   2. placed_order      any order, any status
--   3. activated         first COMPLETED order (the brief's "user activation")
--   4. second_order      ACTIVATED and a second valid order (not Cancelled / Returned).
--                        Conditioning on stage 3 keeps the funnel nested: an earlier draft
--                        counted any user with 2+ valid orders, which let a customer whose
--                        orders were all 'Shipped' reach stage 4 without passing stage 3.
--
-- Why user level and not session level: see j_events_funnel.sql.
-- Why accounts >= 365 days old: every stage then has at least a year to happen,
-- so the stage-to-stage rates are comparable across users.
WITH u AS (
  SELECT id AS user_id, traffic_source
  FROM `bigquery-public-data.thelook_ecommerce.users`
  WHERE DATE(created_at) <= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
),
per_user AS (
  SELECT
    user_id,
    COUNT(DISTINCT order_id)                                              AS any_orders,
    COUNT(DISTINCT IF(status = 'Complete' AND returned_at IS NULL, order_id, NULL)) AS completed_orders,
    COUNT(DISTINCT IF(status NOT IN ('Cancelled', 'Returned'), order_id, NULL))     AS valid_orders
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
  WHERE DATE(created_at) <= CURRENT_DATE()
  GROUP BY user_id
),
j AS (
  SELECT u.traffic_source,
         COALESCE(p.any_orders, 0)       AS any_orders,
         COALESCE(p.completed_orders, 0) AS completed_orders,
         COALESCE(p.valid_orders, 0)     AS valid_orders
  FROM u LEFT JOIN per_user AS p USING (user_id)
)
SELECT
  COALESCE(traffic_source, 'ALL')                                        AS segment,
  COUNT(*)                                                               AS signed_up,
  COUNTIF(any_orders >= 1)                                               AS placed_order,
  COUNTIF(completed_orders >= 1)                                         AS activated,
  COUNTIF(completed_orders >= 1 AND valid_orders >= 2)                   AS second_order,
  ROUND(100 * COUNTIF(any_orders >= 1) / COUNT(*), 1)                    AS signup_to_order_pct,
  ROUND(100 * SAFE_DIVIDE(COUNTIF(completed_orders >= 1),
                          COUNTIF(any_orders >= 1)), 1)                  AS order_to_activated_pct,
  ROUND(100 * SAFE_DIVIDE(COUNTIF(completed_orders >= 1 AND valid_orders >= 2),
                          COUNTIF(completed_orders >= 1)), 1)            AS activated_to_repeat_pct
FROM j
GROUP BY ROLLUP (traffic_source)
ORDER BY signed_up DESC
