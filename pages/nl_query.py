import streamlit as st
import pandas as pd
import plotly.express as px
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from class_init import check_requirements_installed, authenticate_user, load_credentials
from nl_query_engine import analyze, get_db_schema

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
      [data-testid="stChatMessage"] { padding-left: 0 !important; gap: 0 !important; }
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


def render_response(result, turn_id):
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
        st.error(routing["caveat"])

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

    elif chart_hint == "line":
        st.dataframe(df, use_container_width=True)
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        non_numeric = [c for c in df.columns if c not in numeric_cols]
        if non_numeric and numeric_cols:
            fig = px.line(df, x=non_numeric[0], y=numeric_cols, markers=True)
            fig.update_xaxes(type="category")
            _small_chart(fig, key=f"line_{turn_id}")
        elif len(numeric_cols) >= 2:
            fig = px.line(df, x=numeric_cols[0], y=numeric_cols[1:], markers=True)
            _small_chart(fig, key=f"linexy_{turn_id}")

    else:
        st.dataframe(df, use_container_width=True)

    st.caption(f"{len(df)} rows returned")


# replay the conversation so far
for i, turn in enumerate(st.session_state["chat"]):
    with st.chat_message("user"):
        st.markdown(turn["question"])
    with st.chat_message("assistant"):
        render_response(turn["result"], turn_id=i)

# new question
question = st.chat_input("Ask about the race data...")
if question:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = analyze(question, api_key, model)
        render_response(result, turn_id=len(st.session_state["chat"]))
    st.session_state["chat"].append({"question": question, "result": result})
