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

expected_columns = ['Participant ID', 'Date', 'Sex', 'City', 'State', 'ZIP/Postal Code', 'Country', 'event', 'Age']
gender_map = {'M': 'male', 'F': 'female', 'U': 'unknown', 'N': 'N/A'}
age_bins = [-1, 9, 19, 29, 39, 49, 59, 69, 79, float('inf')]
age_labels = ['0-9', '10-19', '20-29', '30-39', '40-49', '50-59', '60-69', '70-79', '80+']

# --- load all race data upfront ---
race_data = {}  # race_name -> df
for race in races:
    conn = connect_db()
    try:
        safe_name = _validate_table_name(race.race_name)
        df = pd.read_sql(f'SELECT * FROM "{safe_name}"', conn)
    except Exception as e:
        st.warning(f'Could not load data for {race.race_name}: {e}')
        continue
    finally:
        conn.close()

    missing_cols = [col for col in expected_columns if col not in df.columns]
    if missing_cols:
        continue

    # clean data
    df['Age'] = pd.to_numeric(df['Age'], errors='coerce')
    df['age_group'] = pd.cut(df['Age'], bins=age_bins, labels=age_labels, right=True)
    df['Sex'] = df['Sex'].fillna('').str.strip().str.upper().map(gender_map).fillna('unknown')
    df['City'] = df['City'].fillna('').str.strip().str.lower()

    race_data[race.race_name] = df

if not race_data:
    st.error('No valid race data found.')
    st.stop()

# use race names as year labels (ordered as they appear in info_df)
race_names_ordered = [r.race_name for r in races if r.race_name in race_data]

# extract year from registration start date for display
race_year_map = {}
for i in range(len(info_df.index)):
    name = info_df['Name'].iloc[i]
    if name in race_data:
        year = datetime.strptime(info_df['Registration start date'].iloc[i], '%Y-%m-%d').year
        race_year_map[name] = str(year)

st.title('year comparison')

# --- compute dominant demographics per year ---
year_dominants = {}  # year_label -> {gender, age, city}
for race_name in race_names_ordered:
    df = race_data[race_name]
    year_label = race_year_map.get(race_name, race_name)
    year_dominants[year_label] = {
        'gender': df['Sex'].value_counts().idxmax(),
        'age': df['age_group'].value_counts().idxmax(),
        'city': df['City'].value_counts().idxmax(),
    }

# --- overview lines ---
for race_name in reversed(race_names_ordered):
    year_label = race_year_map.get(race_name, race_name)
    d = year_dominants[year_label]
    st.write(f"Dominant demographics of year {year_label}: **{d['gender']}** (gender), **{d['age']}** (age), **{d['city']}** (city)")

# --- dominant demographics graph with year toggle ---
st.subheader('dominant demographics')

most_recent_race = race_names_ordered[-1]
most_recent_year = race_year_map.get(most_recent_race, most_recent_race)

all_year_labels = [race_year_map.get(r, r) for r in race_names_ordered]
selected_years = st.multiselect(
    'show dominant demographics from:',
    all_year_labels,
    default=[most_recent_year],
)

# build traces for each selected year's dominants
dominant_records = []
for sel_year in selected_years:
    d = year_dominants[sel_year]
    suffix = f' ({sel_year})' if len(selected_years) > 1 else ''
    for race_name in race_names_ordered:
        df = race_data[race_name]
        year_label = race_year_map.get(race_name, race_name)
        n = len(df)

        gender_count = len(df[df['Sex'] == d['gender']])
        dominant_records.append({
            'year': year_label,
            'category': f"{d['gender']} (gender){suffix}",
            'percent': round(gender_count / n * 100, 2) if n > 0 else 0
        })

        age_count = len(df[df['age_group'] == d['age']])
        dominant_records.append({
            'year': year_label,
            'category': f"{d['age']} (age){suffix}",
            'percent': round(age_count / n * 100, 2) if n > 0 else 0
        })

        city_count = len(df[df['City'] == d['city']])
        dominant_records.append({
            'year': year_label,
            'category': f"{d['city']} (city){suffix}",
            'percent': round(city_count / n * 100, 2) if n > 0 else 0
        })

if dominant_records:
    dominant_df = pd.DataFrame(dominant_records)
    fig_dominant = px.line(dominant_df, x='year', y='percent', color='category', markers=True)
    fig_dominant.update_yaxes(title_text='percent of total')
    fig_dominant.update_xaxes(type='category')
    st.plotly_chart(fig_dominant)

# --- build cross-year summary data ---
years = []
totals = []
gender_records = []
age_records = []
city_records = []

for race_name in race_names_ordered:
    df = race_data[race_name]
    year_label = race_year_map.get(race_name, race_name)
    n = len(df)
    years.append(year_label)
    totals.append(n)

    # gender percentages
    for gender in ['male', 'female', 'unknown', 'N/A']:
        count = len(df[df['Sex'] == gender])
        pct = (count / n * 100) if n > 0 else 0
        gender_records.append({'year': year_label, 'gender': gender, 'percent': round(pct, 2)})

    # age group percentages
    for label in age_labels:
        count = len(df[df['age_group'] == label])
        pct = (count / n * 100) if n > 0 else 0
        age_records.append({'year': year_label, 'age group': label, 'percent': round(pct, 2)})

    # city percentages
    city_vals = df['City'].value_counts()
    for city_name, count in city_vals.items():
        pct = (count / n * 100) if n > 0 else 0
        city_records.append({'year': year_label, 'city': city_name, 'percent': round(pct, 2)})

gender_df = pd.DataFrame(gender_records)
age_df = pd.DataFrame(age_records)
city_df = pd.DataFrame(city_records)

# --- gender trends ---
st.subheader('gender trends')
gender_trend = gender_df[gender_df['gender'].isin(['male', 'female'])]
fig_gender = px.line(gender_trend, x='year', y='percent', color='gender', markers=True)
fig_gender.update_yaxes(title_text='percent of total')
fig_gender.update_xaxes(type='category')
st.plotly_chart(fig_gender)

# --- age trends ---
st.subheader('age trends')
fig_age = px.line(age_df, x='year', y='percent', color='age group', markers=True)
fig_age.update_yaxes(title_text='percent of total')
fig_age.update_xaxes(type='category')
st.plotly_chart(fig_age)

# --- top 5 cities trends ---
st.subheader('top 5 cities trends')
# determine top 5 cities from the most recent year
most_recent_race = race_names_ordered[-1]
most_recent_year = race_year_map.get(most_recent_race, most_recent_race)
recent_city_df = city_df[city_df['year'] == most_recent_year].nlargest(5, 'percent')
top_5_cities = recent_city_df['city'].tolist()

city_trend = city_df[city_df['city'].isin(top_5_cities)]
fig_city = px.line(city_trend, x='year', y='percent', color='city', markers=True)
fig_city.update_yaxes(title_text='percent of total')
fig_city.update_xaxes(type='category')
st.plotly_chart(fig_city)

