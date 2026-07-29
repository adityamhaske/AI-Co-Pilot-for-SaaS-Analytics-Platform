"""Deterministic tests for the metric handlers.

These assert exact numbers against a hand-built fixture. The previous suite exercised
none of this SQL, which is how ``arr`` shipped as an alias for ``mrr``, ``granularity``
shipped as a no-op, and MRR shipped measuring new bookings instead of recurring revenue.
"""

import datetime

import pytest

from app.db.models import Customer, Subscription, Tenant, UsageEvent
from app.validator.query_validator import (
    compare_segments_handler,
    execute_tool,
    get_metric_trend_handler,
    get_top_customers_handler,
)

TENANT = "tenant_metrics"
OTHER_TENANT = "tenant_other"

D = datetime.date
DT = datetime.datetime


@pytest.fixture
def metrics_data(db_session):
    """Two subscriptions with known lifetimes, plus a decoy in another tenant.

        sub_a  mrr=100  2026-01-01 -> open ended   (active)
        sub_b  mrr=200  2026-02-01 -> 2026-03-15   (canceled)

    Expected MRR by month: Jan 100, Feb 300, Mar 300, Apr 100.
    """
    for tid in (TENANT, OTHER_TENANT):
        if not db_session.query(Tenant).filter(Tenant.id == tid).first():
            db_session.add(Tenant(id=tid, name=tid))

    db_session.add_all(
        [
            Customer(
                id="cust_a",
                tenant_id=TENANT,
                name="Alpha",
                segment="enterprise",
                created_at=DT(2026, 1, 5),
            ),
            Customer(
                id="cust_b",
                tenant_id=TENANT,
                name="Beta",
                segment="smb",
                created_at=DT(2026, 2, 10),
            ),
            Subscription(
                id="sub_a",
                tenant_id=TENANT,
                customer_id="cust_a",
                mrr=100.0,
                start_date=D(2026, 1, 1),
                end_date=None,
                status="active",
            ),
            Subscription(
                id="sub_b",
                tenant_id=TENANT,
                customer_id="cust_b",
                mrr=200.0,
                start_date=D(2026, 2, 1),
                end_date=D(2026, 3, 15),
                status="canceled",
            ),
            # Must never appear in TENANT's results.
            Customer(
                id="cust_x",
                tenant_id=OTHER_TENANT,
                name="Xeno",
                segment="enterprise",
                created_at=DT(2026, 1, 5),
            ),
            Subscription(
                id="sub_x",
                tenant_id=OTHER_TENANT,
                customer_id="cust_x",
                mrr=9999.0,
                start_date=D(2026, 1, 1),
                end_date=None,
                status="active",
            ),
            UsageEvent(
                id="evt_a1",
                tenant_id=TENANT,
                customer_id="cust_a",
                event_type="login",
                timestamp=DT(2026, 1, 10),
            ),
            UsageEvent(
                id="evt_a2",
                tenant_id=TENANT,
                customer_id="cust_a",
                event_type="login",
                timestamp=DT(2026, 1, 11),
            ),
            UsageEvent(
                id="evt_b1",
                tenant_id=TENANT,
                customer_id="cust_b",
                event_type="login",
                timestamp=DT(2026, 2, 3),
            ),
            UsageEvent(
                id="evt_x1",
                tenant_id=OTHER_TENANT,
                customer_id="cust_x",
                event_type="login",
                timestamp=DT(2026, 1, 10),
            ),
        ]
    )
    db_session.commit()
    yield db_session

    for model, ids in (
        (UsageEvent, ["evt_a1", "evt_a2", "evt_b1", "evt_x1"]),
        (Subscription, ["sub_a", "sub_b", "sub_x"]),
        (Customer, ["cust_a", "cust_b", "cust_x"]),
        (Tenant, [TENANT, OTHER_TENANT]),
    ):
        db_session.query(model).filter(model.id.in_(ids)).delete(
            synchronize_session=False
        )
    db_session.commit()


TREND_ARGS = {
    "metric": "mrr",
    "start_date": "2026-01-01",
    "end_date": "2026-04-30",
    "granularity": "month",
}


def test_mrr_is_point_in_time_not_new_bookings(metrics_data):
    """A subscription contributes to every month it is live, not just the month it started.

    Grouping by ``start_date`` (the old behaviour) reported Jan=100, Feb=200, Mar=0,
    Apr=0 — and dropped sub_b entirely because it filters ``status == 'active'``.
    """
    rows = get_metric_trend_handler(metrics_data, TENANT, dict(TREND_ARGS))
    assert rows == [
        {"date": "2026-01", "value": 100.0},
        {"date": "2026-02", "value": 300.0},
        {"date": "2026-03", "value": 300.0},
        {"date": "2026-04", "value": 100.0},
    ]


def test_arr_is_twelve_times_mrr(metrics_data):
    """``arr`` used to return the mrr series unchanged."""
    mrr = get_metric_trend_handler(metrics_data, TENANT, dict(TREND_ARGS))
    arr = get_metric_trend_handler(
        metrics_data, TENANT, {**TREND_ARGS, "metric": "arr"}
    )

    assert [r["value"] for r in arr] == [r["value"] * 12 for r in mrr]
    assert arr[0]["value"] == 1200.0


def test_granularity_changes_the_buckets(metrics_data):
    """``granularity`` was validated and advertised to the model, then ignored."""
    daily = get_metric_trend_handler(
        metrics_data,
        TENANT,
        {
            "metric": "mrr",
            "start_date": "2026-02-01",
            "end_date": "2026-02-07",
            "granularity": "day",
        },
    )
    assert [r["date"] for r in daily] == [
        "2026-02-01",
        "2026-02-02",
        "2026-02-03",
        "2026-02-04",
        "2026-02-05",
        "2026-02-06",
        "2026-02-07",
    ]
    assert all(r["value"] == 300.0 for r in daily)

    weekly = get_metric_trend_handler(
        metrics_data,
        TENANT,
        {
            "metric": "mrr",
            "start_date": "2026-02-01",
            "end_date": "2026-02-28",
            "granularity": "week",
        },
    )
    assert len(weekly) < len(daily) * 2
    assert all(len(r["date"]) == len("2026-02-02") for r in weekly)


def test_trend_is_tenant_scoped(metrics_data):
    """The 9999.0 subscription in the other tenant must never leak in."""
    rows = get_metric_trend_handler(metrics_data, TENANT, dict(TREND_ARGS))
    assert all(r["value"] < 9999.0 for r in rows)

    other = get_metric_trend_handler(metrics_data, OTHER_TENANT, dict(TREND_ARGS))
    assert other[0]["value"] == 9999.0


def test_active_users_counts_distinct_customers_per_period(metrics_data):
    rows = get_metric_trend_handler(
        metrics_data,
        TENANT,
        {
            "metric": "active_users",
            "start_date": "2026-01-01",
            "end_date": "2026-02-28",
            "granularity": "month",
        },
    )
    # cust_a has two January events but counts once; cust_b is the only February user.
    assert rows == [
        {"date": "2026-01", "value": 1},
        {"date": "2026-02", "value": 1},
    ]


def test_new_signups_counts_customers_by_creation_month(metrics_data):
    rows = get_metric_trend_handler(
        metrics_data,
        TENANT,
        {
            "metric": "new_signups",
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "granularity": "month",
        },
    )
    assert rows == [
        {"date": "2026-01", "value": 1},
        {"date": "2026-02", "value": 1},
        {"date": "2026-03", "value": 0},
    ]


def test_empty_range_returns_zeros_not_a_fake_row(metrics_data):
    """The old handler returned [{'date': 'no_data', 'value': 0}], which charted as data."""
    rows = get_metric_trend_handler(
        metrics_data,
        TENANT,
        {
            "metric": "mrr",
            "start_date": "2020-01-01",
            "end_date": "2020-02-29",
            "granularity": "month",
        },
    )
    assert [r["date"] for r in rows] == ["2020-01", "2020-02"]
    assert all(r["value"] == 0.0 for r in rows)
    assert not any(r["date"] == "no_data" for r in rows)


def test_reversed_date_range_is_rejected(metrics_data):
    with pytest.raises(ValueError):
        get_metric_trend_handler(
            metrics_data,
            TENANT,
            {
                "metric": "mrr",
                "start_date": "2026-04-01",
                "end_date": "2026-01-01",
                "granularity": "month",
            },
        )


def test_excessive_period_count_is_rejected(metrics_data):
    with pytest.raises(ValueError, match="Narrow the date range"):
        get_metric_trend_handler(
            metrics_data,
            TENANT,
            {
                "metric": "mrr",
                "start_date": "2000-01-01",
                "end_date": "2026-01-01",
                "granularity": "day",
            },
        )


def test_top_customers_is_tenant_scoped(metrics_data):
    rows = get_top_customers_handler(
        metrics_data, TENANT, {"sort_by": "mrr", "limit": 10}
    )
    names = [r["name"] for r in rows]
    assert "Xeno" not in names
    # Beta's only subscription is canceled, so it carries no *current* MRR and drops out
    # of a "top customers by MRR" ranking entirely.
    assert names == ["Alpha"]
    assert rows[0]["mrr"] == 100.0


def test_compare_segments_uses_active_mrr(metrics_data):
    result = compare_segments_handler(
        metrics_data,
        TENANT,
        {"metric": "mrr", "segment_a": "enterprise", "segment_b": "smb"},
    )
    assert result["segment_a"] == {"name": "enterprise", "value": 100.0}
    # sub_b is canceled, so it contributes no *current* MRR.
    assert result["segment_b"]["value"] == 0.0


def test_execute_tool_rejects_unknown_tool(metrics_data):
    with pytest.raises(ValueError, match="Unknown tool"):
        execute_tool(metrics_data, TENANT, "drop_all_tables", {})
