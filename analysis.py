"""
Evidence builder for narrated analysis
======================================
Turns a query result DataFrame into an `Evidence` bundle: the numbers, their
error bars, a verdict on whether anything actually changed, and any caveats
about the data itself.

Why this exists
---------------
An LLM handed five numbers will narrate a trend through them whether or not one
is there. Female share of registrants runs 48.4, 47.1, 45.4, 46.9, 47.0 across
2022-2026 -- every number real, and the "decline into 2024" a model will write
about is pure sampling noise. So the decision about whether an effect is real is
made *here*, in ordinary Python, before any model sees anything. The narrator
only writes prose over a verdict it did not choose.

Nothing in this module calls an LLM.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd


# A |z| of 2 is roughly the 95% two-sided threshold under a normal
# approximation. We only ever compare the first and last complete season, so
# this stays a single comparison per category rather than a fishing expedition.
Z_THRESHOLD = 2.0

# The Wald interval falls apart for small counts. Categories thinner than this
# are carried in the evidence for display but excluded from the verdict.
MIN_COUNT_FOR_INFERENCE = 10

# Matches '2022' or 'race_2022' -- the two forms year labels take in this repo.
YEAR_RE = re.compile(r"^(?:race_)?(\d{4})$")


# ---------------------------------------------------------------------------
# Statistics. Hand-rolled on purpose: these are three short formulas, and a
# reader can check them against a textbook faster than they can check that we
# passed the right arguments to scipy.
# ---------------------------------------------------------------------------

def _wald_se(count: int, total: int) -> float:
    """Standard error of a proportion, as a percentage. sqrt(p(1-p)/n) * 100."""
    if not total:
        return 0.0
    p = count / total
    return math.sqrt(p * (1 - p) / total) * 100


def _two_proportion_z(c1: int, n1: int, c2: int, n2: int) -> float:
    """z statistic for the difference between two independent proportions.

    Uses the pooled standard error, which is the standard choice when the null
    hypothesis is that both proportions are equal.
    """
    if not n1 or not n2:
        return 0.0
    p1, p2 = c1 / n1, c2 / n2
    pooled = (c1 + c2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0
    return (p2 - p1) / se


def _poisson_z(c1: int, c2: int) -> float:
    """z statistic for the difference between two counts, treating each as Poisson.

    Var(count) = count for a Poisson variable, so the variance of the difference
    is c1 + c2. Crude, but the right order of magnitude for registration counts
    and it keeps us from calling a 20-person swing a trend.
    """
    denom = math.sqrt(c1 + c2)
    if denom == 0:
        return 0.0
    return (c2 - c1) / denom


# ---------------------------------------------------------------------------
# Evidence bundle -- the only thing the narrator is ever allowed to see.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Point:
    """One observation: a count, optionally as a share of its group's total."""
    group: str                    # 'race_2022'
    category: str | None          # 'F', or None for a plain count series
    count: int
    total: int | None             # denominator, when a share is meaningful
    share_pct: float | None
    se_pct: float | None
    partial: bool                 # group's registration window hasn't closed


@dataclass(frozen=True)
class Evidence:
    question: str
    sql: str | None
    shape: str                    # proportion_series | count_series | single_metric | other | empty
    verdict: str                  # trend | no_trend | indeterminate | not_applicable
    verdict_detail: str           # human-readable reason, safe to show a user
    points: tuple[Point, ...]
    caveats: tuple[str, ...]

    def to_json(self) -> str:
        """Serialize for the narrator prompt. This is the model's entire world."""
        return json.dumps(
            {
                "question": self.question,
                "shape": self.shape,
                "verdict": self.verdict,
                "verdict_detail": self.verdict_detail,
                "caveats": list(self.caveats),
                "points": [
                    {
                        "group": p.group,
                        "category": p.category,
                        "count": p.count,
                        "total": p.total,
                        "share_pct": None if p.share_pct is None else round(p.share_pct, 1),
                        "margin_of_error_pct": None if p.se_pct is None else round(2 * p.se_pct, 1),
                        "partial_season": p.partial,
                    }
                    for p in self.points
                ],
            },
            indent=2,
        )

    def allowed_numbers(self) -> set[float]:
        """Every number the narrator is permitted to write, plus rounded forms.

        Derived from exactly the values `to_json` exposes -- the model can only
        be held to what it was actually shown. Feeding full-precision internals
        in here would widen the set enough to admit computed differences: a raw
        standard error of 1.46 sits close enough to 48.4 - 46.9 = 1.5 that the
        guard would wave the arithmetic through.

        Rounded variants are included so "about 47%" passes against a stored 46.9.
        """
        raw: set[float] = set()
        for p in self.points:
            raw.add(float(p.count))
            if p.total is not None:
                raw.add(float(p.total))
            if p.share_pct is not None:
                raw.add(round(p.share_pct, 1))
            if p.se_pct is not None:
                raw.add(round(2 * p.se_pct, 1))

        allowed: set[float] = set()
        for value in raw:
            allowed.add(value)
            allowed.add(float(round(value)))
            allowed.add(round(value, 1))
        return allowed


# ---------------------------------------------------------------------------
# Shape detection
# ---------------------------------------------------------------------------

def _normalize_group(value) -> str:
    """Map '2022' or 'race_2022' to the canonical 'race_2022'."""
    match = YEAR_RE.match(str(value).strip())
    return f"race_{match.group(1)}" if match else str(value)


def _year_column(df: pd.DataFrame) -> str | None:
    """Return the column holding year labels, or None.

    Rule 11 of the SQL system prompt guarantees race_name is the first column of
    any cross-year result, so we look for it by name first, then fall back to
    sniffing an object column whose every value looks like a year.
    """
    if "race_name" in df.columns:
        return "race_name"
    for col in df.select_dtypes(include=["object"]).columns:
        if df[col].map(lambda v: bool(YEAR_RE.match(str(v).strip()))).all():
            return col
    return None


def _lookup_partial_seasons(groups: set[str]) -> frozenset[str]:
    """Which of these races still have their registration window open?

    A race whose registration closes in the future has an artificially low count
    and must not be compared against completed seasons. Reads the `info` table.
    Returns an empty set if the database is unreachable -- a missing caveat is
    better than a crashed page, and the verdict logic degrades safely.
    """
    if not groups:
        return frozenset()
    try:
        from class_init import connect_db

        conn = connect_db()
        try:
            info = pd.read_sql('SELECT "Name", "Registration end date" FROM info', conn)
        finally:
            conn.close()
    except Exception:
        return frozenset()

    today = date.today()
    partial = set()
    for row in info.itertuples(index=False):
        name = _normalize_group(row[0])
        if name not in groups:
            continue
        try:
            end = datetime.strptime(str(row[1]).strip(), "%Y-%m-%d").date()
        except ValueError:
            continue
        if end > today:
            partial.add(name)
    return frozenset(partial)


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

def _verdict_for_proportions(
    points: tuple[Point, ...], usable: list[str]
) -> tuple[str, str]:
    """Compare each category's share in the first vs last complete season."""
    if len(usable) < 2:
        return "indeterminate", "Fewer than two complete seasons to compare."

    first, last = usable[0], usable[-1]
    by_key = {(p.group, p.category): p for p in points}
    categories = sorted({p.category for p in points if p.category is not None})

    best_z, best_cat = 0.0, None
    tested = 0
    for cat in categories:
        a, b = by_key.get((first, cat)), by_key.get((last, cat))
        if a is None or b is None:
            continue
        if min(a.count, b.count) < MIN_COUNT_FOR_INFERENCE:
            continue  # Wald interval is unreliable this thin
        tested += 1
        z = _two_proportion_z(a.count, a.total, b.count, b.total)
        if abs(z) > abs(best_z):
            best_z, best_cat = z, cat

    if tested == 0:
        return "indeterminate", "Every category is too small to draw a conclusion from."

    span = f"{first.replace('race_', '')} to {last.replace('race_', '')}"
    if abs(best_z) >= Z_THRESHOLD:
        return "trend", (
            f"The '{best_cat}' share changed by more than sampling noise "
            f"between {span}."
        )
    return "no_trend", (
        f"No category's share changed by more than sampling noise between {span}. "
        f"The largest movement ('{best_cat}') is within the margin of error."
    )


def _verdict_for_counts(points: tuple[Point, ...], usable: list[str]) -> tuple[str, str]:
    """Compare the count in the first vs last complete season."""
    if len(usable) < 2:
        return "indeterminate", "Fewer than two complete seasons to compare."

    by_group = {p.group: p for p in points}
    first, last = by_group[usable[0]], by_group[usable[-1]]
    span = f"{usable[0].replace('race_', '')} to {usable[-1].replace('race_', '')}"

    z = _poisson_z(first.count, last.count)
    if abs(z) >= Z_THRESHOLD:
        direction = "rose" if last.count > first.count else "fell"
        return "trend", f"The count {direction} by more than sampling noise between {span}."
    return "no_trend", (
        f"The count did not change by more than sampling noise between {span}."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_evidence(
    question: str,
    sql: str | None,
    df: pd.DataFrame | None,
    partial_seasons: frozenset[str] | None = None,
) -> Evidence:
    """Classify a result, attach uncertainty where it's well-defined, and rule.

    `partial_seasons` is injectable so this is testable without a database; when
    omitted it is read from the `info` table.
    """
    if df is None or df.empty:
        return Evidence(question, sql, "empty", "not_applicable", "No rows returned.", (), ())

    ycol = _year_column(df)
    numeric = df.select_dtypes(include=["number"]).columns.tolist()
    strings = [c for c in df.select_dtypes(include=["object"]).columns if c != ycol]

    groups = {_normalize_group(v) for v in df[ycol]} if ycol else set()
    if partial_seasons is None:
        partial_seasons = _lookup_partial_seasons(groups)

    caveats: list[str] = []
    for group in sorted(partial_seasons & groups):
        caveats.append(
            f"{group} is a partial season -- its registration window has not closed, "
            f"so its numbers are not comparable to completed years and are excluded "
            f"from the conclusion."
        )

    # --- proportion series: year x category x count -------------------------
    if (
        ycol
        and len(strings) == 1
        and len(numeric) == 1
        and df[ycol].nunique() >= 2
        and df[strings[0]].nunique() >= 2
    ):
        catcol, cntcol = strings[0], numeric[0]
        totals = df.groupby(ycol)[cntcol].sum()
        points = tuple(
            Point(
                group=_normalize_group(row[ycol]),
                category=str(row[catcol]),
                count=int(row[cntcol]),
                total=int(totals[row[ycol]]),
                share_pct=100 * int(row[cntcol]) / int(totals[row[ycol]]),
                se_pct=_wald_se(int(row[cntcol]), int(totals[row[ycol]])),
                partial=_normalize_group(row[ycol]) in partial_seasons,
            )
            for _, row in df.iterrows()
        )
        usable = sorted({p.group for p in points if not p.partial})
        verdict, detail = _verdict_for_proportions(points, usable)
        return Evidence(question, sql, "proportion_series", verdict, detail, points, tuple(caveats))

    # --- count series: year x count -----------------------------------------
    if ycol and not strings and len(numeric) == 1 and df[ycol].nunique() >= 2:
        cntcol = numeric[0]
        points = tuple(
            Point(
                group=_normalize_group(row[ycol]),
                category=None,
                count=int(row[cntcol]),
                total=None,
                share_pct=None,
                se_pct=None,
                partial=_normalize_group(row[ycol]) in partial_seasons,
            )
            for _, row in df.iterrows()
        )
        usable = sorted({p.group for p in points if not p.partial})
        verdict, detail = _verdict_for_counts(points, usable)
        return Evidence(question, sql, "count_series", verdict, detail, points, tuple(caveats))

    if df.shape == (1, 1):
        return Evidence(
            question, sql, "single_metric", "not_applicable",
            "A single value -- there is nothing to compare it against.",
            (), tuple(caveats),
        )

    return Evidence(
        question, sql, "other", "not_applicable",
        "This result is a breakdown, not a series over time. Describe it; do not "
        "claim anything increased or decreased.",
        (), tuple(caveats),
    )
