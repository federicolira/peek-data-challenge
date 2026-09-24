-- Generated from sql/part1_queries.sql by run_all.py - edit that file, not this one.

-- ---------------------------------------------------------------------
-- TASK D.3 — the chosen segment: SHIPPING ZONE (domestic vs international).
--
-- Why this segment and not traffic_source: every acquisition channel behaves
-- identically in this data (conversion, activation and repeat all within ~1
-- point — sql/analysis/e, l), so a channel cut cannot show anything. The cost
-- of a free-shipping policy, on the other hand, lives in WHERE orders ship:
--   * all 10 distribution centres are in the US, yet ~77% of revenue ships
--     abroad (China alone is ~34%);
--   * eligible (>= $100) orders ship from ~1.9 distribution centres on
--     average — a split shipment, i.e. the business would pay for ~2 parcels.
-- shipments = COUNT(DISTINCT distribution centre) of the order's items, read
-- from inventory_items (verified 1:1 with order_items), so no extra join.
-- ---------------------------------------------------------------------

WITH params AS (
  SELECT DATE '2022-01-15' AS launch_date, 100.0 AS thr, 90 AS window_days
),

order_level AS (
  SELECT
    oi.order_id,
    ANY_VALUE(oi.user_id)                                  AS user_id,
    DATE(MIN(oi.created_at))                               AS order_date,
    SUM(oi.sale_price)                                     AS order_revenue,
    SUM(ii.cost)                                           AS order_cogs,
    COUNT(DISTINCT ii.product_distribution_center_id)      AS shipments
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
    ON ii.id = oi.inventory_item_id
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
  GROUP BY oi.order_id
)

SELECT
  IF(u.country = 'United States', 'domestic', 'international')   AS shipping_zone,
  IF(o.order_revenue >= p.thr, 'eligible_ge_100', 'not_eligible')  AS cohort,
  IF(o.order_date >= p.launch_date, 'post', 'pre')                 AS period,
  COUNT(*)                                                         AS orders,
  ROUND(AVG(o.order_revenue), 2)                                   AS aov,
  ROUND(SUM(o.order_revenue), 2)                                   AS revenue,
  ROUND(SUM(o.order_revenue) - SUM(o.order_cogs), 2)               AS gross_profit,
  ROUND(AVG(o.shipments), 2)                                       AS avg_shipments_per_order,
  ROUND(SAFE_DIVIDE(COUNTIF(o.shipments > 1), NULLIF(COUNT(*), 0)) * 100, 1)
                                                                   AS pct_split_shipment
FROM order_level AS o
CROSS JOIN params AS p
JOIN `bigquery-public-data.thelook_ecommerce.users` AS u     -- 1:1 per order, after rollup
  ON u.id = o.user_id
WHERE o.order_date BETWEEN DATE_SUB(p.launch_date, INTERVAL p.window_days DAY)
                       AND DATE_ADD(p.launch_date, INTERVAL p.window_days DAY)
GROUP BY shipping_zone, cohort, period
ORDER BY shipping_zone, cohort, period DESC;
