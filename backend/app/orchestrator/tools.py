TOOLS = [
    {
        "name": "get_metric_trend",
        "description": "Return a time series for one SaaS metric over a date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["mrr", "arr", "active_users", "new_signups"],
                },
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
                "granularity": {"type": "string", "enum": ["day", "week", "month"]},
            },
            "required": ["metric", "start_date", "end_date", "granularity"],
        },
    },
    {
        "name": "get_churn_rate",
        "description": "Return churn rate for a given period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["last_month", "last_quarter", "last_year"],
                }
            },
            "required": ["period"],
        },
    },
    {
        "name": "compare_segments",
        "description": "Compare a metric between two customer segments. Restricted to analyst/admin roles.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["mrr", "churn_rate", "active_users"],
                },
                "segment_a": {"type": "string"},
                "segment_b": {"type": "string"},
            },
            "required": ["metric", "segment_a", "segment_b"],
        },
    },
    {
        "name": "get_top_customers",
        "description": "List top customers by a metric. Restricted to analyst/admin roles.",
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
        "description": "List currently active billing/usage anomaly alerts. Admin only.",
        "input_schema": {"type": "object", "properties": {}},
    },
]
