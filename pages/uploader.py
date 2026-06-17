import streamlit as st
import pandas as pd
from datetime import datetime, date
from class_init import (
    check_requirements_installed, authenticate_user, Information,
    get_races, connect_db, _validate_table_name, TABLE_NAME_PATTERN,
    append_new_participants,
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
    """Parse the registration date column from an uploaded CSV.

    Registration exports include a timezone the way pandas cannot parse: a named
    abbreviation like "2026-03-30 18:45:27 PDT". Passing that straight to
    pd.to_datetime crashes hard (AttributeError deep in pandas), and even
    errors='coerce' does not suppress it. So we first strip a trailing alphabetic
    timezone token, then parse. format='mixed' also tolerates other inconsistent
    formats (e.g. numeric offsets, ISO 'T'); any remaining timezone is dropped so
    the result is naive datetime64 in local wall-clock time, matching how existing
    races are stored.
    """
    df = df.rename(columns={"Sub-event": "event", "Date Registered": "Date"})
    raw = df['Date'].astype(str).str.strip()
    # Drop a trailing tz abbreviation (PDT/PST/EDT/UTC/...). We keep local
    # wall-clock time, so dropping the label is correct, not lossy.
    raw = raw.str.replace(r'\s+[A-Za-z]{2,5}$', '', regex=True)
    parsed = pd.to_datetime(raw, format='mixed', errors='coerce')
    parsed = parsed.map(
        lambda ts: ts.replace(tzinfo=None)
        if (ts is not pd.NaT and ts is not None and getattr(ts, 'tzinfo', None) is not None)
        else ts
    )
    df['Date'] = pd.to_datetime(parsed)
    n_bad = int(df['Date'].isna().sum())
    if n_bad:
        st.warning(
            f"{n_bad} row(s) had an unrecognized registration date and were left "
            "blank. Check the 'Date Registered' column in your CSV."
        )
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
    # New rows are those whose Participant ID is not already stored for this race
    # (insert-only dedup), so preview the same count the write will actually add.
    existing_ids = set(ogRace["Participant ID"]) if "Participant ID" in ogRace else set()
    new_count = df.drop_duplicates(subset=["Participant ID"])["Participant ID"].isin(existing_ids).eq(False).sum()
    st.write(f"{new_count} new rows to be added")

submit = st.button("submit")


if submit and uploaded:
    st.write(f"CSV is reporting data for: {df['Date'].iloc[0].date()}")
    string = info_df[info_df['Name'] == year_selector]['Registration end date'].iloc[0]
    if today >= pd.Timestamp(df['Date'].iloc[0]).date() and today <= pd.Timestamp(string).date():
        st.write("data within range of race")
        # Compare the newest date in each set explicitly. Postgres does not
        # guarantee row order without ORDER BY, so positional indexing (iloc[-1])
        # is not a reliable way to find the latest registration.
        uploaded_latest = pd.to_datetime(df['Date']).max()
        existing_latest = pd.to_datetime(ogRace['Date']).max()
        if uploaded_latest.date() >= existing_latest.date():
            # Column-consistency check: the uploaded CSV must have the same columns
            # as what's already stored for this race. If the race has no rows yet,
            # there's nothing to compare against, so skip the check.
            if not ogRace.empty and set(df.columns) != set(ogRace.columns):
                missing = set(ogRace.columns) - set(df.columns)
                extra = set(df.columns) - set(ogRace.columns)
                st.error(
                    "Uploaded columns do not match the existing data for this race "
                    f"-- missing: {sorted(missing)}, unexpected: {sorted(extra)}. "
                    "Nothing was written."
                )
            else:
                st.write("Data is okay to be written and is being written")

                # year_selector comes from radio buttons populated by existing race
                # names, so it's already validated; validate again defensively.
                safe_name = _validate_table_name(year_selector)
                try:
                    added = append_new_participants(safe_name, df)
                    st.write(f"{added} new rows added")
                except Exception as e:
                    st.error(f"Database write failed: {e}")

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
            conn.commit()
        except Exception as e:
            st.error(f"Database write failed: {e}")
        finally:
            conn.close()
        # Participant rows for the new race go into the shared participants table
        # (stamped with race_name) instead of a dedicated per-race table.
        try:
            added = append_new_participants(safe_name, new_df)
            st.write(f"Database updated successfully -- {added} rows added")
        except Exception as e:
            st.error(f"Database write failed: {e}")


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
