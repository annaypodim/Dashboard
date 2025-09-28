import streamlit as st
import pandas as pd
from datetime import datetime, date
from class_init import *
import csv

check_requirements_installed()
if not authenticate_user():
    st.stop()



# initialize info class
info = Information()
info_df = info.dataframe

races = get_races()

year_selector = st.radio(
    "Select race you want to modify",
    [i.race_name for i in reversed(races)]
)


st.write(f"currently uploading for: {year_selector}")

today = pd.Timestamp(date.today()).date()


for i in reversed(range(len(races))):
    days_from_race = (races[i].end_date-pd.Timestamp(today).date()).days
    if days_from_race >= 0:
        st.write(f"today is {days_from_race} days from race for {races[i].race_name}")
        break



uploaded = False
uploaded_file = st.file_uploader("Upload csv here",type=".csv", accept_multiple_files=False)

ogRace = info.get_race_by_table_name(year_selector)


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
    st.write(f"{len(df)-len(ogRace)} new rows to be added")


submit = st.button("submit")

data = pd.read_csv(uploaded_file, dtype=str, usecols=['Participant ID','Date Registered','Sex','City','State','ZIP/Postal Code','Country','Sub-event','Age'])
df = pd.DataFrame(data).fillna("")
df = df.rename(columns={"Sub-event": "event", "Date Registered": "Date"})
st.write("outside if")
st.write("today:", today)
st.write("first row:", pd.Timestamp(df['Date'].iloc[0]).date())
st.write("last row:", pd.Timestamp(df['Date'].iloc[-1]).date())

if submit and uploaded:
    st.write("Inside If")
    st.write(f"CSV is reporting data for: {df['Date'].iloc[0].date()}")
    st.write("today:", today)
    st.write("first row:", pd.Timestamp(df['Date'].iloc[0]).date())
    st.write("last row:", pd.Timestamp(df['Date'].iloc[-1]).date())
    string = info_df[info_df['Name'] == year_selector]['Registration end date'].iloc[0]
    if today >= pd.Timestamp(df['Date'].iloc[0]).date() and today <= pd.Timestamp(string).date():
        st.write("✅ data within range of race")
        if pd.Timestamp(df['Date'].iloc[-1]).date() >= pd.Timestamp(ogRace['Date'].iloc[-1]).date():
            st.write("✅ Data is okay to be written and is being written")

            conn = connect_db()
            df.to_sql(year_selector, conn, if_exists='replace', index=False)
            conn.commit()
            conn.close()
            st.write("✅ New data has been successfully uploaded")

        else:
            st.write("**❌This appears to be old data for this year and cannot be uploaded**")
    else:
        st.write("❌**Uploaded data is invalid, please check the year of data you are uploading for is the current year**")



st.write("------------------------------------------------------")

st.write("Create a new race below:")


new_uploaded_file = st.file_uploader("Upload csv here",type=".csv", accept_multiple_files=False, key="adsklfj")

if new_uploaded_file is not None:
    data1 = pd.read_csv(new_uploaded_file, dtype=str, usecols=['Participant ID','Date Registered','Sex','City','State','ZIP/Postal Code','Country','Sub-event','Age'])
    df1 = pd.DataFrame(data1).fillna("")
    df1 = df1.rename(columns={"Sub-event": "event", "Date Registered": "Date"})
    for i in range(len(df1)):
        string = df1['Date'].iloc[i]
        string = string[:len(string) - 4]
        df1.at[i, 'Date'] = datetime.strptime(string, '%Y-%m-%d %H:%M:%S')
    st.write(df1)
    uploaded_new = True


race_name = st.text_input("Input a new race name here (refer to top of page to see names already in use), first character MUST BE ALPHABETICAL & NOT A NUMBER OR SYMBOL")
end_date = st.date_input("Input last day of registrations(the day of the race for us)")
create_new_race = st.button("Create new race")


if create_new_race:
    if uploaded_new is not None and race_name is not None and end_date is not None and race_name[0].isalpha() and race_name != "info":

        new_df = df1
        st.write(new_df)
        start_date = new_df['Date'].loc[0]
        if race_name not in [i.race_name for i in races]:
            st.write("✅writing new information")
            conn = connect_db()
            new_info_df = pd.read_sql('SELECT * FROM info', conn)
            new_info_df.loc[len(new_info_df)] = [f"{race_name}", new_df['Date'].loc[0].date(), end_date]
            new_info_df.to_sql("info", conn, index=False, if_exists='replace')
            new_df.to_sql(race_name, conn)
            conn.commit()
            conn.close()
            st.write("✅database updated")
        else:
            st.write("❌name already exists, choose a different name ('info' is also not permited as a race name)")
    else:
        st.write("❌unable to write file")
        st.write(
            f"new_uploaded_file={new_uploaded_file is not None}, "
            f"race_name={race_name is not None}, " 
            f"end_date = {end_date is not None}, "
            f"race_name= {race_name[0].isalpha()}, "
            "race_name is not named 'info'=", {race_name != "info"}
            )
        if not race_name[0].isalpha() or race_name == "info":
            st.write("❌Race name must start with a letter and NOT be 'info'")

