"""The tool surface exposed to the model.

Two sources feed this:

* **Registry-backed tools** — ``get_metric_trend``, ``get_metric_value``,
  ``compare_segments``. Their schemas are *generated* from the metric definitions in
  ``app/metrics/definitions``, so the metric enum the model sees can never drift from
  what the code can actually compute. This list used to be maintained by hand alongside
  the SQL, which is how ``granularity`` became a documented parameter no handler read.
* **Bespoke tools** — ``get_top_customers``, ``list_active_alerts``. These are rankings
  and heuristics rather than metric readings, and still carry hand-written SQL.

Both layers are role-filtered before the model sees them.
"""

from sqlalchemy.orm import Session

from app.core.rbac import check_tool_access
from app.metrics import queries
from app.orchestrator.bespoke_tools import BESPOKE_HANDLERS
from app.providers import ToolSpec

# Tools whose schema is hand-written because they are not a metric reading.
BESPOKE_TOOLS = [
    {
        "name": "get_top_customers",
        "description": (
            "Rank customers by current MRR or by usage-event volume. "
            "Returns customer names, so it is restricted to analyst and admin roles."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sort_by": {"type": "string", "enum": ["mrr", "usage"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "required": ["sort_by", "limit"],
        },
    },
    {
        "name": "list_active_alerts",
        "description": (
            "List currently active billing and usage anomaly alerts. Admin only."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def schemas_for(role: str) -> list[dict]:
    """Every tool this role may use, with schemas generated where possible."""
    tools = [
        t for t in queries.tool_schemas(role) if check_tool_access(role, t["name"])
    ]
    tools.extend(t for t in BESPOKE_TOOLS if check_tool_access(role, t["name"]))
    return tools


def specs_for(role: str) -> list[ToolSpec]:
    """The same tools as provider-neutral specs.

    `input_schema` is Anthropic's key name for the argument schema; ToolSpec calls it
    `parameters`, so no adapter needs to know which vendor the schema was written for.
    """
    return [
        ToolSpec(
            name=tool["name"],
            description=tool["description"],
            parameters=tool["input_schema"],
        )
        for tool in schemas_for(role)
    ]


def execute(db: Session, tenant_id: str, role: str, name: str, kwargs: dict):
    """Run a tool by name. Raises ValueError for an unknown or malformed call."""
    if name in queries.HANDLERS:
        return queries.execute(db, tenant_id, role, name, kwargs)
    if name in BESPOKE_HANDLERS:
        return BESPOKE_HANDLERS[name](db, tenant_id, kwargs)
    raise ValueError(f"Unknown tool: {name}")
