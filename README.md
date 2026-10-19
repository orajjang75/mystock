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

## 배포 (docker compose)

backend(API + 스케줄러), frontend(nginx), postgres를 한 번에 올린다. 위의 "설치"는 개발용이고, 운영은 이쪽이다.

```bash
cp .env.example .env     # 아래 값을 채운다
docker compose up -d --build        # 또는 make up
```

http://localhost:8080 (`WEB_PORT`로 변경). nginx가 `/api`를 backend로 넘기므로 브라우저에서는 한 출처다.
backend는 시작할 때 `alembic upgrade head`를 돌리고, 스케줄러를 같은 프로세스에서 켠다. **worker·replica를 늘리지 않는다** (작업이 중복 실행된다).
compose는 `DATABASE_URL`을 자체 postgres로 덮어쓴다. 기존 `wewatch-postgres`를 쓰는 개발 환경과 5432 포트가 겹치면 `POSTGRES_PORT`를 바꾼다.

`.env`에서 운영에 꼭 채울 값:

| 변수 | 설명 |
| --- | --- |
| `APP_USERNAME`, `APP_PASSWORD`, `SECRET_KEY` | 로그인 계정과 세션 키 (32자 이상). 기본값 그대로 쓰지 않는다 |
| `POSTGRES_PASSWORD` | DB 비밀번호 |
| `ADAPTER` | `mock`(기본, 모의 시세) / `pykrx` / `kis` |
| `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ENV` | `ADAPTER=kis` 일 때. 키는 환경 변수로만 받고 로그·응답에 나오지 않는다 |
| `KRX_ID`, `KRX_PW` | 종목 목록·시가총액 순위(pykrx). `kis`에서도 필요 |
| `DAILY_SCAN_TIME` | 일봉 작업 시각. KIS 수급 확정 이후인 `18:30` 권장 |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 텔레그램 알림. 설정 화면에서 채널을 켠다 |
| `PAPER_RUN` | `true`면 모의 운영(체결 기록 거절). 아래 참고 |
| `COOKIE_SECURE` | HTTPS 뒤에서 서비스하면 `true` |

실제 시세 연동의 한계와 확인할 가정은 [docs/real-data.md](docs/real-data.md)에 있다.

### 모의 운영 (몇 주 동안 신호만 보기)

`PAPER_RUN=true`, `ADAPTER=kis`로 올리면 실제 시세로 신호와 알림만 낸다. 체결 기록은 받지 않는다.
매일 장 마감 후 리포트를 뽑아 신호 누락·지연·수집 실패를 확인한다.

```bash
make ops-report        # docs/ops-reports/<오늘>.md (실행 중인 compose에서)
# 또는 화면 밖에서: GET /api/ops/report?from=2026-11-02&to=2026-11-27&format=md
```

리포트 읽는 법과 5단계 게이트 기준은 [docs/real-data.md](docs/real-data.md) 5장.

### 백업과 복원

데이터는 postgres 볼륨(`mystock_pgdata`)에 있다. 매일 `pg_dump` 파일을 만들어 두고, 볼륨 밖(다른 디스크·클라우드)에도 복사한다.

```bash
./scripts/backup.sh                                   # make backup. backups/mystock_<시각>.dump, 최근 14개만 유지
./scripts/restore.sh backups/mystock_20261019_020000.dump   # make restore FILE=...
```

복원은 backend를 멈추고 테이블을 덮어쓴 뒤 다시 시작한다. 정기 백업 cron 예:
`0 2 * * * cd /path/mystock && ./scripts/backup.sh >> backups/backup.log 2>&1`.
`docker compose down -v`는 볼륨까지 지우므로 쓰지 않는다 (`down`만 쓴다).
KIS 토큰 캐시는 `mystock_appdata` 볼륨에 있어 재시작해도 재발급하지 않는다.

## 테스트

```bash
cd backend  && python -m uv run pytest     # 약 11분 (느린 PC 기준)
cd frontend && npm test
```

마지막 실행 결과 (이 환경):

- 백엔드: 895 passed, 5 skipped. 건너뛴 것은 vectorbt 미설치(`uv sync --extra backtest`로 설치).
- 프런트: 279 passed (vitest), E2E 18 passed (`make e2e`).

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
