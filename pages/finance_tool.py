import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from class_init import *

# authenticate user check
if not authenticate_user():
    st.stop()

# connect to the Postgres database
conn = connect_db()

# load race info from dashboard
info = Information()
info_df = info.dataframe

# get list of all races in db
races = []
for i in range(len(info_df.index)):
    start_date = datetime.strptime(info_df['Registration start date'].iloc[i], '%Y-%m-%d').date()
    end_date   = datetime.strptime(info_df['Registration end date'].iloc[i], '%Y-%m-%d').date()
    races.append(Race(start_date, end_date, info_df['Name'].iloc[i]))

# ── financial data ────────────────────────────────────────────────────────────
# Loaded from the remote 'finance' table (was previously hardcoded here).
# Column groupings come from class_init so the finance tool and the uploader
# agree on the line items. Timing services is a FIXED expense in all years.

FIXED_COLS    = FINANCE_FIXED_COLS
VARIABLE_COLS = FINANCE_VARIABLE_COLS

FINANCE_DATA = load_all_finance()

# compute derived totals from line items
for fin in FINANCE_DATA.values():
    fin["Total income less sponsorship"] = fin["Total income"] - fin["Sponsorship"]
    fin["Total Fixed expense"]           = sum(fin[c] for c in FIXED_COLS)
    fin["Total Variable expense"]        = sum(fin[c] for c in VARIABLE_COLS)

# ── race selector ─────────────────────────────────────────────────────────────
st.title("Finance Tool")

available = [r.race_name for r in reversed(races) if r.race_name in FINANCE_DATA]
if not available:
    st.warning("No financial data is configured for any races in the database yet.")
    st.stop()

race_selector = st.selectbox("Select a race to analyze", available)
fin = FINANCE_DATA[race_selector]

st.write(f"Currently viewing financial data for: **{race_selector}**")

# ── load registrant data ──────────────────────────────────────────────────────
try:
    df = load_race_participants(race_selector)
except Exception as e:
    st.error(f"Error loading data for {race_selector}: {e}")
    st.stop()

actual_registrants       = len(df)
race_income_per_reg      = fin["Total income less sponsorship"] / actual_registrants
var_per_reg              = fin["Total Variable expense"] / actual_registrants
contribution_margin      = race_income_per_reg - var_per_reg
breakeven_sp           = ((fin["Total Fixed expense"]-fin["Sponsorship"]-fin["Donations"]) / contribution_margin
                            if contribution_margin > 0 else float("inf"))
breakeven_nosp           = (fin["Total Fixed expense"] / contribution_margin
                            if contribution_margin > 0 else float("inf"))
if(breakeven_sp<0):
    breakeven_sp = 0
# ── summary cards ─────────────────────────────────────────────────────────────
st.subheader("Actual Race Summary")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Registrants",                f"{actual_registrants:,}")
col2.metric("Total Income",               f"${fin['Total income']:,.0f}")
col3.metric("Total Expenses",             f"${fin['Total expense']:,.2f}")
col4.metric("Net (all in)",               f"${fin['Net (all in)']:,.0f}")

col5, col6, col7, col8 = st.columns(4)
col5.metric("Race Income / Registrant",   f"${race_income_per_reg:,.2f}")
col6.metric("Variable Cost / Reg",        f"${var_per_reg:,.2f}")
col7.metric("Contribution Margin / Reg",  f"${contribution_margin:,.2f}")
col8.metric("Breakeven Registrants",      f"{breakeven_sp:,.0f}")

# ── full breakdown ────────────────────────────────────────────────────────────
with st.expander("View Full Financial Breakdown"):
    left, right = st.columns(2)

    with left:
        st.markdown("**Income**")
        income_items = [
            ("Race income",                  fin["Race income"]),
            ("Sponsorship",                  fin["Sponsorship"]),
            ("Donations",                    fin["Donations"]),
            ("Total income",                 fin["Total income"]),
            ("Total income less sponsorship",fin["Total income less sponsorship"]),
        ]
        income_df = pd.DataFrame(income_items, columns=["Category", "Amount ($)"])
        income_df["Amount ($)"] = income_df["Amount ($)"].apply(lambda x: f"${x:,.2f}")
        st.dataframe(income_df, width='stretch', hide_index=True)

    with right:
        st.markdown("**Fixed Expenses**")
        fixed_items = [(c, fin[c]) for c in FIXED_COLS] + [("Total Fixed expense", fin["Total Fixed expense"])]
        fixed_df = pd.DataFrame(fixed_items, columns=["Category", "Amount ($)"])
        fixed_df["Amount ($)"] = fixed_df["Amount ($)"].apply(lambda x: f"${x:,.2f}")
        st.dataframe(fixed_df, width='stretch', hide_index=True)

    st.markdown("**Variable Expenses**")
    var_items = [(c, fin[c]) for c in VARIABLE_COLS] + [("Total Variable expense", fin["Total Variable expense"])]
    var_df = pd.DataFrame(var_items, columns=["Category", "Amount ($)"])
    var_df["Amount ($)"] = var_df["Amount ($)"].apply(lambda x: f"${x:,.2f}")
    st.dataframe(var_df, width='stretch', hide_index=True)

# ── year-over-year comparison table ──────────────────────────────────────────
if len(available) > 1:
    st.divider()
    st.subheader("Year-over-Year Comparison")

    # build one row per year with exact column spec
    yoy_rows = []
    for yr in sorted(available):
        f = FINANCE_DATA[yr]
        try:
            yr_regs = len(load_race_participants(yr))
        except Exception:
            yr_regs = None

        rpr = (f["Race income"] / yr_regs) if yr_regs else None

        row = {"Year": yr}
        row["Race income"]                    = f"${f['Race income']:,.0f}"
        row["Sponsorship"]                    = f"${f['Sponsorship']:,.0f}"
        row["Donations"]                      = f"${f['Donations']:,.0f}"
        row["Total income"]                   = f"${f['Total income']:,.0f}"
        row["Total income less sponsorship"]  = f"${f['Total income less sponsorship']:,.0f}"
        row["Registrants"]                    = f"{yr_regs:,}" if yr_regs else "N/A"
        row["Race income per registrant"]     = f"${rpr:,.2f}" if rpr else "N/A"
        for c in FIXED_COLS:
            row[c] = f"${f[c]:,.2f}"
        row["Total Fixed expense"]            = f"${f['Total Fixed expense']:,.2f}"
        for c in VARIABLE_COLS:
            row[c] = f"${f[c]:,.2f}"
        row["Total Variable expense"]         = f"${f['Total Variable expense']:,.2f}"
        row["Total expense"]                  = f"${f['Total expense']:,.2f}"
        row["Net (all in)"]                   = f"${f['Net (all in)']:,.0f}"
        row["Net (w/o Sponsorship)"]          = f"${f['Net (w/o Sponsorship)']:,.0f}"
        yoy_rows.append(row)

    yoy_df = pd.DataFrame(yoy_rows)
    st.dataframe(yoy_df.set_index("Year").T, width='stretch')

    # YoY bar chart
    years_sorted = sorted(available)
    fig_yoy = go.Figure(data=[
        go.Bar(name="Total Income",      x=years_sorted, y=[FINANCE_DATA[y]["Total income"]          for y in years_sorted], marker_color="#4f8ef7"),
        go.Bar(name="Total Expenses",    x=years_sorted, y=[FINANCE_DATA[y]["Total expense"]         for y in years_sorted], marker_color="#e85c5c"),
        go.Bar(name="Net (all in)",      x=years_sorted, y=[FINANCE_DATA[y]["Net (all in)"]          for y in years_sorted], marker_color="#5cbf7a"),
        go.Bar(name="Net (w/o Sponsor)", x=years_sorted, y=[FINANCE_DATA[y]["Net (w/o Sponsorship)"] for y in years_sorted], marker_color="#f7a24f"),
    ])
    fig_yoy.update_layout(
        barmode="group",
        yaxis_title="Amount ($)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig_yoy.update_yaxes(tickprefix="$", gridcolor="rgba(200,200,200,0.2)")
    st.plotly_chart(fig_yoy, width='stretch')

# ── projection tool ───────────────────────────────────────────────────────────
st.divider()
st.subheader("Registrant Projection & Comparison")

st.write(
    "Enter a **projected registrant count** to see how finances would look "
    "compared to the actual race results."
)

projected_regs = st.number_input(
    "Projected number of registrants",
    min_value=1,
    max_value=10_000,
    value=actual_registrants,
    step=10,
)

# variable costs scale with registrant count; fixed + sponsorship/donations stay constant
proj_race_income   = race_income_per_reg * projected_regs
proj_variable      = var_per_reg         * projected_regs
proj_total_income  = proj_race_income + fin["Sponsorship"] + fin["Donations"]
proj_total_expense = fin["Total Fixed expense"] + proj_variable
proj_net_all_in    = proj_total_income - proj_total_expense
proj_net_no_spon   = proj_net_all_in   - fin["Sponsorship"]

delta_regs    = projected_regs     - actual_registrants
delta_income  = proj_total_income  - fin["Total income"]
delta_expense = proj_total_expense - fin["Total expense"]
delta_net     = proj_net_all_in    - fin["Net (all in)"]

st.write(f"**Projected vs Actual** — {'+' if delta_regs >= 0 else ''}{delta_regs:,} registrants from actual")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Registrants",    f"{projected_regs:,}",          delta=f"{delta_regs:+,}")
c2.metric("Total Income",   f"${proj_total_income:,.0f}",   delta=f"${delta_income:+,.0f}")
c3.metric("Total Expenses", f"${proj_total_expense:,.0f}",  delta=f"${delta_expense:+,.0f}", delta_color="inverse")
c4.metric("Net (all in)",   f"${proj_net_all_in:,.0f}",    delta=f"${delta_net:+,.0f}")

above_be = projected_regs >= breakeven_sp
c5, c6 = st.columns(2)
c5.metric("Net (w/o Sponsorship)", f"${proj_net_no_spon:,.0f}")
c6.metric(
    "Breakeven Status",
    "✅ Profitable" if proj_net_all_in > 0 else "❌ Loss",
    delta=f"{'Above' if above_be else 'Below'} breakeven by {abs(projected_regs - breakeven_sp):,.0f} regs",
    delta_color="normal" if above_be else "inverse",
)

# ── projected vs actual bar chart ─────────────────────────────────────────────
st.subheader("Projected vs Actual — Income, Expense & Net")

categories  = ["Total Income", "Total Expenses", "Net (all in)", "Net (w/o Sponsorship)"]
actual_vals = [fin["Total income"], fin["Total expense"], fin["Net (all in)"], fin["Net (w/o Sponsorship)"]]
proj_vals   = [proj_total_income,   proj_total_expense,   proj_net_all_in,     proj_net_no_spon]

fig_comp = go.Figure(data=[
    go.Bar(name="Actual",    x=categories, y=actual_vals, marker_color="#4f8ef7"),
    go.Bar(name="Projected", x=categories, y=proj_vals,   marker_color="#f7a24f"),
])
fig_comp.update_layout(
    barmode="group",
    yaxis_title="Amount ($)",
    plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
fig_comp.update_yaxes(tickprefix="$", gridcolor="rgba(200,200,200,0.2)")
st.plotly_chart(fig_comp, width='stretch')

# ── breakeven curve ───────────────────────────────────────────────────────────
st.subheader("Breakeven Curve")

max_x     = max(actual_registrants, projected_regs, int(breakeven_sp) + 50) + 100
reg_range = list(range(0, max_x + 1, 5))
rev_curve = [race_income_per_reg * r + fin["Sponsorship"] + fin["Donations"] for r in reg_range]
nosp_curve = [race_income_per_reg * r for r in reg_range]
exp_curve = [fin["Total Fixed expense"] + var_per_reg * r for r in reg_range]

fig_be = go.Figure()
fig_be.add_trace(go.Scatter(x=reg_range, y=rev_curve, name="Total Income",   line=dict(color="#4f8ef7")))
fig_be.add_trace(go.Scatter(x=reg_range, y=exp_curve, name="Total Expenses", line=dict(color="#e85c5c")))
fig_be.add_trace(go.Scatter(x=reg_range, y=nosp_curve, name="No Sponsorship", line=dict(color="#5cbf7a")))

# stagger annotation y-positions (as paper fractions) so labels never overlap
# even when the three lines are close together
vlines = [
    dict(x=breakeven_sp,     color="orange",  dash="dash", label=f"Sponsorship ({breakeven_sp:,.0f})",     y_frac=0.95),
    dict(x=actual_registrants, color="#4f8ef7", dash="dot",  label=f"Actual ({actual_registrants:,})",       y_frac=0.82),
    dict(x=breakeven_nosp, color="#4f8ef7", dash="dash",  label=f"No Sponsorship ({breakeven_nosp:,.0f})",       y_frac=0.95),
]
if projected_regs != actual_registrants:
    vlines.append(
        dict(x=projected_regs, color="#f7a24f", dash="dot",  label=f"Projected ({projected_regs:,})",        y_frac=0.69)
    )

for vl in vlines:
    fig_be.add_vline(
        x=vl["x"],
        line_dash=vl["dash"],
        line_color=vl["color"],
        line_width=1.5,
        annotation_text=vl["label"],
        annotation_position="top left",
        annotation_yref="paper",
        annotation_y=vl["y_frac"],
        annotation_font_color=vl["color"],
        annotation_bgcolor="rgba(30,30,40,0.75)",
        annotation_bordercolor=vl["color"],
        annotation_borderwidth=1,
    )

fig_be.update_layout(
    xaxis_title="Number of Registrants",
    yaxis_title="Amount ($)",
    plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
fig_be.update_yaxes(tickprefix="$", gridcolor="rgba(200,200,200,0.2)")
fig_be.update_xaxes(gridcolor="rgba(200,200,200,0.2)")
st.plotly_chart(fig_be, width='stretch')

conn.close()

