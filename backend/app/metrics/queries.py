"""Query shapes over the metric registry.

A shape is *how* you slice a metric — a series across periods, a single value, a
segment comparison. Shapes are generic: they work for any metric that declares support
for them, so adding a metric is adding a YAML file, not editing this module.
"""

import datetime
from typing import Literal

from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Customer
from app.metrics import compiler, registry
from app.metrics.periods import Granularity, build_periods, relative_period
from app.metrics.schema import QueryShape

RelativePeriod = Literal["last_month", "last_quarter", "last_year"]


def _require(metric_name: str, shape: QueryShape, role: str):
    """Resolve a metric, enforcing both the shape it supports and the caller's role."""
    metric = registry.get(metric_name)

    if not metric.allowed_for(role):
        raise ValueError(
            f"Metric {metric_name!r} requires the {metric.minimum_role} role."
        )
    if not metric.supports_shape(shape):
        available = registry.names_for(shape, role)
        raise ValueError(
            f"Metric {metric_name!r} does not support {shape.value} queries. "
            f"Available: {', '.join(available)}"
        )
    return metric


def _segment_customer_ids(db: Session, tenant_id: str, segment: str) -> list[str]:
    rows = db.execute(
        select(Customer.id).where(
            Customer.tenant_id == tenant_id, Customer.segment == segment
        )
    ).all()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Argument models
# ---------------------------------------------------------------------------


class TrendArgs(BaseModel):
    metric: str
    start_date: datetime.date
    end_date: datetime.date
    granularity: Granularity = "month"

    @model_validator(mode="after")
    def check_range(self) -> "TrendArgs":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be earlier than start_date")
        return self


class SnapshotArgs(BaseModel):
    metric: str
    period: RelativePeriod = "last_month"


class CompareArgs(BaseModel):
    metric: str
    segment_a: str
    segment_b: str
    period: RelativePeriod = "last_month"


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def trend(db: Session, tenant_id: str, role: str, args: TrendArgs) -> dict:
    metric = _require(args.metric, QueryShape.TREND, role)
    periods = build_periods(args.start_date, args.end_date, args.granularity)
    values = compiler.compute_series(db, metric.name, tenant_id, periods)

    return {
        "metric": metric.name,
        "label": metric.label,
        "unit": metric.unit,
        "granularity": args.granularity,
        "series": [
            {"date": period.label, "value": compiler.format_value(metric, value)}
            for period, value in zip(periods, values, strict=True)
        ],
    }


def snapshot(db: Session, tenant_id: str, role: str, args: SnapshotArgs) -> dict:
    metric = _require(args.metric, QueryShape.SNAPSHOT, role)
    period = relative_period(args.period)
    value = compiler.compute_value(db, metric.name, tenant_id, period)

    result = {
        "metric": metric.name,
        "label": metric.label,
        "unit": metric.unit,
        "period": args.period,
        "value": compiler.format_value(metric, value),
    }

    # For a ratio, show the terms as well: a bare "0.05" is not checkable, but
    # "3 of 60" is.
    if metric.numerator and metric.denominator:
        result["numerator"] = {
            "metric": metric.numerator,
            "value": compiler.compute_value(db, metric.numerator, tenant_id, period),
        }
        result["denominator"] = {
            "metric": metric.denominator,
            "value": compiler.compute_value(db, metric.denominator, tenant_id, period),
        }

    return result


def compare(db: Session, tenant_id: str, role: str, args: CompareArgs) -> dict:
    metric = _require(args.metric, QueryShape.COMPARE, role)
    period = relative_period(args.period)

    def side(segment: str) -> dict:
        ids = _segment_customer_ids(db, tenant_id, segment)
        value = compiler.compute_value(db, metric.name, tenant_id, period, ids)
        return {
            "name": segment,
            "value": compiler.format_value(metric, value),
            "customers": len(ids),
        }

    return {
        "metric": metric.name,
        "label": metric.label,
        "unit": metric.unit,
        "period": args.period,
        "segment_a": side(args.segment_a),
        "segment_b": side(args.segment_b),
    }


# ---------------------------------------------------------------------------
# Tool schemas, generated from the registry
# ---------------------------------------------------------------------------


def tool_schemas(role: str) -> list[dict]:
    """Anthropic tool definitions for a role.

    Generated, not hand-written: the metric enum and the glossary in each description
    come straight from the registry, so a metric can never be advertised to the model
    without an implementation, or implemented without being advertised.
    """
    schemas: list[dict] = []

    trend_metrics = registry.names_for(QueryShape.TREND, role)
    if trend_metrics:
        schemas.append(
            {
                "name": "get_metric_trend",
                "description": (
                    "Return a time series for one metric over a date range.\n"
                    "Available metrics:\n"
                    + registry.describe_for(QueryShape.TREND, role)
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "enum": trend_metrics},
                        "start_date": {"type": "string", "format": "date"},
                        "end_date": {"type": "string", "format": "date"},
                        "granularity": {
                            "type": "string",
                            "enum": ["day", "week", "month"],
                        },
                    },
                    "required": ["metric", "start_date", "end_date", "granularity"],
                },
            }
        )

    snapshot_metrics = registry.names_for(QueryShape.SNAPSHOT, role)
    if snapshot_metrics:
        schemas.append(
            {
                "name": "get_metric_value",
                "description": (
                    "Return a single value for one metric over a relative period.\n"
                    "Available metrics:\n"
                    + registry.describe_for(QueryShape.SNAPSHOT, role)
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "enum": snapshot_metrics},
                        "period": {
                            "type": "string",
                            "enum": ["last_month", "last_quarter", "last_year"],
                        },
                    },
                    "required": ["metric", "period"],
                },
            }
        )

    compare_metrics = registry.names_for(QueryShape.COMPARE, role)
    if compare_metrics:
        schemas.append(
            {
                "name": "compare_segments",
                "description": (
                    "Compare one metric between two customer segments "
                    "(e.g. enterprise, smb, midmarket).\n"
                    "Available metrics:\n"
                    + registry.describe_for(QueryShape.COMPARE, role)
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "enum": compare_metrics},
                        "segment_a": {"type": "string"},
                        "segment_b": {"type": "string"},
                        "period": {
                            "type": "string",
                            "enum": ["last_month", "last_quarter", "last_year"],
                        },
                    },
                    "required": ["metric", "segment_a", "segment_b"],
                },
            }
        )

    return schemas


HANDLERS = {
    "get_metric_trend": (TrendArgs, trend),
    "get_metric_value": (SnapshotArgs, snapshot),
    "compare_segments": (CompareArgs, compare),
}


def execute(db: Session, tenant_id: str, role: str, name: str, kwargs: dict) -> dict:
    """Validate arguments and run a registry-backed tool."""
    args_model, handler = HANDLERS[name]
    try:
        args = args_model.model_validate(kwargs)
    except Exception as exc:
        raise ValueError(f"Invalid arguments for {name}: {exc}") from exc
    return handler(db, tenant_id, role, args)
