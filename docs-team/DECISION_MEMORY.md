# 실행 결과 추적 · 과거 의사결정 사례 검색

이 기능은 저장된 사례를 규칙으로 검색해 다음 검토에 제공한다. LLM 자동 학습·파인튜닝·가중치 업데이트를 수행하지 않는다. API에도 training_performed=false, advisory_only=true를 반환한다. 현재 승인·공급 확인·메일 작성/발송 흐름은 유지한다.

## 기존 데이터와 저장 지점

- 네이티브 ERP: DiscussionRun.snapshot/calculation과 Recommendation, Approval, purchase_orders를 재사용한다. 실제 승인 트랜잭션에서 DecisionCase를 한 번 생성하고 기존 실행 스냅샷을 외래 키로 참조한다. 원본을 복제하지 않으며 참조된 실행을 DB에서 삭제할 수 없다.
- 주 업무: 기존 registerPO의 같은 트랜잭션에서 사례를 생성한다. Scenario의 워크플로는 이후 계속 변경되므로 승인 직전 ERP 투영을 별도 동결한다. 규칙 분석 report ID, 채택한 실제 LLM의 run/recommendation ID(있는 경우), 최종 승인·PO·사용자 ID와 선택 시각을 연결한다. 과거 보고서는 필요한 메타데이터/근거만 보존해 중복을 줄였다.
- 선택 이유는 최종 승인 화면에서 입력한다. 네이티브 ApprovalInput.decision_reason 또는 기존 workspace 명령 args.decision_reason을 사용한다. 기존 API 호환을 위해 필드 자체는 선택 사항이며 누락은 null이다. 담당자 이유를 자동 작성했다고 간주하지 않는다.
- 실제 선택 후보와 전체 후보·예상 비용/일정/폐기량·검증 결과, 원료·규격·단위·필요량·가용량·투입일·예산/확약/유효기간 조건은 승인 시점 정보로 보존한다. 이후 ERP 수정으로 과거 사례를 재계산하거나 덮어쓰지 않는다.
- 과거 PO는 승인자·선택 이유를 추정해 자동 역생성하지 않는다. 신규 서버 승인부터 기록한다. 브라우저만의 오프라인 가상 PO는 서버 사례로 기록하지 않는다.

## DB 변경과 권한

마이그레이션 0004_decision_memory (부모 0003_quote_workflow):

1. decision_cases: scenario_id + po_id 고유 제약, actor_id, 선택적 run_id 외래 키, 동결 decision JSON, 현재 outcome JSON, 결과 revision, created_at.
2. discussion_runs.actor_id: nullable 사용자 외래 키. 기존 실행의 소유자는 추정하지 않고 null로 보존한다.

결과를 수정할 때는 기존 AuditEvent에 before/after/수정자/수정 시각/이유/결과 버전을 남긴다. 결과 이력을 위한 중복 테이블은 만들지 않았다. outcome만 조건부 UPDATE하며 decision JSON은 수정 API가 없다. 충돌은 409이고 기존 값·감사 이력을 덮지 않는다.

사례 목록·상세·검색·결과·변경 이력은 로그인한 actor_id로 제한한다. 다른 사용자에게는 사례 상세/수정/이력을 404로 응답한다. 다른 사람의 선택을 개인 통계에 합산하지 않는다. 기존 감사 조회에서도 개인 decision.* 이벤트는 본인 것만 보인다. 새 분석 실행의 상세·스냅샷·SSE도 소유자를 검사해 과거 사례 입력이 다른 사용자에게 노출되지 않게 한다. 이전 소유자 null 실행은 기존 인증 조회 범위를 유지하지만 개인 사례를 주입하지 않는다. 신규 개인 분석의 타 사용자 채택·승인도 막으며 팀 공유·대리 승인 정책은 별도 설계가 필요하다. 회사 ERP의 일반 업무 데이터 공유 정책 자체를 전면 변경한 것은 아니다.

## 실제·시연·미확인 분류

- main-workspace는 합성 ERP 기반이며 가상 회신·입고·QC/QA·생산 진행 버튼을 사용한다. 실제 LLM이나 실제 메일 연결 여부와 관계없이 이 데이터의 판단 사례는 demo다.
- 기타 ERP도 is_synthetic=true, source_kind=synthetic/demo/simulation/test, test_delivery=true인 레코드가 있으면 demo로 분류한다.
- 실제 데이터 연계팀이 Scenario 메타데이터에 source_kind=actual, is_synthetic=false, source_evidence_refs를 명시하고 합성/테스트 레코드가 없을 때 real로 기록한다. 출처가 충분하지 않으면 unverified다. 실제 ERP 수집·등록 파이프라인에서 이 출처 정보를 제공해야 하며 시연 화면에 실제 전환 버튼을 만들지 않았다.
- source_kind는 판단 시점에 고정된다. 시연·미확인 사례의 결과를 real로 저장할 수 없다. real 판단의 테스트 결과는 outcome.source_kind=demo로 저장할 수 있으며 실제 성과 통계에서 빠진다.
- 검색·목록 기본값은 real만 포함한다. include_demo=true는 사례 표시만 확장하며 선택 성향/실제 성과 통계는 계속 real 사례만 집계한다.
- 실제 기록이 없거나 규격을 비교할 수 없으면 참고할 과거 사례 없음으로 표시한다. 결과가 없거나 담당자 의견만 있는 사례를 좋은 성과로 분류하지 않는다.

## 실행 결과와 관측값

GET 상세 응답의 observations는 현재 ERP를 읽은 입력 후보일 뿐이다. 기존 수동 입력을 자동 덮어쓰지 않는다. 화면에서 불러온 뒤 확인·저장해야 새 결과 버전이 생긴다.

| 기존 데이터 | 가져오는 필드와 조건 |
|---|---|
| 주 업무 PO.lines | actualArrival/qaAt. 기존 값이 있어도 demo 출처이며 실제 통계에 포함하지 않음 |
| 실제 PO.deliveries | actual_arrival_date/actual_usable_date. source_kind=actual와 evidence_refs 필요 |
| 실제 연결 Lot | lot_id 또는 lot_code로 승인 회차 연결. actual_arrival_date/qa_release_date, actual_remaining_quantity/actual_expired_quantity |
| consumptions | PO ID 또는 연결 Lot ID 일치 + source_kind=actual/evidence_refs. 같은 단위의 등록 소비량 합계 |
| production_plans | 승인 당시 requirements의 production_plan_id와 연결. 근거가 있는 actual_start_date를 동결 use_date와 비교. 전체 관련 계획의 실제 시작이 있어야 자동 지연 여부/최대 지연 일수를 계산 |
| PO.actual_costs | purchase/transport/testing/storage/disposal. 실제 출처·근거가 있어야 하며 통화가 다르면 가져오지 않음 |
| PO.actual_outcome | 사용량·잔량·만료 폐기량·지연의 명시된 실제 값. 실제 출처·근거 필요 |

수집 응답의 field_sources/evidence_refs는 원본 컬렉션·레코드·근거를 보여준다. 소비량은 등록 기록 합계라 미등록 소비 여부는 담당자가 확인해야 한다. 만료일이 지났다는 이유만으로 실제 폐기량을 만들지 않으며, 계획 입고일이나 QC/QA 예상일을 실제 일자로 복사하지 않는다.

자동 수집이 불가능하면 담당자가 결과 화면에 입력한다. 빈 값은 null이고 0과 다르다. 날짜 미입력·지연 여부 미확인은 null이다. 실제 결과 저장에는 근거가 필요하며 날짜 순서·회차 ID·수량/금액 범위·결과 버전을 검증한다. 확인은 담당자의 근거 입력을 뜻하며 외부 시스템이 독립 검증했다는 뜻이 아니다.

금액은 기존 ERP 방식처럼 소수 문자열로 전송·보존하고 Decimal로 합산한다. 실제 총비용은 구매·운송·시험·보관·폐기처리비 5개가 모두 확인된 경우에만 계산한다. 폐기 원료의 구매원가는 이미 구매비에 포함되며 추가 합산하지 않는다. 모든 금액/수량은 승인 당시 통화/단위로 입력한다.

비교는 실제 총비용 - 승인 당시 예상 총비용이며 예상 대비 실제 차이로 표시한다. AI 도입 절감액이나 절감 성과로 부르지 않는다. 별도 비교 기준이 없으므로 절감액 필드를 만들지 않았다.

## 설명 가능한 유사도 v1

판단 당시 ERP와 계산만으로 context를 동결한다. 결과 비용·입고 실적·사용량·평가·수정 결과는 유사도 특징에 포함하지 않는다.

먼저 원료 코드, 제품 코드/제조사/제형/함량/등급, 기본단위와 통화가 같은지 확인한다. 제품 코드와 규격이 미확인인 자료는 비교하지 않는다. 단위 변환을 임의로 추정하지 않는다.

| 특징 | 계산 | 기본 정규화 규모 |
|---|---|---|
| production_days | 판단 기준일 → 최초 부족/안전재고 부족 투입일까지 일수 | 30일 |
| inventory_ratio | 생산 가용량 / 필요량 | 1 |
| budget_margin | (가용예산 - 현재 적격안 최소 예상비용) / max(abs(가용예산),1) | 1 |
| supply_confirmation | 당시 등록 후보 중 공급 확약 비율 | 1 |
| expiry_days | 당시 적격 공급 회차의 Lot 만료일과 마지막 투입일 사이 최소 여유 | 90일 |
| quote_validity_days | 당시 업체 견적 유효일까지 최소 남은 일수 | 30일 |
| waste_ratio | 당시 적격 후보의 예상 폐기량/주문량 중 최솟값 | 1 |

각 항목 점수 = max(0, 1 - min(abs(현재 - 과거)/규모, 1)). 유사도는 가중합 / 전체 가중치다. 미확인 항목은 점수를 만들지 않으며 분모에서는 제외하지 않아 정보 부족으로 높은 점수를 얻지 않는다. 알려진 항목 가중치 비율이 최소 coverage보다 낮으면 제외한다. 순위는 유사도와 사례 ID로 결정하며 선호·성과는 순위를 올리는 요인이 아니다.

기본 가중치는 각각 1, 최소 유사도 0.5, 최소 coverage 0.5다. 비교 근거는 현재/과거 값, 항목 점수·가중치·규모, 유사/차이/미확인으로 반환한다. 개인의 최근 최대 1000건이 검색 후보 풀이고 그중 조건이 맞는 사례 전체를 집계하며 화면에는 기본 상위 5건을 표시한다.

서버 환경변수:

~~~dotenv
BIOFLOW_CASE_WEIGHTS={"production_days":1,"inventory_ratio":1,"budget_margin":1,"supply_confirmation":1,"expiry_days":1,"quote_validity_days":1,"waste_ratio":1}
BIOFLOW_CASE_SCALES={"production_days":30,"inventory_ratio":1,"budget_margin":1,"supply_confirmation":1,"expiry_days":90,"quote_validity_days":30,"waste_ratio":1}
BIOFLOW_CASE_MIN_SIMILARITY=0.5
BIOFLOW_CASE_MIN_COVERAGE=0.5
~~~

일부 키만 설정하면 나머지는 기본값이다. 알 수 없는 키·음수 가중치·0 이하 규모 등은 조회 API가 503으로 알린다. 조회를 완료하지 못해도 Orchestrator는 과거 입력 unavailable을 명시하고 기존 현재 ERP 검증 경로를 유지한다.

## 선택 성향과 실행 성과

preference는 유사 조건의 본인 real 사례에서 선택한 일괄/분할 횟수다. 비용이 적게 들었다거나 전략이 우수했다는 뜻이 아니다. performance는 확인값이 있는 실제 결과 사례 수와 비용/지연/폐기 확인 사례 수를 별도로 제공한다. confirmed_outcome_count는 real 사례 + real 결과 + 근거 + 하나 이상의 실제 측정값을 뜻하며 모든 결과가 완결되었다는 뜻은 아니다. 평가 문장만 있으면 확인된 실행 결과에 포함하지 않는다.

## 팀원 API·함수 계약

기존 세션 쿠키 인증을 사용한다.

| API | 사용 |
|---|---|
| GET /api/v1/decision-cases?scenario_id=...&po_id=...&include_demo=false | 본인 발주 사례 목록. 최대 200건 |
| GET /api/v1/decision-cases/{id} | 동결 의사결정·ERP 참조 해석·현재 결과·관측값 |
| PUT /api/v1/decision-cases/{id}/outcome | 결과 전체 저장. expected_revision 필수; 409는 최신 내용 재조회 |
| GET /api/v1/decision-cases/{id}/history | 본인 결과의 before/after·수정 이유·입력자·시각 |
| GET /api/v1/decision-memory/similar?scenario_id=... | 현재 서버 ERP로 유사 사례 조회. material_id/limit(1~20)/include_demo/exclude_po 선택 가능 |

주 업무 검토 화면은 로컬 workflowStamp의 SHA-256을 expected_stamp로 함께 전송한다. 서버 원본과 다르면 409로 저장·재조회 안내를 표시해 다른 버전의 과거 비교를 현재 결과처럼 보여주지 않는다. 별도 팀원 호출은 서버 ERP를 기준으로 조회할 수 있다.

결과 저장 예시 (real은 real 사례에만 허용):

~~~json
{
  "expected_revision": 0,
  "source_kind": "real",
  "receipts": [{"line_id":"승인 스냅샷의 회차 ID","actual_arrival":"2026-11-01","usable_date":null}],
  "actual_purchase_cost":"0",
  "actual_transport_cost":null,
  "actual_testing_cost":null,
  "actual_storage_cost":null,
  "actual_disposal_cost":null,
  "used_quantity":0,
  "remaining_quantity":null,
  "expired_quantity":null,
  "production_delayed":null,
  "production_delay_days":null,
  "evaluation":"원가 확인, 나머지 결과 미확인",
  "notes":"추가 근거 수집 중",
  "evidence_refs":["GRN:원본 레코드 ID"],
  "change_reason":"최초 결과 입력"
}
~~~

미입력 필드는 null로 저장된다. 수정은 전체 결과 교체이므로 부분 변경 클라이언트는 최신 values를 먼저 불러와 유지할 필드를 보존해야 한다. 이전 버전은 감사 이력에 남는다.

similar 응답에는 cases[].id/po_id/source_kind/similarity/coverage/explanation, decision(연결 ID·사용자 선택·이유·제약·후보), outcome(values/confirmed/unknown_fields/비용 차이), preference/performance/policy/current_context를 포함한다. 항상 advisory_only=true, training_performed=false다. 공개 API의 reuse_authorized=false는 과거 안을 현재 승인안으로 자동 적용할 수 없다는 뜻이다.

Python 연결점은 services.decision_memory.memory_for(db, user_id, snapshot, calculation) 및 search(...), orchestrator_input(result)다. 기본 대상은 최초 확보가 필요한 원료이며 다른 원료는 API material_id로 명시할 수 있다.

services.discussions의 기존 run_discussion은 사용자 소유 실행의 동결 snapshot/calculation으로 history를 조회해 case_memory artifact에 보존한다. Orchestrator 입력의 historical_decision_memory/history_use_policy에만 전달한다. 부서 AI 모듈을 전면 변경하지 않았다. Orchestrator에는 상위 5건의 선택/결과/근거와 통계만 제한적으로 투영하고 과거 ERP·전체 후보를 중복 주입하지 않는다. 개인 사용자 ID도 모델 입력에 필요하지 않아 제외한다. 원본 상세는 소유자 API에서 확인한다.

과거 선택 이유와 결과 의견은 비신뢰 참고 데이터다. 과거 사례 ID는 현재 evidence_contract가 아니며, 반환할 후보는 현재 registered_candidates와 기존 결정론적 품질·납기·예산·현금 검증을 통과해야 한다. 과거 선호로 필수조건을 완화하거나 자동 승인하지 않는다.

## 실행·검증

PowerShell, 프로젝트 루트:

~~~powershell
npm test
.venv\Scripts\python.exe -m pytest -q backend/tests
npm run build
.venv\Scripts\python.exe scripts/run-local.py
~~~

기존 실행기는 시작할 때 alembic upgrade head를 실행한다. 별도 배포는 DATABASE_URL을 지정하고 backend에서 python -m alembic upgrade head 후 API/worker를 재시작한다. 개발자 DB를 테스트에 사용하거나 데이터를 초기화하지 않았다. 첫 번째 업체 이메일·승인·메일 흐름은 기존 API와 테스트를 유지한다.

최종 검사: 백엔드 168개, 프런트엔드 97개 통과. 프로덕션 빌드와 브라우저 검사 통과. 기존 Vite 큰 청크 경고와 Starlette/Alembic 사용 중단 예정 경고만 남는다.

검증 범위: 스냅샷 보존/승인 실패 시 미생성/실제·시연 분리/미입력과 0/Decimal 비용·폐기 중복 방지/소유자 범위/수정 충돌·감사 이력/정규화·가중치·규격 필터/기록 부족/실제 소비·Lot·생산 수집/Orchestrator 참고 입력/현재 승인 조건 우회 방지/기존 DB 업·다운 마이그레이션.

Headless Edge와 격리 SQLite DB에서 결과 입력·관측값 불러오기·새로고침 복원·수정 이력·판단 스냅샷 불변을 확인한다. 로컬 산출물은 .runtime/browser-check/memory-result.json 및 memory-verified.png이며 Git에 포함하지 않는다. 실제 메일·Google·LLM 호출·모델 재학습은 실행하지 않는다.

## 변경 파일

- 서버: models.py, schemas.py, main.py, db.py, decision_api.py, services/decision_memory.py, services/approvals.py, services/workspace.py, services/discussions.py.
- DB: migrations/versions/0004_decision_memory.py.
- 화면: workflow/DecisionMemory.tsx, decision-memory.css, decisionResults.ts, FlowApp.tsx, connected/vendor/pages/Discussions.tsx, ERP.tsx.
- 테스트: test_decision_memory.py, test_decision_memory_migration.py, decisionResults.test.ts; 기존 conftest/마이그레이션 테스트의 head 및 Orchestrator 입력 계약 테스트 갱신.
- 설정: .env.example; 이 문서.

## 남은 한계

현재 기본 데이터는 시연이어서 기본 실제 통계가 비어 있는 것이 정상이다. 실제 ERP 연계팀이 출처 메타데이터와 실제 관측 필드/근거를 제공해야 하며, 담당자 입력 결과는 독립적인 외부 검증을 의미하지 않는다. 과거 미기록 발주의 승인자나 실제 성과는 추정하지 않는다. 초기 검색은 최근 1000건의 설명 가능한 규칙이며 대규모 색인·팀 공유 통계·자동 최적화·재학습은 구현하지 않았다. 실제 LLM 서비스·PostgreSQL 실서버·현장 ERP에 대한 통합 검증은 별도다.
