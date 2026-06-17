"""
Natural Language Query Engine for Race Dashboard
=================================================
Translates natural language questions into SQL queries against the Postgres
race database, executes them safely, and returns structured results.

Architecture: "Text-to-SQL" pattern
- User asks a question in plain English
- An LLM translates it to a SQL SELECT query using schema context
- The query is validated (read-only) and executed
- Results are returned as a pandas DataFrame for visualization

Why this approach?
- The data is already in Postgres — no need to build a separate index
- SQL is deterministic and auditable — users can see exactly what query ran
- The LLM only needs to know the schema, not the data itself
- No vector DB, no embeddings, no RAG pipeline — minimal dependencies
"""

import re
import pandas as pd
from datetime import datetime
from openai import OpenAI
from class_init import connect_db, _validate_table_name


# ---------------------------------------------------------------------------
# Schema introspection — we dynamically read the DB schema so the LLM always
# has accurate context, even if tables are added/removed via the uploader.
# ---------------------------------------------------------------------------

def get_db_schema() -> str:
    """
    Reads the Postgres database and returns a human-readable schema description
    that we'll include in the LLM prompt. This is the 'context injection' step —
    giving the model the information it needs to write correct SQL.
    """
    conn = connect_db()
    try:
        # Get all user table names from information_schema (Postgres metadata).
        tables = pd.read_sql(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name",
            conn,
        )["table_name"].tolist()

        # Participant data now lives in the single 'participants' table. The old
        # per-race tables (named after each race in 'info') are kept only as a
        # backup, so exclude them from the schema the LLM sees -- otherwise it
        # might generate queries against stale tables.
        legacy_race_tables = set(
            pd.read_sql("SELECT * FROM info", conn)["Name"].tolist()
        )

        schema_parts = []

        for table in tables:
            if table in legacy_race_tables:
                continue  # superseded by the participants table

            # Validate table name before using it in queries.
            try:
                safe_table = _validate_table_name(table)
            except ValueError:
                continue  # Skip tables with unusual names

            # Get column info from information_schema. safe_table is already
            # validated (alphanumeric/underscore only), so inlining it is safe.
            cols = pd.read_sql(
                "SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_schema = 'public' AND table_name = '{safe_table}' "
                "ORDER BY ordinal_position",
                conn,
            )
            col_descriptions = [
                f"    {row.column_name} ({row.data_type})"
                for row in cols.itertuples(index=False)
            ]

            # Get row count for context.
            count = pd.read_sql(
                f'SELECT COUNT(*) AS n FROM "{safe_table}"', conn
            )["n"].iloc[0]

            # Get sample values for key columns to help the LLM understand data
            # format. Only the participants table has event/Date columns; querying
            # them on info/finance errors and (in Postgres) aborts the transaction.
            sample_info = ""
            if table == "participants":
                try:
                    events = pd.read_sql(
                        f'SELECT DISTINCT event FROM "{safe_table}" LIMIT 10', conn
                    )["event"].tolist()
                    sample_info = f"\n  Sample event values: {events}"
                except Exception:
                    pass
                try:
                    date_sample = pd.read_sql(
                        f'SELECT "Date" FROM "{safe_table}" LIMIT 1', conn
                    )
                    if not date_sample.empty:
                        sample_info += f"\n  Date format example: {date_sample['Date'].iloc[0]}"
                except Exception:
                    pass

            schema_parts.append(
                f"Table: {table} ({count} rows)\n"
                f"  Columns:\n" + "\n".join(col_descriptions) + sample_info
            )

        # Also get the info table contents — this is critical context because it maps
        # race names to date ranges, which the LLM needs to answer time-based questions.
        info_rows = pd.read_sql("SELECT * FROM info", conn)
        info_context = "\n\nRace metadata (from 'info' table):\n"
        for row in info_rows.itertuples(index=False):
            info_context += f"  {row[0]}: registration {row[1]} to {row[2]}\n"
    finally:
        conn.close()

    return "\n\n".join(schema_parts) + info_context


# ---------------------------------------------------------------------------
# The system prompt — this is the most important part of the text-to-SQL
# approach. It constrains the LLM to produce valid, safe SQL.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a SQL query generator for a race registration database.
You translate natural language questions into PostgreSQL SELECT queries.

POSTGRESQL SYNTAX (the database is PostgreSQL — these are mandatory):
1. ONLY generate SELECT statements. Never INSERT, UPDATE, DELETE, DROP, ALTER, or any DDL. Single statement only.
2. Identifiers are CASE-SENSITIVE. Every column whose name has uppercase letters, spaces, or slashes MUST be wrapped in double quotes: "Participant ID", "Date", "Sex", "City", "State", "ZIP/Postal Code", "Country", "Age". The 'race_name' and 'event' columns are lowercase and may be left unquoted.
3. The "Date" column is a real timestamp — compare it directly to date literals, e.g. "Date" < DATE '2024-10-09', or cast with "Date"::date. NEVER use SQLite functions like date() or substr() on it.
4. For case-insensitive text matching use ILIKE (never LIKE ... COLLATE NOCASE). String literals use single quotes; escape an apostrophe by doubling it ('Kid''s'). Never use double quotes for string values — double quotes mean an identifier.

SCHEMA CONVENTIONS:
5. ALL participant registrations live in ONE table called participants. Each row belongs to a race identified by the race_name column (values like 'race_2022', 'race_2023', 'race_2024', ...). Columns: race_name, "Participant ID", "Date", "Sex", "City", "State", "ZIP/Postal Code", "Country", event, "Age". To restrict to a single race, filter with WHERE race_name = 'race_2024'. There are no per-year tables — never write FROM race_2024; always FROM participants with a race_name filter.
6. The 'info' table maps race names to registration date ranges (columns: "Name", "Registration start date", "Registration end date"). info."Name" matches participants.race_name. When answering questions about registration dates / windows, ALWAYS include the "Name" column in the SELECT so the user can see which race the dates belong to.
7. "Sex" values are 'M' (male), 'F' (female), 'N' (non-binary), 'U' (unknown).
8. "registrants" = rows in the participants table. Each row = one registration. Filter by race_name to scope to a particular race/year.

SINGLE-YEAR vs CROSS-YEAR — IMPORTANT:
9. If the question names ONE specific year (e.g. "race_2024", "in 2023", "for race_2022", "in race_2025"), filter with WHERE race_name = 'race_YYYY' and do NOT add a race_name / year label column to the output — the output columns must be EXACTLY the requested metric(s). For example, "How many male vs female in race_2023?" → `SELECT "Sex", COUNT(*) FROM participants WHERE race_name = 'race_2023' AND "Sex" IN ('M','F') GROUP BY "Sex"`. And "Which event had the most registrations in race_2023?" → `SELECT event, COUNT(*) FROM participants WHERE race_name = 'race_2023' GROUP BY event ORDER BY COUNT(*) DESC LIMIT 1`. The year is already known — don't duplicate it.
10. If the question mentions multiple years, "each year", "across all years", "by year", "per year", "compare X and Y" across years, or "how did X change" — produce ONE ROW PER YEAR by adding race_name to GROUP BY (e.g. `SELECT race_name, COUNT(*) AS n FROM participants GROUP BY race_name ORDER BY race_name`). Do NOT use UNION ALL — grouping on race_name is the single-table equivalent. Never use SELECT * — list specific columns explicitly.
11. In cross-year output, the FIRST column MUST be race_name (the 'race_YYYY' label). The metric columns come AFTER. Never put the metric before the race_name column.
12. "from YEAR_A to YEAR_B" phrased as a change or comparison ("change from A to B", "compare between A and B", "how did X change from A to B") means ONLY the two endpoint years (exactly 2 rows). Restrict with WHERE race_name IN ('race_A', 'race_B') and GROUP BY race_name. Do NOT include years in between. For example, "between 2022 and 2024" in a comparison context means race_2022 and race_2024 only — never include race_2023.
13. Rule 10 applies to "each year" only — NOT to "each event", "each city", etc. "Each event" means GROUP BY event (within a race_name filter), not GROUP BY race_name. Add race_name to the grouping solely when the grouping dimension is year.

DEMOGRAPHIC / GROUPING QUERIES:
14. "male vs female" / "male and female" / "by sex" / "sex breakdown" — return ONE ROW PER SEX using GROUP BY "Sex". Restrict to "Sex" IN ('M','F') when the phrasing is a male-vs-female comparison; otherwise include all sexes present. Do NOT use CASE WHEN columns to produce a single row — always use GROUP BY rows.
15. "sex breakdown across all years" or "by sex for each year" — produce ONE ROW PER (year, sex) pair: `SELECT race_name, "Sex", COUNT(*) AS n FROM participants WHERE ... GROUP BY race_name, "Sex" ORDER BY race_name, "Sex"`.
16. "male 5K" means WHERE "Sex"='M' AND event='5K'. "female 10K" means "Sex"='F' AND event='10K'.
17. For unique participants use COUNT(DISTINCT "Participant ID"); otherwise COUNT(*). Alias calculated columns with readable snake_case names.

EVENT NAME MATCHING:
18. Exact event codes like '5K', '10K' use equality: event='5K' or event='10K'.
19. Descriptive event phrases refer to ALL event rows whose name contains a matching stem — use ILIKE with wildcards (case-insensitive), and pick the SHORTEST DISTINCTIVE STEM so variant spellings/apostrophes/suffixes all match.
      - "Fido Mile" or "Fido" → event ILIKE '%Fido%' (captures '1 Mile - Fido Mile', 'FIDO MILE Family member***', 'Additional Fido Escorts')
      - "Kids Fun Run" or "Kid's Fun Run" → event = '1 Mile - Kid''s Fun Run' (exact match, NOT ILIKE). Do NOT include 'Parent Escort - 1 Mile Kids'' Fun Run' — that's a different event for parents escorting kids, not the Kids Fun Run itself.
      - "Virtual Run" → event ILIKE '%Virtual%'
    Check the schema's sample event values to confirm which variants exist before writing the ILIKE pattern.

CROSS-YEAR COVERAGE:
20. All years have complete data in the participants table — include every year (including the latest) in cross-year queries the same as any other.

DATE ARITHMETIC:
21. "N days before the race" means CUMULATIVE registrations whose "Date" is on or before (that race's Registration end date minus N days) — INCLUSIVE. It is a running total, not a single-day window. For race_2024 (end 2024-10-12), "3 days before the race" → `WHERE race_name = 'race_2024' AND "Date"::date <= DATE '2024-10-12' - INTERVAL '3 days'`. Use '<=', not '<' and not BETWEEN.
22. When "days before the race" is asked across all years, apply rule 21 per year using each year's own Registration end date (from the info table / the values listed in "Race metadata" below), grouping on race_name per rule 10/11.

RESPONSE FORMAT:
Return ONLY the SQL query. No explanation, no markdown, no code fences. Just the raw SQL.

DATABASE SCHEMA:
{schema}
"""


def generate_sql(question: str, api_key: str, model: str = "gpt-4o-mini", provider: str = "openai") -> str:
    """
    Uses an LLM to translate a natural language question into a SQL query.

    Why gpt-4o-mini as default?
    - It's cheap (~$0.15/1M input tokens) and fast
    - SQL generation is a well-understood task that smaller models handle well
    - For a dashboard tool, low latency matters more than max capability

    The user can override to gpt-4o for harder questions if needed.
    """
    schema = get_db_schema()

    if provider == "gemini":
        client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    else:
        client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        temperature=0,  # Deterministic — we want consistent SQL, not creative writing
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(schema=schema)},
            {"role": "user", "content": question}
        ],
        max_tokens=1000,
    )

    sql = response.choices[0].message.content.strip()
    # Strip markdown code fences if the model includes them despite instructions
    sql = re.sub(r'^```(?:sql)?\s*', '', sql)
    sql = re.sub(r'\s*```$', '', sql)
    return sql


# ---------------------------------------------------------------------------
# SQL validation — defense in depth. Even though the prompt says "SELECT only",
# we verify before executing. Never trust LLM output without validation.
# ---------------------------------------------------------------------------

# These are SQL keywords that could modify the database. We reject any query
# containing them. This is a blocklist approach — not perfect, but combined
# with the read-only connection mode, it provides strong protection.
DANGEROUS_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "REPLACE", "TRUNCATE", "GRANT", "REVOKE", "ATTACH",
    "DETACH", "PRAGMA", "VACUUM", "REINDEX",
]


def validate_sql(sql: str) -> tuple[bool, str]:
    """
    Validates that a SQL query is safe to execute.
    Returns (is_valid, error_message).

    Defense-in-depth: even though the LLM is prompted to only generate SELECT,
    we verify independently. This is a core security principle — never trust
    a single layer of protection.
    """
    sql_upper = sql.upper().strip()

    # Must start with SELECT or WITH (for CTEs)
    if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
        return False, "Query must be a SELECT statement."

    # Check for dangerous keywords
    # We tokenize by splitting on non-alphanumeric chars to avoid false positives
    # (e.g., a city named "Grants Pass" shouldn't trigger on "GRANT")
    tokens = set(re.findall(r'\b[A-Z]+\b', sql_upper))
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in tokens:
            return False, f"Query contains forbidden keyword: {keyword}"

    # Reject multiple statements (SQL injection via semicolon)
    # Count semicolons outside of string literals (simple heuristic)
    # Remove string literals first
    cleaned = re.sub(r"'[^']*'", "", sql)
    if ";" in cleaned.rstrip(";"):  # Allow trailing semicolon
        return False, "Multiple statements are not allowed."

    return True, ""


def execute_query(sql: str) -> pd.DataFrame:
    """
    Executes a validated SQL query and returns results as a DataFrame.

    We open a fresh connection for each query. In SQLite, connections are
    lightweight (no network round-trip), so this is fine and avoids stale
    connection issues in the Streamlit execution model.
    """
    conn = connect_db()
    try:
        df = pd.read_sql_query(sql, conn)
        return df
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Post-processing normalization layer.
# Keeps SQL generation simple and lets us normalize user-facing text values
# (e.g. "belmont ", "BELMONT", "Belmont" → "Belmont") without relying on the
# LLM to write LOWER(TRIM(...)) correctly. Running after SQL execution also
# means we can collapse case/whitespace duplicates in the result.
# ---------------------------------------------------------------------------

# Columns whose string values should be normalized for display, keyed by the
# lowercased column name. The callable produces the canonical display form.
NORMALIZERS = {
    "city": lambda s: str(s).strip().title() if pd.notna(s) else s,
}


def _norm_col_name(col: str) -> str | None:
    """Return a normalizer key if this column should be normalized, else None."""
    return col.lower() if col.lower() in NORMALIZERS else None


def _strip_limit(sql: str) -> tuple[str, int | None]:
    """Remove a trailing LIMIT N from SQL so we can re-apply it after
    normalization. Only strips a final top-level LIMIT, not ones inside
    subqueries."""
    match = re.search(r'\bLIMIT\s+(\d+)\s*;?\s*$', sql, re.IGNORECASE)
    if not match:
        return sql, None
    return sql[:match.start()].rstrip().rstrip(';'), int(match.group(1))


def normalize_result(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize known text columns (e.g. City) and collapse resulting
    duplicates by summing integer columns. Re-sorts by the first numeric
    column descending so top-N ordering is preserved."""
    if df is None or df.empty:
        return df

    norm_cols = [c for c in df.columns if _norm_col_name(c) is not None]
    if not norm_cols:
        return df

    df = df.copy()
    for c in norm_cols:
        df[c] = df[c].map(NORMALIZERS[_norm_col_name(c)])

    other_cols = [c for c in df.columns if c not in norm_cols]
    int_cols = [c for c in other_cols if pd.api.types.is_integer_dtype(df[c])]

    # Only re-aggregate when every non-normalized column is an integer count.
    # Mixed-type rows (e.g. averages, percentages) are left as-is to avoid
    # silently summing things that should be averaged.
    if other_cols and len(int_cols) == len(other_cols):
        df = df.groupby(norm_cols, as_index=False, sort=False)[int_cols].sum()
        df = df.sort_values(int_cols[0], ascending=False).reset_index(drop=True)

    return df


def ask(question: str, api_key: str, model: str = "gpt-4o-mini", provider: str = "openai") -> dict:
    """
    End-to-end: question in, structured result out.

    Returns a dict with:
    - question: the original question
    - sql: the generated SQL
    - data: the result DataFrame (or None if error)
    - error: error message (or None if success)
    - chart_hint: suggestion for what visualization to use
    """
    try:
        sql = generate_sql(question, api_key, model, provider)
    except Exception as e:
        return {
            "question": question,
            "sql": None,
            "data": None,
            "error": f"Failed to generate SQL: {str(e)}",
            "chart_hint": None,
        }

    is_valid, error_msg = validate_sql(sql)
    if not is_valid:
        return {
            "question": question,
            "sql": sql,
            "data": None,
            "error": f"Query rejected (safety check): {error_msg}",
            "chart_hint": None,
        }

    # If the SQL touches a column we normalize (e.g. City) and ends in LIMIT,
    # strip the LIMIT so we can aggregate case/whitespace variants that would
    # otherwise be cut off, then re-apply the LIMIT after normalization.
    needs_norm = any(col in sql.lower() for col in NORMALIZERS.keys())
    exec_sql, original_limit = (_strip_limit(sql) if needs_norm else (sql, None))

    try:
        df = execute_query(exec_sql)
    except Exception as e:
        return {
            "question": question,
            "sql": sql,
            "data": None,
            "error": f"Query execution failed: {str(e)}",
            "chart_hint": None,
        }

    df = normalize_result(df)
    if original_limit is not None:
        df = df.head(original_limit).reset_index(drop=True)

    # Determine chart type based on result shape
    chart_hint = infer_chart_type(df)

    return {
        "question": question,
        "sql": sql,
        "data": df,
        "error": None,
        "chart_hint": chart_hint,
    }


def infer_chart_type(df: pd.DataFrame) -> str:
    """
    Heuristic to suggest the best chart type based on the result DataFrame shape.

    This is a simple rule-based approach. The idea:
    - 1 row, 1 column → single number (metric card)
    - 1 column of numbers → bar chart
    - 2 columns (label + number) → bar or pie chart
    - Multiple numeric columns → line or grouped bar chart
    - Has a date/time column → line chart
    """
    if df.empty:
        return "empty"

    nrows, ncols = df.shape

    if nrows == 1 and ncols == 1:
        return "metric"

    # Check for date-like columns
    date_cols = [c for c in df.columns if any(d in c.lower() for d in ["date", "day", "month", "year", "time"])]

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    string_cols = df.select_dtypes(include=["object"]).columns.tolist()

    if date_cols and numeric_cols:
        return "line"

    if len(string_cols) == 1 and len(numeric_cols) == 1:
        if nrows <= 10:
            return "bar"
        return "bar"

    if len(string_cols) == 1 and len(numeric_cols) >= 2:
        return "grouped_bar"

    if len(numeric_cols) >= 2 and nrows > 1:
        return "line"

    if ncols == 1 and nrows > 1:
        return "bar"

    return "table"
