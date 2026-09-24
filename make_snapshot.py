"""
make_snapshot.py - freeze theLook as it was at one moment, in your own project.

    python make_snapshot.py                                  # the snapshot behind this repo
    python make_snapshot.py "2026-09-24 00:40:00+00" 2026-09-24

Why: theLook does not append data - it REGENERATES the whole dataset (observed at
2026-09-24 03:35 UTC: every month's values changed, row count 181,415 -> 180,925).
Numbers computed on one day cannot be reproduced on the next. BigQuery time travel
can read a table as it was up to 7 days back, so this copies the seven tables
FOR SYSTEM_TIME AS OF the moment data/ was produced into `<project>.thelook_snapshot`,
plus a one-row _snapshot_meta table with the as-of date the queries should use in
place of CURRENT_DATE().

After this, `run_all.py --snapshot` and `deploy_looker_views.py` read the frozen
copy, so the CSVs, the deck and the dashboard all describe the same data forever.
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from run_query import project, run  # noqa: E402

TABLES = ["order_items", "orders", "users", "products", "inventory_items",
          "distribution_centers", "events"]
SNAPSHOT_TS = "2026-09-24 00:40:00+00"    # just before data/ was produced (00:42 UTC)
AS_OF_DATE = "2026-09-24"                  # CURRENT_DATE() in UTC at that moment


def main():
    ts = sys.argv[1] if len(sys.argv) > 1 else SNAPSHOT_TS
    as_of = sys.argv[2] if len(sys.argv) > 2 else AS_OF_DATE
    proj = project()
    ds = f"{proj}.thelook_snapshot"
    run(f"CREATE SCHEMA IF NOT EXISTS `{ds}` OPTIONS (location = 'US', description = "
        f"'theLook frozen with time travel AS OF {ts}. theLook regenerates daily; this copy "
        f"keeps the repo, the deck and the dashboard reproducible.')")
    for t in TABLES:
        run(f"CREATE OR REPLACE TABLE `{ds}.{t}` AS SELECT * FROM "
            f"`bigquery-public-data.thelook_ecommerce.{t}` FOR SYSTEM_TIME AS OF TIMESTAMP '{ts}'")
        _, rows, _ = run(f"SELECT COUNT(*) FROM `{ds}.{t}`")
        print(f"  {t:<22} {int(rows[0][0]):>10,} rows")
    run(f"CREATE OR REPLACE TABLE `{ds}._snapshot_meta` AS SELECT TIMESTAMP '{ts}' AS snapshot_ts, "
        f"DATE '{as_of}' AS as_of_date")
    print(f"\n  snapshot {ds} as of {ts}  (queries use as-of date {as_of})")


if __name__ == "__main__":
    main()
