"""Loads and indexes the metric definitions.

The registry is built once at import and validated eagerly: a malformed definition, an
unknown column, a dangling `base`/`numerator` reference or a dependency cycle raises at
startup rather than at the moment a user asks a question.
"""

import functools
from pathlib import Path

import yaml

from app.metrics.schema import MetricDefinition, MetricKind, QueryShape

DEFINITIONS_DIR = Path(__file__).parent / "definitions"


class MetricRegistryError(RuntimeError):
    """A definition file is invalid. Always fatal at startup."""


def _load_definitions(directory: Path) -> dict[str, MetricDefinition]:
    metrics: dict[str, MetricDefinition] = {}

    for path in sorted(directory.glob("*.yaml")):
        try:
            # Files may hold several documents, so building blocks can live beside the
            # metric that composes them.
            documents = [d for d in yaml.safe_load_all(path.read_text()) if d]
        except yaml.YAMLError as exc:
            raise MetricRegistryError(f"{path.name}: not valid YAML: {exc}") from exc

        for document in documents:
            try:
                metric = MetricDefinition.model_validate(document)
            except Exception as exc:
                raise MetricRegistryError(f"{path.name}: {exc}") from exc

            if metric.name in metrics:
                raise MetricRegistryError(
                    f"{path.name}: duplicate metric name {metric.name!r}"
                )
            metrics[metric.name] = metric

    if not metrics:
        raise MetricRegistryError(f"no metric definitions found in {directory}")

    _check_references(metrics)
    return metrics


def _check_references(metrics: dict[str, MetricDefinition]) -> None:
    """Every cross-metric reference must resolve, and must not cycle."""
    for metric in metrics.values():
        refs = [
            ("base", metric.base),
            ("numerator", metric.numerator),
            ("denominator", metric.denominator),
        ]
        for field, ref in refs:
            if ref and ref not in metrics:
                raise MetricRegistryError(
                    f"{metric.name}: {field} references unknown metric {ref!r}"
                )

    def walk(name: str, seen: tuple[str, ...]) -> None:
        if name in seen:
            trail = " -> ".join([*seen, name])
            raise MetricRegistryError(f"circular metric definition: {trail}")
        metric = metrics[name]
        for ref in (metric.base, metric.numerator, metric.denominator):
            if ref:
                walk(ref, (*seen, name))

    for name in metrics:
        walk(name, ())


@functools.lru_cache(maxsize=1)
def _registry() -> dict[str, MetricDefinition]:
    return _load_definitions(DEFINITIONS_DIR)


def get(name: str) -> MetricDefinition:
    try:
        return _registry()[name]
    except KeyError:
        raise ValueError(f"Unknown metric: {name!r}") from None


def all_metrics() -> dict[str, MetricDefinition]:
    return dict(_registry())


def resolve_base(metric: MetricDefinition) -> MetricDefinition:
    """Follow a derived metric down to the metric that actually carries a source."""
    seen = metric
    while seen.kind is MetricKind.DERIVED:
        seen = get(seen.base)
    return seen


def derived_factor(metric: MetricDefinition) -> float:
    """Product of the factors between a metric and its underlying source metric."""
    factor = 1.0
    seen = metric
    while seen.kind is MetricKind.DERIVED:
        factor *= seen.factor
        seen = get(seen.base)
    return factor


def names_for(shape: QueryShape, role: str) -> list[str]:
    """Metric names a role may use with a given query shape.

    This is what makes the tool schemas RBAC-aware: the model is only shown the metrics
    the caller is actually allowed to ask for.
    """
    return sorted(
        name
        for name, metric in _registry().items()
        if metric.supports_shape(shape) and metric.allowed_for(role)
    )


def describe_for(shape: QueryShape, role: str) -> str:
    """A compact metric glossary for the tool description the model reads."""
    lines = []
    for name in names_for(shape, role):
        metric = get(name)
        summary = " ".join(metric.description.split())
        lines.append(f"- {name} ({metric.unit}): {summary}")
    return "\n".join(lines)
