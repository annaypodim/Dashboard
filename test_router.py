"""
Tests for the intent router.

Plain asserts, no pytest, no API key -- the deterministic marker path and the
no-key fallback are exercised offline. The LLM tie-breaker is not tested here
(it needs a key); the point of the marker path is that the questions that matter
most -- the causal ones we must not answer silently -- never depend on it.

    python3 test_router.py
"""

import sys

from router import classify, _deterministic_causal, _causal_caveat


# Questions that MUST be flagged causal by the deterministic markers alone, so
# they never depend on an LLM call being available or correct.
CAUSAL = [
    "Did the price increase hurt signups?",
    "What was the impact of the price increase on registrations?",
    "What effect did the new route have on 10K numbers?",
    "Why did registrations drop in 2024?",
    "Did the fee change affect female participation?",
    "What drove the growth in registrations?",
    "Is the price responsible for fewer signups?",
    "Explain the decline in the Kids Fun Run.",
]

# Descriptive questions that must NOT trip the causal markers. Note the trap:
# "how did X change over time" is about change, not cause, and must stay
# descriptive.
DESCRIPTIVE = [
    "How many people registered in 2024?",
    "Show the sex breakdown for each year.",
    "How did the gender split change over the years?",
    "What are the top 5 cities?",
    "Compare total registrations between 2022 and 2024.",
    "What is the average age of 5K runners?",
    "List registrations by event type.",
]


def test_causal_markers_fire_without_llm():
    for q in CAUSAL:
        r = classify(q, api_key=None)
        assert r["intent"] == "causal", f"{q!r} -> {r}"
        assert r["method"] == "marker", f"{q!r} used {r['method']}"
        assert r["caveat"], f"{q!r} produced no caveat"


def test_descriptive_do_not_trip_markers():
    for q in DESCRIPTIVE:
        assert _deterministic_causal(q) is None, f"{q!r} matched {_deterministic_causal(q)!r}"


def test_descriptive_default_without_key():
    """No marker and no API key -> descriptive, via the fallback path, no banner."""
    for q in DESCRIPTIVE:
        r = classify(q, api_key=None)
        assert r["intent"] == "descriptive", f"{q!r} -> {r}"
        assert r["method"] == "fallback", f"{q!r} used {r['method']}"
        assert r["caveat"] is None


def test_change_over_time_is_descriptive():
    """The single most important false-positive to avoid."""
    r = classify("How did the gender split change over the years?", api_key=None)
    assert r["intent"] == "descriptive", r


def test_price_causal_mentions_missing_price_data():
    r = classify("What was the impact of the price increase on signups?", api_key=None)
    assert "no price information" in r["caveat"], r["caveat"]


def test_non_price_causal_omits_price_note():
    caveat = _causal_caveat("Why did registrations drop in 2024?")
    assert "price" not in caveat.lower(), caveat


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
