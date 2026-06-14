import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from class_init import (
    authenticate_user, connect_db, Information, Race, _validate_table_name
)

# authenticate user check
if not authenticate_user():
    st.stop()

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

# load race data with validated table name
conn = connect_db()
try:
    safe_name = _validate_table_name(race_selector)
    df = pd.read_sql(f'SELECT * FROM "{safe_name}"', conn)
except Exception as e:
    st.error(f'Error loading data for {race_selector}: {e}')
    st.stop()
finally:
    conn.close()

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
city_counts.columns = ['city', 'registrants']

total_registrants = len(df)
city_counts['percentage'] = (round(((city_counts['registrants'] / total_registrants) * 100), 2)).astype(str) + ' %'

# display all cities
st.subheader('all cities')

st.write(f'total registrants: **{total_registrants}**')

st.dataframe(city_counts, use_container_width=True, hide_index=True)

# display top 5 cities
st.subheader('top 5 cities')

top_5 = city_counts.head(5)

st.dataframe(top_5, use_container_width=True, hide_index=True)

st.subheader('by city')
city_pct_raw = (city_counts['registrants'] / total_registrants) * 100
city_pie = city_counts.copy()
city_pie['city'] = city_pie['city'].where(city_pct_raw > 1, 'other')
city_pie = city_pie.groupby('city', as_index=False)['registrants'].sum()
fig = px.pie(city_pie, values='registrants', names='city')
fig.update_traces(textinfo='label')
st.plotly_chart(fig)
