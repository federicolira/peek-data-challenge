-- Sensitivity of 90-day churn to the definition of 'purchase'.
-- Same 90-day churn, computed two ways side by side:
--   brief : purchase = status 'Complete' and not returned
--   alt   : purchase = any order not Cancelled and not Returned
WITH params AS (
  SELECT LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_obs,
         DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS cur_month
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),
purchases AS (
  SELECT oi.user_id, DATE(oi.created_at) AS d,
         DATE_TRUNC(DATE(oi.created_at), MONTH) AS m,
         (oi.status = 'Complete' AND oi.returned_at IS NULL) AS is_brief,
         (oi.status NOT IN ('Cancelled','Returned'))          AS is_alt
  FROM `bigquery-public-data.thelook_ecommerce.order_items` oi, params p
  WHERE DATE_TRUNC(DATE(oi.created_at), MONTH) < p.cur_month
    AND DATE(oi.created_at) <= p.max_obs
),
def AS (SELECT 'brief' AS defn UNION ALL SELECT 'alt'),
p2 AS (
  SELECT d.defn, x.user_id, x.d, x.m FROM purchases x CROSS JOIN def d
  WHERE (d.defn='brief' AND x.is_brief) OR (d.defn='alt' AND x.is_alt)
),
active AS (SELECT DISTINCT defn, m, user_id FROM p2),
flag AS (
  SELECT a.defn, a.m, a.user_id, COUNT(o.user_id) > 0 AS came_back
  FROM active a
  LEFT JOIN p2 o
    ON o.defn = a.defn AND o.user_id = a.user_id
   AND o.d >  LAST_DAY(a.m, MONTH)
   AND o.d <= DATE_ADD(LAST_DAY(a.m, MONTH), INTERVAL 90 DAY)
  GROUP BY a.defn, a.m, a.user_id
)
SELECT f.defn,
       COUNT(*) AS active_customer_months,
       ROUND(100 * COUNTIF(NOT f.came_back) / COUNT(*), 1) AS churn_90d_pct
FROM flag f, params p
WHERE f.m BETWEEN DATE '2025-06-01' AND DATE '2026-05-01'
GROUP BY f.defn ORDER BY f.defn DESC
