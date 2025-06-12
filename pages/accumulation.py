import streamlit as st
from datetime import *
from class_init import *

if not authenticate_user():
    st.stop()


# initialize info class
info = Information()
info_df = info.dataframe

races = []
for i in range(len(info_df.index)):
    start_date = datetime.strptime(info_df['Registration start date'].iloc[i], "%Y-%m-%d").date()
    end_date = datetime.strptime(info_df['Registration end date'].iloc[i], "%Y-%m-%d").date()
    races.append(Race(start_date, end_date, info_df['Name'].iloc[i]))

today = datetime.today().date()

# just calculates day from race
for i in reversed(range(len(races))):
    days_from_race = (races[i].end_date-today).days
    if days_from_race >= 0:
        st.write(f"today is {days_from_race} days from race")
        break
    elif i == len(races)-1:
        st.write("no new race has been uploaded yet to calculate days from race day")
        break


num_days = st.text_input("input days until race here")


if num_days.isnumeric() and int(num_days) < 200 and int(num_days) >= 0:
    col1, col2 = st.columns(2)
    for i in reversed(range(len(races))):
        if i % 2 == 0:
            with col1:
                st.write(races[i].race_name)
                st.dataframe(races[i].get_accumulated_unique_by_day(int(num_days)).set_index('events'))
        else:
            with col2:
                st.write(races[i].race_name)
                st.dataframe(races[i].get_accumulated_unique_by_day(int(num_days)).set_index('events'))
else:
    st.write("invalid input for number of days until race, 199 to 0 valid inputs") 


