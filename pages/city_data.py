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

st.write(f'Currently viewing city data for: **{race_selector}**')

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

# ensure city column is consistent
df['City'] = df['City'].fillna('').str.strip().str.lower()

if df['City'].eq('').all():
    st.warning('No city data found for this race.')
    st.stop()

# calculate counts and percentages
city_counts = df['City'].value_counts().reset_index()
city_counts.columns = ['city', 'count']

total_registrants = len(df)
city_counts['percentage'] = (round(((city_counts['count'] / total_registrants) * 100), 2)).astype(str) + ' %'

# display all cities
st.subheader('all cities')

st.write(f'total registrants: **{total_registrants}**')

st.dataframe(city_counts, use_container_width=True)
print(city_counts)

# display top 5 cities
st.subheader('top 5 cities')

top_5 = city_counts.head(5)

st.dataframe(top_5, use_container_width=True)

st.subheader('registrants by city')
fig = px.pie(city_counts, values='count', names='city')
st.plotly_chart(fig)

conn.close()
