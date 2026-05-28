# 런북 — Daily Operations

매일 수집을 정상 가동·점검하는 절차.

## 1. 사전 준비 (최초 1회)
- `.env.example`를 `.env`로 복사 후 값 채우기: `MONGO_URI`, `MARIADB_URL`, `ANTHROPIC_API_KEY`, `GUARDIAN_API_KEY`, X 버너 계정(`X_USERNAME`/`X_EMAIL`/`X_PASSWORD`).
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
