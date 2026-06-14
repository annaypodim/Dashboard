"""
One-time migration: copy every table from the local races.db SQLite file into
the remote Postgres database.

Usage:
    pip install -r requirements.txt
    # DATABASE_URL can be set in .env or passed inline:
    DATABASE_URL="postgresql://user:pass@host/dbname?sslmode=require" \
        python migrate_to_postgres.py

It is safe to re-run: each table is written with if_exists="replace", so the
Postgres tables are rebuilt from the SQLite source every time.
"""

import os
import sqlite3

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

SQLITE_PATH = "races.db"

load_dotenv()
PG_URL = os.environ.get("DATABASE_URL")
if not PG_URL:
    raise SystemExit("DATABASE_URL not set -- put it in .env or pass it inline.")

if not os.path.exists(SQLITE_PATH):
    raise SystemExit(f"{SQLITE_PATH} not found -- run this from the project root.")

sqlite_conn = sqlite3.connect(SQLITE_PATH)
pg_engine = create_engine(PG_URL)

# Discover every table in the SQLite file (skip SQLite's internal tables).
tables = pd.read_sql(
    "SELECT name FROM sqlite_master WHERE type='table' "
    "AND name NOT LIKE 'sqlite_%'",
    sqlite_conn,
)["name"].tolist()

print(f"Found {len(tables)} tables to migrate: {tables}")

for table in tables:
    df = pd.read_sql(f'SELECT * FROM "{table}"', sqlite_conn)

    # Drop the leftover pandas index column that some race tables carry
    # (race_2022/2023/2024 have it; race_2025 does not) so every table is uniform.
    if "index" in df.columns:
        df = df.drop(columns=["index"])

    # Store Date as a real Postgres timestamp instead of text. This is what lets
    # the NL query engine use native date comparisons.
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])

    df.to_sql(table, pg_engine, if_exists="replace", index=False)
    print(f"  migrated {table}: {len(df)} rows")

sqlite_conn.close()
pg_engine.dispose()

# Verify row counts match between source and destination.
print("\nVerifying row counts...")
verify_conn = create_engine(PG_URL).connect()
sqlite_conn = sqlite3.connect(SQLITE_PATH)
all_ok = True
for table in tables:
    src = pd.read_sql(f'SELECT COUNT(*) AS n FROM "{table}"', sqlite_conn)["n"].iloc[0]
    dst = pd.read_sql(f'SELECT COUNT(*) AS n FROM "{table}"', verify_conn)["n"].iloc[0]
    status = "OK" if src == dst else "MISMATCH"
    if src != dst:
        all_ok = False
    print(f"  {table}: sqlite={src} postgres={dst} [{status}]")
sqlite_conn.close()
verify_conn.close()

print("\nDone." if all_ok else "\nDone, but some row counts did not match -- check above.")
