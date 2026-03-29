# financial tool
import streamlit as st
import pandas as pd
import sqlite3
import plotly.graph_objects as go
from datetime import datetime
from class_init import *

# authenticate user check
if not authenticate_user():
    st.stop()

# connect to sqlite database
conn = sqlite3.connect('races.db')

# load race info from dashboard
info = Information()
info_df = info.dataframe

# get list of all races in db
races = []
for i in range(len(info_df.index)):
    start_date = datetime.strptime(info_df['Registration start date'].iloc[i], '%Y-%m-%d').date()
    end_date = datetime.strptime(info_df['Registration end date'].iloc[i], '%Y-%m-%d').date()
    races.append(Race(start_date, end_date, info_df['Name'].iloc[i]))

# ── 2025 financial constants ─────────────────────────────────────────────────
FINANCE_2025 = {
    # income
    "race_income":        34_417,
    "sponsorship":         8_000,
    "donations":           3_352,
    "total_income":       45_769,
    # fixed expenses
    "fixed": {
        "BTB (Race Director Fee)":          7_076,
        "BTB (Equipment Rental)":           5_407,
        "EMS":                                440,
        "Portable":                         1_046,
        "Facebook / Signs":                 1_564,
        "RRCA (Insurance)":                 1_275,
        "Other (Parks, Sign, Acctg)":       3_891,
        "Photography":                      1_477,
    },
    # variable expenses (scale with registrant count)
    "variable": {
        "Shirts":                           5_745,
        "Medals":                           1_968,
        "Bandana":                            495,
        "EMEDIA (Bibs)":                      475,
        "Timing Services":                  2_453,
    },
}

FINANCE_2025["total_fixed"]    = sum(FINANCE_2025["fixed"].values())    # 22,176
FINANCE_2025["total_variable"] = sum(FINANCE_2025["variable"].values()) # 11,137
FINANCE_2025["total_expense"]  = 33_313
FINANCE_2025["net_all_in"]     = 12_456
FINANCE_2025["net_no_sponsor"] =  4_456

# supported years (expand dict above when ready for more years)
SUPPORTED_YEARS = {"race_2025": FINANCE_2025}

# ── race selector ─────────────────────────────────────────────────────────────
st.title("💰 Finance Tool")

available = [r.race_name for r in reversed(races) if r.race_name in SUPPORTED_YEARS]
if not available:
    st.warning("No financial data is configured for any races in the database yet.")
    st.stop()

race_selector = st.selectbox("Select a race to analyze", available)
fin = SUPPORTED_YEARS[race_selector]

st.write(f"Currently viewing financial data for: **{race_selector}**")

# ── load registrant data ──────────────────────────────────────────────────────
try:
    df = pd.read_sql(f"SELECT * FROM {race_selector}", conn)
except Exception as e:
    st.error(f"Error loading data for {race_selector}: {e}")
    st.stop()

actual_registrants = len(df)

# ── per-registrant metrics ────────────────────────────────────────────────────
rev_per_reg      = fin["race_income"]    / actual_registrants  # race income only (excl. sponsorship/donations)
var_per_reg      = fin["total_variable"] / actual_registrants
contribution_margin = rev_per_reg - var_per_reg                # margin per registrant toward fixed costs
breakeven_regs   = fin["total_fixed"] / contribution_margin if contribution_margin > 0 else float("inf")

# ── summary cards ─────────────────────────────────────────────────────────────
st.subheader("📊 Actual Race Summary")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Registrants",              f"{actual_registrants:,}")
col2.metric("Total Income",             f"${fin['total_income']:,.0f}")
col3.metric("Total Expenses",           f"${fin['total_expense']:,.0f}")
col4.metric("Net (all‑in)",             f"${fin['net_all_in']:,.0f}")

col5, col6, col7, col8 = st.columns(4)
col5.metric("Revenue / Registrant",     f"${rev_per_reg:,.2f}")
col6.metric("Variable Cost / Reg",      f"${var_per_reg:,.2f}")
col7.metric("Contribution Margin / Reg",f"${contribution_margin:,.2f}")
col8.metric("Breakeven Registrants",    f"{breakeven_regs:,.0f}")

# ── income & expense breakdown tables ────────────────────────────────────────
with st.expander("📋 View Full Financial Breakdown"):
    left, right = st.columns(2)

    with left:
        st.markdown("**Income**")
        income_rows = {
            "Race Income":   fin["race_income"],
            "Sponsorship":   fin["sponsorship"],
            "Donations":     fin["donations"],
            "**Total**":     fin["total_income"],
        }
        income_df = pd.DataFrame(income_rows.items(), columns=["Category", "Amount ($)"])
        st.dataframe(income_df, use_container_width=True, hide_index=True)

    with right:
        st.markdown("**Fixed Expenses**")
        fixed_df = pd.DataFrame(
            list(fin["fixed"].items()) + [("**Total Fixed**", fin["total_fixed"])],
            columns=["Category", "Amount ($)"]
        )
        st.dataframe(fixed_df, use_container_width=True, hide_index=True)

    st.markdown("**Variable Expenses**")
    var_df = pd.DataFrame(
        list(fin["variable"].items()) + [("**Total Variable**", fin["total_variable"])],
        columns=["Category", "Amount ($)"]
    )
    st.dataframe(var_df, use_container_width=True, hide_index=True)

# ── projection tool ───────────────────────────────────────────────────────────
st.divider()
st.subheader("🔮 Registrant Projection & Comparison")

st.write(
    "Enter a **projected registrant count** to see how the finances would look "
    "compared to the actual race results."
)

projected_regs = st.number_input(
    "Projected number of registrants",
    min_value=1,
    max_value=10_000,
    value=actual_registrants,
    step=10,
)

# projected financials
proj_race_income  = rev_per_reg * projected_regs
proj_variable     = var_per_reg * projected_regs
proj_total_income = proj_race_income + fin["sponsorship"] + fin["donations"]
proj_total_expense = fin["total_fixed"] + proj_variable
proj_net_all_in   = proj_total_income - proj_total_expense
proj_net_no_spon  = proj_net_all_in - fin["sponsorship"]

# delta vs actuals
delta_regs    = projected_regs    - actual_registrants
delta_income  = proj_total_income - fin["total_income"]
delta_expense = proj_total_expense - fin["total_expense"]
delta_net     = proj_net_all_in   - fin["net_all_in"]

st.write(f"**Projected vs Actual** — {'+' if delta_regs >= 0 else ''}{delta_regs:,} registrants from actual")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Registrants",    f"{projected_regs:,}",         delta=f"{delta_regs:+,}")
c2.metric("Total Income",   f"${proj_total_income:,.0f}",  delta=f"${delta_income:+,.0f}")
c3.metric("Total Expenses", f"${proj_total_expense:,.0f}", delta=f"${delta_expense:+,.0f}", delta_color="inverse")
c4.metric("Net (all‑in)",   f"${proj_net_all_in:,.0f}",   delta=f"${delta_net:+,.0f}")

c5, c6 = st.columns(2)
c5.metric("Net (w/o Sponsorship)", f"${proj_net_no_spon:,.0f}")
c6.metric(
    "Status",
    "✅ Profitable" if proj_net_all_in > 0 else "❌ Loss",
    delta=f"{'Above' if projected_regs >= breakeven_regs else 'Below'} breakeven by {abs(projected_regs - breakeven_regs):,.0f} regs",
    delta_color="normal" if projected_regs >= breakeven_regs else "inverse"
)

# ── comparison chart ──────────────────────────────────────────────────────────
st.subheader("📈 Projected vs Actual — Income, Expense & Net")

categories  = ["Total Income", "Total Expenses", "Net (all‑in)", "Net (w/o Sponsorship)"]
actual_vals = [fin["total_income"], fin["total_expense"], fin["net_all_in"], fin["net_no_sponsor"]]
proj_vals   = [proj_total_income,   proj_total_expense,   proj_net_all_in,   proj_net_no_spon]

fig = go.Figure(data=[
    go.Bar(name="Actual",    x=categories, y=actual_vals, marker_color="#4f8ef7"),
    go.Bar(name="Projected", x=categories, y=proj_vals,   marker_color="#f7a24f"),
])
fig.update_layout(
    barmode="group",
    yaxis_title="Amount ($)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    plot_bgcolor="rgba(0,0,0,0)",
)
fig.update_yaxes(tickprefix="$", gridcolor="rgba(200,200,200,0.2)")
st.plotly_chart(fig, use_container_width=True)

# ── breakeven curve ───────────────────────────────────────────────────────────
st.subheader("📉 Breakeven Curve")

reg_range = list(range(0, max(actual_registrants, projected_regs, int(breakeven_regs) + 50) + 100, 10))
revenue_curve = [rev_per_reg * r + fin["sponsorship"] + fin["donations"] for r in reg_range]
expense_curve = [fin["total_fixed"] + var_per_reg * r for r in reg_range]

fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=reg_range, y=revenue_curve, name="Total Income",   line=dict(color="#4f8ef7")))
fig2.add_trace(go.Scatter(x=reg_range, y=expense_curve, name="Total Expenses", line=dict(color="#e85c5c")))
fig2.add_vline(x=breakeven_regs,     line_dash="dash", line_color="orange",  annotation_text=f"Breakeven ({breakeven_regs:,.0f})")
fig2.add_vline(x=actual_registrants, line_dash="dot",  line_color="#4f8ef7", annotation_text=f"Actual ({actual_registrants:,})")
if projected_regs != actual_registrants:
    fig2.add_vline(x=projected_regs, line_dash="dot", line_color="#f7a24f", annotation_text=f"Projected ({projected_regs:,})")
fig2.update_layout(
    xaxis_title="Number of Registrants",
    yaxis_title="Amount ($)",
    plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
fig2.update_yaxes(tickprefix="$", gridcolor="rgba(200,200,200,0.2)")
fig2.update_xaxes(gridcolor="rgba(200,200,200,0.2)")
st.plotly_chart(fig2, use_container_width=True)

conn.close()
