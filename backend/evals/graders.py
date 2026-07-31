"""Graders.

Each grader answers one narrow question about a run and returns a verdict plus a reason,
so a failure report says *what* went wrong rather than just that the case failed.

Deliberately mechanical: no model-as-judge. A grader that itself relies on an LLM would
make the accuracy number depend on the thing being measured.
"""

from dataclasses import dataclass
from typing import Any

# Phrases that signal the assistant declined rather than fabricating. Matched
# case-insensitively against the final answer.
INABILITY_MARKERS = (
    "cannot",
    "can't",
    "can not",
    "unable",
    "don't have",
    "do not have",
    "no tool",
    "not able",
    "not available",
    "outside",
    "no access",
    "not permitted",
    "isn't something",
    "is not something",
    "apolog",
    "sorry",
)


@dataclass
class Verdict:
    name: str
    passed: bool
    reason: str = ""

    @property
    def symbol(self) -> str:
        return "PASS" if self.passed else "FAIL"


def _norm(value: Any) -> str:
    return str(value).strip().lower()


def grade_tool_choice(expected: dict, calls: list[dict]) -> Verdict:
    """Was the expected tool called, with the expected arguments?

    Only the arguments named in the case are checked. Dates are left free: several date
    ranges are defensible for "the last 6 months", and pinning them would measure
    prompt-phrasing luck rather than correctness.
    """
    name = expected["name"]
    matching = [c for c in calls if c["name"] == name]
    if not matching:
        called = ", ".join(c["name"] for c in calls) or "nothing"
        return Verdict("tool", False, f"expected {name}, called {called}")

    wanted = expected.get("args") or {}
    if not wanted:
        return Verdict("tool", True)

    for call in matching:
        got = call.get("input") or {}
        mismatches = [
            f"{k}={got.get(k)!r} (wanted {v!r})"
            for k, v in wanted.items()
            if _norm(got.get(k)) != _norm(v)
        ]
        if not mismatches:
            return Verdict("tool", True)

    got = matching[0].get("input") or {}
    diff = ", ".join(
        f"{k}={got.get(k)!r} wanted {v!r}"
        for k, v in wanted.items()
        if _norm(got.get(k)) != _norm(v)
    )
    return Verdict("tool", False, f"{name} called with {diff}")


def grade_tools_called(expected: list[str], calls: list[dict]) -> Verdict:
    """Were at least the expected tools called, counting repeats?"""
    remaining = list(expected)
    for call in calls:
        if call["name"] in remaining:
            remaining.remove(call["name"])
    if remaining:
        called = ", ".join(c["name"] for c in calls) or "nothing"
        return Verdict(
            "tool", False, f"missing {', '.join(remaining)}; called {called}"
        )
    return Verdict("tool", True)


def grade_no_tool(calls: list[dict]) -> Verdict:
    """The system should not have reached for data it cannot legitimately return."""
    if calls:
        return Verdict("tool", False, f"called {', '.join(c['name'] for c in calls)}")
    return Verdict("tool", True)


def grade_value(expected: float, calls: list[dict]) -> Verdict:
    """Did a tool actually return the expected number?

    Checked against tool *results*, not the answer text, so formatting choices
    ("$5,600" vs "5600.0") do not affect the verdict.
    """
    for call in calls:
        if _contains_number(call.get("result"), expected):
            return Verdict("value", True)
    return Verdict("value", False, f"no tool result contained {expected}")


def _contains_number(payload: Any, target: float, tolerance: float = 0.01) -> bool:
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        return abs(float(payload) - target) <= tolerance
    if isinstance(payload, dict):
        return any(_contains_number(v, target, tolerance) for v in payload.values())
    if isinstance(payload, list):
        return any(_contains_number(v, target, tolerance) for v in payload)
    return False


def grade_answer(expected: dict, answer: str) -> Verdict:
    """Does the final text satisfy the case's content constraints?"""
    lowered = answer.lower()
    problems = []

    contains_any = expected.get("contains_any")
    if contains_any and not any(c.lower() in lowered for c in contains_any):
        problems.append(f"none of {contains_any} present")

    for forbidden in expected.get("not_contains_any", []):
        if forbidden.lower() in lowered:
            problems.append(f"contains forbidden {forbidden!r}")

    if expected.get("indicates_inability") and not any(
        marker in lowered for marker in INABILITY_MARKERS
    ):
        problems.append("did not decline or acknowledge a limit")

    if problems:
        return Verdict("answer", False, "; ".join(problems))
    return Verdict("answer", True)


def grade_completion(run: dict) -> Verdict:
    """Did the turn actually finish and say something?

    Added after the first live run scored 100% while eight cases had produced no answer
    at all: the model called the right tool, then burned its whole step budget and
    emitted an error. The tool grader passed them. A user would have seen charts and no
    explanation, so a suite that calls that a pass is measuring the wrong thing.
    """
    errors = run.get("errors") or []
    if errors:
        return Verdict("completion", False, f"ended with an error: {errors[0]}")
    if not (run.get("answer") or "").strip():
        return Verdict("completion", False, "produced no answer text")
    return Verdict("completion", True)


def grade_case(case: dict, run: dict) -> list[Verdict]:
    """Apply every grader the case asks for."""
    verdicts: list[Verdict] = [grade_completion(run)]
    calls = run["tool_calls"]

    if case.get("expect_no_tool"):
        verdicts.append(grade_no_tool(calls))
    elif case.get("expect_tool"):
        verdicts.append(grade_tool_choice(case["expect_tool"], calls))
    elif case.get("expect_tools_called"):
        verdicts.append(grade_tools_called(case["expect_tools_called"], calls))

    expected_value: float | None = run.get("expected_value")
    if expected_value is not None:
        verdicts.append(grade_value(expected_value, calls))

    if case.get("expect_answer"):
        verdicts.append(grade_answer(case["expect_answer"], run["answer"]))

    return verdicts
