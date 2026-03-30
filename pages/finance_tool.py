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
    end_date   = datetime.strptime(info_df['Registration end date'].iloc[i], '%Y-%m-%d').date()
    races.append(Race(start_date, end_date, info_df['Name'].iloc[i]))

# ── financial constants by year ───────────────────────────────────────────────
# Column order mirrors the spec:
#   Race income | Sponsorship | Donations | Total income | Total income less sponsorship
#   | Registrants | Race income per registrant
#   Fixed: BTB (Cost/Consulting) | BTB (Rentals) | EMS | Timing services | Portable
#          | Facebook/Signs | RRCA (insurance) | Other | Photography | Total Fixed expense
#   Variable: Shirts | Medals | Bandana | EMEDIA (Bibs) | Total Variable expense
#   | Total expense | Net (all in) | Net (w/o Sponsorship)
#
# NOTE: Timing services is a FIXED expense in all years.

FINANCE_DATA = {

    "race_2025": {
        # income
        "Race income":                   34_417,
        "Sponsorship":                    8_000,
        "Donations":                      3_352,
        "Total income":                  45_769,
        # fixed expenses
        "BTB (Cost / Consulting)":        7_076,
        "BTB (Rentals)":                  5_407,
        "EMS":                              440,
        "Timing services":                2_453,
        "Portable":                       1_046,
        "Facebook/Signs":                 1_564,
        "RRCA (insurance)":               1_275,
        "Other":                          3_891,
        "Photography":                    1_477,
        # variable expenses
        "Shirts":                         5_745,
        "Medals":                         1_968,
        "Bandana":                          495,
        "EMEDIA (Bibs)":                    475,
        # totals
        "Total expense":                 33_313,
        "Net (all in)":                  12_456,
        "Net (w/o Sponsorship)":          4_456,
    },

    "race_2024": {
        # income
        "Race income":                   33_527,
        "Sponsorship":                    6_000,
        "Donations":                      2_551,
        "Total income":                  42_078,
        # fixed expenses
        "BTB (Cost / Consulting)":        6_875.00,
        "BTB (Rentals)":                  5_585.86,
        "EMS":                              440.00,
        "Timing services":                1_995.00,
        "Portable":                       1_404.63,
        "Facebook/Signs":                 1_277.63,
        "RRCA (insurance)":               1_183.00,
        "Other":                          1_999.26,
        "Photography":                    1_576.00,
        # variable expenses
        "Shirts":                         4_141.79,
        "Medals":                         1_643.50,
        "Bandana":                          492.92,
        "EMEDIA (Bibs)":                    419.10,
        # totals
        "Total expense":                 29_033.69,
        "Net (all in)":                  13_045,
        "Net (w/o Sponsorship)":          7_045,
    },

    "race_2023": {
        # income
        "Race income":                   27_472,
        "Sponsorship":                   30_024,
        "Donations":                      2_303,
        "Total income":                  59_799,
        # fixed expenses
        "BTB (Cost / Consulting)":       10_429,
        "BTB (Rentals)":                  2_240,
        "EMS":                              320,
        "Timing services":                2_221,
        "Portable":                       1_154,
        "Facebook/Signs":                 1_497,
        "RRCA (insurance)":               1_152,
        "Other":                            498,
        "Photography":                    1_227,
        # variable expenses
        "Shirts":                         4_658,
        "Medals":                         2_041,
        "Bandana":                          676,
        "EMEDIA (Bibs)":                    447,
        # totals
        "Total expense":                 28_560,
        "Net (all in)":                  31_239,
        "Net (w/o Sponsorship)":          1_215,
    },

    "race_2022": {
        # income — donations were $0 in 2022 (race income + sponsorship = total exactly)
        "Race income":                   31_654.89,
        "Sponsorship":                   49_789.46,
        "Donations":                          0,
        "Total income":                  81_444.35,
        # fixed expenses
        "BTB (Cost / Consulting)":       10_060,
        "BTB (Rentals)":                  9_213,
        "EMS":                              360,
        "Timing services":                1_997,
        "Portable":                         904,
        "Facebook/Signs":                 3_817,
        "RRCA (insurance)":               1_122,
        "Other":                          2_299,
        "Photography":                    1_216,
        # variable expenses
        "Shirts":                         5_847,
        "Medals":                         7_467,
        "Bandana":                          334,
        "EMEDIA (Bibs)":                    120,
        # totals
        "Total expense":                 44_755,
        "Net (all in)":                  36_689,
        "Net (w/o Sponsorship)":        -13_100,
    },
}

# compute derived totals from line items
FIXED_COLS    = ["BTB (Cost / Consulting)", "BTB (Rentals)", "EMS", "Timing services",
                 "Portable", "Facebook/Signs", "RRCA (insurance)", "Other", "Photography"]
VARIABLE_COLS = ["Shirts", "Medals", "Bandana", "EMEDIA (Bibs)"]

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
    df = pd.read_sql(f"SELECT * FROM {race_selector}", conn)
except Exception as e:
    st.error(f"Error loading data for {race_selector}: {e}")
    st.stop()

actual_registrants       = len(df)
race_income_per_reg      = fin["Race income"]          / actual_registrants
var_per_reg              = fin["Total Variable expense"] / actual_registrants
contribution_margin      = race_income_per_reg - var_per_reg
breakeven_regs           = (fin["Total Fixed expense"] / contribution_margin
                            if contribution_margin > 0 else float("inf"))

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
col8.metric("Breakeven Registrants",      f"{breakeven_regs:,.0f}")

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
        st.dataframe(income_df, use_container_width=True, hide_index=True)

    with right:
        st.markdown("**Fixed Expenses**")
        fixed_items = [(c, fin[c]) for c in FIXED_COLS] + [("Total Fixed expense", fin["Total Fixed expense"])]
        fixed_df = pd.DataFrame(fixed_items, columns=["Category", "Amount ($)"])
        fixed_df["Amount ($)"] = fixed_df["Amount ($)"].apply(lambda x: f"${x:,.2f}")
        st.dataframe(fixed_df, use_container_width=True, hide_index=True)

    st.markdown("**Variable Expenses**")
    var_items = [(c, fin[c]) for c in VARIABLE_COLS] + [("Total Variable expense", fin["Total Variable expense"])]
    var_df = pd.DataFrame(var_items, columns=["Category", "Amount ($)"])
    var_df["Amount ($)"] = var_df["Amount ($)"].apply(lambda x: f"${x:,.2f}")
    st.dataframe(var_df, use_container_width=True, hide_index=True)

# ── year-over-year comparison table ──────────────────────────────────────────
if len(available) > 1:
    st.divider()
    st.subheader("Year-over-Year Comparison")

    # build one row per year with exact column spec
    yoy_rows = []
    for yr in sorted(available):
        f = FINANCE_DATA[yr]
        try:
            yr_regs = len(pd.read_sql(f"SELECT * FROM {yr}", conn))
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
    st.dataframe(yoy_df.set_index("Year").T, use_container_width=True)

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
    st.plotly_chart(fig_yoy, use_container_width=True)

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

above_be = projected_regs >= breakeven_regs
c5, c6 = st.columns(2)
c5.metric("Net (w/o Sponsorship)", f"${proj_net_no_spon:,.0f}")
c6.metric(
    "Breakeven Status",
    "✅ Profitable" if proj_net_all_in > 0 else "❌ Loss",
    delta=f"{'Above' if above_be else 'Below'} breakeven by {abs(projected_regs - breakeven_regs):,.0f} regs",
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
st.plotly_chart(fig_comp, use_container_width=True)

# ── breakeven curve ───────────────────────────────────────────────────────────
st.subheader("Breakeven Curve")

max_x     = max(actual_registrants, projected_regs, int(breakeven_regs) + 50) + 100
reg_range = list(range(0, max_x + 1, 10))
rev_curve = [race_income_per_reg * r + fin["Sponsorship"] + fin["Donations"] for r in reg_range]
exp_curve = [fin["Total Fixed expense"] + var_per_reg * r for r in reg_range]

fig_be = go.Figure()
fig_be.add_trace(go.Scatter(x=reg_range, y=rev_curve, name="Total Income",   line=dict(color="#4f8ef7")))
fig_be.add_trace(go.Scatter(x=reg_range, y=exp_curve, name="Total Expenses", line=dict(color="#e85c5c")))

# stagger annotation y-positions (as paper fractions) so labels never overlap
# even when the three lines are close together
vlines = [
    dict(x=breakeven_regs,     color="orange",  dash="dash", label=f"Breakeven ({breakeven_regs:,.0f})",     y_frac=0.95),
    dict(x=actual_registrants, color="#4f8ef7", dash="dot",  label=f"Actual ({actual_registrants:,})",       y_frac=0.82),
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
st.plotly_chart(fig_be, use_container_width=True)

conn.close()

