# SLO-1 병렬화 벤치마크 런북 (2026-07-14)

`python -m bullet_in.benchmark` 로 순차 vs 병렬 fetch speedup 을 실측하는 절차와 해석 기준.
설계: `docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md`.

## 1. 실행 절차

- 사전: `set -a; source .env; set +a` ( X 쿠키 · 자격 필요 — afcstuff 어댑터 ).
- 실행: `uv run python -m bullet_in.benchmark` ( 순차 → 60s 대기 → 병렬, JSON stdout ).
- 서로 다른 시간대에 3회 실행 → speedup_pct 중앙값을 README §4 에 기입.
- 간격은 2시간 이상 — 벤치 자체가 fmkorea 를 2회 타격해 차단 창 ( §3, 65분 초과 실측 ) 을 유발하므로, 그보다 짧으면 다음 회차가 폐기된다.

## 2. 소스 부하 주의

- 1세트 = enabled 소스별 2회 타격 ( 순차 1 + 병렬 1 ).
- fmkorea 는 430 rate-limit 이력, afcstuff 는 Playwright 로그인이 세트당 2회 발생.
- 단시간 반복 실행 금지 — 스크립트 내 반복 대신 시간대 분산 3회가 이 이유.

## 3. 결과 해석

- `errors_seq` · `errors_par` 의 소스 집합이 다르면 그 회차는 비교 무효 — 폐기하고 재실행.
- fmkorea 430 은 어댑터가 스킵 처리해 **에러로 안 잡힌다** — 직전 회차 대비 fmkorea `per_source` 급감이 판별 신호이며, 그 회차도 폐기 · 재실행.
  실측: 벤치 직후 4분 시점 종단 실행 · 65분 시점 2회차에서 430 잔존 확인 (2026-07-14).
  fmkorea 차단 창은 65분 초과 — fmkorea 타격 후 재실행은 **2시간 이상** 간격을 둔다.
- 순차 패스의 fmkorea 타격이 60s 뒤 병렬 패스에서 430 을 유발할 수 있다 (2R 실측).
  이 경우 병렬 시간은 최장 소스 ( x_afcstuff ~42s ) 가 결정하므로 fmkorea ( ~11s ) 의 병렬 단축은 **측정 중립** — `per_source` ( 순차 ) 가 정상이면 유효 회차로 취급한다.
- `speedup_pct = null` 은 순차 합계 0 ( 전 소스 실패 ) — 환경 점검 후 재실행.
- `per_source` 최댓값이 병렬 시간의 하한 — 최장 소스가 지배하면 70% 미달이 구조적일 수 있다.
  그 경우 README 목표를 실측 기반으로 갱신하고 아래 로그에 사유를 남긴다 ( spec §3.4 ).

## 4. 한계

- 순차 → 병렬 순서 고정이라 서버 측 캐시 워밍이 병렬 패스에 유리할 수 있다.
  완전 제거는 불가 — 3회 중앙값으로 완화한다.

## 5. 실측 로그

| 회차 | 일시 (UTC) | sequential_sec | parallel_sec | speedup_pct | 비고 |
|---|---|---|---|---|---|
| 1 | 2026-07-14 12:47 | 91.75 | 41.34 | 54.9 | 에러 없음 · x_afcstuff 40.37s 최장 |
| 2 | 2026-07-14 13:56 | 78.97 | 42.0 | 46.8 | **폐기** — fmkorea `per_source` 0.12s 급감 ( 430 잔존, §3 규칙 ) |
| 2R | 2026-07-14 16:00 | 93.66 | 40.72 | 56.5 | 유효 — 순차 fmkorea 정상 10.92s, 병렬 패스만 430 ( 측정 중립, §3 ) |
| 3 | | | | | |

- 중앙값: ( Task 8 기입 )
- 최장 소스: ( per_source 기준, Task 8 기입 )
