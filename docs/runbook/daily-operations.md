# 런북 — Daily Operations

매일 수집을 정상 가동·점검하는 절차.

## 1. 사전 준비 (최초 1회)
- `.env.example`를 `.env`로 복사 후 값 채우기: `MONGO_URI`, `MARIADB_URL`, `GEMINI_API_KEY`, X 버너 계정(`X_USERNAME`/`X_EMAIL`/`X_PASSWORD`).
- 의존성: `uv sync --extra dev && uv run playwright install chromium`.

## 2. 데이터 스토어 기동
```bash
docker compose up -d        # mongo, mariadb
docker compose ps           # 두 컨테이너 running 확인
```

## 3. 파이프라인 실행
- 수동: `uv run python -m bullet_in.run --concurrency 8`
- 스케줄: Airflow DAG `bullet_in_daily` (@daily) 트리거.

## 4. 수집 현황 점검 (이상 점검)
실행 요약(stdout dict)에서 다음을 확인:
- `success_rate >= 0.99` (소스별 격리 + 재시도 포함)
- `errors == {}` — 비어 있지 않으면 해당 소스만 실패한 것. troubleshooting/ 참고.
- `new_or_changed` 가 전일 대비 급감/급증이면 수집량 이상 신호.

## 5. 품질 게이트
```bash
cd dbt && uv run dbt build --profiles-dir .
```
`unique`(중복 0)·`not_null`(필수 필드)·`accepted_values`(tier 0~4) 테스트가 모두 PASS여야 한다. 실패 = 데이터 이상 → incident-recovery.md.

## 6. 서빙 확인
`site/index.html` 가 갱신되고 confidence 내림차순으로 기사가 나열되는지 확인.

## 7. enrich (번역) 점검 — 긴 본문 번역 잘림 · Gemini 503 / 429

- **증상**: 특정 (주로 긴) 기사가 매 사이클 `body_ko` / `summary3_ko` NULL 유지 (에러 로그 없이 조용히).

긴 본문 번역이 출력 한도에 걸려 잘리면서 영영 안 채워지는 경로.

```
원문 (extract_article_body, 최대 8000자)
  ── 번역 출력 > max_output_tokens
  ── JSON 잘림
  ── 파싱 실패로 행 스킵
  ── 트리거 title_ko IS NULL 그대로
  ── 다음 회차도 같은 길이라 다시 잘림 (무한)
```

- **대응**: `src/bullet_in/enrich.py` 의 `max_output_tokens` 상향 (현 8192) 또는 `extract_article_body` 본문 cap (현 8000자) 하향.
- **Gemini 503 (모델 과부하) vs 429 구분**
  - 429 (RESOURCE_EXHAUSTED) — `_is_rate_limit` 이 잡아 그 회차 즉시 중단 · 남은 행은 다음 회차 누적.
  - 503 — 개별 행만 스킵하고 배치는 지속 · 다음 회차 재시도. 503 급증 시 일부 행이 이번 회차에 안 채워지는 것은 정상.
- **멱등**: 둘 다 `title_ko IS NULL` 로 다음 사이클 자동 재시도 · 중복 적재 없음.
- 상세 — `docs/troubleshooting/2026-06-29-fmkorea-discovery-extraction.md` · `2026-05-27-llm-json-parsing-robustness.md`.
