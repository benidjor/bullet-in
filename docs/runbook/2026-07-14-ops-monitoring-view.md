# 수집 현황 운영 뷰 (2026-07-14)

## 개요

SLO-5 · SLO-6 Discord 알림은 "문제가 생겼다" 만 통지하고, 받은 뒤 추세 · 맥락을 보려면 DB 에 직접 SQL 을 쳐야 했다.
`site/ops.html` 은 그 사각을 메우는 운영자용 정적 페이지다.

- **목적** — 알림 수신 직후 (또는 정기 점검 시) 최근 30회 추세 · 소스별 신선도 · tier 분포를 한 화면에서 확인.
- **진입 경로** — `site/index.html` 하단 푸터의 "수집 현황" 링크 (`src/bullet_in/serve/templates/index.html.j2`).
- **갱신 주기** — 매 파이프라인 회차, `pipeline_runs` INSERT 직후 재생성 (`src/bullet_in/run.py`).
  현재 회차가 항상 "최근 30회" 에 포함된 상태로 렌더된다.
- **데이터 경로** — 뷰는 dbt 마트가 아니라 `MartStore.ops_snapshot()` 이 MariaDB 를 직접 집계한 값을 쓴다.
  dbt 는 분석 · 게이트용으로 독립 운영되며 (§5 에서 조회 방법을 별도로 안내), 두 경로의 지표 정의는 spec §5 표를 단일 기준으로 맞춘다
  (근거: `docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md` §3.1).

## 화면 해석

### KPI 타일 6종

| 타일 | 무엇을 보는가 | 이상 신호 |
|---|---|---|
| 신규 (최근 회차) | 최신 `pipeline_runs` 행의 `new_count` | 0 이 반복되면 전 소스 수집 정지 의심 |
| 중복 차단 | 최신 행의 `dup_count` | 급증은 URL · content_hash 중복 로직 이상보다는 재수집 정상 동작일 때가 많음 |
| 에러 | 최신 행의 `error_count` | 0 초과면 파이프라인 로그의 어댑터 예외를 확인 |
| 성공률 | 최신 행의 `success_rate` | 낮으면 (SLO-2 기준 90% 미만) §5 SLO 롤업의 `bad` 배지와 함께 확인 |
| 수집 끊긴 소스 | `source_freshness` 최신 회차의 `stale = 1` 행 수, 타일 값이 빨간색 (`.bad`) | 1 이상이면 SLO-5 신선도 알림과 동일 소스인지 대조 |
| 번역 · 분류 대기 | `rows_missing_translation()` · `rows_missing_stage()` 와 같은 술어 (`title_ko IS NULL` · `transfer_stage IS NULL`) 로 센 전체 합 | 하루 4회 Gemini 누적 스케줄 구조라 **절대값보다 회차마다 줄어드는지** 가 관건 — 안 줄면 enrich 자체가 막힌 것 |

콜드 스타트 (이력 0행) 에서는 "신규 · 중복 · 에러 · 성공률 · 수집 끊긴 소스" 5개 타일이 `—` 로 표시된다 (`_kpi()`, `src/bullet_in/serve/render.py`).
"번역 · 분류 대기" 타일만 `articles` 테이블 직접 카운트라 콜드 스타트에서도 실수를 보인다.

### 섹션 5개

- **① 회차별 수집량 (최근 30회)** — 막대 높이 = `new_count`, 빨간 막대 = 그 회차 `error_count > 0`.
  마우스를 올리면 시각 · 신규 · 중복 · 에러 상세가 뜬다.
  막대가 오른쪽 (최신) 으로 갈수록 낮아지는 추세는 전반적 수집량 감소 신호다.
- **② 소스별 신선도** — `source_freshness` 최신 회차 전 행 + 최근 12회 `age_hours` 스파크라인.
  "수집 끊긴 소스" = SLO-5 stale 과 동일 판정 — 뷰는 저장된 `stale` 값을 그대로 배지로 바꿀 뿐 재계산하지 않는다.
  배지 3종: `✓ 신선` (초록) · `✕ 초과` (빨강, stale) · `이력 없음` (회색, `age_hours IS NULL`).
  이력 없음은 "이상" 이 아니라 "판정 계층이 아직 이 소스를 stale 로 볼 근거 (워터마크) 자체가 없다" 는 뜻이므로 빨강으로 그리지 않는다.
- **③ 소스별 수집량 · 번역 · 분류 대기 (최근 12회)** — `source_counts` JSON 최근 12회 합 (부재 회차 = 0 으로 합산) + 소스별 번역 · 분류 대기.
  enabled 소스 전체가 행으로 나오므로, 12회 내내 수집량 0 인 소스가 그대로 노출된다 — 죽은 소스일수록 이 표에서 도드라져야 정상.
  "번역 · 분류 대기" = 다음 Gemini 사이클이 처리할 잔량이며, KPI 타일과 마찬가지로 회차마다 줄어드는지가 핵심이다.
  단, 비활성 (disabled) 소스의 잔량은 KPI 타일 합계에는 포함되지만 이 표 (enabled 소스만) 에는 안 보여 타일 > 표 합계가 될 수 있다 — "다음 Gemini 사이클 잔량" 의 올바른 값은 타일 쪽이다.
- **④ tier 분포 (전체 기사)** — `articles` 전체를 tier 로 묶은 막대.
  1 · 2 · 3 은 각 tier 라벨로, 정의 밖 값 (0 · 1.5 · 4) 은 "기타" 버킷 하나로 흡수한다 (`ETC_TIER_LABEL`, `src/bullet_in/serve/render.py`).
- **⑤ SLO 롤업 (최근 30회 기준)** — SLO-2 (평균 success_rate) · SLO-5 (수집 끊긴 소스 수) · SLO-6 (현재 회차 이상 감지 소스 수) · duration (참고치, SLO 아님) 4행.
  SLO-6 만 예외적으로 run.py 가 방금 계산한 메모리 값 (`anomaly_count`) 을 전달받는다 — 감지 결과가 DB 에 저장되지 않기 때문 (spec §4 "예외").

## 데이터 계약 요약

spec §6.1 표를 그대로 옮긴다 (`docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md`).

| 컬렉션 | 부재 회차의 의미 | 뷰 처리 |
|---|---|---|
| `source_counts` (희소 JSON) | 그 회차 신규 0건 | **부재 = 0** 으로 합산 (`h.get(sid, 0)`) — 판정 계층과 동일 계약 |
| `source_freshness` (매 회차 전 소스 기록) | 그때 소스가 config 에 없었음 | **진짜 결측** — 있는 회차만으로 스파크라인 |

- 두 계약을 섞으면 "회차별 수집량" (③) 은 왜곡되고 "신선도 추세" (②) 는 정상 렌더된다 — 컬렉션마다 부재의 의미가 다르므로 처리도 갈라야 한다.
  실제로 다른 소비자 (알림 embed 추세 시퀀스) 가 부재 = 결측으로 잘못 처리해 왜곡이 발생한 적이 있다.
  자세한 경위 → `docs/troubleshooting/2026-07-13-sparse-source-counts-trend-bias.md`.
- "생성" 시각과 `source_freshness` 의 `age_hours` 는 모두 UTC 로 고정된 시계 (`MartStore.db_now()` = `SELECT UTC_TIMESTAMP()`) 를 쓴다.
  naive DATETIME 두 값을 다른 시계로 비교하면 오프셋만큼 전 소스가 동시 오탐할 수 있었던 함정 → `docs/troubleshooting/2026-07-13-freshness-clock-mixing-gap.md`.
- **섹션 ① 호버 라벨의 시각** (`pipeline_runs.started_at`) 도 이제 UTC 고정이다 — 해소됨 (2026-07-15).
  과거에는 run.py 가 `FROM_UNIXTIME()` · `NOW()` (DB 세션 TZ 의존) 로 기록해 "세션 TZ 가 비 UTC 로 바뀌면 이 라벨만 오프셋" 이라는 표시 전용 잠복 가정이 있었다.
  PR #42 (PR #39 최종 리뷰 이월 ①) 가 기록 경로를 Python UTC 바인딩 · `UTC_TIMESTAMP()` 로 이관해, 뷰의 전 시계가 세션 TZ 무관 UTC 로 통일됐다.

## 실패 모드

- **생성 시각이 낡음 = `write_ops` 실패 신호** — 헤더의 "생성: … UTC" 가 최근 회차 시각과 어긋나 있으면, `run.py` 의 아래 처리로 인해 실패가 삼켜졌다는 뜻이다.

  ```python
  try:
      write_ops(mart.ops_snapshot(), sources, "site",
                anomaly_count=len(anomalies), now=mart.db_now())
  except Exception:
      logging.getLogger(__name__).warning(
          "ops 뷰 생성 실패 — 파이프라인은 계속 진행", exc_info=True)
  ```

  파이프라인 자체는 계속 돌고 `site/ops.html` 은 직전 회차 파일이 그대로 남으므로, 페이지가 죽은 것처럼 보이지 않는다.
  낡은 생성 시각을 발견하면 파이프라인 로그에서 `bullet_in.run` 로거의 `WARNING` — "ops 뷰 생성 실패" 를 검색해 스택 트레이스를 확인한다.
- **"이력 없음" 표시 조건** — 섹션 ① · ② · ⑤ 는 각 원천 (`pipeline_runs` · `source_freshness`) 이 빈 경우 표 대신 "이력 없음" 문구로 대체된다 (`ops.html.j2` 의 `{% else %}` 가드).
  섹션 ③ 은 `for sid in sources` 로 행을 만들어 이 가드에 걸리지 않는다 — 이력이 없어도 enabled 소스 전체가 0 행으로 렌더된다 (spec §5.2 "12회 내내 부재인 소스도 0 으로 노출" 취지의 정상 동작).
  섹션 ④ (tier 분포) 는 `articles` 자체 집계라 가드가 없다 — 기사 0건이면 분모 0 방지용 `or 1` 가드만 적용된다.
- **콜드 스타트 화면** — `pipeline_runs` · `source_freshness` 모두 0행일 때 KPI 5종은 `—`, 번역 · 분류 대기만 실수 (articles 직접 카운트라 이력에 안 걸림).
  섹션 ① · ② · ⑤ 는 "이력 없음", 섹션 ③ 은 enabled 소스 전체가 수집량 0 행으로 나오는 표, 섹션 ④ 는 전부 0 행 (기사 0건이면 0% 로 렌더) 이다.

## dbt 마트 조회

뷰와 별개로, dbt 마트가 같은 정의 (spec §5) 로 지표를 재현하는지 직접 확인할 수 있다.

```bash
cd dbt && uv run dbt build --profiles-dir .
duckdb dbt/bullet_in.duckdb "select * from slo_rollup"
```

- `slo_rollup` 은 SLO-2 · SLO-5 · duration 3행 (long 포맷: `slo_id` · `metric` · `value`).
  **SLO-6 은 여기 없다** — dbt 는 run.py 메모리 값 (`anomaly_count`) 을 받을 수단이 없어, 뷰의 SLO 롤업 4행 중 SLO-6 한 행만 마트에서 제외된다 (spec §7.2 "SLO-6 비대칭").
- `tier_distribution` 은 뷰의 ④ tier 분포와 동일한 `GROUP BY tier` 결과를 `tier` · `n_articles` · `pct` 로 담는다.
- 두 마트 모두 `materialized='table'` 이라 dbt 세션 없이도 duckdb CLI 또는 `uv run python -c "import duckdb; duckdb.connect('dbt/bullet_in.duckdb', read_only=True)..."` 로 직접 열어 조회할 수 있다.
- 조회 중 `Failed to bind column reference` 류의 binder 오류를 만나면 dbt 버그가 아니라 알려진 duckdb + mysql_scanner 조합 함정이다 → `docs/troubleshooting/2026-07-14-duckdb-mysql-scanner-binder-error.md`.

## 참고

- spec: `docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md`.
- 함정: `docs/troubleshooting/2026-07-13-sparse-source-counts-trend-bias.md` (부재 = 0 vs 진짜 결측) ·
  `docs/troubleshooting/2026-07-13-freshness-clock-mixing-gap.md` (시계 혼합) ·
  `docs/troubleshooting/2026-07-14-duckdb-mysql-scanner-binder-error.md` (dbt 마트 조회 binder 오류).
- 관련 운영 문서: `docs/runbook/2026-07-13-freshness-watermark-ops.md` (SLO-5 알림 자체 해석) ·
  `docs/runbook/2026-07-13-collection-alerts-ops.md` (SLO-6 알림 자체 해석).
