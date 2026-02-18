import streamlit as st
import pandas as pd
import sqlite3
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

# select race
race_selector = st.selectbox(
    'Select a race to analyze',
    [r.race_name for r in reversed(races)]
)

st.write(f'Currently viewing age data for: **{race_selector}**')

# load race data
try:
    df = pd.read_sql(f'SELECT * FROM {race_selector}', conn)
except Exception as e:
    st.error(f'Error loading data for {race_selector}: {e}')
    st.stop()

# ensure uploaded column names match expected raceroster column names
expected_columns = ['Participant ID', 'Date', 'Sex', 'City', 'State', 'ZIP/Postal Code', 'Country', 'event', 'Age']
missing_cols = [col for col in expected_columns if col not in df.columns]
if missing_cols:
    st.error(f'The following required columns are missing in this race table: {missing_cols}')
    st.stop()

total_registrants = len(df)

# --- age breakdown ---
st.subheader('registrant age breakdown')

df['Age'] = pd.to_numeric(df['Age'], errors='coerce')
age_bins = [-1, 19, 39, 49, 59, float('inf')]
age_labels = ['0-19', '20-39', '40-49', '50-59', '60+']
df['age_group'] = pd.cut(df['Age'], bins=age_bins, labels=age_labels, right=True)

age_counts = df['age_group'].value_counts().reindex(age_labels).dropna().reset_index()
age_counts.columns = ['age group', 'count']
age_counts['percentage'] = (round(((age_counts['count'] / total_registrants) * 100), 2)).astype(str) + ' %'

st.dataframe(age_counts, use_container_width=True)

st.subheader('by age')
df_age_raw = df['Age'].dropna().astype(int).value_counts().sort_index().reset_index()
df_age_raw.columns = ['age', 'count']
fig_age_raw = px.bar(df_age_raw, x='age', y='count')
st.plotly_chart(fig_age_raw)

st.subheader('by age group')
fig_age_bar = px.bar(age_counts, x='age group', y='count')
st.plotly_chart(fig_age_bar)

fig_age_pie = px.pie(age_counts, values='count', names='age group')
fig_age_pie.update_traces(textinfo='label')
st.plotly_chart(fig_age_pie)

conn.close()
