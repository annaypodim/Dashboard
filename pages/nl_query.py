import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from class_init import check_requirements_installed, authenticate_user, load_credentials
from nl_query_engine import (
    analyze,
    get_db_schema,
    is_report_question,
    build_demographic_report,
)

load_credentials()

check_requirements_installed()

# authenticate user check
if not authenticate_user():
    st.stop()

# Black accents instead of Streamlit's default red -- applies to buttons and the
# chat-input send control, which both otherwise render in the theme primary color.
st.markdown(
    """
    <style>
      :root { --primary-color: #000000; }
      button[kind="primary"], button[kind="primaryFormSubmit"] {
        background-color: #000000 !important;
        border-color: #000000 !important;
        color: #ffffff !important;
      }
      [data-testid="stChatInput"] button {
        background-color: #000000 !important;
        color: #ffffff !important;
      }
      /* drop the little user/assistant avatar icons and reclaim their space.
         Streamlit suffixes the testid (…AvatarUser / …AvatarAssistant), so match
         by prefix rather than an exact id. */
      [data-testid^="stChatMessageAvatar"],
      [class^="stChatMessageAvatar"] { display: none !important; }
      [data-testid="stChatMessage"] { gap: 0 !important; }
      /* Give the message body some breathing room from the bubble's left edge.
         Without this the question text sits flush against the border. */
      [data-testid="stChatMessage"] [data-testid="stChatMessageContent"],
      [data-testid="stChatMessage"] .stChatMessageContent {
        padding-left: 0.9rem !important;
        padding-right: 0.9rem !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# api key check — load from .env so user only enters once ever
api_key = os.environ.get("OPENAI_API_KEY", "")

if not api_key:
    entered_key = st.text_input("OpenAI API Key", type="password")
    if entered_key:
        # persist to .env — use same resolution as load_credentials()
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(project_root, ".env")
        if not os.path.exists(env_path):
            env_path = os.path.join(project_root, "..", ".env")
        with open(env_path, "a") as f:
            f.write(f"\nOPENAI_API_KEY={entered_key}\n")
        os.environ["OPENAI_API_KEY"] = entered_key
        st.rerun()
    else:
        st.write("Enter your OpenAI API key above to get started.")
        st.stop()
    api_key = entered_key


# sidebar: model choice and a way to start over
with st.sidebar:
    model = st.selectbox('Model', ['gpt-4o-mini', 'gpt-4o'], index=0)
    if st.button('Clear chat'):
        st.session_state.pop("chat", None)
        st.rerun()

st.markdown("##### natural language query")

if "chat" not in st.session_state:
    st.session_state["chat"] = []


def _small_chart(fig, key):
    """Render a plotly figure at a reduced size.

    Height is capped and the chart is placed in the left ~60% of the row so it
    reads as a compact panel rather than a full-bleed banner.
    """
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
    left, _ = st.columns([3, 2])
    with left:
        st.plotly_chart(fig, use_container_width=True, key=key)


# Dates the user names in the question (e.g. "price increased on 5/11 and 7/6")
# get drawn on any time-series chart as labelled vertical lines, so a question
# like "is there a correlated increase in registrations around these dates" is
# answered visually as well as in prose. Matches M/D, M/D/YY, and M/D/YYYY.
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")


def _reference_dates(question):
    """Return [(month, day, year_or_None, label)] for dates named in the question."""
    out = []
    for m, d, y in _DATE_RE.findall(question or ""):
        month, day = int(m), int(d)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        year = None
        if y:
            year = int(y) + 2000 if len(y) == 2 else int(y)
        out.append((month, day, year, f"{month}/{day}"))
    return out


def _looks_like_dates(series):
    """True if the column parses as real dates (a genuine time axis, not year labels)."""
    parsed = pd.to_datetime(series, errors="coerce")
    return parsed.notna().mean() >= 0.8 and parsed.dt.normalize().nunique() > 1


def _add_date_markers(fig, x_series, question):
    """Draw a vertical line + label for each date named in the question.

    A bare M/D (no year) is placed in every year the data spans, so the marker
    lands on the chart regardless of which season the registrations are from.
    """
    refs = _reference_dates(question)
    if not refs:
        return
    parsed = pd.to_datetime(x_series, errors="coerce").dropna()
    if parsed.empty:
        return
    years = sorted(parsed.dt.year.unique())
    for month, day, year, label in refs:
        for yr in ([year] if year else years):
            try:
                stamp = pd.Timestamp(year=yr, month=month, day=day)
            except ValueError:
                continue
            if not (parsed.min() <= stamp <= parsed.max()):
                continue
            # Draw the line and label separately: add_vline's own annotation
            # averages the x-coords, which errors on pandas Timestamps.
            fig.add_vline(x=stamp, line_dash="dash", line_color="#c0392b")
            fig.add_annotation(
                x=stamp, yref="paper", y=1.0, text=label,
                showarrow=False, font=dict(color="#c0392b", size=11),
            )


def render_response(result, turn_id, question=""):
    """Render one assistant turn from an analyze() result dict.

    `turn_id` makes plotly chart keys unique -- the same figure is re-rendered on
    every rerun as history replays, and Streamlit rejects duplicate element keys.
    """
    if result["sql"]:
        with st.expander("generated SQL", expanded=False):
            st.code(result["sql"], language="sql")

    if result["error"]:
        st.error(result["error"])
        return

    df = result["data"]
    if df is None or df.empty:
        st.warning("The query returned no results. Try rephrasing your question.")
        return

    evidence = result["evidence"]
    narrative = result["narrative"]
    routing = result.get("routing")

    # A causal question ("why did X happen", "impact of price on signups") is
    # answered descriptively but flagged up front, so the reader does not mistake
    # a GROUP BY for evidence of cause.
    if routing and routing["intent"] == "causal":
        st.info(routing["caveat"])

    for caveat in evidence.caveats:
        st.warning(caveat)

    if narrative:
        st.info(narrative["text"])
        if narrative["guard_status"] == "fallback":
            st.caption(
                "The written summary was rejected for citing a number not in the data, "
                "so this is the raw statistical finding instead."
            )

    chart_hint = result["chart_hint"]

    if chart_hint == "metric":
        value = df.iloc[0, 0]
        col_name = df.columns[0]
        st.metric(label=col_name, value=f"{value:,}" if isinstance(value, (int, float)) else str(value))

    elif chart_hint == "pivot_bar":
        st.dataframe(df, use_container_width=True)
        string_cols = df.select_dtypes(include=["object"]).columns.tolist()
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        # Per rule 11 the year label is the first string column; the second is the
        # breakdown dimension. Categories go on x so they compare across years.
        year_col, cat_col, val_col = string_cols[0], string_cols[1], numeric_cols[0]
        wide = df.pivot_table(index=cat_col, columns=year_col, values=val_col,
                              aggfunc="sum", fill_value=0).reset_index()
        years = [c for c in wide.columns if c != cat_col]
        fig = px.bar(wide, x=cat_col, y=years, barmode="group")
        fig.update_yaxes(title=val_col)
        _small_chart(fig, key=f"pivot_{turn_id}")
        # Share view: category mix within each year, so a year with more total
        # registrants doesn't just look uniformly taller.
        pct = df.pivot_table(index=year_col, columns=cat_col, values=val_col,
                             aggfunc="sum", fill_value=0)
        pct = (pct.div(pct.sum(axis=1), axis=0) * 100).round(1).reset_index()
        cats = [c for c in pct.columns if c != year_col]
        fig_pct = px.bar(pct, x=year_col, y=cats, barmode="stack")
        fig_pct.update_yaxes(title="% share")
        _small_chart(fig_pct, key=f"pivotshare_{turn_id}")

    elif chart_hint == "metrics":
        # One row, several figures: show them as KPI tiles rather than a
        # single-point chart. Tiles wrap onto a second line past four columns.
        row = df.iloc[0]
        cols = list(df.columns)
        for start in range(0, len(cols), 4):
            chunk = cols[start:start + 4]
            for slot, name in zip(st.columns(len(chunk)), chunk):
                value = row[name]
                slot.metric(
                    label=str(name),
                    value=f"{value:,.2f}".rstrip("0").rstrip(".")
                    if isinstance(value, float) else f"{value:,}"
                    if isinstance(value, int) else str(value),
                )
        with st.expander("data", expanded=False):
            st.dataframe(df, use_container_width=True)

    elif chart_hint == "bar":
        st.dataframe(df, use_container_width=True)
        string_cols = df.select_dtypes(include=["object"]).columns.tolist()
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if string_cols and numeric_cols:
            fig = px.bar(df, x=string_cols[0], y=numeric_cols[0])
            _small_chart(fig, key=f"bar_{turn_id}")
            if len(df) <= 10:
                fig_pie = px.pie(df, values=numeric_cols[0], names=string_cols[0])
                fig_pie.update_traces(textinfo='label')
                _small_chart(fig_pie, key=f"pie_{turn_id}")

    elif chart_hint == "grouped_bar":
        st.dataframe(df, use_container_width=True)
        string_cols = df.select_dtypes(include=["object"]).columns.tolist()
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if string_cols and numeric_cols:
            fig = px.bar(df, x=string_cols[0], y=numeric_cols, barmode="group")
            _small_chart(fig, key=f"grouped_{turn_id}")
            # A share view alongside the counts, so categories of very different
            # sizes stay comparable.
            share = df.copy()
            totals = share[numeric_cols].sum(axis=1)
            for c in numeric_cols:
                share[c] = (share[c] / totals * 100).round(1)
            fig_share = px.bar(share, x=string_cols[0], y=numeric_cols, barmode="stack")
            fig_share.update_yaxes(title="% share")
            _small_chart(fig_share, key=f"groupedshare_{turn_id}")

    elif chart_hint == "line":
        st.dataframe(df, use_container_width=True)
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        non_numeric = [c for c in df.columns if c not in numeric_cols]
        if non_numeric and numeric_cols:
            xcol = non_numeric[0]
            if _looks_like_dates(df[xcol]):
                # A real time axis: keep it continuous and drop in the
                # user's reference dates (e.g. price-increase dates) as markers.
                d = df.copy()
                d[xcol] = pd.to_datetime(d[xcol], errors="coerce")
                fig = px.line(d, x=xcol, y=numeric_cols, markers=True)
                _add_date_markers(fig, d[xcol], question)
            else:
                fig = px.line(df, x=xcol, y=numeric_cols, markers=True)
                fig.update_xaxes(type="category")
            _small_chart(fig, key=f"line_{turn_id}")
        elif len(numeric_cols) >= 2:
            fig = px.line(df, x=numeric_cols[0], y=numeric_cols[1:], markers=True)
            _small_chart(fig, key=f"linexy_{turn_id}")

    else:
        # Fallback: still give a graph with every answer whenever the shape
        # allows one, rather than dropping to a bare table.
        st.dataframe(df, use_container_width=True)
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        string_cols = df.select_dtypes(include=["object"]).columns.tolist()
        if string_cols and numeric_cols:
            fig = px.bar(df, x=string_cols[0], y=numeric_cols[0])
            _small_chart(fig, key=f"fallback_{turn_id}")
        elif len(numeric_cols) >= 2:
            fig = px.line(df, x=numeric_cols[0], y=numeric_cols[1:], markers=True)
            _small_chart(fig, key=f"fallbackxy_{turn_id}")

    st.caption(f"{len(df)} rows returned")


def _render_panel(panel, key):
    """Chart one demographic-report panel according to its declared shape."""
    df = panel["df"]
    st.markdown(f"**{panel['title']}**")
    if panel.get("note"):
        st.caption(panel["note"])

    if df is None or df.empty:
        st.info("No data for this breakdown.")
        return

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    string_cols = df.select_dtypes(include=["object"]).columns.tolist()
    chart = panel["chart"]

    if chart == "trend" and numeric_cols and string_cols:
        # one row per year: race_name (x) + a single value column.
        fig = px.line(df, x=string_cols[0], y=numeric_cols[0], markers=True)
        fig.update_xaxes(type="category")
        _small_chart(fig, key=key)

    elif chart in ("share", "grouped") and len(string_cols) >= 2 and numeric_cols:
        # long form: year + category + count -> pivot to year x category.
        year_col, cat_col, val_col = string_cols[0], string_cols[1], numeric_cols[0]
        wide = df.pivot_table(index=year_col, columns=cat_col, values=val_col,
                              aggfunc="sum", fill_value=0).reset_index()
        cats = [c for c in wide.columns if c != year_col]
        fig = px.bar(wide, x=year_col, y=cats, barmode="group")
        _small_chart(fig, key=key + "_g")
        if chart == "share":
            pct = wide.copy()
            totals = pct[cats].sum(axis=1)
            for c in cats:
                pct[c] = (pct[c] / totals * 100).round(1)
            fig_pct = px.bar(pct, x=year_col, y=cats, barmode="stack")
            fig_pct.update_yaxes(title="% share")
            _small_chart(fig_pct, key=key + "_s")

    elif chart == "bar" and numeric_cols and string_cols:
        fig = px.bar(df, x=string_cols[0], y=numeric_cols[0])
        _small_chart(fig, key=key)

    with st.expander("data", expanded=False):
        st.dataframe(df, use_container_width=True)


def render_report(panels, turn_id):
    """Render a multi-panel demographic report as a stack of charted sections."""
    st.info(
        "Here's a demographic profile of the registrants with every year side by "
        "side. The most recent year is still in progress, so treat it as 'so far'."
    )
    for j, panel in enumerate(panels):
        _render_panel(panel, key=f"report_{turn_id}_{j}")
        st.divider()


# replay the conversation so far
for i, turn in enumerate(st.session_state["chat"]):
    with st.chat_message("user"):
        st.markdown(turn["question"])
    with st.chat_message("assistant"):
        if turn.get("report") is not None:
            render_report(turn["report"], turn_id=i)
        else:
            render_response(turn["result"], turn_id=i, question=turn["question"])

# new question
question = st.chat_input("Ask about the race data...")
if question:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        if is_report_question(question):
            with st.spinner("Building report..."):
                panels = build_demographic_report(question)
            render_report(panels, turn_id=len(st.session_state["chat"]))
            st.session_state["chat"].append({"question": question, "report": panels})
        else:
            with st.spinner("Thinking..."):
                result = analyze(question, api_key, model)
            render_response(result, turn_id=len(st.session_state["chat"]), question=question)
            st.session_state["chat"].append({"question": question, "result": result})
