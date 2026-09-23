-- Can the events table measure conversion? Session-level funnel, by year.
--
-- Finding (see README § Funnels): no. The table is generated from templates:
--   * every IDENTIFIED session follows one of 4 fixed paths and ALWAYS ends in
--     'purchase' — 181,415 such sessions, exactly one per order_items row;
--   * every ANONYMOUS session follows one of 4 abandonment paths and NEVER buys,
--     at a flat ~65,000 sessions a year.
-- So "conversion" = purchase sessions / all sessions is (order volume) / (order
-- volume + a constant), and it rises mechanically as order volume grows:
-- 2.4% in 2019 to 55% in 2026. That is a property of the generator, not of users.
WITH s AS (
  SELECT
    session_id,
    DATE_TRUNC(DATE(MIN(created_at)), MONTH)   AS m,
    LOGICAL_OR(user_id IS NULL)                AS anon,
    LOGICAL_OR(event_type = 'product')         AS saw_product,
    LOGICAL_OR(event_type = 'cart')            AS added_to_cart,
    LOGICAL_OR(event_type = 'purchase')        AS purchased
  FROM `bigquery-public-data.thelook_ecommerce.events`
  WHERE DATE(created_at) <= CURRENT_DATE()
  GROUP BY session_id
)
SELECT
  EXTRACT(YEAR FROM m)                                        AS year,
  COUNT(*)                                                    AS sessions,
  COUNTIF(anon)                                               AS anonymous_sessions,
  COUNTIF(purchased)                                          AS purchase_sessions,
  COUNTIF(saw_product)                                        AS step1_product,
  COUNTIF(added_to_cart)                                      AS step2_cart,
  COUNTIF(purchased)                                          AS step3_purchase,
  ROUND(100 * SAFE_DIVIDE(COUNTIF(added_to_cart), COUNTIF(saw_product)), 1) AS product_to_cart_pct,
  ROUND(100 * SAFE_DIVIDE(COUNTIF(purchased), COUNTIF(added_to_cart)), 1)   AS cart_to_purchase_pct,
  ROUND(100 * SAFE_DIVIDE(COUNTIF(purchased), COUNT(*)), 1)                 AS naive_session_cvr_pct
FROM s
GROUP BY year
ORDER BY year
