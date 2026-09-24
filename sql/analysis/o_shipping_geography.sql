-- Where do completed orders ship, and from where? (context for Task D)
--
-- Findings (as of 2026-09-23):
--   * all 10 distribution centres are in the US;
--   * ~77% of completed revenue ships abroad (China alone ~34%);
--   * orders >= $100 ship from ~1.9 distribution centres on average and ~60% are
--     split shipments, vs ~16% for smaller orders — so free shipping over $100
--     means paying for about two parcels per eligible order;
--   * transit time does not depend on distance (correlation ~0.005), so the
--     delivery timestamps cannot be used to estimate shipping cost. Parcel
--     costs in D.4-D.5 are therefore stated assumptions.
-- Distance uses ST_DISTANCE on the customer's and the warehouse's lat/long;
-- the warehouse is read from inventory_items.product_distribution_center_id.
WITH li AS (
  SELECT
    oi.order_id,
    oi.sale_price,
    u.country,
    ii.product_distribution_center_id                       AS dc,
    ST_DISTANCE(ST_GEOGPOINT(u.longitude, u.latitude),
                ST_GEOGPOINT(dc.longitude, dc.latitude)) / 1000 AS km,
    TIMESTAMP_DIFF(oi.delivered_at, oi.shipped_at, HOUR) / 24   AS transit_days
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.users` AS u ON u.id = oi.user_id
  JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
    ON ii.id = oi.inventory_item_id
  JOIN `bigquery-public-data.thelook_ecommerce.distribution_centers` AS dc
    ON dc.id = ii.product_distribution_center_id
  WHERE oi.status = 'Complete' AND oi.returned_at IS NULL
    AND DATE(oi.created_at) <= CURRENT_DATE()
),
ord AS (
  SELECT order_id, ANY_VALUE(country) AS country, SUM(sale_price) AS rev,
         COUNT(DISTINCT dc) AS parcels, AVG(km) AS km
  FROM li GROUP BY order_id
)
SELECT
  IF(rev >= 100, 'ge_100', 'lt_100')                                AS basket,
  COUNT(*)                                                          AS orders,
  ROUND(100 * COUNTIF(country <> 'United States') / COUNT(*), 1)    AS pct_international,
  ROUND(100 * COUNTIF(parcels > 1) / COUNT(*), 1)                   AS pct_split_shipment,
  ROUND(AVG(parcels), 2)                                            AS avg_parcels,
  ROUND(AVG(km))                                                    AS avg_km_from_dc,
  (SELECT ROUND(CORR(km, transit_days), 3) FROM li)                 AS corr_km_transit_days,
  (SELECT ROUND(100 * SUM(IF(country <> 'United States', sale_price, 0)) / SUM(sale_price), 1)
     FROM li)                                                       AS pct_revenue_international
FROM ord
GROUP BY basket
ORDER BY basket
