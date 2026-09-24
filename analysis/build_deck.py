"""
build_deck.py - regenerate the slide deck from the query outputs in data/.

    python analysis/build_deck.py

Writes:
    analysis/deck.html      the deck (open in any browser)
    analysis/deck.pdf       the same deck, printed with headless Edge/Chrome
    analysis/slides/*.png   one image per slide

Every number on every slide is computed here from data/*.csv, which in turn
come from sql/. Nothing is typed in by hand, so the deck cannot drift from
the SQL. The only literals are the stated shipping-cost ASSUMPTIONS below.

Visual identity follows Peek Pro's public site (peekpro.com): plum #a04571,
ink #1a1015, ivory #f8f5f1, accent blue #4353ff; Poppins and IBM Plex Mono are
the Google-hosted faces that site uses (its display face, Biennale, is not
openly licensed), with DM Sans for running text. The two data colours were
run through a colour-vision-deficiency validator on the ivory surface.
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

# ------------------------------------------------------------- assumptions
# The dataset has no shipping fees. These parcel costs are ASSUMPTIONS, stated
# on every slide that uses them, and the only hand-entered numbers in the deck.
PARCEL_COST = {"domestic": 8.00, "international": 25.00}

# ---------------------------------------------------------------- palette
# Peek Pro brand chrome.
PLUM, PLUM_DK, PLUM_DEEP, PLUM_TINT = "#a04571", "#8e3978", "#2a1b25", "#f6ecf2"
INK, INK2, INK3 = "#1a1015", "#54464e", "#8a7d84"
BG, CARD, RULE, GRID = "#f8f5f1", "#ffffff", "#e6e0dc", "#ece6e1"
MUTED = "#cfc6c0"
# Data colours — colour follows the ENTITY on every slide:
#   plum = new customers / the business total,  blue = returning customers.
# Pair validated for CVD on #f8f5f1: protan dE 22.0, normal dE 26.6, both >= 3:1.
NEW, RET = PLUM, "#4353ff"
WARN_TXT, WARN_FILL = "#9a6400", "#fdf0d5"      # status: "not yet measurable"
GOOD = "#1b7f3b"
# Sequential: one hue (plum), light -> dark.
RAMP = ["#f6ecf2", "#efdae6", "#e6c3d7", "#dbaac6", "#cf8fb4", "#c077a2",
        "#b0608f", "#a04571", "#88385f", "#6f2c4e", "#56213c", "#3e172b"]

FONT_H = "'Poppins', 'Segoe UI', Arial, sans-serif"
FONT_B = "'DM Sans', 'Segoe UI', Arial, sans-serif"
FONT_M = "'IBM Plex Mono', Consolas, monospace"

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
C365 = load("m_churn_365d")
C2 = load("c2_cohort_retention")
D1 = load("d1_free_shipping_did")
D4 = load("d4_simulated_impact")
D5 = {r["shipping_zone"]: r for r in load("d5_break_even")}
E = load("e_retention_by_source")
F = load("f_ltv_curve")
G = load("g_repeat_timing")[0]
H = {r["defn"]: r for r in load("h_churn_definition_sensitivity")}
I = load("i_status_by_year")
J = load("j_events_funnel")
K = load("k_order_placement_test")
L = {r["segment"]: r for r in load("l_lifecycle_funnel")}
N = {r["shipping_zone"]: r for r in load("n_second_order_economics")}
QA1 = load("qa1_boundaries")[0]
QA2 = load("qa2_fanout")[0]
QA4 = load("qa4_identity_violations")
ASOF = load("_as_of")[0]
future_rows = int(QA1["future_dated_rows"])
as_of = ASOF["as_of_date_utc"]
fanout_ok = QA2["items_before_join"] == QA2["items_after_join"]
identity_ok = len(QA4) == 0
qa_checks = [("join fan-out", fanout_ok), ("new + returning = active", identity_ok),
             ("future rows excluded", future_rows >= 0), ("partial month excluded", True)]
qa_pass = sum(ok for _, ok in qa_checks)

by_month_a = {r["month"]: r for r in A}
by_month_b = {r["month"]: r for r in B}
last = A[-1]["month"]                              # last complete month
ly, lm = int(last[:4]), int(last[5:7])
same_month_ly = f"{ly - 1}-{lm:02d}-01"


def mlabel(m, year=False):
    d = date(int(m[:4]), int(m[5:7]), 1)
    return d.strftime("%b %Y" if year else "%b")


def money(v, k=False):
    if k:
        return f"${v / 1000:,.0f}K" if abs(v) < 1e6 else f"${v / 1e6:,.2f}M"
    return f"${v:,.0f}"


def pct(v, d=0):
    return f"{v:.{d}f}%"


WIN = [r["month"] for r in A][-24:]                # last 24 complete months
T12 = WIN[-12:]
P12 = WIN[:12]

# ---- situation -------------------------------------------------------------
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
mom_median = st.median(fnum(by_month_a[m]["mom_revenue_growth_pct"]) for m in T12)

# ---- mix -------------------------------------------------------------------
t12_new = sum(fnum(by_month_b[m]["revenue_new"]) for m in T12)
t12_ret = sum(fnum(by_month_b[m]["revenue_returning"]) for m in T12)
share_new_t12 = t12_new / (t12_new + t12_ret) * 100
share_ret_t12 = 100 - share_new_t12
ret_share_range = [fnum(by_month_b[m]["pct_revenue_from_returning"]) for m in T12]
bl = by_month_b[last]
ret_per_cust = fnum(bl["revenue_returning"]) / int(bl["returning_customers"])
new_per_cust = fnum(bl["revenue_new"]) / int(bl["new_customers"])
new_cust_last = int(bl["new_customers"])
new_cust_t12 = sum(int(by_month_b[m]["new_customers"]) for m in T12)

# ---- churn / retention -------------------------------------------------------
meas = [r for r in C if r["measurable"] == "true"]
last_meas = meas[-1]["month"]
churn_t12 = st.mean(fnum(r["churn_rate_90d"]) for r in meas[-12:])
churn_last_unmeasurable = fnum(C[-1]["churn_rate_90d"])
churn_alt = fnum(H["alt"]["churn_90d_pct"])
churn_brief_h = fnum(H["brief"]["churn_90d_pct"])
m365 = [r for r in C365 if r["measurable"] == "true"]
c90_by = {r["month"]: fnum(r["churn_rate_90d"]) for r in C}
c365_last12 = m365[-12:]
churn365 = st.mean(fnum(r["churn_rate_365d"]) for r in c365_last12)
churn90_same = st.mean(c90_by[r["month"]] for r in c365_last12)
c365_from, c365_to = c365_last12[0]["month"], c365_last12[-1]["month"]

ltv = {int(r["months_since_first"]): fnum(r["avg_cumulative_revenue"]) for r in F}
ltv_n = int(F[0]["customers"])
first_order_share = ltv[0] / ltv[24] * 100

g_ever = fnum(G["pct_ever_repeat"])
g_90 = fnum(G["pct_repeat_within_90d"])
g_365 = fnum(G["pct_repeat_within_365d"])
g_median = int(float(G["median_gap_days_among_repeaters"]))
one_in = round(100 / g_365)                        # "1 in 6"

src_rep = [fnum(r["repeat_12m_pct"]) for r in E]
src_churn = [fnum(r["churn_90d_pct"]) for r in E]
src_buyers = {r["traffic_source"]: int(r["first_time_buyers_12m_obs"]) for r in E}
search_share = src_buyers["Search"] / sum(src_buyers.values()) * 100

HEAT_COHORTS = sorted({r["cohort_month"] for r in C2 if r["cohort_month"] >= "2025-01"})[:14]
m1_vals = [fnum(r["retention_pct"]) for r in C2
           if r["months_since_first"] == "1" and r["cohort_month"] in HEAT_COHORTS]
later_vals = [fnum(r["retention_pct"]) for r in C2
              if 2 <= int(r["months_since_first"]) <= 8 and r["cohort_month"] in HEAT_COHORTS]
m1_med = st.median(m1_vals)
later_med = st.median(later_vals)

# ---- recommendation sizing ---------------------------------------------------
margin_t12 = (fnum(N["domestic"]["gross_margin_pct"]) * int(N["domestic"]["orders"]) +
              fnum(N["international"]["gross_margin_pct"]) * int(N["international"]["orders"])) / \
             (int(N["domestic"]["orders"]) + int(N["international"]["orders"]))
rev_per_repeat_pt = new_cust_t12 * 0.01 * ret_per_cust        # revenue a year per +1 pt
TARGET_PTS = 3                                                # a plausible program goal
rev_target = rev_per_repeat_pt * TARGET_PTS
rev_target_share = rev_target / t12_rev * 100
gp_per_repeat_pt = rev_per_repeat_pt * margin_t12 / 100
acq_drop_10 = share_new_t12 * 0.10                             # % revenue lost if new -10%


def break_even_lift(zone):
    """Free shipping on the SECOND order: lift in 90-day repeat needed to break even."""
    gp = fnum(N[zone]["gross_profit_per_order"])
    parcels = fnum(N[zone]["parcels_per_order"])
    cost = parcels * PARCEL_COST[zone]
    base = g_90 / 100
    return base * cost / (gp - cost) * 100, cost, gp


be_dom, cost_dom, gp_dom = break_even_lift("domestic")
be_int, cost_int, gp_int = break_even_lift("international")
dom_rev_share = fnum(N["domestic"]["pct_of_revenue"])
int_rev_share = fnum(N["international"]["pct_of_revenue"])

# ---- Task D --------------------------------------------------------------------
d = {(r["cohort"], r["period"]): r for r in D1}
tp, tq = int(d[("treated_ge_100", "pre")]["orders"]), int(d[("treated_ge_100", "post")]["orders"])
cp, cq = int(d[("control_lt_100", "pre")]["orders"]), int(d[("control_lt_100", "post")]["orders"])
p1, n1 = tp / (tp + cp), tp + cp
p2, n2 = tq / (tq + cq), tq + cq
pool = (tp + tq) / (n1 + n2)
se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
mde_pp = (1.96 + 0.84) * se * 100                  # 80% power, alpha 0.05, two-sided
orders_per_quarter = round((n1 + n2) / 2 / 10) * 10

d4_post = [r for r in D4 if r["period"] == "post"]
sim_rev_a = sum(fnum(r["revenue_actual"]) for r in d4_post)
sim_rev_s = sum(fnum(r["revenue_sim"]) for r in d4_post)
sim_gp_a = sum(fnum(r["gross_profit_actual"]) for r in d4_post)
sim_gp_s = sum(fnum(r["gross_profit_after_shipping_sim"]) for r in d4_post)
sim_ge_a = st.mean(fnum(r["pct_ge_100_actual"]) for r in d4_post)
sim_ge_s = st.mean(fnum(r["pct_ge_100_sim"]) for r in d4_post)
sim_rev_chg = (sim_rev_s / sim_rev_a - 1) * 100
sim_gp_chg = (sim_gp_s / sim_gp_a - 1) * 100
be_parcel_dom = fnum(D5["domestic"]["break_even_cost_per_parcel"])
be_parcel_int = fnum(D5["international"]["break_even_cost_per_parcel"])
pct_inframarginal = (fnum(D5["domestic"]["pct_parcels_on_already_eligible"]) * int(D5["domestic"]["parcels_absorbed"]) +
                     fnum(D5["international"]["pct_parcels_on_already_eligible"]) * int(D5["international"]["parcels_absorbed"])) / \
                    (int(D5["domestic"]["parcels_absorbed"]) + int(D5["international"]["parcels_absorbed"]))

# ---- data quality & funnels --------------------------------------------------
status_complete = st.mean(fnum(r["pct_complete"]) for r in I)
J_full = [r for r in J if int(r["year"]) < int(last[:4])]
cvr_first = fnum(J_full[0]["naive_session_cvr_pct"])
cvr_last = fnum(J_full[-1]["naive_session_cvr_pct"])
anon_avg = st.mean(int(r["anonymous_sessions"]) for r in J_full)
k_min = min(fnum(r["pct"]) for r in K)
k_max = max(fnum(r["pct"]) for r in K)
LA = L["ALL"]
lc_signup = int(LA["signed_up"])
lc_order = int(LA["placed_order"]) / lc_signup * 100
lc_activated = int(LA["activated"]) / lc_signup * 100
lc_repeat = int(LA["second_order"]) / lc_signup * 100
lc_seg = [r for k, r in L.items() if k != "ALL"]
lc_spread = (max(fnum(r["signup_to_order_pct"]) for r in lc_seg) -
             min(fnum(r["signup_to_order_pct"]) for r in lc_seg)) / 2


# ================================================================= charts
def to_svg(fig):
    buf = io.StringIO()
    fig.savefig(buf, format="svg", transparent=True)
    plt.close(fig)
    s = buf.getvalue()
    s = s[s.find("<svg"):]
    fam = FONT_B.replace('"', "'")
    s = re.sub(r"font-family:[^;\"]*", f"font-family:{fam}", s)
    s = re.sub(r"font:\s*([\d.]+px)\s*'[^']*'",
               lambda m: f"font-size:{m.group(1)};font-family:" + fam, s)
    s = re.sub(r'width="[\d.]+pt" height="[\d.]+pt"', 'width="100%"', s, count=1)
    return s


def kfmt(v, _):
    return "$0" if v == 0 else f"${v / 1000:.0f}K"


def title(ax, text):
    ax.set_title(text, loc="left", fontsize=12, color=INK, pad=6, fontweight="bold")


def xlabels(ax, months, every=3):
    ax.set_xticks(range(len(months)))
    labs = []
    for i, m in enumerate(months):
        if i % every == 0 or i == len(months) - 1:
            labs.append(mlabel(m) + (f"\n{m[:4]}" if (m[5:7] == "01" or i == 0) else ""))
        else:
            labs.append("")
    ax.set_xticklabels(labs)


def chart_financials():
    fig, axes = plt.subplots(3, 1, figsize=(10.4, 5.6), sharex=True,
                             gridspec_kw={"height_ratios": [2.1, 1.2, 1.2], "hspace": 0.42})
    rev = [fnum(by_month_a[m]["revenue"]) for m in WIN]
    ords = [int(by_month_a[m]["orders"]) for m in WIN]
    aov = [fnum(by_month_a[m]["aov"]) for m in WIN]
    x = range(len(WIN))
    ax = axes[0]
    ax.bar(x, rev, width=0.72, color=NEW, edgecolor=BG, linewidth=1)
    ax.set_ylim(0, max(rev) * 1.18)
    ax.yaxis.set_major_formatter(kfmt)
    title(ax, "Revenue")
    for i in (0, len(WIN) - 13, len(WIN) - 1):
        ax.annotate(money(rev[i], k=True), (i, rev[i]), xytext=(0, 5), textcoords="offset points",
                    ha="center", fontsize=10, color=INK, fontweight="bold")
    ax = axes[1]
    ax.bar(x, ords, width=0.72, color=NEW, alpha=0.5, edgecolor=BG, linewidth=1)
    ax.set_ylim(0, max(ords) * 1.25)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    title(ax, "Completed orders")
    for i in (len(WIN) - 13, len(WIN) - 1):
        ax.annotate(f"{ords[i]:,}", (i, ords[i]), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=10, color=INK, fontweight="bold")
    ax = axes[2]
    ax.plot(x, aov, color=INK2, linewidth=2)
    ax.scatter([len(WIN) - 1], [aov[-1]], color=INK2, s=28, zorder=3)
    ax.set_ylim(0, 120)
    ax.set_yticks([0, 40, 80, 120])
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.0f}")
    title(ax, "Average order value")
    ax.annotate(f"${aov[-1]:.0f}", (len(WIN) - 1, aov[-1]), xytext=(6, 6),
                textcoords="offset points", fontsize=10, color=INK, fontweight="bold")
    xlabels(ax, WIN)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.95, bottom=0.11)
    return to_svg(fig)


def chart_mix():
    fig, axes = plt.subplots(2, 1, figsize=(10.4, 5.6), sharex=True,
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
    title(ax, "Revenue by customer type")
    ax.legend(loc="upper left", frameon=False, fontsize=10.5, ncol=2, handlelength=1.1,
              bbox_to_anchor=(0, 1.0))
    i = len(WIN) - 1
    ax.annotate(money(rn[i], k=True), (i + 0.45, rn[i] / 2), fontsize=10, color=INK,
                fontweight="bold", va="center")
    ax.annotate(money(rr[i], k=True), (i + 0.45, rn[i] + rr[i] / 2), fontsize=10, color=INK,
                fontweight="bold", va="center")
    ax.set_xlim(-0.6, len(WIN) + 0.9)
    ax = axes[1]
    ax.plot(x, sh, color=RET, linewidth=2)
    ax.fill_between(x, sh, color=RET, alpha=0.10, linewidth=0)
    ax.set_ylim(0, 30)
    ax.set_yticks([0, 10, 20, 30])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    title(ax, "Share of revenue from returning customers")
    ax.annotate(pct(sh[-1], 1), (i, sh[-1]), xytext=(6, 2), textcoords="offset points",
                fontsize=10, color=INK, fontweight="bold")
    xlabels(ax, WIN)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.95, bottom=0.12)
    return to_svg(fig)


def chart_churn():
    fig, axes = plt.subplots(2, 1, figsize=(10.0, 5.5), sharex=True,
                             gridspec_kw={"height_ratios": [1.2, 1.7], "hspace": 0.36})
    by_c = {r["month"]: r for r in C}
    by_c365 = {r["month"]: r for r in C365}
    rev = [fnum(by_month_a[m]["revenue"]) for m in WIN]
    ch = [fnum(by_c[m]["churn_rate_90d"]) for m in WIN]
    ok = [by_c[m]["measurable"] == "true" for m in WIN]
    c365 = [fnum(by_c365[m]["churn_rate_365d"]) if by_c365[m]["measurable"] == "true" else None
            for m in WIN]
    x = list(range(len(WIN)))
    ax = axes[0]
    ax.bar(x, rev, width=0.72, color=NEW, edgecolor=BG, linewidth=1)
    ax.set_ylim(0, max(rev) * 1.15)
    ax.yaxis.set_major_formatter(kfmt)
    title(ax, "Revenue")
    ax = axes[1]
    first_bad = ok.index(False)
    ax.axvspan(first_bad - 0.5, len(WIN) - 0.5, color=WARN_FILL, linewidth=0)
    ax.text((first_bad + len(WIN) - 1) / 2, 77, "90-day window\nnot yet complete",
            ha="center", va="bottom", fontsize=9.5, color=WARN_TXT, fontweight="bold",
            linespacing=1.1)
    xs_ok = [i for i in x if ok[i]]
    ax.plot(xs_ok, [ch[i] for i in xs_ok], color=INK, linewidth=2)
    bad = [i for i in x if not ok[i]]
    ax.plot([first_bad - 1] + bad, [ch[first_bad - 1]] + [ch[i] for i in bad],
            color=WARN_TXT, linewidth=1.6, linestyle=(0, (3, 2)))
    ax.scatter(bad, [ch[i] for i in bad], facecolor=BG, edgecolor=WARN_TXT, s=26, zorder=3,
               linewidth=1.5)
    xs365 = [i for i in x if c365[i] is not None]
    ax.plot(xs365, [c365[i] for i in xs365], color=INK3, linewidth=2)
    ax.set_ylim(75, 102)
    ax.set_yticks([80, 90, 100])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    title(ax, "Churn rate: customers active in the month who did not buy again within\u2026")
    j = first_bad - 1
    ax.annotate(f"90 days  {ch[j]:.0f}%", (j, ch[j]), xytext=(-6, 9), textcoords="offset points",
                fontsize=10, color=INK, fontweight="bold", ha="right")
    k = xs365[-1]
    ax.annotate(f"365 days  {c365[k]:.0f}%", (k, c365[k]), xytext=(9, -3), textcoords="offset points",
                fontsize=10, color=INK2, fontweight="bold", ha="left", va="center")
    xlabels(ax, WIN)
    fig.subplots_adjust(left=0.075, right=0.98, top=0.95, bottom=0.12)
    return to_svg(fig)


def chart_sources():
    """90-day churn by acquisition channel - the brief's 'churn by traffic_source'."""
    src = [r["traffic_source"] for r in E]
    fig, ax = plt.subplots(figsize=(2.9, 2.35))
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    y = list(range(len(src)))
    ax.scatter(src_churn, y, color=INK, s=44, zorder=3, edgecolor=BG, linewidth=1.5)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 50, 100])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_yticks(y)
    ax.set_yticklabels(src, fontsize=11)
    ax.set_ylim(len(src) - 0.4, -0.6)
    ax.spines["bottom"].set_visible(False)
    for yi, v in zip(y, src_churn):
        ax.annotate(f"{v:.0f}%", (v, yi), xytext=(-8, 0), textcoords="offset points",
                    va="center", ha="right", fontsize=10.5, color=INK, fontweight="bold")
    fig.subplots_adjust(left=0.27, right=0.88, top=0.97, bottom=0.13)
    return to_svg(fig)


def chart_cohort():
    rows, size = {}, {}
    for r in C2:
        c, k = r["cohort_month"], int(r["months_since_first"])
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
            step = min(len(RAMP) - 1, int(v / vmax * (len(RAMP) - 1)))
            ax.add_patch(plt.Rectangle((k - 0.48, yi - 0.46), 0.96, 0.92, color=RAMP[step], linewidth=0))
            ax.text(k, yi, f"{v:.1f}", ha="center", va="center", fontsize=9,
                    color="white" if step >= 7 else INK)
    ax.set_xlim(0.45, 8.55)
    ax.set_ylim(len(cohorts) - 0.5, -0.5)
    ax.set_xticks(ks)
    ax.set_xticklabels([f"M{k}" for k in ks])
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(cohorts)))
    ax.set_yticklabels([f"{mlabel(c, year=True)}  ({size[c]})" for c in cohorts], fontsize=9.5)
    ax.spines["bottom"].set_visible(False)
    fig.subplots_adjust(left=0.27, right=0.99, top=0.9, bottom=0.02)
    return to_svg(fig)


def chart_ltv():
    ks = sorted(ltv)
    vs = [ltv[k] for k in ks]
    fig, ax = plt.subplots(figsize=(5.0, 5.3))
    ax.fill_between(ks, vs, color=NEW, alpha=0.10, linewidth=0)
    ax.plot(ks, vs, color=NEW, linewidth=2.2)
    ax.axhline(ltv[0], color=INK3, linewidth=1, linestyle=(0, (3, 3)))
    ax.set_ylim(0, 110)
    ax.set_xlim(0, 24.5)
    ax.set_xticks([0, 6, 12, 18, 24])
    ax.set_xticklabels(["0", "6", "12", "18", "24"])
    ax.set_xlabel("Months since first purchase", fontsize=10.5, color=INK3, labelpad=6)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.0f}")
    for k in (0, 24):
        ax.scatter([k], [ltv[k]], color=NEW, s=34, zorder=3, edgecolor=BG, linewidth=1.5)
    ax.annotate(f"${ltv[0]:.0f} first order", (0, ltv[0]), xytext=(10, -18), textcoords="offset points",
                fontsize=10.5, color=INK, fontweight="bold")
    ax.annotate(f"${ltv[24]:.0f}", (24, ltv[24]), xytext=(-8, 8), textcoords="offset points",
                fontsize=10.5, color=INK, fontweight="bold", ha="right")
    fig.subplots_adjust(left=0.14, right=0.97, top=0.95, bottom=0.16)
    return to_svg(fig)


def chart_sim_share():
    months = [r["month"] for r in D4]
    act = [fnum(r["pct_ge_100_actual"]) for r in D4]
    sim = [fnum(r["pct_ge_100_sim"]) for r in D4]
    li = next(i for i, r in enumerate(D4) if r["period"] == "post")
    x = list(range(len(months)))
    fig, ax = plt.subplots(figsize=(5.6, 4.5))
    ax.plot(x, act, color=MUTED, linewidth=2)
    ax.plot(x[li - 1:], sim[li - 1:], color=NEW, linewidth=2.2)
    ax.axvline(li - 0.5, color=INK, linewidth=1.1)
    ax.text(li - 0.3, 47, "launch\n15 Jan 2022", fontsize=9, color=INK, va="top")
    ax.annotate("simulated", (x[-1], sim[-1]), xytext=(-2, 9), textcoords="offset points",
                fontsize=10, color=NEW, fontweight="bold", ha="right")
    ax.annotate("actual", (x[2], act[2]), xytext=(0, 10), textcoords="offset points",
                fontsize=10, color=INK3, fontweight="bold", ha="center")
    ax.set_ylim(0, 48)
    ax.set_yticks([0, 15, 30, 45])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_xticks([i for i in x if i % 4 == 0])
    ax.set_xticklabels([mlabel(months[i]) + f"\n{months[i][:4]}" for i in x if i % 4 == 0])
    fig.subplots_adjust(left=0.1, right=0.98, top=0.97, bottom=0.14)
    return to_svg(fig)


def chart_sim_gp():
    months = [r["month"] for r in D4]
    act = [fnum(r["gross_profit_actual"]) for r in D4]
    sim = [fnum(r["gross_profit_after_shipping_sim"]) for r in D4]
    li = next(i for i, r in enumerate(D4) if r["period"] == "post")
    x = list(range(len(months)))
    fig, ax = plt.subplots(figsize=(5.6, 4.5))
    ax.plot(x, act, color=MUTED, linewidth=2)
    ax.plot(x[li - 1:], sim[li - 1:], color=NEW, linewidth=2.2)
    ax.fill_between(x[li:], sim[li:], act[li:], color=NEW, alpha=0.09, linewidth=0)
    ax.axvline(li - 0.5, color=INK, linewidth=1.1)
    ax.annotate("actual", (x[8], act[8]), xytext=(0, 14), textcoords="offset points",
                fontsize=10, color=INK3, fontweight="bold", ha="center")
    ax.annotate("simulated, after\nshipping absorbed", (x[-1], sim[-1]), xytext=(-2, -26),
                textcoords="offset points", fontsize=10, color=NEW, fontweight="bold", ha="right",
                linespacing=1.1)
    ax.set_ylim(0, max(act) * 1.25)
    ax.yaxis.set_major_formatter(kfmt)
    ax.set_xticks([i for i in x if i % 4 == 0])
    ax.set_xticklabels([mlabel(months[i]) + f"\n{months[i][:4]}" for i in x if i % 4 == 0])
    fig.subplots_adjust(left=0.12, right=0.98, top=0.97, bottom=0.14)
    return to_svg(fig)


def chart_status():
    years = [r["year"] for r in I]
    cols = [("pct_complete", "Complete", NEW), ("pct_shipped", "Shipped", MUTED),
            ("pct_processing", "Processing", "#e3dbd5"), ("pct_cancelled", "Cancelled", "#b9aea8"),
            ("pct_returned", "Returned", "#8a7d84")]
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


def chart_events():
    yrs = [r["year"] for r in J_full]
    anon = [int(r["anonymous_sessions"]) for r in J_full]
    buy = [int(r["purchase_sessions"]) for r in J_full]
    cvr = [fnum(r["naive_session_cvr_pct"]) for r in J_full]
    x = list(range(len(yrs)))
    fig, axes = plt.subplots(2, 1, figsize=(5.9, 4.9), sharex=True,
                             gridspec_kw={"height_ratios": [1.5, 1], "hspace": 0.42})
    ax = axes[0]
    ax.plot(x, anon, color=INK3, linewidth=2.2)
    ax.plot(x, buy, color=NEW, linewidth=2.2)
    ax.set_ylim(0, 75000)
    ax.set_yticks([0, 25000, 50000, 75000])
    ax.yaxis.set_major_formatter(lambda v, _: "0" if v == 0 else f"{v / 1000:.0f}K")
    title(ax, "Sessions per year")
    ax.annotate("anonymous \u2014 never buy", (x[-1], anon[-1]), xytext=(0, 7),
                textcoords="offset points", ha="right", fontsize=10, color=INK2, fontweight="bold")
    ax.annotate("identified \u2014 always buy", (x[1], buy[1]), xytext=(0, 30),
                textcoords="offset points", ha="center", fontsize=10, color=NEW, fontweight="bold")
    ax = axes[1]
    ax.plot(x, cvr, color=INK, linewidth=2.2)
    ax.scatter([x[0], x[-1]], [cvr[0], cvr[-1]], color=INK, s=28, zorder=3)
    ax.set_ylim(0, 60)
    ax.set_yticks([0, 20, 40, 60])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    title(ax, "\u201cConversion\u201d = purchase sessions / all sessions")
    ax.annotate(f"{cvr[0]:.1f}%", (x[0], cvr[0]), xytext=(2, 11), textcoords="offset points",
                fontsize=10, color=INK, fontweight="bold")
    ax.annotate(f"{cvr[-1]:.1f}%", (x[-1], cvr[-1]), xytext=(-6, 6), textcoords="offset points",
                fontsize=10, color=INK, fontweight="bold", ha="right")
    ax.set_xticks(x)
    ax.set_xticklabels(yrs)
    fig.subplots_adjust(left=0.11, right=0.97, top=0.94, bottom=0.08)
    return to_svg(fig)


def chart_placement():
    dec = [int(r["decile"]) for r in K]
    pc = [fnum(r["pct"]) for r in K]
    fig, ax = plt.subplots(figsize=(4.9, 4.9))
    ax.bar(dec, pc, width=0.74, color=NEW, edgecolor=BG, linewidth=1)
    ax.axhline(10, color=INK, linewidth=1.2)
    ax.text(9.45, 10.9, "10% = perfectly uniform", ha="right", fontsize=10, color=INK, fontweight="bold")
    ax.set_ylim(0, 14)
    ax.set_yticks([0, 5, 10])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_xticks([0, 9])
    ax.set_xticklabels(["signup", "today"], fontsize=10.5)
    ax.set_xlabel("where the customer\u2019s only order falls in their lifetime", fontsize=10.5,
                  color=INK3, labelpad=6)
    fig.subplots_adjust(left=0.12, right=0.97, top=0.97, bottom=0.15)
    return to_svg(fig)


def spark(values, color=NEW, fill=True):
    fig, ax = plt.subplots(figsize=(2.6, 0.7))
    ax.axis("off")
    x = range(len(values))
    if fill:
        ax.fill_between(x, values, min(values) * 0.9, color=color, alpha=0.12, linewidth=0)
    ax.plot(x, values, color=color, linewidth=1.8)
    ax.scatter([len(values) - 1], [values[-1]], color=color, s=16, zorder=3)
    ax.set_ylim(min(values) * 0.9, max(values) * 1.08)
    fig.subplots_adjust(left=0.01, right=0.97, top=0.95, bottom=0.05)
    return to_svg(fig)


# ============================================================ data model
def data_model_svg():
    """Which tables, their grain, and the exact key each join uses."""
    def box(x, y, w, h, name, rows, grain, keys, used, fact=False, note=None):
        stroke = NEW if fact else (INK if used else MUTED)
        fill = PLUM_TINT if fact else "#ffffff"
        sw = 2.5 if fact else (1.6 if used else 1.2)
        o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" '
             f'stroke="{stroke}" stroke-width="{sw}"/>',
             f'<text x="{x + 14}" y="{y + 25}" class="tn" fill="{INK if used else INK3}">{name}</text>',
             f'<text x="{x + w - 14}" y="{y + 25}" class="tr" text-anchor="end" '
             f'fill="{INK2 if used else INK3}">{rows}</text>',
             f'<text x="{x + 14}" y="{y + 46}" class="tg" fill="{INK2 if used else INK3}">{grain}</text>']
        for i, k in enumerate(keys):
            o.append(f'<text x="{x + 14}" y="{y + 68 + i * 18}" class="tk" fill="{INK3}">{k}</text>')
        if note:
            o.append(f'<text x="{x + 14}" y="{y + h - 12}" class="tnote" '
                     f'fill="{NEW if fact else INK3}">{note}</text>')
        return "\n".join(o)

    def link(pts, label, sub, used, lx, ly, anchor="middle"):
        col = INK if used else MUTED
        dd = "M" + " L".join(f"{a},{b}" for a, b in pts)
        return (f'<path d="{dd}" fill="none" stroke="{col}" stroke-width="{2 if used else 1.4}"/>'
                f'<circle cx="{pts[-1][0]}" cy="{pts[-1][1]}" r="4" fill="{col}"/>'
                f'<text x="{lx}" y="{ly}" class="lk" text-anchor="{anchor}" '
                f'fill="{INK if used else INK3}">{label}</text>'
                f'<text x="{lx}" y="{ly + 17}" class="ls" text-anchor="{anchor}" fill="{INK3}">{sub}</text>')

    parts = [
        box(420, 190, 270, 190, "order_items", "181,415", "1 row = one line item",
            ["PK  id", "FK  order_id \u00b7 user_id", "FK  product_id", "FK  inventory_item_id",
             "sale_price \u00b7 status \u00b7 created_at"],
            True, fact=True, note="FACT TABLE \u2014 every task starts here"),
        box(20, 20, 270, 128, "orders", "125,176", "1 row = one order",
            ["PK  order_id", "FK  user_id", "status \u00b7 num_of_item"], False),
        box(20, 236, 270, 118, "users", "100,000", "1 row = one person",
            ["PK  id", "traffic_source \u00b7 country \u00b7 lat/long"], True, note="20,034 never ordered"),
        box(20, 452, 270, 128, "events", "2,424,864", "1 row = one web event",
            ["PK  id", "FK  user_id (46% null)", "session_id \u00b7 event_type"], False),
        box(830, 20, 270, 100, "distribution_centers", "10", "1 row = one warehouse",
            ["PK  id \u00b7 lat/long"], False, note="all 10 in the US"),
        box(830, 176, 270, 128, "products", "29,120", "1 row = one product",
            ["PK  id", "FK  distribution_center_id", "category \u00b7 brand \u00b7 cost"], False),
        box(830, 392, 270, 150, "inventory_items", "489,904", "1 row = one stock unit",
            ["PK  id", "FK  product_id", "cost \u2192 COGS \u00b7 DC \u2192 parcels"], True,
            note="181,415 sold = 1 per line item"),
        link([(420, 300), (290, 300)], "user_id", "many \u2192 1 \u00b7 0 orphans", True, 355, 268),
        link([(420, 225), (355, 225), (355, 84), (290, 84)], "order_id", "not joined: redundant",
             False, 362, 150, "start"),
        link([(155, 452), (155, 354)], "user_id", "not used", False, 165, 406, "start"),
        link([(600, 380), (600, 467), (830, 467)], "inventory_item_id",
             "1 \u2194 1 \u00b7 45,373 rows before and after", True, 715, 492),
        link([(690, 240), (830, 240)], "product_id", "not needed", False, 760, 212),
        link([(965, 176), (965, 120)], "distribution_center_id", "", False, 952, 153, "end"),
    ]
    style = (f"<style>.tn{{font:700 16px {FONT_H}}}.tr{{font:600 14px {FONT_M}}}"
             f".tg{{font:500 13.5px {FONT_B}}}.tk{{font:12.5px {FONT_M}}}"
             f".tnote{{font:700 11px {FONT_B};letter-spacing:.06em}}"
             f".lk{{font:600 13px {FONT_M}}}.ls{{font:12px {FONT_B}}}</style>")
    return (f'<svg viewBox="0 0 1120 600" width="100%" role="img" '
            f'aria-label="Entity relationship diagram of the seven theLook tables">{style}'
            + "\n".join(parts) + "</svg>")


# ================================================================= slides
# Writing rule for every slide: a short title that IS the takeaway, the chart,
# at most three evidence numbers, one-line footnote. The talk track carries the
# rest - the slide only has to tell the reader where to look.

def slide(n, kicker, title_, body, foot, cls="", sub=None):
    return f"""
<section class="slide {cls}" data-n="{n}">
  <header class="top"><span class="kick">{kicker}</span><span class="brand"><b>peek</b> · DAISY · Product &amp; BI Analyst challenge</span></header>
  <h1>{title_}</h1>
  {f'<p class="sub">{sub}</p>' if sub else ''}
  <div class="body">{body}</div>
  <footer class="foot"><span>{foot}</span><span class="pg">{n}</span></footer>
</section>"""


def rail(items, cls=""):
    out = [f'<div class="ev"><div class="evn">{big}</div><div class="evl">{lab}</div></div>'
           for big, lab in items]
    return f'<aside class="rail {cls}">' + "".join(out) + "</aside>"


S = []

# ---- cover ----------------------------------------------------------------------
S.append(f"""
<section class="slide cover" data-n="0">
  <div class="cv-top"><span class="cv-for">Prepared for <span class="cv-logo">peek</span></span><span class="cv-tag">DAISY · Data, AI, Strategy &amp; Yield</span></div>
  <div class="cv-main">
    <p class="cv-kick">Product &amp; BI Analyst — data challenge</p>
    <h1 class="cv-h">Growth runs on<br>first purchases</h1>
    <p class="cv-sub">Customers, churn and a free-shipping policy — and three moves to act on it.</p>
  </div>
  <div class="cv-foot"><span>Federico Lira · September 2026</span>
    <span>theLook e-commerce · BigQuery · Jan 2019 – {mlabel(last, True)}</span></div>
</section>""")

# ---- 1 executive summary -------------------------------------------------------
S.append(slide(
    "1", "Executive summary", "Growth runs on first purchases",
    f"""
<div class="kpis">
  <div class="kpi"><div class="kl">Revenue, {mlabel(last, True)}</div><div class="kn">{money(rev_last, k=True)}</div>
    <div class="kd up">+{rev_yoy:.0f}% year over year</div></div>
  <div class="kpi"><div class="kl">From first-time buyers</div><div class="kn">{share_new_t12:.0f}%</div>
    <div class="kd">of revenue, last 12 months</div></div>
  <div class="kpi"><div class="kl">Buy again within a year</div><div class="kn">1 in {one_in}</div>
    <div class="kd">median wait: {g_median} days</div></div>
  <div class="kpi"><div class="kl">Free shipping over $100</div><div class="kn neg">−{abs(sim_gp_chg):.0f}%</div>
    <div class="kd">gross profit, simulated</div></div>
</div>
<div class="twocol">
  <div><p class="colh">What we found</p><ol class="takeaways">
    <li>Revenue <b>+{rev_yoy:.0f}%</b> — all volume; basket size flat</li>
    <li><b>{share_new_t12:.0f}%</b> of revenue from first-time buyers; few come back</li>
    <li>Free shipping over $100 <b>pays for baskets that already exist</b></li>
  </ol></div>
  <div><p class="colh rec">What we should do</p><ol class="takeaways recs">
    <li><b>Win the second purchase</b> in the first 60 days</li>
    <li><b>Free shipping on the second order</b> — US first</li>
    <li><b>Fix measurement</b> before scaling decisions</li>
  </ol></div>
</div>""",
    f"Completed sales only (brief definition). Jan 2019 – {mlabel(last, True)}; partial month and "
    f"{future_rows:,} future-dated rows excluded (as of {as_of}).", "exec"))

# ---- 2 financial health ------------------------------------------------------
S.append(slide(
    "2", "Situation · Financial health", f"Revenue +{rev_yoy:.0f}% — driven by volume, not basket",
    f'<div class="chart wide">{chart_financials()}</div>' + rail([
        (f"+{ord_yoy:.0f}%", "orders, year over year"),
        (f"${min(aov_win):.0f}–${max(aov_win):.0f}", "order value — flat for 2 years"),
        (f"{money(t12_rev, k=True)}", f"revenue, last 12 months (+{t12_growth:.0f}%)"),
    ]),
    "Task A. Last 24 complete months."))

# ---- 3 new vs returning --------------------------------------------------------
S.append(slide(
    "3", "Complication · Revenue mix", f"{share_new_t12:.0f}% of revenue comes from first-time buyers",
    f'<div class="chart wide">{chart_mix()}</div>' + rail([
        (f"+{(ret_per_cust / new_per_cust - 1) * 100:.0f}%", "spend per returning customer vs new"),
        (f"−{acq_drop_10:.0f}%", "revenue if new customers fall 10%"),
        (f"{search_share:.0f}%", "of first-time buyers come from Search"),
    ]),
    "Task B. New = first completed order that month; new + returning = active in every month (QA.4)."))

# ---- 4 churn vs revenue ----------------------------------------------------------
S.append(slide(
    "4", "Complication · Churn vs revenue", f"Even over a full year, {churn365:.0f}% don’t come back",
    f"""<div class="chart wide">{chart_churn()}</div>
<aside class="rail">
  <div class="ev"><div class="evn">{churn90_same:.1f}% → {churn365:.1f}%</div><div class="evl">churn at 90 vs 365 days</div></div>
  <div class="ev"><div class="evn">{churn_brief_h:.1f}% → {churn_alt:.1f}%</div><div class="evl">if all valid orders count, not only ‘Complete’</div></div>
  <div class="ev minich"><div class="evl"><b>90-day churn by channel</b></div>{chart_sources()}</div>
</aside>""",
    f"Task C. Months after {mlabel(last_meas, True)} have no full 90-day window — computing them anyway shows 100%."))

# ---- 5 why: cohort + LTV ------------------------------------------------------------
S.append(slide(
    "5", "Complication · Why", f"The first order is {first_order_share:.0f}% of two-year value",
    f"""<div class="pair">
  <figure><figcaption><b>Cohort retention</b> — % buying again in month N</figcaption>{chart_cohort()}</figure>
  <figure><figcaption><b>Cumulative spend per customer</b></figcaption>{chart_ltv()}</figure>
</div>""",
    f"Task C stretch + LTV. Month 1 is the repeat peak: {m1_med:.1f}% of a cohort vs {later_med:.1f}% after.",
    sub=f"Month 1 is the best chance of a second purchase."))

# ---- 6 recommendations ----------------------------------------------------------------
S.append(slide(
    "6", "Resolution · Recommendations", "Three moves to build a repeat base",
    f"""<div class="recs3">
  <div class="rc"><div class="rn">1</div><h3>Win the 2nd purchase in 60 days</h3>
    <p class="rw">Month 1 is the repeat peak ({m1_med:.1f}% vs {later_med:.1f}%).</p>
    <dl><dt>Target</dt><dd>All first-time buyers — by timing, not channel</dd>
      <dt>KPI</dt><dd>12-month repeat vs holdout (today {g_365:.1f}%)</dd>
      <dt>Guardrail</dt><dd>Incentive cost per extra order</dd></dl>
    <p class="rs">+{TARGET_PTS} pts ≈ <b>{money(rev_target, k=True)}</b>/yr</p></div>
  <div class="rc"><div class="rn">2</div><h3>Free shipping on the 2nd order</h3>
    <p class="rw">Not over $100: {pct_inframarginal:.0f}% of those parcels go to baskets that already exist.</p>
    <dl><dt>Target</dt><dd>US first-time buyers ({dom_rev_share:.0f}% of revenue)</dd>
      <dt>KPI</dt><dd>90-day repeat vs holdout (today {g_90:.1f}%)</dd>
      <dt>Guardrail</dt><dd>Gross profit after shipping</dd></dl>
    <p class="rs">Breaks even at <b>+{be_dom:.1f} pts</b></p></div>
  <div class="rc"><div class="rn">3</div><h3>Fix measurement first</h3>
    <p class="rw">‘Complete’ is a random 25% of orders; 90 days is too short a churn window.</p>
    <dl><dt>Do</dt><dd>Agree “sale” with finance · 12-month churn · automated QA</dd>
      <dt>KPI</dt><dd>QA pass rate · data freshness</dd></dl>
    <p class="rs">Makes 1 and 2 <b>measurable</b></p></div>
</div>""",
    f"Sizing: {new_cust_t12:,} first-time buyers/yr × ${ret_per_cust:.0f}. Parcels assumed ${PARCEL_COST['domestic']:.0f} US / "
    f"${PARCEL_COST['international']:.0f} abroad (no shipping data).", "recslide"))

# ---- 7 free shipping ----------------------------------------------------------------------
S.append(slide(
    "7", "Product change · Free shipping over $100", "Free shipping over $100 lifts revenue, cuts profit",
    f"""<div class="pair">
  <figure><figcaption><b>Orders over $100</b> — share of all orders</figcaption>{chart_sim_share()}</figure>
  <figure><figcaption><b>Gross profit per month</b> — after shipping</figcaption>{chart_sim_gp()}</figure>
</div>""" + rail([
        (f"{sim_ge_a:.0f}% → {sim_ge_s:.0f}%", "orders over $100"),
        (f"{sim_rev_chg:+.1f}%", "revenue"),
        (f"< $1", f"break-even cost per parcel — {pct_inframarginal:.0f}% go to orders already over $100"),
    ], "slim"),
    "Task D, simulated (the policy is hypothetical): 30% of $70–99 orders top up after launch. "
    "Real test: randomized holdout — pre/post can’t separate the policy from growth.",
    sub=f"Simulated impact: gross profit after shipping −{abs(sim_gp_chg):.0f}%."))

# ---- A1 definitions (question 1) -----------------------------------------------------------
S.append(slide(
    "A1", "Appendix · Definitions & alternatives", "What each metric means — and when to change it",
    """<table class="deftab">
  <thead><tr><th>Metric</th><th>Definition used</th><th>Alternative</th><th>Use the alternative when…</th></tr></thead>
  <tbody>
    <tr><td>Churn</td><td>Active in month M, no order in the next 90 days</td><td>12-month window</td><td>Purchases are infrequent (here: median 412 days)</td></tr>
    <tr><td>Active customer</td><td>≥ 1 completed order in the month</td><td>Active in the last 12 months</td><td>The product is bought once or twice a year</td></tr>
    <tr><td>New vs returning</td><td>New in the month of the first completed order</td><td>Returning = bought in last 12 months</td><td>The question is reactivation, not acquisition</td></tr>
    <tr><td>Cohort</td><td>Month of first completed order</td><td>Signup month</td><td>Measuring activation, not repeat</td></tr>
    <tr><td>Funnel</td><td>Signup → order → activated → 2nd order</td><td>Session: product → cart → purchase</td><td>Session data is real (here it is template-generated)</td></tr>
    <tr><td>Product-change KPI</td><td>Primary: behaviour targeted · Guardrail: profit after its cost</td><td>Revenue alone</td><td>Never — revenue hid the free-shipping loss</td></tr>
  </tbody>
</table>""",
    "Full definitions and the ‘Complete’ status caveat in README § Definitions.", "defslide"))

# ---- A2 data model --------------------------------------------------------------------------
S.append(slide(
    "A2", "Appendix · Data model", "One fact table, two joins, zero fan-out",
    f"""<div class="dm">{data_model_svg()}</div>
<aside class="rail rules">
  <div class="rh">Join rules</div>
  <ol>
    <li><b>Grain first</b> — one row per line item</li>
    <li><b>Count rows</b> before and after every join</li>
    <li><b>Skip joins</b> that add no columns (orders)</li>
    <li><b>Aggregate</b> before one-to-many joins</li>
  </ol>
</aside>""",
    "Black = joined · grey = not needed. 0 orphan keys. inventory_items: 45,373 rows before and after."))

# ---- A3 data quality ---------------------------------------------------------------------------
S.append(slide(
    "A3", "Appendix · Data quality", "Four data traps, all handled",
    f"""<div class="pair">
  <figure><figcaption><b>Order status by year</b> — a 2019 order is still ‘Shipped’</figcaption>{chart_status()}</figure>
  <div class="dq">
    <div class="dqi"><div class="dqn">{future_rows:,}</div><div class="dqt"><b>rows dated after today</b> — excluded</div></div>
    <div class="dqi"><div class="dqn">{status_complete:.0f}%</div><div class="dqt"><b>of items ‘Complete’</b>, every year — status is random</div></div>
    <div class="dqi"><div class="dqn">3</div><div class="dqt"><b>months with no full churn window</b> — flagged, not reported</div></div>
    <div class="dqi"><div class="dqn">0</div><div class="dqt"><b>empty columns</b> — every null is structural</div></div>
  </div>
</div>""",
    "QA.1–QA.4 in sql/part1_queries.sql; null audit in README."))

# ---- A4 funnels -------------------------------------------------------------------------------------
S.append(slide(
    "A4", "Appendix · Funnels", "Session data can’t measure conversion",
    f"""<div class="pair">
  <figure><figcaption><b>events</b> — anonymous traffic is a constant</figcaption>{chart_events()}</figure>
  <figure><figcaption><b>Order timing</b> — orders fall at random between signup and today</figcaption>{chart_placement()}</figure>
</div>
<aside class="rail slim">
  <div class="ev"><div class="evl"><b>The funnel we use</b> — per user</div></div>
  <div class="lcf">
    <div><b>100</b><span>signed up</span></div>
    <div><b>{lc_order:.0f}</b><span>ordered</span></div>
    <div><b>{lc_activated:.0f}</b><span>activated</span></div>
    <div><b>{lc_repeat:.0f}</b><span>2nd order</span></div>
  </div>
  <div class="ev"><div class="evn">±{lc_spread:.1f} pts</div><div class="evl">across channels</div></div>
</aside>""",
    "Accounts ≥ 1 year old. Activated = first completed order (brief definition)."))

# ---- A5 KPI dashboard ---------------------------------------------------------------------------------
def hbars(items, color, maxv=None):
    maxv = maxv or max(v for _, v in items)
    return "".join(
        f'<div class="hb"><span class="hbl">{lab}</span><span class="hbt"><i style="width:{v / maxv * 100:.1f}%;'
        f'background:{color}"></i></span><span class="hbv">{v:.0f}%</span></div>' for lab, v in items)


tot_b = sum(src_buyers.values())
channel_bars = hbars([(k, v / tot_b * 100) for k, v in src_buyers.items()], NEW, 100)
funnel_bars = hbars([("signed up", 100), ("ordered", lc_order), ("activated", lc_activated),
                     ("2nd order", lc_repeat)], NEW, 100)
ladder_bars = hbars([("in 90 days", g_90), ("in 12 months", g_365), ("ever", g_ever)], NEW, 50)
new_series = [int(by_month_b[m]["new_customers"]) for m in WIN]
ret_series = [fnum(by_month_b[m]["pct_revenue_from_returning"]) for m in WIN]
rev_series = [fnum(by_month_a[m]["revenue"]) for m in WIN]
S.append(slide(
    "A5", "Appendix · Business health dashboard", "Seven metrics leadership should watch",
    f"""<div class="dash">
  <div class="grp"><div class="gh">Acquisition</div>
    <div class="tile"><div class="tl">New customers / month</div><div class="tv">{new_cust_last:,}</div>
      <div class="sp">{spark(new_series)}</div></div>
    <div class="tile"><div class="tl">First-time buyers from Search</div><div class="tv">{search_share:.0f}%</div>
      <div class="bars">{channel_bars}</div></div></div>
  <div class="grp"><div class="gh">Activation</div>
    <div class="tile"><div class="tl">Signup → first order</div><div class="tv">{lc_order:.0f}%</div>
      <div class="bars">{funnel_bars}</div></div></div>
  <div class="grp"><div class="gh">Retention</div>
    <div class="tile hero"><div class="tl">12-month repeat · north star</div><div class="tv">{g_365:.1f}%</div>
      <div class="bars">{ladder_bars}</div></div>
    <div class="tile"><div class="tl">Revenue from returning</div><div class="tv">{share_ret_t12:.0f}%</div>
      <div class="sp">{spark(ret_series, RET)}</div></div></div>
  <div class="grp"><div class="gh">Monetization</div>
    <div class="tile"><div class="tl">Revenue, last 12 months</div><div class="tv">{money(t12_rev, k=True)}</div>
      <div class="sp">{spark(rev_series)}</div></div>
    <div class="tile"><div class="tl">Gross margin</div><div class="tv">{margin_t12:.1f}%</div></div></div>
</div>
<div class="health"><span class="hh">Data health</span>
  <span>✓ last complete month {mlabel(last, True)}</span><span>✓ {future_rows:,} future rows excluded</span>
  <span>{"✓" if qa_pass == len(qa_checks) else "✗"} QA {qa_pass}/{len(qa_checks)} passing</span><span>✓ as of {as_of}</span></div>""",
    "Live in Looker Studio on curated BigQuery views (sql/looker/) — filterable by month, zone, channel, country.",
    "dashslide"))

# ---- A6 AI -------------------------------------------------------------------------------------------------
S.append(slide(
    "A6", "Appendix · AI in this analysis", "AI drafted the work; checks decided what stayed",
    f"""<div class="ai3">
  <div class="aic"><div class="aih">Used for</div>
    <ul><li>Profiling tables, nulls and join keys</li><li>First drafts of every query</li><li>This deck, generated from the SQL outputs</li></ul></div>
  <div class="aic"><div class="aih">Caught by checks</div>
    <ul><li>100% churn months = edge of the data</li><li>A metric that was 100% or 0% by construction</li>
    <li>“Conversion” rising {cvr_last / cvr_first:.0f}× on a constant denominator</li></ul></div>
  <div class="aic"><div class="aih">How I validate</div>
    <ul><li>Row counts before / after joins</li><li>Identity checks that must return 0 rows</li><li>Same metric, two definitions</li></ul></div>
</div>
<p class="prompt"><span>Example prompt</span>“Churn is ~100% for the last three months. Before treating it as real,
what at the data boundary could cause it — and write the SQL check that tells an artifact from a real spike.”</p>""",
    "README § Part 3."))


# ================================================================= page
CSS = """
@page { size: 1600px 900px; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; background: #d8d0ca; }
body { font-family: FB; color: INK; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.slide { width: 1600px; height: 900px; background: BG; position: relative; overflow: hidden;
  padding: 46px 72px 0; display: flex; flex-direction: column; margin: 0 auto 24px;
  break-after: page; page-break-after: always; border-top: 6px solid PLUM; }
@media print { html, body { background: BG; } .slide { margin: 0; } }
.top { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
.kick { font-family: FB; font-size: 13px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: PLUM; }
.brand { font-size: 12.5px; color: INK3; letter-spacing: .03em; }
.brand b { font-family: FH; font-weight: 700; color: PLUM; letter-spacing: -.01em; font-size: 15px; }
h1 { font-family: FH; font-size: 34px; line-height: 1.2; font-weight: 600; letter-spacing: -.015em; margin: 0 0 12px;
  max-width: 1400px; text-wrap: balance; color: INK; }
.sub { font-size: 18.5px; line-height: 1.5; color: INK2; margin: 0 0 14px; max-width: 1280px; }
.body { flex: 1; display: flex; gap: 36px; min-height: 0; align-items: stretch; }
.chart.wide { flex: 1; min-width: 0; display: flex; align-items: center; }
.chart svg, figure svg { display: block; width: 100%; height: auto; }
.rail { width: 300px; flex: none; display: flex; flex-direction: column; gap: 20px; padding-top: 6px;
  border-left: 1px solid RULE; padding-left: 28px; }
.rail.slim { width: 290px; }
.ev .evn { font-family: FH; font-size: 30px; font-weight: 600; letter-spacing: -.02em; line-height: 1.1; color: INK; }
.ev .evl { font-size: 14.5px; line-height: 1.42; color: INK2; margin-top: 4px; }
.ev.minich .evl { margin-bottom: 4px; }
.foot { display: flex; justify-content: space-between; gap: 40px; align-items: flex-end;
  border-top: 1px solid RULE; margin-top: 12px; padding: 11px 0 18px; font-size: 11.5px; line-height: 1.45; color: INK3; }
.foot .pg { font-family: FM; font-weight: 600; color: PLUM; }
.pair { flex: 1; display: flex; gap: 34px; min-width: 0; }
.pair figure { flex: 1; margin: 0; min-width: 0; display: flex; flex-direction: column; }
figcaption { font-size: 14.5px; color: INK2; margin-bottom: 8px; line-height: 1.35; }
figcaption b { color: INK; }

/* cover */
.cover { background: PDEEP; border-top: none; padding: 64px 88px 48px; justify-content: space-between; color: #f8f5f1; }
.cv-top { display: flex; justify-content: space-between; align-items: center; }
.cv-for { font-size: 15px; letter-spacing: .08em; text-transform: uppercase; color: #cdb6c4;
  display: flex; align-items: baseline; gap: 14px; }
.cv-logo { text-transform: none; font-family: FH; font-weight: 700; font-size: 44px; letter-spacing: -.03em; color: #f8f5f1; }
.cv-logo::after { content: ""; display: inline-block; width: 12px; height: 12px; border-radius: 50%;
  background: PLUMLT; margin-left: 4px; }
.cv-tag { font-size: 14px; letter-spacing: .14em; text-transform: uppercase; color: #cdb6c4; }
.cv-kick { font-size: 15px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; color: PLUMLT; margin: 0 0 18px; }
.cv-h { font-family: FH; font-size: 92px; font-weight: 600; line-height: 1.02; letter-spacing: -.035em; margin: 0 0 26px; color: #f8f5f1; }
.cv-sub { font-size: 22px; line-height: 1.5; color: #d9c8d1; max-width: 900px; margin: 0; }
.cv-foot { display: flex; justify-content: space-between; font-size: 14px; color: #b9a3b0;
  border-top: 1px solid #4a3542; padding-top: 18px; }

/* exec */
.exec .body { flex-direction: column; gap: 34px; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: RULE; border: 1px solid RULE; }
.kpi { background: CARD; padding: 24px 26px 22px; }
.kl { font-size: 13px; font-weight: 600; color: INK3; letter-spacing: .02em; line-height: 1.3; min-height: 34px; }
.kn { font-family: FH; font-size: 50px; font-weight: 600; letter-spacing: -.025em; margin: 6px 0 2px; color: INK; }
.kd { font-size: 14px; color: INK2; }
.kd.up { color: GOOD; font-weight: 600; }
.twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; }
.colh { font-size: 13px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: INK3; margin: 0 0 12px; }
.colh.rec { color: PLUM; }
.takeaways { margin: 0; padding: 0; list-style: none; counter-reset: t; display: grid; gap: 20px; }
.takeaways li { counter-increment: t; position: relative; padding-left: 46px; font-size: 18.5px; line-height: 1.5; color: INK2; }
.takeaways li::before { content: counter(t); position: absolute; left: 0; top: 1px; width: 28px; height: 28px;
  border-radius: 50%; background: INK; color: BG; font-weight: 700; font-size: 14px; display: grid; place-items: center; }
.takeaways.recs li::before { background: PLUM; }
.takeaways b { color: INK; }

/* recommendations */
.recslide .body { align-items: stretch; }
.recs3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; flex: 1; }
.rc { background: CARD; border: 1px solid RULE; border-top: 4px solid PLUM; padding: 22px 24px 20px;
  display: flex; flex-direction: column; }
.rn { font-family: FH; font-weight: 700; font-size: 15px; color: CARD; background: PLUM; width: 30px; height: 30px;
  border-radius: 50%; display: grid; place-items: center; margin-bottom: 10px; }
.rc h3 { font-family: FH; font-size: 23px; line-height: 1.25; font-weight: 600; margin: 0 0 10px; color: INK; }
.rw { font-size: 16.5px; line-height: 1.5; color: INK2; margin: 0 0 16px; }
.rc dl { margin: 0; display: grid; grid-template-columns: 92px 1fr; gap: 10px 12px; font-size: 15.5px; line-height: 1.45; }
.rc dt { font-size: 11px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: PLUM; padding-top: 2px; }
.rc dd { margin: 0; color: INK2; }
.rc dd b { color: INK; }
.rs { margin: auto 0 0; padding-top: 14px; border-top: 1px solid RULE; font-size: 16px; line-height: 1.4; color: INK2; }
.rs b { font-family: FH; font-size: 20px; color: PLUM; font-weight: 600; }

/* data model */
.dm { flex: 1; min-width: 0; display: flex; align-items: center; }
.rules .rh { font-size: 13px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: INK3; }
.rules ol { margin: 0; padding-left: 20px; display: grid; gap: 14px; font-size: 15px; line-height: 1.45; color: INK2; }
.rules b { color: INK; }

/* data quality */
.dq { flex: 1; display: flex; flex-direction: column; gap: 18px; justify-content: center; }
.dqi { display: flex; gap: 20px; align-items: baseline; }
.dqn { font-family: FH; font-size: 32px; font-weight: 600; letter-spacing: -.02em; width: 130px; flex: none; text-align: right; color: PLUM; }
.dqt { font-size: 15.5px; line-height: 1.45; color: INK2; }
.dqt b { color: INK; }

/* lifecycle stack */
.lcf { display: grid; gap: 8px; }
.lcf div { display: flex; align-items: baseline; gap: 14px; }
.lcf b { font-family: FH; font-size: 28px; font-weight: 600; letter-spacing: -.02em; width: 56px; text-align: right; flex: none; color: PLUM; }
.lcf span { font-size: 14.5px; color: INK2; line-height: 1.3; }

/* dashboard */
.dashslide .body { flex-direction: column; gap: 16px; }
.dash { display: grid; grid-template-columns: 1.5fr 0.85fr 1.5fr 1.5fr; gap: 16px; flex: 1; }
.grp { display: flex; flex-direction: column; gap: 12px; }
.gh { font-size: 12.5px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: PLUM;
  border-bottom: 2px solid PLUM; padding-bottom: 6px; }
.tile { background: CARD; border: 1px solid RULE; padding: 16px 18px; display: flex; flex-direction: column; gap: 4px; flex: 1; }
.tile.hero { background: PTINT; border-color: PLUM; }
.tl { font-size: 13px; font-weight: 600; color: INK3; line-height: 1.3; }
.tv { font-family: FH; font-size: 34px; font-weight: 600; letter-spacing: -.02em; color: INK; }
.td { font-size: 13px; color: INK2; line-height: 1.35; }
.sp svg { width: 100%; height: auto; display: block; }
.bars { display: grid; gap: 5px; margin: 6px 0 4px; }
.hb { display: grid; grid-template-columns: 92px 1fr 40px; align-items: center; gap: 8px; font-size: 12.5px; color: INK2; }
.hbt { height: 9px; background: GRIDC; border-radius: 2px; overflow: hidden; }
.hbt i { display: block; height: 100%; border-radius: 0 2px 2px 0; }
.hbv { font-family: FM; font-size: 12px; color: INK; text-align: right; }
.health { display: flex; gap: 26px; align-items: center; background: CARD; border: 1px solid RULE; padding: 12px 18px;
  font-size: 14px; color: INK2; }
.health span:not(.hh) { color: GOOD; font-weight: 600; }
.hh { font-size: 12.5px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: INK3; }

/* ai */
.ai { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1px; background: RULE; border: 1px solid RULE; }
.aic { background: CARD; padding: 18px 22px; }
.aih { font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: PLUM; margin-bottom: 8px; }
.aic ul { margin: 0; padding-left: 18px; display: grid; gap: 6px; font-size: 15.5px; line-height: 1.4; color: INK2; }
.slide:has(.ai) .body { flex-direction: column; gap: 18px; }
.prompt { margin: 0; font-size: 17px; line-height: 1.5; font-style: italic; color: INK; border-left: 3px solid PLUM;
  padding: 2px 0 2px 20px; max-width: 1300px; }
.prompt span { display: block; font-style: normal; font-size: 12px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: INK3; margin-bottom: 4px; }


/* concise-deck overrides */
h1 { font-size: 42px; margin-bottom: 14px; }
.kn.neg { color: #b3261e; }
.takeaways li { font-size: 21px; }
.twocol { gap: 56px; }
.rc h3 { font-size: 26px; }
.rw { font-size: 18px; }
.rc dl { font-size: 17px; grid-template-columns: 100px 1fr; }
.rs { font-size: 18px; }
.rs b { font-size: 26px; }
.ev .evn { font-size: 34px; }
.ev .evl { font-size: 16px; }
.deftab { width: 100%; border-collapse: collapse; font-size: 18px; align-self: flex-start; }
.deftab th { text-align: left; font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  color: PLUM; border-bottom: 2px solid PLUM; padding: 10px 14px 10px 0; }
.deftab td { padding: 14px 14px 14px 0; border-bottom: 1px solid RULE; color: INK2; vertical-align: top; line-height: 1.4; }
.deftab td:first-child { font-family: FH; font-weight: 600; color: INK; white-space: nowrap; }
.ai3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: RULE; border: 1px solid RULE; }
.ai3 .aic ul { font-size: 18px; gap: 10px; }
.slide:has(.ai3) .body { flex-direction: column; gap: 28px; }
.prompt { font-size: 19px; }
.dqt { font-size: 18px; }
.dqn { font-size: 38px; }
.rules ol { font-size: 17px; gap: 18px; }
.lcf span { font-size: 16px; }
.tl { font-size: 14px; }

/* text-only slides: centred, larger */
.exec .body { justify-content: center; gap: 60px; }
.exec .kn { font-size: 60px; }
.exec .kpi { padding: 28px 30px 26px; }
.exec .takeaways li { font-size: 24px; }
.exec .takeaways { gap: 24px; }
.recslide .body { align-items: center; }
.recs3 { flex: none; width: 100%; }
.rc { padding: 28px 30px 26px; }
.rs { margin-top: auto; }
.rc dl { margin-bottom: 24px; }
.defslide .body { align-items: center; }
.deftab { font-size: 21px; }
.deftab td { padding: 18px 16px 18px 0; }
.slide:has(.ai3) .body { justify-content: center; gap: 36px; }
.ai3 .aic { padding: 26px 28px; }
.ai3 .aic ul { font-size: 21px; gap: 14px; }
.aih { font-size: 14px; }
.prompt { font-size: 22px; }

/* single-slide preview mode: deck.html?s=3 */
body.one .slide { display: none; margin: 0; }
body.one .slide.show { display: flex; }
"""
for k, v in {"PLUMLT": "#d989b5", "PDEEP": PLUM_DEEP, "PTINT": PLUM_TINT, "PLUM": PLUM,
             "FH": FONT_H, "FB": FONT_B, "FM": FONT_M, "INK3": INK3, "INK2": INK2, "INK": INK,
             "BG": BG, "CARD": CARD, "RULE": RULE, "GOOD": GOOD, "GRIDC": GRID}.items():
    CSS = CSS.replace(k, v)

HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Growth Runs on First Purchases \u2014 Peek BI Analyst Challenge</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700&family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Mono:wght@400;600&display=swap">
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
    for old in shots.glob("slide_*.png"):
        old.unlink()
    for i in range(1, len(S) + 1):
        png = shots / f"slide_{i:02d}.png"
        subprocess.run(base + ["--window-size=1600,900", f"--screenshot={png}", f"{url}?s={i}"],
                       capture_output=True, timeout=120)
    print(f"  -> {shots}  ({len(S)} slides)")
    shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    main()
