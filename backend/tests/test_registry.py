"""Tests for the metric registry itself.

The registry's value is that a bad definition fails at startup rather than at the moment
a user asks a question, and that the tool schemas the model sees are generated from the
same definitions the SQL is compiled from. Both properties are asserted here.
"""

import textwrap

import pytest

from app.core.rbac import ROLE_PERMISSIONS
from app.metrics import registry
from app.metrics.registry import MetricRegistryError, _load_definitions
from app.metrics.schema import MetricDefinition, QueryShape
from app.orchestrator import tools as toolbox


def write_definitions(tmp_path, *documents: str):
    (tmp_path / "metrics.yaml").write_text(
        "\n---\n".join(textwrap.dedent(d).strip() for d in documents)
    )
    return tmp_path


VALID = """
    name: widgets
    label: Widgets
    description: A test metric counting customer rows by creation date.
    kind: row_count
    supports: [trend]
    source:
      model: customer
      timestamp_column: created_at
      entity_column: id
"""


# ---------------------------------------------------------------------------
# Loader validation
# ---------------------------------------------------------------------------


def test_valid_definition_loads(tmp_path):
    metrics = _load_definitions(write_definitions(tmp_path, VALID))
    assert set(metrics) == {"widgets"}


def test_unknown_model_is_rejected(tmp_path):
    bad = VALID.replace("model: customer", "model: secret_admin_table")
    with pytest.raises(MetricRegistryError, match="unknown model"):
        _load_definitions(write_definitions(tmp_path, bad))


def test_unknown_column_is_rejected(tmp_path):
    """A typo in a column name must fail at startup, not at query time."""
    bad = VALID.replace("timestamp_column: created_at", "timestamp_column: creatd_at")
    with pytest.raises(MetricRegistryError, match="no column"):
        _load_definitions(write_definitions(tmp_path, bad))


def test_missing_required_field_for_kind_is_rejected(tmp_path):
    bad = """
        name: broken
        label: Broken
        description: Missing the value column a sum needs.
        kind: point_in_time_sum
        supports: [trend]
        source:
          model: subscription
          interval_start: start_date
    """
    with pytest.raises(MetricRegistryError, match="value_column"):
        _load_definitions(write_definitions(tmp_path, bad))


def test_dangling_reference_is_rejected(tmp_path):
    dangling = """
        name: doubled
        label: Doubled
        description: Derived from a metric that does not exist.
        kind: derived
        supports: [trend]
        base: no_such_metric
        factor: 2
    """
    with pytest.raises(MetricRegistryError, match="unknown metric"):
        _load_definitions(write_definitions(tmp_path, VALID, dangling))


def test_circular_reference_is_rejected(tmp_path):
    a = """
        name: a
        label: A
        description: Cycles through b.
        kind: derived
        base: b
        factor: 2
    """
    b = """
        name: b
        label: B
        description: Cycles back to a.
        kind: derived
        base: a
        factor: 2
    """
    with pytest.raises(MetricRegistryError, match="circular"):
        _load_definitions(write_definitions(tmp_path, a, b))


def test_duplicate_names_are_rejected(tmp_path):
    with pytest.raises(MetricRegistryError, match="duplicate"):
        _load_definitions(write_definitions(tmp_path, VALID, VALID))


def test_unknown_minimum_role_is_rejected(tmp_path):
    bad = """
        name: widgets
        label: Widgets
        description: A test metric counting customer rows by creation date.
        kind: row_count
        minimum_role: superuser
        supports: [trend]
        source:
          model: customer
          timestamp_column: created_at
          entity_column: id
    """
    with pytest.raises(MetricRegistryError, match="minimum_role"):
        _load_definitions(write_definitions(tmp_path, bad))


def test_empty_directory_is_rejected(tmp_path):
    with pytest.raises(MetricRegistryError, match="no metric definitions"):
        _load_definitions(tmp_path)


# ---------------------------------------------------------------------------
# The shipped definitions
# ---------------------------------------------------------------------------


def test_shipped_definitions_all_load():
    metrics = registry.all_metrics()
    assert {"mrr", "arr", "active_users", "new_signups", "churn_rate"} <= set(metrics)


@pytest.mark.parametrize(
    "metric", registry.all_metrics().values(), ids=lambda m: m.name
)
def test_every_metric_has_a_usable_description(metric: MetricDefinition):
    """The description is what the model reads to pick a metric, so it must be real."""
    assert len(metric.description.split()) >= 8, metric.name
    assert metric.label


def test_arr_is_derived_from_mrr_not_redefined():
    arr = registry.get("arr")
    assert registry.resolve_base(arr).name == "mrr"
    assert registry.derived_factor(arr) == 12


# ---------------------------------------------------------------------------
# Generated tool schemas
# ---------------------------------------------------------------------------


def test_tool_schemas_are_generated_from_the_registry():
    schema = next(
        t for t in toolbox.schemas_for("admin") if t["name"] == "get_metric_trend"
    )
    enum = schema["input_schema"]["properties"]["metric"]["enum"]
    assert enum == registry.names_for(QueryShape.TREND, "admin")
    # The glossary the model reads is generated too.
    assert "mrr" in schema["description"]


def test_every_advertised_metric_is_computable():
    """Nothing may appear in a tool enum without a definition behind it.

    This is the invariant that a hand-maintained tool list could not hold: `granularity`
    was advertised to the model and silently ignored by every handler.
    """
    for role in ("viewer", "analyst", "admin"):
        for tool in toolbox.schemas_for(role):
            enum = tool["input_schema"]["properties"].get("metric", {}).get("enum", [])
            for name in enum:
                metric = registry.get(name)  # raises if undefined
                assert metric.allowed_for(role)


def test_every_advertised_tool_has_a_handler():
    from app.metrics.queries import HANDLERS
    from app.orchestrator.bespoke_tools import BESPOKE_HANDLERS

    known = set(HANDLERS) | set(BESPOKE_HANDLERS)
    for role in ("viewer", "analyst", "admin"):
        for tool in toolbox.schemas_for(role):
            assert tool["name"] in known


def test_rbac_matrix_references_only_real_tools():
    """A typo in the RBAC matrix would silently hide a tool from every role."""
    from app.metrics.queries import HANDLERS
    from app.orchestrator.bespoke_tools import BESPOKE_HANDLERS

    known = set(HANDLERS) | set(BESPOKE_HANDLERS)
    for role, permissions in ROLE_PERMISSIONS.items():
        for tool_name in permissions["tools"]:
            assert tool_name in known, f"{role} grants unknown tool {tool_name}"


# ---------------------------------------------------------------------------
# Role scoping
# ---------------------------------------------------------------------------


def test_viewer_sees_fewer_tools_than_admin():
    viewer = {t["name"] for t in toolbox.schemas_for("viewer")}
    admin = {t["name"] for t in toolbox.schemas_for("admin")}
    assert viewer < admin
    assert "list_active_alerts" in admin
    assert "list_active_alerts" not in viewer


def test_unknown_role_gets_no_tools():
    assert toolbox.schemas_for("intern") == []
