# 대시보드 두 화면 개편 설계 (2026-09-05)

운영자용 화면 둘 (행동 지표 `behavior.html` · 수집 현황 `ops.html`) 은 지금 표와 CSS 막대뿐이고 시계열 · 퍼널 · 리텐션 · SLO 여섯 행이 없다.
2026-09-04 밤에 실제 데이터로 목업을 여덟 판 돌려 v2.8 을 확정했다.
이 문서는 목업을 다시 설명하지 않고 가리킨다.
목업이 정하지 않은 것, 곧 데이터 계약 · 코드 자리 · 첫 회차의 빈 구간 · 검증 · PR 분할만 정한다.

안건 `2φ` 의 설계다.
구현 계획은 별도 문서로 쓴다.

## 1. 확정된 화면은 목업 v2.8 이다

- 주소 = https://claude.ai/code/artifact/412a19f4-40af-4edd-8d9e-02ec483b9854 (버전 선택기에서 v2.8).
- 목업의 숫자는 2026-09-04 19:24 KST 추출이고 그 값이 런북 `2026-09-04-measuring-visitors-funnel-and-retention-from-bronze.md` §9 의 기준값이다.
- 목업의 절과 `id` 는 그대로 화면의 절과 `id` 가 된다.

| 화면 | 절 (목업 순서) |
| --- | --- |
| 행동 지표 | 타일 여섯 · `sec-dau` · `sec-engagement-funnel` · `sec-activity-heatmap` · `sec-engagement-by-dimension` · `sec-retention` · `sec-clicks-by-surface` · `sec-pages-sessions` · `sec-top-articles` · `sec-player-pages` |
| 수집 현황 | 타일 여섯 · `sec-slo` · `sec-ingestion-volume` · `sec-source-coverage` · `sec-throughput` · `sec-run-duration` · `sec-ingestion-latency` · `sec-coverage-by-player` · `sec-credibility-mix-stage-mix` · `sec-source-freshness` |

목업이 이미 정한 것은 이 문서가 되풀이하지 않는다.
용어 · 색 계열 셋과 순서형 램프 · 퍼널의 끝이 재방문인 것 · 공개일 (08-29) 을 평균 · 비율 · 분포에서 빼고 절마다 「제외 | 포함」 을 두는 것 · 구성 비율은 숫자를 적은 히트맵인 것 · 설명문이 서술형이고 인사이트가 두 층인 것 · 상단 고정과 목차 · 선수 축이 기사 주체 기준이고 감독 · 임원을 빼는 것 · SLO 여섯 행이 그것이다.
정본은 목업이고 다툼이 생기면 목업을 본다.

## 2. 지금 코드 (2026-09-05 실측)

- 렌더 = `src/bullet_in/serve/render.py` 의 `build_ops_view` 와 `render_behavior` 다.
  행동 화면은 뷰모델이 따로 없고 `state/behavior_metrics.json` 을 그대로 템플릿에 넘긴다.
  SVG 헬퍼는 스파크라인 하나 (`spark_points`) 뿐이고 나머지 막대는 전부 CSS 다.
  템플릿 `ops.html.j2` (143줄) 와 `behavior.html.j2` (90줄) 는 `_layout.html.j2` 를 안 쓰는 독립 문서이고 `noindex` 다.
- 행동 로그 = `src/bullet_in/warehouse.py` 한 모듈이다.
  Iceberg `behavior` 네임스페이스에 bronze `ga4_events` · silver `ga4_events_flat` · gold `fact_card_click` · `dim_date` 가 있고 gold 는 회차마다 silver 에서 통째로 다시 만든다 (`build_gold`).
  집계는 `aggregate` 하나이고 `write_metrics` 가 JSON 파일로 내린다.
  렌더가 Iceberg 인증 없이 돌아야 해서 파일을 거친다 (그 주석이 `warehouse.py` 에 있다).
- 수집 현황의 데이터는 `Mart.ops_snapshot()` 한 번이다 (최근 30회 · 신선도 12회 · 등급 분포 · 미처리 · 재작성 잔존).
- SLO 는 두 곳이 따로 센다.
  `render.py` 가 다섯 행을 만들고 dbt `gold_slo_rollup` 이 넷을 만드는데 서로 안 읽는다.
  중복 적재율 · 필드 완전성 · 수집량 이상은 dbt 모델에 없고 `dbt/target/run_results.json` 은 `dbt_gate.parse_results` 만 읽는다.
  README §4 표는 번호가 없고 신선도 행도 없다.
- 회차 = Airflow DAG 의 `publish` 태스크가 두 화면을 그린다.
  `warehouse_load` 는 `publish` 뒤 병렬 가지라 행동 화면은 늘 직전 적재의 JSON 을 보여 주고, `gate` 는 `publish` 뒤라 `run_results.json` 도 직전 회차 것이다.
  `confirm_player._render` 는 두 화면을 안 그린다.
- 계측은 이미 고쳐져 있다.
  배포본 `app.js` 가 `card_slug` 를 보내고 (2026-09-05 00:24 확인), gold 의 선수 카드 클릭 44건은 전부 09-01 이전이라 #439 배포 (09-03) 전 것이다.
  트러블슈팅 `2026-09-04-three-charts-that-pointed-at-the-wrong-layer.md` §3 의 「값이 이벤트 파라미터로는 안 나간다」 는 틀렸다.

## 3. 결정

### 3.1. 행동 화면의 데이터 경로 — gold 표 셋을 새로 만들고 화면은 JSON 하나만 읽는다

목업의 방문 · 세션 · 퍼널 · 리텐션 축은 silver 를 파이썬으로 직접 읽어 만들었다.
같은 질문을 화면 · 런북 · 테스트가 각자 세면 두 키 함정 (`bi_cid` 와 `user_pseudo_id` 를 섞어 두 배로 센 것) 이 되풀이된다.
그래서 사람 · 세션 · 코호트를 gold 표 셋으로 한 번 만들고 사람 수가 들어가는 집계는 전부 그 위에서 한다.
경로별 페이지 뷰만 silver 의 `page_view` 행을 직접 센다.

| 표 | 알갱이 | 컬럼 |
| --- | --- | --- |
| `fact_session` | 사용자 × GA4 세션 | `user_pseudo_id` · `ga_session_id` · `session_date_kst` · `started_at` · `start_hour_kst` · `weekday_kst` · `engaged` · `device_category` · `traffic_source` · `traffic_medium` · `n_page_views` · `n_card_clicks` · `n_filter_applies` · `n_origin_exits` · `engagement_msec` |
| `fact_user_daily` | 사용자 × 날짜 (KST) | `user_pseudo_id` · `date_kst` · `is_new` · `n_sessions` · `n_entries` · `n_card_clicks` · `n_article_views` · `n_player_views` · `n_origin_exits` · `used_trust_filter` · `device_category` |
| `dim_user` | 사용자 | `user_pseudo_id` · `first_date_kst` · `first_device` · `first_source` · `first_medium` · `n_active_days` · `n_card_clicks` |

- 셋 다 `build_gold` 와 같은 방식이다.
  silver 에서 통째로 다시 만들고 덮어쓴다.
  사람을 세는 키는 `user_pseudo_id` 하나이고 `bi_cid` 는 어디에도 안 쓴다.
- `is_new` 는 `dim_user.first_date_kst` 와 같은 날이다.
  `n_article_views` 와 `n_player_views` 는 `page_view` 의 `page_location` 경로가 `/article/` · `/player/` 로 시작하는 수다.
  `used_trust_filter` 는 그날 `bi_filter_apply` 가운데 `n_tier` 나 `n_journalist` 가 0 이 아닌 것이 있는지다 (런북 §9 의 「신뢰도 · 기자 필터 사용자」 가 이 정의다).
- `fact_card_click` 과 `dim_date` 는 그대로 둔다.
  Engagement by Dimension 절은 지금 `aggregate` 가 만드는 `axes` 를 그대로 쓴다.

집계는 `aggregate` 하나를 다섯 함수로 가른다.

| 함수 | 입력 | 결과 키 | 창 |
| --- | --- | --- | --- |
| `agg_daily` | `fact_user_daily` · `fact_session` | `daily` (날짜별 DAU · 신규 · 재방문 · 세션 · 참여 세션 · 카드 클릭 · 기기별 사용자 · 화면별 클릭) | 최근 28일 |
| `agg_funnel` | `fact_user_daily` | `funnel` (진입 · 카드 클릭 · 2건 이상 · 2일 이상 방문) 과 곁가지 둘 (필터 사용 · 원문 이동) | 최근 28일 |
| `agg_heatmap` | `fact_session` | `heat` (요일 × 시각 고유 사용자) · `excl` 과 `incl` 두 벌 | 공개 뒤 전체 |
| `agg_retention` | `dim_user` · `fact_user_daily` | `retention` (코호트 × D+0 에서 D+6) | 최근 14 코호트 |
| `agg_pages` | `fact_session` · silver `page_view` | `pages` (경로별 뷰 · 체류 구간 · 선수 슬러그별 뷰 · 상위 기사 해시 12) | 최근 28일 |

- 타일 여섯은 `agg_daily` 를 마지막 7일 창으로 한 번 더 돌린 `weekly` 에서 만든다.
  고유 사용자 수는 날짜별 값을 더해서 못 얻기 때문이다.
- 함수마다 `start` · `end` 를 받는다.
  기본값은 위 창이고, 검증은 08-28 에서 09-03 을 넣어 §9 를 재현한다 (§5).
- 공개일 규칙은 트러블슈팅 `2026-09-04-two-keys-double-the-visitor-count.md` §5 그대로다.
  총량 · 시계열에는 넣고 평균 · 비율 · 분포에서는 뺀다.
  히트맵과 축 넷은 `excl` · `incl` 두 벌을 다 내려서 화면의 토글이 서버에 안 묻게 한다.
- Player Pages 절의 이적 상태는 JSON 에 없다.
  렌더가 `PlayerStore` 에서 `transfer_status` 를 읽어 슬러그에 붙이고 라벨은 `render.py` 의 상태 그룹 다섯을 그대로 쓴다.
- `write_metrics` 는 위 키를 기존 `axes` · `totals` · `generated_at` 옆에 더한 JSON 하나를 같은 자리 (`state/behavior_metrics.json`) 에 쓴다.
  파일 하나를 유지하는 이유는 §2 의 인증 경계와 같다.

### 3.2. 차트는 `serve/charts.py` 로 옮긴다

- 목업 생성기의 차트 함수 12종 (스파크라인 · 선 · 누적 막대 · 가로 막대 · diverging · 퍼널 · 히트맵 · 캘린더 · 미터 · 덤벨 · 범례 · 표) 을 순수 함수로 옮긴다.
  입력은 파이썬 값이고 출력은 SVG 문자열이다.
- 색은 SVG 속성에 직접 적지 않고 CSS 클래스로 건다.
  presentation attribute 에 `var()` 가 안 통해 색이 통째로 죽는다 (목업에서 밟았다).
- 목업 생성기 원본은 세션 스크래치패드에만 있어 사라진다.
  코드 PR 의 첫 태스크가 이 파일을 옮기는 것이고 계획서가 그 원본 경로를 적는다.

### 3.3. 템플릿은 두 페이지 · 공통 조각 하나 · 작은 JS

- `behavior.html.j2` 와 `ops.html.j2` 를 목업대로 다시 쓴다.
  상단 (제목 · 두 화면 링크 · 목차) · 스타일 · JS 는 `_dash.html.j2` 한 조각에 두고 둘이 그것을 상속한다 (`extends`).
- 행동 화면의 뷰모델은 새 모듈 `serve/behavior_view.py` 에 둔다.
  `render.py` 가 2,200줄이라 더 얹지 않는다.
- 목업의 탭은 페이지 하나 안의 전환이었지만 실제는 페이지 둘이다.
  탭 자리는 두 페이지로 가는 링크이고 현재 페이지가 선택된 모양이다.
- JS 는 셋뿐이다.
  공개일 토글 (두 벌 가운데 하나를 `hidden`) · 목차의 현재 절 표시 · 툴팁.
  `app.js` 는 싣지 않고 `noindex` 는 그대로다.
- 설명문 (`.q`) 은 목업 문장을 그대로 옮긴다.
  인사이트 (`.ins`) 는 값에서 만들 수 있는 문장만 남기고 숫자를 뷰에서 채운다.
  「시각을 옮길 근거가 된다」 같은 해석 문장은 화면에 안 싣는다.
  화면은 매 회차 새 값으로 그려지는데 해석은 그 값이 바뀌어도 안 바뀌기 때문이다.

### 3.4. 수집 현황은 MariaDB 직접 읽기 + 게이트 결과 파일

- `Mart.ops_snapshot()` 을 넓힌다.
  첫 라이브 실행 (06-12) 부터의 회차 전체 (`started_at` · `duration_sec` · `fetch_duration_sec` · `source_counts` · `new_count` · `dup_count` · `error_count` · `success_rate`) · 발행에서 수집까지 지연 행 (07-14 이후 · 30일 초과 제외) · 주별 등급 · 단계 · 기자 식별 수 · 기사 주체 기준 선수 상위 10 · 신선도 이력 3일이 더 온다.
  SQL 은 런북 §8 의 셋을 그대로 쓴다.
- 소스 × 주 행렬은 `pipeline_runs.source_counts` 로 그린다.
  `articles.fetched_at` 은 재수집 backfill 이 옮기므로 6월이 빈다 (트러블슈팅 `three-charts` §1).
- 선수 축은 `article_players.role = 'subject'` 이고 `players.category IN ('squad', 'external')` 이다 (같은 문서 §2).
- 뷰모델은 `build_ops_view` 안에 여섯을 더한다.
  캘린더 (일별 신규 · 회차 수) · 소스 × 주 · 처리량 (주별 신규 · 중복 차단) · 소요 밴드 (p10 에서 p90 · p50 · 주별 구성) · 발행에서 수집까지 지연 (소스별 p50 · p95) · 주별 구성 비율 (등급 · 단계).
- SLO-3 (중복 적재율) 과 SLO-4 (필수 필드 완전성) 는 `dbt/target/run_results.json` 에서 읽는다.
  파서는 `dbt_gate.parse_results` 를 그대로 쓰고 `unique` 테스트 전부 통과가 SLO-3 · `not_null` 테스트 전부 통과가 SLO-4 다.
  파일이 없으면 두 행의 값은 「게이트 결과 없음」 이고 상태는 `info` 다.
  이 값은 직전 회차 게이트의 것이라 화면에 게이트 시각을 함께 적는다.
- SLO-1 은 회차마다 안 재므로 런북 값을 고정으로 적는다 (목업과 같다).

### 3.5. README §4 에 SLO 번호 여섯을 적는다

지금 표는 다섯 행이고 번호가 없다.
번호를 붙이고 신선도 행을 더한다.

| 번호 | README 지금 행 | 처리 |
| --- | --- | --- |
| SLO-1 | 병렬화 수집 시간 단축 | 번호만 |
| SLO-2 | 일일 수집 성공률 | 번호만 · 행을 둘째로 |
| SLO-3 | 중복 적재율 | 번호만 |
| SLO-4 | 필수 필드 완전성 | 번호만 |
| SLO-5 | 없음 | 「소스 신선도 · 끊긴 소스 0 · `source_freshness` 워터마크」 행 신설 |
| SLO-6 | 수집량 이상 감지 | 번호만 |

화면의 ※ 는 이 표가 머지되면 뗀다.
실측 열의 낡은 값 (07-19 · 358건) 은 안건 `2χ` 의 몫이라 여기서 안 건드린다.

### 3.6. 계측은 고치지 않고 확인한다

- §2 대로 슬러그는 이미 나간다.
  코드 PR 에서 할 일은 배포 뒤 브라우저 (광고 차단 없는 것) 로 선수 카드를 한 번 누르고, 다음 날 silver 에 `card_surface = 'pcard'` 이고 `card_slug` 가 찬 행이 생기는지 보는 것이다.
- 생기면 트러블슈팅 `three-charts` §3 을 「#439 배포 전 44건은 되살릴 수 없고 그 뒤는 슬러그가 실린다」 로 고친다.
  안 생기면 그때 `app.js` 를 본다.
- Player Pages 절의 선수별 수는 페이지 뷰 (`/player/<슬러그>`) 로 세므로 카드 클릭 슬러그와 무관하게 지금 데이터로 그려진다.

### 3.7. PR 은 셋이고 순서가 있다

| PR | 범위 | 배포 |
| --- | --- | --- |
| 0 | 이 스펙 · 계획서 | 없음 |
| 1 | 행동 화면 — gold 표 셋 · 집계 다섯 · JSON · `charts.py` · `_dash.html.j2` · `behavior.html.j2` · 테스트 · 트러블슈팅 §3 정정 | 회차가 받는다 |
| 2 | 수집 현황 — `ops_snapshot` 확장 · 뷰모델 여섯 · `ops.html.j2` · SLO-3 · 4 · README §4 · 테스트 | 회차가 받는다 |

- PR 1 이 `charts.py` 와 `_dash.html.j2` 를 만들고 PR 2 가 그것을 쓴다.
  그래서 순서를 바꿀 수 없다.
- 마감 (09-09) 이 빠듯하면 PR 2 를 마감 뒤로 미룬다.
  그때 README 개편 (`2χ`) 과 슬라이드는 새 행동 화면과 지금의 수집 현황 화면을 캡처한다.
- 2026-09-05 결정 (사용자) = PR 1 을 먼저 하고, PR 2 를 마감 안에 넣을지는 09-06 저녁에 PR 1 의 진행을 보고 정한다.

## 4. 첫 회차의 빈 구간

- PR 1 이 머지되면 `advance` 가 코드를 받은 회차의 `publish` 는 옛 모양의 JSON (`daily` 등이 없다) 을 읽는다.
  새 JSON 은 같은 회차의 `warehouse_load` 가 끝나야 생기고 다음 회차 `publish` 가 읽는다.
- 그래서 렌더는 키가 없는 절을 「다음 적재 뒤에 채워진다」 한 줄로 그리고 실패하지 않는다.
  `publish` 의 예외 격리가 있지만 그것은 화면이 통째로 안 나가는 길이라 여기서 쓰면 안 된다.
- gold 표 셋은 `build_gold` 와 같은 태스크에서 만들어지므로 따로 부트스트랩이 없다.
- `ops_snapshot` 확장은 읽기만 늘고 스키마 변경이 없어 빈 구간이 없다.

## 5. 검증

- 단위 테스트는 기존 자리를 따른다.
  gold 행 생성과 집계 다섯은 `tests/test_warehouse.py`, 차트는 새 `tests/test_charts.py`, 두 화면은 `tests/test_behavior_view.py` · `tests/test_ops_view.py` · `tests/test_serve_ops.py` 다.
  차트 테스트는 픽셀이 아니라 구조 (막대 수 · 라벨 · 툴팁 문자열 · 클래스) 를 단언한다.
- 기준값 재현은 코드가 한다.
  `python -m bullet_in.warehouse show --from 2026-08-28 --to 2026-09-03` 이 §9 표의 값을 그대로 찍어야 한다.
  PR 1 의 본문에 그 출력을 붙인다.
  다르면 표가 아니라 런북 절차와 어디가 다른지를 먼저 찾는다 (§9 의 규칙).
- 내가 지어 만든 픽스처는 컬럼 이름을 검증하지 못한다.
  gold 행 생성 테스트 하나는 silver 의 실제 컬럼 목록 (`FLAT_BASE_TYPES` · `NESTED_COLUMNS` · 계측 파라미터 이름) 에서 픽스처를 만든다.
- 배포 뒤 화면은 `curl -sL` 로 받아 절 `id` 열여덟과 SVG 수를 센다.
  캡처는 README 개편이 쓴다.
- 테스트 기준선은 1,704 이다.
- `docs/` 문서는 서식 훅을 통과하고 PR 본문은 `check-pr-format.py` 와 humanize fast 를 거친다.

## 6. 범위 밖

- 21시 회차 시각 이동 (히트맵이 근거를 주지만 이 안건이 아니다).
- dbt `gold_slo_rollup` 에 SLO-3 · 4 · 6 을 더하는 것.
- 사이트 내비게이션에서 두 화면으로 가는 링크.
- 기사 상세의 선수 칩 (`a.pchip`) · 홈의 스토리 링크 (`a.storylink`) 클릭 계측.
- `confirm_player._render` 가 두 화면도 그리게 하는 것.
- README §4 실측 열의 갱신 (`2χ`).

## 7. 참조

- 목업 = §1 의 주소 · 정본 메모리 `dashboard-redesign-track-2026-09-04`.
- 런북 `docs/runbook/2026-09-04-measuring-visitors-funnel-and-retention-from-bronze.md` (§8 SQL · §9 기준값).
- 트러블슈팅 `docs/troubleshooting/2026-09-04-two-keys-double-the-visitor-count.md` · `2026-09-04-three-charts-that-pointed-at-the-wrong-layer.md`.
- 앞선 설계 `docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md` (§5 지표 정의는 이 문서의 §3.4 가 대신한다) · `2026-09-02-behavior-log-bronze-design.md` · `2026-08-31-analytics-event-schema.md`.
