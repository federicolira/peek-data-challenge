"""
deploy_looker_views.py - create the curated BigQuery views behind the Looker Studio
dashboard, then print a link that opens a new report already connected to them.

    python deploy_looker_views.py                 # dataset: peek_challenge
    python deploy_looker_views.py my_dataset

The project comes from BQ_PROJECT or `gcloud config`. The views live next to the
public dataset's location (US) and read it directly - nothing is copied.
"""

import pathlib
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from run_query import project, run  # noqa: E402

ROOT = pathlib.Path(__file__).parent
VIEWS = ["v_sales", "v_monthly_kpis", "v_cohort_retention", "v_cohort_repeat",
         "v_lifecycle_funnel", "v_data_health"]


def main():
    proj = project()
    dataset = sys.argv[1] if len(sys.argv) > 1 else "peek_challenge"

    run(f"CREATE SCHEMA IF NOT EXISTS `{proj}.{dataset}` OPTIONS (location = 'US', "
        f"description = 'Curated views over bigquery-public-data.thelook_ecommerce for the "
        f"Peek BI challenge dashboard. Definitions and guards match sql/part1_queries.sql.')")
    print(f"  dataset {proj}.{dataset} ready")
    run(f"DROP VIEW IF EXISTS `{proj}.{dataset}.v_orders`")   # superseded by v_sales

    for path in sorted((ROOT / "sql" / "looker").glob("*.sql")):
        sql = path.read_text(encoding="utf-8").replace("__PROJECT__", proj).replace("__DATASET__", dataset)
        run(sql)
        print(f"  created {path.stem[3:]}")

    # Linking API: without a template report (c.reportId) only ONE data source can be
    # attached, with no alias. Aliased sources (ds.ds0.*, ds.ds1.*) are rejected with
    # "ds0 is not a valid data source alias" unless a template defines those aliases.
    # So the link opens the report on v_sales; the other views are added in the UI.
    params = {"r.reportName": "Peek - Business Health (theLook)", "c.mode": "edit",
              "ds.connector": "bigQuery", "ds.type": "TABLE", "ds.projectId": proj,
              "ds.datasetId": dataset, "ds.tableId": VIEWS[0], "ds.billingProjectId": proj}
    url = "https://lookerstudio.google.com/reporting/create?" + urllib.parse.urlencode(params)
    print("\n  1. Open this link - it creates the report connected to v_sales:\n")
    print("  " + url)
    print("\n  2. In the report: Add data > BigQuery > My projects > "
          f"{proj} > {dataset}, and add: " + ", ".join(VIEWS[1:]))


if __name__ == "__main__":
    main()
