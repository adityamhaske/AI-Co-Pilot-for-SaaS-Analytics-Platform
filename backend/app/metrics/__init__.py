"""Declarative metric layer.

One YAML definition per metric drives everything: the tool schema the model sees, the
argument validation, the SQL, and the RBAC scope. See docs/architecture for the design,
and `definitions/` for the metrics themselves.
"""

from app.metrics import compiler, periods, queries, registry
from app.metrics.schema import MetricDefinition, MetricKind, QueryShape

__all__ = [
    "MetricDefinition",
    "MetricKind",
    "QueryShape",
    "compiler",
    "periods",
    "queries",
    "registry",
]
