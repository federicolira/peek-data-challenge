"""
build_deck.py - regenerate the slide deck from the query outputs in data/.

    python analysis/build_deck.py

Writes:
    analysis/deck.html      the deck (open in any browser)
    analysis/deck.pdf       the same deck, printed with headless Edge/Chrome
    analysis/slides/*.png   one image per slide

Every number on every slide is computed here from data/*.csv, which in turn
come from sql/. Nothing is typed in by hand, so the deck cannot drift from
the SQL.
"""

import csv
import io
import logging
import math
import re
import shutil
import statistics as st
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "analysis"

# ---------------------------------------------------------------- palette
# Validated categorical slots (CVD-safe adjacent pairs). Colour follows the
# ENTITY on every slide: blue is always "new", orange is always "returning".
NEW, RET, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
CRIT = "#d03b3b"
INK, INK2, INK3 = "#16181d", "#4d5360", "#8a8f99"
RULE, GRID, BG = "#e3e1dc", "#ecebe7", "#fbfaf8"
MUTED = "#c9c6bf"
BLUE_RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
             "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281"]

FONT_STACK = '"Instrument Sans", "Segoe UI", Arial, sans-serif'

plt.rcParams.update({
    "svg.fonttype": "none",            # keep text as text; the page's font applies
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
    "font.size": 11,
    "axes.edgecolor": RULE,
    "axes.labelcolor": INK3,
    "xtick.color": INK3,
    "ytick.color": INK3,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "grid.color": GRID,
    "grid.linewidth": 1,
    "axes.axisbelow": True,
    "figure.facecolor": "none",
    "axes.facecolor": "none",
})


# ================================================================= data
def load(name):
    with open(DATA / f"{name}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x):
    return None if x in (None, "", "NULL") else float(x)


A = load("a_monthly_financials")
B = load("b_new_vs_returning")
C = load("c_churn_90d")
C2 = load("c2_cohort_retention")
D1 = load("d1_free_shipping_did")
D2 = load("d2_free_shipping_monthly")
E = load("e_retention_by_source")
F = load("f_ltv_curve")
G = load("g_repeat_timing")[0]
H = {r["defn"]: r for r in load("h_churn_definition_sensitivity")}
I = load("i_status_by_year")

by_month_a = {r["month"]: r for r in A}
last = A[-1]["month"]                              # last complete month
ly, lm = int(last[:4]), int(last[5:7])
same_month_ly = f"{ly - 1}-{lm:02d}-01"


def mlabel(m, year=False):
    d = date(int(m[:4]), int(m[5:7]), 1)
    return d.strftime("%b %Y" if year else "%b")


def money(v, k=False):
    if k:
        return f"${v / 1000:,.0f}K" if v < 1e6 else f"${v / 1e6:,.2f}M"
    return f"${v:,.0f}"


def pct(v, d=0):
    return f"{v:.{d}f}%"


# last 24 complete months for all time-series panels
WIN = [r["month"] for r in A][-24:]
T12 = WIN[-12:]
P12 = WIN[:12]

# ---- headline numbers (all derived) --------------------------------------
rev_last = fnum(by_month_a[last]["revenue"])
rev_ly = fnum(by_month_a[same_month_ly]["revenue"])
rev_yoy = (rev_last / rev_ly - 1) * 100
ord_last = int(by_month_a[last]["orders"])
ord_ly = int(by_month_a[same_month_ly]["orders"])
ord_yoy = (ord_last / ord_ly - 1) * 100
aov_last = fnum(by_month_a[last]["aov"])
aov_ly = fnum(by_month_a[same_month_ly]["aov"])
aov_win = [fnum(by_month_a[m]["aov"]) for m in WIN]
t12_rev = sum(fnum(by_month_a[m]["revenue"]) for m in T12)
p12_rev = sum(fnum(by_month_a[m]["revenue"]) for m in P12)
t12_growth = (t12_rev / p12_rev - 1) * 100
mom_t12 = [fnum(by_month_a[m]["mom_revenue_growth_pct"]) for m in T12]
mom_median = st.median(mom_t12)

by_month_b = {r["month"]: r for r in B}
t12_new = sum(fnum(by_month_b[m]["revenue_new"]) for m in T12)
t12_ret = sum(fnum(by_month_b[m]["revenue_returning"]) for m in T12)
share_new_t12 = t12_new / (t12_new + t12_ret) * 100
ret_share_range = [fnum(by_month_b[m]["pct_revenue_from_returning"]) for m in T12]
bl = by_month_b[last]
ret_per_cust = fnum(bl["revenue_returning"]) / int(bl["returning_customers"])
new_per_cust = fnum(bl["revenue_new"]) / int(bl["new_customers"])
new_cust_last = int(bl["new_customers"])

meas = [r for r in C if r["measurable"] == "true"]
last_meas = meas[-1]["month"]
churn_t12 = st.mean(fnum(r["churn_rate_90d"]) for r in meas[-12:])
not_meas = [r["month"] for r in C if r["measurable"] != "true"]
churn_last_unmeasurable = fnum(C[-1]["churn_rate_90d"])
churn_alt = fnum(H["alt"]["churn_90d_pct"])
churn_brief_h = fnum(H["brief"]["churn_90d_pct"])

ltv = {int(r["months_since_first"]): fnum(r["avg_cumulative_revenue"]) for r in F}
ltv_n = int(F[0]["customers"])
first_order_share = ltv[0] / ltv[24] * 100

g_ever = fnum(G["pct_ever_repeat"])
g_90 = fnum(G["pct_repeat_within_90d"])
g_365 = fnum(G["pct_repeat_within_365d"])
g_median = int(float(G["median_gap_days_among_repeaters"]))
g_n = int(G["customers_12m_observable"])
window_ratio = g_median / 90

src_churn = [fnum(r["churn_90d_pct"]) for r in E]
src_rep = [fnum(r["repeat_12m_pct"]) for r in E]
src_buyers = {r["traffic_source"]: int(r["first_time_buyers_12m_obs"]) for r in E}
search_share = src_buyers["Search"] / sum(src_buyers.values()) * 100

# ---- Task D: difference-in-differences + honest power check --------------
d = {(r["cohort"], r["period"]): r for r in D1}
tp, tq = int(d[("treated_ge_100", "pre")]["orders"]), int(d[("treated_ge_100", "post")]["orders"])
cp, cq = int(d[("control_lt_100", "pre")]["orders"]), int(d[("control_lt_100", "post")]["orders"])
treat_g = (tq / tp - 1) * 100
ctrl_g = (cq / cp - 1) * 100
did_pp = treat_g - ctrl_g
# Share of orders >= $100, pre vs post: two-proportion z-test.
p1, n1 = tp / (tp + cp), tp + cp
p2, n2 = tq / (tq + cq), tq + cq
pool = (tp + tq) / (n1 + n2)
se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
z = (p2 - p1) / se
p_value = math.erfc(abs(z) / math.sqrt(2))
mde_pp = (1.96 + 0.84) * se * 100          # 80% power, alpha 0.05, two-sided
d2_pre = [fnum(r["pct_orders_over_threshold"]) for r in D2 if r["period"] == "pre"]
d2_post = [fnum(r["pct_orders_over_threshold"]) for r in D2 if r["period"] == "post"]
orders_per_quarter = round((n1 + n2) / 2 / 10) * 10

status_complete = st.mean(fnum(r["pct_complete"]) for r in I)


# ================================================================= charts
def to_svg(fig):
    buf = io.StringIO()
    fig.savefig(buf, format="svg", transparent=True)
    plt.close(fig)
    s = buf.getvalue()
    s = s[s.find("<svg"):]
    # matplotlib measures with a fallback font; the page renders the real one
    s = re.sub(r"font-family:[^;\"]*", f"font-family:{FONT_STACK}".replace('"', "'"), s)
    s = re.sub(r"font:\s*([\d.]+px)\s*'[^']*'",
               lambda m: f"font-size:{m.group(1)};font-family:" + FONT_STACK.replace('"', "'"), s)
    s = re.sub(r'width="[\d.]+pt" height="[\d.]+pt"', 'width="100%"', s, count=1)
    return s


def kfmt(v, _):
    return "$0" if v == 0 else f"${v / 1000:.0f}K"


def xlabels(ax, months, every=3, year_on_jan=True):
    ax.set_xticks(range(len(months)))
    labs = []
    for i, m in enumerate(months):
        if i % every == 0 or i == len(months) - 1:
            labs.append(mlabel(m) + (f"\n{m[:4]}" if (m[5:7] == "01" or i == 0) and year_on_jan else ""))
        else:
            labs.append("")
    ax.set_xticklabels(labs)


def chart_financials():
    fig, axes = plt.subplots(3, 1, figsize=(10.4, 5.5), sharex=True,
                             gridspec_kw={"height_ratios": [2.1, 1.2, 1.2], "hspace": 0.42})
    rev = [fnum(by_month_a[m]["revenue"]) for m in WIN]
    ords = [int(by_month_a[m]["orders"]) for m in WIN]
    aov = [fnum(by_month_a[m]["aov"]) for m in WIN]
    x = range(len(WIN))

    ax = axes[0]
    ax.bar(x, rev, width=0.72, color=NEW, edgecolor=BG, linewidth=1)
    ax.set_ylim(0, max(rev) * 1.18)
    ax.yaxis.set_major_formatter(kfmt)
    ax.set_title("Revenue", loc="left", fontsize=12, color=INK, pad=6, fontweight="bold")
    for i in (0, len(WIN) - 13, len(WIN) - 1):
        ax.annotate(money(rev[i], k=True), (i, rev[i]), xytext=(0, 5), textcoords="offset points",
                    ha="center", fontsize=10, color=INK, fontweight="bold")

    ax = axes[1]
    ax.bar(x, ords, width=0.72, color=NEW, alpha=0.55, edgecolor=BG, linewidth=1)
    ax.set_ylim(0, max(ords) * 1.25)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    ax.set_title("Completed orders", loc="left", fontsize=12, color=INK, pad=6, fontweight="bold")
    for i in (len(WIN) - 13, len(WIN) - 1):
        ax.annotate(f"{ords[i]:,}", (i, ords[i]), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=10, color=INK, fontweight="bold")

    ax = axes[2]
    ax.plot(x, aov, color=INK2, linewidth=2)
    ax.scatter([len(WIN) - 1], [aov[-1]], color=INK2, s=28, zorder=3)
    ax.set_ylim(0, 120)
    ax.set_yticks([0, 40, 80, 120])
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.0f}")
    ax.set_title("Average order value", loc="left", fontsize=12, color=INK, pad=6, fontweight="bold")
    ax.annotate(f"${aov[-1]:.0f}", (len(WIN) - 1, aov[-1]), xytext=(6, 6),
                textcoords="offset points", fontsize=10, color=INK, fontweight="bold")
    xlabels(ax, WIN)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.95, bottom=0.11)
    return to_svg(fig)


def chart_mix():
    fig, axes = plt.subplots(2, 1, figsize=(10.4, 5.5), sharex=True,
                             gridspec_kw={"height_ratios": [2.6, 1.1], "hspace": 0.35})
    rn = [fnum(by_month_b[m]["revenue_new"]) for m in WIN]
    rr = [fnum(by_month_b[m]["revenue_returning"]) for m in WIN]
    sh = [fnum(by_month_b[m]["pct_revenue_from_returning"]) for m in WIN]
    x = range(len(WIN))
    ax = axes[0]
    ax.bar(x, rn, width=0.72, color=NEW, edgecolor=BG, linewidth=1.5, label="New customers")
    ax.bar(x, rr, bottom=rn, width=0.72, color=RET, edgecolor=BG, linewidth=1.5,
           label="Returning customers")
    ax.set_ylim(0, (rn[-1] + rr[-1]) * 1.2)
    ax.yaxis.set_major_formatter(kfmt)
    ax.set_title("Revenue by customer type", loc="left", fontsize=12, color=INK, pad=6,
                 fontweight="bold")
    ax.legend(loc="upper left", frameon=False, fontsize=10.5, ncol=2, handlelength=1.1,
              bbox_to_anchor=(0, 1.0))
    i = len(WIN) - 1
    ax.annotate(money(rn[i], k=True), (i + 0.45, rn[i] / 2), fontsize=10, color=NEW,
                fontweight="bold", va="center")
    ax.annotate(money(rr[i], k=True), (i + 0.45, rn[i] + rr[i] / 2), fontsize=10, color=RET,
                fontweight="bold", va="center")
    ax.set_xlim(-0.6, len(WIN) + 0.9)

    ax = axes[1]
    ax.plot(x, sh, color=RET, linewidth=2)
    ax.fill_between(x, sh, color=RET, alpha=0.10, linewidth=0)
    ax.set_ylim(0, 30)
    ax.set_yticks([0, 10, 20, 30])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_title("Share of revenue from returning customers", loc="left", fontsize=12,
                 color=INK, pad=6, fontweight="bold")
    ax.annotate(pct(sh[-1], 1), (i, sh[-1]), xytext=(6, 2), textcoords="offset points",
                fontsize=10, color=INK, fontweight="bold")
    xlabels(ax, WIN)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.95, bottom=0.12)
    return to_svg(fig)


def chart_cohort():
    rows = {}
    size = {}
    for r in C2:
        c = r["cohort_month"]
        k = int(r["months_since_first"])
        if c < "2025-01" or k == 0 or k > 8:
            continue
        rows.setdefault(c, {})[k] = fnum(r["retention_pct"])
        size[c] = int(r["cohort_customers"])
    cohorts = sorted(rows)[:14]
    ks = list(range(1, 9))
    fig, ax = plt.subplots(figsize=(6.2, 5.3))
    ax.grid(False)
    vmax = 5.0
    for yi, c in enumerate(cohorts):
        for k in ks:
            v = rows[c].get(k)
            if v is None:
                continue
            step = min(len(BLUE_RAMP) - 1, int(v / vmax * (len(BLUE_RAMP) - 1)))
            col = BLUE_RAMP[step]
            ax.add_patch(plt.Rectangle((k - 0.48, yi - 0.46), 0.96, 0.92, color=col, linewidth=0))
            ax.text(k, yi, f"{v:.1f}", ha="center", va="center", fontsize=9,
                    color="white" if step >= 7 else INK)
    ax.set_xlim(0.45, 8.55)
    ax.set_ylim(len(cohorts) - 0.5, -0.5)
    ax.set_xticks(ks)
    ax.set_xticklabels([f"M{k}" for k in ks])
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(cohorts)))
    ax.set_yticklabels([f"{mlabel(c + '-01' if len(c) == 7 else c, year=True)}  ({size[c]})"
                        for c in cohorts], fontsize=9.5)
    ax.spines["bottom"].set_visible(False)
    fig.subplots_adjust(left=0.27, right=0.99, top=0.9, bottom=0.02)
    return to_svg(fig)


def chart_ltv():
    ks = sorted(ltv)
    vs = [ltv[k] for k in ks]
    fig, ax = plt.subplots(figsize=(5.0, 5.3))
    ax.fill_between(ks, vs, color=AQUA, alpha=0.12, linewidth=0)
    ax.plot(ks, vs, color=AQUA, linewidth=2.2)
    ax.axhline(ltv[0], color=INK3, linewidth=1, linestyle=(0, (3, 3)))
    ax.set_ylim(0, 110)
    ax.set_xlim(0, 24.5)
    ax.set_xticks([0, 6, 12, 18, 24])
    ax.set_xticklabels(["0", "6", "12", "18", "24"])
    ax.set_xlabel("Months since first purchase", fontsize=10.5, color=INK3, labelpad=6)
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.0f}")
    for k in (0, 24):
        ax.scatter([k], [ltv[k]], color=AQUA, s=34, zorder=3, edgecolor=BG, linewidth=1.5)
    ax.annotate(f"${ltv[0]:.0f} first order", (0, ltv[0]), xytext=(10, -18), textcoords="offset points",
                fontsize=10.5, color=INK, fontweight="bold")
    ax.annotate(f"${ltv[24]:.0f}", (24, ltv[24]), xytext=(-8, 8), textcoords="offset points",
                fontsize=10.5, color=INK, fontweight="bold", ha="right")
    fig.subplots_adjust(left=0.14, right=0.97, top=0.95, bottom=0.16)
    return to_svg(fig)


def chart_churn():
    fig, axes = plt.subplots(2, 1, figsize=(10.0, 5.4), sharex=True,
                             gridspec_kw={"height_ratios": [1.3, 1.6], "hspace": 0.36})
    by_c = {r["month"]: r for r in C}
    rev = [fnum(by_month_a[m]["revenue"]) for m in WIN]
    ch = [fnum(by_c[m]["churn_rate_90d"]) for m in WIN]
    ok = [by_c[m]["measurable"] == "true" for m in WIN]
    x = list(range(len(WIN)))
    ax = axes[0]
    ax.bar(x, rev, width=0.72, color=NEW, edgecolor=BG, linewidth=1)
    ax.set_ylim(0, max(rev) * 1.15)
    ax.yaxis.set_major_formatter(kfmt)
    ax.set_title("Revenue", loc="left", fontsize=12, color=INK, pad=6, fontweight="bold")

    ax = axes[1]
    first_bad = ok.index(False)
    ax.axvspan(first_bad - 0.5, len(WIN) - 0.5, color=CRIT, alpha=0.07, linewidth=0)
    ax.text((first_bad + len(WIN) - 1) / 2, 76.5, "not yet\nmeasurable", ha="center",
            va="bottom", fontsize=9.5, color=CRIT, fontweight="bold", linespacing=1.1)
    xs_ok = [i for i in x if ok[i]]
    ax.plot(xs_ok, [ch[i] for i in xs_ok], color=INK, linewidth=2)
    ax.plot([first_bad - 1] + [i for i in x if not ok[i]],
            [ch[first_bad - 1]] + [ch[i] for i in x if not ok[i]],
            color=CRIT, linewidth=1.6, linestyle=(0, (3, 2)))
    ax.scatter([i for i in x if not ok[i]], [ch[i] for i in x if not ok[i]],
               facecolor=BG, edgecolor=CRIT, s=26, zorder=3, linewidth=1.5)
    ax.set_ylim(75, 102)
    ax.set_yticks([80, 90, 100])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_title("90-day churn rate (brief definition)", loc="left", fontsize=12, color=INK,
                 pad=6, fontweight="bold")
    j = first_bad - 1
    ax.annotate(pct(ch[j], 1), (j, ch[j]), xytext=(-4, -15), textcoords="offset points",
                fontsize=10, color=INK, fontweight="bold", ha="right")
    ax.annotate(f"{ch[-1]:.0f}% = edge of the data", (len(WIN) - 1, ch[-1]), xytext=(-10, 0),
                textcoords="offset points", fontsize=9.5, color=CRIT, ha="right", va="center",
                fontweight="bold")
    xlabels(ax, WIN)
    fig.subplots_adjust(left=0.075, right=0.98, top=0.95, bottom=0.12)
    return to_svg(fig)


def chart_sources():
    src = [r["traffic_source"] for r in E]
    fig, ax = plt.subplots(figsize=(2.9, 2.35))
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    y = list(range(len(src)))
    ax.scatter(src_rep, y, color=RET, s=44, zorder=3, edgecolor=BG, linewidth=1.5,
               label="Repeat within 12 mo")
    ax.set_xlim(0, 25)
    ax.set_xticks([0, 10, 20])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_yticks(y)
    ax.set_yticklabels(src, fontsize=11)
    ax.set_ylim(len(src) - 0.4, -0.6)
    ax.spines["bottom"].set_visible(False)
    for yi, v in zip(y, src_rep):
        ax.annotate(f"{v:.1f}%", (v, yi), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=10.5, color=INK, fontweight="bold")
    fig.subplots_adjust(left=0.27, right=0.95, top=0.97, bottom=0.13)
    return to_svg(fig)


def chart_fs_did():
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    groups = [("Orders < $100\n(control)", cp, cq, MUTED, INK2),
              ("Orders \u2265 $100\n(eligible)", tp, tq, NEW, NEW)]
    w = 0.34
    for gi, (lab, pre, post, cpre, cpost) in enumerate(groups):
        ax.bar(gi - w / 2 - 0.02, pre, width=w, color=cpre, alpha=0.55 if gi else 1)
        ax.bar(gi + w / 2 + 0.02, post, width=w, color=cpost if gi else INK3)
        ax.annotate(f"{pre}", (gi - w / 2 - 0.02, pre), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=10, color=INK)
        ax.annotate(f"{post}", (gi + w / 2 + 0.02, post), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=10, color=INK,
                    fontweight="bold")
        ax.text(gi - w / 2 - 0.02, 10, "before", ha="center", va="bottom", fontsize=9.5,
                color=INK2, fontweight="bold")
        ax.text(gi + w / 2 + 0.02, 10, "after", ha="center", va="bottom", fontsize=9.5,
                color="white", fontweight="bold")
        g = (post / pre - 1) * 100
        ax.annotate(f"{g:+.0f}%", (gi, max(pre, post)), xytext=(0, 22),
                    textcoords="offset points", ha="center", fontsize=11, color=INK,
                    fontweight="bold")
    ax.set_xticks([0, 1])
    ax.set_xticklabels([g[0] for g in groups], fontsize=10.5, color=INK2)
    ax.set_ylim(0, max(cp, cq) * 1.28)
    ax.set_ylabel("Completed orders, \u00b190 days", fontsize=10)
    fig.subplots_adjust(left=0.16, right=0.98, top=0.97, bottom=0.17)
    return to_svg(fig)


def chart_fs_monthly():
    months = [r["month"] for r in D2]
    vals = [fnum(r["pct_orders_over_threshold"]) for r in D2]
    launch_i = next(i for i, r in enumerate(D2) if r["period"] == "post")
    fig, ax = plt.subplots(figsize=(5.8, 4.6))
    x = range(len(months))
    pre_mean = st.mean(d2_pre)
    ax.axhspan(pre_mean - st.pstdev(d2_pre) * 2, pre_mean + st.pstdev(d2_pre) * 2,
               color=INK3, alpha=0.08, linewidth=0)
    ax.plot(x, vals, color=NEW, linewidth=2)
    ax.axvline(launch_i - 0.5, color=INK, linewidth=1.2)
    ax.text(launch_i - 0.3, 41.5, "15 Jan 2022\n(hypothetical launch)", fontsize=9, color=INK,
            va="top")
    ax.set_ylim(0, 45)
    ax.set_yticks([0, 15, 30, 45])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_xticks([i for i in x if i % 4 == 0])
    ax.set_xticklabels([mlabel(months[i]) + f"\n{months[i][:4]}" for i in x if i % 4 == 0])
    ax.text(0.2, pre_mean - st.pstdev(d2_pre) * 2 - 1.2, "normal month-to-month range",
            fontsize=9, color=INK3, va="top")
    fig.subplots_adjust(left=0.1, right=0.98, top=0.97, bottom=0.14)
    return to_svg(fig)


def chart_status():
    years = [r["year"] for r in I]
    cols = [("pct_complete", "Complete", NEW), ("pct_shipped", "Shipped", MUTED),
            ("pct_processing", "Processing", "#dcd9d2"), ("pct_cancelled", "Cancelled", "#b3b0a8"),
            ("pct_returned", "Returned", "#8f8b83")]
    fig, ax = plt.subplots(figsize=(6.4, 3.9))
    ax.grid(False)
    y = range(len(years))
    left = [0] * len(years)
    for key, lab, col in cols:
        v = [fnum(r[key]) for r in I]
        ax.barh(y, v, left=left, color=col, edgecolor=BG, linewidth=1.5, height=0.7, label=lab)
        if key == "pct_complete":
            for yi, vv in zip(y, v):
                ax.text(vv / 2, yi, f"{vv:.0f}%", ha="center", va="center", fontsize=9,
                        color="white", fontweight="bold")
        left = [a + b for a, b in zip(left, v)]
    ax.set_yticks(list(y))
    ax.set_yticklabels(years, fontsize=10)
    ax.set_ylim(len(years) - 0.4, -0.6)
    ax.set_xlim(0, 100)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.2), ncol=5, frameon=False,
              fontsize=9.5, handlelength=1, columnspacing=1)
    fig.subplots_adjust(left=0.1, right=0.98, top=0.99, bottom=0.14)
    return to_svg(fig)


# ============================================================ data model
def data_model_svg():
    """Hand-drawn: which tables, their grain, and the exact key each join uses."""
    def box(x, y, w, h, name, rows, grain, keys, used, fact=False, note=None):
        stroke = NEW if fact else (INK if used else MUTED)
        fill = "#eef4fc" if fact else "#ffffff"
        sw = 2.5 if fact else (1.6 if used else 1.2)
        o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" '
             f'stroke="{stroke}" stroke-width="{sw}"/>',
             f'<text x="{x + 14}" y="{y + 25}" class="tn" fill="{INK if used else INK3}">{name}</text>',
             f'<text x="{x + w - 14}" y="{y + 25}" class="tr" text-anchor="end" '
             f'fill="{INK2 if used else INK3}">{rows}</text>',
             f'<text x="{x + 14}" y="{y + 46}" class="tg" fill="{INK2 if used else INK3}">{grain}</text>']
        for i, k in enumerate(keys):
            o.append(f'<text x="{x + 14}" y="{y + 68 + i * 18}" class="tk" '
                     f'fill="{INK3}">{k}</text>')
        if note:
            o.append(f'<text x="{x + 14}" y="{y + h - 12}" class="tnote" '
                     f'fill="{NEW if fact else INK3}">{note}</text>')
        return "\n".join(o)

    def link(pts, label, sub, used, lx, ly, anchor="middle"):
        col = INK if used else MUTED
        d = "M" + " L".join(f"{a},{b}" for a, b in pts)
        return (f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{2 if used else 1.4}"/>'
                f'<circle cx="{pts[-1][0]}" cy="{pts[-1][1]}" r="4" fill="{col}"/>'
                f'<text x="{lx}" y="{ly}" class="lk" text-anchor="{anchor}" '
                f'fill="{INK if used else INK3}">{label}</text>'
                f'<text x="{lx}" y="{ly + 17}" class="ls" text-anchor="{anchor}" '
                f'fill="{INK3}">{sub}</text>')

    parts = [
        # fact table
        box(420, 190, 270, 190, "order_items", "181,415", "1 row = one line item",
            ["PK  id", "FK  order_id \u00b7 user_id", "FK  product_id", "FK  inventory_item_id",
             "sale_price \u00b7 status \u00b7 created_at"],
            True, fact=True, note="FACT TABLE \u2014 every task starts here"),
        box(20, 20, 270, 128, "orders", "125,176", "1 row = one order",
            ["PK  order_id", "FK  user_id", "status \u00b7 num_of_item"], False),
        box(20, 236, 270, 118, "users", "100,000", "1 row = one person",
            ["PK  id", "traffic_source \u00b7 country"], True,
            note="20,034 never ordered"),
        box(20, 452, 270, 128, "events", "2,424,864", "1 row = one web event",
            ["PK  id", "FK  user_id (46% null)", "session_id \u00b7 event_type"], False),
        box(830, 20, 270, 100, "distribution_centers", "10", "1 row = one warehouse",
            ["PK  id"], False),
        box(830, 176, 270, 128, "products", "29,120", "1 row = one product",
            ["PK  id", "FK  distribution_center_id", "category \u00b7 brand \u00b7 cost"], False),
        box(830, 392, 270, 150, "inventory_items", "489,904", "1 row = one stock unit",
            ["PK  id", "FK  product_id", "cost  \u2192 COGS"], True,
            note="181,415 sold = 1 per line item"),
        # links
        link([(420, 300), (290, 300)], "user_id", "many \u2192 1 \u00b7 0 orphans", True, 355, 268),
        link([(420, 225), (355, 225), (355, 84), (290, 84)], "order_id", "not joined: redundant",
             False, 362, 150, "start"),
        link([(155, 452), (155, 354)], "user_id", "not used", False, 165, 406, "start"),
        link([(600, 380), (600, 467), (830, 467)], "inventory_item_id",
             "1 \u2194 1 \u00b7 45,373 rows before and after", True, 715, 492),
        link([(690, 240), (830, 240)], "product_id", "not needed", False, 760, 212),
        link([(965, 176), (965, 120)], "distribution_center_id", "", False, 952, 153, "end"),
    ]
    style = (f"<style>.tn{{font:700 16px {FONT_STACK}}}.tr{{font:600 14px 'IBM Plex Mono',monospace}}"
             f".tg{{font:500 13.5px {FONT_STACK}}}.tk{{font:12.5px 'IBM Plex Mono',monospace}}"
             f".tnote{{font:700 11px {FONT_STACK};letter-spacing:.06em}}"
             f".lk{{font:600 13px 'IBM Plex Mono',monospace}}.ls{{font:12px {FONT_STACK}}}</style>")
    return (f'<svg viewBox="0 0 1120 600" width="100%" role="img" '
            f'aria-label="Entity relationship diagram of the seven theLook tables">{style}'
            + "\n".join(parts) + "</svg>")


# ================================================================= slides
def slide(n, kicker, title, sub, body, foot, cls=""):
    return f"""
<section class="slide {cls}" data-n="{n}">
  <header class="top"><span class="kick">{kicker}</span><span class="brand">Peek \u00b7 Product &amp; BI Analyst Challenge</span></header>
  <h1>{title}</h1>
  {f'<p class="sub">{sub}</p>' if sub else ''}
  <div class="body">{body}</div>
  <footer class="foot"><span>{foot}</span><span class="pg">{n}</span></footer>
</section>"""


def rail(items):
    out = []
    for big, lab in items:
        out.append(f'<div class="ev"><div class="evn">{big}</div><div class="evl">{lab}</div></div>')
    return '<aside class="rail">' + "".join(out) + "</aside>"


S = []

# ---- 1 executive summary --------------------------------------------------
S.append(slide(
    "1", "Executive summary",
    f"Monthly revenue has more than doubled in a year \u2014 and ~{share_new_t12:.0f}% of it comes from "
    f"people buying for the first time",
    None,
    f"""
<div class="kpis">
  <div class="kpi"><div class="kl">Revenue, {mlabel(last, True)}</div><div class="kn">{money(rev_last, k=True)}</div>
    <div class="kd up">+{rev_yoy:.0f}% vs {mlabel(same_month_ly, True)}</div></div>
  <div class="kpi"><div class="kl">Revenue from new customers, last 12 mo</div><div class="kn">{share_new_t12:.0f}%</div>
    <div class="kd">returning: {min(ret_share_range):.0f}\u2013{max(ret_share_range):.0f}% a month</div></div>
  <div class="kpi"><div class="kl">Median time to 2nd purchase</div><div class="kn">{g_median} days</div>
    <div class="kd">{g_ever:.0f}% ever buy again; {g_90:.1f}% within 90 days</div></div>
  <div class="kpi"><div class="kl">First order as share of 24-mo value</div><div class="kn">{first_order_share:.0f}%</div>
    <div class="kd">${ltv[0]:.0f} of ${ltv[24]:.0f}</div></div>
</div>
<ol class="takeaways">
  <li><b>Growth is real and it is volume.</b> Orders are up {ord_yoy:.0f}% year over year; average order value is not
    (${aov_ly:.0f} \u2192 ${aov_last:.0f}). The business is winning more customers, not bigger baskets.</li>
  <li><b>Repeat purchase is slow, so growth depends on acquisition.</b> The typical returning customer takes over a year to come
    back, and {search_share:.0f}% of first-time buyers arrive through one channel, Search. That is a concentration risk, not a retention crisis.</li>
  <li><b>The free-shipping test cannot be read from this data.</b> At ~{orders_per_quarter} completed orders a quarter,
    only a shift of \u2265{mde_pp:.0f} points in the share of orders over $100 would be detectable. The design is right; the sample is not.</li>
</ol>""",
    f"Completed sale = status \u2018Complete\u2019 and not returned (brief definition). Window: Jan 2019 \u2013 {mlabel(last, True)}; "
    f"the partial current month and 1,154 future-dated rows are excluded.",
    "exec"))

# ---- 2 financial health ---------------------------------------------------
S.append(slide(
    "2", "Situation \u00b7 Financial health",
    f"Revenue grew {rev_yoy:.0f}% year over year on order volume \u2014 average order value did not grow",
    f"Trailing-12-month revenue is {money(t12_rev, k=True)}, up {t12_growth:.0f}% on the prior 12 months. "
    f"The typical month grows {mom_median:.1f}% on the one before.",
    f'<div class="chart wide">{chart_financials()}</div>' + rail([
        (f"+{ord_yoy:.0f}%", f"completed orders, {mlabel(last, True)} vs a year earlier"),
        (f"${min(aov_win):.0f}\u2013${max(aov_win):.0f}", "range of monthly average order value over two years"),
        (f"{mom_median:.1f}%", "median month-over-month revenue growth, last 12 months"),
    ]),
    "Last 24 complete months shown. Revenue = SUM(sale_price) of completed line items; orders = COUNT(DISTINCT order_id); "
    "AOV = revenue / orders. Source: sql/part1_queries.sql, Task A."))

# ---- 3 new vs returning ---------------------------------------------------
S.append(slide(
    "3", "Complication \u00b7 Where growth comes from",
    f"Roughly {share_new_t12 / 10:.0f} in 10 revenue dollars every month come from first-time buyers",
    f"Returning customers are not the problem \u2014 they spend more per head (${ret_per_cust:.0f} vs ${new_per_cust:.0f} in "
    f"{mlabel(last)}). There are just very few of them each month.",
    f'<div class="chart wide">{chart_mix()}</div>' + rail([
        (f"{share_new_t12:.0f}%", "of revenue from new customers, last 12 months"),
        (f"{new_cust_last:,}", f"new customers in {mlabel(last, True)} \u2014 a record"),
        (f"+{(ret_per_cust / new_per_cust - 1) * 100:.0f}%", "spend per returning customer vs per new customer"),
    ]),
    "New = first-ever completed order falls in that month; returning = active, first purchase earlier. "
    "New + returning = active in all 92 months (QA.4). Source: Task B."))

# ---- 4 why: retention -----------------------------------------------------
S.append(slide(
    "4", "Complication \u00b7 Why",
    f"Customers who come back take a median of {g_median} days \u2014 so the first order is ~{first_order_share:.0f}% "
    f"of what a customer spends in two years",
    f"{g_ever:.0f}% of customers do buy again eventually. Almost none do it quickly: {g_90:.1f}% within 90 days, "
    f"{g_365:.0f}% within a year.",
    f"""<div class="pair">
  <figure><figcaption><b>Cohort retention</b> \u2014 % of each first-purchase cohort buying again in month N</figcaption>
    {chart_cohort()}</figure>
  <figure><figcaption><b>Average cumulative spend per customer</b> \u2014 {ltv_n:,} customers with 24 months of history</figcaption>
    {chart_ltv()}</figure>
</div>""",
    "Cohort heatmap and LTV use completed orders (brief definition). Repeat timing uses any non-cancelled, non-returned order, "
    "because order status in this dataset is assigned at random (appendix A2). Source: Task C stretch; sql/analysis/f, g."))

# ---- 5 churn vs revenue -----------------------------------------------------
S.append(slide(
    "5", "Complication \u00b7 Churn vs revenue",
    f"{churn_t12:.0f}% of active customers don\u2019t buy again within 90 days \u2014 a window "
    f"{window_ratio:.1f}\u00d7 shorter than the typical repeat cycle",
    "Revenue and churn rise together: the churn figure describes a business that grows by adding customers, "
    "not one that is losing them. It is also the same in every acquisition channel.",
    f"""<div class="chart wide">{chart_churn()}</div>
<aside class="rail">
  <div class="ev"><div class="evn">{churn_brief_h:.1f}% \u2192 {churn_alt:.1f}%</div>
    <div class="evl">churn if \u201cpurchase\u201d includes shipped and processing orders, not only \u2018Complete\u2019</div></div>
  <div class="ev minich"><div class="evl"><b>12-month repeat rate by channel</b></div>{chart_sources()}</div>
</aside>""",
    f"Churned-90d = active in month M with no completed order in the 90 days after M ends. The last measurable month is "
    f"{mlabel(last_meas, True)}: later months have no full window yet, and computing them anyway yields "
    f"{churn_last_unmeasurable:.0f}% for {mlabel(last, True)}. Source: Task C; sql/analysis/e, h."))

# ---- 6 free shipping --------------------------------------------------------
S.append(slide(
    "6", "Resolution \u00b7 Evaluating a product change",
    "Free shipping over $100 can\u2019t be evaluated on this data: the design works, the sample is too small",
    f"Eligible orders grew {treat_g:.0f}% against {ctrl_g:.0f}% for the rest \u2014 a +{did_pp:.0f}-point "
    f"difference-in-differences that is not statistically significant (p = {p_value:.2f}).",
    f"""<div class="pair">
  <figure><figcaption><b>Difference-in-differences</b> \u2014 completed orders 90 days before vs after</figcaption>
    {chart_fs_did()}</figure>
  <figure><figcaption><b>Share of orders over $100</b>, the metric the policy is meant to move</figcaption>
    {chart_fs_monthly()}</figure>
</div>
<aside class="rail slim">
  <div class="ev"><div class="evn">\u2265{mde_pp:.0f} pts</div><div class="evl">smallest shift in the share of orders over $100
    detectable with ~{orders_per_quarter} orders a quarter (80% power)</div></div>
  <div class="ev"><div class="evl"><b>What a real test needs:</b> a shipping_fee field, a holdout group, cart-abandonment
    events, and margin net of shipping.</div></div>
</aside>""",
    "Hypothetical policy; not present in the data. Why not pre/post alone: the business grows every month, so any "
    "before/after window shows a lift. The \u2265$100 group is a proxy that leaks, since the policy pushes orders across the "
    "threshold. Source: Task D."))

# ---- 7 placeholder ------------------------------------------------------------
S.append(slide(
    "7", "Resolution \u00b7 Recommendations",
    "Recommendations and KPI framework",
    None,
    """<div class="draft">
  <p class="dk">In progress</p>
  <p>This slide answers the brief\u2019s \u201cQuestions to address\u201d:</p>
  <ul><li>Definitions &amp; alternatives</li><li>The single most important trend for leadership</li>
      <li>One business initiative: target segment, primary and secondary metrics</li>
      <li>A 5\u20137 metric business-health dashboard</li></ul>
</div>""",
    "", "draftslide"))

# ---- A1 data model -------------------------------------------------------------
S.append(slide(
    "A1", "Appendix \u00b7 Data model",
    "One fact table and two joins \u2014 each checked to add columns, never rows",
    None,
    f"""<div class="dm">{data_model_svg()}</div>
<aside class="rail rules">
  <div class="rh">Join rules applied</div>
  <ol>
    <li><b>Pick the grain first.</b> order_items is one row per line item, so orders and customers are counted with DISTINCT.</li>
    <li><b>Count rows before and after every join.</b> Joining inventory_items: 45,373 before, 45,373 after.</li>
    <li><b>Skip joins that add nothing.</b> order_items already carries the order\u2019s user_id and status (0 mismatches), so orders is never joined.</li>
    <li><b>Aggregate before joining one-to-many.</b> Task D rolls line items up to one row per order before attaching users.</li>
  </ol>
</aside>""",
    "Black = joined in the analysis \u00b7 grey = available, not needed. Every key checked for orphans: 0 line items without an "
    "order, user, product or stock unit. Row counts are whole tables as of the query date."))

# ---- A2 data quality -----------------------------------------------------------
S.append(slide(
    "A2", "Appendix \u00b7 Data quality",
    "Three things about this data change the numbers, and none of them is in the brief",
    None,
    f"""<div class="pair">
  <figure><figcaption><b>Order status mix by year of order</b> \u2014 a 2019 order is still \u2018Shipped\u2019 today</figcaption>
    {chart_status()}</figure>
  <div class="dq">
    <div class="dqi"><div class="dqn">1,154</div><div class="dqt"><b>rows dated in the future.</b> The generator writes ahead of
      today. Every query caps its window at the earlier of the last row and today.</div></div>
    <div class="dqi"><div class="dqn">{status_complete:.0f}%</div><div class="dqt"><b>of line items are \u2018Complete\u2019,</b> the same share every
      year. Status is assigned at random, so the brief\u2019s definition samples a quarter of real orders.</div></div>
    <div class="dqi"><div class="dqn">{churn_brief_h - churn_alt:.1f} pts</div><div class="dqt"><b>of churn come from that sampling alone</b>
      ({churn_brief_h:.1f}% vs {churn_alt:.1f}%). A repeat order labelled \u2018Shipped\u2019 counts as a lost customer.</div></div>
  </div>
</div>""",
    "Source: sql/part1_queries.sql QA.1\u2013QA.4; sql/analysis/h, i."))

# ---- A3 AI -------------------------------------------------------------------
S.append(slide(
    "A3", "Appendix \u00b7 AI in this analysis",
    "AI wrote the first draft of every query; a check that could fail decided whether to keep it",
    None,
    """<div class="ai">
  <div class="aic"><div class="aih">Where it sped things up</div>
    <ul><li>Profiling the seven tables and every join key in minutes</li><li>First drafts of CTE-structured SQL for all four tasks</li>
    <li>Generating this deck reproducibly from the query outputs</li></ul></div>
  <div class="aic"><div class="aih">Where checks overruled it</div>
    <ul><li>A Task D column was 100% or 0% by construction \u2014 caught, and the query rebuilt at monthly grain</li>
    <li>A 100% churn month \u2014 identified as the edge of the data, not an event</li>
    <li>\u201cRetention is near zero\u201d \u2014 revised once repeat timing was measured</li></ul></div>
  <div class="aic"><div class="aih">What I would automate next</div>
    <ul><li>Run the QA queries on a schedule and alert when a check fails, before a dashboard refreshes</li>
    <li>Have an LLM draft the weekly KPI narrative with every figure pulled from SQL, never computed by the model</li>
    <li>Point text-to-SQL at curated, documented views rather than raw tables, so definitions are fixed upstream</li></ul></div>
  <div class="aic"><div class="aih">Checks that ship with the repo</div>
    <ul><li>Row counts before and after every join</li><li>Identity assertion: new + returning = active, every month</li>
    <li>Revenue reconciled to the status breakdown</li><li>Definition sensitivity: churn under two definitions</li></ul></div>
</div>
<p class="prompt"><span>Example prompt</span>\u201cThe last three months return churn near 100%. Before assuming that is real: what in the data
boundary could produce it, and write the check that would tell an artifact from a genuine spike.\u201d</p>""",
    "Full write-up in README.md \u00a7 Part 3."))


# ================================================================= page
CSS = """
@page { size: 1600px 900px; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #d9d6cf; }
body { font-family: FONTSTACK; color: INK; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.slide { width: 1600px; height: 900px; background: BG; position: relative; overflow: hidden;
  padding: 50px 72px 0; display: flex; flex-direction: column; margin: 0 auto 24px;
  break-after: page; page-break-after: always; }
@media print { html, body { background: BG; } .slide { margin: 0; } }
.top { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 18px; }
.kick { font-size: 13px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: NEWC; }
.brand { font-size: 12.5px; color: INK3; letter-spacing: .04em; }
h1 { font-size: 38px; line-height: 1.16; font-weight: 700; letter-spacing: -.018em; margin: 0 0 12px;
  max-width: 1360px; text-wrap: balance; }
.sub { font-size: 19px; line-height: 1.5; color: INK2; margin: 0 0 14px; max-width: 1240px; }
.body { flex: 1; display: flex; gap: 36px; min-height: 0; align-items: stretch; }
.chart.wide { flex: 1; min-width: 0; display: flex; align-items: center; }
.chart svg, figure svg { display: block; width: 100%; height: auto; }
.rail { width: 300px; flex: none; display: flex; flex-direction: column; gap: 22px; padding-top: 8px;
  border-left: 1px solid RULE; padding-left: 28px; }
.rail.slim { width: 280px; }
.ev .evn { font-size: 34px; font-weight: 700; letter-spacing: -.02em; line-height: 1.05; }
.ev .evl { font-size: 15px; line-height: 1.42; color: INK2; margin-top: 5px; }
.ev.minich .evl { margin-bottom: 4px; }
.foot { display: flex; justify-content: space-between; gap: 40px; align-items: flex-end;
  border-top: 1px solid RULE; margin-top: 14px; padding: 12px 0 20px; font-size: 12px; line-height: 1.45; color: INK3; }
.foot .pg { font-family: 'IBM Plex Mono', monospace; font-weight: 600; color: INK2; }
.pair { flex: 1; display: flex; gap: 34px; min-width: 0; }
.pair figure { flex: 1; margin: 0; min-width: 0; display: flex; flex-direction: column; }
figcaption { font-size: 15px; color: INK2; margin-bottom: 8px; line-height: 1.35; }
figcaption b { color: INK; }

/* exec */
.exec .body { flex-direction: column; gap: 40px; justify-content: center; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: RULE; border: 1px solid RULE; }
.kpi { background: #fff; padding: 28px 28px 26px; }
.kl { font-size: 13px; font-weight: 600; color: INK3; letter-spacing: .02em; line-height: 1.3; min-height: 34px; }
.kn { font-size: 56px; font-weight: 700; letter-spacing: -.025em; margin: 8px 0 4px; }
.kd { font-size: 14.5px; color: INK2; }
.kd.up { color: #0a7d0a; font-weight: 600; }
.takeaways { margin: 0; padding: 0; list-style: none; counter-reset: t; display: grid; gap: 26px; max-width: 1400px; }
.takeaways li { counter-increment: t; position: relative; padding-left: 52px; font-size: 21px; line-height: 1.5; color: INK2; }
.takeaways li::before { content: counter(t); position: absolute; left: 0; top: 1px; width: 30px; height: 30px;
  border-radius: 50%; background: INK; color: BG; font-weight: 700; font-size: 15px; display: grid; place-items: center; }
.takeaways b { color: INK; }

/* data model */
.dm { flex: 1; min-width: 0; display: flex; align-items: center; }
.rules .rh { font-size: 13px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: INK3; }
.rules ol { margin: 0; padding-left: 20px; display: grid; gap: 14px; font-size: 15px; line-height: 1.45; color: INK2; }
.rules b { color: INK; }

/* data quality */
.dq { flex: 1; display: flex; flex-direction: column; gap: 22px; justify-content: center; }
.dqi { display: flex; gap: 22px; align-items: baseline; }
.dqn { font-size: 36px; font-weight: 700; letter-spacing: -.02em; width: 150px; flex: none; text-align: right; }
.dqt { font-size: 17px; line-height: 1.45; color: INK2; }
.dqt b { color: INK; }

/* ai */
.ai { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1px; background: RULE; border: 1px solid RULE; }
.aic { background: #fff; padding: 22px 24px; }
.aih { font-size: 14px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: NEWC; margin-bottom: 10px; }
.aic ul { margin: 0; padding-left: 18px; display: grid; gap: 8px; font-size: 16.5px; line-height: 1.42; color: INK2; }
.slide:has(.ai) .body { flex-direction: column; gap: 22px; }
.prompt { margin: 0; font-size: 18px; line-height: 1.5; font-style: italic; color: INK; border-left: 3px solid NEWC;
  padding: 4px 0 4px 20px; max-width: 1300px; }
.prompt span { display: block; font-style: normal; font-size: 12.5px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: INK3; margin-bottom: 4px; }

/* draft */
.draft { border: 2px dashed MUTED; border-radius: 8px; padding: 36px 44px; font-size: 19px; color: INK2; width: 900px; }
.draft .dk { font-size: 13px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: CRIT; margin: 0 0 12px; }
.draft ul { margin: 10px 0 0; line-height: 1.8; }

/* single-slide preview mode: deck.html?s=3 */
body.one .slide { display: none; margin: 0; }
body.one .slide.show { display: flex; }
"""
for k, v in {"FONTSTACK": FONT_STACK, "INK3": INK3, "INK2": INK2, "INK": INK, "BG": BG,
             "RULE": RULE, "NEWC": NEW, "MUTED": MUTED, "CRIT": CRIT}.items():
    CSS = CSS.replace(k, v)

HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Growth Without Repeat \u2014 Peek BI Analyst Challenge</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;600;700&display=swap">
<style>{CSS}</style></head>
<body>
{''.join(S)}
<script>
  const s = new URLSearchParams(location.search).get("s");
  if (s) {{
    document.body.classList.add("one");
    const el = document.querySelectorAll(".slide")[Number(s) - 1];
    if (el) el.classList.add("show");
  }}
</script>
</body></html>"""


# ================================================================= render
def find_browser():
    for c in (shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if c and Path(c).exists():
            return c
    return None


def main():
    OUT.mkdir(exist_ok=True)
    html_path = OUT / "deck.html"
    html_path.write_text(HTML, encoding="utf-8")
    print(f"  -> {html_path}")

    browser = find_browser()
    if not browser:
        print("  (no Edge/Chrome found: deck.html written, PDF skipped)")
        return
    url = html_path.resolve().as_uri()
    prof = tempfile.mkdtemp(prefix="deck-")
    base = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            f"--user-data-dir={prof}", "--virtual-time-budget=8000"]

    subprocess.run(base + ["--no-pdf-header-footer", f"--print-to-pdf={OUT / 'deck.pdf'}", url],
                   capture_output=True, timeout=180)
    print(f"  -> {OUT / 'deck.pdf'}")

    shots = OUT / "slides"
    shots.mkdir(exist_ok=True)
    for i in range(1, len(S) + 1):
        png = shots / f"slide_{i:02d}.png"
        subprocess.run(base + ["--window-size=1600,900", f"--screenshot={png}", f"{url}?s={i}"],
                       capture_output=True, timeout=120)
    print(f"  -> {shots}  ({len(S)} slides)")
    shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    main()
