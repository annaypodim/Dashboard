"""
One-time cleanup: back up and drop the legacy per-race participant tables.

All participant data now lives in the single `participants` table (race_name
column). The original per-race tables (race_2022, race_2023, ...) were kept only
as a backup after migrate_to_single_table.py ran. This script:

  1. Reads the race names from the `info` table (these are the per-race table
     names — info/finance/participants are never touched).
  2. Dumps each one to ./legacy_race_backup_<timestamp>/<race>.csv so the drop
     is reversible.
  3. Drops the per-race tables.

Usage:
    # Dry run — back up and report what WOULD be dropped, but drop nothing:
    DATABASE_URL="postgresql://..." python drop_legacy_race_tables.py

    # Actually drop, after reviewing the backup:
    DATABASE_URL="postgresql://..." python drop_legacy_race_tables.py --drop

NOTE: After dropping, do NOT re-run migrate_to_single_table.py — it rebuilds
`participants` FROM these tables and would wipe it with nothing to refill from.
"""

import os
import sys
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Tables that must never be dropped, regardless of what's in `info`.
PROTECTED = {"participants", "info", "finance"}

load_dotenv()
PG_URL = os.environ.get("DATABASE_URL")
if not PG_URL:
    raise SystemExit("DATABASE_URL not set -- put it in .env or pass it inline.")

do_drop = "--drop" in sys.argv

engine = create_engine(PG_URL)
backup_dir = f"legacy_race_backup_{datetime.now():%Y%m%d_%H%M%S}"

with engine.connect() as conn:
    races = pd.read_sql("SELECT * FROM info", conn)["Name"].tolist()
    print(f"Found {len(races)} races in info: {races}")

    # Only operate on tables that (a) are named in info, (b) aren't protected,
    # and (c) actually exist as a table in the public schema.
    existing = set(
        pd.read_sql(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'",
            conn,
        )["table_name"].tolist()
    )
    targets = [r for r in races if r not in PROTECTED and r in existing]
    skipped = [r for r in races if r not in targets]
    if skipped:
        print(f"Skipping (protected or not present as a table): {skipped}")

    if not targets:
        print("Nothing to back up or drop. Done.")
        engine.dispose()
        sys.exit(0)

    # 1 + 2. Back up every target table to CSV before touching anything.
    os.makedirs(backup_dir, exist_ok=True)
    print(f"\nBacking up to ./{backup_dir}/ ...")
    for race in targets:
        df = pd.read_sql(f'SELECT * FROM "{race}"', conn)
        path = os.path.join(backup_dir, f"{race}.csv")
        df.to_csv(path, index=False)
        print(f"  {race}: {len(df)} rows -> {path}")

    # 3. Drop, only when explicitly asked.
    if not do_drop:
        print(
            "\nDRY RUN: backup written, no tables dropped. "
            "Review the CSVs, then re-run with --drop to drop these tables:"
        )
        for race in targets:
            print(f'    DROP TABLE "{race}";')
    else:
        print("\nDropping legacy per-race tables...")
        for race in targets:
            conn.execute(text(f'DROP TABLE IF EXISTS "{race}"'))
            conn.commit()
            print(f"  dropped {race}")
        print("\nDone. participants is now the sole copy of registration data.")
        print(f"Backup retained at ./{backup_dir}/ in case you need to restore.")

engine.dispose()
