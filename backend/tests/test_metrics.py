"""Deterministic tests for the metric registry.

These assert exact numbers against a hand-built fixture, so a change in metric semantics
has to be made deliberately rather than discovered in production.
"""

import pytest

from app.metrics import queries, registry
from app.metrics.queries import CompareArgs, SnapshotArgs, TrendArgs
from app.metrics.schema import QueryShape
from app.orchestrator import tools as toolbox
from tests.conftest import OTHER_TENANT, TENANT

FULL_RANGE = {
    "start_date": "2026-01-01",
    "end_date": "2026-04-30",
    "granularity": "month",
}


def series(db, metric, role="viewer", **overrides):
    args = TrendArgs(metric=metric, **{**FULL_RANGE, **overrides})
    result = queries.trend(db, TENANT, role, args)
    return [(p["date"], p["value"]) for p in result["series"]]


# ---------------------------------------------------------------------------
# Metric semantics
# ---------------------------------------------------------------------------


def test_mrr_is_measured_as_of_period_end(metrics_data):
    """MRR is a stock measure, read at the close of each period.

    sub_b cancels on 15 March, so it counts towards February's closing MRR but not
    March's. The original implementation grouped by start_date, which measured new
    bookings instead and reported zero for every month after a subscription began.
    """
    assert series(metrics_data, "mrr") == [
        ("2026-01", 100.0),
        ("2026-02", 300.0),
        ("2026-03", 100.0),
        ("2026-04", 100.0),
    ]


def test_arr_is_twelve_times_mrr(metrics_data):
    """arr is declared as `derived from mrr, factor 12`, so it cannot drift."""
    mrr = series(metrics_data, "mrr")
    arr = series(metrics_data, "arr")
    assert [v for _, v in arr] == [v * 12 for _, v in mrr]


def test_granularity_changes_the_buckets(metrics_data):
    """granularity was validated, advertised to the model, and then ignored."""
    daily = series(
        metrics_data,
        "mrr",
        start_date="2026-02-01",
        end_date="2026-02-05",
        granularity="day",
    )
    assert [d for d, _ in daily] == [
        "2026-02-01",
        "2026-02-02",
        "2026-02-03",
        "2026-02-04",
        "2026-02-05",
    ]
    assert all(v == 300.0 for _, v in daily)

    weekly = series(
        metrics_data,
        "mrr",
        start_date="2026-02-01",
        end_date="2026-02-28",
        granularity="week",
    )
    assert 4 <= len(weekly) <= 5


def test_active_users_counts_distinct_customers(metrics_data):
    rows = series(
        metrics_data, "active_users", start_date="2026-01-01", end_date="2026-02-28"
    )
    # cust_a has two January events but counts once.
    assert rows == [("2026-01", 1), ("2026-02", 1)]


def test_new_signups_counts_by_creation_month(metrics_data):
    rows = series(
        metrics_data, "new_signups", start_date="2026-01-01", end_date="2026-03-31"
    )
    assert rows == [("2026-01", 1), ("2026-02", 1), ("2026-03", 0)]


def test_empty_range_returns_zeros_not_a_sentinel_row(metrics_data):
    """The old handler returned [{'date': 'no_data', 'value': 0}], which charted as data."""
    rows = series(metrics_data, "mrr", start_date="2020-01-01", end_date="2020-02-29")
    assert rows == [("2020-01", 0.0), ("2020-02", 0.0)]
    assert not any(d == "no_data" for d, _ in rows)


def test_churn_rate_reports_its_own_terms(metrics_data):
    """A bare ratio is not checkable; the numerator and denominator make it auditable."""
    result = queries.snapshot(
        metrics_data,
        TENANT,
        "viewer",
        SnapshotArgs(metric="churn_rate", period="last_year"),
    )
    assert result["numerator"]["metric"] == "churned_subscriptions"
    assert result["denominator"]["metric"] == "active_subscriptions_at_start"
    assert result["unit"] == "ratio"


# ---------------------------------------------------------------------------
# Consistency — the reason the registry exists
# ---------------------------------------------------------------------------


def test_compare_agrees_with_trend_on_the_same_metric(metrics_data):
    """Segment MRR and trend MRR must reconcile.

    Before the registry there were three MRR definitions in one module: a point-in-time
    sum for trends and two `status == 'active'` variants for comparison and ranking. The
    sum of the segments could not be tied back to the trend.
    """
    compare = queries.compare(
        metrics_data,
        TENANT,
        "analyst",
        CompareArgs(
            metric="mrr", segment_a="enterprise", segment_b="smb", period="last_month"
        ),
    )
    snapshot = queries.snapshot(
        metrics_data, TENANT, "viewer", SnapshotArgs(metric="mrr", period="last_month")
    )

    total = compare["segment_a"]["value"] + compare["segment_b"]["value"]
    assert total == snapshot["value"]


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_trend_is_tenant_scoped(metrics_data):
    ours = series(metrics_data, "mrr")
    assert all(v < 9999.0 for _, v in ours)

    theirs = queries.trend(
        metrics_data, OTHER_TENANT, "viewer", TrendArgs(metric="mrr", **FULL_RANGE)
    )
    assert theirs["series"][0]["value"] == 9999.0


def test_compare_is_tenant_scoped(metrics_data):
    """The other tenant also has an 'enterprise' segment; it must not bleed across."""
    result = queries.compare(
        metrics_data,
        TENANT,
        "analyst",
        CompareArgs(
            metric="mrr", segment_a="enterprise", segment_b="smb", period="last_month"
        ),
    )
    assert result["segment_a"]["value"] == 100.0
    assert result["segment_a"]["customers"] == 1


def test_unknown_segment_yields_zero_not_everything(metrics_data):
    """An empty customer list must filter to nothing, not fall through to no filter."""
    result = queries.compare(
        metrics_data,
        TENANT,
        "analyst",
        CompareArgs(metric="mrr", segment_a="nonexistent", segment_b="smb"),
    )
    assert result["segment_a"] == {"name": "nonexistent", "value": 0.0, "customers": 0}


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_metric_must_support_the_requested_shape(metrics_data):
    with pytest.raises(ValueError, match="does not support trend"):
        queries.trend(
            metrics_data, TENANT, "viewer", TrendArgs(metric="churn_rate", **FULL_RANGE)
        )


def test_building_block_metrics_are_not_exposed(metrics_data):
    """Components of churn_rate declare `supports: []` and must reach no tool."""
    for shape in QueryShape:
        for role in ("viewer", "analyst", "admin"):
            names = registry.names_for(shape, role)
            assert "churned_subscriptions" not in names
            assert "active_subscriptions_at_start" not in names


def test_unknown_metric_is_rejected(metrics_data):
    with pytest.raises(ValueError, match="Unknown metric"):
        queries.trend(
            metrics_data,
            TENANT,
            "viewer",
            TrendArgs(metric="revenue_per_unicorn", **FULL_RANGE),
        )


def test_reversed_date_range_is_rejected():
    with pytest.raises(ValueError, match="not be earlier"):
        TrendArgs(
            metric="mrr",
            start_date="2026-04-01",
            end_date="2026-01-01",
            granularity="month",
        )


def test_excessive_period_count_is_rejected(metrics_data):
    with pytest.raises(ValueError, match="Narrow the date range"):
        series(
            metrics_data,
            "mrr",
            start_date="2000-01-01",
            end_date="2026-01-01",
            granularity="day",
        )


def test_unknown_tool_is_rejected(metrics_data):
    with pytest.raises(ValueError, match="Unknown tool"):
        toolbox.execute(metrics_data, TENANT, "admin", "drop_all_tables", {})


# ---------------------------------------------------------------------------
# Bespoke tools that still carry hand-written SQL
# ---------------------------------------------------------------------------


def test_top_customers_is_tenant_scoped(metrics_data):
    rows = toolbox.execute(
        metrics_data,
        TENANT,
        "analyst",
        "get_top_customers",
        {"sort_by": "mrr", "limit": 10},
    )
    names = [r["name"] for r in rows]
    assert "Xeno" not in names
    # Beta's only subscription is cancelled, so it carries no current MRR.
    assert names == ["Alpha"]
