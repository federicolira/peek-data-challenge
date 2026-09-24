-- ---------------------------------------------------------------------------
-- v_monthly_kpis — one row per complete month: Tasks A, B and C in one place.
-- Churn is NULL for months whose observation window has not closed yet, so a
-- chart built on this view cannot plot the artificial 100% at the data edge.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW `__PROJECT__.__DATASET__.v_monthly_kpis`
OPTIONS (description = "One row per complete month. Revenue, orders, units, AOV, MoM and YoY growth (Task A); active, new and returning customers and revenue (Task B); churn over 90 and 365 days (Task C). Churn is NULL where the window has not closed, never an artificial 100%.")
AS
WITH params AS (
  SELECT
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS current_month,
    LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_observable
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

items AS (
  SELECT
    oi.order_id,
    oi.user_id,
    oi.sale_price,
    DATE(oi.created_at)                              AS order_date,
    DATE_TRUNC(DATE(oi.created_at), MONTH)           AS month
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) < p.current_month
    AND DATE(oi.created_at) <= p.max_observable
),

financials AS (
  SELECT
    month,
    SUM(sale_price)                                  AS revenue,
    COUNT(DISTINCT order_id)                         AS orders,
    COUNT(*)                                         AS units
  FROM items
  GROUP BY month
),

first_purchase AS (
  SELECT user_id, MIN(month) AS cohort_month FROM items GROUP BY user_id
),

customer_month AS (
  SELECT month, user_id, SUM(sale_price) AS revenue, MIN(order_date) AS first_order_in_month
  FROM items
  GROUP BY month, user_id
),

mix AS (
  SELECT
    cm.month,
    COUNT(*)                                                      AS active_customers,
    COUNTIF(cm.month = fp.cohort_month)                           AS new_customers,
    COUNTIF(cm.month > fp.cohort_month)                           AS returning_customers,
    SUM(IF(cm.month = fp.cohort_month, cm.revenue, 0))            AS revenue_new,
    SUM(IF(cm.month > fp.cohort_month, cm.revenue, 0))            AS revenue_returning
  FROM customer_month AS cm
  JOIN first_purchase AS fp USING (user_id)
  GROUP BY cm.month
),

-- next purchase after month M = first order of the customer's next active month
with_next AS (
  SELECT
    month,
    LEAD(first_order_in_month) OVER (PARTITION BY user_id ORDER BY month) AS next_purchase
  FROM customer_month
),

churn AS (
  SELECT
    w.month,
    COUNTIF(w.next_purchase IS NULL
         OR w.next_purchase > DATE_ADD(LAST_DAY(w.month, MONTH), INTERVAL 90 DAY))  AS churned_90d,
    COUNTIF(w.next_purchase IS NULL
         OR w.next_purchase > DATE_ADD(LAST_DAY(w.month, MONTH), INTERVAL 365 DAY)) AS churned_365d,
    ANY_VALUE(DATE_ADD(LAST_DAY(w.month, MONTH), INTERVAL 90 DAY)  <= p.max_observable) AS measurable_90d,
    ANY_VALUE(DATE_ADD(LAST_DAY(w.month, MONTH), INTERVAL 365 DAY) <= p.max_observable) AS measurable_365d
  FROM with_next AS w
  CROSS JOIN params AS p
  GROUP BY w.month
)

SELECT
  f.month,
  ROUND(f.revenue, 2)                                                        AS revenue,
  f.orders,
  f.units,
  ROUND(SAFE_DIVIDE(f.revenue, f.orders), 2)                                 AS aov,
  ROUND(SAFE_DIVIDE(f.revenue - LAG(f.revenue) OVER (ORDER BY f.month),
                    LAG(f.revenue) OVER (ORDER BY f.month)) * 100, 2)        AS mom_revenue_growth_pct,
  ROUND(SAFE_DIVIDE(f.revenue - LAG(f.revenue, 12) OVER (ORDER BY f.month),
                    LAG(f.revenue, 12) OVER (ORDER BY f.month)) * 100, 2)    AS yoy_revenue_growth_pct,
  m.active_customers,
  m.new_customers,
  m.returning_customers,
  ROUND(m.revenue_new, 2)                                                    AS revenue_new,
  ROUND(m.revenue_returning, 2)                                              AS revenue_returning,
  ROUND(SAFE_DIVIDE(m.revenue_returning, f.revenue) * 100, 2)                AS pct_revenue_from_returning,
  c.churned_90d,
  IF(c.measurable_90d,  ROUND(SAFE_DIVIDE(c.churned_90d,  m.active_customers) * 100, 2), NULL)
                                                                             AS churn_rate_90d,
  c.measurable_90d,
  IF(c.measurable_365d, ROUND(SAFE_DIVIDE(c.churned_365d, m.active_customers) * 100, 2), NULL)
                                                                             AS churn_rate_365d,
  c.measurable_365d
FROM financials AS f
JOIN mix   AS m USING (month)
JOIN churn AS c USING (month)
