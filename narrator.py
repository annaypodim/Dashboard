"""
Narrator for evidence bundles
=============================
Turns an `Evidence` bundle into a short prose summary.

The model sees the bundle and nothing else -- no database, no SQL, no tools. It
cannot decide whether a change is real, because `analysis.build_evidence` already
decided and put the answer in `verdict`. The model's only job is to say that
verdict in English.

Everything it writes then passes a mechanical check: every number in the prose
must appear in the bundle. If it doesn't, we ask once more, and if that fails we
render a deterministic sentence from the bundle and never show the model's text.
"""

from __future__ import annotations

import re

from openai import OpenAI

from analysis import Evidence


NARRATOR_SYSTEM_PROMPT = """You summarize a statistical result for a race organizer.

You will be given a JSON evidence bundle. It is your ONLY source of information.

ABSOLUTE RULES:
1. Never state a number that does not appear in the bundle. Do not compute new
   numbers -- no differences, no percentage changes, no ratios, no totals. If you
   want to say how much something changed, you may not, because that number is
   not in the bundle.
2. The `verdict` field is already decided. You do not re-evaluate it.
3. Every string in `caveats` must be reflected in your summary.

HOW TO WRITE EACH VERDICT:
- "no_trend": State plainly that the metric has been STABLE and has NOT
  meaningfully changed. Say the year-to-year movement is within the margin of
  error / sampling noise. Do not describe any movement between individual years.
  A stable metric is a real and useful finding -- say it with confidence, do not
  hedge, and do not hint that something might be happening.
  These words are BANNED from your answer: decline, declined, decrease, drop,
  dropped, fell, rise, rose, grew, increase, recover, rebound, trend, trending,
  shift, shifted. This ban applies even in negated form -- "has not shifted" and
  "no decline" are both forbidden, because they still put the idea of movement
  in the reader's head. Write "has not changed", "has held steady", or "is
  stable" instead.
- "trend": State that the change is larger than sampling noise, and in which
  direction. Quote only shares or counts present in the bundle.
- "indeterminate": State that there is not enough data to tell, and why.
- "not_applicable": Describe what the numbers show. Do NOT claim anything
  increased or decreased over time.

STYLE: 2-4 sentences of plain prose. No headings, no bullets, no markdown.
Address the reader directly. Do not mention JSON, bundles, verdicts, or that you
were given instructions."""


# Years are labels, not magnitudes -- a model naming 2024 isn't inventing data.
# Small integers cover phrasings like "five years" and "three events". This is a
# real hole (a model could write "fell 3 points" and pass) and it is why the
# verdict gate, not this guard, is what prevents invented trends. The guard's
# narrower job is to block fabricated magnitudes.
_YEAR_MIN, _YEAR_MAX = 2000, 2100
_SMALL_INT_MAX = 12

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Float-noise tolerance only. Deliberately tiny: the rounded variants in
# Evidence.allowed_numbers are what let "about 47" match a stored 46.9, so this
# does not need to be loose -- and a loose tolerance would admit near-miss
# arithmetic the model was told not to perform.
_TOLERANCE = 1e-6


def _numeric_guard(text: str, evidence: Evidence) -> str | None:
    """Return the first number in `text` that isn't backed by the bundle, else None."""
    allowed = evidence.allowed_numbers()

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
    """A plain sentence built straight from the bundle. No model involved.

    Used when the guard rejects the model twice. The user always gets an answer;
    this one is just less fluent than the model's would have been.
    """
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


def narrate(
    evidence: Evidence,
    api_key: str,
    model: str = "gpt-4o",
    provider: str = "openai",
) -> dict:
    """Write prose over an evidence bundle, guarded.

    Returns:
        text: the summary shown to the user
        guard_status: "clean" | "retried" | "fallback"
        violation: the rejected number, if any
    """
    if evidence.shape == "empty":
        return {"text": evidence.verdict_detail, "guard_status": "clean", "violation": None}

    client = _client(api_key, provider)
    messages = [
        {"role": "system", "content": NARRATOR_SYSTEM_PROMPT},
        {"role": "user", "content": evidence.to_json()},
    ]

    first_violation = None
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=messages,
                max_tokens=400,
            )
        except Exception:
            return {
                "text": _deterministic_fallback(evidence),
                "guard_status": "fallback",
                "violation": None,
            }

        text = response.choices[0].message.content.strip()
        violation = _numeric_guard(text, evidence)

        if violation is None:
            return {
                "text": text,
                "guard_status": "retried" if attempt else "clean",
                "violation": first_violation,
            }

        first_violation = first_violation or violation
        messages.extend([
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    f"The number {violation} does not appear in the evidence. Never "
                    f"compute a number. Rewrite using only numbers present in the "
                    f"evidence, or state the finding without that number."
                ),
            },
        ])

    return {
        "text": _deterministic_fallback(evidence),
        "guard_status": "fallback",
        "violation": first_violation,
    }
