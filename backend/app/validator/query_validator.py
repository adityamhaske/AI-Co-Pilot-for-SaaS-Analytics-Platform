from sqlalchemy.orm import Session
from app.db.models import Customer

def get_metric_trend_handler(db: Session, tenant_id: str, kwargs: dict) -> list:
    # Dummy implementation for tool
    return [{"date": "2024-01-01", "value": 100}]

def get_churn_rate_handler(db: Session, tenant_id: str, kwargs: dict) -> dict:
    return {"churn_rate": 0.05}

def compare_segments_handler(db: Session, tenant_id: str, kwargs: dict) -> dict:
    return {kwargs["segment_a"]: 100, kwargs["segment_b"]: 120}

def get_top_customers_handler(db: Session, tenant_id: str, kwargs: dict) -> list:
    limit = kwargs.get("limit", 5)
    # Filter strictly by tenant_id!
    customers = db.query(Customer).filter(Customer.tenant_id == tenant_id).limit(limit).all()
    return [{"id": c.id, "name": c.name} for c in customers]

def list_active_alerts_handler(db: Session, tenant_id: str, kwargs: dict) -> list:
    return [{"alert": "High usage spike detected"}]

TOOL_HANDLERS = {
    "get_metric_trend": get_metric_trend_handler,
    "get_churn_rate": get_churn_rate_handler,
    "compare_segments": compare_segments_handler,
    "get_top_customers": get_top_customers_handler,
    "list_active_alerts": list_active_alerts_handler,
}

def execute_tool(db: Session, tenant_id: str, tool_name: str, tool_kwargs: dict) -> any:
    if tool_name not in TOOL_HANDLERS:
        raise ValueError(f"Unknown tool: {tool_name}")
    return TOOL_HANDLERS[tool_name](db, tenant_id, tool_kwargs)
