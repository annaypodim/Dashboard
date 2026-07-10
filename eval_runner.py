"""
Eval runner for the NL query engine.
Runs each question in eval_dataset.json through the engine and checks results
against expected values. Prints a scorecard at the end.

Usage:
    python eval_runner.py                    # run all
    python eval_runner.py --ids 1 5 8        # run specific cases
    python eval_runner.py --category hard    # filter by difficulty
"""

import json
import re
import sys
import os
import time
import argparse
from dotenv import load_dotenv

# load .env for API key
if os.path.exists(".env"):
    load_dotenv()
elif os.path.exists("../.env"):
    load_dotenv(dotenv_path="../.env")

from nl_query_engine import analyze, ask


# Year labels: models may return "2022" or "race_2022" — both are valid
YEAR_ALIASES = {
    "race_2022": ["race_2022", "2022"],
    "race_2023": ["race_2023", "2023"],
    "race_2024": ["race_2024", "2024"],
    "race_2025": ["race_2025", "2025"],
}


def _normalize_year_key(key):
    """Map any year alias to its canonical form."""
    for canonical, aliases in YEAR_ALIASES.items():
        if key in aliases:
            return canonical
    return key


def _build_actual_map(df):
    """Build a key->value map from first two columns, normalizing year keys."""
    if df.shape[1] < 2:
        return {}
    return {
        _normalize_year_key(str(k)): v
        for k, v in zip(df.iloc[:, 0].astype(str), df.iloc[:, 1])
    }


def check_result(expected, result):
    """Check result against expected values. Returns (passed, details)."""
    if result["error"]:
        return False, f"ERROR: {result['error']}"

    df = result["data"]
    if df is None:
        return False, "No data returned"

    if df.empty:
        return False, "Empty result set"

    checks = []
    passed = True

    # check row count
    if "rows" in expected:
        ok = len(df) == expected["rows"]
        checks.append(f"rows: {len(df)} {'==' if ok else '!='} {expected['rows']}")
        if not ok:
            passed = False

    if "rows_gte" in expected:
        ok = len(df) >= expected["rows_gte"]
        checks.append(f"rows: {len(df)} {'>=' if ok else '<'} {expected['rows_gte']}")
        if not ok:
            passed = False

    # check single scalar value
    if "value" in expected:
        actual = df.iloc[0, -1] if df.shape[1] > 1 else df.iloc[0, 0]
        try:
            ok = int(actual) == expected["value"]
        except (ValueError, TypeError):
            ok = str(actual) == str(expected["value"])
        checks.append(f"value: {actual} {'==' if ok else '!='} {expected['value']}")
        if not ok:
            passed = False

    # check approximate value
    if "value_approx" in expected:
        actual = df.iloc[0, -1] if df.shape[1] > 1 else df.iloc[0, 0]
        tol = expected.get("tolerance", 1.0)
        try:
            ok = abs(float(actual) - expected["value_approx"]) <= tol
        except (ValueError, TypeError):
            ok = False
        checks.append(f"value_approx: {actual} ~= {expected['value_approx']} (tol={tol}) {'OK' if ok else 'FAIL'}")
        if not ok:
            passed = False

    # check first value in first row — accept year aliases
    if "first_value" in expected:
        actual = str(df.iloc[0, 0])
        expected_val = expected["first_value"]
        ok = actual == expected_val
        if not ok:
            ok = _normalize_year_key(actual) == _normalize_year_key(expected_val)
        checks.append(f"first_value: {actual} {'==' if ok else '!='} {expected_val}")
        if not ok:
            passed = False

    # check unordered key-value pairs (with year alias normalization)
    if "values_unordered" in expected:
        expected_map = expected["values_unordered"]
        actual_map = _build_actual_map(df)
        for k, v in expected_map.items():
            canonical = _normalize_year_key(k)
            actual_v = actual_map.get(canonical)
            try:
                ok = int(actual_v) == v
            except (ValueError, TypeError):
                ok = False
            checks.append(f"  {k}: {actual_v} {'==' if ok else '!='} {v}")
            if not ok:
                passed = False

    # check approximate unordered key-value pairs (with year alias normalization)
    if "values_approx_unordered" in expected:
        expected_map = expected["values_approx_unordered"]
        tol = expected.get("tolerance", 1.0)
        actual_map = _build_actual_map(df)
        for k, v in expected_map.items():
            canonical = _normalize_year_key(k)
            actual_v = actual_map.get(canonical)
            try:
                ok = abs(float(actual_v) - v) <= tol
            except (ValueError, TypeError):
                ok = False
            checks.append(f"  {k}: {actual_v} ~= {v} (tol={tol}) {'OK' if ok else 'FAIL'}")
            if not ok:
                passed = False

    # check ordered values list
    if "values" in expected:
        for i, v in enumerate(expected["values"]):
            if i < len(df):
                actual = df.iloc[i, -1] if df.shape[1] > 1 else df.iloc[i, 0]
                try:
                    ok = int(actual) == v
                except (ValueError, TypeError):
                    ok = False
                checks.append(f"  row[{i}]: {actual} {'==' if ok else '!='} {v}")
                if not ok:
                    passed = False

    # check row tuples: each expected tuple must appear as a row (unordered)
    # year aliases normalized on any string cell
    if "row_tuples" in expected:
        def _norm(v):
            s = str(v).strip()
            return _normalize_year_key(s)

        actual_rows = [tuple(_norm(v) for v in row) for row in df.itertuples(index=False, name=None)]
        for tup in expected["row_tuples"]:
            target = tuple(_norm(v) for v in tup)
            ok = False
            for row in actual_rows:
                if len(row) < len(target):
                    continue
                # match target against any contiguous alignment starting at 0
                match = True
                for i, want in enumerate(target):
                    got = row[i]
                    if want == got:
                        continue
                    try:
                        if float(got) == float(want):
                            continue
                    except (ValueError, TypeError):
                        pass
                    match = False
                    break
                if match:
                    ok = True
                    break
            checks.append(f"row_tuple {tup}: {'FOUND' if ok else 'MISSING'}")
            if not ok:
                passed = False

    # check contains
    if "contains" in expected:
        flat = df.to_string()
        for val in expected["contains"]:
            ok = val in flat
            checks.append(f"contains '{val}': {'YES' if ok else 'NO'}")
            if not ok:
                passed = False

    return passed, "; ".join(checks)


def check_narrative(expected, result):
    """Check the narrated summary against an `expected_narrative` block.

    Returns (passed, details). Checks any of:
    - verdict: the statistical gate's ruling must match exactly
    - forbidden_terms: words the prose must not contain (case-insensitive).
      This is how we assert the model didn't narrate a trend through noise.
    - required_terms: at least one must appear
    - caveat_contains: a substring that must appear in some caveat
    - guard_status: "clean" | "retried" | "fallback"
    """
    evidence = result.get("evidence")
    narrative = result.get("narrative")
    if evidence is None:
        return False, "no evidence bundle"

    checks = []
    passed = True

    if "verdict" in expected:
        ok = evidence.verdict == expected["verdict"]
        passed &= ok
        checks.append(f"verdict={evidence.verdict} (want {expected['verdict']}): {'ok' if ok else 'MISMATCH'}")

    if "caveat_contains" in expected:
        ok = any(expected["caveat_contains"] in c for c in evidence.caveats)
        passed &= ok
        checks.append(f"caveat contains '{expected['caveat_contains']}': {'ok' if ok else 'MISSING'}")

    if narrative is None:
        if any(k in expected for k in ("forbidden_terms", "required_terms", "guard_status")):
            return False, "; ".join(checks + ["no narrative (run with --narrate)"])
        return passed, "; ".join(checks)

    text = narrative["text"].lower()

    if "forbidden_terms" in expected:
        hits = [t for t in expected["forbidden_terms"] if t.lower() in text]
        passed &= not hits
        checks.append(f"forbidden terms: {'none' if not hits else 'FOUND ' + str(hits)}")

    if "required_terms" in expected:
        hits = [t for t in expected["required_terms"] if t.lower() in text]
        passed &= bool(hits)
        checks.append(f"required terms: {'ok ' + str(hits) if hits else 'NONE FOUND'}")

    if "guard_status" in expected:
        ok = narrative["guard_status"] == expected["guard_status"]
        passed &= ok
        checks.append(f"guard={narrative['guard_status']} (want {expected['guard_status']}): {'ok' if ok else 'MISMATCH'}")

    if narrative["violation"]:
        checks.append(f"guard caught: {narrative['violation']}")

    return passed, "; ".join(checks)


def run_eval(dataset_path="eval_dataset.json", ids=None, difficulty=None, provider="openai", narrate=False):
    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("ERROR: Set GEMINI_API_KEY in .env or environment")
            sys.exit(1)
        model = "gemini-2.5-flash"
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("ERROR: Set OPENAI_API_KEY in .env or environment")
            sys.exit(1)
        model = "gpt-4o-mini"

    print(f"Provider: {provider} | Model: {model}\n")

    with open(dataset_path) as f:
        cases = json.load(f)

    if ids:
        cases = [c for c in cases if c["id"] in ids]
    if difficulty:
        cases = [c for c in cases if c["difficulty"] == difficulty]

    results = []
    total = len(cases)
    passed_count = 0

    print(f"Running {total} eval cases...\n")
    print("=" * 70)

    for case in cases:
        qid = case["id"]
        question = case["question"]
        print(f"\n[Q{qid}] {question}")
        print(f"  difficulty: {case['difficulty']}  category: {case['category']}")

        if narrate:
            result = analyze(question, api_key, model=model, provider=provider)
        else:
            result = ask(question, api_key, model=model, provider=provider)

        # respect rate limits for free tier
        if provider == "gemini":
            time.sleep(13)

        if result["sql"]:
            print(f"  SQL: {result['sql'][:120]}...")

        passed, details = check_result(case["expected_result"], result)

        # also check SQL pattern if provided
        sql_ok = True
        if case.get("expected_sql_pattern") and result["sql"]:
            sql_ok = bool(re.search(case["expected_sql_pattern"], result["sql"], re.IGNORECASE | re.DOTALL))
            if not sql_ok:
                print(f"  SQL pattern '{case['expected_sql_pattern']}' NOT matched")

        # Narration checks only when the narrator actually ran -- without
        # --narrate there is no evidence bundle, and a case shouldn't fail for
        # a summary nobody asked to generate.
        narrative_ok = True
        if narrate and case.get("expected_narrative"):
            narrative_ok, narrative_details = check_narrative(case["expected_narrative"], result)
            details = f"{details} | narrative: {narrative_details}"
            if result.get("narrative"):
                print(f"  SUMMARY: {result['narrative']['text']}")

        overall = passed and sql_ok and narrative_ok
        status = "PASS" if overall else "FAIL"
        print(f"  {status}: {details}")

        if overall:
            passed_count += 1

        results.append({
            "id": qid,
            "question": question,
            "passed": overall,
            "sql": result.get("sql"),
            "details": details,
        })

    print("\n" + "=" * 70)
    print(f"\nSCORECARD: {passed_count}/{total} passed ({100*passed_count/total:.0f}%)")

    # breakdown by difficulty
    for diff in ["easy", "medium", "hard"]:
        subset = [c for c in cases if c["difficulty"] == diff]
        subset_passed = sum(1 for c, r in zip(cases, results) if c["difficulty"] == diff and r["passed"])
        if subset:
            print(f"  {diff}: {subset_passed}/{len(subset)}")

    # save results
    results_file = f"eval_results_{provider}.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to {results_file}")

    return passed_count, total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="+", type=int, help="Run specific case IDs")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    parser.add_argument("--provider", choices=["openai", "gemini"], default="openai")
    parser.add_argument(
        "--narrate",
        action="store_true",
        help="Also generate and check the prose summary (costs an extra LLM call per case)",
    )
    args = parser.parse_args()
    run_eval(ids=args.ids, difficulty=args.difficulty, provider=args.provider, narrate=args.narrate)
