-- Does order status move through a lifecycle, or is it assigned at random?
-- If it were a lifecycle, 2019 orders would all be Complete or Returned by now.
-- Result: the mix is ~flat every year (~25% Complete, ~30% Shipped, ~20% Processing),
-- so 'Complete' behaves like a random 25% sample of orders.
SELECT
  EXTRACT(YEAR FROM created_at) AS year,
  COUNT(*) AS items,
  ROUND(100*COUNTIF(status='Complete')/COUNT(*),1)   AS pct_complete,
  ROUND(100*COUNTIF(status='Shipped')/COUNT(*),1)    AS pct_shipped,
  ROUND(100*COUNTIF(status='Processing')/COUNT(*),1) AS pct_processing,
  ROUND(100*COUNTIF(status='Cancelled')/COUNT(*),1)  AS pct_cancelled,
  ROUND(100*COUNTIF(status='Returned')/COUNT(*),1)   AS pct_returned
FROM `bigquery-public-data.thelook_ecommerce.order_items`
WHERE DATE(created_at) <= CURRENT_DATE()
GROUP BY year ORDER BY year
