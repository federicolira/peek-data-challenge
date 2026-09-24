"""
deploy_looker_views.py - create the curated BigQuery views behind the Looker Studio
dashboard, then print a link that opens a new report connected to them.

    python deploy_looker_views.py            # views read <project>.thelook_snapshot (default)
    python deploy_looker_views.py --live     # views read the live public dataset

Default is the frozen snapshot (make_snapshot.py): theLook regenerates its whole
history daily, so a dashboard on the live tables drifts away from the deck within a
day. On the snapshot, every dashboard figure matches the repo's outputs permanently.
The SQL files in sql/looker/ name the public dataset and CURRENT_DATE(); the snapshot
table names and the snapshot's as-of date are substituted at deploy time.
"""

import pathlib
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from run_query import project, run  # noqa: E402

ROOT = pathlib.Path(__file__).parent
DATASET = "peek_challenge"
VIEWS = ["v_sales", "v_monthly_kpis", "v_cohort_retention", "v_cohort_repeat",
         "v_lifecycle_funnel", "v_data_health"]


def main():
    proj = project()
    live = "--live" in sys.argv

    if live:
        rewrite = lambda s: s
        source = "the live public dataset"
    else:
        _, rows, _ = run(f"SELECT CAST(as_of_date AS STRING) FROM `{proj}.thelook_snapshot._snapshot_meta`")
        as_of = rows[0][0]
        rewrite = lambda s: (s.replace("`bigquery-public-data.thelook_ecommerce.", f"`{proj}.thelook_snapshot.")
                              .replace("CURRENT_DATE()", f"DATE '{as_of}'"))
        source = f"{proj}.thelook_snapshot (as of {as_of})"

    run(f"CREATE SCHEMA IF NOT EXISTS `{proj}.{DATASET}` OPTIONS (location = 'US', "
        f"description = 'Curated views for the Peek BI challenge dashboard. Definitions and "
        f"guards match sql/part1_queries.sql.')")
    run(f"DROP VIEW IF EXISTS `{proj}.{DATASET}.v_orders`")   # superseded by v_sales
    print(f"  views read {source}")

    for path in sorted((ROOT / "sql" / "looker").glob("*.sql")):
        sql = path.read_text(encoding="utf-8").replace("__PROJECT__", proj).replace("__DATASET__", DATASET)
        run(rewrite(sql))
        print(f"  created {path.stem[3:]}")

    # Linking API: without a template report (c.reportId) only ONE data source can be
    # attached, with no alias. Aliased sources (ds.ds0.*, ds.ds1.*) are rejected with
    # "ds0 is not a valid data source alias" unless a template defines those aliases.
    params = {"r.reportName": "Peek - Business Health (theLook)", "c.mode": "edit",
              "ds.connector": "bigQuery", "ds.type": "TABLE", "ds.projectId": proj,
              "ds.datasetId": DATASET, "ds.tableId": VIEWS[0], "ds.billingProjectId": proj}
    url = "https://lookerstudio.google.com/reporting/create?" + urllib.parse.urlencode(params)
    print("\n  1. Open this link - it creates the report connected to v_sales:\n")
    print("  " + url)
    print("\n  2. In the report: Add data > BigQuery > My projects > "
          f"{proj} > {DATASET}, and add: " + ", ".join(VIEWS[1:]))


if __name__ == "__main__":
    main()
