"""
Intent router: descriptive vs. causal
======================================
Before we answer a question, decide what *kind* of question it is.

A DESCRIPTIVE question asks what the data shows -- counts, shares, rankings,
change over time. Text-to-SQL plus the narrator answers these honestly.

A CAUSAL question asks *why*, or whether one thing *caused* another -- "did the
price increase hurt signups?", "what was the impact of X on Y?". We cannot answer
these from a single descriptive query: correlation in a GROUP BY is not cause, and
the confounds (deadline effects, event-mix drift) are exactly what a bare number
hides. So we still show the descriptive numbers, but we label them plainly as
descriptive and refuse to imply cause.

Detection is a deterministic causal-marker scan first (fast, free, unit-testable,
high precision on the obvious phrasings), then an LLM tie-breaker for anything the
markers miss. On any LLM failure we default to "descriptive" -- the markers have
already caught the clear causal cases, and a missed banner is better than nagging
every descriptive question with a false one.
"""

from __future__ import annotations

import re

from openai import OpenAI


# High-precision causal phrasings. These target *causation* specifically, not
# *change* -- "how did the split change over time" is descriptive and must not
# match here, while "why did the split change" must. Word boundaries keep
# "impact of" from firing on "high-impact" and "cause" from firing inside a
# larger word.
_CAUSAL_MARKERS = [
    r"\bimpact(?:ed)?\s+(?:of|on)\b",
    r"\beffect\b",
    r"\baffect(?:ed|s|ing)?\b",
    r"\binfluenc(?:e|ed|es|ing)\b",
    r"\bcaus(?:e|ed|es|ing)\b",
    r"\bbecause\b",
    r"\bdue to\b",
    r"\bas a result\b",
    r"\bresult(?:ed)?\s+(?:in|from)\b",
    r"\bled to\b",
    r"\bdriv(?:e|en|es|ing)\b",
    r"\bdrove\b",
    r"\bhurt\b",
    r"\bboost(?:ed)?\b",
    r"\bwhy\b",
    r"\bresponsible for\b",
    r"\battributab",
    r"\bcorrelat",
    r"\bcontribut(?:e|ed|es|ing)\b",
    r"\bthanks to\b",
    r"\bexplain(?:s|ed)?\b",
]

_CAUSAL_RE = re.compile("|".join(_CAUSAL_MARKERS), re.IGNORECASE)

# Price questions are the motivating causal case, and they carry an extra
# problem beyond causation: there is no price data in the database at all. When
# a causal question is also about price, the banner should say so.
_PRICE_RE = re.compile(r"\bpric(?:e|es|ing)\b|\bcost(?:s)?\b|\bfee(?:s)?\b|\bdollar", re.IGNORECASE)


ROUTER_SYSTEM_PROMPT = """You classify a question about a race registration dataset.

Answer with exactly one word, lowercase, no punctuation: "descriptive" or "causal".

descriptive = asks what the data shows: counts, totals, averages, shares,
rankings, distributions, or how a metric changed over time. Examples:
"how many people registered in 2024", "show the sex breakdown by year",
"how did the gender split change", "what are the top cities".

causal = asks why something happened, or whether one thing caused, drove,
affected, or explains another. Examples: "did the price increase hurt signups",
"what was the impact of the new route on registrations", "why did 10K numbers
fall". A question is causal even if it also names a metric.

If the question only asks to see or compare numbers, it is descriptive. It is
causal only when it asks for a reason or an effect.

Reply with one word only."""


def _deterministic_causal(question: str) -> str | None:
    """Return the matched causal phrase if one is present, else None."""
    match = _CAUSAL_RE.search(question)
    return match.group(0) if match else None


def _llm_classify(question: str, api_key: str, model: str, provider: str) -> str:
    client = _client(api_key, provider)
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=4,
        messages=[
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    answer = response.choices[0].message.content.strip().lower()
    return "causal" if "causal" in answer else "descriptive"


def _client(api_key: str, provider: str) -> OpenAI:
    """Same provider switch as nl_query_engine.generate_sql and narrator."""
    if provider == "gemini":
        return OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    return OpenAI(api_key=api_key)


def _causal_caveat(question: str) -> str:
    """The banner text shown when a question is judged causal."""
    base = (
        "Heads up: this is a cause-and-effect question, so read the analysis below "
        "as descriptive -- it shows what the registration numbers did around the "
        "dates in question, not proof that one thing caused another. Other things "
        "may have changed at the same time."
    )
    if _PRICE_RE.search(question):
        base += (
            " Note that the database has no price field, so the analysis works from "
            "any dates you provide rather than from price data itself."
        )
    return base


def classify(
    question: str,
    api_key: str | None = None,
    model: str = "gpt-4o-mini",
    provider: str = "openai",
) -> dict:
    """Route a question to a descriptive or causal intent.

    Returns:
        intent: "descriptive" | "causal"
        method: "marker" | "llm" | "fallback"
        matched: the causal phrase that fired, if method == "marker"
        caveat: banner text to show when intent == "causal", else None
    """
    marker = _deterministic_causal(question)
    if marker:
        return {
            "intent": "causal",
            "method": "marker",
            "matched": marker,
            "caveat": _causal_caveat(question),
        }

    # No obvious marker. Ask the model, but only if we can -- with no key we
    # default to descriptive rather than guess.
    if api_key:
        try:
            intent = _llm_classify(question, api_key, model, provider)
            method = "llm"
        except Exception:
            intent, method = "descriptive", "fallback"
    else:
        intent, method = "descriptive", "fallback"

    return {
        "intent": intent,
        "method": method,
        "matched": None,
        "caveat": _causal_caveat(question) if intent == "causal" else None,
    }
