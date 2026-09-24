-- ---------------------------------------------------------------------------
-- v_cohort_repeat — the north-star metric: 12-month repeat rate, by cohort.
-- GRAIN: one row per first-purchase month.
-- "Purchase" here = any order not Cancelled / Returned, because order status is
-- assigned at random in theLook (sql/analysis/i_status_by_year.sql): counting
-- only 'Complete' would hide three quarters of genuine repeat orders.
-- POPULATION: first-time buyers observed for at least 365 days, for BOTH windows,
-- so the 90-day and 12-month rates describe the same customers (and match the
-- deck: 4.4% and 16.2%). Including recent cohorts in the 90-day rate would mix in
-- customers whose orders the generator compresses into a short window.
-- In Looker: repeat rate = SUM(repeat_365d) / SUM(customers_observed_1y).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW `__PROJECT__.__DATASET__.v_cohort_repeat`
OPTIONS (description = "Repeat purchase by first-purchase cohort (any non-cancelled, non-returned order), for first-time buyers observed at least 365 days. 12-month repeat rate = SUM(repeat_365d) / SUM(customers_observed_1y); 90-day rate = SUM(repeat_90d) / SUM(customers_observed_1y). Cohorts younger than a year contribute zero.")
AS
WITH params AS (
  SELECT LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_observable
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

valid_orders AS (
  SELECT user_id, order_id, DATE(MIN(created_at)) AS order_date
  FROM `bigquery-public-data.thelook_ecommerce.order_items`, params AS p
  WHERE status NOT IN ('Cancelled', 'Returned')
    AND DATE(created_at) <= p.max_observable
  GROUP BY user_id, order_id
),

seq AS (
  SELECT
    user_id,
    order_date,
    ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY order_date, order_id) AS n,
    LEAD(order_date) OVER (PARTITION BY user_id ORDER BY order_date, order_id) AS next_date
  FROM valid_orders
),

firsts AS (
  SELECT
    user_id,
    DATE_TRUNC(order_date, MONTH)                                AS cohort_month,
    DATE_DIFF(next_date, order_date, DAY)                        AS gap_days,
    DATE_DIFF(p.max_observable, order_date, DAY)                 AS days_observed
  FROM seq, params AS p
  WHERE n = 1
)

SELECT
  cohort_month,
  COUNT(*)                                                       AS first_time_buyers,
  COUNTIF(days_observed >= 365)                                  AS customers_observed_1y,
  COUNTIF(days_observed >= 365 AND gap_days <= 90)               AS repeat_90d,
  COUNTIF(days_observed >= 365 AND gap_days <= 365)              AS repeat_365d,
  COUNTIF(gap_days IS NOT NULL)                                  AS repeat_ever_so_far
FROM firsts
GROUP BY cohort_month
