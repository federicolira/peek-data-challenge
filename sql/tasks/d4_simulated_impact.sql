-- Generated from sql/part1_queries.sql by run_all.py - edit that file, not this one.

-- ---------------------------------------------------------------------
-- TASK D.4 — SIMULATED impact, monthly (the brief: "generate the visual as
-- if there is a noticeable impact").
--
-- The policy is not in the data, so its effect is INJECTED here through the
-- mechanism free-shipping thresholds actually trigger: customers just below
-- the line add an item to clear it ("threshold bunching"). Every assumption
-- is a parameter, so the simulation can be re-run at any strength.
--
--   near_threshold_floor  orders of $70-$99.99 are within reach of $100
--   topup_rate            30% of those, post-launch, top up to $100-$120
--   cost_per_shipment_*   ASSUMED parcel cost; the data has no shipping fees
--   customers_paid_ship.  assumption: shipping is charged to customers today,
--                         so the policy moves that cost onto the business
--
-- Draws use FARM_FINGERPRINT(order_id), not RAND(): the "random" top-ups are
-- identical on every run, so the simulated numbers reproduce exactly.
-- Margin on the added item = the order's own margin ratio.
-- ---------------------------------------------------------------------

WITH params AS (
  SELECT
    DATE '2022-01-15'  AS launch_date,
    100.0              AS thr,
    70.0               AS near_threshold_floor,
    0.30               AS topup_rate,
    8.00               AS cost_per_shipment_domestic,
    25.00              AS cost_per_shipment_international
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

sim AS (
  SELECT
    o.*,
    u.country = 'United States'                                          AS domestic,
    o.order_date >= p.launch_date                                        AS post,
    -- two independent, reproducible uniform draws per order
    MOD(ABS(FARM_FINGERPRINT(CAST(o.order_id AS STRING))), 10000) / 10000.0          AS u1,
    MOD(ABS(FARM_FINGERPRINT(CONCAT('b', CAST(o.order_id AS STRING)))), 10000) / 10000.0 AS u2,
    p.*
  FROM order_level AS o
  CROSS JOIN params AS p
  JOIN `bigquery-public-data.thelook_ecommerce.users` AS u ON u.id = o.user_id
  WHERE o.order_date BETWEEN DATE_SUB(p.launch_date, INTERVAL 12 MONTH)
                         AND DATE_ADD(p.launch_date, INTERVAL 12 MONTH)
),

scored AS (
  SELECT
    *,
    (post AND rev >= near_threshold_floor AND rev < thr AND u1 < topup_rate)  AS topped_up,
    IF(post AND rev >= near_threshold_floor AND rev < thr AND u1 < topup_rate,
       thr + u2 * 20, rev)                                                    AS sim_rev
  FROM sim
),

final AS (
  SELECT
    *,
    cogs * SAFE_DIVIDE(sim_rev, rev)                                           AS sim_cogs,
    -- the business absorbs every parcel on an eligible post-launch order
    IF(post AND sim_rev >= thr,
       shipments * IF(domestic, cost_per_shipment_domestic,
                                cost_per_shipment_international), 0)           AS shipping_absorbed
  FROM scored
)

SELECT
  DATE_TRUNC(order_date, MONTH)                                        AS month,
  IF(LOGICAL_OR(post), 'post', 'pre')                                  AS period,
  COUNT(*)                                                             AS orders,
  COUNTIF(topped_up)                                                   AS simulated_top_ups,
  -- actual
  ROUND(100 * COUNTIF(rev >= thr) / COUNT(*), 2)            AS pct_ge_100_actual,
  ROUND(AVG(rev), 2)                                                   AS aov_actual,
  ROUND(SUM(rev), 2)                                                   AS revenue_actual,
  ROUND(SUM(rev - cogs), 2)                                            AS gross_profit_actual,
  -- simulated
  ROUND(100 * COUNTIF(sim_rev >= thr) / COUNT(*), 2)        AS pct_ge_100_sim,
  ROUND(AVG(sim_rev), 2)                                               AS aov_sim,
  ROUND(SUM(sim_rev), 2)                                               AS revenue_sim,
  ROUND(SUM(sim_rev - sim_cogs), 2)                                    AS gross_profit_sim,
  ROUND(SUM(shipping_absorbed), 2)                                     AS shipping_absorbed_sim,
  ROUND(SUM(sim_rev - sim_cogs - shipping_absorbed), 2)                AS gross_profit_after_shipping_sim
FROM final
GROUP BY month
ORDER BY month;
