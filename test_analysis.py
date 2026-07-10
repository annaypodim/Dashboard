"""
Tests for the evidence builder and the numeric guard.

Plain asserts, no pytest -- same script-not-framework style as eval_runner.py.
Needs no database and no API key.

    python3 test_analysis.py

The two tests that matter are `test_real_gender_split_is_flat` and
`test_partial_season_excluded_from_verdict`. Those encode the two ways this
system could confidently mislead someone: narrating noise as a trend, and
narrating an unfinished season as a collapse.
"""

import sys

import pandas as pd

from analysis import Evidence, Point, build_evidence
from narrator import _deterministic_fallback, _numeric_guard


COMPLETE = frozenset()
PARTIAL_2026 = frozenset({"race_2026"})


def _gender_df(rows):
    return pd.DataFrame(rows, columns=["race_name", "Sex", "n"])


# Real counts, straight from the participants table.
REAL_GENDER = _gender_df([
    ("race_2022", "F", 426), ("race_2022", "M", 445), ("race_2022", "N", 1), ("race_2022", "U", 9),
    ("race_2023", "F", 468), ("race_2023", "M", 516), ("race_2023", "N", 4), ("race_2023", "U", 6),
    ("race_2024", "F", 527), ("race_2024", "M", 622), ("race_2024", "N", 3), ("race_2024", "U", 10),
    ("race_2025", "F", 546), ("race_2025", "M", 608), ("race_2025", "N", 1), ("race_2025", "U", 10),
    ("race_2026", "F", 131), ("race_2026", "M", 146), ("race_2026", "N", 1), ("race_2026", "U", 1),
])


def test_real_gender_split_is_flat():
    """48.4 -> 45.4 -> 47.0 is sampling noise, not a decline. This must not be a trend."""
    ev = build_evidence("sex breakdown across all years", "SELECT ...", REAL_GENDER, PARTIAL_2026)
    assert ev.shape == "proportion_series", ev.shape
    assert ev.verdict == "no_trend", f"got {ev.verdict}: {ev.verdict_detail}"


def test_real_gender_split_reports_shares():
    ev = build_evidence("sex breakdown", "SELECT ...", REAL_GENDER, PARTIAL_2026)
    f2022 = next(p for p in ev.points if p.group == "race_2022" and p.category == "F")
    assert f2022.total == 881, f2022.total
    assert abs(f2022.share_pct - 48.35) < 0.05, f2022.share_pct
    assert abs(f2022.se_pct - 1.68) < 0.05, f2022.se_pct


def test_thin_category_excluded_from_inference():
    """'N' has counts of 1 -- a Wald interval there is meaningless."""
    ev = build_evidence("sex breakdown", "SELECT ...", REAL_GENDER, PARTIAL_2026)
    assert "'N'" not in ev.verdict_detail, ev.verdict_detail


def test_fabricated_decline_is_a_trend():
    """A genuine 48% -> 35% collapse must be caught. The gate isn't just saying no."""
    df = _gender_df([
        ("race_2022", "F", 480), ("race_2022", "M", 520),
        ("race_2025", "F", 350), ("race_2025", "M", 650),
    ])
    ev = build_evidence("sex breakdown", "SELECT ...", df, COMPLETE)
    assert ev.verdict == "trend", f"got {ev.verdict}: {ev.verdict_detail}"


def test_partial_season_produces_caveat():
    df = pd.DataFrame(
        [("race_2022", 881), ("race_2025", 1165), ("race_2026", 279)],
        columns=["race_name", "n"],
    )
    ev = build_evidence("registrations each year", "SELECT ...", df, PARTIAL_2026)
    assert ev.shape == "count_series", ev.shape
    assert any("race_2026" in c for c in ev.caveats), ev.caveats


def test_partial_season_excluded_from_verdict():
    """2026's 279 is an open window, not a collapse. The verdict compares 2022 to 2025."""
    df = pd.DataFrame(
        [("race_2022", 881), ("race_2025", 1165), ("race_2026", 279)],
        columns=["race_name", "n"],
    )
    ev = build_evidence("registrations each year", "SELECT ...", df, PARTIAL_2026)
    assert ev.verdict == "trend", ev.verdict
    assert "rose" in ev.verdict_detail, ev.verdict_detail
    assert "2026" not in ev.verdict_detail, ev.verdict_detail


def test_single_complete_season_is_indeterminate():
    df = pd.DataFrame([("race_2025", 1165), ("race_2026", 279)], columns=["race_name", "n"])
    ev = build_evidence("registrations each year", "SELECT ...", df, PARTIAL_2026)
    assert ev.verdict == "indeterminate", ev.verdict


def test_flat_counts_are_no_trend():
    df = pd.DataFrame([("race_2024", 1162), ("race_2025", 1165)], columns=["race_name", "n"])
    ev = build_evidence("registrations each year", "SELECT ...", df, COMPLETE)
    assert ev.verdict == "no_trend", f"{ev.verdict}: {ev.verdict_detail}"


def test_city_ranking_is_not_a_series():
    """A breakdown has no time axis. The narrator must not describe movement."""
    df = pd.DataFrame([("Belmont", 573), ("Redwood City", 143)], columns=["City", "n"])
    ev = build_evidence("top cities", "SELECT ...", df, COMPLETE)
    assert ev.shape == "other", ev.shape
    assert ev.verdict == "not_applicable", ev.verdict


def test_single_metric():
    ev = build_evidence("how many in 2024", "SELECT ...", pd.DataFrame([[1162]], columns=["n"]), COMPLETE)
    assert ev.shape == "single_metric", ev.shape


def test_empty_result():
    ev = build_evidence("nothing", "SELECT ...", pd.DataFrame(), COMPLETE)
    assert ev.shape == "empty" and ev.verdict == "not_applicable"


# --- numeric guard ---------------------------------------------------------

GUARD_EVIDENCE = Evidence(
    question="q", sql="SELECT ...", shape="proportion_series",
    verdict="no_trend", verdict_detail="Stable.",
    points=(Point("race_2022", "F", 426, 881, 48.35, 1.68, False),
            Point("race_2025", "F", 546, 1165, 46.87, 1.46, False)),
    caveats=(),
)


def test_guard_rejects_fabricated_magnitude():
    assert _numeric_guard("Registrations fell 23% this year.", GUARD_EVIDENCE) == "23"


def test_guard_allows_rounded_share():
    """'about 47%' against a stored 46.87 must pass, or the narrator can't write prose."""
    assert _numeric_guard("The split has held at about 47% female.", GUARD_EVIDENCE) is None


def test_guard_allows_shares_as_the_bundle_rounds_them():
    """The bundle shows 48.4 and 46.9, so those are what the narrator may write."""
    assert _numeric_guard("48.4% in 2022 and 46.9% in 2025.", GUARD_EVIDENCE) is None


def test_guard_allows_margin_of_error():
    """The bundle exposes 2*se as margin_of_error_pct: 3.4 and 2.9."""
    assert _numeric_guard("The margin of error is 3.4 points.", GUARD_EVIDENCE) is None


def test_guard_allows_years_and_small_ints():
    assert _numeric_guard("Across 5 years, from 2022 to 2026, nothing moved.", GUARD_EVIDENCE) is None


def test_guard_allows_counts_with_separators():
    assert _numeric_guard("There were 1,165 registrants.", GUARD_EVIDENCE) is None


def test_guard_rejects_computed_difference():
    """1.48 is 48.35 - 46.87. Real numbers, arithmetic the model was told not to do."""
    assert _numeric_guard("Female share dropped 1.48 points.", GUARD_EVIDENCE) == "1.48"


def test_fallback_includes_detail_and_caveats():
    ev = Evidence("q", "SELECT ...", "count_series", "trend", "The count rose.", (), ("2026 is partial.",))
    text = _deterministic_fallback(ev)
    assert "The count rose." in text and "2026 is partial." in text


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = []
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except AssertionError as exc:
            failures.append((test.__name__, exc))
            print(f"  FAIL  {test.__name__}: {exc}")

    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
