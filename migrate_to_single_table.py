"""
One-time migration: consolidate the per-race participant tables (race_2022,
race_2023, ...) into a single `participants` table with a race_name column.

Usage:
    DATABASE_URL="postgresql://..." python migrate_to_single_table.py

Idempotent: the participants table is dropped and rebuilt from the per-race
tables every run. The original per-race tables are left untouched as a backup --
drop them separately once the dashboard is verified. Race names come from the
`info` table, so only true participant tables are migrated (info/finance are
ignored).
"""

import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PARTICIPANT_TABLE = "participants"

load_dotenv()
PG_URL = os.environ.get("DATABASE_URL")
if not PG_URL:
    raise SystemExit("DATABASE_URL not set -- put it in .env or pass it inline.")

engine = create_engine(PG_URL)

with engine.connect() as conn:
    races = pd.read_sql("SELECT * FROM info", conn)["Name"].tolist()
    print(f"Found {len(races)} races in info: {races}")

    # Rebuild from scratch so re-runs are safe.
    conn.execute(text(f'DROP TABLE IF EXISTS "{PARTICIPANT_TABLE}"'))
    conn.commit()

    src_counts = {}
    for race in races:
        df = pd.read_sql(f'SELECT * FROM "{race}"', conn)
        if "index" in df.columns:
            df = df.drop(columns=["index"])
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
        df["race_name"] = race
        src_counts[race] = len(df)
        df.to_sql(PARTICIPANT_TABLE, conn, if_exists="append", index=False)
        conn.commit()
        print(f"  migrated {race}: {len(df)} rows")

    # Non-unique index on race_name -- every read filters by it.
    conn.execute(text(
        f'CREATE INDEX IF NOT EXISTS idx_participants_race '
        f'ON "{PARTICIPANT_TABLE}" (race_name)'
    ))
    conn.commit()

    print("\nVerifying per-race row counts...")
    all_ok = True
    for race in races:
        dst = pd.read_sql(
            text(f'SELECT COUNT(*) AS n FROM "{PARTICIPANT_TABLE}" WHERE race_name = :r'),
            conn, params={"r": race},
        )["n"].iloc[0]
        status = "OK" if dst == src_counts[race] else "MISMATCH"
        if dst != src_counts[race]:
            all_ok = False
        print(f"  {race}: source={src_counts[race]} participants={dst} [{status}]")

    total = pd.read_sql(f'SELECT COUNT(*) AS n FROM "{PARTICIPANT_TABLE}"', conn)["n"].iloc[0]
    print(f"  grand total: {total} (expected {sum(src_counts.values())})")

engine.dispose()

print("\nDone." if all_ok else "\nDone, but some counts did not match -- check above.")
print("Backup intact: the original per-race tables were NOT dropped.")
print("After verifying the dashboard, drop them manually, e.g.:")
for race in races:
    print(f'    DROP TABLE "{race}";')
