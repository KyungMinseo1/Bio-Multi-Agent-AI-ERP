# CSV 원본·부족 감지·견적 요청

## 데이터와 규칙

`public/erp-csv/`에는 `materials.csv`, `production.csv`, `lots.csv`, `suppliers.csv`, `shipments.csv`, `receipts.csv` 원본이 있습니다. 초기 입고 예정은 0건으로 유지하여 기존 IL-7 계산을 바꾸지 않습니다. 화면에서 현재 원본을 내려받거나 기준 파일을 열고 편집·적용할 수 있습니다. 서버 저장 시 검증된 원본 데이터와 CSV 표현은 DB 업무 스냅샷에 보존합니다.

| 파일 | 주요 열·관계 |
| --- | --- |
| materials | 기존 원료 ID, 품명, 안전재고, 단위. 제품 상세 규격은 보존 |
| production | 생산 ID, 투입일, IL-7·IL-15 수요, 완료일, 고객 납기, 예산 |
| lots | 원료 ID 참조, 수량, QC/QA·온도 상태, 유효기간, 입고일, CoA |
| suppliers | 기존 업체 ID, 단가, MOQ·배수·운송비, 업체·제품 승인, 회신 주소 email, 리드타임 leadDays |
| shipments | vendor 참조, 회차 ID, 수량·입고·유효·지급일, 확약·QA 보류, QC 지연 |
| receipts | 기존 확약 입고 예정. material·vendor 참조, lot, 수량, 입고·유효일, confirmed·qaHold·qcDelay |

CSV는 UTF-8(BOM 허용), 쉼표 구분, RFC 4180 형태의 따옴표·개행을 지원합니다. 중복 ID·열, 잘못된 숫자·날짜·품질 상태·외래 코드·열 개수는 적용 전에 차단합니다. 숫자는 0 이상이며 수량은 정수, boolean은 `true`/`false`입니다. 기존 원료·업체 코드와 제품 규격은 유지하고 생산·Lot·회차·기존 입고 예정은 행 단위로 등록합니다.

규칙 엔진은 원료별 QC/QA·온도·유효기간을 확인한 후 날짜순으로 생산 수요를 배정합니다. 확약 입고는 QC 지연 + QC 기간 + QA 기간 이후의 예측 물량이며 현재 가용량과 구분합니다. 기존 PO·Lot와 같은 입고 ID/로트는 중복 집계하지 않습니다. 발주 검토 기한은 필요일에서 업체 리드타임, QC, QA, 검토 여유 1일을 역산합니다. 리드타임은 `leadDays`를 우선 사용하며 기존 데이터는 기준일과 첫 입고일 차이를 사용합니다.

생산계획 추가·CSV 적용·원본 편집은 revision을 갱신하고 부족 위험을 자동 재계산합니다. 동일 위험 키에 대한 알림은 중복 생성하지 않습니다. 원본 변경은 기존 견적 요청 승인과 추천의 유효성에 반영됩니다. 추가 부족에 대한 견적 요청을 승인해도 기존 PO 조건은 변경되지 않습니다.

## 승인·발송

견적 요청 1차 승인과 실제 구매 발주 승인은 별개입니다. 공급업체별 초안은 같은 ERP 버전에서 생성하고 사용자가 수신처·수량·납기·본문을 확인해야 처리할 수 있습니다. 서버는 저장된 원본과 승인을 공통 엔진으로 재검증하며 오래된 버전이나 조작된 수량·일정을 거부합니다.

실행 모드는 `simulation`, `gmail_mcp`, `smtp`입니다. 시뮬레이션은 네트워크 발송 없이 같은 검증과 DB 기록을 실행합니다. 실제 수신처는 CSV 업체 이메일 또는 서버 기본 수신 주소와 일치해야 합니다. 같은 원본 fingerprint·업체·수신처·모드의 요청은 다른 브라우저에서 다시 제출해도 중복 전송하지 않습니다. 연결 전 실패는 설정 수정 후 재시도할 수 있고, 전송 후 결과 불확실 상태는 메일함 확인 전 자동 재시도를 차단합니다.

## Gmail MCP 구성

ERP는 Python MCP SDK v1의 Streamable HTTP 클라이언트를 사용합니다. 서버 환경에 다음을 설정합니다.

```dotenv
GMAIL_MCP_URL=https://your-authorized-gmail-mcp.example/mcp
GMAIL_MCP_TOKEN=
GMAIL_MCP_PROFILE_TOOL=gmail_get_profile
GMAIL_MCP_SEND_TOOL=gmail_send_email
GMAIL_MCP_SEARCH_TOOL=gmail_search_emails
GMAIL_MCP_READ_TOOL=gmail_read_email
```

도구 계약은 `backend/app/services/gmail_mcp.py`와 `backend/app/gmail_gateway.py`에 정의되어 있습니다. profile은 이메일 주소, send는 Gmail message ID와 thread ID를 반환해야 합니다. send는 본문과 CSV 첨부의 MIME 트리를 받습니다. 도구 이름만 같고 입력 스키마가 다른 서버는 어댑터 조정이 필요합니다. 발신 주소와 연결 계정이 다르면 전송 전에 차단합니다. 연결 실패·인증 누락을 연결 완료로 표시하지 않습니다.

별도 서버가 없다면 포함된 로컬 Gmail MCP 게이트웨이를 사용할 수 있습니다.

```dotenv
BIOFLOW_GMAIL_MCP_LOCAL=1
BIOFLOW_GMAIL_MCP_PORT=4180
GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=
# 또는 단기 액세스 토큰
GMAIL_ACCESS_TOKEN=
```

사용자가 승인한 Gmail OAuth 자격증명을 서버 환경에만 등록해야 합니다. 발송에는 Gmail send, 회신 조회에는 readonly 범위가 필요합니다. 로컬 실행 스크립트가 127.0.0.1에만 MCP 서버를 띄우고 API↔MCP 전용 bearer 토큰을 `.runtime/`에 생성하여 외부 브라우저의 무인 호출을 차단합니다. `.env`의 빈 `GMAIL_MCP_URL`·`GMAIL_MCP_TOKEN`은 로컬 게이트웨이 활성화 시 자동 설정합니다.

**Codex의 Gmail 커넥터 로그인은 ERP 서버로 자동 이전되지 않습니다.** 서버용 OAuth 또는 원격 MCP 인증을 별도로 제공해야 합니다. 비밀번호나 토큰을 채팅·Git·프론트엔드 환경변수에 넣지 않습니다. 계정·스코프 설정을 완료하기 전에는 시뮬레이션으로 검증할 수 있습니다.

## 회신과 AI

발송한 요청의 수신 주소, 요청번호, thread ID가 일치하는 회신만 조회합니다. 메일 본문은 비신뢰 데이터로 표시하고 지시문으로 실행하지 않습니다. 담당자가 실제 회신에 맞춘 단가·MOQ·확약 수량·회차·유효기간을 확인한 뒤 기존 구매·재고생산·품질·재무 AI와 Orchestrator 분석으로 전달합니다. 원본이 변경됐거나 검증되지 않은 메시지 ID이면 회신 확약 등록을 거부합니다. 가상 회신은 명시적인 시뮬레이션 동작으로만 생성합니다.

## 검증

- CSV 왕복·형식·날짜·코드 관계, 추가 생산 수요, QC 지연, 중복 알림 검증
- 승인 누락·수량 위조·버전 충돌·중복 요청·불확실 전송 재시도 차단
- 실제 MCP SDK↔로컬 모의 MCP 서버의 profile·MIME send·회신 스레드 검증
- OAuth 게이트웨이 인증, 발신 계정, MIME 생성 검증 (Google 요청은 모의 처리)
- 검증된 회신 등록 이후 기존 Agent·Orchestrator 추천까지 통합 검증

실제 외부 메일은 자동 테스트에서 전송하지 않습니다. CSV 변경은 감사 이력에 기록하고 기존 발주 승인 스냅샷은 보존합니다.

## 공식 참고

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.30.0)
- [Gmail API 메일 작성·발송](https://developers.google.com/workspace/gmail/api/guides/sending)
- [Google OAuth 서버 인증](https://developers.google.com/identity/protocols/oauth2/web-server)
