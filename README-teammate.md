# Bio-Multi-Agent-AI-ERP

합성 바이오 원료 데이터로 발주 의사결정을 시연하는 독립 웹 ERP. 상황·부족량·만료 위험 → 기본 발주안 A/B/C → 구매·재고/생산계획·품질·재무 AI 병렬 검토 → Orchestrator 통합 선정 → 담당자 선택·승인 → **내부 발주 등록**을 수행한다. 공급업체에 주문을 전송하지 않으며, 발주 승인은 QC/QA 사용 승인이 아니다.

## 실행

Docker Desktop의 Linux containers와 Compose v2가 필요하다.

1. `.env.example`을 `.env`로 복사한다.
2. `POSTGRES_PASSWORD`, `SESSION_SECRET`, `INITIAL_APPROVER_EMAIL`, `INITIAL_APPROVER_PASSWORD`를 직접 설정한다. 저장소 기본 비밀번호는 없다. `SESSION_SECRET`은 충분히 긴 난수 문자열을 사용한다. DB 연결 URL에 들어가는 비밀번호는 영숫자 난수를 권장한다.
3. 프로젝트 루트에서 실행한다.

```sh
docker compose up -d db
docker compose run --build --rm api alembic upgrade head
docker compose run --rm api python -m app.seed --scenario scenario_1
docker compose up --build -d api worker web
```

접속: http://localhost:8080 . `.env`에 지정한 계정으로 로그인한다. API와 worker는 마이그레이션 완료 후 시작해야 한다. PostgreSQL 데이터는 named volume에 남으며 seed 재실행은 기존 입력을 초기화하지 않는다. 초기 계정 환경변수 변경은 기존 계정 비밀번호 변경 절차를 대신하지 않는다.

## 시나리오 선택

화면 상단에서 선택하며 선택값은 브라우저에 보존한다. ERP 데이터·revision·토론·발주는 시나리오별로 분리한다. 시나리오를 바꾸어도 다른 시나리오의 사용자 입력을 삭제하지 않는다.

| ID | 배경 | 확인할 동작 |
|---|---|---|
| `scenario_1` | IL-7 분할 발주 | 장부 6개, 생산 가용 2개, 신규 필요 12개; B의 4개씩 3회 입고 |
| `scenario_1_qc_bottleneck` | 독립 IL-7 QC 병목 변형 | B 두 번째 사용 가능일 11월 12일, 11월 11일 생산 부족 |
| `baseline` | 별도 CHO 배지 배경 | 온도별 원료와 품질·보관·예산 제약 |

`PLANNING_AS_OF=2026-10-24`는 재현용 고정 기준일이다. 실제 날짜로 운영하려면 이 값을 제거한다. 모든 공급업체·견적·제품 승인·재고는 합성이다. IL-7/IL-15 SKU·함량·보관 조건은 명시적 프로토타입 가정이며 실제 제품 규격이나 임상 제조 적합성을 주장하지 않는다.

### 새 scenario_* 추가

1. `backend/app/scenarios/`에 기존 `seeds.py`와 같은 형태의 factory를 작성한다. 매 호출마다 새 데이터 사전을 반환한다.
2. `backend/app/scenarios/__init__.py`에서 아래처럼 등록한다.

```python
register_scenario("scenario_2", "화면에 보일 이름", "배경과 검증 목표", scenario_two)
```

3. 기존 데이터 구조의 원료·Lot·수요·견적·예산·자원 참조를 채운다. UUID는 로드 시 시나리오 namespace로 분리된다. 합성 여부·기준일·수량 문자열·근거를 명시한다.
4. 필요하면 `python -m app.seed --scenario scenario_2`로 선입력한다. 선택 목록은 서버 registry를 읽으므로 프런트엔드 수정은 필요 없다.

문서 파일만 추가해도 실행 데이터로 자동 변환되는 방식은 아니다. 계산 가능한 구조화 데이터 factory 등록이 필요하다.

## LLM 설정

선택한 공급자의 **정확한 모델 ID와 연결 설정**을 `.env`에 설정한다. 모델 기본값이나 자동 공급자 전환, 가짜 토론 응답은 없다. API 키는 OpenAI·Gemini·OpenRouter에서 필수이며 인증 없는 자체 호스팅 서버에서는 선택 사항이다.

- `LLM_PROVIDER=openai`: `OPENAI_API_KEY`, `OPENAI_MODEL` — OpenAI **Responses API**를 사용한다. `OPENAI_BASE_URL`은 선택적 endpoint 재정의이며 Chat Completions 전용 서버용 설정이 아니다.
- `LLM_PROVIDER=gemini`: `GEMINI_API_KEY`, `GEMINI_MODEL`
- `LLM_PROVIDER=openrouter`: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, 선택적 `OPENROUTER_BASE_URL`
- `LLM_PROVIDER=vllm`: `VLLM_BASE_URL`(`/v1`로 끝나는 주소), `VLLM_MODEL`, 필요한 경우 `VLLM_API_KEY` — 기존과 동일하게 외부 서버의 Chat Completions API를 사용한다.
- `LLM_PROVIDER=openai_compatible`: `OPENAI_COMPATIBLE_BASE_URL`(`/v1`로 끝나는 주소), `OPENAI_COMPATIBLE_MODEL`, 필요한 경우 `OPENAI_COMPATIBLE_API_KEY` — 일반 OpenAI 호환 서버의 `/v1/chat/completions`를 사용한다.

vLLM 모델은 이 ERP 프로세스 안에서 로드하지 않는다. 별도 추론 서버에서 예를 들어 `vllm serve <model-id> --host 0.0.0.0 --port 8000 --tensor-parallel-size 2`를 실행한다. `--tensor-parallel-size`는 추론 서버의 GPU 구성 옵션이며 ERP 환경변수가 아니다. API와 worker가 모두 접근할 수 있는 주소(예: `http://inference-host:8000/v1`)와 해당 서버가 제공하는 모델 ID를 설정한다. 컨테이너의 `localhost`는 컨테이너 자체를 가리키므로 외부 추론 서버 주소로 바꾼다. **URL만으로는 부족하며 모델 ID도 필수**다. vLLM 서버를 일반 호환 공급자 또는 기존 `vllm` 공급자로 연결할 수 있다.

Chat Completions 공급자(vLLM·일반 호환 API·OpenRouter)는 `response_format.type=json_schema`, `json_schema.strict=true`를 지원해야 한다. 단순 텍스트 생성이나 JSON 모드만 지원하는 endpoint는 충분하지 않다. 반환 결과는 서버에서 JSON Schema와 업무 스키마로 다시 검증하며, 지원하지 않거나 형식이 틀리면 실패로 남긴다. 구조화 출력을 제거하거나 합성 응답으로 우회하지 않는다.

`LLM_ROLE_MAPPING`은 역할별 공급자/모델 JSON 설정이다. 키는 환경변수에만 두며 화면에는 설정 여부만 표시한다. 토론 실행에는 API 외에 worker가 필요하다. 미설정·인증 실패·타임아웃·잘못된 구조화 응답은 실패로 표시한다.

예: `LLM_ROLE_MAPPING={"quality":{"provider":"gemini","model":"사용할-모델-ID","reasoning_effort":"auto"},"finance":{"provider":"openai","model":"사용할-모델-ID"}}`. 나머지 역할은 `LLM_PROVIDER`와 해당 공급자의 모델 설정을 사용한다. 각 역할에 `base_url`, `timeout`을 지정하면 기본 URL·공통 제한 시간을 재정의한다. API 키는 해당 공급자의 환경변수에서만 읽는다. 활성 역할 키는 `purchasing`, `inventory_planning`, `quality`, `finance`, `orchestrator`이다. 이전의 분리된 재고·생산·QC·QA 역할 매핑은 새 역할로 변경해야 한다.

요청 제한 시간은 역할별 `LLM_ROLE_MAPPING`의 `timeout`(초)이 최우선이다. 명시하지 않으면 Orchestrator는 `LLM_ORCHESTRATOR_TIMEOUT_SECONDS=180`, 나머지 네 AI는 `LLM_TIMEOUT_SECONDS=60`을 사용한다. 제한 시간은 목표 응답 시간이 아닌 실패를 감지하는 상한이다. `.env` 변경 후 API와 worker를 모두 재시작해야 한다(Compose는 환경변수를 다시 읽도록 컨테이너를 재생성). 비동기 LLM 요청의 시간초과는 해당 호출 실패이며 서버 전체의 장애를 뜻하지 않는다. 시간초과 후 자동 재시도·추가 축약·검증 우회는 하지 않는다.

이전 활성 역할 `admin`은 `orchestrator`로 변경해야 하며 설정 호환 별칭은 없다. 저장된 과거 스냅샷·메시지·오류는 수정하지 않는다. 과거 `admin`은 `Admin (이전 통합 역할)`로 표시하고 현재 검토 AI나 검토 라운드 수 산정에 포함하지 않는다.

### 빠른 판단과 추론 강도

`LLM_REASONING_EFFORT=low`는 네 검토 AI와 Orchestrator 모두에 낮은 추론 강도를 요청한다. 프롬프트의 짧은 답변 지시와 달리 실제 API의 추론 제어를 사용한다. 허용값은 `auto`, `low`, `medium`, `high`이며 역할별 `LLM_ROLE_MAPPING`의 `reasoning_effort`가 우선한다. 예: `{"orchestrator":{"reasoning_effort":"low"}}`. `auto`는 API 제어값을 생략해 모델 기본값을 쓰며 **추론 비활성화가 아니다**. 환경변수를 생략하면 `auto`다. 설정 화면에서 역할별 실제 설정을 확인한다.

OpenAI Responses에는 `reasoning.effort`, OpenAI 호환 Chat Completions·OpenRouter·vLLM에는 `reasoning_effort`를 전달한다. 모델과 서버의 지원이 필요하며 지원하지 않는 조합은 역할별 `auto`로 설정한다. 오류를 숨기거나 다른 모델로 전환하지 않는다. 낮은 추론은 속도·비용과 판단 깊이의 절충이며 고정 응답 시간을 보장하지 않는다. 공식 계약: [OpenAI reasoning effort](https://developers.openai.com/api/docs/guides/reasoning).

현재 네이티브 Gemini 어댑터는 `auto`만 지원한다. Gemini는 모델 세대별로 `thinking_level`과 `thinking_budget` 계약이 달라 동일한 제어값으로 추정 변환하지 않는다. 전역 `low`와 Gemini 역할을 함께 사용할 때 해당 역할에 `"reasoning_effort":"auto"`를 명시한다. 명시적 비자동 강도는 호출 전 설정 오류로 차단한다. [Gemini 모델별 추론 제어](https://ai.google.dev/gemini-api/docs/openai).

네 검토 AI는 ERP 전체가 아니라 **자기 부서 ERP 데이터**와 공통 목표(원료 부족 상황), 후보별 역할 관련 수치만 받는다(`ROLE_DATA`, `CANDIDATE_FIELDS`). 통합 단계는 ERP 레코드를 받지 않는다. **모든 회차의 구조화된 검토 결과**(결론·찬반/정보 부족·비교 이유·요청 조치·수치 영향·근거 참조)와 후보 표(ID·이름·수량·비용·적격성 검증)만 전달하며 원료는 이름·코드만 포함한다. 근거 인용은 검토 AI가 실제로 인용한 ID로 한정한다. 사실 확인은 각 부서 AI가, 수치·제약은 서버가 결정적으로 검증하므로 Orchestrator는 의견 통합과 우선순위에 집중한다. 대신 부서 AI의 근거 없는 단정을 Orchestrator가 원본으로 걸러내지 못하므로 미확인 주장은 확인 조건으로 남긴다. 별도 LLM 요약 호출 없이 결정적으로 구성하며 후보·검토 회차·이견을 임의로 잘라내지 않는다. 원본 스냅샷은 실행 기록에 보존하고 최종 추천은 서버가 원본으로 재검증한다.

### 병렬 검토 횟수

`LLM_REVIEW_ROUNDS=1`이 기본이며 허용 범위는 정수 1–5다. 잘못된 값은 실행 전에 설정 오류로 표시한다. 구매 AI도 다른 세 AI와 동시에 같은 발주안들을 검토하며 선행 제안 단계를 만들지 않는다. `2`이면 네 AI가 첫 회차 전체 의견을 공유받아 다시 병렬 검토하고, 모든 회차가 끝난 뒤 Orchestrator가 전체 검토 결과와 간결한 검증 자료·잔여 이견으로 최적 제안을 선정한다. 실행 생성 시 횟수를 스냅샷에 저장하므로 대기 중 환경변수가 바뀌어도 해당 실행의 횟수는 바뀌지 않는다. 정상 호출 수는 `4 × 회차 + Orchestrator 1회`이며 구조화 응답 교정 호출은 별도다.

대시보드 기본안은 검토 전 수량·비용·회차별 일정·예상 폐기를 비교하는 자료다. 추천·적합성·순위 레이블은 붙이지 않으며, 실제 검토 후 Orchestrator 결과에서만 추천 이유와 위험을 표시한다.

### AI 응답과 근거 계약

- 첫 병렬 회차는 다른 AI 의견을 보지 않은 **독립 비교**다. 구매 AI도 자기 의견을 제안하며 다른 AI의 제안을 수용했다고 쓰지 않는다. 이후 회차에서만 제공된 실제 이전 의견을 참고한다. 같은 결론은 허용하되 역할별 근거와 트레이드오프를 제시하고 억지 이견을 만들지 않는다.
- 검토 AI는 판단만 출력한다(`ReviewTurn`: `position`·`candidate_ids`·`summary`·`reasons`·`change_requests`·`evidence_refs`·`metrics`). `candidate_ids`는 우선하거나 조건부로 수용하는 안만 담고 전체를 나열하지 않는다. `metrics`는 판단에 결정적인 지표 이름만 고르며 값은 서버가 계산 결과에서 채운다. 역할·전략 ID·회차도 서버가 붙여 기존 저장 구조(`proposal.summary`·`impacts` 등)로 저장하므로 UI와 Orchestrator 입력은 바뀌지 않는다. `summary`는 검토 결론/판단 보류, `reasons`는 역할별 대안 비교 근거, `change_requests`는 남은 조건·위험과 구체적인 확인/수정 요청이다. 핵심 근거 부족 시 `needs_information`을 사용한다. UI의 `검토상 수용`은 역할 자신의 판단이지 AI 간 합의 완료가 아니다.
- 구매는 MOQ·구매 조건·확약, 재고/생산계획은 투입별 가용량·만료·지연 취약 구간, 품질은 시험·승인·문서·슬롯, 재무는 총비용·예산·실제 지급 일정에 집중한다. 분할입고만으로 분할지급이나 현금흐름 개선을 추론하지 않는다.
- 미래 일정은 등록 공급·시험·처리능력 가정이 유지될 때의 예측이다. 공통 승인 안내를 각 근거에 반복하지 않고 역할별로 중요한 조건만 남긴다. Orchestrator는 다수 동의를 사실로 취급하지 않고 전체 비교·미확인 사항을 통합한다.
- 추가 예산 승인이 필요한 안과 필수조건·투입 일정·현금 제약을 위반한 안을 구분한다. 예산 초과만으로 부적격이라고 하지 않으며 다른 적격안이 있는 상태에서 `유일한 적격안`이라고 단정하지 않는다. Lot별 만료·실제 품질 문서와 미래 가정을 구분한다. Orchestrator는 제공된 검증 자료와 역할별 주장을 대조하고 서버는 추천을 원본 스냅샷으로 재검증한다.
- 매 요청의 `reference_contract`에 허용 `evidence_ids`, `candidate_ids`, `message_ids`, `strategy_ids`를 명시한다. 코드·이름·URL·JSON 경로를 ID로 사용하지 않는다. 서버의 실제 ID·수치·적격안 검증은 유지한다.
- 공급자 호출 직전 모든 UUID를 짧은 별칭(`R1`, `R2`…, 데이터에 같은 표기가 있으면 `RR1`…)으로 바꾸고, 응답의 ID 필드와 본문에 나온 알려진 별칭을 원래 UUID로 복원한다. UUID 하나가 수십 토큰이고 오복사가 잦았기 때문이다. 모델이 만든 없는 별칭은 그대로 남아 근거·숫자 검증에서 거부된다. 저장·검증·UI는 원래 UUID와 등록 이름을 사용한다.
- Orchestrator의 수치 `impacts`는 후보별 `impact_contract`의 metric/value를 그대로 인용한다. `quantity`는 주문 수량이고 `purchase/transport/storage/testing/disposal/subtotal/total`은 금액이다. 특히 `disposal`은 폐기 개수가 아니다. 지원하지 않는 예상 잔량·폐기 수량을 금액 필드에 넣지 않으며, 수치 오류 교정 시 반환값·기대값·단위 의미를 함께 제공한다.
- 날짜·입고 횟수·금액 등 숫자를 요약·비교 이유·확인 요청 본문에 쓰지 않는다. 본문에서 안과 레코드는 `reference_contract`의 ID로만 지칭하고, 서버가 ID를 등록된 이름(후보명, 레코드 코드·Lot 코드·이름)으로 바꿔 저장한다. 시나리오별 안 이름 규칙(A/B/C 등)을 가정하지 않는다. 서버가 이름을 찾지 못한 ID는 본문에 그대로 남아 숫자 검증에서 거부된다. 렌더링된 이름과 제공된 코드는 숫자를 포함해도 허용하지만 순수 숫자는 식별자로 인정하지 않는다. 조건을 생략하거나 검증을 완화해 속도를 얻지 않는다.
- 검토 AI에는 적격안(필수조건·투입 일정·현금 제약 통과)만 역할별 상세 필드를 주고, 부적격안은 이름·비용·검증 결과만 준다. 검토 AI는 수치 값 표(`impact_contract`)를 받지 않는다.
- 잘못된 근거 ID가 반환되면 해당 값이 오류에 포함된다. 교정 요청에는 거부된 구조화 응답과 허용 ID 목록·오류를 함께 전달하며 한 번만 교정한다. 계속 실패하면 검토는 실패하며 가짜 인용·추천으로 대체하지 않는다. 일반 문장의 의미적 정확성은 프롬프트만으로 보장되지 않으며 원본 근거와 담당자 검토가 필요하다.

프롬프트 변경은 **새 검토 실행부터** 적용된다. 기존에 저장된 AI 답변·실패 기록은 덮어쓰지 않는다.

### 외부 vLLM 서버 연결 예

GPU 서버에서 모델을 먼저 실행한다. 다음 모델 경로·GPU 수·API 키는 배포 환경에 맞게 바꾼다.

```sh
vllm serve /models/your-model --served-model-name bio-erp --host 0.0.0.0 --port 8000 --tensor-parallel-size 2 --api-key YOUR_SERVER_KEY
```

ERP의 `.env`에는 **API와 worker에서 접근 가능한 GPU 서버 주소**를 쓴다.

```dotenv
LLM_PROVIDER=vllm
VLLM_BASE_URL=http://192.168.0.50:8000/v1
VLLM_MODEL=bio-erp
VLLM_API_KEY=YOUR_SERVER_KEY
LLM_REVIEW_ROUNDS=1
LLM_TIMEOUT_SECONDS=60
LLM_ORCHESTRATOR_TIMEOUT_SECONDS=180
LLM_ROLE_MAPPING={}
```

`192.168.0.50`은 예시이므로 실제 서버 IP/DNS로 바꾼다. Docker Desktop과 같은 호스트에서 vLLM을 실행하면 `http://host.docker.internal:8000/v1`을 사용한다. 인증 없는 서버는 `--api-key`를 생략하고 `VLLM_API_KEY=`로 둔다. GPU 한 개이면 병렬 크기를 `1`로 바꾼다. `VLLM_MODEL`은 모델 경로가 아니라 위 `--served-model-name`과 일치해야 한다.

서버 접근과 모델 이름은 `curl -H "Authorization: Bearer YOUR_SERVER_KEY" http://192.168.0.50:8000/v1/models`로 확인할 수 있다. 모델 목록 조회 성공만으로 구조화 응답 지원이 검증되지는 않는다. 실제 검토 실행에도 strict JSON Schema 지원이 필요하다. API 키를 쓰는 외부 연결은 신뢰된 사설망 또는 HTTPS로 보호하고 포트를 공개 노출하지 않는다.

환경변수 변경 후 `docker compose up -d --build api worker web`으로 반영한다. 일반 OpenAI 호환 서버라면 `LLM_PROVIDER=openai_compatible` 및 `OPENAI_COMPATIBLE_BASE_URL`, `OPENAI_COMPATIBLE_MODEL`, `OPENAI_COMPATIBLE_API_KEY`에 같은 값을 설정한다.

## 검증과 개발

백엔드 Python 3.12 이상, 프런트엔드 Node.js 22 권장.

```sh
python -m pip install -r backend/requirements.txt
cd backend
# 로컬 .env에는 DATABASE_URL=sqlite:///./bioerp.db 추가
python -m dotenv -f ../.env run -- alembic upgrade head
python -m dotenv -f ../.env run -- python -m app.seed --scenario scenario_1
python -m uvicorn app.main:app --env-file ../.env --port 8000
# 별도 터미널, backend 디렉터리
python -m dotenv -f ../.env run -- python -m app.worker
```

```sh
cd frontend
npm ci
npm run dev
```

개발 UI: http://localhost:5173 . Vite가 `/api`를 localhost:8000으로 프록시한다. SQLite는 단일 개발 환경용이고, 다중 프로세스 운영은 Compose의 PostgreSQL을 사용한다.

Windows에서 8000 포트 바인딩이 `WinError 10013`으로 거부되면 API를 `--port 18000`으로 실행하고 프런트엔드 실행 환경에 `VITE_API_PROXY=http://127.0.0.1:18000`을 설정한다. 프런트엔드 접속 origin도 `ALLOWED_ORIGINS`에 포함한다.

```sh
cd backend
python -m pytest -q
cd ../frontend
npm run build
```

공식 외부 소스는 설정 화면에서 수집 상태와 오류를 확인한다. 실제 공지를 합성 업체에 자동 연결하지 않는다. 관련성 확인과 품질 영향 확정을 구분하며, 승인 직전 필수 수집이 실패하면 내부 PO를 만들지 않는다. 외부 소스가 전체 공급망 이슈를 포착한다고 보장하지 않는다.

### 이번 구현의 실행 확인

- 백엔드 테스트 110개 통과. 설치된 Starlette/httpx 조합의 기존 deprecation warning 2건이 남는다. 역할별 시간제한·추론 강도·override·잘못된 설정, 검토 AI의 역할별 ERP 데이터 한정과 부적격안 요약, 검토 AI 출력의 서버 측 역할·수치 채움, UUID 별칭 왕복(본문 포함)과 없는 별칭 보존, 본문 ID의 이름 렌더링과 미등록 ID 거부, 토론 결과 기반 통합의 모든 회차·이견 보존과 검토 AI가 인용하지 않은 근거 거부, 원본 데이터 기반 최종 현금 제약 차단을 포함한다.
- TypeScript 검사 및 Vite production build 통과.
- 임시 SQLite DB에서 마이그레이션·계정 로그인·실제 API/worker 실행 확인.
- 실제 브라우저에서 시나리오 선택/새로고침 유지, 견적 폼 저장, 독립 시나리오 데이터 불변, 미설정 LLM 오류 표시 확인.
- 반복 seed가 수정한 견적과 revision을 보존함을 확인.
- 공식 MedWatch 수동 수집 20건 저장, worker의 openFDA 및 공급업체 RSS 실제 동기화 성공과 DB 작업 완료 상태 확인.
- 프롬프트 변경 후 현재 설정된 OpenAI 호환 서버를 실제 호출해, 독립 임시 SQLite DB의 IL-7 스냅샷으로 네 AI 검토·Admin 통합·추천 저장(`awaiting_review`)까지 확인했다. 사용자 ERP 데이터·발주·예산은 변경하지 않았다. 별도 vLLM 서버와 실제 추천을 이용한 브라우저 승인 완료는 검증하지 않았다.
- backend(Python 3.12)·frontend(Node 22/nginx) Docker 이미지 빌드 성공. 별도 PostgreSQL 16 컨테이너에 마이그레이션·seed 후 API/worker/nginx 컨테이너를 연결해 로그인·견적 수정·재계산·브라우저 대시보드 반영 및 DB의 worker 작업 완료를 확인했다. Compose 명령 전체를 그대로 실행한 검증과는 구별한다.
- 컨테이너의 실제 외부 수집에서 MedWatch가 HTTP 404를 반환했던 원인은 FDA의 봇 차단이었다. 연락처 URL이 없는 수집기 User-Agent를 `abuse-detection-apology` 페이지로 리다이렉트한다. User-Agent에 프로젝트 URL(`+https://github.com/...`)을 넣은 뒤 컨테이너에서 MedWatch 20건·openFDA·공급업체 RSS 동기화가 모두 완료됐다. 실패 상태는 DB에 남으며 이 상태에서는 승인 직전 최신 정보 확인 조건을 충족하지 못한다. 공개 소스의 차단 정책이 바뀌면 다시 실패할 수 있다.
- 상황 우선 UI의 이전 확인에서는 잠정 후보 기본 접힘을 검증했으며, 현재 흐름은 기본 A/B/C를 즉시 표시하고 복수 공급·추가 분할 파생안만 접는다. 계산 기준 IL-7 장부 6·생산 가용 2·수요 12·추가 필요량 12, 실제 발주일 미정을 유지한다.
- 임시 로컬 HTTP 서버로 `vllm`·`openai_compatible`의 `/v1/chat/completions`, 모델 ID·strict JSON Schema 전송, 정상 응답 파싱 및 잘못된 구조화 응답 거부를 확인했다. 네 AI 동시 도착 barrier를 둔 별도 HTTP 스모크에서 고정 1/2회 실행이 각각 5/9회 호출하고, Admin이 전체 4/8개 의견을 받은 후 추천을 저장함을 확인했다. 환경변수를 실행 전 5로 바꿔도 생성 시 고정한 회차가 유지됐다. 로컬 응답 fixture이며 실제 모델 추론 증거가 아니다.
- 병렬 검토 전환 후 Compose 재빌드·기동과 TypeScript/Vite 빌드 성공. 브라우저에서 기본 A/B/C가 견적 코드 순으로 즉시 표시되고 추천 강조 없이 수량·비용·회차별 일정을 보여주는 것, 파생안 기본 접힘, 1회 설정과 다섯 역할 매핑, 새 병렬 검토 진입 화면을 확인했다. 390px 화면에서 문서 가로 폭은 390px이며 브라우저 오류 기록은 없었다.
- 답변 제약 변경 후 브라우저에서 기존 저장 기록의 새 `검토상 수용` 표시와 `수치 영향 · 남은 조건과 요청 조치` 영역을 확인했다. 과거 답변 본문은 수정하지 않는다. 실제 생성에서는 품질 AI가 A/B 시험 부담을 비교하고 Lot별 CoA·시험·QA 서명 확인을 요청했으며 근거 검증을 통과했다. 이는 개별 실행의 관찰이며 모든 자연어 주장의 정확성을 보장하지 않는다.
- 중간 실제 생성 실행에서 재고/생산계획 AI의 `disposal` 수치 불일치를 검증기가 차단했다. 후보별 수치 계약·금액/수량 단위 설명과 구체적 교정 정보를 추가한 최종 실행에서는 네 AI와 Admin이 검증을 통과하고 B 우선·A 대안의 추천 2개를 저장했다. A의 추가 예산 승인 조건도 별도로 설명했다. 성공 한 번을 모든 향후 호출의 성공 보장으로 취급하지 않는다.
- `admin` 시간초과 실패 기록에서 통합 시작 후 약 60초에 실패했음을 확인했다. 활성 역할은 `orchestrator`로 전환하고 검토 AI 60초·Orchestrator 180초를 분리했다. Compose 재빌드·기동과 브라우저의 역할별 실제 제한 시간·Orchestrator 화면 표시를 확인했다. 과거 실행의 `admin` 메시지·오류는 원본 그대로 보존한다.
- 기존 실패 실행의 네 AI 의견과 전체 스냅샷·계산 근거를 읽어 독립 임시 DB에서 새 `orchestrator` 호출을 수행했다. 실제 OpenAI 호환 모델 응답이 103.32초 후 검증을 통과했고 추천 2개를 반환했다. 적용 제한은 Orchestrator 180초·검토 AI 60초이며, 사용자 DB·기존 실패 기록·발주·예산은 수정하지 않았다. 이 검증은 새 통합 호출이며 전체 검토 AI 재실행·사용자 최종 승인까지의 검증과 구별한다.
- 빠른 판단 설정 후 Compose 재빌드·API/worker/web 기동과 TypeScript/Vite 빌드를 확인했다. 브라우저에서 다섯 역할 모두 `추론 강도 low`, 기존 역할별 제한 시간, 환경변수·호환성 안내를 확인했다. 390px 화면의 가로 넘침과 브라우저 오류는 관찰되지 않았다.
- 마지막 교정은 프롬프트만 변경했다. 허용 ID를 글자 그대로 복사하고 잘못된 UUID를 임의 수정하지 않도록 지시했으며, 본문 날짜·횟수 중복을 금지했다. 스키마·검증·제한 시간은 유지했다. 실제 동시 검토에서 구매 24.74초·재무 23.59초 응답은 검증을 통과했으나 재고/생산계획·품질은 60초에 시간초과되어 전체 실행은 실패했다. 프롬프트만으로 전체 완료나 일정한 지연을 보장하지 않는다.
- 같은 저장 실행의 네 검토 결과로 통합 단계를 따로 실제 호출했다. compact 사용자 입력은 63,748자이며 기존 전체 문맥 구성은 191,635자였다(토큰 수가 아님). `reasoning_effort=low`가 실제 HTTP 요청에 포함됐고 Orchestrator가 교정 호출 없이 29.96초에 응답했다. `needs_information`과 미확인 품질 문서를 보존한 조건부 B 추천이 근거·수치·원본 적격성 재검증을 통과했다. 이전 103.32초와 현재 값은 개별 호출 관찰이며 전체 실행 성공 증거가 아니다. 사용자 DB·발주·예산은 변경하지 않았다.
- 검토 AI 입력을 역할별 ERP 데이터로 한정했다. 같은 저장 실행 기준 검토 AI 문맥이 약 83,000자에서 28,509–45,172자로 줄었고, 실제 동시 검토에서 재무 20초·구매 26초·재고/생산계획 33초에 통과했다. 품질은 60초 시간초과였다. 품질 단독 호출은 35.95초로 통과했으며 입력 22,009토큰·출력 1,911토큰·추론 88토큰, 첫 토큰 3.38초였다. 지연의 대부분은 구조화 출력 생성이며 네 요청 동시 처리 시 60초를 넘는다.
- Orchestrator를 토론 결과 + 후보 표만 받도록 바꿨다. 같은 실행의 저장된 검토 3건으로 실제 호출한 결과 전체 입력이 27,413자였고 42.09초에 교정 없이 검증을 통과해 B 우선·A 조건부 대안을 반환했다. 입력 감소가 응답 시간 감소를 보장하지 않으며 출력 길이가 주요 요인이다.
- 검토 AI 전용 출력(`ReviewTurn`)과 UUID 별칭을 적용했다. 재무 시간초과가 난 같은 저장 실행으로 실제 vLLM에 네 AI를 동시 호출하자 각 9.08–13.01초(동시 실행 전체 13.26초)에 교정 없이 통과했고 출력은 906–1,304자였다(이전 2,182–4,054자). 이어 Orchestrator가 26.24초에 통과해 B 우선·A·C 조건부 대안을 반환했다. 두 차례 실행의 관찰이며 고정 지연을 보장하지 않는다.
- 프롬프트에서 시나리오 전제(A/B/C 안 이름, IL-7 예시)를 제거하고 본문 ID를 서버가 등록 이름으로 렌더링하도록 바꿨다. 이전에는 CHO 배지 시나리오(원료 3종·후보 64개)에서 모델이 본문에 별칭(`R84`)을 써 구매·재고·품질이 숫자 검증에 실패했다. 변경 후 같은 저장 실행으로 실제 vLLM 전체 흐름을 실행하자 검토 AI 동시 실행이 21.91초(구매 교정 1회 포함), Orchestrator가 21.69초에 통과했다. IL-7 실행도 검토 13.16초·Orchestrator 18.06초에 교정 없이 통과했다. CHO 검토 입력은 약 14만 자로 IL-7보다 크다.

## 계산 주의사항

- 금액·수량은 Decimal 계산 및 API 소수 문자열을 사용한다.
- QC/QA 완료 예상은 현재 확정 가용 재고와 다르다. 유효일 당일까지 사용 가능하다.
- FEFO를 적용한 A안은 20개 구매 후 총 10개 잔여이지만, 구성은 신규 단기 유효 8개 + 기존 장기 유효 2개다. 따라서 11월 말 예상 폐기는 8개다. 원래 시나리오의 전량 10개 폐기 설명은 이 규칙에 맞게 수정했다.
- B안 구매+운송은 12,300,000원이며 보관·시험·폐기를 더한 총비용과 구별한다.

요구사항과 배경: [구현 계획](docs/PLAN.md), [IL-7 시나리오](docs/scenario_1.md).
