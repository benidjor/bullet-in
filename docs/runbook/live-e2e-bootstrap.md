# 런북 — 라이브 e2e 부트스트랩

로컬에서 실제 소스로 파이프라인을 처음 종단 실행하는 절차와 알려진 제약.
일상 운영은 `daily-operations.md`, 이 문서는 **첫 라이브 셋업·검증**에 집중.

## 1. 사전 준비
- Docker Desktop 기동(데몬이 꺼져 있으면 `open -a Docker`, 부팅 30~60초).
- `.env` 생성(gitignore됨): `MONGO_URI`·`MONGO_DB`·`MARIADB_URL`은 `.env.example` 기본값 그대로(로컬 docker-compose와 일치), `GEMINI_API_KEY` 실값. (X·fmkorea 비활성 시 X 자격증명 불필요.)
- 의존성: `uv sync --extra dev && uv run playwright install chromium`.

## 2. 데이터 스토어 기동
```bash
docker compose up -d        # mongo, mariadb
docker compose ps           # 두 컨테이너 running 확인
```

## 3. 스키마 적용 (중요 — 현재 수동 단계)
`run.py`는 테이블을 만들지 않는다. `src/bullet_in/storage/schema.sql`을 MariaDB에 적용해야 첫 실행이 `articles`/`pipeline_runs`에 쓸 수 있다.
```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from pathlib import Path
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
for s in [s.strip() for s in Path("src/bullet_in/storage/schema.sql").read_text().split(";") if s.strip()]:
    with eng.begin() as c: c.execute(text(s))
print("schema applied")
PY
```
> **개선 TODO**: `run.py`(또는 부트스트랩)가 `CREATE TABLE IF NOT EXISTS`를 멱등 적용하도록 만들면 이 수동 단계 제거 가능.

## 4. 종단 실행
이 프로젝트는 `python-dotenv`를 쓰지 않고 `os.environ`을 직접 읽는다 → **셸에 export 후** 실행.
```bash
set -a; source .env; set +a
uv run python -m bullet_in.run --concurrency 8
```
기대 출력(예): `{'new_or_changed': 90, 'errors': {}, 'success_rate': 1.0, 'elapsed_sec': 28.8}`.
서빙 페이지는 `site/index.html`에 생성.

## 5. 검증 쿼리
```sql
SELECT COUNT(*) FROM articles;                          -- 적재 건수
SELECT COUNT(*) FROM articles WHERE title_ko IS NOT NULL;-- 번역 완료 건수
SELECT source_id, COUNT(*), ROUND(AVG(confidence_score),2) FROM articles GROUP BY source_id;
SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1;  -- SLO 기록
```

## 6. 알려진 제약 — Gemini 무료 티어 429
- 무료 티어 `gemini-2.5-flash-lite`는 **분당 요청 한도(~15 RPM)** 가 있어, 회당 ~90건 enrich 시 **약 15건만 번역**되고 나머지는 `429 RESOURCE_EXHAUSTED`로 스킵된다.
- `enrich.enrich_rows`/`summarize_ko_rows`는 행 단위 예외를 삼키므로(배치 격리) **429가 조용히 누락**으로 나타난다. 로그가 없어 진단이 어렵다.
- 대응 옵션:
  - **A. 결제 활성화(유료)** — 병목 제거, flash-lite는 저렴(~$0.01/90콜). 가장 단순.
  - **B. 무료 + enrich 레이트리밋/백오프** — ≤15/분 throttle(90건 ≈ 6분+), 일일 한도 가능성 있음.
  - **C. 부분 번역 멱등 누적** — `title_ko IS NULL`만 처리하는 멱등 구조라, 여러 실행/스케줄로 점진 완성.
- **개선 TODO**: enrich가 429를 식별해 로깅 + 백오프(파싱 실패와 구분).

## 7. 현재 활성 소스(첫 라이브 기준)
- **활성**: `arsenal_official`(HTML), `bbc_sport`(HTML), `football_london`(HTML).
- **비활성(후속 복구)**:
  - `goal` — Playwright 셀렉터/동의월 드리프트(troubleshooting/2026-06-12-live-source-selector-drift.md).
  - `x_afcstuff` — X 버너 자격증명 필요.
  - `fmkorea` — 퍼가기 금지 정책 + HTTP 429 대응 필요(spec §9.1).
