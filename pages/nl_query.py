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

# api key check
api_key = os.environ.get("OPENAI_API_KEY", "")

if not api_key:
    api_key = st.text_input("OpenAI API Key", type="password")

if not api_key:
    st.write("Enter your OpenAI API key above to get started.")
    st.stop()

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
            st.session_state["nl_question"] = example

# question input
st.subheader('your question')

question = st.text_input(
    'Ask a question about the race data:',
    value=st.session_state.get("nl_question", ""),
    placeholder="e.g., How many people registered for the 5K in 2024?",
    key="question_input",
)

run_query = st.button("Ask", type="primary", use_container_width=True)

# query execution and results
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
