-- ---------------------------------------------------------------------------
-- v_sales — the self-service fact view for Looker Studio.
-- GRAIN: one row per COMPLETED line item (status = 'Complete' AND returned_at
-- IS NULL) — the same grain and month convention as Tasks A and B, so every
-- revenue, order and new/returning figure on the dashboard reconciles exactly
-- with sql/part1_queries.sql. Order-level attributes (parcels, basket size) are
-- attached to each of the order's lines.
--
-- Why line-item grain and not order grain: the items of one order carry
-- different timestamps (up to ~4 days apart), and 572 orders straddle two
-- months. An order-grain view dated by its first item disagreed with Task A by
-- up to 2% in a month. One dashboard must never show two revenue figures for
-- the same month.
--
-- Derived metrics to create in Looker Studio:
--   Orders         = COUNT_DISTINCT(order_id)
--   AOV            = SUM(revenue) / COUNT_DISTINCT(order_id)
--   Gross margin % = SUM(gross_profit) / SUM(revenue)
-- __PROJECT__ and __DATASET__ are filled in by deploy_looker_views.py.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW `__PROJECT__.__DATASET__.v_sales`
OPTIONS (description = "One row per completed line item (status Complete, not returned), same grain and month as Tasks A-B. Excludes the partial current month and future-dated rows. Orders = COUNT_DISTINCT(order_id); AOV = SUM(revenue) / COUNT_DISTINCT(order_id). customer_type: New in the month of the customer's first completed order, else Returning.")
AS
WITH params AS (
  SELECT
    DATE_TRUNC(DATE(MAX(created_at)), MONTH)     AS current_month,
    LEAST(DATE(MAX(created_at)), CURRENT_DATE()) AS max_observable
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

items AS (
  SELECT
    oi.id                                            AS line_item_id,
    oi.order_id,
    oi.user_id,
    DATE(oi.created_at)                              AS sale_date,
    DATE_TRUNC(DATE(oi.created_at), MONTH)           AS month,
    oi.sale_price,
    ii.cost,
    ii.product_category                              AS category,
    ii.product_distribution_center_id                AS dc
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
    ON ii.id = oi.inventory_item_id                  -- verified 1:1, no fan-out
  CROSS JOIN params AS p
  WHERE oi.status = 'Complete'
    AND oi.returned_at IS NULL
    AND DATE_TRUNC(DATE(oi.created_at), MONTH) < p.current_month
    AND DATE(oi.created_at) <= p.max_observable
),

order_attrs AS (
  SELECT order_id, SUM(sale_price) AS order_value, COUNT(DISTINCT dc) AS parcels
  FROM items
  GROUP BY order_id
),

first_purchase AS (
  SELECT user_id, MIN(month) AS cohort_month FROM items GROUP BY user_id
)

SELECT
  i.line_item_id,
  i.order_id,
  i.user_id,
  i.sale_date,
  i.month,
  ROUND(i.sale_price, 2)                                                 AS revenue,
  ROUND(i.cost, 2)                                                       AS cogs,
  ROUND(i.sale_price - i.cost, 2)                                        AS gross_profit,
  i.category,
  oa.parcels                                                             AS order_parcels,
  oa.parcels > 1                                                         AS is_split_shipment,
  oa.order_value >= 100                                                  AS order_ge_100,
  f.cohort_month,
  DATE_DIFF(i.month, f.cohort_month, MONTH)                              AS months_since_first,
  IF(i.month = f.cohort_month, 'New', 'Returning')                       AS customer_type,
  u.country,
  IF(u.country = 'United States', 'Domestic', 'International')          AS shipping_zone,
  u.traffic_source
FROM items AS i
JOIN order_attrs    AS oa USING (order_id)
JOIN first_purchase AS f  USING (user_id)
JOIN `bigquery-public-data.thelook_ecommerce.users` AS u ON u.id = i.user_id
