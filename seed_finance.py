"""
One-time seed: load the previously-hardcoded finance figures into the remote
'finance' table in Postgres.

Run once after the Postgres migration:
    python3 seed_finance.py

Safe to re-run: values are upserted, so re-running just overwrites each line
item with the seed value again. After seeding, the database is the source of
truth and finance data is edited via the uploader page.
"""

from class_init import ensure_finance_table, save_finance, FINANCE_CATEGORIES

# The original hardcoded figures, ported verbatim from finance_tool.py. Only the
# raw line items are stored; derived totals are computed at display time.
FINANCE_DATA = {
    "race_2025": {
        "Race income":            34_417,
        "Sponsorship":             8_000,
        "Donations":               3_352,
        "Total income":           45_769,
        "BTB (Cost / Consulting)": 7_076,
        "BTB (Rentals)":           5_407,
        "EMS":                       440,
        "Timing services":         2_453,
        "Portable":                1_046,
        "Facebook/Signs":          1_564,
        "RRCA (insurance)":        1_275,
        "Other":                   3_891,
        "Photography":             1_477,
        "Shirts":                  5_745,
        "Medals":                  1_968,
        "Bandana":                   495,
        "EMEDIA (Bibs)":             475,
        "Total expense":          33_313,
        "Net (all in)":           12_456,
        "Net (w/o Sponsorship)":   4_456,
    },
    "race_2024": {
        "Race income":            33_527,
        "Sponsorship":             6_000,
        "Donations":               2_551,
        "Total income":           42_078,
        "BTB (Cost / Consulting)": 6_875.00,
        "BTB (Rentals)":           5_585.86,
        "EMS":                       440.00,
        "Timing services":         1_995.00,
        "Portable":                1_404.63,
        "Facebook/Signs":          1_277.63,
        "RRCA (insurance)":        1_183.00,
        "Other":                   1_999.26,
        "Photography":             1_576.00,
        "Shirts":                  4_141.79,
        "Medals":                  1_643.50,
        "Bandana":                   492.92,
        "EMEDIA (Bibs)":             419.10,
        "Total expense":          29_033.69,
        "Net (all in)":           13_045,
        "Net (w/o Sponsorship)":   7_045,
    },
    "race_2023": {
        "Race income":            27_472,
        "Sponsorship":            30_024,
        "Donations":               2_303,
        "Total income":           59_799,
        "BTB (Cost / Consulting)":10_429,
        "BTB (Rentals)":           2_240,
        "EMS":                       320,
        "Timing services":         2_221,
        "Portable":                1_154,
        "Facebook/Signs":          1_497,
        "RRCA (insurance)":        1_152,
        "Other":                     498,
        "Photography":             1_227,
        "Shirts":                  4_658,
        "Medals":                  2_041,
        "Bandana":                   676,
        "EMEDIA (Bibs)":             447,
        "Total expense":          28_560,
        "Net (all in)":           31_239,
        "Net (w/o Sponsorship)":   1_215,
    },
    "race_2022": {
        "Race income":            31_654.89,
        "Sponsorship":            49_789.46,
        "Donations":                   0,
        "Total income":           81_444.35,
        "BTB (Cost / Consulting)":10_060,
        "BTB (Rentals)":           9_213,
        "EMS":                       360,
        "Timing services":         1_997,
        "Portable":                  904,
        "Facebook/Signs":          3_817,
        "RRCA (insurance)":        1_122,
        "Other":                   2_299,
        "Photography":             1_216,
        "Shirts":                  5_847,
        "Medals":                  7_467,
        "Bandana":                   334,
        "EMEDIA (Bibs)":             120,
        "Total expense":          44_755,
        "Net (all in)":           36_689,
        "Net (w/o Sponsorship)": -13_100,
    },
}

if __name__ == "__main__":
    ensure_finance_table()
    for race_name, values in FINANCE_DATA.items():
        # Sanity check: make sure we're not silently dropping a category.
        missing = set(FINANCE_CATEGORIES) - set(values)
        if missing:
            raise SystemExit(f"{race_name} is missing categories: {missing}")
        save_finance(race_name, values)
        print(f"seeded {race_name}: {len(values)} line items")
    print("Done.")
