# BioFlow 1차 승인 → 견적 요청 이메일

## 확인한 기존 구조

- 작업 디렉터리와 상위 디렉터리에서 적용할 `AGENTS.md`를 찾지 못했다.
- 1차 공급 확인 승인은 `src/workflow/engine.ts`, 서버 저장은 `services/workspace.py`의 기존 명령·버전 잠금·감사 기록을 사용한다. 최종 PO 승인은 별도 `registerPO` / 추천 승인 경로다.
- 메일은 **MCP가 아닌 Python `smtplib` SMTP**다. 기존 `services/mailer.py`의 SSL/STARTTLS·발신 허용 목록·Gmail 인증·CSV 첨부를 재사용한다. 새 발송 시스템은 추가하지 않았다.
- 변경 전 작성 화면은 `BIOFLOW_SMTP_DEFAULT_TO`를 모든 업체의 기본 수신자로 사용했고, 업체 선택을 바꿔도 주소와 본문을 다시 채우지 않았다. 이제 이 변수는 호환 설정 조회에만 남고 업체/테스트 수신자로 사용하지 않는다.
- 소스의 발신자·수신자에 실제 팀원 개인 이메일 리터럴은 발견하지 못했다. 로컬 실행 파일에는 로컬 로그인용 예시 계정만 있으며, SMTP 발신·공통 수신·허용 테스트 주소는 설정되지 않았다. 비밀정보 값은 출력하지 않았다.

## 사용자 흐름

1. 통합 서버에 승인자 계정으로 연결한다. 로컬 시연은 기존 로컬 로그인 기능을 사용한다.
2. 공급업체·견적 표의 편집에서 업체 ID별 **견적 담당자 이메일**을 설정한다. 새 시드 A/B/C는 서로 다른 `supplier-a@example.com` 형태의 예시다. 기존 저장 데이터의 누락 주소는 추정하지 않는다.
3. 1차 검토의 **공급업체 확인 승인**을 누른다. ERP 저장과 서버 승인 명령이 성공한 경우에만 문의 탭과 이메일 작성 화면이 열린다. 저장 실패·409 충돌·보류는 작성 화면으로 진행하지 않는다. 승인 처리 중에는 중복 클릭과 모달 닫기를 막는다.
4. 승인 명령은 승인 기록과 문의들을 한 트랜잭션으로 저장한다. 기존 문의가 있으면 ID를 유지한다. 승인 직후 SMTP 호출은 없다.
5. 업체 선택 시 해당 업체 주소·본문·기존 초안을 불러온다. ERP 원료 코드·제품 코드·명칭·규격·단위·확보 목표량·생산 투입/희망 입고 일정·회신 기한과 단가/MOQ/분할/유효기간/품질 문서 확인 요청을 채운다. 제목·본문·허용 발신자를 수정할 수 있다. 업체 주소는 마스터에서 수정한다.
6. **초안 저장**은 서버에 저장한다. 편집 내용은 브라우저에도 문의 ID별로 보존한다. 발송 전 확인 체크 후 현재 모드의 버튼을 누른다. 승인된 서버 버전과 다른 데이터는 발송할 수 없다.
7. `sent`는 SMTP 서버 수락이다. 실제 도착·업체 회신·공급 확약은 별개이며, 발송만으로 공급 가능량이나 최종 PO를 생성하지 않는다.

연결되지 않은 Vite 단독 화면에서는 서버에 승인을 저장할 수 없으므로 승인 후 메일 단계도 진행하지 않는다. 로컬 초안과 서버 업무가 다르면 기존 통합 서버 화면에서 서버 업무를 불러와 충돌을 해결한다.

## 업체 데이터와 DB

| 위치 | 필드 | 의미 |
|---|---|---|
| 기존 워크플로 `data.vendors[]` | `id`, `quoteEmail?: string` | 업체 ID와 견적 담당자 이메일 |
| ERP 공급업체 JSON 투영 | `id`, `code`, `quote_email` | 기존 `SUP-A` 등의 ID 매핑을 유지 |
| 일반 ERP 공급업체 폼 | `quote_email` | 팀원이 일반 공급업체 마스터에서도 관리 가능 |
| 기존 `outbound_emails` | `scope` (nullable unique) | `inquiry_id:mode` 단위의 발송 잠금 |
| 동일 테이블 | `mode`, `reply_status`, `request_data` | 모드, 회신 상태, 편집된 요청 전체와 첨부 데이터 |

`0003_rfq_drafts`는 0002에서 승격한다. 기존 발송 기록은 `mode=legacy`, `scope=NULL`로 보존한다. 기존 성공은 `awaiting_reply`로 표시한다. 과거 SMTP 실패는 실제 수락 후 타임아웃일 수 있으므로 설정/입력 오류를 제외하면 `unknown`으로 보수적으로 이관한다. 기존 실제 발송/불명확 기록도 중복 발송·가상 회신 차단에 포함한다. 업체 이메일은 기존 JSON 구조에 저장하므로 별도 업체 테이블을 만들지 않았다.

## 환경변수

서버 프로세스 환경 또는 기존 실행기의 루트 `.env` / `backend/.env`에 설정한다. `.runtime/local-demo.env`는 실행기가 로컬 시연 인증을 로드할 때 사용하는 파일이며, 일반 업무 설정은 `.env`에 두는 편이 명확하다. 변경 후 API/worker를 재시작한다. 프런트엔드 `VITE_*`에는 SMTP 비밀정보를 넣지 않는다.

| 변수 | 기본값 / 동작 |
|---|---|
| `BIOFLOW_MAIL_MODE` | `preview`; `preview`, `test`, `live`만 허용. 잘못된 값도 preview |
| `BIOFLOW_MAIL_TEST_TO` | 비어 있음. test 모드의 실제 수신자 한 명 |
| `BIOFLOW_MAIL_TEST_ALLOWLIST` | 비어 있음. 쉼표로 구분한 허용 목록; TEST_TO가 포함되어야 함 |
| `BIOFLOW_SMTP_HOST`, `PORT`, `SECURITY` | 기존 SMTP; 보안 모드 starttls 또는 ssl |
| `BIOFLOW_SMTP_USERNAME`, `PASSWORD` | 기존 계정과 자격증명 |
| `BIOFLOW_SMTP_DEFAULT_FROM`, `ALLOWED_FROM` | 기본 발신자와 쉼표 구분 발신 허용 목록 |
| `BIOFLOW_SMTP_DEFAULT_TO` | 업체/테스트 수신자에는 사용하지 않는 이전 호환 설정 |

- **preview:** SMTP 설정 없이 초안과 미리보기 저장만 한다. 실제 발송·회신 대기로 기록하지 않는다.
- **test:** 원래 업체 주소와 실제 TEST_TO를 각각 화면·응답에 표시한다. SMTP 봉투와 To는 허용 TEST_TO만 사용하고, 제목/본문에 테스트 표시를 추가한다. 주소를 추정하거나 DEFAULT_TO로 대체하지 않는다. `reply_status=test_only`이며 공급 확인/공급 확약이 아니다.
- **live:** 업체별 마스터 주소로만 발송한다. 주소 누락·형식 오류와 example.com/net/org 및 `.test`, `.invalid`, localhost 주소(하위 도메인 포함)를 차단한다.
- 예시 업체 주소로 test 모드 미리보기/리디렉션은 가능하지만, 그 예시 주소 자체로는 SMTP를 호출하지 않는다. 허용 테스트 수신자로도 예시 도메인은 사용할 수 없다.

실제 수신 주소는 관리자가 직접 설정해야 한다. 이번 구현/테스트에서는 실제 이메일을 발송하지 않았다.

## 요청·응답 계약

기존 `/api/v1/mail` 및 `/api/v1/workspace` 경로를 확장했다. 모두 기존 세션 인증을 사용하며 메일과 1차 승인은 `approver` 권한이 필요하다.

### 1차 승인

`POST /api/v1/workspace/commands`

```json
{
  "command": "approveInquiry",
  "args": {"approve": true},
  "expected_revision": 3
}
```

응답은 기존 `{scenario_id, revision, workflow, stamp, data_revision, engine}`다. `workflow.approvals[0]`는 kind=1이고 인증된 담당자 이메일을 actor로 저장한다. `workflow.inquiries`에 업체별 문의가 들어 있다. `approve=false`는 보류이며 신규 문의를 만들지 않는다. 기존 문의는 이력 보존을 위해 남는다. `startInquiries` 재호출은 동일 문의를 반환한다. 문의 생성과 승인 저장 후에 클라이언트가 작성 화면을 열며 최종 구매 승인은 `registerPO`로 별도 처리한다.

### 초안 저장 / 미리보기·발송

- `PUT /api/v1/mail/quote-requests`: 초안 저장
- `POST /api/v1/mail/quote-requests`: 현재 서버 모드로 미리보기 또는 발송
- 필수 헤더 `Idempotency-Key`: 16~200자. UI는 문의 ID와 모드를 포함한 안정된 키를 재사용한다.

두 요청의 본문은 같다. 기존 요청에 **`inquiry_id`, `expected_revision`을 필수로 추가**했다. 팀원 클라이언트도 함께 갱신해야 하며 이전 형태는 422다.

```json
{
  "case_id": "PR-IL7-20261024",
  "inquiry_id": "서버가 반환한 RFQ ID",
  "expected_revision": 4,
  "vendor_id": "A",
  "vendor_name": "A · 대량 할인",
  "sender_email": "",
  "recipient_email": "supplier-a@example.com",
  "subject": "견적 요청: MAT-IL7 · PR-IL7-20261024",
  "body": "담당자가 검토하고 편집한 요청 본문",
  "material_code": "MAT-IL7",
  "material_name": "재조합 인간 IL-7",
  "unit": "바이알",
  "required_quantity": 12,
  "safety_stock": 2,
  "schedule": [
    {"production_id":"PROD-01","needed_date":"2026-11-04","quantity":4},
    {"production_id":"PROD-02","needed_date":"2026-11-11","quantity":4},
    {"production_id":"PROD-03","needed_date":"2026-11-18","quantity":4}
  ]
}
```

`sender_email`/`recipient_email`는 초안 보존을 위해 빈 문자열을 허용한다. 실제/테스트 발송에는 유효한 허용 발신자와 업체 주소가 필요하다. preview에서도 잘못된 업체 주소의 발송 동작은 422이며 초안은 남는다. 모드·실제 테스트 수신 주소는 클라이언트가 선택하지 못한다. `recipient_email`, 업체명, 원료·수량·단위·일정은 서버의 승인된 ERP와 비교한다. 제목·본문은 자유롭게 편집하되 헤더 줄바꿈을 차단한다.

성공 응답 예시:

```json
{
  "id":"발송/초안 ID",
  "case_id":"PR-IL7-20261024",
  "vendor_id":"A",
  "vendor_name":"A · 대량 할인",
  "sender":"buyer@your-company-domain",
  "recipient":"관리자가 설정한 실제 테스트 주소",
  "original_recipient":"supplier-a@example.com",
  "subject":"견적 요청 제목",
  "mode":"test",
  "status":"sent",
  "reply_status":"test_only",
  "message_id":"<SMTP Message-ID>",
  "error_code":null,
  "draft":{},
  "created_at":"ISO-8601 UTC",
  "updated_at":"ISO-8601 UTC"
}
```

실제 `draft`에는 제출한 본문 전체가 들어 있다. 이미 sent인 같은 문의/모드 요청은 발송 없이 기존 응답에 `already_sent=true`를 추가한다. 새 키를 만들어도 scope 고유 제약과 상태 잠금으로 중복 발송하지 못한다. 한 구매요청·업체의 legacy/live 발송 이력이 있으면 새 문의 ID로 우회한 live 발송도 차단한다.

- `GET /api/v1/mail/settings`: 기존 안전한 설정 + `mode`, `test_recipient`, `test_allowlist`. 비밀번호/토큰은 반환하지 않는다.
- `GET /api/v1/mail/outbox?case_id=...`: 위 응답 형태의 최근 50건. 원래 주소·실제 대상·편집 내용·상태 복구에 사용한다.
- `422`: 입력/설정/예시 주소 오류. 설정 또는 업체 마스터를 수정한다.
- `409`: 승인/버전 불일치, 다른 요청에 사용한 키, 이미 처리 중, 확인이 필요한 결과. 다른 키로 우회 재시도하지 않는다.
- SMTP 처리 후의 `failed`/`unknown`은 **200 응답의 `status`**로 반환한다. HTTP 200만으로 발송 성공으로 판단하지 말아야 한다.

## 상태 전이와 동시성

| 상태 | 의미 | 다음 동작 |
|---|---|---|
| `draft` | 서버에 편집 내용 저장 | 편집 또는 명시적 발송 |
| `preview` | 검토용 저장 완료, 실제 발송 없음 | 편집 가능; test/live 전환은 서버 설정으로 별도 scope 사용 |
| `sending` | DB에 발송 소유권 저장 후 SMTP 호출 중 | 중복 발송/초안 변경 차단; 오래 남으면 확인 필요 |
| `sent` | SMTP가 수락 | 재발송 없이 기존 결과 반환 |
| `failed` | 전송 전 오류 또는 SMTP의 명시적 거절 | 초안 유지; 원인 수정 후 담당자가 재시도 가능 |
| `unknown` | DATA 중 타임아웃/연결 종료 등 결과 불명확 | 자동/수동 버튼 재시도 모두 차단; 메일함/SMTP 기록으로 확인 |

`reply_status`는 별도로 `not_requested`(초안/미리보기), `awaiting_reply`(실제 업체 회신 대기), `test_only`(테스트), `check_required`(결과 확인 필요)를 기록한다. 발송 성공이 `공급 확인`으로 전이하지 않는다.

초안 저장과 발송 직전에 기존 workspace 버전 잠금을 확인한다. 발송 소유권은 scope 고유 제약 + 상태/updated_at 조건부 UPDATE로 획득하고 SMTP 호출 **전에 커밋**한다. 병렬 요청은 하나만 전송한다. 네트워크 응답 손실 후에는 동일 문의를 조회한다. 서버 프로세스가 종료되어 sending이 남아도 자동으로 재발송하지 않는다. 실패/성공/불명확 결과는 기존 감사 테이블에도 기록한다.

서버 `receiveReplies`는 DB의 legacy/live/test 발송 중·성공·불명확 업체를 조회해 가상 회신에서 제외한다. 브라우저도 이력 조회 실패 시 연결 모드의 가상 회신을 중단한다. 실제/테스트 발송 업체에 가상 확약을 끼워 넣은 workspace 업로드도 거절한다. 테스트 업체는 `테스트 메일 · 공급 확인 미진행`으로 구분한다.

## 실행과 검증

PowerShell, 프로젝트 루트:

```powershell
npm run build
npm test
.venv\Scripts\python.exe -m pytest -q backend/tests
.venv\Scripts\python.exe scripts/run-local.py
```

기존 실행기는 시작할 때 `alembic upgrade head`를 실행하고 `.runtime/bioflow.db`를 사용한다. 배포 DB는 기존 `DATABASE_URL`을 설정하고 backend 작업 디렉터리에서 `python -m alembic upgrade head` 후 API/worker를 재시작한다. 데이터 삭제/초기화는 필요 없다. 원래 npm의 `start:local`/`test:api`는 POSIX 가상환경 경로를 사용하므로 Windows에서는 위 직접 명령을 사용한다.

테스트는 별도 임시 DB와 모의 SMTP만 사용한다. 검증 범위: 저장된 승인 후 작성 callback 실행, 저장 실패/버전 충돌/보류 시 미실행, 업체별 자동 작성, 누락/잘못된/예시 주소 차단, 서버 수신자 변조 거절, 테스트 허용 목록과 실제 SMTP To/봉투 일치, 병렬 클릭/다른 키 중복 방지, 명시적 거절 재시도와 초안 보존, 모호한 결과 차단, 실제/테스트 업체의 가상 회신 제외, 기존 0002 데이터 보존 마이그레이션.

검증 결과: 백엔드 전체 140개, 프런트엔드 79개 통과. TypeScript 및 프로덕션 빌드 통과. 기존 Vite 큰 청크 경고와 Starlette/Alembic 사용 중단 예정 경고가 남는다. 개발자의 `.runtime/bioflow.db`에는 테스트 마이그레이션을 실행하지 않았으며, 기존 실행기 재시작 시 실제 DB 마이그레이션이 적용된다.

## 변경 파일

- 화면/워크플로: `src/workflow/FlowApp.tsx`, `engine.ts`, `quoteMail.ts`, `quoteMail.test.ts`
- 업체 정보: `src/erp/model.ts`, `store.ts`, `viewData.ts`, `src/connected/vendor/erpSchema.ts`
- 서버 연결/공유 엔진: `src/connected/connection.ts`, `connection.test.ts`, `scripts/workflow-runner.ts`
- 서버: `backend/app/main.py`, `models.py`, `schemas.py`, `db.py`, `services/workspace.py`, `services/mailer.py`, `services/quote_requests.py`
- 마이그레이션/검증: `backend/migrations/versions/0003_rfq_drafts.py`, `backend/tests/conftest.py`, `test_mailer.py`, `test_quote_requests.py`, `test_rfq_migration.py`
- 설정/문서: `.env.example`, 이 문서

Windows에서 기존 공유 엔진 subprocess의 cp949 디코딩 오류가 있어 UTF-8을 명시했다. 기존 메일 인증 테스트의 POSIX 권한 비트 검사는 Windows에 해당하지 않아 해당 플랫폼에서만 생략한다.

## 남은 한계

- SMTP는 전달/열람/실제 회신 자동 동기화를 제공하지 않는다. 실제 회신을 증빙과 함께 ERP 조건으로 반영하는 기능은 기존 범위를 따른다.
- unknown/sending의 확인·해제·재문의 운영 화면은 없다. Message-ID와 메일 서버 기록을 담당자가 확인해야 한다. 해제 없이 다른 키로 보내는 경로는 제공하지 않는다.
- 검증은 단위/서버 통합/SQLite 마이그레이션과 빌드다. 실제 SMTP 수신 확인, 브라우저 E2E, PostgreSQL 실서버 마이그레이션은 실행하지 않았다.
- 초안 자동 복원은 같은 브라우저의 저장소를 사용한다. 다른 기기와 공유하려면 초안 저장 버튼을 사용한다. 모드별 전송 결과는 DB에 분리되지만 본문 편집 초안은 문의별로 복원한다.
- 기존 Gmail 자격증명 파일의 Windows ACL 관리는 이 변경에 포함하지 않았다. 기존 방식보다 새로운 자격증명 저장 경로를 추가하지 않았다.
- 공급/품질 데이터와 회신 기한에는 기존 시연 달력과 합성 가정이 남아 있다. 실제 업무 데이터·업체 주소·일정을 검토한 뒤 명시적으로 모드를 설정해야 한다.
