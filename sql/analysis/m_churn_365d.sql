-- Recommended alternative to Task C: the same churn logic with a 365-day window,
-- sized to the observed repeat cycle (median 412 days between 1st and 2nd purchase).
-- Identical to sql/tasks/c_churn_90d.sql except for the window length.
WITH params AS (
  SELECT
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
    AND DATE(oi.created_at) <= p.max_observable
),

-- one row per customer per active month, with that month's first purchase
customer_month AS (
  SELECT user_id, month, MIN(order_date) AS first_order_in_month
  FROM completed_orders
  GROUP BY user_id, month
),

-- The customer's NEXT purchase after month M ends is simply the first order of
-- their next active month: every later active month starts after M, and within
-- it the earliest order comes first. So one LEAD() replaces a range self-join.
with_next AS (
  SELECT
    user_id,
    month,
    LEAD(first_order_in_month) OVER (PARTITION BY user_id ORDER BY month) AS next_purchase_date
  FROM customer_month
)

SELECT
  w.month,
  COUNT(*)                                                         AS active_customers,
  COUNTIF(w.next_purchase_date IS NULL
       OR w.next_purchase_date > DATE_ADD(LAST_DAY(w.month, MONTH), INTERVAL 365 DAY))
                                                                   AS churned_customers_365d,
  ROUND(SAFE_DIVIDE(
    COUNTIF(w.next_purchase_date IS NULL
         OR w.next_purchase_date > DATE_ADD(LAST_DAY(w.month, MONTH), INTERVAL 365 DAY)),
    NULLIF(COUNT(*), 0)) * 100, 2)                                 AS churn_rate_365d,
  DATE_ADD(LAST_DAY(w.month, MONTH), INTERVAL 365 DAY) <= p.max_observable
                                                                   AS measurable
FROM with_next AS w
CROSS JOIN params AS p
GROUP BY w.month, measurable
ORDER BY w.month
