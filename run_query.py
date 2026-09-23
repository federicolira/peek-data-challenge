"""
run_query.py - run a BigQuery Standard SQL file and save the result as CSV.

Why this exists instead of the `bq` CLI: the bundled bq.cmd wrapper breaks on
the space in "Cloud SDK" on this machine. This talks to the BigQuery REST API
directly, using a short-lived token minted by gcloud, so there is no service
account key anywhere on disk and nothing credential-shaped to commit.

    python run_query.py sql/tasks/a_monthly_financials.sql data/a_monthly.csv
    python run_query.py --sql "SELECT 1"

Requires only the standard library plus an authenticated gcloud.
"""

import csv
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import os
import shutil

# Nothing is hard-coded to one machine: the project comes from the
# environment or from `gcloud config`, and gcloud is found on PATH.
# On Windows the .cmd wrapper is the one that works — the .ps1 is blocked
# when PowerShell script execution is Restricted.
GCLOUD = (shutil.which("gcloud.cmd") or shutil.which("gcloud")
          or r"C:\Users\%s\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
             % os.environ.get("USERNAME", ""))


def _gcloud(*args) -> str:
    return subprocess.run([GCLOUD, *args],
                          capture_output=True, text=True).stdout.strip()


def project() -> str:
    """BQ_PROJECT if set, else whatever gcloud is configured with."""
    p = os.environ.get("BQ_PROJECT") or _gcloud("config", "get-value", "project")
    if not p or p == "(unset)":
        sys.exit("Sin proyecto. Corre:  gcloud config set project <tu-proyecto>\n"
                 "o exporta BQ_PROJECT=<tu-proyecto>")
    return p


def token() -> str:
    """A short-lived OAuth token from the logged-in gcloud account.

    Deliberately NOT a service account key: nothing credential-shaped ever
    touches the disk, so there is nothing to accidentally commit.
    """
    t = _gcloud("auth", "print-access-token")
    if not t:
        sys.exit("No se pudo obtener token. Corre:  gcloud auth login")
    return t


def api() -> str:
    return ("https://bigquery.googleapis.com/bigquery/v2/projects/"
            f"{project()}/queries")


def run(sql: str, timeout_ms: int = 120000):
    """Returns (columns, rows, bytes_billed). Follows pagination."""
    body = {
        "query": sql,
        "useLegacySql": False,
        "timeoutMs": timeout_ms,
        "maxResults": 20000,
    }
    endpoint = api()
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token()}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(detail)["error"]["message"]
        except Exception:
            msg = detail
        sys.exit(f"\nBigQuery rechazo la consulta:\n  {msg}\n")

    if res.get("errors"):
        sys.exit("BigQuery: " + json.dumps(res["errors"], indent=2))

    cols = [f["name"] for f in res.get("schema", {}).get("fields", [])]
    rows = [[c.get("v") for c in r.get("f", [])] for r in res.get("rows", [])]

    # page through the rest, if any
    job = res.get("jobReference", {})
    page = res.get("pageToken")
    while page:
        url = (f"{endpoint}/{job['jobId']}?pageToken={page}"
               f"&location={job.get('location', 'US')}&maxResults=20000")
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token()}"})
        with urllib.request.urlopen(req) as r:
            nxt = json.load(r)
        rows += [[c.get("v") for c in x.get("f", [])] for x in nxt.get("rows", [])]
        page = nxt.get("pageToken")

    return cols, rows, int(res.get("totalBytesProcessed", 0))


def show(cols, rows, limit=25):
    if not cols:
        print("  (sin resultados)")
        return
    shown = rows[:limit]
    grid = [cols] + [["NULL" if v is None else str(v) for v in r] for r in shown]
    w = [max(len(g[i]) for g in grid) for i in range(len(cols))]
    print("\n  " + "  ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
    print("  " + "  ".join("-" * x for x in w))
    for r in grid[1:]:
        print("  " + "  ".join(v.ljust(w[i]) for i, v in enumerate(r)))
    if len(rows) > limit:
        print(f"  ... {len(rows):,} filas en total ({limit} mostradas)")


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)

    if a[0] == "--sql":
        sql, out = a[1], None
    else:
        sql = Path(a[0]).read_text(encoding="utf-8")
        out = a[1] if len(a) > 1 else None

    cols, rows, scanned = run(sql)
    show(cols, rows)
    print(f"\n  {len(rows):,} filas  |  {scanned/1e6:.1f} MB escaneados")

    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(cols)
            wr.writerows(rows)
        print(f"  -> {p}")


if __name__ == "__main__":
    main()
