"""Compiles metric definitions into tenant-scoped SQLAlchemy queries.

Every query this module builds carries a tenant predicate. That is not left to the
caller: `_base_filters` is the only way a query is constructed, and it always applies
the tenant scope.
"""

import datetime
from typing import Any

from sqlalchemy import Select, case, false, func, or_, select
from sqlalchemy.orm import Session

from app.metrics import registry
from app.metrics.periods import Period
from app.metrics.schema import (
    MODELS,
    EvaluateAt,
    MetricDefinition,
    MetricKind,
    MetricSource,
)


def _model(source: MetricSource) -> Any:
    return MODELS[source.model]


def _base_filters(source: MetricSource, tenant_id: str) -> list:
    """Tenant scope plus the definition's constant predicates. Never bypassed."""
    model = _model(source)
    filters = [model.tenant_id == tenant_id]
    for column, value in source.filters.items():
        filters.append(getattr(model, column) == value)
    return filters


def _period_predicate(metric: MetricDefinition, period: Period):
    """The condition under which a row contributes to `period`."""
    source = metric.source
    model = _model(source)

    if metric.kind in (MetricKind.POINT_IN_TIME_SUM, MetricKind.POINT_IN_TIME_COUNT):
        start = getattr(model, source.interval_start)
        end = getattr(model, source.interval_end) if source.interval_end else None

        if metric.evaluate_at is EvaluateAt.OVERLAP:
            began = start < period.end
            not_yet_ended = (
                or_(end.is_(None), end >= period.start) if end is not None else True
            )
            return began & not_yet_ended

        # Stock measures are read at an instant. `period.end` is exclusive, so the last
        # day inside the period is one day earlier.
        as_of = (
            period.start
            if metric.evaluate_at is EvaluateAt.PERIOD_START
            else period.end - datetime.timedelta(days=1)
        )
        began = start <= as_of
        still_open = or_(end.is_(None), end >= as_of) if end is not None else True
        return began & still_open

    # Instant kinds: the row's timestamp falls inside the half-open period.
    stamp = getattr(model, source.timestamp_column)
    return (stamp >= period.start) & (stamp < period.end)


def _aggregate(metric: MetricDefinition, period: Period):
    """A single conditional aggregate producing this metric's value for one period."""
    source = metric.source
    model = _model(source)
    predicate = _period_predicate(metric, period)

    if metric.kind is MetricKind.POINT_IN_TIME_SUM:
        value = getattr(model, source.value_column)
        return func.coalesce(func.sum(case((predicate, value), else_=0.0)), 0.0)

    if metric.kind in (MetricKind.POINT_IN_TIME_COUNT, MetricKind.ROW_COUNT):
        return func.count(case((predicate, model.id)))

    if metric.kind is MetricKind.DISTINCT_COUNT:
        column = getattr(model, source.distinct_column)
        return func.count(func.distinct(case((predicate, column))))

    raise ValueError(f"{metric.kind} has no aggregate form")


def _entity_filter(source: MetricSource, customer_ids: list[str] | None):
    """Restrict a query to a set of customers, used for segment comparisons."""
    if customer_ids is None:
        return None
    if not customer_ids:
        # An empty segment must yield zero, not "no filter at all".
        return false()
    model = _model(source)
    return getattr(model, source.entity_column).in_(customer_ids)


def _series_query(
    metric: MetricDefinition,
    tenant_id: str,
    periods: list[Period],
    customer_ids: list[str] | None = None,
) -> Select:
    source = metric.source
    columns = [_aggregate(metric, p).label(f"p{i}") for i, p in enumerate(periods)]
    filters = _base_filters(source, tenant_id)
    entity = _entity_filter(source, customer_ids)
    if entity is not None:
        filters.append(entity)
    return select(*columns).where(*filters)


def compute_series(
    db: Session,
    metric_name: str,
    tenant_id: str,
    periods: list[Period],
    customer_ids: list[str] | None = None,
) -> list[float]:
    """Return one value per period for a metric, in period order.

    Derived and ratio metrics resolve through their components, so ARR can never drift
    from MRR and churn can never disagree with its own numerator.
    """
    metric = registry.get(metric_name)

    if metric.kind is MetricKind.DERIVED:
        base = registry.resolve_base(metric)
        factor = registry.derived_factor(metric)
        values = compute_series(db, base.name, tenant_id, periods, customer_ids)
        return [v * factor for v in values]

    if metric.kind is MetricKind.RATIO:
        numerators = compute_series(
            db, metric.numerator, tenant_id, periods, customer_ids
        )
        denominators = compute_series(
            db, metric.denominator, tenant_id, periods, customer_ids
        )
        return [
            round(n / d, metric.precision) if d else 0.0
            for n, d in zip(numerators, denominators, strict=True)
        ]

    if not periods:
        return []

    row = db.execute(_series_query(metric, tenant_id, periods, customer_ids)).one()
    return [float(value or 0) for value in row]


def compute_value(
    db: Session,
    metric_name: str,
    tenant_id: str,
    period: Period,
    customer_ids: list[str] | None = None,
) -> float:
    """A metric's value for a single period."""
    return compute_series(db, metric_name, tenant_id, [period], customer_ids)[0]


def format_value(metric: MetricDefinition, value: float) -> float:
    """Round according to the metric's unit: currency to cents, counts to integers."""
    if metric.unit == "count":
        return round(value)
    if metric.unit == "ratio":
        return round(value, metric.precision)
    return round(value, 2)
