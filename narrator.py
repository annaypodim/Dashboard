"""
Narrator for evidence bundles
=============================
Turns a query result into a short prose summary that a race organizer reads
*alongside the raw numbers*.

Design stance (deliberately looser than the first version): the human on the
other end always sees the table, so the narrator's job is to interpret and, when
reasonable, suggest why -- not merely restate a verdict. It is given the full
result table and a `run_sql` tool, so it can check a hunch or pull a figure it
wants to cite.

The one thing it may never do is invent a number. Every numeral in the prose
must appear in the data it was given or in something it retrieved with run_sql --
if it wants a ratio or a percentage change, it must query for it, not compute it
in its head. A mechanical guard enforces exactly that, retrying once and then
falling back to a deterministic sentence. The verdict is still respected for the
narrow claim of statistical significance: a `no_trend` result may not be narrated
as a rise or a decline, because that would be inventing significance rather than
a number.
"""

from __future__ import annotations

import json
import math
import re

import pandas as pd
from openai import OpenAI

from analysis import Evidence


NARRATOR_SYSTEM_PROMPT = """You are a data analyst summarizing a query result for a race organizer.

A human is reading your summary WITH the raw numbers in front of them. Your job is
to interpret: say what the data shows, point out what is notable, and -- when it is
reasonable -- suggest WHY, framed as a hypothesis the reader can weigh.

You have a run_sql tool. Use it freely to check a hunch, pull a breakdown, or get a
figure you want to cite.

HARD RULES (about honesty, not brevity):
1. Never state a number that is not in the data you were given OR that you retrieved
   with run_sql. If you want to cite a number you do not have -- a ratio, a
   percentage change, a per-person figure -- RUN A QUERY to get it first. Do not
   compute it in your head and write it down.
2. Separate what the data shows from what you are inferring. Causal explanations are
   welcome but must be marked as such: "this may be because...", "one likely
   explanation...", "consistent with...". Never assert cause as established fact.
3. If you are given a statistical verdict, respect it. "no_trend" means the
   year-to-year movement is within sampling noise -- do NOT call it a rise, a
   decline, a drop, or a recovery; it is statistically flat. You may still discuss
   the levels and suggest why they are steady.
4. Every caveat you are given (e.g. a partial season) must be reflected in your
   summary.

STYLE: one or two short paragraphs of plain prose. Lead with the answer. Be direct
about what the data suggests, as long as rule 2 holds. No headings, no bullet lists."""


RUN_SQL_TOOL = {
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": (
            "Run a single read-only SELECT against the race database and get the rows "
            "back as a table. Use this to fetch any number or breakdown you want to "
            "cite that is not already in the result you were given."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "One read-only SELECT statement. No other statement types.",
                }
            },
            "required": ["sql"],
        },
    },
}


# Years are labels, not magnitudes; small integers cover phrasings like "five
# years". The guard's real job is to block fabricated *magnitudes*, so these
# pass regardless of the data.
_YEAR_MIN, _YEAR_MAX = 2000, 2100
_SMALL_INT_MAX = 12

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_TOLERANCE = 1e-6


def _df_numbers(df: pd.DataFrame) -> set[float]:
    """Every numeric value in a DataFrame, plus 0/1/2-dp rounded forms.

    The rounded forms let the narrator write "about 47" for a stored 46.87 or
    "$24.99" for 24.99 without tripping the guard, while a value it merely
    computed in its head (and never queried) still has no match.
    """
    nums: set[float] = set()
    for col in df.columns:
        for value in df[col].tolist():
            try:
                f = float(value)
            except (TypeError, ValueError):
                continue
            if math.isnan(f) or math.isinf(f):
                continue
            nums.add(f)
            nums.add(float(round(f)))
            nums.add(round(f, 1))
            nums.add(round(f, 2))
    return nums


def _numeric_guard(text: str, allowed: set[float]) -> str | None:
    """Return the first number in `text` not backed by `allowed`, else None."""
    for token in _NUMBER_RE.findall(text):
        value = float(token.replace(",", ""))

        is_year = value.is_integer() and _YEAR_MIN <= value <= _YEAR_MAX
        is_small_int = value.is_integer() and value <= _SMALL_INT_MAX
        if is_year or is_small_int:
            continue

        if not any(abs(value - a) < _TOLERANCE for a in allowed):
            return token
    return None


def _deterministic_fallback(evidence: Evidence) -> str:
    """A plain sentence built straight from the bundle. No model involved."""
    parts = [evidence.verdict_detail]
    parts.extend(evidence.caveats)
    return " ".join(parts)


def _client(api_key: str, provider: str) -> OpenAI:
    """Same provider switch as nl_query_engine.generate_sql."""
    if provider == "gemini":
        return OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    return OpenAI(api_key=api_key)


def _user_message(evidence: Evidence, df: pd.DataFrame | None, schema: str) -> str:
    """The opening context: the question, the full result table, and the verdict."""
    table = "(no rows)" if df is None or df.empty else df.to_string(index=False)
    lines = [
        f"Question: {evidence.question}",
        "",
        "Result table (these numbers are solid -- cite freely):",
        table,
        "",
        f"Statistical verdict: {evidence.verdict} -- {evidence.verdict_detail}",
    ]
    if evidence.caveats:
        lines += ["", "Caveats you must reflect:"] + [f"- {c}" for c in evidence.caveats]
    if schema:
        lines += ["", "Database schema (for any run_sql follow-ups):", schema]
    return "\n".join(lines)


def _run_tool(tool_call, validate_sql, execute_query, allowed: set[float]) -> str:
    """Execute one run_sql call read-only; widen `allowed` with what it returns."""
    try:
        args = json.loads(tool_call.function.arguments)
    except (json.JSONDecodeError, TypeError):
        return "Invalid tool arguments."

    sql = args.get("sql", "")
    ok, err = validate_sql(sql)
    if not ok:
        return f"Query rejected (safety check): {err}"

    try:
        rdf = execute_query(sql)
    except Exception as exc:  # surface the DB error to the model so it can adjust
        return f"Query failed: {exc}"

    allowed.update(_df_numbers(rdf))
    if rdf.empty:
        return "(no rows)"
    return rdf.head(100).to_string(index=False)


def narrate(
    evidence: Evidence,
    api_key: str,
    model: str = "gpt-4o",
    provider: str = "openai",
    df: pd.DataFrame | None = None,
    max_steps: int = 4,
) -> dict:
    """Write an interpretive summary over a result, guarded against fabricated numbers.

    Returns:
        text: the summary shown to the user
        guard_status: "clean" | "retried" | "fallback"
        violation: the rejected number, if any
        steps: how many run_sql rounds the model took
    """
    if evidence.shape == "empty":
        return {"text": evidence.verdict_detail, "guard_status": "clean", "violation": None, "steps": 0}

    # Reuse the engine's SQL guardrails and schema for the loop. Imported here to
    # avoid a circular import at module load (nl_query_engine imports narrator).
    from nl_query_engine import validate_sql, execute_query, get_db_schema

    allowed = set(evidence.allowed_numbers())
    if df is not None:
        allowed |= _df_numbers(df)

    try:
        schema = get_db_schema()
    except Exception:
        schema = ""

    client = _client(api_key, provider)
    messages = [
        {"role": "system", "content": NARRATOR_SYSTEM_PROMPT},
        {"role": "user", "content": _user_message(evidence, df, schema)},
    ]

    steps = 0
    first_violation = None
    for _ in range(max_steps):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=messages,
                tools=[RUN_SQL_TOOL],
                max_tokens=700,
            )
        except Exception:
            return {"text": _deterministic_fallback(evidence), "guard_status": "fallback",
                    "violation": None, "steps": steps}

        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                out = _run_tool(tc, validate_sql, execute_query, allowed)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            steps += 1
            continue

        text = (msg.content or "").strip()
        violation = _numeric_guard(text, allowed)
        if violation is None:
            return {"text": text, "guard_status": "retried" if first_violation else "clean",
                    "violation": first_violation, "steps": steps}

        first_violation = first_violation or violation
        messages.extend([
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    f"The number {violation} is not in the data you were given or retrieved. "
                    f"Either run a SQL query to obtain it, or remove it. Rewrite using only "
                    f"numbers present in the data."
                ),
            },
        ])

    return {"text": _deterministic_fallback(evidence), "guard_status": "fallback",
            "violation": first_violation, "steps": steps}
