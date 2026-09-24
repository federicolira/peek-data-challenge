-- ---------------------------------------------------------------------------
-- v_cohort_retention — the Task C stretch, for a Looker Studio heatmap.
-- GRAIN: one row per (first-purchase month, months since first purchase).
-- In Looker: pivot table, rows = cohort_month, columns = months_since_first,
-- metric = retention_pct, heatmap on; filter months_since_first >= 1.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW `__PROJECT__.__DATASET__.v_cohort_retention`
OPTIONS (description = "Cohort retention: one row per first-purchase month and months since first purchase. retention_pct = share of the cohort with a completed order that month. Month 0 is 100% by definition; filter months_since_first >= 1 for the heatmap.")
AS
WITH params AS (
  SELECT
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS current_month,
    LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_observable
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

items AS (
  SELECT oi.user_id, DATE_TRUNC(DATE(oi.created_at), MONTH) AS month
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) < p.current_month
    AND DATE(oi.created_at) <= p.max_observable
),

first_purchase AS (SELECT user_id, MIN(month) AS cohort_month FROM items GROUP BY user_id),
cohort_size    AS (SELECT cohort_month, COUNT(*) AS cohort_customers FROM first_purchase GROUP BY cohort_month),

activity AS (
  SELECT DISTINCT
    fp.cohort_month,
    DATE_DIFF(i.month, fp.cohort_month, MONTH)       AS months_since_first,
    i.user_id
  FROM items AS i
  JOIN first_purchase AS fp USING (user_id)
)

SELECT
  a.cohort_month,
  a.months_since_first,
  cs.cohort_customers,
  COUNT(*)                                                           AS active_customers,
  ROUND(SAFE_DIVIDE(COUNT(*), cs.cohort_customers) * 100, 2)         AS retention_pct
FROM activity AS a
JOIN cohort_size AS cs USING (cohort_month)
GROUP BY a.cohort_month, a.months_since_first, cs.cohort_customers
