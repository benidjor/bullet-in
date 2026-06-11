# CLAUDE.md — bullet-in

아스날 FC 뉴스 수집 파이프라인. 다중 소스(RSS/HTML/Playwright/X)를 asyncio 병렬 수집 →
MongoDB(raw) → MariaDB(mart, content_hash·URL UNIQUE dedup) → Gemini 번역/요약 →
dbt 품질 게이트(DuckDB) → 정적 HTML 서빙. 스케줄은 Airflow.

스택: Python 3.11, uv, pydantic v2, httpx+BeautifulSoup, Playwright, twikit, google-genai, SQLAlchemy.

## 명령어
```bash
uv sync --extra dev && uv run playwright install chromium   # 셋업
uv run pytest -q                                            # 테스트(통합은 DB/Airflow 없으면 skip)
docker compose up -d                                        # mongo, mariadb
set -a; source .env; set +a                                 # 이 프로젝트는 dotenv 미사용 → 셸 export 필요
uv run python -m bullet_in.run --concurrency 8              # 종단 실행
```
첫 라이브 실행 절차·제약: `docs/runbook/live-e2e-bootstrap.md`.

## 커밋 & PR 컨벤션 (필독)
SoT: `docs/conventions/2026-06-11-commit-pr-convention.md`. 핵심:
- 커밋: `<type>(<scope>): 한국어 제목` + 본문(왜) + `Refs:` + 트레일러. type/scope는 영어.
- **트레일러 이메일은 반드시 소유자 GitHub noreply**:
  `Co-Authored-By: Claude Opus <버전> (1M context) <94089198+benidjor@users.noreply.github.com>`
  공용 `noreply@anthropic.com`을 쓰면 그 주소를 선점한 제3자에게 co-author로 귀속됨(금지).
- PR 본문: 7섹션 한국어 구조, `--body-file`로 전달, **Claude 서명 금지**(§2.7).
- GitHub Flow + squash merge, PR = Task.

## 공개 저장소 주의
- 공개되는 글(README·PR·커밋)에 Claude 서명, '포트폴리오/이직/취업' 프레이밍, 회사 실명 금지.
- 동기는 실제 제품 관점(아스날 팬, 흩어진 현지 언론·ITK 한곳 모으기)으로 서술.

## 설계·계획·상태
- 스펙: `docs/superpowers/specs/`, 계획: `docs/superpowers/plans/`.
- 트러블슈팅: `docs/troubleshooting/`, 런북: `docs/runbook/`.
- 산출물 본문은 한국어로 작성.

## 자주 밟는 함정
- **소스 셀렉터 드리프트**: `config/sources.yaml`의 selector/feed_url은 외부 사이트에 의존해 깨진다.
  신규/변경 소스는 머지 전 어댑터 단독 `fetch()`로 라이브 검증할 것(단위 테스트는 모킹이라 못 잡음).
  사례: `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`.
- **Gemini 무료 티어 429**: ~15 RPM이라 회당 ~15건만 번역됨. enrich는 429를 조용히 삼킴(로그 개선 TODO).
- **스키마 수동 적용**: `run.py`는 테이블을 안 만든다. 첫 실행 전 `src/bullet_in/storage/schema.sql` 적용(런북 참조).
- **git 신원**: `benidjor <94089198+benidjor@users.noreply.github.com>`로 커밋(다른 이메일 금지).
