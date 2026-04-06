import streamlit as st
import pandas as pd
import plotly.express as px
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from class_init import check_requirements_installed, authenticate_user, load_credentials
from nl_query_engine import ask, get_db_schema

load_credentials()

check_requirements_installed()

# authenticate user check
if not authenticate_user():
    st.stop()

# api key check — load from .env so user only enters once ever
api_key = os.environ.get("OPENAI_API_KEY", "")

if not api_key:
    entered_key = st.text_input("OpenAI API Key", type="password")
    if entered_key:
        # persist to .env so it's loaded automatically next time
        env_path = "../.env" if os.path.exists("../.env") else ".env"
        with open(env_path, "a") as f:
            f.write(f"\nOPENAI_API_KEY={entered_key}\n")
        os.environ["OPENAI_API_KEY"] = entered_key
        st.rerun()
    else:
        st.write("Enter your OpenAI API key above to get started.")
        st.stop()
    api_key = entered_key


# model selection
model = st.selectbox(
    'Select model',
    ['gpt-4o-mini', 'gpt-4o'],
    index=0
)

# example questions
st.subheader('example questions')

examples = [
    "How many registrants were there 3 days before the race across all years?",
    "What are the top 5 cities for race_2024?",
    "Show me total registrations by event type for each year",
    "How many female registrants signed up for the 5K in 2024?",
    "What's the age distribution of 10K runners in race_2023?",
    "Compare total registrations between race_2022 and race_2024",
]

cols = st.columns(3)
for i, example in enumerate(examples):
    with cols[i % 3]:
        if st.button(example, key=f"example_{i}", use_container_width=True):
            st.session_state["prefill_question"] = example
            st.rerun()

# question input
st.subheader('your question')

# if an example was clicked, pre-fill the text box (but don't auto-run)
prefill = st.session_state.pop("prefill_question", None)
if prefill:
    st.session_state["question_input"] = prefill
    st.session_state["just_prefilled"] = True

def _on_input_change():
    st.session_state["input_submitted"] = True

question = st.text_input(
    'Ask a question about the race data:',
    placeholder="e.g., How many people registered for the 5K in 2024?",
    key="question_input",
    on_change=_on_input_change,
)

run_query = st.button("Ask", type="primary", use_container_width=True)

# on_change fires for both Enter and prefill, so skip if we just prefilled
if st.session_state.pop("just_prefilled", False):
    st.session_state.pop("input_submitted", None)
    run_query = False

if st.session_state.pop("input_submitted", False):
    run_query = True

if run_query and question:
    with st.spinner("Translating your question and querying the database..."):
        result = ask(question, api_key, model)

    # show generated sql
    if result["sql"]:
        with st.expander("generated SQL", expanded=False):
            st.code(result["sql"], language="sql")

    if result["error"]:
        st.error(result["error"])
        st.stop()

    df = result["data"]

    if df.empty:
        st.warning("The query returned no results. Try rephrasing your question.")
        st.stop()

    st.subheader('results')

    chart_hint = result["chart_hint"]

    # single value
    if chart_hint == "metric":
        value = df.iloc[0, 0]
        col_name = df.columns[0]
        st.metric(label=col_name, value=f"{value:,}" if isinstance(value, (int, float)) else str(value))

    # bar chart
    elif chart_hint == "bar":
        st.dataframe(df, use_container_width=True)
        string_cols = df.select_dtypes(include=["object"]).columns.tolist()
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if string_cols and numeric_cols:
            fig = px.bar(df, x=string_cols[0], y=numeric_cols[0])
            st.plotly_chart(fig, use_container_width=True)

            if len(df) <= 10:
                fig_pie = px.pie(df, values=numeric_cols[0], names=string_cols[0])
                fig_pie.update_traces(textinfo='label')
                st.plotly_chart(fig_pie, use_container_width=True)

    # grouped bar
    elif chart_hint == "grouped_bar":
        st.dataframe(df, use_container_width=True)
        string_cols = df.select_dtypes(include=["object"]).columns.tolist()
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if string_cols and numeric_cols:
            fig = px.bar(df, x=string_cols[0], y=numeric_cols, barmode="group")
            st.plotly_chart(fig, use_container_width=True)

    # line chart
    elif chart_hint == "line":
        st.dataframe(df, use_container_width=True)
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        non_numeric = [c for c in df.columns if c not in numeric_cols]
        if non_numeric and numeric_cols:
            fig = px.line(df, x=non_numeric[0], y=numeric_cols, markers=True)
            fig.update_xaxes(type="category")
            st.plotly_chart(fig, use_container_width=True)
        elif len(numeric_cols) >= 2:
            fig = px.line(df, x=numeric_cols[0], y=numeric_cols[1:], markers=True)
            st.plotly_chart(fig, use_container_width=True)

    # default table
    else:
        st.dataframe(df, use_container_width=True)

    st.write(f'**{len(df)} rows** returned')
