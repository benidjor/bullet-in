# 수집 현황 모니터링 뷰 설계 (2026-07-14)

로드맵 SoT ( `docs/superpowers/2026-06-28-v1-completion-roadmap.md` ) Tier 3 항목 7 구현.
초기 설계 §4 "수집 현황 모니터링 = SLO 메트릭 + 수집현황 뷰" 와 §7 dbt 마트 약속 ( `tier_distribution` · `slo_rollup` ) 을 함께 이행한다.

## 1. 배경 · 문제

- **알림 뒤 확인할 곳 부재** — SLO-5 · SLO-6 Discord 알림은 "문제 발생" 만 통지하고, 받은 뒤 추세 · 맥락을 확인하려면 DB 에 SQL 을 직접 쳐야 함.
- **소비자 없는 이력** — `pipeline_runs` · `source_freshness` ( PR #36 ) 에 회차별 이력이 쌓이지만 읽는 화면이 없음.
- **로드맵 약속 미이행** — dbt 마트 `tier_distribution` · `slo_rollup` 이 초기 설계 §7 에 약속됐으나 `daily_source_quality` 만 존재.

## 2. 목표 · 비목표

- **목표** — 운영자용 정적 페이지 `site/ops.html` 을 매 파이프라인 회차 생성 ( KPI 타일 6종 + 섹션 5개 ).
- **목표** — dbt 마트 `tier_distribution` · `slo_rollup` + staging 2종 추가, 기존 수동 게이트 안에서 동작.
- **목표** — index 푸터에 '수집 현황' 링크 1개.
- **비목표 ( YAGNI )** — dbt 의 파이프라인 연동 없음 ( §3 데이터 경로 결정 참조 ).
- **비목표** — 에러 상세 내역 · 알림 발송 이력 적재 없음 ( 둘 다 신규 스키마가 필요해 별도 트랙 ).
- **비목표** — 브라우저 JS · 외부 차트 라이브러리 · 배포 / 접근 제어 없음 ( 로컬 정적 사이트 전제 ).

## 3. 결정 사항 — 데이터 경로 · 시각화 · 용어

### 3.1. 데이터 경로 = MariaDB 직접 집계 ( A안 )

- **뷰** — run.py 가 MariaDB 에서 직접 집계해 렌더. dbt 마트는 분석 · 게이트용으로 독립 유지.
- **기각한 대안** — dbt run 을 파이프라인에 연결하고 뷰가 DuckDB 마트를 소비 ( B안 ).
  지표 정의 단일화 이점은 있으나, dbt 실패 = 뷰 실패가 되어 "뷰가 가장 필요한 순간에 같이 죽는" 구조.
  관측 도구는 관측 대상보다 단순해야 한다는 원칙으로 기각.
- **이중화 상쇄 장치** — 뷰용 SQL 과 dbt 모델의 지표 정의가 어긋나지 않도록 §5 지표 정의 표를 양쪽의 단일 기준으로 삼는다.
- **전환 여지** — 추후 dbt 를 Airflow 정식 태스크로 승격하는 트랙에서 뷰의 데이터 소스를 마트로 교체 가능 ( 렌더 입력 교체 수준 ).

### 3.2. 시각화 = KPI 타일 + 스파크라인 표 + 바 차트 ( 정적 SVG )

- 스파크라인 · 바 차트는 파이썬이 SVG 좌표를 계산해 템플릿에 주입 — 브라우저 JS 없이 완결.
- 호버 상세는 SVG `<title>` / `title` 속성 ( 브라우저 기본 툴팁 ) 으로 처리.
- 확정 목업: `docs/superpowers/specs/assets/2026-07-14-ops-view-mockup.html` ( 구현 기준 ).

### 3.3. 용어 — 운영자 화면의 자연어 표기

| 내부 용어 | 화면 표기 |
|---|---|
| enrich 잔량 | 번역 · 분류 대기 |
| stale 소스 | 수집 끊긴 소스 |
| freshness 위반 배지 | ✕ 초과 / ✓ 신선 |

## 4. 아키텍처 · 데이터 흐름

```
run.py (매 회차, pipeline_runs INSERT 후)
  ├─ MartStore.ops_snapshot(...)          ← 신규: MariaDB 집계 메서드
  │    pipeline_runs (최근 30회) · source_freshness (최근 12회)
  │    articles (tier 분포 · 번역/분류 대기)
  ├─ 순수 가공 함수 (뷰모델 구성 · SVG 좌표)
  └─ write_ops(snapshot, sources, "site")  ← 신규: serve/render.py
       └─ templates/ops.html.j2 → site/ops.html
```

- **렌더 시점** — `pipeline_runs` INSERT **후**.
  현재 회차가 "최근 30회" 에 포함되고, KPI 타일이 메모리 값과 DB 값을 섞지 않고 DB 한 경로만 읽는다 ( 출처 혼합 차단 ).
- **실패 격리** — `write_ops` 는 try/except 로 감싸 실패 시 `WARNING` 로깅 후 파이프라인 계속.
  실패 시 `site/ops.html` 은 직전 회차 파일이 남으며, 상단 "생성: … UTC" 표기가 낡음을 드러낸다.
- **역할 배치** — SQL 집계 = `MartStore` ( `source_watermarks()` 와 동급 ), 가공 = 순수 함수, 렌더 = `serve/render.py` + Jinja2.
  신규 모듈 없이 기존 두 파일에 추가.
- **예외** — SLO-6 이상 감지 결과만 run.py 메모리 값 ( 방금 계산한 `anomalies` ) 을 전달받는다 ( §5.2 ⑤ SLO 롤업 ).
  감지 결과가 DB 에 저장되지 않기 때문이며, 이 예외는 여기 한 곳뿐이다.

## 5. 화면 구성 · 지표 정의 ( 뷰 SQL 과 dbt 모델의 단일 기준 )

원칙: 뷰는 **기존 판정 로직과 같은 정의** 를 쓴다.
뷰가 자체 해석을 만들면 알림과 뷰가 다른 말을 하게 된다.

### 5.1. KPI 타일 ( 6종 )

| 타일 | 정의 ( 원천 ) |
|---|---|
| 신규 · 중복 차단 · 에러 · 성공률 | `pipeline_runs` 최신 1행의 `new_count` · `dup_count` · `error_count` · `success_rate` |
| 수집 끊긴 소스 | `source_freshness` 최신 run 의 `stale = 1` 행 수 — 저장값 그대로, 재계산 금지 |
| 번역 · 분류 대기 | `rows_missing_translation()` · `rows_missing_stage()` 와 동일한 WHERE 로 카운트한 합 |

### 5.2. 섹션 5개

| 섹션 | 정의 ( 원천 ) |
|---|---|
| ① 회차별 수집량 | `pipeline_runs` 최근 30회. 막대 = `new_count`, 빨강 = `error_count > 0`, 호버 = 시각 · 신규 / 중복 / 에러 |
| ② 소스별 신선도 | `source_freshness` 최신 run 의 전 행 + 최근 12회 `age_hours` 스파크라인. `age_hours` 는 SLO-5 저장값 표시만 |
| ③ 소스별 수집량 · 번역 · 분류 대기 | `source_counts` JSON 최근 12회 합 ( 부재 = 0 ) + 소스별 대기 카운트. enabled 소스 전체를 행으로 표시 — 12회 내내 부재인 소스도 0 으로 노출 ( 죽은 소스일수록 보여야 함 ) |
| ④ tier 분포 | `articles` 전체 `GROUP BY tier`, 정의 밖 값은 "기타" 버킷 |
| ⑤ SLO 롤업 | SLO-2 = 최근 30회 평균 `success_rate` · SLO-5 = 수집 끊긴 소스 수 ( 최신 run ) · SLO-6 = 현재 회차 이상 감지 소스 수 ( run.py 메모리 전달 ) · duration = 최근 30회 평균 ( 참고치 ) |

### 5.3. 경계값

- **30회** — 차트 · SLO 평균. 하루 4회 스케줄 기준 약 일주일.
- **12회** — 신선도 추세 · 소스별 합계. SLO-6 이상 탐지와 같은 크기의 창이지만 위상이 한 회차 다르다:
  SLO-6 은 현재 런 INSERT 전 직전 12회 ( run.py 조회 시점 ), 뷰는 INSERT 후 최근 12회 ( 현재 런 포함 ).
  ( 정정 2026-07-14: 원문 "같은 창을 본다" 가 이 한 회차 차이를 숨겨 정밀화 — PR #39 최종 리뷰 이월 ② )

## 6. 데이터 계약 — 직전 트랙 함정 2건의 예방 반영

### 6.1. 부재의 의미가 다른 두 컬렉션

| 컬렉션 | 부재 회차의 의미 | 뷰 처리 |
|---|---|---|
| `source_counts` ( 희소 JSON ) | 그 회차 신규 0건 | **부재 = 0** 으로 합산 ( `h.get(sid, 0)` ) — 판정 계층과 동일 계약 |
| `source_freshness` ( 매 회차 전 소스 기록 ) | 그때 소스가 config 에 없었음 | **진짜 결측** — 있는 회차만으로 스파크라인 |

두 계약의 차이가 혼동 지점이므로 구현 · 리뷰 시 이 표를 기준으로 대조한다.
근거: `docs/troubleshooting/2026-07-13-sparse-source-counts-trend-bias.md`.

### 6.2. 시계 · 저장값 계약

- **페이지 생성 시각** — `MartStore.db_now()` ( `SELECT UTC_TIMESTAMP()` ) 재사용, 화면에 "UTC" 명기.
  근거: `docs/troubleshooting/2026-07-13-freshness-clock-mixing-gap.md`.
- **재계산 금지** — `age_hours` · `stale` 은 SLO-5 가 UTC 고정 시계로 계산해 저장한 값을 그대로 표시.
  뷰가 재계산하면 판정과 표시가 어긋날 수 있다.
- **대기 카운트 정합** — 번역 · 분류 대기는 `rows_missing_*` 와 WHERE 절을 공유해 "다음 Gemini 사이클이 처리할 잔량" 과 정확히 일치시킨다.

## 7. dbt 마트

### 7.1. 신규 모델 4개

- `staging/stg_pipeline_runs.sql` — `maria.pipeline_runs` 에서 run_id · started_at · duration_sec · new / dup / error · success_rate.
- `staging/stg_source_freshness.sql` — `maria.source_freshness` 에서 run_id · checked_at · source_id · age_hours · stale.
- `marts/tier_distribution.sql` — `stg_articles` 를 `GROUP BY tier`: `tier` · `n_articles` · `pct`.
- `marts/slo_rollup.sql` — SLO 당 1행 long 포맷 ( `slo_id` · `metric` · `value` ): SLO-2 · SLO-5 · duration.
  지표 정의는 §5 표와 동일.

### 7.2. 테스트 · 비대칭 · 회귀

- **스키마 테스트** — `tier_distribution.tier` · `slo_rollup.slo_id` 에 `unique` + `not_null` ( sources.yml ).
- **SLO-6 비대칭** — dbt 마트에서 SLO-6 제외.
  감지 결과가 DB 에 없고, dbt 는 뷰와 달리 run.py 메모리 값을 받을 수 없다.
- **게이트 회귀** — 머지 전 `dbt build` 로 신규 모델 테스트 + 기존 게이트 ( `stg_articles` · `daily_source_quality` ) 통과 확인.

## 8. 에러 처리 · 엣지 케이스

| 상황 | 처리 |
|---|---|
| 콜드 스타트 ( 이력 테이블 0행 ) | 섹션 ① · ② · ⑤ "이력 없음" 문구, 타일 `—` 표시, 템플릿 가드로 렌더 생존. 단 ③ 은 enabled 소스 전체 0 행 · ④ 는 전부 0 행 렌더가 정상 ( §5.2 "부재 소스도 0 으로 노출" ) |
| 수집 이력 없는 소스 ( `age_hours = NULL` ) | 배지 "이력 없음" ( 중립색 ) — 판정 계층이 stale 로 치지 않으므로 뷰도 빨강 금지 |
| 나중에 추가된 소스 ( 추세 앞부분 부재 ) | 있는 회차만으로 스파크라인 ( §6.1 진짜 결측 ) |
| 스파크라인 값 전부 0 · 동일값 | 스케일 분모 `max(1, …)` 가드, 평평한 선으로 렌더 |
| tier 정의 밖 값 | "기타" 버킷 흡수 |
| `write_ops` 예외 | `WARNING` 로깅 후 파이프라인 계속 ( §4 실패 격리 ) |

## 9. 테스트 전략

- **단위 — 가공 순수 함수**:
  부재 = 0 합산은 **부분 부재 픽스처 필수** ( 일부 회차에만 키가 있는 소스가 0 포함 합산되는지 — 전 키 존재 픽스처만으로는 이 계열 결함이 안 잡힘 ).
  `age_hours = NULL` → "이력 없음", 부분 이력 소스 → 있는 회차만 스파크라인.
  좌표 생성은 전부 0 · 단일값 · 정상 시퀀스에서 0-나눗셈 없이 산출.
- **단위 — 렌더 스모크**: `render_ops()` 가 정상 · 콜드 스타트 양쪽에서 HTML 을 뱉고 KPI 타일 · 섹션 제목 · "수집 끊긴 소스" 라벨이 존재.
- **통합** ( DB 없으면 skip — 기존 패턴 ): `MartStore` 신규 집계 메서드를 시드로 검증 — 30회 경계 ( 초과 시드 ), NULL age 행 포함.
- **dbt**: `dbt build` 통과 ( 신규 4 모델 + 기존 게이트 회귀 ).
- **라이브 검증** ( verification-before-completion ): 종단 실행 후 `site/ops.html` 브라우저 육안 확인 ( 차트 · 라벨 겹침은 자동 검증 사각 ), 캡처를 PR 에 첨부, index 푸터 링크 진입 확인.

## 10. 성공 기준

- 종단 실행 후 `site/ops.html` 이 생성되고 KPI 타일 6종 + 섹션 5개가 목업과 일치.
- `uv run pytest -q` 통과 ( 신규 단위 · 통합 포함 ).
- `dbt build` 통과 ( 신규 마트 2 + staging 2 + 기존 게이트 ).
- index 푸터 '수집 현황' 링크로 진입 가능.
- 운영 문서: 런북 ( 뷰 해석 · 실패 모드 ) 을 코드와 같은 PR 에 동반.
