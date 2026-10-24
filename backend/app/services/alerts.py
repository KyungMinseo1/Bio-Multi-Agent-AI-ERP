from sqlalchemy import select
from ..models import Alert
from ..config import planning_date
from .erp import snapshot
from .planning import evaluate


def recalculate(db, scenario_id):
    data = snapshot(db, scenario_id)
    result = evaluate(data, as_of=planning_date())
    active = set()
    for value in result.get("alerts", []):
        key = f"{value.get('material_id')}:{value.get('production_plan_id', '')}:{value.get('kind', 'reorder')}"
        active.add(key)
        row = db.scalar(select(Alert).where(Alert.scenario_id == scenario_id, Alert.scope_key == key))
        if row:
            row.data, row.status = value, value.get("status", "warning")
        else:
            row = Alert(scenario_id=scenario_id, scope_key=key, data=value, status=value.get("status", "warning"))
            db.add(row)
        db.flush()
        value["id"] = row.id
        value["acknowledgement"] = row.acknowledgement
    for row in db.scalars(select(Alert).where(Alert.scenario_id == scenario_id)):
        if row.scope_key not in active:
            row.status = "resolved"
    db.commit()
    return result
