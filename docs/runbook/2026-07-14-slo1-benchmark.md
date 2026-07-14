# SLO-1 병렬화 벤치마크 런북 (2026-07-14)

`python -m bullet_in.benchmark` 로 순차 vs 병렬 fetch speedup 을 실측하는 절차와 해석 기준.
설계: `docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md`.

## 1. 실행 절차

- 사전: `set -a; source .env; set +a` ( X 쿠키 · 자격 필요 — afcstuff 어댑터 ).
- 실행: `uv run python -m bullet_in.benchmark` ( 순차 → 60s 대기 → 병렬, JSON stdout ).
- 서로 다른 시간대에 3회 실행 ( 최소 1시간 간격 권장 ) → speedup_pct 중앙값을 README §4 에 기입.

## 2. 소스 부하 주의

- 1세트 = enabled 소스별 2회 타격 ( 순차 1 + 병렬 1 ).
- fmkorea 는 430 rate-limit 이력, afcstuff 는 Playwright 로그인이 세트당 2회 발생.
- 단시간 반복 실행 금지 — 스크립트 내 반복 대신 시간대 분산 3회가 이 이유.

## 3. 결과 해석

- `errors_seq` · `errors_par` 의 소스 집합이 다르면 그 회차는 비교 무효 — 폐기하고 재실행.
- `speedup_pct = null` 은 순차 합계 0 ( 전 소스 실패 ) — 환경 점검 후 재실행.
- `per_source` 최댓값이 병렬 시간의 하한 — 최장 소스가 지배하면 70% 미달이 구조적일 수 있다.
  그 경우 README 목표를 실측 기반으로 갱신하고 아래 로그에 사유를 남긴다 ( spec §3.4 ).

## 4. 한계

- 순차 → 병렬 순서 고정이라 서버 측 캐시 워밍이 병렬 패스에 유리할 수 있다.
  완전 제거는 불가 — 3회 중앙값으로 완화한다.

## 5. 실측 로그

| 회차 | 일시 (UTC) | sequential_sec | parallel_sec | speedup_pct | 비고 |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

- 중앙값: ( Task 8 기입 )
- 최장 소스: ( per_source 기준, Task 8 기입 )
