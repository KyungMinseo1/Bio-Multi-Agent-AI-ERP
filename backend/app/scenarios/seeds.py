"""Synthetic prices, dates and qualifications, not clinical manufacturing advice."""
from uuid import NAMESPACE_URL, uuid5


def uid(code):
    return str(uuid5(NAMESPACE_URL, "bio-erp/synthetic/" + code))


def record(code, **values):
    return {"id": uid(code), "code": code, "name": values.pop("name", code), "revision": 1,
            "is_synthetic": True, **values}


def empty():
    return {"as_of": "2026-10-24", "revision": 1, "is_synthetic": True,
            **{key: [] for key in ("materials", "lots", "production_plans", "requirements", "suppliers",
                "offers", "resource_calendars", "storage_capacities", "budgets", "purchase_orders",
                "issues", "reservations", "consumptions", "supplier_materials", "customer_orders")}}


def scenario_one(qc_bottleneck=False):
    data = empty()
    il7 = record("MAT-IL7", name="재조합 인간 IL-7", base_unit="vial", safety_stock="2",
        storage_condition="frozen", space_per_unit="0.01", review_days=2, planning_horizon_days=37,
        daily_usage_fallback="0", manufacturer="합성 제조사 CellFactor", product_code="SYN-IL7-10UG",
        formulation="동결건조·미개봉", content_per_vial="10 ug", grade="합성 공정개발 등급",
        unit_conversions={"vial": "1"}, approval_evidence="SYN-QUAL-IL7-001",
        unopened_storage="-20°C", reconstituted_policy="생산별 승인 후 즉시 사용; 잔여 재사용 금지")
    il15 = record("MAT-IL15", name="재조합 인간 IL-15", base_unit="vial", safety_stock="2",
        storage_condition="frozen", space_per_unit="0.01", review_days=2, planning_horizon_days=37,
        daily_usage_fallback="0", manufacturer="합성 제조사 CellFactor", product_code="SYN-IL15-10UG",
        formulation="동결건조·미개봉", content_per_vial="10 ug", grade="합성 공정개발 등급",
        unit_conversions={"vial": "1"}, approval_evidence="SYN-QUAL-IL15-001")
    for material in (il7, il15):
        material["provenance"] = "합성 프로토타입 SKU·함량·온도·승인 가정. 공식 제품 규격/임상 적합성 검증 아님."
    data["materials"] = [il7, il15]
    for number, (qc, qa, expiry) in enumerate([("passed", "approved", "2027-03-31"),
                ("pending", "pending", "2027-03-31"), ("passed", "approved", "2026-10-31")], 1):
        data["lots"].append(record(f"IL7-LOT-0{number}", material_id=il7["id"], quantity="2",
            consumed_quantity="0", qc_status=qc, qa_status=qa, expiry_date=expiry,
            storage_condition="frozen", temperature_status="passed", coa_ref=f"SYN-COA-IL7-{number}",
            hold_reason="문서 검토 미완료" if number == 2 else None,
            release_condition="QC 시험 결과 및 QA 서명 필요" if number == 2 else None))
    data["lots"].append(record("IL15-LOT-01", material_id=il15["id"], quantity="20", consumed_quantity="0",
        qc_status="passed", qa_status="approved", expiry_date="2027-03-31", storage_condition="frozen",
        temperature_status="passed", coa_ref="SYN-COA-IL15-1"))
    for number, day in enumerate((4, 11, 18), 1):
        plan = record(f"PROD-0{number}", name=f"T세포 파일럿 생산 {number}",
            customer_delivery_date=f"2026-11-{day + 9:02d}", production_days=4, finished_testing_days=2,
            packaging_days=1, shipping_days=1, customer_transport_days=1, line_id="CELL-PILOT-1")
        data["production_plans"].append(plan)
        data["customer_orders"].append(record(f"CUSTOMER-0{number}", production_plan_id=plan["id"],
            delivery_date=plan["customer_delivery_date"], quantity="1", product="합성 T세포 파일럿"))
        for material in (il7, il15):
            data["requirements"].append(record(f"REQ-{material['code']}-{number}", material_id=material["id"],
                production_plan_id=plan["id"], use_date=f"2026-11-{day:02d}", quantity="4", unit="vial"))
        data["budgets"].append(record(f"BUDGET-IL7-{number}", material_id=il7["id"],
            production_plan_id=plan["id"], approved_amount="4000000", committed_amount="0"))
    data["budgets"].append(record("BUDGET-IL7-SAFETY", material_id=il7["id"],
        allocation="safety_stock", approved_amount="1000000", committed_amount="0"))
    for label, price, moq, confirmed, expiry in [("A", "800000", "20", True, "2026-11-30"),
                ("B", "1000000", "4", True, "2027-03-31"), ("C", "700000", "4", False, "2027-03-31")]:
        supplier = record(f"SUP-{label}", name=f"가상 공급업체 {label}", approved=True,
            official_aliases=[f"Synthetic supplier {label}"], approval_evidence=f"SYN-SUP-QUAL-{label}")
        data["suppliers"].append(supplier)
        data["supplier_materials"].append(record(f"QUAL-{label}-IL7", supplier_id=supplier["id"],
            material_id=il7["id"], approved=True, approval_evidence=f"SYN-PRODUCT-QUAL-{label}"))
        deliveries = [{"quantity": "4" if label == "B" else moq,
            "arrival_date": date, "expiry_date": expiry, "confirmed": confirmed,
            "lot_code": f"SYN-{label}-{index}", "temperature_status": "passed",
            "evidence_ref": f"SYN-SHIPMENT-{label}-{index}" if confirmed else None}
            for index, date in enumerate(("2026-10-30", "2026-11-06", "2026-11-13") if label == "B" else ("2026-10-30",), 1)]
        data["offers"].append(record(f"OFFER-{label}-IL7", name=f"{label} {'3회 분할입고' if label == 'B' else '단일 입고'}",
            material_id=il7["id"], supplier_id=supplier["id"], approved=True, product_approved=True,
            unit_price=price, moq=moq, order_multiple=moq, available_quantity="40", valid_until="2026-10-27",
            preparation_days=3, transport_days=2, receiving_days=1, qc_days=2, qa_days=1,
            confirmed=confirmed, performance_count=12 if confirmed else 0,
            delay_samples=[0, 0, 0] if confirmed else [], allow_split=label == "B",
            max_deliveries=3 if label == "B" else 1, deliveries=deliveries,
            transport_cost="100000", testing_cost="100000", storage_cost_per_unit_day="100",
            disposal_cost_per_unit="10000", payment_days=0, shelf_life_days=150,
            storage_condition="frozen", change_terms="미출하 회차 변경은 공급자 서면 재확약 필요",
            confirmation_evidence=f"SYN-CONTRACT-{label}" if confirmed else None))
    data["supplier_materials"].append(record("QUAL-A-IL15", supplier_id=data["suppliers"][0]["id"],
        material_id=il15["id"], approved=True, approval_evidence="SYN-PRODUCT-QUAL-A-IL15"))
    data["offers"].append(record("OFFER-A-IL15", material_id=il15["id"], supplier_id=data["suppliers"][0]["id"],
        approved=True, product_approved=True, unit_price="900000", moq="4", order_multiple="4",
        available_quantity="40", valid_until="2026-10-27", preparation_days=3, transport_days=2, receiving_days=1,
        qc_days=2, qa_days=1, confirmed=True, performance_count=12, allow_split=False, max_deliveries=1,
        transport_cost="100000", testing_cost="100000", storage_cost_per_unit_day="100",
        disposal_cost_per_unit="10000", payment_days=0, shelf_life_days=150, storage_condition="frozen", deliveries=[]))
    data["storage_capacities"].append(record("STORE-FROZEN", storage_condition="frozen", capacity="2", unit="L"))
    data["resource_calendars"].append(record("QC-DEFAULT", resource_type="qc", capacity="4"))
    data["resource_calendars"].append(record("LINE-DEFAULT", resource_type="production", line_id="CELL-PILOT-1", capacity="1"))
    if qc_bottleneck:
        for day in (6, 7, 8):
            data["resource_calendars"].append(record(f"QC-BLOCK-NOV-{day}", resource_type="qc",
                date=f"2026-11-{day:02d}", capacity="0", reserved="0"))
    for index, payment_date in enumerate(("2026-10-30", "2026-11-06", "2026-11-13")):
        data["budgets"].append(record(f"CASH-IL7-{index}", material_id=il7["id"], payment_date=payment_date,
            cash_limit="20000000", approved_amount="0", committed_amount="0"))
    return data


def baseline():
    data = empty()
    configurations = [("CHO-MEDIUM", "CHO 무혈청 배지", "L", "refrigerated", "8", "25", "1"),
        ("GLUTAMINE", "L-글루타민 보충제", "vial", "frozen", "4", "8", "0.1"),
        ("BUFFER", "공정 완충액", "L", "ambient", "5", "60", "1")]
    for code, name, unit, storage, safety, quantity, space in configurations:
        material = record(f"BASE-{code}", name=name, base_unit=unit, storage_condition=storage,
            safety_stock=safety, review_days=3, planning_horizon_days=45, space_per_unit=space,
            daily_usage_fallback="0", unit_conversions={unit: "1"}, product_code=f"SYN-{code}")
        data["materials"].append(material)
        data["lots"].append(record(f"BASE-LOT-{code}", material_id=material["id"], quantity=quantity,
            consumed_quantity="0", qc_status="passed", qa_status="approved", expiry_date="2027-06-30",
            storage_condition=storage, temperature_status="passed"))
        data["storage_capacities"].append(record(f"BASE-STORE-{storage}", storage_condition=storage,
            capacity="55" if storage == "refrigerated" else "200", unit="L"))
        data["budgets"].append(record(f"BASE-BUDGET-{code}", material_id=material["id"],
            approved_amount="2500000", committed_amount="0"))
        data["budgets"].append(record(f"BASE-CASH-{code}", material_id=material["id"], payment_date="2026-10-31",
            cash_limit="10000000", approved_amount="0", committed_amount="0"))
        data["budgets"].append(record(f"BASE-CASH-SECOND-{code}", material_id=material["id"], payment_date="2026-11-07",
            cash_limit="10000000", approved_amount="0", committed_amount="0"))
    for index, day in enumerate((5, 12, 19), 1):
        plan = record(f"BASE-PROD-{index}", name=f"CHO 파일럿 배양 {index}", customer_delivery_date=f"2026-11-{day + 8:02d}",
            production_days=3, finished_testing_days=2, packaging_days=1, shipping_days=1,
            customer_transport_days=1, line_id="CHO-1")
        data["production_plans"].append(plan)
        for material, quantity in zip(data["materials"], ("20", "4", "10")):
            data["requirements"].append(record(f"BASE-REQ-{index}-{material['code']}", material_id=material["id"],
                production_plan_id=plan["id"], quantity=quantity, use_date=f"2026-11-{day:02d}", unit=material["base_unit"]))
    for index in range(4):
        supplier = record(f"BASE-SUP-{index}", name=f"가상 CHO 공급업체 {index + 1}", approved=index != 3,
            official_aliases=[f"Synthetic CHO {index + 1}"])
        data["suppliers"].append(supplier)
        for material in data["materials"]:
            data["supplier_materials"].append(record(f"BASE-QUAL-{index}-{material['code']}", material_id=material["id"],
                supplier_id=supplier["id"], approved=index != 3))
            data["offers"].append(record(f"BASE-OFFER-{index}-{material['code']}", material_id=material["id"],
                supplier_id=supplier["id"], approved=True, product_approved=index != 3,
                unit_price=str((index + 1) * 10000 if index != 3 else 1000), moq="10", order_multiple="5",
                available_quantity="200", valid_until="2026-11-01", preparation_days=3, transport_days=2,
                receiving_days=2, qc_days=2, qa_days=1, confirmed=index in (0, 1),
                performance_count=8 if index in (0, 1) else 0, allow_split=index == 1, max_deliveries=2,
                transport_cost="50000", testing_cost="30000", storage_cost_per_unit_day="10",
                disposal_cost_per_unit="1000", payment_days=0, shelf_life_days=90,
                storage_condition=material["storage_condition"], deliveries=[]))
    data["resource_calendars"] = [record("BASE-QC", resource_type="qc", capacity="8"),
        record("BASE-LINE", resource_type="production", line_id="CHO-1", capacity="1")]
    data["lots"].append(record("BASE-HOLD", material_id=data["materials"][0]["id"], quantity="5", consumed_quantity="0",
        qc_status="pending", qa_status="pending", expiry_date="2026-10-20", storage_condition="refrigerated",
        temperature_status="passed", hold_reason="만료 및 QA 미승인"))
    lot = data["lots"][0]
    data["reservations"].append(record("BASE-RESERVE", lot_id=lot["id"], production_plan_id=data["production_plans"][0]["id"], quantity="5"))
    data["consumptions"].append(record("BASE-CONSUMED", lot_id=lot["id"], quantity="2", consumed_at="2026-10-23"))
    data["purchase_orders"].append(record("BASE-EXISTING-PO", material_id=data["materials"][1]["id"], status="approved",
        deliveries=[{"id": uid("BASE-EXISTING-DELIVERY"), "quantity": "4", "arrival_date": "2026-10-29",
            "available_date": "2026-11-01", "expiry_date": "2027-05-01", "confirmed": True}]))
    data["issues"].append(record("BASE-UNVERIFIED", source_kind="synthetic", verification_status="relevance_unconfirmed",
        summary="동일 원료명 합성 공지: 당사 납품분 관련성 미확인", supplier_id=data["suppliers"][2]["id"]))
    data["issues"].append(record("BASE-QUALITY", source_kind="synthetic", verification_status="quality_impact_confirmed",
        summary="합성 승인문서상 해당 제품 공급 품질 문제 확인", supplier_id=data["suppliers"][3]["id"],
        material_id=data["materials"][0]["id"], evidence="SYN-QUALITY-CONFIRM-001"))
    return data
