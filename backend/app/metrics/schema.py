"""The metric definition format.

A metric is declared once, as data, and everything downstream is derived from it:
the Anthropic tool schema the model sees, the argument validation, the SQL, and the
RBAC scope. Before this, the semantics lived in hand-written SQL in one module and the
tool schema lived in a hand-maintained list in another, with nothing keeping them in
step — which is how ``granularity`` became a documented parameter no handler read, and
how three different definitions of MRR ended up in the same file.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from app.db.models import Customer, Invoice, Subscription, UsageEvent

# Definitions may only reference models named here. This is a security boundary as much
# as a convenience: a definition file cannot point the compiler at an arbitrary table.
MODELS = {
    "subscription": Subscription,
    "customer": Customer,
    "usage_event": UsageEvent,
    "invoice": Invoice,
}

# Role ordering for `minimum_role`. A role can use every metric at or below its rank.
ROLE_RANK = {"viewer": 0, "analyst": 1, "admin": 2}


class MetricKind(StrEnum):
    #: Sum a value over rows whose validity interval overlaps the period (e.g. MRR).
    POINT_IN_TIME_SUM = "point_in_time_sum"
    #: Count rows whose validity interval overlaps the period (e.g. active subscriptions).
    POINT_IN_TIME_COUNT = "point_in_time_count"
    #: Count distinct values of a column among rows timestamped inside the period.
    DISTINCT_COUNT = "distinct_count"
    #: Count rows timestamped inside the period (e.g. new signups).
    ROW_COUNT = "row_count"
    #: Another metric scaled by a constant factor (e.g. ARR = 12 x MRR).
    DERIVED = "derived"
    #: The quotient of two other declared metrics (e.g. churn rate).
    RATIO = "ratio"


class QueryShape(StrEnum):
    TREND = "trend"  # a value per period across a range
    SNAPSHOT = "snapshot"  # a single value for one period
    COMPARE = "compare"  # a snapshot per customer segment


class EvaluateAt(StrEnum):
    """When an interval metric is measured.

    MRR and subscription counts are *stock* measures: they have a value at an instant,
    not over a span. The industry convention is to report them as of the close of the
    period ("MRR as of month end"), which is why that is the default — a subscription
    that churns mid-March does not appear in March's MRR.
    """

    #: Measured on the last day of the period. The default for stock metrics.
    PERIOD_END = "period_end"
    #: Measured on the first day of the period — the population at risk, for churn.
    PERIOD_START = "period_start"
    #: Counts if valid at any point during the period. Rarely what you want for a stock.
    OVERLAP = "overlap"


class MetricSource(BaseModel):
    """Where a metric's numbers come from."""

    model: str
    value_column: str | None = None
    #: For interval kinds: the columns bounding each row's validity.
    interval_start: str | None = None
    interval_end: str | None = None
    #: For instant kinds: the column that places each row in time.
    timestamp_column: str | None = None
    #: For DISTINCT_COUNT: the column whose distinct values are counted.
    distinct_column: str | None = None
    #: Column linking this model to a Customer, used for segment comparisons.
    entity_column: str = "customer_id"
    #: Constant equality predicates applied to every query, e.g. {"status": "canceled"}.
    filters: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def known_model_and_columns(self) -> "MetricSource":
        if self.model not in MODELS:
            raise ValueError(f"unknown model {self.model!r}; allowed: {sorted(MODELS)}")
        target = MODELS[self.model]
        referenced = [
            self.value_column,
            self.interval_start,
            self.interval_end,
            self.timestamp_column,
            self.distinct_column,
            self.entity_column,
            *self.filters,
        ]
        for column in filter(None, referenced):
            if not hasattr(target, column):
                raise ValueError(f"{self.model} has no column {column!r}")
        return self


class MetricDefinition(BaseModel):
    """One declared metric. This is the schema every YAML file is validated against."""

    name: str
    label: str
    description: str
    kind: MetricKind
    unit: str = "count"
    minimum_role: str = "viewer"
    supports: list[QueryShape] = Field(default_factory=list)
    evaluate_at: EvaluateAt = EvaluateAt.PERIOD_END

    source: MetricSource | None = None

    # DERIVED
    base: str | None = None
    factor: float | None = None

    # RATIO
    numerator: str | None = None
    denominator: str | None = None
    #: Ratios are rounded to this many decimal places.
    precision: int = 4

    @model_validator(mode="after")
    def required_fields_for_kind(self) -> "MetricDefinition":
        if self.minimum_role not in ROLE_RANK:
            raise ValueError(
                f"unknown minimum_role {self.minimum_role!r}; "
                f"allowed: {sorted(ROLE_RANK)}"
            )

        kind = self.kind

        if kind is MetricKind.DERIVED:
            if not self.base or self.factor is None:
                raise ValueError("derived metrics require 'base' and 'factor'")
            return self

        if kind is MetricKind.RATIO:
            if not self.numerator or not self.denominator:
                raise ValueError("ratio metrics require 'numerator' and 'denominator'")
            return self

        if self.source is None:
            raise ValueError(f"{kind.value} metrics require a 'source'")

        required = {
            MetricKind.POINT_IN_TIME_SUM: ["value_column", "interval_start"],
            MetricKind.POINT_IN_TIME_COUNT: ["interval_start"],
            MetricKind.DISTINCT_COUNT: ["timestamp_column", "distinct_column"],
            MetricKind.ROW_COUNT: ["timestamp_column"],
        }[kind]

        for field in required:
            if getattr(self.source, field) is None:
                raise ValueError(f"{kind.value} metrics require source.{field}")

        return self

    def allowed_for(self, role: str) -> bool:
        return ROLE_RANK.get(role, -1) >= ROLE_RANK[self.minimum_role]

    def supports_shape(self, shape: QueryShape) -> bool:
        return shape in self.supports
