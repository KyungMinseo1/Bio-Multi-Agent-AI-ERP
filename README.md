# Bio-Multi-Agent-AI-ERP

합성 바이오 원료 데이터로 발주 의사결정을 시연하는 독립 웹 ERP. 한국어 화면에서 시나리오 선택 → ERP 입력 → 수치 검증 → 실제 LLM 부서 협의 → 사람 승인 → **내부 발주 등록**을 수행한다. 공급업체에 주문을 전송하지 않으며, 발주 승인은 QC/QA 사용 승인이 아니다.

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

선택한 공급자의 키와 **모델 ID를 모두** `.env`에 설정한다. 모델 기본값이나 자동 공급자 전환, 가짜 토론 응답은 없다.

- `LLM_PROVIDER=openai`: `OPENAI_API_KEY`, `OPENAI_MODEL`
- `LLM_PROVIDER=gemini`: `GEMINI_API_KEY`, `GEMINI_MODEL`
- `LLM_PROVIDER=openrouter`: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`
- `LLM_PROVIDER=vllm`: `VLLM_BASE_URL`(`/v1` 포함), `VLLM_MODEL`, 필요한 경우 `VLLM_API_KEY`

`LLM_ROLE_MAPPING`은 역할별 공급자/모델 JSON 설정이다. 키는 환경변수에만 두며 화면에는 설정 여부만 표시한다. 토론 실행에는 API 외에 worker가 필요하다. 미설정·인증 실패·타임아웃·잘못된 구조화 응답은 실패로 표시한다.

예: `LLM_ROLE_MAPPING={"qc":{"provider":"gemini","model":"사용할-모델-ID"},"finance":{"provider":"openai","model":"사용할-모델-ID"}}`. 나머지 역할은 `LLM_PROVIDER`와 해당 공급자의 모델 설정을 사용한다. 역할 키는 `purchasing`, `inventory_logistics`, `production_management`, `production`, `qc`, `qa`, `finance`, `admin`이다.

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

- 백엔드 테스트 40개 통과. 설치된 Starlette/httpx 조합에서 의존성 deprecation warning 2건이 남는다.
- TypeScript 검사 및 Vite production build 통과.
- 임시 SQLite DB에서 마이그레이션·계정 로그인·실제 API/worker 실행 확인.
- 실제 브라우저에서 시나리오 선택/새로고침 유지, 견적 폼 저장, 독립 시나리오 데이터 불변, 미설정 LLM 오류 표시 확인.
- 반복 seed가 수정한 견적과 revision을 보존함을 확인.
- 공식 MedWatch 수동 수집 20건 저장, worker의 openFDA 및 공급업체 RSS 실제 동기화 성공과 DB 작업 완료 상태 확인.
- 실제 LLM 인증 정보와 vLLM 서버는 제공되지 않아 실제 여덟 역할 협의 및 그 결과를 이용한 브라우저 승인 완료는 검증하지 않았다. 승인 트랜잭션은 격리된 회귀 테스트로 검증했으며 실제 LLM 연동 증거와 구별한다.
- backend(Python 3.12)·frontend(Node 22/nginx) Docker 이미지 빌드 성공. 별도 PostgreSQL 16 컨테이너에 마이그레이션·seed 후 API/worker/nginx 컨테이너를 연결해 로그인·견적 수정·재계산·브라우저 대시보드 반영 및 DB의 worker 작업 완료를 확인했다. Compose 명령 전체를 그대로 실행한 검증과는 구별한다.
- 컨테이너의 실제 외부 수집에서는 openFDA·공급업체 RSS가 성공했지만 MedWatch가 HTTP 404를 반환했다. 실패 상태가 DB에 남으며 이 상태에서는 승인 직전 최신 정보 확인 조건을 충족하지 못한다. 호스트 수집 성공이 모든 실행 환경에서의 소스 가용성을 보장하지 않는다.

## 계산 주의사항

- 금액·수량은 Decimal 계산 및 API 소수 문자열을 사용한다.
- QC/QA 완료 예상은 현재 확정 가용 재고와 다르다. 유효일 당일까지 사용 가능하다.
- FEFO를 적용한 A안은 20개 구매 후 총 10개 잔여이지만, 구성은 신규 단기 유효 8개 + 기존 장기 유효 2개다. 따라서 11월 말 예상 폐기는 8개다. 원래 시나리오의 전량 10개 폐기 설명은 이 규칙에 맞게 수정했다.
- B안 구매+운송은 12,300,000원이며 보관·시험·폐기를 더한 총비용과 구별한다.

요구사항과 배경: [구현 계획](docs/PLAN.md), [IL-7 시나리오](docs/scenario_1.md).
