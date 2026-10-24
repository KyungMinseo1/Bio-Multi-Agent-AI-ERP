# 업체 이메일 데이터 · 팀원 메일 기능 통합

통합 기준일: 2026-10-25. 실제 이메일 발송 및 원격 push는 수행하지 않았다.

## 보존과 통합 대상

- 최초 폴더에는 .git이 없었다. 원래 브랜치·커밋·미커밋 상태는 존재하지 않아 확인할 수 없었다. 로컬 main을 생성하거나 변경하지 않았다.
- 소스 119개 파일을 비밀정보 검사 후 로컬 체크포인트 a3220cf에 보존했다. 보존 브랜치: checkpoint/pre-email-integration-20261024. .env, .runtime, DB, 가상환경, 빌드는 커밋하지 않았다. .env.example은 비밀정보 없는 템플릿으로 포함했다.
- 현재 작업 브랜치: integration/supplier-email-joengwon.
- git fetch origin으로 확인한 실제 원격 브랜치명은 Jeongwon이다. joengwon이라는 정확한 이름은 없었고, main 외에 해당 작업 브랜치만 있어 식별 가능한 대상이었다.
- 통합 원격: https://github.com/KyungMinseo1/Bio-Multi-Agent-AI-ERP/tree/Jeongwon
- 통합 커밋: ecd572c4664de9595bcda023a054b0337ce4f31a (문서). 핵심 기능 커밋: fadc22f (CSV 부족 계산·Gmail MCP 견적 흐름).
- Git 이력이 없는 소스와 원격이므로 --allow-unrelated-histories --no-commit 병합으로 시작했다. add/add 충돌 23개는 팀원의 CSV/메일 구현을 기준으로 해소하고 업체 데이터·안전 검증·Windows UTF-8 수정은 재적용했다. 양쪽 이력은 merge commit의 부모로 보존한다.
- 적용할 AGENTS.md는 로컬/상위 디렉터리 및 원격 파일 목록에서 발견하지 못했다.

### 기존 변경과 이전 작업 구분

원격 7f18141과 체크포인트를 파일 내용으로 비교하면 아래 25개 파일이 다르며, 지난 대화에서 제가 수정한 파일 목록과 일치한다. 나머지 94개 보존 파일은 해당 원격 기준과 같다. 단, 원래 Git 이력이 없어 같은 파일에 사용자가 추가로 수정했는지는 분리 확정할 수 없다. 그래서 파일 전체를 체크포인트로 먼저 보존했다. 보존 파일의 SHA-256 목록은 로컬 .runtime/integration-preservation/source-manifest.json에 있다.

이전 광범위 구현은 체크포인트에서 확인할 수 있다. 현재 담당 범위에서는 이전 quoteMail.ts, 중복 초안 PUT API, 개인 초안용 0003_rfq_drafts와 해당 전용 테스트를 제거하고 팀원 기능으로 통일했다. 실제 로컬 DB는 0002_outbound_emails여서 제거한 개인 마이그레이션이 적용되지 않았음을 확인했다. 다른 환경에서 그 개인 마이그레이션을 이미 적용했다면 별도 DB 이관 검토가 필요하다.

## 팀원이 이미 구현한 기능

- Vendor.email, 공급업체 CSV email 열, CSV 읽기/쓰기와 workspace JSON 저장.
- 결정론적 부족·확보 기한 계산, 견적 요청 1차 승인과 업체별 quoteDraft 생성.
- ProcurementDesk의 simulation / gmail_mcp / smtp 선택 및 최종 확인 후 기존 POST /mail/quote-requests 호출.
- Python MCP SDK 기반 Gmail 연결·발신 계정 확인·MIME/CSV 발송, 선택적 OAuth Gmail 게이트웨이. 기존 SMTP 어댑터도 유지.
- 원본 revision/source_stamp·수량·일정 검증, 발송 이력·중복 요청/불명확 결과 재시도 차단.
- Gmail 회신 조회와 담당자 확인 후 기존 AI 분석으로 전달.

승인 직후 메일을 자동 발송하는 기능은 없다. 원격 FlowApp의 승인 후 이동은 문의 탭까지였고, ProcurementDesk 승인은 로컬 상태 변경이었다. 통합본은 기존 승인 함수를 재사용해 **서버 저장 성공 후** ProcurementDesk로 이동하거나 작성 영역으로 스크롤한다. 저장 실패/버전 충돌/보류는 작성 영역을 열지 않는다. 최종 구매 PO 승인은 별도 흐름으로 유지한다.

## 이번 담당 범위의 변경

- 기존 email 필드를 단일 기준으로 사용한다. quoteEmail/quote_email이라는 새 마스터 필드나 별도 공급업체 API를 만들지 않았다.
- 신규 임시 업체 A/B/C에 supplier-a@example.com, supplier-b@example.com, supplier-c@example.com을 설정했다. 시드와 public/erp-csv/suppliers.csv가 일치한다.
- 이전 로컬 quoteEmail 값은 email이 없는 경우에만 이어받는다. 기존 email이 우선하며 정규화 후 quoteEmail은 제거한다. 기존 PO의 고정 스냅샷은 바꾸지 않는다. 주소가 없으면 다른 사람 주소를 추정하지 않는다.
- 선택한 업체 email을 즉시 표시한다. 변경한 주소는 업체 이메일 저장 버튼으로 기존 PUT /workspace에 저장한다. 화면 상태와 DB를 함께 갱신하므로 새로고침 뒤에도 유지된다. CSV 편집·저장 경로도 계속 사용할 수 있다.
- 이메일만 변경할 때 수량·품질·공급 확약을 바꾸지 않으며, 불필요한 부족 재승인 팝업을 띄우지 않는다. 형식 오류·누락 주소는 안내하고 발송을 막는다.
- 공통 default_recipient fallback과 기본 수신자 허용 예외를 제거했다. BIOFLOW_SMTP_DEFAULT_TO는 이전 설정 조회 호환용으로만 남고 업체 주소나 테스트 주소로 사용하지 않는다. 개인 팀원 이메일 리터럴도 소스에서 발견하지 못했다.
- 실제 발신자는 기존 메일 설정의 default_sender를 읽기 전용으로 표시하고 서버에서도 일치 여부를 확인한다.
- FlowApp의 오래된 두 번째 작성 폼·발송 핸들러를 제거했다. 작성·발송 UI는 ProcurementDesk, 발송 API는 팀원의 기존 POST 하나를 사용한다. SMTP 계정 연결 설정 화면은 유지한다.

## 기존 API 사용법

모든 경로는 /api/v1 접두사와 기존 세션 인증을 사용한다.

| API | 사용 |
|---|---|
| GET /workspace | 저장된 workflow.data.vendors[]의 id/email 조회. 새로고침·서버 업무 불러오기 |
| PUT /workspace | 기존 expected_revision + workflow 전체 저장. 화면의 업체 이메일 저장과 승인 저장이 사용 |
| GET /workspace/csv | revision 및 sources.suppliers CSV 조회 |
| PUT /workspace/csv/suppliers | 기존 공급업체 CSV의 email 열을 변경해 저장. 본문은 content와 expected_revision |
| GET /scenarios/main-workspace/suppliers | 파생 ERP 공급업체에 id/code/email 투영 조회 |
| POST /mail/quote-requests | 기존 팀원 발송 API. simulation/gmail_mcp/smtp와 최종 확인·원본 검증 유지 |
| GET /mail/settings | 기존 계정 설정 + recipient_policy/test_recipient/test_allowlist |
| GET /mail/outbox?case_id=... | 기존 이력 + original_recipient/test_delivery 표시 |

workspace 저장 요청은 다음 구조다. workflow는 GET으로 읽은 전체 원본을 보존해 보내야 한다. 서버가 반환한 revision으로 다음 변경을 진행하고 409이면 최신 업무를 불러와 충돌을 해결한다.

~~~json
{
  "expected_revision": 3,
  "workflow": {
    "data": {"vendors": [{"id":"B", "email":"quotes@your-supplier-domain"}]}
  }
}
~~~

위 구조는 설명용 발췌다. 실제 요청에는 기존 schema/products/lots/productions/vendors/config/approvals/inquiries/orders 등의 전체 workflow가 필요하다. CSV 방식은 GET /workspace/csv의 sources.suppliers 전체 양식에서 해당 ID 행의 email만 변경해 보낸다.

~~~json
{
  "expected_revision": 3,
  "content": "기존 공급업체 CSV 전체 내용"
}
~~~

발송 요청 계약은 팀원의 QuoteEmailInput을 유지한다. quoteDraft의 case_id/vendor_id/vendor_name/recipient_email/원료/수량/일정, 설정의 sender_email, 담당자가 확인한 subject/body에 expected_revision, source_stamp, final_confirmation=true, delivery_mode를 추가한다. Idempotency-Key 헤더도 유지한다. 서버는 recipient_email이 선택한 업체의 저장된 email인지 확인하며 임의 주소나 공통 기본 수신자 우회를 거부한다.

실제 발송 성공 응답의 recipient는 실제 SMTP/MCP 대상이고 original_recipient는 마스터 업체 주소다. test_delivery=true이면 테스트 수신자에게 보낸 결과다. 원래 주소와 실제 대상은 payload에도 보존한다. HTTP 상태 외에 기존 status(sent/simulated/sending/failed/uncertain/replied)를 함께 확인해야 한다. 공급 확약은 메일 sent와 별개이며 기존 명시적 회신 확인 절차를 거친다.

## 발송 정책과 설정

새 전송 시스템이 아니라 기존 dispatch의 수신자 검증이다. 실제 계정·OAuth·MCP 설정은 팀원의 docs-team/CSV-RFQ.md와 .env.example을 따른다.

| 변수 | 동작 |
|---|---|
| BIOFLOW_MAIL_MODE=preview | 기본값. 실제 발송을 막고 기존 simulation만 허용. 잘못된 모드 값도 preview |
| BIOFLOW_MAIL_MODE=test | 기존 gmail_mcp/smtp를 선택해도 허용 테스트 주소로만 전송 |
| BIOFLOW_MAIL_TEST_TO | 실제 허용 테스트 수신자 1명. 설정 없으면 차단 |
| BIOFLOW_MAIL_TEST_ALLOWLIST | 쉼표 구분 목록. TEST_TO가 반드시 포함되어야 함 |
| BIOFLOW_MAIL_MODE=live | 마스터 업체 email로 전송. 예시 도메인은 차단 |
| BIOFLOW_SMTP_DEFAULT_FROM / ALLOWED_FROM | 기존 발신 계정 설정. 화면에서 임의 발신자로 변경하지 않음 |

example.com/net/org 및 하위 도메인, .test/.invalid/localhost 주소에는 실제 전송하지 않는다. 예시 업체 주소를 test 모드의 원래 주소로 표시할 수는 있지만 실제 대상은 별도 허용 목록의 비예시 주소여야 한다. 허용 테스트 주소를 임의로 채우거나 DEFAULT_TO로 대체하지 않는다.

화면에는 원래 업체 주소와 실제 수신 대상/전송 없음이 표시된다. 테스트 메일에는 테스트 제목·본문을 추가하고, 테스트 회신을 공급 확약으로 승격하는 sync/confirm-reply는 서버에서 막는다. 실제·테스트 발송 중/성공/불명확 업체를 가상 회신에서 제외한다.

## DB와 실행

업체 email은 기존 JSON/CSV 필드이므로 이번 담당 범위를 위한 새 테이블·이메일 전용 마이그레이션은 없다. 팀원의 0003_quote_workflow는 OutboundEmail에 MCP/원본/회신 메타데이터를 추가하므로 그대로 포함했다. 공급업체 데이터와 기존 0002 메일 이력 보존은 임시 DB 마이그레이션 테스트로 확인한다. 사용자 .runtime/bioflow.db를 테스트에 사용하거나 초기화하지 않았다.

PowerShell, 프로젝트 루트:

~~~powershell
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm test
.venv\Scripts\python.exe -m pytest -q backend/tests
npm run build
.venv\Scripts\python.exe scripts/run-local.py
~~~

기존 실행기는 시작할 때 alembic upgrade head를 실행한다. 설정 변경이나 통합본 실행에는 기존 API/worker를 종료 후 재시작한다. 실제 테스트 수신자가 설정되지 않은 상태에서는 preview/simulation으로 확인한다. 기본 실행은 외부 메일 발송을 하지 않는다.

## 검증과 남은 확인

최종 결과: 프런트엔드 94개, 백엔드 152개 통과. 프로덕션 빌드 통과. Headless Edge와 격리 SQLite DB에서 승인 저장 후 작성 영역 진입, A/B 업체별 주소, B 주소 변경·저장·새로고침 복원, simulation 처리, preview 정책의 실제 발송 차단을 확인했다. 실제 발송 요청은 발생하지 않았다. 로컬 스크린샷: .runtime/browser-check/supplier-email-verified.png. 사용자 DB는 변경하지 않았다.


- 프런트엔드: 업체별 자동 표시, 주소 오류/예시 차단, 이전 주소 호환, 저장 후 로컬 복원, 승인 저장 성공/실패/충돌/보류 순서, 기존 CSV/계산/분석 테스트.
- 백엔드: 기존 CSV 저장·조회·ERP 투영, 새 조회로 저장 내용 복원, 버전 충돌, 주소/발신자 변조·기본 수신자 우회 차단, 테스트 허용 목록·MCP 실제 인자, 테스트 회신 승격 차단, 기존 MCP SDK/게이트웨이·실제 회신 확인 테스트.
- 실제 메일·Google 호출은 모의 처리한다. 실제 SMTP 전달·사용자 OAuth 계정과 PostgreSQL 실서버 검증은 별도 설정 후 담당자가 수행해야 한다.
- 빌드에는 기존 Vite 큰 청크 경고, 테스트에는 기존 Starlette/Alembic 사용 중단 예정 경고가 남을 수 있다.
- source-manifest와 격리 브라우저 검증 산출물은 .runtime에만 남고 Git에 포함하지 않는다.

## 파일별 소유 범위

팀원에서 그대로 가져온 핵심 파일: gmail_mcp.py, gmail_gateway.py, 0003_quote_workflow.py, CSV 파서/규칙/기본 API, 기존 OAuth 실행기·의존성.

원격 대비 이번 보완 파일: .env.example; services/mailer.py(수신 정책); services/quote_requests.py(기존 dispatch 주소/대상 검증); services/workspace.py(주소 호환·Windows UTF-8·가상 회신 제외); main.py(테스트 회신 차단); scripts/workflow-runner.ts(기존 ERP email 투영); src/erp/model.ts/store.ts/viewData.ts와 erpSchema.ts(기존 필드 표시); ProcurementDesk.tsx/FlowApp.tsx/procurement.ts/engine.ts/store.ts/supplierEmail.ts(단일 화면·저장·복원); public/erp-csv/suppliers.csv(예시 데이터); 관련 테스트와 이 문서.

이전 작업의 변경 파일 목록(체크포인트에 원본 보존):
- .env.example
- backend/app/db.py
- backend/app/main.py
- backend/app/models.py
- backend/app/schemas.py
- backend/app/services/mailer.py
- backend/app/services/quote_requests.py
- backend/app/services/workspace.py
- backend/migrations/versions/0003_rfq_drafts.py
- backend/tests/conftest.py
- backend/tests/test_mailer.py
- backend/tests/test_quote_requests.py
- backend/tests/test_rfq_migration.py
- docs-team/RFQ_EMAIL_INTEGRATION.md
- scripts/workflow-runner.ts
- src/connected/connection.test.ts
- src/connected/connection.ts
- src/connected/vendor/erpSchema.ts
- src/erp/model.ts
- src/erp/store.ts
- src/erp/viewData.ts
- src/workflow/FlowApp.tsx
- src/workflow/engine.ts
- src/workflow/quoteMail.test.ts
- src/workflow/quoteMail.ts
