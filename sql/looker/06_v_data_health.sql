-- ---------------------------------------------------------------------------
-- v_data_health — the QA checks, live, as one row the dashboard can show.
-- Every value is recomputed on each refresh, so the "trust" strip on the
-- dashboard is a real test, not a caption.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW `__PROJECT__.__DATASET__.v_data_health`
OPTIONS (description = "Live data-quality checks: as-of date, last complete month, future-dated rows excluded, join fan-out check, and the new + returning = active identity. Recomputed on every refresh.")
AS
WITH bounds AS (
  SELECT
    CURRENT_DATE()                                                    AS as_of_date_utc,
    DATE_SUB(DATE_TRUNC(DATE(MAX(created_at)), MONTH), INTERVAL 1 MONTH) AS last_complete_month,
    COUNTIF(DATE(created_at) > CURRENT_DATE())                        AS future_dated_rows_excluded
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
),

fanout AS (
  SELECT
    (SELECT COUNT(*) FROM `bigquery-public-data.thelook_ecommerce.order_items`
      WHERE status = 'Complete' AND returned_at IS NULL)
    =
    (SELECT COUNT(*)
       FROM `bigquery-public-data.thelook_ecommerce.order_items` AS oi
       JOIN `bigquery-public-data.thelook_ecommerce.inventory_items` AS ii
         ON ii.id = oi.inventory_item_id
      WHERE oi.status = 'Complete' AND oi.returned_at IS NULL)        AS join_fanout_ok
),

identity AS (
  SELECT COUNTIF(active_customers <> new_customers + returning_customers) = 0
                                                                      AS new_plus_returning_equals_active
  FROM `__PROJECT__.__DATASET__.v_monthly_kpis`
)

SELECT
  b.as_of_date_utc,
  b.last_complete_month,
  b.future_dated_rows_excluded,
  f.join_fanout_ok,
  i.new_plus_returning_equals_active,
  (f.join_fanout_ok AND i.new_plus_returning_equals_active)           AS all_checks_pass
FROM bounds AS b, fanout AS f, identity AS i
