import streamlit as st
import pandas as pd
from datetime import datetime, date
from class_init import (
    check_requirements_installed, authenticate_user, Information,
    get_races, connect_db, _validate_table_name, TABLE_NAME_PATTERN
)

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

today = date.today()


for i in reversed(range(len(races))):
    days_from_race = (races[i].end_date - today).days
    if days_from_race >= 0:
        st.write(f"today is {days_from_race} days from race for {races[i].race_name}")
        break


def _parse_csv_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse dates in uploaded CSV using vectorized pandas parsing."""
    df = df.rename(columns={"Sub-event": "event", "Date Registered": "Date"})
    df['Date'] = pd.to_datetime(df['Date'])
    return df


uploaded = False
uploaded_file = st.file_uploader("Upload csv here", type=".csv", accept_multiple_files=False)

ogRace = info.get_race_by_table_name(year_selector)


if uploaded_file is not None:
    try:
        data = pd.read_csv(
            uploaded_file, dtype=str,
            usecols=['Participant ID', 'Date Registered', 'Sex', 'City',
                     'State', 'ZIP/Postal Code', 'Country', 'Sub-event', 'Age']
        )
    except (ValueError, KeyError) as e:
        st.error(f"CSV format error: {e}. Please check column names match expected format.")
        st.stop()

    df = pd.DataFrame(data).fillna("")
    df = _parse_csv_dates(df)
    st.write(df)
    uploaded = True
    st.write(f"{len(df) - len(ogRace)} new rows to be added")

submit = st.button("submit")


if submit and uploaded:
    st.write(f"CSV is reporting data for: {df['Date'].iloc[0].date()}")
    string = info_df[info_df['Name'] == year_selector]['Registration end date'].iloc[0]
    if today >= pd.Timestamp(df['Date'].iloc[0]).date() and today <= pd.Timestamp(string).date():
        st.write("data within range of race")
        if pd.Timestamp(df['Date'].iloc[-1]).date() >= pd.Timestamp(ogRace['Date'].iloc[-1]).date():
            st.write("Data is okay to be written and is being written")

            # year_selector comes from radio buttons populated by existing race names,
            # so it's already validated. But we validate again for defense-in-depth.
            safe_name = _validate_table_name(year_selector)
            conn = connect_db()
            try:
                df.to_sql(safe_name, conn, if_exists='replace', index=False)
                conn.commit()
                st.write("New data has been successfully uploaded")
            except Exception as e:
                st.error(f"Database write failed: {e}")
            finally:
                conn.close()

        else:
            st.error("This appears to be old data for this year and cannot be uploaded")
    else:
        st.error("Uploaded data is invalid, please check the year of data you are uploading for is the current year")



st.write("------------------------------------------------------")

st.write("Create a new race below:")


new_uploaded_file = st.file_uploader("Upload csv here", type=".csv", accept_multiple_files=False, key="new_race_upload")

# Track whether a new file has been uploaded — this variable must exist
# before the create_new_race button check to avoid NameError.
uploaded_new = False
df1 = None

if new_uploaded_file is not None:
    try:
        data1 = pd.read_csv(
            new_uploaded_file, dtype=str,
            usecols=['Participant ID', 'Date Registered', 'Sex', 'City',
                     'State', 'ZIP/Postal Code', 'Country', 'Sub-event', 'Age']
        )
    except (ValueError, KeyError) as e:
        st.error(f"CSV format error: {e}. Please check column names match expected format.")
        st.stop()

    df1 = pd.DataFrame(data1).fillna("")
    df1 = _parse_csv_dates(df1)
    st.write(df1)
    uploaded_new = True


race_name = st.text_input(
    "Input a new race name here (refer to top of page to see names already in use). "
    "Only letters, numbers, and underscores allowed. Must start with a letter."
)
end_date = st.date_input("Input last day of registrations (the day of the race for us)")
create_new_race = st.button("Create new race")


if create_new_race:
    # Validate all required inputs
    name_valid = bool(race_name) and TABLE_NAME_PATTERN.match(race_name) and race_name != "info"

    if not uploaded_new or df1 is None:
        st.error("Please upload a CSV file for the new race first.")
    elif not name_valid:
        st.error("Race name must start with a letter, contain only letters/numbers/underscores, and not be 'info'.")
    elif race_name in [i.race_name for i in races]:
        st.error("Name already exists, choose a different name.")
    else:
        safe_name = _validate_table_name(race_name)
        new_df = df1
        st.write(new_df)
        st.write("Writing new information...")
        conn = connect_db()
        try:
            new_info_df = pd.read_sql('SELECT * FROM info', conn)
            new_info_df.loc[len(new_info_df)] = [safe_name, new_df['Date'].loc[0].date(), end_date]
            new_info_df.to_sql("info", conn, index=False, if_exists='replace')
            new_df.to_sql(safe_name, conn, index=False)
            conn.commit()
            st.write("Database updated successfully")
        except Exception as e:
            st.error(f"Database write failed: {e}")
        finally:
            conn.close()
