-- Generated from sql/part1_queries.sql by run_all.py - edit that file, not this one.

-- ---------------------------------------------------------------------
-- TASK D.5 — break-even, by shipping zone, over the 12 months after launch.
--
-- The one number leadership can react to: how much can a parcel cost before
-- the policy destroys more gross profit than it creates?
--   gain  = gross profit on the ADDED items of topped-up orders
--   cost  = parcels on every eligible order — including the orders that were
--           already over $100 and needed no incentive (the "inframarginal"
--           subsidy, which is where most of the money goes)
--   break-even cost per parcel = gain / parcels absorbed
-- Same assumptions and deterministic draws as D.4.
-- ---------------------------------------------------------------------

WITH params AS (
  SELECT DATE '2022-01-15' AS launch_date, 100.0 AS thr,
         70.0 AS near_threshold_floor, 0.30 AS topup_rate
),

order_level AS (
  SELECT
    oi.order_id,
    ANY_VALUE(oi.user_id)                                  AS user_id,
    DATE(MIN(oi.created_at))                               AS order_date,
    SUM(oi.sale_price)                                     AS rev,
    SUM(ii.cost)                                           AS cogs,
    COUNT(DISTINCT ii.product_distribution_center_id)      AS shipments
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
    ON ii.id = oi.inventory_item_id
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
  GROUP BY oi.order_id
),

post AS (
  SELECT
    IF(u.country = 'United States', 'domestic', 'international')      AS shipping_zone,
    o.rev, o.cogs, o.shipments, p.thr,
    (o.rev >= p.near_threshold_floor AND o.rev < p.thr
     AND MOD(ABS(FARM_FINGERPRINT(CAST(o.order_id AS STRING))), 10000) / 10000.0 < p.topup_rate)
                                                                        AS topped_up,
    p.thr + 20 * MOD(ABS(FARM_FINGERPRINT(CONCAT('b', CAST(o.order_id AS STRING)))), 10000)
                  / 10000.0                                             AS topped_rev
  FROM order_level AS o
  CROSS JOIN params AS p
  JOIN `bigquery-public-data.thelook_ecommerce.users` AS u ON u.id = o.user_id
  WHERE o.order_date >= p.launch_date
    AND o.order_date <  DATE_ADD(p.launch_date, INTERVAL 12 MONTH)
)

SELECT
  shipping_zone,
  COUNT(*)                                                                AS orders,
  COUNTIF(rev >= thr)                                                     AS already_eligible,
  COUNTIF(topped_up)                                                      AS topped_up,
  -- gross profit on the added item only (added revenue x the order's margin)
  ROUND(SUM(IF(topped_up, (topped_rev - rev) * (1 - SAFE_DIVIDE(cogs, rev)), 0)), 2)
                                                                          AS incremental_gross_profit,
  SUM(IF(rev >= thr OR topped_up, shipments, 0))                          AS parcels_absorbed,
  ROUND(SAFE_DIVIDE(SUM(IF(rev >= thr, shipments, 0)),
                    SUM(IF(rev >= thr OR topped_up, shipments, 0))) * 100, 1)
                                                                          AS pct_parcels_on_already_eligible,
  ROUND(SAFE_DIVIDE(
    SUM(IF(topped_up, (topped_rev - rev) * (1 - SAFE_DIVIDE(cogs, rev)), 0)),
    SUM(IF(rev >= thr OR topped_up, shipments, 0))), 2)                   AS break_even_cost_per_parcel
FROM post
GROUP BY shipping_zone
ORDER BY shipping_zone;
