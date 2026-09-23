-- Customer LTV curve: average cumulative completed revenue per customer,
-- by months since first completed purchase. Only cohorts with the full
-- 24 months observable are included, so every point on the curve is
-- averaged over the SAME customers (no survivorship drift along the x-axis).
WITH params AS (
  SELECT LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_obs,
         DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS cur_month
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),
completed AS (
  SELECT oi.user_id, oi.sale_price, DATE_TRUNC(DATE(oi.created_at), MONTH) AS m
  FROM `bigquery-public-data.thelook_ecommerce.order_items` oi, params p
  WHERE oi.status = 'Complete' AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) < p.cur_month
    AND DATE(oi.created_at) <= p.max_obs
),
first_p AS (SELECT user_id, MIN(m) AS cohort FROM completed GROUP BY user_id),
eligible AS (
  SELECT f.user_id, f.cohort FROM first_p f, params p
  WHERE DATE_ADD(f.cohort, INTERVAL 24 MONTH) < p.cur_month
),
months AS (SELECT k FROM UNNEST(GENERATE_ARRAY(0, 24)) AS k),
rev AS (
  SELECT e.user_id, DATE_DIFF(c.m, e.cohort, MONTH) AS k, SUM(c.sale_price) AS r
  FROM eligible e JOIN completed c USING (user_id)
  GROUP BY e.user_id, k
),
grid AS (
  SELECT e.user_id, mo.k, COALESCE(r.r, 0) AS r
  FROM eligible e CROSS JOIN months mo
  LEFT JOIN rev r ON r.user_id = e.user_id AND r.k = mo.k
),
cum AS (
  SELECT user_id, k, SUM(r) OVER (PARTITION BY user_id ORDER BY k) AS cum_rev
  FROM grid
)
SELECT
  k AS months_since_first,
  COUNT(*) AS customers,
  ROUND(AVG(cum_rev), 2) AS avg_cumulative_revenue
FROM cum
GROUP BY k
ORDER BY k
