import argparse
import json
from .db import SessionLocal, assert_migrated
from .auth import bootstrap_accounts
from .services.erp import ensure_scenario, snapshot
from .services.external_sources import seed_sources
from .scenarios import list_scenarios


def main():
    parser = argparse.ArgumentParser(description="Seed a synthetic scenario without replacing user changes")
    parser.add_argument("--scenario", default="baseline", choices=[s["id"] for s in list_scenarios()])
    args = parser.parse_args()
    assert_migrated()
    with SessionLocal() as db:
        ensure_scenario(db, args.scenario)
        db.commit()
        bootstrap_accounts(db)
        seed_sources(db)
        data = snapshot(db, args.scenario)
        print(json.dumps({"scenario": args.scenario, "revision": data["revision"], "is_synthetic": data.get("is_synthetic"), "materials": len(data["materials"]), "mode": "insert-if-missing; existing records preserved"}))


if __name__ == "__main__":
    main()
