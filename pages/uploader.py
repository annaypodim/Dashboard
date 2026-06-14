import streamlit as st
import pandas as pd
from datetime import datetime, date
from class_init import (
    check_requirements_installed, authenticate_user, Information,
    get_races, connect_db, _validate_table_name, TABLE_NAME_PATTERN,
    load_all_finance, save_finance,
    FINANCE_INCOME_COLS, FINANCE_FIXED_COLS, FINANCE_VARIABLE_COLS, FINANCE_TOTAL_COLS,
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
    """Parse dates in uploaded CSV. Strips trailing timezone abbreviation
    (e.g. ' PST', ' PDT') since pandas no longer parses those."""
    df = df.rename(columns={"Sub-event": "event", "Date Registered": "Date"})
    cleaned = df['Date'].astype(str).str.replace(r'\s+[A-Z]{2,4}$', '', regex=True)
    df['Date'] = pd.to_datetime(cleaned, format='%Y-%m-%d %H:%M:%S', errors='coerce')
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
    st.write(f"CSV is reporting data from: {df['Date'].iloc[0].date()} to {df['Date'].iloc[-1].date()}")
    race_row = info_df[info_df['Name'] == year_selector].iloc[0]
    reg_start = pd.Timestamp(race_row['Registration start date']).date()
    reg_end = pd.Timestamp(race_row['Registration end date']).date()
    csv_first = pd.Timestamp(df['Date'].iloc[0]).date()
    csv_last = pd.Timestamp(df['Date'].iloc[-1]).date()

    if reg_start <= csv_first and csv_last <= reg_end:
        st.write(f"CSV dates fall within {year_selector} registration window ({reg_start} to {reg_end})")
        # Compare the newest date in each set explicitly. Postgres does not
        # guarantee row order without ORDER BY, so positional indexing (iloc[-1])
        # is not a reliable way to find the latest registration.
        uploaded_latest = pd.to_datetime(df['Date']).max()
        existing_latest = pd.to_datetime(ogRace['Date']).max()
        if uploaded_latest.date() >= existing_latest.date():
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
            st.error("This appears to be an older snapshot than what's already in the DB and cannot be uploaded")
    else:
        st.error(f"CSV dates ({csv_first} to {csv_last}) do not fall within {year_selector}'s registration window ({reg_start} to {reg_end}). Check you selected the right race.")



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


st.write("------------------------------------------------------")
st.write("### Finance data")
st.write(
    "Enter or update financial line items for a race. Derived totals "
    "(fixed/variable/income-less-sponsorship) are computed automatically on the "
    "Finance Tool page, so only enter the raw line items below."
)

# refresh races so a newly-created race above is selectable here
finance_races = get_races()

if not finance_races:
    st.info("Create a race first before adding finance data.")
else:
    fin_race = st.selectbox(
        "Select race to edit finance data for",
        [r.race_name for r in reversed(finance_races)],
        key="finance_race_selector",
    )

    existing_fin = load_all_finance().get(fin_race, {})

    with st.form("finance_form"):
        st.write(f"Editing finance data for **{fin_race}**")

        # Single prominent submit button at the top so it's clear when the form
        # saves without scrolling to the bottom of the line-item list.
        save_finance_clicked = st.form_submit_button("Save finance data", type="primary")

        finance_inputs = {}

        # number_input per line item, grouped and prefilled with any existing value
        for header, cols in [
            ("Income", FINANCE_INCOME_COLS),
            ("Fixed expenses", FINANCE_FIXED_COLS),
            ("Variable expenses", FINANCE_VARIABLE_COLS),
            ("Totals", FINANCE_TOTAL_COLS),
        ]:
            st.markdown(f"**{header}**")
            for cat in cols:
                finance_inputs[cat] = st.number_input(
                    cat,
                    value=float(existing_fin.get(cat, 0.0)),
                    step=100.0,
                    # race-specific key so switching the selector loads each
                    # race's own stored values instead of reusing widget state
                    key=f"finance_input_{fin_race}_{cat}",
                )

    if save_finance_clicked:
        try:
            save_finance(fin_race, finance_inputs)
            st.success(f"Finance data saved for {fin_race}")
        except Exception as e:
            st.error(f"Failed to save finance data: {e}")
