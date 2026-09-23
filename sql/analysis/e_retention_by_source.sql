-- Retention by acquisition channel (users.traffic_source), two lenses:
--   churn_90d_pct   : brief definition, last 12 measurable months (Jun 2025 - May 2026)
--   repeat_12m_pct  : any valid order (not Cancelled/Returned) within 365 days of the
--                     first one, for customers with a full 12 months observable.
-- The second lens exists because the median gap between 1st and 2nd purchase is
-- ~412 days, so a 90-day window mislabels most eventual repeaters as churned.
WITH params AS (
  SELECT LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_obs,
         DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS cur_month
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),
completed AS (
  SELECT oi.user_id, DATE(oi.created_at) AS d, DATE_TRUNC(DATE(oi.created_at), MONTH) AS m
  FROM `bigquery-public-data.thelook_ecommerce.order_items` oi, params p
  WHERE oi.status = 'Complete' AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) < p.cur_month
    AND DATE(oi.created_at) <= p.max_obs
),
active AS (SELECT DISTINCT m, user_id FROM completed
           WHERE m BETWEEN DATE '2025-06-01' AND DATE '2026-05-01'),
churn AS (
  SELECT a.user_id, a.m, COUNT(c.user_id) = 0 AS churned
  FROM active a
  LEFT JOIN completed c
    ON c.user_id = a.user_id
   AND c.d >  LAST_DAY(a.m, MONTH)
   AND c.d <= DATE_ADD(LAST_DAY(a.m, MONTH), INTERVAL 90 DAY)
  GROUP BY a.user_id, a.m
),
valid_orders AS (
  SELECT user_id, order_id, DATE(MIN(created_at)) AS d
  FROM `bigquery-public-data.thelook_ecommerce.order_items`, params p
  WHERE status NOT IN ('Cancelled','Returned') AND DATE(created_at) <= p.max_obs
  GROUP BY user_id, order_id
),
seq AS (
  SELECT user_id, d,
         ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY d, order_id) AS n,
         LEAD(d)      OVER (PARTITION BY user_id ORDER BY d, order_id) AS next_d
  FROM valid_orders
),
repeat12 AS (
  SELECT s.user_id, (s.next_d IS NOT NULL AND DATE_DIFF(s.next_d, s.d, DAY) <= 365) AS repeated
  FROM seq s, params p
  WHERE s.n = 1 AND s.d <= DATE_SUB(p.max_obs, INTERVAL 365 DAY)
),
churn_src AS (
  SELECT u.traffic_source, COUNT(*) AS active_customer_months,
         ROUND(100 * COUNTIF(ch.churned) / COUNT(*), 1) AS churn_90d_pct
  FROM churn ch JOIN `bigquery-public-data.thelook_ecommerce.users` u ON u.id = ch.user_id
  GROUP BY u.traffic_source
),
repeat_src AS (
  SELECT u.traffic_source, COUNT(*) AS first_time_buyers_12m_obs,
         ROUND(100 * COUNTIF(r.repeated) / COUNT(*), 1) AS repeat_12m_pct
  FROM repeat12 r JOIN `bigquery-public-data.thelook_ecommerce.users` u ON u.id = r.user_id
  GROUP BY u.traffic_source
)
SELECT c.traffic_source, c.active_customer_months, c.churn_90d_pct,
       r.first_time_buyers_12m_obs, r.repeat_12m_pct
FROM churn_src c JOIN repeat_src r USING (traffic_source)
ORDER BY c.active_customer_months DESC
