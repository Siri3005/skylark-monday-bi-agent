"""
JSON schemas for all agent tools.
The LLM sees these schemas to decide which tool to call and with what parameters.
"""

TOOL_SCHEMAS = [
    {
        "name": "get_deals",
        "description": (
            "Fetch deal records from the Monday.com Deals board (live, dynamic query). "
            "Returns normalized deal records with pipeline values, sectors, stages, statuses. "
            "Use for any question about deals, pipeline, funnel, or deal counts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by Deal Status. Valid values: 'Open', 'Won', 'Dead', 'On Hold'. Leave empty for all.",
                },
                "sector_filter": {
                    "type": "string",
                    "description": "Filter by sector (e.g. 'Mining', 'Renewables', 'Railways'). Leave empty for all sectors.",
                },
                "date_from": {
                    "type": "string",
                    "description": "ISO date YYYY-MM-DD. Filter deals with tentative close date >= this.",
                },
                "date_to": {
                    "type": "string",
                    "description": "ISO date YYYY-MM-DD. Filter deals with tentative close date <= this.",
                },
                "date_field": {
                    "type": "string",
                    "enum": ["tentative_close_date", "close_date", "created_date"],
                    "description": "Which date field to apply the date filter on.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_work_orders",
        "description": (
            "Fetch work order records from the Monday.com Work Orders board (live, dynamic). "
            "Returns normalized WO records with execution status, billing, sector, financials. "
            "Use for questions about work orders, execution, billing, or operational status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by Execution Status (e.g. 'Ongoing', 'Completed', 'Not Started').",
                },
                "sector_filter": {
                    "type": "string",
                    "description": "Filter by sector (e.g. 'Mining', 'Renewables').",
                },
            },
            "required": [],
        },
    },
    {
        "name": "calculate_pipeline",
        "description": (
            "Calculate open pipeline value and deal counts from the Deals board. "
            "Returns total pipeline value, breakdown by sector and stage, at-risk deals. "
            "All arithmetic is done in Python — never by the LLM."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sector": {
                    "type": "string",
                    "description": "Filter to a specific sector.",
                },
                "stage": {
                    "type": "string",
                    "description": "Filter to a specific deal stage substring.",
                },
                "period": {
                    "type": "string",
                    "enum": ["this_quarter", "last_quarter", "this_month"],
                    "description": "Filter by tentative close date period. Calendar quarters (Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec).",
                },
                "weighted": {
                    "type": "boolean",
                    "description": "Apply probability weighting: High=75%, Med=50%, Low=25%. Stated assumption.",
                    "default": False,
                },
                "status": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Deal statuses to include. Default: ['Open', 'On Hold'].",
                },
            },
            "required": [],
        },
    },
    {
        "name": "calculate_revenue",
        "description": (
            "Calculate revenue. YOU MUST SPECIFY the basis parameter — 'revenue' is ambiguous. "
            "basis='deal_value': sum of Won deal values (Deals board). "
            "basis='billed': sum of Billed Value incl GST (Work Orders board). "
            "basis='collected': sum of Collected Amount incl GST (Work Orders board). "
            "If user didn't specify, ask them first before calling this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "basis": {
                    "type": "string",
                    "enum": ["deal_value", "billed", "collected"],
                    "description": "REQUIRED. The revenue basis: deal_value, billed, or collected.",
                },
                "sector": {"type": "string"},
                "period": {
                    "type": "string",
                    "enum": ["this_quarter", "last_quarter", "this_month"],
                },
            },
            "required": ["basis"],
        },
    },
    {
        "name": "calculate_operational_metrics",
        "description": (
            "Calculate operational metrics for Work Orders: active/completed counts, "
            "backlog, billing breakdown, financials. "
            "Note: 'Executed until current month' = ACTIVE recurring contracts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by specific execution status."},
                "sector": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "calculate_sector_performance",
        "description": (
            "Side-by-side comparison of Deals pipeline vs Work Orders execution for each sector. "
            "Join is at sector level only (reliable). Customer-level join not supported."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sector": {"type": "string", "description": "Focus on a specific sector, or omit for all."},
            },
            "required": [],
        },
    },
    {
        "name": "cross_board_metric",
        "description": (
            "Cross-board analysis at sector and owner/BD level. "
            "question_type options: 'pipeline_vs_execution', 'strong_sales_weak_ops', "
            "'owner_conversion', 'sector_overview'. "
            "Customer-level cross-board join is NOT supported — use 'customer_level' type "
            "to return the documented limitation message."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question_type": {
                    "type": "string",
                    "enum": ["pipeline_vs_execution", "strong_sales_weak_ops", "owner_conversion",
                             "sector_overview", "customer_level"],
                    "description": "Type of cross-board question.",
                },
                "sector": {"type": "string"},
            },
            "required": ["question_type"],
        },
    },
    {
        "name": "check_data_quality",
        "description": (
            "Return a data quality report: null counts, known data issues, "
            "board statistics, normalization applied."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "board": {
                    "type": "string",
                    "enum": ["deals", "work_orders"],
                    "description": "Which board to check. Omit for both.",
                },
            },
            "required": [],
        },
    },
]
