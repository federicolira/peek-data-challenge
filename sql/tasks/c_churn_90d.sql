WITH params AS (
  SELECT
    LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_observable,
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS current_month
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),
completed_orders AS (
  SELECT oi.user_id, DATE(oi.created_at) AS order_date,
         DATE_TRUNC(DATE(oi.created_at), MONTH) AS month
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete' AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) < p.current_month
    AND DATE(oi.created_at) <= p.max_observable
),
active_by_month AS (SELECT DISTINCT month, user_id FROM completed_orders),
churn_flag AS (
  SELECT a.month, a.user_id,
    MAX(IF(o.order_date IS NOT NULL, 1, 0)) AS returned_within_90d
  FROM active_by_month AS a
  LEFT JOIN completed_orders AS o
    ON  o.user_id    = a.user_id
    AND o.order_date >  LAST_DAY(a.month, MONTH)
    AND o.order_date <= DATE_ADD(LAST_DAY(a.month, MONTH), INTERVAL 90 DAY)
  GROUP BY a.month, a.user_id
)
SELECT
  c.month,
  COUNT(*)                                                        AS active_customers,
  COUNTIF(c.returned_within_90d = 0)                              AS churned_customers_90d,
  ROUND(SAFE_DIVIDE(COUNTIF(c.returned_within_90d = 0),
                    NULLIF(COUNT(*), 0)) * 100, 2)                AS churn_rate_90d,
  DATE_ADD(LAST_DAY(c.month, MONTH), INTERVAL 90 DAY) <= p.max_observable AS measurable
FROM churn_flag AS c
CROSS JOIN params AS p
GROUP BY c.month, measurable
ORDER BY c.month
