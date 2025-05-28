import streamlit as st
import pandas as pd
from datetime import datetime, date
from class_init import *
import csv


# initialize info class
info = Information()
info_df = info.dataframe

races = []
for i in range(len(info_df.index)):
    start_date = datetime.strptime(info_df['Registration start date'].iloc[i], "%Y-%m-%d").date()
    end_date = datetime.strptime(info_df['Registration end date'].iloc[i], "%Y-%m-%d").date()
    races.append(Race(start_date, end_date, info_df['Name of race'].iloc[i]))



year_selector = st.radio(
    "Select race you want to modify",
    [i.race_name for i in reversed(races)]
)


st.write(f"currently uploading for: {year_selector}")

today = pd.to_datetime(date.today())


for i in reversed(range(len(races))):
    days_from_race = (races[i].end_date-pd.Timestamp(today).date()).days
    if days_from_race >= 0:
        st.write(f"today is {days_from_race} days from race for {races[i].race_name}")
        break



uploaded = False
uploaded_file = st.file_uploader("Upload csv here",type=".csv", accept_multiple_files=False)


if uploaded_file is not None:
    data = pd.read_csv(uploaded_file, dtype=str, usecols=['Participant ID','Date Registered','Sex','City','State','ZIP/Postal Code','Country','Sub-event','Age'])
    df = pd.DataFrame(data).fillna("")
    df = df.rename(columns={"Sub-event": "event", "Date Registered": "Date"})
    for i in range(len(df)):
        string = df['Date'].iloc[i]
        string = string[:len(string) - 4]
        df.at[i, 'Date'] = datetime.strptime(string, '%Y-%m-%d %H:%M:%S')
    st.write(df)
    uploaded = True

submit = st.button("submit")

if submit and uploaded:
    st.write(f"CSV is reporting data for: {df['Date'].iloc[0].date()}")
    info_df['Name of race' == year_selector]['']
    if today >= df['Date'].iloc[0] and today <= df['Date'].iloc[len(df)-1]:
        st.write("data within range of race")
        # match is_new_data(dataframe):
        #     case 0:
        #         st.write("Data already up to date")
        #     case 1:
        #         write_data(dataframe, current_year_number)
        #         st.write("New data uploaded")
        #     case 2:
        #         st.write("Too many values have been removed from the spreadsheet, try to upload a more recent sheet")
    else:
        st.write("Uploaded data is invalid, please check the year of data you are uploading for is the current year")





st.write("Create a new race below:")
new_uploaded_file = st.file_uploader("Upload csv here",type=".csv", accept_multiple_files=False, key="adsklfj")
race_name = st.text_input("Input race name here ex. 2024 race -- Must be just the year")
# start_date = st.date_input("Input start date of registrations")
end_date = st.date_input("Input last day of registrations")
create_new_race = st.button("Create new race")
st.dataframe(pd.read_csv(new_uploaded_file, dtype=str, usecols=['Date Registered', 'Sex', 'City', 'State', 'ZIP/Postal Code', 'Sub-event', 'Age']))


#verify everything to update info.csv exists
if create_new_race and new_uploaded_file is not None and race_name is not None and end_date is not None:
    data1 = pd.read_csv(new_uploaded_file, dtype=str, usecols=['Date Registered', 'Sex', 'City', 'State', 'ZIP/Postal Code', 'Sub-event', 'Age'])
    dataframe1 = pd.DataFrame(data1).fillna("")
    st.write(f"start registration date: {dataframe1['Date Registered'].loc[0]}")
    if race_name not in [i.race_name for i in races]:

        st.write("writing new information")
        dataframe1.to_csv(f'csvs/{race_name}_race.csv', index=False)
        df = pd.read_csv('csvs/info.csv')
        df.loc[-1] = [f"{race_name}_race", dataframe1['Date Registered'].loc[0], end_date]
        df.to_csv("csvs/info.csv",index=False)
    else:
        st.write("name already exists, check to see if this race already exists")

