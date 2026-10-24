import json
import os
from zoneinfo import ZoneInfo
from datetime import datetime

CANONICAL_ROLES = ("purchasing", "inventory_planning", "quality", "finance", "admin")
MAX_REVIEW_ROUNDS = 5


def validate_review_rounds(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"LLM_REVIEW_ROUNDS must be an integer from 1 to {MAX_REVIEW_ROUNDS}")
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or not 1 <= int(text) <= MAX_REVIEW_ROUNDS:
        raise ValueError(f"LLM_REVIEW_ROUNDS must be an integer from 1 to {MAX_REVIEW_ROUNDS}")
    return int(text)


def review_rounds() -> int:
    return validate_review_rounds(setting("LLM_REVIEW_ROUNDS", "1"))



def setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def planning_date() -> str:
    return setting("PLANNING_AS_OF") or datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def role_mapping() -> dict:
    try:
        value = json.loads(setting("LLM_ROLE_MAPPING", "{}"))
        if not isinstance(value, dict):
            return {"__configuration_error__": "LLM_ROLE_MAPPING must be a JSON object"}
        unknown = set(value) - set(CANONICAL_ROLES)
        if unknown:
            return {"__configuration_error__": "Unknown LLM_ROLE_MAPPING roles: " + ", ".join(sorted(unknown))}
        return value
    except ValueError:
        return {"__configuration_error__": "LLM_ROLE_MAPPING contains invalid JSON"}


COLLECTIONS = (
    "materials", "suppliers", "supplier_materials", "lots", "reservations", "consumptions",
    "customer_orders", "production_plans", "requirements", "resource_calendars",
    "storage_capacities", "offers", "budgets", "purchase_orders", "issues",
)
