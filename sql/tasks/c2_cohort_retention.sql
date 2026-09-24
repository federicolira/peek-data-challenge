-- Generated from sql/part1_queries.sql by run_all.py - edit that file, not this one.

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
