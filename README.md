# mystock

my stock manager — 알림 전용 KOSPI 턴어라운드 앱 (주문·자동매매 기능 없음).
백엔드 FastAPI, 프런트 React + TypeScript + antd. 자세한 요구사항은 `docs/PRD.md`, 작업 규칙은 `CLAUDE.md`를 본다.

## 사전 준비

- Python 3.11+ (3.12 확인), Node.js / npm, Docker
- [uv](https://docs.astral.sh/uv/) — 없으면 `python -m pip install --user uv` 후 `python -m uv ...`로 실행
- `make`가 없는 환경(Windows)에서는 아래 명령을 직접 실행한다.

## 설치 (Windows, 기존 `wewatch-postgres` 컨테이너 사용)

새 PostgreSQL 이미지를 받지 않고, 이미 떠 있는 `wewatch-postgres`(postgres:16) 컨테이너에 mystock 전용 DB를 추가한다.
`wewatch` DB의 `public` 스키마에는 다른 앱의 `alembic_version` 테이블이 있어 마이그레이션 이력이 충돌하므로,
같은 컨테이너 안에 별도 DB를 만든다. 기존 `wewatch` DB는 건드리지 않는다.

```bash
# 1. DB 계정과 데이터베이스 추가 (컨테이너의 슈퍼유저는 wewatch)
docker exec wewatch-postgres psql -U wewatch -d wewatch \
  -c "CREATE ROLE mystock LOGIN PASSWORD 'mystock' CREATEDB" \
  -c "CREATE DATABASE mystock OWNER mystock" \
  -c "CREATE DATABASE mystock_e2e OWNER mystock"

# 2. 환경 변수 (.env는 git에서 제외됨). 기본값이 위 DB를 가리킨다.
cp .env.example .env

# 3. 의존성 설치
cd backend  && python -m uv sync
cd ../frontend && npm ci

# 4. 테이블 생성 (alembic 마이그레이션)
cd ../backend && python -m uv run alembic upgrade head

# 5. 모의 시세 적재 + 스캔 (ADAPTER=mock)
python -m uv run python -m app.jobs.daily_scan --force
```

별도 Postgres를 새로 띄우려면 저장소의 `docker-compose.yml`(`make db-up`)을 쓰면 된다.

## 실행

터미널 두 개에서 각각 실행한다.

```bash
# 백엔드 (:8000)
cd backend && python -m uv run uvicorn app.main:create_app --factory --reload --port 8000

# 프런트 (:5173)
cd frontend && npm run dev
```

http://localhost:5173 접속. 로그인은 `.env`의 `APP_USERNAME` / `APP_PASSWORD`(기본 `admin` / `change-me`).
실제 사용 전에 `.env`의 `APP_PASSWORD`와 `SECRET_KEY`를 바꾼다.

## 테스트

```bash
cd backend  && python -m uv run pytest     # 약 11분 (느린 PC 기준)
cd frontend && npm test
```

마지막 실행 결과 (이 환경):

- 백엔드: 839 passed, 5 skipped. 건너뛴 것은 vectorbt 미설치(`uv sync --extra backtest`로 설치).
- 프런트: 277개 중 274 passed, 3 failed. `BacktestPage` 테스트가 15초 타임아웃에 걸림 (느린 PC로 추정, 원인 미확인).

## 주요 명령 (Makefile 대응)

| 작업 | 명령 |
| --- | --- |
| 마이그레이션 | `cd backend && python -m uv run alembic upgrade head` |
| 시세 수집 + 스캔 | `cd backend && python -m uv run python -m app.jobs.daily_scan --force` |
| 수집만 | `cd backend && python -m uv run python -m app.jobs.ingest` |
| 백테스트 | `cd backend && python -m uv run python -m app.backtest` |
| 린트 | `cd backend && python -m uv run ruff check . && python -m uv run mypy`; `cd frontend && npm run lint` |
| E2E (Playwright) | `cd frontend && npx playwright test` (DB `mystock_e2e` 사용) |

`make`가 있으면 `make install`, `make dev`, `make test` 등을 그대로 쓸 수 있다.
