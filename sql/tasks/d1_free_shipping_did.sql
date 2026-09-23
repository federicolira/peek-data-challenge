WITH params AS (
  SELECT DATE '2022-01-15' AS launch_date, 100.0 AS thr, 90 AS window_days
),
order_level AS (
  SELECT oi.order_id,
         ANY_VALUE(oi.user_id)    AS user_id,
         DATE(MIN(oi.created_at)) AS order_date,
         SUM(oi.sale_price)       AS order_revenue,
         SUM(ii.cost)             AS order_cogs,
         COUNT(*)                 AS units
  FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
  JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
    ON ii.id = oi.inventory_item_id
  WHERE oi.status = 'Complete' AND oi.returned_at IS NULL
  GROUP BY oi.order_id
)
SELECT
  IF(o.order_revenue >= p.thr, 'treated_ge_100', 'control_lt_100') AS cohort,
  IF(o.order_date >= p.launch_date, 'post', 'pre')                 AS period,
  COUNT(*)                                           AS orders,
  ROUND(SUM(o.order_revenue), 2)                     AS revenue,
  ROUND(AVG(o.order_revenue), 2)                     AS aov,
  ROUND(SUM(o.order_revenue) - SUM(o.order_cogs), 2) AS gross_profit,
  ROUND(SAFE_DIVIDE(SUM(o.order_revenue)-SUM(o.order_cogs),
                    NULLIF(SUM(o.order_revenue),0))*100, 2) AS gross_margin_pct,
  ROUND(AVG(o.units), 2)                             AS avg_units
FROM order_level AS o CROSS JOIN params AS p
WHERE o.order_date BETWEEN DATE_SUB(p.launch_date, INTERVAL p.window_days DAY)
                       AND DATE_ADD(p.launch_date, INTERVAL p.window_days DAY)
GROUP BY cohort, period
ORDER BY cohort, period DESC
