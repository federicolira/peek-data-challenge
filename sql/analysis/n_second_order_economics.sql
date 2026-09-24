-- Unit economics for Recommendation 2 ("free shipping on the SECOND order"),
-- last 12 complete months, by shipping zone.
--
-- Break-even logic (computed in analysis/build_deck.py from this output):
--   a free-shipping-on-second-order offer pays parcels on every second order —
--   including the ~4.4% of first-time buyers who would have come back anyway
--   within 90 days (the inframarginal cost). Each INCREMENTAL second order
--   earns its gross profit minus its own parcels. Break-even lift =
--     baseline_repeat x parcel_cost_per_order / (gp_per_order - parcel_cost_per_order)
-- Parcel costs are assumptions ($8 domestic, $25 international), stated on the
-- slide; everything else comes from the data below.
WITH params AS (
  SELECT
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS current_month,
    LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_obs
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),
order_level AS (
  SELECT
    oi.order_id,
    ANY_VALUE(oi.user_id)                                  AS user_id,
    SUM(oi.sale_price)                                     AS rev,
    SUM(ii.cost)                                           AS cogs,
    COUNT(DISTINCT ii.product_distribution_center_id)      AS shipments
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
    ON ii.id = oi.inventory_item_id
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) <  p.current_month
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) >= DATE_SUB(p.current_month, INTERVAL 12 MONTH)
    AND DATE(oi.created_at) <= p.max_obs
  GROUP BY oi.order_id
)
SELECT
  IF(u.country = 'United States', 'domestic', 'international')   AS shipping_zone,
  COUNT(*)                                                        AS orders,
  ROUND(SUM(o.rev), 2)                                            AS revenue,
  ROUND(AVG(o.rev), 2)                                            AS aov,
  ROUND(AVG(o.rev - o.cogs), 2)                                   AS gross_profit_per_order,
  ROUND(SAFE_DIVIDE(SUM(o.rev - o.cogs), SUM(o.rev)) * 100, 1)    AS gross_margin_pct,
  ROUND(AVG(o.shipments), 3)                                      AS parcels_per_order,
  ROUND(SAFE_DIVIDE(SUM(o.rev), SUM(SUM(o.rev)) OVER ()) * 100, 1) AS pct_of_revenue
FROM order_level AS o
JOIN `bigquery-public-data.thelook_ecommerce.users` AS u ON u.id = o.user_id
GROUP BY shipping_zone
ORDER BY shipping_zone
