-- Repeat-purchase timing: how long until a first-time buyer buys again?
-- Valid order = not Cancelled / Returned (status is randomly assigned in theLook,
-- see i_status_by_year.sql, so 'Complete' alone would hide most repeat purchases).
-- Only customers whose first order is >=365 days old, so each has 12 months to repeat.
-- Order-level, valid orders (not cancelled / returned), no future rows.
WITH o AS (
  SELECT user_id, order_id, DATE(MIN(created_at)) AS d
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
  WHERE status NOT IN ('Cancelled','Returned')
    AND DATE(created_at) <= CURRENT_DATE()
  GROUP BY user_id, order_id
),
seq AS (
  SELECT user_id, d,
         ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY d, order_id) AS n,
         LEAD(d)      OVER (PARTITION BY user_id ORDER BY d, order_id) AS next_d
  FROM o
),
firsts AS (
  SELECT user_id, d AS first_d, DATE_DIFF(next_d, d, DAY) AS gap_days
  FROM seq WHERE n = 1
    -- give every customer at least 12 months to show a repeat
    AND d <= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
),
-- EXACT percentiles, not APPROX_QUANTILES: the approximate version returned 412 on
-- one run and 410 on the next, and a headline number must reproduce exactly.
gaps AS (
  SELECT gap_days,
         PERCENTILE_CONT(gap_days, 0.5) OVER () AS p50,
         PERCENTILE_CONT(gap_days, 0.9) OVER () AS p90
  FROM firsts WHERE gap_days IS NOT NULL
)
SELECT
  COUNT(*)                                                    AS customers_12m_observable,
  ROUND(100*COUNTIF(gap_days IS NOT NULL)/COUNT(*),1)         AS pct_ever_repeat,
  ROUND(100*COUNTIF(gap_days <= 90)/COUNT(*),1)               AS pct_repeat_within_90d,
  ROUND(100*COUNTIF(gap_days <= 365)/COUNT(*),1)              AS pct_repeat_within_365d,
  (SELECT ROUND(ANY_VALUE(p50)) FROM gaps)                    AS median_gap_days_among_repeaters,
  (SELECT ROUND(ANY_VALUE(p90)) FROM gaps)                    AS p90_gap_days
FROM firsts
