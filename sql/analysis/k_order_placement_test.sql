-- How does theLook place orders in time?
--
-- For every customer with exactly ONE order and an account at least a year old:
-- where does that order fall within the customer's lifetime [signup, today]?
--   frac = 0  -> the day they signed up;  frac = 1 -> today.
--
-- Result: every decile holds 9.8-10.2% of customers — a uniform distribution.
-- The generator creates users at a fixed rate (~12,600 a year) and drops each
-- order at a random date between signup and today. Consequences:
--   * recent months always receive orders from every user created so far, so
--     order volume and revenue grow into the present mechanically;
--   * gaps between purchases scale with account age;
--   * any "conversion within N days of signup" rises for recent cohorts.
-- Cross-sectional comparisons (segment vs segment, same period) are unaffected;
-- trends over calendar time should be read with this in mind.
WITH o AS (
  SELECT user_id, COUNT(DISTINCT order_id) AS n_orders, MIN(DATE(created_at)) AS d
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
  WHERE DATE(created_at) <= CURRENT_DATE()
  GROUP BY user_id
),
pos AS (
  SELECT SAFE_DIVIDE(DATE_DIFF(o.d, DATE(u.created_at), DAY),
                     DATE_DIFF(CURRENT_DATE(), DATE(u.created_at), DAY)) AS frac
  FROM o
  JOIN `bigquery-public-data.thelook_ecommerce.users` AS u ON u.id = o.user_id
  WHERE o.n_orders = 1
    AND DATE_DIFF(CURRENT_DATE(), DATE(u.created_at), DAY) >= 365
)
SELECT
  CAST(FLOOR(LEAST(frac, 0.9999) * 10) AS INT64)             AS decile,
  COUNT(*)                                                    AS customers,
  ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)            AS pct
FROM pos
GROUP BY decile
ORDER BY decile
