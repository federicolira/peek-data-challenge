"""
run_all.py - regenerate EVERY query output in data/ in one pass, on one as-of date.

    python run_all.py              # then: python analysis/build_deck.py

Why this exists: the queries window on CURRENT_DATE(), which BigQuery evaluates
in UTC. Running them one by one across a session can straddle UTC midnight and
leave the CSVs on two different as-of dates (this happened while building the
repo: one count moved from 84,991 to 85,017). Running everything together, and
recording the date, makes data/ a single consistent snapshot.

To pin a past snapshot instead of "today", replace CURRENT_DATE() in the params
CTEs with a literal date - the one place each query takes its cutoff.
"""

import csv
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from run_query import run  # noqa: E402

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "data"

# Part 1 statements, in file order, and the CSV each one feeds.
PART1 = ["a_monthly_financials", "b_new_vs_returning", "c_churn_90d", "c2_cohort_retention",
         "d1_free_shipping_did", "d2_free_shipping_monthly", "d3_shipping_zone",
         "d4_simulated_impact", "d5_break_even",
         "qa1_boundaries", "qa2_fanout", "qa3_status_mix", "qa4_identity_violations"]


def save(name, cols, rows):
    with open(DATA / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


def statements(path):
    src = path.read_text(encoding="utf-8")
    no_comments = "\n".join(line.split("--", 1)[0] for line in src.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def sync_tasks():
    """Write sql/tasks/*.sql FROM part1_queries.sql, comments included, so the
    per-task copies can never drift from the deliverable."""
    src = (ROOT / "sql" / "part1_queries.sql").read_text(encoding="utf-8")
    # a statement ends at a CODE line ending in ';' — comment lines may contain
    # semicolons (e.g. the DECLARE example in the header) and must not split
    chunks, buf = [], []
    for line in src.splitlines():
        buf.append(line)
        if not line.lstrip().startswith("--") and line.rstrip().endswith(";"):
            chunks.append("\n".join(buf).strip() + "\n")
            buf = []
    if len(chunks) != len(PART1):
        sys.exit(f"could not split part1_queries.sql into {len(PART1)} statements")
    out = ROOT / "sql" / "tasks"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.sql"):
        old.unlink()
    for name, chunk in zip(PART1, chunks):
        if name.startswith("qa"):
            continue
        (out / f"{name}.sql").write_text(
            f"-- Generated from sql/part1_queries.sql by run_all.py - edit that file, not this one.\n\n"
            + chunk, encoding="utf-8")
    print(f"  synced sql/tasks/ from part1_queries.sql")


def main():
    DATA.mkdir(exist_ok=True)
    sync_tasks()
    if "--sync-only" in sys.argv:
        return
    total = 0

    cols, rows, _ = run("SELECT CURRENT_DATE() AS as_of_date_utc, "
                        "MAX(DATE(created_at)) AS last_row_date "
                        "FROM `bigquery-public-data.thelook_ecommerce.order_items`")
    save("_as_of", cols + ["generated_at_utc"],
         [rows[0] + [dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")]])
    print(f"  as-of date (UTC): {rows[0][0]}   last row in data: {rows[0][1]}")

    stmts = statements(ROOT / "sql" / "part1_queries.sql")
    if len(stmts) != len(PART1):
        sys.exit(f"part1_queries.sql has {len(stmts)} statements, expected {len(PART1)}")
    for name, sql in zip(PART1, stmts):
        cols, rows, b = run(sql)
        save(name, cols, rows)
        total += b
        print(f"  {name:<30} {len(rows):>6} rows  {b / 1e6:>6.1f} MB")

    for path in sorted((ROOT / "sql" / "analysis").glob("*.sql")):
        cols, rows, b = run(path.read_text(encoding="utf-8"))
        save(path.stem, cols, rows)
        total += b
        print(f"  {path.stem:<30} {len(rows):>6} rows  {b / 1e6:>6.1f} MB")

    print(f"\n  total scanned: {total / 1e6:.0f} MB")
    violations = list(csv.reader(open(DATA / "qa4_identity_violations.csv", encoding="utf-8")))
    if len(violations) > 1:
        sys.exit("  QA.4 FAILED: new + returning != active in some month")
    print("  QA.4 passed: new + returning = active in every month")


if __name__ == "__main__":
    main()
