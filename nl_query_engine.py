"""
Natural Language Query Engine for Race Dashboard
=================================================
Translates natural language questions into SQL queries against the races.db
SQLite database, executes them safely, and returns structured results.

Architecture: "Text-to-SQL" pattern
- User asks a question in plain English
- An LLM translates it to a SQL SELECT query using schema context
- The query is validated (read-only) and executed
- Results are returned as a pandas DataFrame for visualization

Why this approach?
- The data is already in SQLite — no need to build a separate index
- SQL is deterministic and auditable — users can see exactly what query ran
- The LLM only needs to know the schema, not the data itself
- No vector DB, no embeddings, no RAG pipeline — minimal dependencies
"""

import sqlite3
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
    Reads the SQLite database and returns a human-readable schema description
    that we'll include in the LLM prompt. This is the 'context injection' step —
    giving the model the information it needs to write correct SQL.
    """
    conn = connect_db()
    cursor = conn.cursor()

    # Get all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]

    schema_parts = []

    for table in tables:
        # Validate table name before using in queries
        try:
            safe_table = _validate_table_name(table)
        except ValueError:
            continue  # Skip tables with unusual names

        # Get column info using PRAGMA — SQLite's metadata command
        cursor.execute(f"PRAGMA table_info([{safe_table}])")
        columns = cursor.fetchall()
        col_descriptions = []
        for col in columns:
            # PRAGMA table_info returns: (cid, name, type, notnull, default, pk)
            col_descriptions.append(f"    {col[1]} ({col[2] or 'TEXT'})")

        # Get row count for context
        cursor.execute(f"SELECT COUNT(*) FROM [{safe_table}]")
        count = cursor.fetchone()[0]

        # Get sample values for key columns to help the LLM understand data format
        sample_info = ""
        if table != "info":
            try:
                cursor.execute(f"SELECT DISTINCT event FROM [{safe_table}] LIMIT 10")
                events = [row[0] for row in cursor.fetchall()]
                sample_info = f"\n  Sample event values: {events}"
            except Exception:
                pass
            try:
                cursor.execute(f"SELECT Date FROM [{safe_table}] LIMIT 1")
                date_sample = cursor.fetchone()
                if date_sample:
                    sample_info += f"\n  Date format example: {date_sample[0]}"
            except Exception:
                pass

        schema_parts.append(
            f"Table: {table} ({count} rows)\n"
            f"  Columns:\n" + "\n".join(col_descriptions) + sample_info
        )

    # Also get the info table contents — this is critical context because it maps
    # race names to date ranges, which the LLM needs to answer time-based questions
    cursor.execute("SELECT * FROM info")
    info_rows = cursor.fetchall()
    info_context = "\n\nRace metadata (from 'info' table):\n"
    for row in info_rows:
        info_context += f"  {row[0]}: registration {row[1]} to {row[2]}\n"

    conn.close()

    return "\n\n".join(schema_parts) + info_context


# ---------------------------------------------------------------------------
# The system prompt — this is the most important part of the text-to-SQL
# approach. It constrains the LLM to produce valid, safe SQL.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a SQL query generator for a race registration database.
You translate natural language questions into SQLite SELECT queries.

RULES:
1. ONLY generate SELECT statements. Never INSERT, UPDATE, DELETE, DROP, ALTER, or any DDL.
2. Always return valid SQLite syntax.
3. When comparing dates, the Date column is stored as 'YYYY-MM-DD HH:MM:SS' text format. Use date() or substr() for comparisons.
4. Each race table (race_2022, race_2023, etc.) has the same schema with columns: index, Participant ID, Date, Sex, City, State, ZIP/Postal Code, Country, event, Age.
5. The 'info' table maps race names to registration date ranges.
6. When users ask about "days before the race", calculate from the Registration end date in the info table. For example, "3 days before the race" for race_2024 (end date 2024-10-12) means date('2024-10-12', '-3 days').
7. When users ask "across all years" or "for each year", write a UNION ALL query combining all race tables, adding a 'race_year' column. IMPORTANT: Never use SELECT * in UNION ALL queries — always list specific columns explicitly (e.g. "Participant ID", Date, Sex, City, State, "ZIP/Postal Code", Country, event, Age) because tables may have different numbers of columns.
8. For counts, use COUNT(*). For unique participants, use COUNT(DISTINCT "Participant ID").
9. Always alias calculated columns with readable names.
10. If the question is ambiguous, make a reasonable assumption and proceed.
11. The 'event' column contains sub-event names like '5K', '10K', '1 Mile - Fido Mile', etc.
12. "registrants" means rows in a race table. Each row = one registration.

RESPONSE FORMAT:
Return ONLY the SQL query. No explanation, no markdown, no code fences. Just the raw SQL.

DATABASE SCHEMA:
{schema}
"""


def generate_sql(question: str, api_key: str, model: str = "gpt-4o-mini") -> str:
    """
    Uses an LLM to translate a natural language question into a SQL query.

    Why gpt-4o-mini as default?
    - It's cheap (~$0.15/1M input tokens) and fast
    - SQL generation is a well-understood task that smaller models handle well
    - For a dashboard tool, low latency matters more than max capability

    The user can override to gpt-4o for harder questions if needed.
    """
    schema = get_db_schema()
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


def ask(question: str, api_key: str, model: str = "gpt-4o-mini") -> dict:
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
        sql = generate_sql(question, api_key, model)
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

    try:
        df = execute_query(sql)
    except Exception as e:
        return {
            "question": question,
            "sql": sql,
            "data": None,
            "error": f"Query execution failed: {str(e)}",
            "chart_hint": None,
        }

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
