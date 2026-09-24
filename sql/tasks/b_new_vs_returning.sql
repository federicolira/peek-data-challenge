-- Generated from sql/part1_queries.sql by run_all.py - edit that file, not this one.

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
