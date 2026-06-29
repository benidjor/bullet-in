# 런북 — 라이브 e2e 부트스트랩

로컬에서 실제 소스로 파이프라인을 처음 종단 실행하는 절차와 알려진 제약.
일상 운영은 `2026-05-27-daily-operations.md`, 이 문서는 **첫 라이브 셋업·검증**에 집중.

## 1. 사전 준비
- Docker Desktop 기동(데몬이 꺼져 있으면 `open -a Docker`, 부팅 30~60초).
- `.env` 생성(gitignore됨): `MONGO_URI`·`MONGO_DB`·`MARIADB_URL`은 `.env.example` 기본값 그대로(로컬 docker-compose와 일치), `GEMINI_API_KEY` 실값. (X·fmkorea 비활성 시 X 자격증명 불필요.)
- 의존성: `uv sync --extra dev && uv run playwright install chromium`.

## 2. 데이터 스토어 기동
```bash
docker compose up -d        # mongo, mariadb
docker compose ps           # 두 컨테이너 running 확인
```

## 3. 스키마 (자동 부트스트랩 — 수동 단계 불필요)
`run.py`는 시작 시 `MartStore.ensure_schema()`로 `src/bullet_in/storage/schema.sql`을 멱등 적용한다(`CREATE TABLE IF NOT EXISTS`). DB 컨테이너만 떠 있으면 첫 실행이 `articles`/`pipeline_runs`를 자동 생성하므로 별도 적용은 필요 없다.

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
- 분당 요청 한도(~15 RPM)는 **속도** 제한이지 총량이 아니다 — 1분에 15콜까지, 1분 뒤 리셋. 한 회차에 90건을 몰면 ~15건만 되고 나머지는 `429 RESOURCE_EXHAUSTED`.
- **채택: 옵션 C(멱등 누적, 2026-06)** — 결제 불필요(₩0), 추가 코드 0. 기존 dedup·`title_ko IS NULL` 구조가 매 실행 신규만 번역하므로, **하루 4회 스케줄**(DAG `0 */6 * * *`)로 신규를 누적 처리한다. 90건은 콜드스타트 1회뿐이고, 정상 운영 시 회당 신규는 보통 15 미만이라 한도에 거의 안 닿는다.
  - 한국 Gemini API 결제는 **선불(Cloud Prepay, 최소 ₩25,000·1년 만료)** 이라, 회당 수 센트 사용량엔 상당액이 만료돼 비효율 → A 미채택.
- 미채택 대안: A. 결제(선불) / B. enrich에 ≤15/분 throttle 추가(1회 ~6분, SLO 부풀음).
- **방어 코드(적용됨)**: enrich가 429를 식별해 그 회차를 **즉시 중단(break)·`WARNING` 로깅**하고 남은 행은 다음 사이클에 누적한다(파싱 실패·기타 예외는 행 단위 스킵). 스케줄이 곧 재시도이므로 per-row 백오프는 두지 않는다(헛 호출·실행 지연 방지).

## 7. 현재 활성 소스(첫 라이브 기준)
- **활성**: `arsenal_official`(HTML), `bbc_sport`(HTML), `football_london`(HTML).
- **비활성(후속 복구)**:
  - `goal` — Playwright 셀렉터/동의월 드리프트(troubleshooting/2026-06-12-live-source-selector-drift.md).
  - `x_afcstuff` — X 버너 자격증명 필요.
  - `fmkorea` — 퍼가기 금지 정책 + HTTP 429 대응 필요(spec §9.1).
