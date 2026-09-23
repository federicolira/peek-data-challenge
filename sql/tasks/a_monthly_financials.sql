WITH params AS (
  SELECT
    DATE_TRUNC(DATE(MIN(created_at)), MONTH)     AS first_month,
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS current_month,
    LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_observable
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),
completed_items AS (
  SELECT
    oi.order_id, oi.user_id, oi.sale_price,
    DATE_TRUNC(DATE(oi.created_at), MONTH) AS month
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) <  p.current_month
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) >= p.first_month
    AND DATE(oi.created_at) <= p.max_observable
),
monthly AS (
  SELECT
    month,
    ROUND(SUM(sale_price), 2)                                       AS revenue,
    COUNT(DISTINCT order_id)                                        AS orders,
    COUNT(*)                                                        AS units,
    ROUND(SUM(sale_price) / NULLIF(COUNT(DISTINCT order_id), 0), 2) AS aov
  FROM completed_items
  GROUP BY month
)
SELECT
  month, revenue, orders, units, aov,
  LAG(revenue) OVER (ORDER BY month) AS revenue_prior_month,
  ROUND(SAFE_DIVIDE(revenue - LAG(revenue) OVER (ORDER BY month),
                    NULLIF(LAG(revenue) OVER (ORDER BY month), 0)) * 100, 2)
                                     AS mom_revenue_growth_pct
FROM monthly
ORDER BY month
