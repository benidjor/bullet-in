# SLO-1 병렬화 시간 단축 실측 · 기록 설계 (2026-07-14)

로드맵 SoT ( `docs/superpowers/2026-06-28-v1-completion-roadmap.md` ) Tier 3 항목 8 구현 — Tier 3 마지막 항목.
README §4 SLO 표의 "병렬화 수집 시간 단축 · 순차 대비 ~70%↓" 를 실측해 공란을 채우고, 근거를 상시 기록 경로로 남긴다.
성능 개선은 범위 밖 — 측정 · 기록 트랙이다.

## 1. 배경 · 문제

- **코드는 있는데 호출이 없음** — `metrics.benchmark()` · `speedup_pct()` 가 구현 · 테스트돼 있으나 어디서도 호출되지 않고, README SLO 표 실측값이 공란.
- **기존 이력으로 대체 불가** — `pipeline_runs.duration_sec` 은 fetch 만이 아니라 전체 파이프라인 ( Mongo 적재 + Gemini 번역 · 분류 + 렌더 ) 을 계측한다.
  신규 70건 회차 470s vs 신규 0건 회차 119s 로 enrich 비용이 지배해, 병렬화 효과가 이 값에서 보이지 않는다.
- **이력 규모 정정** — pipeline_runs 는 13회 ( 초기 빈 런 3회 포함 ) 로, 세션 메모리의 "30회+" 와 다름을 실측으로 확인 (2026-07-14).
- **~70% 목표의 구조적 한계** — 병렬 시간의 하한은 가장 느린 소스 1개의 시간 ( 순차 = `Σt_i`, 병렬 ≈ `max(t_i)` ).
  enabled 6소스 구성에서 최장 소스 ( 유력: afcstuff Playwright 로그인 ) 가 지배하면 70% 가 안 나올 수 있다.

## 2. 목표 · 비목표

- **목표** — 순차 vs 병렬 speedup 을 1회성 벤치마크로 실측하고, 3회 중앙값을 README §4 에 기입.
- **목표** — 매 런의 fetch 구간 소요를 `pipeline_runs.fetch_duration_sec` 으로 상시 기록해 병렬 실측치의 지속 근거 확보.
- **목표** — ops 뷰 SLO 롤업 + dbt `slo_rollup` 에 fetch duration 행 추가.
- **목표** — PR #39 최종 리뷰 이월 Minor 3건 동반: ① started_at UTC 고정 ② ops spec §5.3 표현 정밀화 ③ stale 배지 렌더 스모크.
- **비목표 ( YAGNI )** — 성능 개선 ( 세션 재사용 · 타임아웃 튜닝 등 ) 없음.
  실측이 70% 미달이면 README 목표를 실측 기반으로 갱신하고 사유를 기록한다 — 개선 루프는 별도 트랙.
- **비목표** — 벤치마크 결과의 DB 적재 없음 ( 런북 기록으로 충분 ), 벤치마크 스케줄링 없음 ( 수동 실행 ).

## 3. 결정 사항 — 실측 방식 · 프로토콜 · 기록 위치

### 3.1. 실측 방식 = 하이브리드

- **1회성 벤치마크** — 순차 baseline 이 필요한 speedup 실측은 전용 진입점으로 분리.
  순차 실행을 매 런마다 하면 소스 부하가 2배가 되므로 상시 경로에 넣지 않는다.
- **상시 기록** — run.py 의 fetch 구간만 별도 계측해 `fetch_duration_sec` 으로 매 런 기록.
  병렬 실측치가 소스 구성 변화 후에도 낡지 않도록 지속 근거를 남긴다.
- **기각한 대안** — 벤치마크만 ( 소스 구성 변경 시 실측치 부패를 감지 못함 ) · 상시 기록만 ( 순차 baseline 이 없어 SLO-1 원 정의 미충족 ).

### 3.2. 실행 프로토콜 = 스크립트 1세트 + 수동 3회

- 스크립트는 순차 → gap 대기 → 병렬 1세트만 실행하고 JSON 을 출력한다.
- 운영 절차 ( 런북 ) 로 서로 다른 시간대에 3회 실행 ( 최소 1시간 간격 권장 ) → 중앙값을 README 에 기입, 3회 로그는 런북에 기록.
  ( 정정 2026-07-15: 실측에서 fmkorea 차단 창이 65분을 초과해 간격 기준을 **2시간 이상** 으로 갱신 — 운영 SoT 는 런북 §1 · §3 )
- **기각한 대안** — 스크립트 내 3회 반복 ( 단시간 소스별 6회 타격 — fmkorea 430 · X 안티봇 리스크 ) · 1회 측정 ( 네트워크 변동 무방비 ).

### 3.3. 진입점 = 전용 모듈

- `python -m bullet_in.benchmark` — config 에서 어댑터 빌드 → `metrics.benchmark()` → JSON stdout.
- README 측정 방법 문구가 이미 `metrics.benchmark()` 를 지칭하므로 문서와 코드가 일치한다.
- **기각한 대안** — run.py `--benchmark` 플래그 ( 적재하지 않는 벤치 분기가 파이프라인 코드와 섞임 ) · scripts/ 단독 스크립트 ( 프로젝트에 관례 없음, 테스트 경로 약함 ).

### 3.4. 70% 미달 시 = 실측값으로 갱신

- README 목표를 실측 기반으로 재조정하고 재조정 사유 ( 최장 소스 지배 구조, per_source 분해 근거 ) 를 런북에 문서화.
- 코드 개선으로 목표를 맞추러 가지 않는다 ( §2 비목표 ).

## 4. 벤치마크 설계

### 4.1. `metrics.py` 확장

시그니처: `benchmark(adapters, *, gap_sec: float = 60) -> dict`.

- **순차 패스** — 어댑터별 개별 계측 루프: 어댑터 하나씩 `gather_all([a], concurrency=1)` 로 실행하며 각각 perf_counter 계측.
  합 = `sequential_sec`, 소스별 분해 = `per_source` — 최장 소스 식별이 §3.4 사유 기록의 근거가 된다.
- **gap 대기** — 순차 · 병렬 패스 사이 `gap_sec` 대기 ( 소스 연속 타격 완화, 테스트에선 0 ).
- **병렬 패스** — 기존 `gather_all(adapters, concurrency=len(adapters))` 그대로 — 운영과 동일 코드 경로로 측정. `parallel_sec`.
- **반환** — `{sequential_sec, parallel_sec, speedup_pct, per_source, errors_seq, errors_par}`.

### 4.2. `benchmark.py` 진입점 ( 신규 )

- config/sources.yaml 에서 어댑터 빌드 → `benchmark()` 실행 → JSON stdout.
- DB 미적재 — Mongo · MariaDB 를 건드리지 않는 순수 fetch 측정. Gemini 미관여.

## 5. 상시 계측 설계

- **run.py** — `gather_all` 전후 perf_counter 로 `fetch_duration_sec` 산출, `pipeline_runs` INSERT 에 컬럼 추가.
- **schema.sql** — CREATE 에 `fetch_duration_sec FLOAT` + `ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS` ( transfer_stage 선례와 동일한 멱등 마이그레이션 패턴 — `ensure_schema()` 가 라이브 테이블에 자동 적용 ).
- **① started_at UTC 고정 ( 같은 INSERT 문 )** — `FROM_UNIXTIME(:t0)` → Python 에서 만든 UTC datetime 바인딩, `NOW()` → `UTC_TIMESTAMP()`.
  SLO-5 `checked_at` 과 시계 통일 — 세션 TZ 의존 잠복 가정 제거 ( `docs/runbook/2026-07-14-ops-monitoring-view.md` 이월 항목 ).
  기존 13회 이력은 컨테이너 TZ 가 UTC 였으므로 불연속 없음.

## 6. 연동 — SLO 롤업 행 ( 두 곳 )

ops 뷰 ( MariaDB 직접 집계, A안 ) 와 dbt 마트는 이원 경로이므로 행 추가 지점이 두 곳이다.

- **ops 뷰** — `ops_snapshot()` SELECT 에 `fetch_duration_sec` 추가 → `build_ops_view()` SLO 롤업에 행 추가:
  slo_id `fetch_duration` · definition "최근 30회 평균 fetch 시간" · status `info`.
  NULL 이력 제외 평균, 전부 NULL 이면 `—` 표시.
- **dbt** — `stg_pipeline_runs` 에 컬럼 추가 + `slo_rollup.sql` 에 같은 정의의 행 추가 ( `avg()` 는 NULL 자동 제외 ).
  기존 `slo_id` unique · not_null 테스트와 충돌 없음.

## 7. Minor 이월분 ( ② · ③ )

- **② ops spec §5.3 정밀화 ( 문서만 )** — "SLO-6 이상 탐지의 히스토리 창과 동일 = 알림과 뷰가 같은 창을 본다" 를 사실대로 수정:
  SLO-6 은 현재 런 INSERT 전 직전 12회 ( run.py:71–75 ), 뷰는 INSERT 후 최근 12회 ( 현재 런 포함 ) — 한 회차 어긋난 창.
  합의된 spec 의 사후 정정이므로 정정 표식 ( 수정 일자 · 사유 ) 을 함께 남긴다.
- **③ stale 배지 렌더 스모크 ( 테스트만 )** — `tests/test_serve_ops.py` 에 stale=1 픽스처 케이스 추가.
  현재 픽스처는 stale=0 뿐이라 stale 배지 렌더 경로가 미검증.

## 8. 에러 처리 · 엣지 케이스

| 상황 | 처리 |
|---|---|
| 벤치마크 두 패스의 에러 소스 불일치 | 결과 JSON 에 `errors_seq` · `errors_par` 노출 — 비교 무효. 런북 규칙 = 해당 회차 폐기 · 재실행 |
| 전 소스 에러 ( sequential_sec ≈ 0 ) | `speedup_pct` 계산 전 가드 — 0-나눗셈 방지, 결과 무효 표시 |
| `fetch_duration_sec` NULL ( 기존 13회 이력 ) | 평균에서 제외 ( SQL `avg` 자동, Python 은 None 필터 ), 전부 NULL 이면 `—` |
| 순서 편향 ( 순차 먼저 → 서버 캐시 워밍이 병렬에 유리 ) | 구조상 완전 제거 불가 — 순서 고정 + 3회 중앙값으로 완화, 한계를 런북에 명시 |
| 벤치마크 중단 ( Ctrl-C · 네트워크 ) | 상태를 남기지 않으므로 재실행으로 충분 |

## 9. 테스트 전략

- **단위 — metrics**: 페이크 어댑터 ( asyncio.sleep 기반, 지연 조절 ) 로 검증. 전부 `gap_sec=0`.
  순차 ≈ Σ지연 · 병렬 ≈ max지연 은 여유 있는 경계로 flaky 방지.
  `per_source` 키 = 어댑터 id, 에러 어댑터 포함 시 `errors_*` 분리, `speedup_pct` 0-나눗셈 가드.
- **단위 — 렌더**: SLO 롤업 `fetch_duration` 행 ( 값 있음 / 전부 NULL → `—` ) + ③ stale=1 배지 스모크.
- **통합** ( DB 없으면 skip — 기존 패턴 ): INSERT 후 `fetch_duration_sec` 저장 확인 + `started_at` 이 `UTC_TIMESTAMP()` 근방인지 확인 ( ① 검증 ).
- **dbt**: `dbt build` 통과 ( stg_pipeline_runs 컬럼 · slo_rollup 행 추가 + 기존 게이트 회귀 ).
- **라이브 검증** ( verification-before-completion ): 벤치마크 실측 3회 + 종단 실행 1회로 `fetch_duration_sec` 기록 · ops 뷰 행 노출 육안 확인.

## 10. 문서 · README

- **README §4 SLO 표** — `실측` 컬럼 추가.
  SLO-1 행에 3회 중앙값 기입 ( 예: "실측 N%↓ (2026-07-XX, 3회 중앙값)" ), 나머지 행은 `—` 유지.
  70% 미달 시 목표 셀도 실측 기반으로 갱신, 사유는 런북 링크.
- **런북 ( 신규 )** — `docs/runbook/2026-07-14-slo1-benchmark.md`:
  실행 절차 ( 3회 · 시간대 분산 · 간격은 런북 §1 이 SoT — 정정 2026-07-15: 1시간 → 2시간 이상 ), 소스 부하 주의 ( fmkorea 430 · afcstuff Playwright 세션 2회/세트 ),
  결과 해석 ( 에러 불일치 = 폐기 ), 3회 실측 로그, 순서 편향 한계.
- 코드 · 런북 · README 를 같은 PR 에 동반.

## 11. 성공 기준

- `uv run python -m bullet_in.benchmark` 실측 3회 완료, 중앙값이 README §4 에 기입됨.
- 종단 실행 후 `pipeline_runs.fetch_duration_sec` 기록 + ops 뷰 SLO 롤업에 fetch 행 노출.
- `started_at` · `finished_at` 이 세션 TZ 무관 UTC 로 기록됨 ( ① ).
- `uv run pytest -q` · `dbt build` 통과.
- ops spec §5.3 정정 ( ② ) · stale 배지 스모크 ( ③ ) 반영.
