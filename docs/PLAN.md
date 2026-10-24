# 바이오 원료 발주 ERP 및 멀티 에이전트

## Context
가상 데이터를 실제 저장·입력하는 독립 웹 ERP 위에 선제 발주 감지 → 부서별 실제 LLM 토론 → Admin 검토 → 사용자 대안 선택 → 내부 발주 등록을 구현한다. OpenAI, Gemini, OpenRouter, vLLM을 지원하고 공식 외부 이슈 자동 수집을 포함한다. 실제 공급업체 주문 전송이나 발주 이후 성과 분석 제품 전체는 이번 범위가 아니며, 재고·입고 예정·시험·승인 상태 입력은 의사결정에 필요한 수준으로 제공한다.

근거: 현재 저장소는 README.md(제목만), .gitignore, docs의 두 PDF뿐이며 구현 코드·실행 설정이 없다. docs/바이오_원료발주_AI_ERP_기획정리_v1.4.pdf 1~5쪽의 부서 역할, 날짜별 가용 재고, 납품 역산, 품질 필수조건, 불변 전략 이력, 외부 이슈 관련성 확인을 기준으로 한다. docs/해커톤 설명 요약.pdf에 플렉스튜디오 언급이 있으나 사용자는 독립 웹 ERP를 선택했다.

## Approach

### 1. 실행 기반과 영속 ERP를 먼저 구성
새 경로는 아래에서 지정하는 설계 경로이며 기존 파일로 주장하는 것이 아니다. 재사용할 애플리케이션 코드가 없으므로 backend/에 Python 3.12·FastAPI·SQLAlchemy 2·Alembic·Pydantic 2·httpx, frontend/에 React·TypeScript·Vite·TanStack Query·React Router를 구성한다. PostgreSQL 16을 사용하며 compose.yaml은 db, api, worker, web 네 서비스를 실행한다. api와 worker는 동일 backend 이미지와 DB를 공유한다. 프런트는 nginx에서 /api를 api로 전달하고 개발 Vite도 같은 프록시를 사용한다. 시간은 UTC 저장·Asia/Seoul 표시, 계획 계산은 한국 달력 날짜/달력일 기준이며 공휴일 최적화는 넣지 않는다.

backend/app/{models,schemas,api,services,providers}와 backend/tests, frontend/src/{pages,components,api}로 구분한다. 돈·수량은 Decimal/Numeric을 사용하고 API에서는 소수 문자열로 전달한다. 원료 기본단위를 명시하고 다른 단위는 등록된 양수 변환계수 없이는 입력 거부한다. ID는 UUID, 변경 가능한 ERP 레코드는 revision 정수로 낙관적 잠금을 수행한다. PDF 원본은 수정하지 않는다.

DB 모델을 다음 동작별로 만든다.
- Material: code/name/base_unit/storage_condition/safety_stock/review_days/planning_horizon_days. Supplier와 SupplierMaterial: 업체명·공식 별칭·원료 연결·공급업체 승인 상태·원료 승인 상태·승인 근거.
- InventoryLot: 원료·Lot·총량·온도조건·유효일·QC 상태(pending/passed/failed)·QA 상태(pending/approved/rejected). StockReservation은 생산 건과 Lot의 배정량, Consumption은 실제 소모 기록. 음수 잔량·중복 소모·전체 재고 초과 배정을 트랜잭션으로 거부한다. 배정은 해당 생산 수요만 충족하며 다른 수요의 자유 재고로 재사용하지 않는다.
- CustomerOrder와 ProductionPlan/MaterialRequirement: 제품·목표 고객 납품일·생산 수량·원료별 투입일/수량, 생산/완제품 검사/포장/출하/고객 운송 소요일. QC/QA 예상 소요일과 자원 일정(QC 일별 처리 용량, 생산 라인 예약), StorageCapacity(온도조건·공통 용량 단위), 원료 단위당 공간계수를 저장한다.
- SupplierOffer: 업체·원료·유효기한·단가·MOQ·주문배수·공급 준비/운송 소요일·공급 가능량·공급 확약 상태/근거/확인 시각·분할입고 허용·납품 실적 건수와 지연일 표본·잔여 유효기간·운송비·입고 Lot별 시험비·일별 보관비·폐기 단가·지급기한. PurchaseBudget은 생산 건별 승인 한도 및 지급일별 현금 가용 한도를 저장한다. 근거 없는 확률은 만들지 않는다.
- PurchaseOrder/lines/deliveries: 승인된 제안 버전·수량·단가·입고 예정일·예상 QC/QA 완료일·공급 확실성·사용자와 승인 시각. ERP 입력으로 기존 발주도 등록할 수 있다. 새 발주는 approved 상태의 내부 기록으로만 생성한다.
- ExternalIssue/IssueEvidence/IssueLink, Alert, DiscussionRun, StrategyVersion, AgentMessage, ValidationResult, Recommendation, Approval, Job, AuditEvent를 영속화한다. 원본 메시지/전략/검증은 수정하지 않고 새 버전으로 추가한다. AuditEvent에는 행위자·시각·변경 전후를 남기되 비밀키는 기록하지 않는다.

API는 /api/v1 아래에 materials, suppliers, supplier-materials, lots, reservations, consumptions, customer-orders, production-plans, requirements, resource-calendars, storage-capacities, offers, budgets, purchase-orders의 GET/POST/PATCH와 입력 검증을 제공한다. 필수 참조가 있는 레코드는 삭제 대신 inactive 처리하며 과거 의사결정 스냅샷은 보존한다. 사용 중인 Lot/원료의 단위 변경은 거부한다. 사용자 계정은 단일 조직 로컬 계정과 역할 operator/approver로 한정하고 서버 세션·해시 비밀번호·HttpOnly 쿠키를 사용한다. 초기 계정 비밀번호는 환경변수로만 제공하며 저장소 기본 비밀번호는 두지 않는다. 발주·예산 추가승인은 approver만 가능하다.

### 2. 가상 데이터와 ERP 입력 화면을 같은 저장 경로에 연결
python -m app.seed --scenario baseline을 만들어 고정 식별자·고정 기준일(2026-10-24)·명시적 is_synthetic 표식으로 재실행해도 중복 없는 데이터 세트를 생성한다. 초기화로 사용자 데이터를 삭제하지 않는다. 실제 공지의 업체를 허구 사건에 연결하지 않는다. 가상 공급업체 4곳, 원료 3종(냉장·냉동·상온), 생산 주문 3건과 Lot/예약/소모/기존 발주/견적/자원 일정/예산을 함께 생성한다. 정상 발주, 가격은 싸지만 납기 근거 부족, 만료/미승인 재고, 냉장 용량 부족, 예산 초과, 관련성 미확인 및 품질 문제 확인의 사례를 포함한다. 합성 외부 이슈는 source_kind=synthetic으로 표시하고 실제 수집 목록과 구별한다.

화면은 한국어로 /dashboard, /erp/materials, /erp/suppliers, /erp/inventory, /erp/production, /erp/offers, /erp/purchase-orders, /issues, /discussions/:id, /settings를 제공한다. ERP 화면에서 위 모델의 등록·수정·목록·상세를 지원하고 seed 전용 내부 경로를 만들지 않는다. 재고 화면은 Lot별 QC/QA/유효일/배정/소모와 온도별 공간, 생산 화면은 원료 수요·납품 역산·예산/지급 한도를 편집한다. 빈 화면은 필요한 입력과 이동 링크를 보여주며 저장 실패는 필드 오류와 서버 메시지로 표시한다.

### 3. LLM과 독립적인 선제 감지·검증 계산 구현
backend/app/services/planning.py의 evaluate_material(material_id: UUID, as_of: date) -> PlanningResult와 validate_strategy(snapshot: PlanningSnapshot, strategy: Strategy) -> ValidationResult를 유일한 수치 판단 경로로 사용한다. 입력 전체 revision과 계산 기준일을 스냅샷으로 보관한다.

날짜별 재고 투영은 기준일 재고에서 이미 기록된 소모를 한 번만 차감한 잔량으로 시작한다. approved QA + passed QC이고 투입일까지 유효한 Lot만 FEFO로 배정하며 다른 생산 예약분은 제외한다. 유효일 당일까지 사용 가능, 다음 날부터 불가로 통일한다. 입고 예정분은 입고일이 아니라 예상 QC/QA 완료일부터 반영하고, 미확약 공급은 별도 optimistic 시나리오에만 넣는다. 날짜별 생산 투입 수요·유효기간·입고·자원/보관 제약을 함께 반영한다. 미래 QC/QA 완료는 예측치이지 현재 확정 가용 재고로 표시하지 않는다.

조달기간 = 공급 준비 + 운송 + 입고 처리(견적에 일수 저장) + QC + QA. 생산 건의 최종 원료 사용 가능일은 고객 납품일에서 고객 운송·출하/포장·완제품 검사·생산 소요일을 역산한다. QC/생산 자원 용량이 차면 다음 가능한 날짜로 밀어 실제 완료일을 다시 계산한다. 알림 기준은 검토기간 + 조달기간 안의 예정 사용량 + 안전재고이며, 일정 수요가 없는 일정 사용량 사례도 지원하도록 원료에 daily_usage_fallback을 선택 입력한다. 날짜별 계획이 있는 구간에는 평균 소모를 중복 가산하지 않는다.

알림에는 자유 가용량, 첫 안전재고 미달일, 첫 수요 미충족일, 예상 소진일, 최종 발주 검토일, 조달 분해, 기존 입고 근거, 영향 생산/납품 건을 표시한다. 조달기간을 확정할 유효 견적이 없으면 정상으로 간주하지 않고 data_missing으로 표시한다. 이미 부족하거나 최종 발주일이 지났으면 urgent, 검토일이 도래하면 warning. 정상 회복 시 resolved. (material_id, production_order_id 또는 null, alert_kind)별 활성 알림 하나와 acknowledgement를 유지한다.

후보는 유효하고 승인된 SupplierOffer에서 생성하며 부족 수요 + 안전재고를 MOQ/배수로 올림한다. 단일 업체안, 분할입고 허용 견적의 2회 입고안, 두 업체 조합의 분할발주안을 열거한다. `scenario_1`처럼 등록 계약이 3회 공급을 명시하면 해당 3회 입고안도 검증한다. 주문배수 단위의 공급량 배분을 양쪽 수요 충족 범위에서 열거하고 상한 200개를 넘으면 납기/비용 정렬로 200개만 검증한다. 부족 수요가 없는 원료는 신규 발주를 만들지 않는다. 업체 승인·원료 승인·확인된 품질 이슈·유효기간·온도/공간·공급량·자원 일정을 hard constraint로 검증하고, 예산 초과는 requires_budget_approval로 분리한다. 비용은 구매+운송+입고 Lot별 시험+입고일부터 계획 소진일까지 보관+기한 내 미소진 예상 폐기 비용으로 계산하고 지급일별 현금 한도도 검사한다.

순위는 필수조건 충족 → 목표 납품 가능 → 확약/실적/확인된 공급차질의 근거 등급(confirmed, supported, unconfirmed) → 총비용 순이며 가중합으로 품질·납기를 가격과 상쇄하지 않는다. 실적/확약 없는 후보를 supported로 올리지 않는다. 공급차질 확인 시 등록된 지연일로 재계산하고 지연일 미확인은 불확실로 남긴다. 미확인 기사만으로 감점/거래중단하지 않는다.

수정 API의 트랜잭션에 재계산 Job을 함께 넣는다. worker는 DB의 FOR UPDATE SKIP LOCKED로 작업을 점유하고 원료별 중복 작업을 합친다. 재시작 시 만료된 작업 lease를 회수한다. 주기적 재평가와 외부 수집도 동일 worker에서 실행한다. GET /alerts, POST /planning/recalculate, POST /alerts/{id}/acknowledge를 제공한다.

### 4. 실제 8역할 토론과 공급자 교체 가능한 호출 경계
backend/app/providers에 공통 async generate_json(role: str, messages: list[Message], schema: dict) -> dict 인터페이스와 OpenAI/Gemini/OpenRouter/vLLM 어댑터를 둔다. openai와 google-genai SDK를 직접 사용하며 별도 에이전트 프레임워크는 도입하지 않는다. provider/model/base_url/timeout은 서버 설정과 역할별 매핑으로 선택하고 API 키는 환경변수만 읽는다. /settings에는 키 값이 아닌 설정 여부와 모델/역할 매핑만 표시한다. 연결 확인은 실제 짧은 구조화 호출로 수행한다. 구성되지 않은 공급자는 명시적인 configuration_error이며 mock으로 대체하지 않는다.

공급자별 계약은 다음으로 고정한다. 모든 모델 ID는 환경변수로 명시하며 임의 기본 모델/자동 공급자 전환은 없다. 공통 LLM_TIMEOUT_SECONDS=60, OpenAI 계열 SDK max_retries=0. Pydantic extra=forbid, object 루트, 모든 속성 required(선택값은 nullable), 중첩 additionalProperties=false인 공통 스키마를 사용한다.
- OpenAI: AsyncOpenAI.responses.parse(model=OPENAI_MODEL, input=messages, text_format=해당 Pydantic 모델), https://api.openai.com/v1/responses. completed와 output_parsed를 확인하고 refusal/incomplete는 실패 처리한다.
- Gemini: genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=60000)).aio.models.generate_content(model=GEMINI_MODEL, contents=직렬화한 문맥, config=types.GenerateContentConfig(system_instruction=역할 지시, response_mime_type="application/json", response_json_schema=schema)). prompt block/finish_reason/빈 후보를 확인한 뒤 response.text를 로컬 검증한다.
- OpenRouter: AsyncOpenAI(base_url="https://openrouter.ai/api/v1").chat.completions.create(model=OPENROUTER_MODEL, messages=messages, response_format={"type":"json_schema","json_schema":{"name":"department_turn","strict":true,"schema":schema}}, extra_body={"provider":{"require_parameters":true}}). HTTP 200의 error 필드도 실패 처리한다.
- vLLM: VLLM_BASE_URL은 /v1로 끝나는 서버 주소, VLLM_MODEL은 served model ID. chat.completions.create에 표준 response_format json_schema를 전달한다. 구버전 guided_json은 사용하지 않는다. 인증 없는 배포만 SDK api_key에 비밀이 아닌 "not-required"를 사용한다.
- Chat Completions는 stop 완료·비어 있지 않은 content를 확인하고 JSON/Pydantic/근거 참조 검증을 모두 통과해야 성공이다. SDK 클라이언트는 실행 프로세스 수명 동안 재사용하고 종료 시 닫는다. 예외는 timeout/transport/provider_rejected/refused_or_blocked/incomplete/invalid_output으로 정규화하고 사용자 오류에 키/헤더를 포함하지 않는다.

공식 계약 근거: https://developers.openai.com/api/docs/guides/structured-outputs ; https://github.com/openai/openai-python ; https://ai.google.dev/gemini-api/docs/structured-output ; https://github.com/googleapis/python-genai ; https://openrouter.ai/docs/guides/features/structured-outputs ; https://docs.vllm.ai/en/stable/features/structured_outputs/ . 문서 확인이며 실제 인증 호출은 아직 수행하지 않았다.

POST /discussions는 alert_id와 ERP snapshot revision으로 202와 run_id를 반환한다. GET /discussions/{id}와 /events는 영속 메시지와 Last-Event-ID로 재접속 가능한 SSE를 제공한다. 상태는 queued/running/awaiting_review/completed/failed/stale. 실행 중 ERP 입력이 바뀌어도 토론은 기존 snapshot으로 끝내고 stale을 표시한다.

구매가 계산 후보를 받아 StrategyVersion v1을 제안하고, 재고·물류/생산관리/생산/QC/QA/재무 6역할이 같은 v1을 병렬 검토한다. 구매 수정 → 같은 6역할 재검토를 최대 2회 수행한다. 모든 메시지는 strategy_id/version/role/proposal/impacts/reasons/evidence_refs/change_requests/position(accept, object, needs_information) 구조로 Pydantic 검증한다. 근거는 스냅샷의 레코드 ID·계산 결과 ID·외부 근거 ID만 허용하고 없는 ID는 거부한다. 단순 찬반이 아니라 PDF의 7개 부서 목표별 지연·품질·폐기·공간·비용·지급 문제를 표시한다.

LLM은 공급업체/가격/기한/승인 상태를 만들어낼 수 없으며 제안은 등록된 offer_id와 허용 수량/입고 일정으로만 구성한다. 수정안도 planning.validate_strategy로 재검증한다. JSON 오류 시 오류 목록을 포함해 동일 역할에 한 번만 수정 요청하고 다시 실패하면 run=failed, 해당 역할·원인을 UI에 노출한다. 호출 시간초과/통신/인증 오류도 숨기거나 성공으로 대체하지 않는다.

Admin은 전체 메시지와 계산 검증 결과를 읽고 근거가 있는 서로 다른 2~3개 후보의 설명과 우선순위를 제출한다. 서버가 hard constraint와 순위를 재검증한 후보만 Recommendation으로 확정한다. 1개만 적합하면 1개와 제외 사유, 0개면 발주 불가·추가 확인사항을 표시한다. 무조건 합의로 위장하지 않고 잔여 반대/미확인 사항/추가 비용/납기 근거를 보존한다. UI는 역할별 진행 상태, 버전 차이, 토론 근거, 추천안 비교를 보여준다.

추천 근거는 실제 토론 기록을 따라 역추적할 수 있도록 Recommendation에 rationale_items를 저장한다. 각 항목은 claim(사용자용 판단 요약), evidence_refs(ERP snapshot/계산 결과/외부 근거 ID 목록), message_refs(실제 AgentMessage ID 목록), change_refs(해당 StrategyVersion 변경 ID 목록)를 가진다. 원본이 없는 참조와 계산 결과에 반하는 수치 주장은 검증 오류로 처리한다. Admin은 실제 부서 의견·반론·수정·검증을 요약하며 내부 사고과정 공개를 요구하지 않는다. 부서 동의 자체를 사실 증명으로 취급하지 않고, 해결되지 않은 이견과 미확인 조건도 추천안에 남긴다.

UI는 의사결정 요약을 기본으로 하고 상세를 단계적으로 공개한다. /dashboard 첫 영역은 '지금 해야 할 일'로 구성하여 발주 검토 필요 원료·검토 마감일·영향 생산/납품·다음 행동 버튼을 보여준다. /discussions/:id 첫 영역에는 추천안별 추천 이유·목표 납기 충족 여부와 근거 수준·총비용과 추가 비용·필수조건 검증·잔여 위험·승인 필요사항을 동일 항목으로 비교한다. 이어 '협의 요약'에 부서별 핵심 의견·수정 전후·해결되지 않은 이견을 표시한다. '근거 보기'를 누르면 해당 주장에 연결된 ERP 스냅샷/계산 내역/외부 출처/부서 메시지를 열고, 전체 토론 로그는 별도 펼침 영역에 둔다. 사용자가 발주 판단을 위해 전체 대화를 읽도록 강제하지 않는다. 상태는 색상뿐 아니라 텍스트로 구별하며 ERP 입력·수정 화면은 요약에서 바로 이동할 수 있게 유지한다.

### 5. 공식 외부 이슈 자동 수집과 수동 확인을 연결
backend/app/services/external_sources.py에 openFDA JSON과 public RSS/Atom의 두 수집기를 구현한다. ExternalIssue는 source_kind, source_url, publisher, published_at, occurred_at(nullable), fetched_at, source_status, verification_status(unverified/relevance_unconfirmed/supply_impact_confirmed/quality_impact_confirmed/cleared), severity, source_reliability, summary를 분리한다. 영향 지연일/업체/원료/Lot/발주 링크와 확인자·사유를 IssueLink에 기록한다. 공개 소스가 공급 차질을 완전히 포착한다고 주장하지 않는다.

실제 자동 수집 소스와 요청은 다음으로 확정한다.
- openFDA: https://api.fda.gov/drug/enforcement.json 에 search=report_date:[시작YYYYMMDD TO 종료YYYYMMDD], sort=report_date:desc, limit=100, skip=0부터 100씩 요청한다. 초기/일별 동기화는 최근 90일이며 총량이 skip 상한 25000을 넘으면 날짜 범위를 반으로 나눠 수집한다. 추적 중인 recall_number는 별도 조회한다. 404 No matches는 빈 성공으로 처리하고 429/기타 오류는 실패로 기록한다. 키 없이 확인된 사용 가능 범위에서 요청을 순차 실행하며 하루 900회/분 200회 상한을 DB에 집계한다. FDA_API_KEY는 선택 설정이다.
- 실제 식별키는 (source_id, recall_number), 사건 그룹은 event_id. recalling_firm/product_description/reason_for_recall/code_info/classification/status/report_date/recall_initiation_date와 원본 JSON을 보존한다. 날짜는 YYYYMMDD를 파싱하고 누락은 null로 남긴다. code_info는 비정형 Lot 텍스트이며 자동으로 정확한 Lot 배열로 취급하지 않는다. openfda={}도 정상이다. meta.last_updated는 소스 데이터 갱신일로만 표시한다.
- FDA MedWatch: https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medwatch/rss.xml 을 기본 활성화한다.
- 공급업체 공개 RSS 예시: https://www.thermofisher.com/onelambda/us/en/support/rss-feed/jcr:content.rss?key=revision-notices 를 공식 공급업체 문서 개정 공지로 기본 활성화하되 가상 업체에 연결하지 않는다. 문서 개정 자체를 공급중단으로 분류하지 않는다. 해당 공식 디렉터리는 https://www.thermofisher.com/onelambda/us/en/support/rss-feed.html 이다.
- ExternalSource에 kind/display_name/url/enabled/supplier_id(nullable)/official_domain/ownership_verified/poll_interval_minutes/last_success/last_error를 저장한다. approver가 /settings에서 추가·수정하고 POST /external-sources/{id}/sync와 GET /external-sources/{id}/runs로 실행·상태를 확인한다. openFDA는 24시간, RSS는 12시간 주기로 수집하고 더 긴 feed TTL은 준수한다. 승인 직전 강제 확인은 주기와 별개로 실행하되 rate limit을 넘지 않는다.
- RSS/Atom은 feedparser로 원본 bytes를 파싱하고 원문 guid/Atom id → canonical link → 안정적 내용 hash 순으로 식별한다. pubDate timezone/비UTF8/정렬 안 된 항목/빈 feed를 정상 처리하고 ETag/Last-Modified 조건부 요청 및 304를 지원한다. XML 외부 엔티티는 비활성화한다. 원문 HTML은 실행하지 않고 짧은 텍스트 발췌와 링크만 표시한다.
- 공개 HTTPS URL만 허용하고 사용자정보 포함 URL, localhost/private/link-local/metadata IP를 거부한다. DNS 확인과 실제 연결 대상 검증을 모두 수행하고 리다이렉트마다 재검증한다. 연결 10초/전체 30초/본문 5MiB/리다이렉트 최대 3회로 제한한다. 임의 기사 크롤링/로그인 첨부 다운로드는 하지 않는다. 공급자 공지는 신뢰할 수 없는 데이터로 LLM 문맥에 넣고 지시로 실행하지 않는다.

공식 근거: https://open.fda.gov/apis/drug/enforcement/ ; https://open.fda.gov/fields/drugenforcement.yaml ; https://open.fda.gov/apis/query-parameters/ ; https://open.fda.gov/apis/authentication/ ; https://open.fda.gov/terms/ . 조사에서 실제 JSON/RSS 응답을 확인했다. openFDA는 주 단위 갱신이며 회수 현재 상태 추적용이 아니므로 status로 자동 해제를 판정하지 않는다. MedWatch/공급업체 RSS는 rolling feed라 과거 전체 이력·수집 완전성이 보장되지 않는다. 관련 원문 정정/해제 근거 또는 담당자 확인으로만 cleared를 기록한다. 공식 문서의 무키 제한은 1000회/일·240회/분이며 인증 설명 일부와 모순되지만 무키 요청은 실제 성공했다.

실제 공지 수집과 허구 ERP 업체 매칭을 구분한다. 공식 업체 별칭·원료 별칭·Lot 일치는 검토할 suggested link만 생성하고 사용자가 실제 관련성을 확인해야 확정 영향으로 계산한다. 자동 수집된 공식 회수 공지라도 사용자 발주와 관련성은 자동 확정하지 않는다. 관련 품질문제 확인은 해당 후보를 보류하며 기존 발주 취소/재고 폐기는 자동 수행하지 않는다. 원료명만 같으면 구매 차단하지 않는다.

GET /issues와 GET /issues/{id}는 근거 버전·suggested links를 반환하고 POST /issues/{id}/links는 ERP 대상과 확인 상태/사유/근거를 입력받는다. operator는 제안·관련성 확인을 할 수 있으나 quality_impact_confirmed/cleared는 approver가 근거와 함께 확정한다. POST /issues는 직접 등록도 지원한다. 가상 ERP에 실사건을 시연 연결할 때는 demo_association=true를 필수로 저장하고 실제 피해 확인과 별개로 표시한다.

정기 수집, 수동 동기화, 승인 직전 동기화를 제공한다. 수집 실패 시 과거 데이터를 삭제하지 않고 last_success/error/stale을 표시한다. 사건 고유키로 중복 공지를 병합하되 정정·해제·원문 변경을 Evidence 새 버전으로 보존한다. 검증된 영향이 바뀌면 연관 alert 재계산·완료 토론 stale 표시·기존 PO 재검토 알림을 생성한다. 프런트에서 원문 링크·발행/발생/확인 시각·실제/가상 표시·검증 상태·영향 주문·담당자 확인 양식을 제공한다.

### 6. 사람의 최종 승인으로만 내부 발주 생성
POST /recommendations/{id}/approve는 expected_revision과 Idempotency-Key를 요구하고 승인자 세션을 확인한다. 승인 직전 외부 수집 Job을 완료한 뒤 현재 ERP revision/견적 유효기한/재고/일정/예산/외부 영향으로 재검증한다. 동기화가 실패하면 발주를 만들지 않고 최신 정보 확인 불가와 재시도 경로를 반환한다. 새 이슈가 미확인인 경우 이를 표시하고 사용자 acknowledgement를 받되 확인된 품질 문제처럼 취급하지 않는다.

입력이 달라 추천이 stale이면 409와 변경 항목·재토론 버튼을 반환하고 옛 추천을 자동 수정해 승인하지 않는다. 추가 예산 승인이 필요한 안은 approver가 추가 금액·사유를 명시적으로 기록한 뒤에만 진행하며 승인 예산/현금 한도를 같은 트랜잭션에서 검증한다. 품질 담당자의 실제 사용 승인과 발주 승인 UI를 분리하고 발주 승인이 QC/QA 상태를 바꾸지 않는다.

동일 snapshot 범위의 동시 승인/중복 클릭은 DB 잠금·고유 제약으로 한 번만 PO를 생성한다. PO·예산 약정·audit·추천 선택을 한 트랜잭션으로 저장하고 성공 화면에 발주번호, 업체, 수량, 입고/사용 가능 예상일, 선택 근거, 남은 위험을 표시한다. 외부 업체로 이메일/API 전송은 하지 않으며 화면에 내부 발주 등록임을 표시한다.

## Verification
실행 전 Docker Desktop/Linux containers와 Docker Compose v2, 호스트 8080 포트, 선택 LLM/공식 소스의 HTTPS 접근이 필요하다. 루트 .env.example에 POSTGRES_DB=bioerp, POSTGRES_USER=bioerp, POSTGRES_PASSWORD(필수), SESSION_SECRET(필수), INITIAL_APPROVER_EMAIL(필수), INITIAL_APPROVER_PASSWORD(필수), LLM_PROVIDER, 위 공급자 변수, PLANNING_AS_OF를 정의하고 사용자가 .env에 실제 비밀을 넣는다. compose 서비스 내부 DB URL은 이 변수로 구성하며 DB는 호스트 포트를 기본 노출하지 않는다. backend 컨테이너 WORKDIR=/app에 app/과 tests/를 둔다.

구현 후 실행할 명령은 프로젝트 루트 기준 docker compose up --build -d db, docker compose run --rm api alembic upgrade head, docker compose run --rm api python -m app.seed --scenario baseline, docker compose up --build -d api worker web, docker compose exec api pytest 순서다. backend의 pytest와 httpx 테스트 클라이언트로 계산 경계/승인 트랜잭션을 검증하며 테스트는 별도 테스트 DB를 생성해 사용자 DB와 격리한다. 접근 URL은 http://localhost:8080, 개발 프런트는 5173, API 직접 개발 포트는 8000으로 지정한다. seed 기준일 재현용 PLANNING_AS_OF=2026-10-24를 개발/검증에서만 사용하고 운영 기본값은 오늘 날짜다. api/worker는 마이그레이션이 필요한 DB에서 ready가 되지 않아야 하며 위 순서로 시작한다.

- 계산: 기존 입고 없음, 재고 40, 일 사용 1, 조달 30일, 안전재고 5, 검토 0일 → 40에서는 발주 임계 알림 없음, 35에서 warning. 34에서 뒤늦은 경고이며 이미 수요 부족이 있는 입력은 urgent. 동일 원료의 QC 대기/QA 미승인/만료/타 생산 예약 Lot는 확정 가용량에 포함하지 않는다. 입고일보다 QC/QA 완료가 늦은 기존 PO가 중간 부족을 가리지 않아야 한다.
- 충돌: 가장 싼 미승인 업체는 제외, 확약 없는 저가안은 납기 근거 충분안보다 아래, 냉장공간 초과/미허용 분할입고/유효기간 전 미소진/지급 한도 초과를 각각 구별해 표시한다. 배정된 Lot는 해당 생산 수요에 한 번만 사용한다.
- 실제 브라우저: 초기 로그인 → ERP 폼으로 견적/투입 수요 변경 → dashboard 선제 알림 변경 → 토론 실행 → 7부서와 Admin 실제 메시지/SSE → 2~3개 적합안 비교 → 사용자 선택 → 내부 PO 목록과 DB 영속 상태 확인. 1개/0개 적합안도 별도로 확인한다. 새로고침/worker 재시작 후 이력과 결과가 남아야 한다.
- 설명 가능성과 사용성: 브라우저에서 재고·물류의 공간 초과 반론으로 입고안이 수정되는 가상 시나리오를 실행한다. 추천 요약 → 해당 부서 의견 → 수정 전후 → 공간 계산과 원본 용량 레코드가 실제 ID로 연결되는지 확인한다. 원본 ERP를 수정한 후에도 과거 추천 근거는 당시 snapshot을 보여야 한다. 전체 토론을 펼치지 않고 대시보드에서 검토 대상 확인 → 대안 비교 → 위험/추가 비용 확인 → 승인까지 완료할 수 있어야 한다. 근거 없는 주장·존재하지 않는 메시지 참조는 추천 확정 전에 거부한다.
- LLM 4종: OPENAI_API_KEY/OPENAI_MODEL, GEMINI_API_KEY/GEMINI_MODEL, OPENROUTER_API_KEY/OPENROUTER_MODEL, VLLM_BASE_URL/VLLM_MODEL 및 필요 시 VLLM_API_KEY를 구성하고 각 공급자로 같은 구조화 역할 호출을 실제 실행한다. 전체 토론은 가용한 한 공급자로 완료하고 역할별 다른 공급자 매핑도 실제 호출로 증명한다. 자격증명/실제 vLLM 서버가 없는 공급자는 검증 불가로 명시하며 mock 통과를 실제 연동 증거로 보고하지 않는다. 잘못된 키/부정확 JSON/타임아웃에서 실패가 사용자에게 보여야 한다.
- 자동 수집: 공식 소스에서 실제 레코드를 동기화해 원문 링크/시각/원본 식별자가 DB와 /issues에 나타남을 확인한다. 동일 수집 재실행은 중복 사건을 만들지 않는다. 가상 업체와 자동 연결하지 않음, 원료명 유사 사건은 relevance_unconfirmed, 확인된 품질 링크는 후보 보류, 공급 지연 확인은 재계산, 해제는 새 이력과 재검토로 확인한다. 테스트에서는 격리된 HTTP fixture로 정정/429/실패 동작을 검증하고 실제 수집 smoke와 구분한다.
- 승인: 토론 후 ERP/외부 영향 변경 → 409 stale 및 발주 미생성. 승인 동기화 실패 → 발주 미생성. 추가 예산 승인 없이는 초과안 발주 불가. 같은 Idempotency-Key/동시 두 요청 → PO 한 건. 다른 사용자/권한 부족 → 403. 사용자 승인으로 QC/QA 사용 승인이 생기지 않음.

## Assumptions & contingencies
- 사용자 선택: 독립 웹 ERP, 발주 의사결정 전 과정과 내부 발주 등록, 외부 이슈 실제 자동 수집. 초기에는 단일 조직 로컬 계정이며 기업 SSO/다중 테넌트는 요구하지 않는다.
- 공개 외부 소스는 전체 공급망의 완전성을 보장하지 않는다. 원료·업체·Lot 관련성 확인이 안 되면 미확인으로 유지한다. 수집원이 중단되면 오류/최근 성공 시각을 표시하고 승인 직전 확인이 복구될 때까지 발주 승인을 막는다.
- 키/모델명/실제 vLLM 서버는 실행 환경이 제공해야 한다. 없는 경우 ERP·계산·수집은 정상 실행하되 실제 토론은 설정 필요 상태로 남기며 가짜 응답은 생성하지 않는다.
