import json
import os
from zoneinfo import ZoneInfo
from datetime import datetime


def setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def planning_date() -> str:
    return setting("PLANNING_AS_OF") or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def role_mapping() -> dict:
    try:
        value = json.loads(setting("LLM_ROLE_MAPPING", "{}"))
        return value if isinstance(value, dict) else {"__configuration_error__": "LLM_ROLE_MAPPING must be a JSON object"}
    except ValueError:
        return {"__configuration_error__": "LLM_ROLE_MAPPING contains invalid JSON"}


COLLECTIONS = (
    "materials", "suppliers", "supplier_materials", "lots", "reservations", "consumptions",
    "customer_orders", "production_plans", "requirements", "resource_calendars",
    "storage_capacities", "offers", "budgets", "purchase_orders", "issues",
)
