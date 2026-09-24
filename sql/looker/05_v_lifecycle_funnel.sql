-- ---------------------------------------------------------------------------
-- v_lifecycle_funnel — the user-level funnel, in long format for a bar chart.
-- GRAIN: one row per (traffic_source, country, stage). Each stage is a strict
-- subset of the one before. Accounts at least 365 days old only, so every
-- stage has had a full year to happen.
-- In Looker: bar chart, dimension = stage (sorts correctly: names are numbered),
-- metric = SUM(users); traffic_source and country work as filters.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW `__PROJECT__.__DATASET__.v_lifecycle_funnel`
OPTIONS (description = "Customer lifecycle funnel for accounts at least a year old: 1 signed up, 2 placed an order, 3 activated (first completed order), 4 second order (activated and 2+ valid orders). Long format; each stage is a subset of the one before.")
AS
WITH u AS (
  SELECT id AS user_id, traffic_source, country
  FROM `bigquery-public-data.thelook_ecommerce.users`
  WHERE DATE(created_at) <= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
),

per_user AS (
  SELECT
    user_id,
    COUNT(DISTINCT order_id)                                                         AS any_orders,
    COUNT(DISTINCT IF(status = 'Complete' AND returned_at IS NULL, order_id, NULL))  AS completed_orders,
    COUNT(DISTINCT IF(status NOT IN ('Cancelled', 'Returned'), order_id, NULL))      AS valid_orders
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
  WHERE DATE(created_at) <= CURRENT_DATE()
  GROUP BY user_id
),

agg AS (
  SELECT
    u.traffic_source,
    u.country,
    COUNT(*)                                                                         AS s1,
    COUNTIF(COALESCE(p.any_orders, 0) >= 1)                                          AS s2,
    COUNTIF(COALESCE(p.completed_orders, 0) >= 1)                                    AS s3,
    COUNTIF(COALESCE(p.completed_orders, 0) >= 1 AND COALESCE(p.valid_orders, 0) >= 2) AS s4
  FROM u
  LEFT JOIN per_user AS p USING (user_id)
  GROUP BY u.traffic_source, u.country
)

SELECT a.traffic_source, a.country, s.stage_order, s.stage, s.users
FROM agg AS a,
UNNEST([
  STRUCT(1 AS stage_order, '1. Signed up'                          AS stage, a.s1 AS users),
  STRUCT(2 AS stage_order, '2. Placed an order'                    AS stage, a.s2 AS users),
  STRUCT(3 AS stage_order, '3. Activated (first completed order)'  AS stage, a.s3 AS users),
  STRUCT(4 AS stage_order, '4. Second order'                       AS stage, a.s4 AS users)
]) AS s
