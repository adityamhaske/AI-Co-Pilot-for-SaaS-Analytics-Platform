"""Tests for the eval harness itself.

Two things need to hold before an accuracy number means anything:

1. The dataset is well-formed — every case names a real tool, a real role, and a real
   metric, so a typo cannot quietly make a case unfailable.
2. The hand-computed expected values in `evals/fixtures.py` actually match what the
   metric layer returns for that fixture. Otherwise the evals measure agreement with a
   wrong answer.

Neither needs an API key, so both run on every commit.
"""

import pytest

from app.core.rbac import ROLE_PERMISSIONS
from app.metrics import queries, registry
from app.metrics.queries import CompareArgs, SnapshotArgs
from app.metrics.schema import QueryShape
from app.orchestrator import tools as toolbox
from app.orchestrator.bespoke_tools import BESPOKE_HANDLERS
from evals import fixtures
from evals.graders import (
    Verdict,
    grade_answer,
    grade_no_tool,
    grade_tool_choice,
    grade_tools_called,
    grade_value,
)
from evals.runner import load_cases

CASES = load_cases()
KNOWN_TOOLS = set(queries.HANDLERS) | set(BESPOKE_HANDLERS)


@pytest.fixture
def eval_data(db_session):
    fixtures.build(db_session)
    yield db_session
    fixtures.wipe(db_session)


# ---------------------------------------------------------------------------
# Dataset integrity
# ---------------------------------------------------------------------------


def test_case_ids_are_unique():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_is_well_formed(case):
    assert case["question"].strip()
    assert case["role"] in ROLE_PERMISSIONS, case["role"]
    assert case.get("category"), "every case needs a category for the report"

    expectations = [
        k
        for k in (
            "expect_tool",
            "expect_tools_called",
            "expect_no_tool",
            "expect_answer",
        )
        if case.get(k)
    ]
    assert expectations, "a case that asserts nothing cannot fail"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_expected_tools_exist(case):
    names = []
    if case.get("expect_tool"):
        names.append(case["expect_tool"]["name"])
    names.extend(case.get("expect_tools_called", []))
    for name in names:
        assert name in KNOWN_TOOLS, f"{case['id']} expects unknown tool {name}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_expected_metrics_exist_and_are_reachable(case):
    """A case must expect a metric the caller can actually reach, or it can never pass."""
    expect = case.get("expect_tool")
    if not expect:
        return
    metric_name = (expect.get("args") or {}).get("metric")
    if not metric_name:
        return

    metric = registry.get(metric_name)  # raises if undefined
    assert metric.allowed_for(case["role"])

    shape = {
        "get_metric_trend": QueryShape.TREND,
        "get_metric_value": QueryShape.SNAPSHOT,
        "compare_segments": QueryShape.COMPARE,
    }[expect["name"]]
    assert metric.supports_shape(shape), f"{metric_name} does not support {shape.value}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_expected_values_reference_real_keys(case):
    key = case.get("expect_value")
    if key:
        assert key in fixtures.EXPECTED, f"{case['id']} references unknown key {key}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_rbac_cases_match_the_real_matrix(case):
    """An `expect_no_tool` RBAC case must genuinely be out of that role's reach."""
    if case.get("category") != "rbac":
        return
    available = {t["name"] for t in toolbox.schemas_for(case["role"])}
    if case.get("expect_no_tool"):
        # The tool the question is fishing for must not be available to this role.
        assert "list_active_alerts" not in available or "top" in case["id"]
    if case.get("expect_tool"):
        assert case["expect_tool"]["name"] in available


def test_dataset_covers_every_category():
    categories = {c.get("category") for c in CASES}
    assert {
        "direct",
        "granularity",
        "indirect",
        "multi_tool",
        "grounding",
        "rbac",
        "adversarial",
    } <= categories


def test_dataset_exercises_every_tool():
    """Every tool the model can be shown should appear somewhere in the dataset."""
    expected = set()
    for case in CASES:
        if case.get("expect_tool"):
            expected.add(case["expect_tool"]["name"])
        expected.update(case.get("expect_tools_called", []))
    assert KNOWN_TOOLS <= expected, f"never evaluated: {KNOWN_TOOLS - expected}"


# ---------------------------------------------------------------------------
# The fixture's hand-computed answers
# ---------------------------------------------------------------------------


def test_fixture_mrr_matches_expected(eval_data):
    result = queries.snapshot(
        eval_data,
        fixtures.EVAL_TENANT,
        "viewer",
        SnapshotArgs(metric="mrr", period="last_month"),
    )
    assert result["value"] == fixtures.EXPECTED["mrr"]


def test_fixture_arr_matches_expected(eval_data):
    result = queries.snapshot(
        eval_data,
        fixtures.EVAL_TENANT,
        "viewer",
        SnapshotArgs(metric="arr", period="last_month"),
    )
    assert result["value"] == fixtures.EXPECTED["arr"]


def test_fixture_segment_mrr_matches_expected(eval_data):
    result = queries.compare(
        eval_data,
        fixtures.EVAL_TENANT,
        "analyst",
        CompareArgs(metric="mrr", segment_a="enterprise", segment_b="smb"),
    )
    assert result["segment_a"]["value"] == fixtures.EXPECTED["enterprise_mrr"]
    assert result["segment_b"]["value"] == fixtures.EXPECTED["smb_mrr"]


def test_fixture_churned_segment_has_no_current_mrr(eval_data):
    result = queries.compare(
        eval_data,
        fixtures.EVAL_TENANT,
        "analyst",
        CompareArgs(metric="mrr", segment_a="midmarket", segment_b="smb"),
    )
    assert result["segment_a"]["value"] == fixtures.EXPECTED["midmarket_mrr"]


def test_fixture_churn_rate_matches_expected(eval_data):
    result = queries.snapshot(
        eval_data,
        fixtures.EVAL_TENANT,
        "viewer",
        SnapshotArgs(metric="churn_rate", period="last_quarter"),
    )
    assert result["value"] == fixtures.EXPECTED["churn_rate_quarter"]
    assert result["numerator"]["value"] == 2
    assert result["denominator"]["value"] == fixtures.EXPECTED["total_customers"]


def test_fixture_segments_sum_to_total_mrr(eval_data):
    """The segments partition the customer base, so they must add up."""
    total = queries.snapshot(
        eval_data,
        fixtures.EVAL_TENANT,
        "viewer",
        SnapshotArgs(metric="mrr", period="last_month"),
    )["value"]
    parts = sum(
        queries.compare(
            eval_data,
            fixtures.EVAL_TENANT,
            "analyst",
            CompareArgs(metric="mrr", segment_a=segment, segment_b="none"),
        )["segment_a"]["value"]
        for segment in ("enterprise", "smb", "midmarket")
    )
    assert parts == total


# ---------------------------------------------------------------------------
# Graders
# ---------------------------------------------------------------------------


def call(name, **inp):
    return {"name": name, "input": inp, "result": None}


def test_tool_choice_passes_on_exact_match():
    v = grade_tool_choice(
        {"name": "get_metric_trend", "args": {"metric": "mrr"}},
        [call("get_metric_trend", metric="mrr", granularity="month")],
    )
    assert v.passed


def test_tool_choice_fails_on_wrong_metric():
    v = grade_tool_choice(
        {"name": "get_metric_trend", "args": {"metric": "mrr"}},
        [call("get_metric_trend", metric="arr")],
    )
    assert not v.passed
    assert "arr" in v.reason


def test_tool_choice_fails_when_tool_absent():
    v = grade_tool_choice({"name": "get_metric_trend"}, [call("get_top_customers")])
    assert not v.passed


def test_tool_choice_accepts_any_matching_call_among_several():
    """A model may call a tool twice; one correct call is enough."""
    v = grade_tool_choice(
        {"name": "get_metric_value", "args": {"metric": "churn_rate"}},
        [
            call("get_metric_value", metric="mrr"),
            call("get_metric_value", metric="churn_rate"),
        ],
    )
    assert v.passed


def test_tools_called_requires_all_expected():
    calls = [call("get_metric_trend"), call("get_top_customers")]
    assert grade_tools_called(["get_metric_trend", "get_top_customers"], calls).passed
    assert not grade_tools_called(
        ["get_metric_trend", "list_active_alerts"], calls
    ).passed


def test_tools_called_counts_repeats():
    v = grade_tools_called(
        ["get_metric_value", "get_metric_value"], [call("get_metric_value")]
    )
    assert not v.passed


def test_no_tool_grader():
    assert grade_no_tool([]).passed
    assert not grade_no_tool([call("get_metric_trend")]).passed


def test_value_grader_finds_nested_numbers():
    calls = [
        {
            "name": "t",
            "input": {},
            "result": {"series": [{"date": "x", "value": 5600.0}]},
        }
    ]
    assert grade_value(5600.0, calls).passed
    assert not grade_value(1234.0, calls).passed


def test_value_grader_ignores_booleans():
    """True == 1 in Python; a boolean must not satisfy a numeric expectation."""
    calls = [{"name": "t", "input": {}, "result": {"ok": True}}]
    assert not grade_value(1.0, calls).passed


def test_answer_grader_contains_any():
    assert grade_answer({"contains_any": ["5,600", "5600"]}, "Your MRR is 5600.").passed
    assert not grade_answer({"contains_any": ["5,600"]}, "Your MRR is 1.").passed


def test_answer_grader_not_contains():
    v = grade_answer({"not_contains_any": ["tenant_test"]}, "Data for tenant_test here")
    assert not v.passed


def test_answer_grader_detects_declining():
    assert grade_answer({"indicates_inability": True}, "I cannot answer that.").passed
    assert grade_answer({"indicates_inability": True}, "I don't have that data.").passed
    assert not grade_answer(
        {"indicates_inability": True}, "You have 250 employees."
    ).passed


def test_verdict_symbol():
    assert Verdict("tool", True).symbol == "PASS"
    assert Verdict("tool", False).symbol == "FAIL"
