-- ---------------------------------------------------------------------------
-- p_repeat_drivers — does anything about a customer or their first order
-- predict whether they buy again within 12 months?
--
-- Same population and definitions as the north-star metric (v_cohort_repeat):
-- first-time buyers observed for at least 365 days; a purchase is any order not
-- Cancelled / Returned. Each first order is described by seven attributes, and
-- the 12-month repeat rate is computed for every segment.
--
-- Result: every segment sits within 2 points of the overall 16.2% (14.5–18.0%).
-- Nothing observable here explains churn, which fits a synthetic generator that
-- places orders at random (k_order_placement_test.sql). In real data the first
-- place to look is first-order experience: late delivery, a return, a support
-- ticket, a discount.
-- ---------------------------------------------------------------------------
WITH params AS (
  SELECT LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_observable
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

-- one row per valid order, with the attributes of that order
valid_orders AS (
  SELECT
    oi.user_id,
    oi.order_id,
    DATE(MIN(oi.created_at))                                            AS order_date,
    SUM(oi.sale_price)                                                  AS order_value,
    COUNT(*)                                                            AS items,
    DATE_DIFF(DATE(MAX(oi.delivered_at)), DATE(MIN(oi.created_at)), DAY) AS days_to_deliver,
    -- category of the most expensive item: deterministic, unlike ANY_VALUE
    ARRAY_AGG(p.category ORDER BY oi.sale_price DESC, oi.id LIMIT 1)[OFFSET(0)] AS main_category
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.products`    AS p ON p.id = oi.product_id
  CROSS JOIN params
  WHERE oi.status NOT IN ('Cancelled', 'Returned')
    AND DATE(oi.created_at) <= params.max_observable
  GROUP BY oi.user_id, oi.order_id
),

seq AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY order_date, order_id) AS n,
    LEAD(order_date) OVER (PARTITION BY user_id ORDER BY order_date, order_id) AS next_date
  FROM valid_orders
),

first_orders AS (
  SELECT
    s.*,
    u.gender,
    u.age,
    u.country,
    IFNULL(DATE_DIFF(s.next_date, s.order_date, DAY) <= 365, FALSE) AS repeat_12m
  FROM seq AS s
  JOIN `bigquery-public-data.thelook_ecommerce.users` AS u ON u.id = s.user_id
  CROSS JOIN params
  WHERE s.n = 1
    AND DATE_DIFF(params.max_observable, s.order_date, DAY) >= 365
),

segments AS (
  SELECT repeat_12m, 'Gender' AS attribute, gender AS segment FROM first_orders
  UNION ALL
  SELECT repeat_12m, 'Age', CASE WHEN age < 25 THEN '<25' WHEN age < 40 THEN '25-39'
                                 WHEN age < 55 THEN '40-54' ELSE '55+' END FROM first_orders
  UNION ALL
  SELECT repeat_12m, 'First order value', CASE WHEN order_value < 50 THEN '<$50' WHEN order_value < 100 THEN '$50-99'
                                               WHEN order_value < 200 THEN '$100-199' ELSE '$200+' END FROM first_orders
  UNION ALL
  SELECT repeat_12m, 'Items in first order', IF(items >= 4, '4+', CAST(items AS STRING)) FROM first_orders
  UNION ALL
  SELECT repeat_12m, 'Days to deliver', CASE WHEN days_to_deliver IS NULL THEN 'not delivered'
                                             WHEN days_to_deliver <= 2 THEN '0-2' WHEN days_to_deliver <= 4 THEN '3-4'
                                             ELSE '5+' END FROM first_orders
  UNION ALL
  SELECT repeat_12m, 'Shipping zone', IF(country = 'United States', 'Domestic (US)', 'International') FROM first_orders
  UNION ALL
  SELECT repeat_12m, 'Main category', main_category FROM first_orders
),

overall AS (
  SELECT AVG(IF(repeat_12m, 1, 0)) * 100 AS rate FROM first_orders
)

SELECT
  attribute,
  segment,
  COUNT(*)                                                      AS first_time_buyers,
  ROUND(AVG(IF(repeat_12m, 1, 0)) * 100, 1)                     AS repeat_12m_pct,
  ROUND(AVG(IF(repeat_12m, 1, 0)) * 100 - ANY_VALUE(o.rate), 1) AS pts_vs_overall
FROM segments
CROSS JOIN overall AS o
GROUP BY attribute, segment
HAVING COUNT(*) >= 1000          -- small categories are noise at this rate
ORDER BY attribute, segment
