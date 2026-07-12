# SLO-6 수집 이상 알림 — 하드 실패 · 소프트 드리프트 설계 (2026-07-13)

수집 파이프라인이 깨졌을 때 아무도 모르는 현재 공백을, Discord 알림으로 두 방향에서 메우는 설계.
하드 실패 (파이프라인이 예외로 죽음) 는 Airflow `on_failure_callback` 으로, 소프트 드리프트 (실행은 성공했으나 한 소스가 조용히 0건) 는 수집량 이상탐지 (SLO-6) 로 잡는다.
두 알림은 공유 `notify.py` embed 배관을 함께 쓴다.

## 배경 · 문제

현재 수집이 깨져도 사람이 인지할 경로가 없다.

- **하드 실패 무통지** — DAG 는 `run_pipeline` PythonOperator 하나가 `main()` 전체를 실행하며 `retries` 설정도 없다.
  `main()` 이 예외로 죽으면 (Mongo · MariaDB 연결 실패 · 미처리 예외) Airflow UI 에만 빨간 표시가 뜨고 push 알림은 없다.
- **소프트 드리프트 무통지** — 이 프로젝트의 자주 밟는 함정 1번은 소스 셀렉터 드리프트다.
  외부 사이트가 조용히 바뀌면 어댑터는 `[]` 를 반환할 뿐 예외를 던지지 않아, 태스크는 SUCCESS 로 끝나고 한 소스만 0건이 된 사실이 묻힌다.
- **알림 인프라 전무** — `volume_anomaly()` 는 구현 · 테스트됐으나 run.py 에 연결되지 않았고, 알림 채널 (Slack · 메일 · webhook) 자체가 없다.

## 목적 · 성공 기준

- 파이프라인이 예외로 죽으면 Discord 로 실패 알림을 받는다.
- 한 소스가 평소 대비 이상 수준으로 수집량이 떨어지면 (셀렉터 드리프트) Discord 로 이상 알림을 받는다.
- 두 알림은 `DISCORD_WEBHOOK_URL` env 기반이며, 미설정이면 `WARNING` 로깅으로 폴백해 dev · CI 를 깨지 않는다.
- 알림 발송 실패 (네트워크 오류 · webhook 미설정) 가 파이프라인 · 태스크를 죽이지 않는다.
- 탐지 순수 로직 · notify 배관 · context 매핑을 단위 테스트로 검증한다.

## 설계 결정 (합의)

- **두 알림, 하나의 배관** — 하드 실패와 소프트 드리프트는 성격이 다르지만 (전자는 예외 crash · 후자는 silent 0건) Discord embed 발송 배관을 공유한다.
  상보적이라 둘을 합치면 "수집이 어떤 식으로 깨지든 안다" 가 완성된다.
- **탐지 단위는 소스별** — 총량 감시는 소스 15개 중 1개가 죽어도 노이즈에 묻혀 못 잡는다.
  `source_counts` JSON 에서 소스마다 history 를 뽑아 각각 `volume_anomaly` 를 적용해, 셀렉터 드리프트를 소스 단위로 포착한다.
- **신호는 `source_counts` (dedup 전 원수집 건수)** — 셀렉터가 깨지면 이 값이 0 으로 떨어진다.
  `new_count` 는 dedup 에 희석돼 정상 상태에서도 낮고 변동이 커 부적합하다.
- **저volume floor** — 평균 수집량이 작은 소스 (평균 1 – 2 건) 는 상대 변동이 커 오탐이 잦다.
  history 평균이 `min_baseline` 미만인 소스는 평가에서 건너뛴다 (기본 `min_baseline=3.0`) .
- **단순 last-N 윈도우** — 지난 12 회 (약 3 일) 를 history 로 쓴다.
  동일 시각 (HOUR) 비교는 시간대 계절성을 제거하지만 2 주 이상 이력이 쌓여야 유효하므로 이번엔 단순 last-N 으로 가고, 오탐이 실제 관찰되면 그때 개선한다 (YAGNI) .
- **양방향 탐지** — 기존 `volume_anomaly` 의 2σ 밴드를 그대로 써 드롭 · 스파이크를 모두 잡고, 메시지에 방향을 표기한다.
- **생애주기는 실패만** — `on_failure_callback` 만 부착한다.
  `on_retry_callback` 은 `retries` 설정이 선행돼야 하고, `on_success_callback` 은 4 회/일 성공 스팸이라 이번 범위에서 제외한다.
- **`notify.py` 는 Airflow-free** — Airflow context 추출은 DAG 파일에 두고, `notify.py` 는 title · description · color · fields 만 받는 순수 파이썬으로 유지한다.

## 컴포넌트

### 1. 공유 배관 — `notify.py` (신규)

Discord embed 발송의 단일 창구다.

- **`send_alert(title, description, *, color, fields=None) -> None`** — `{"embeds": [{title, description, color, fields, timestamp}]}` 를 `DISCORD_WEBHOOK_URL` 에 httpx POST 한다.
  `fields` 는 `[{"name", "value", "inline"}]` 형태의 Discord embed 필드 목록이다.
- **폴백** — `DISCORD_WEBHOOK_URL` 미설정이면 POST 하지 않고 `logging.warning` 으로 제목 · 설명을 남긴다.
- **오류 삼킴** — POST 가 예외 · 비정상 상태코드를 내도 로깅만 하고 삼킨다 (알림 실패가 파이프라인 · 태스크를 죽이면 안 됨) .
- **색상** — Discord embed 색은 정수다.
  이상 = 주황 (`0xF2A600`) · 실패 = 빨강 (`0xE01E5A`) 을 상수로 둔다.

### 2. 소프트 드리프트 — 수집량 이상탐지 (SLO-6)

`quality.py` 에 소스별 래퍼를 추가하고 run.py 가 연결한다.

- **`quality.volume_anomalies(today_counts, history_counts, sigma=2.0, min_baseline=3.0) -> list[Anomaly]`** — 순수 함수다.
  `today_counts` 는 `{source_id: count}` · `history_counts` 는 과거 회차별 같은 dict 의 list 다.
  history 와 today 의 소스 합집합을 돌며, 각 소스의 history 평균이 `min_baseline` 이상이면 `volume_anomaly(today, hist, sigma)` 를 적용한다.
  이상이면 `source_id` · `today` · `baseline` (평균) · `direction` (드롭 · 스파이크) 를 담은 항목을 반환한다.
- **today 에서 사라진 소스** — history 에 있으나 today 에 없는 소스는 `today=0` 으로 평가한다 (소스가 조용히 사라진 케이스를 잡는 게 핵심) .
- **run.py 연결** — pipeline_runs INSERT 직전에 지난 12 회 `source_counts` 를 조회한다.
  `volume_anomalies(stats["source_counts"], history)` 를 호출하고, 이상 소스가 있으면 메시지를 포맷해 `notify.send_alert` 로 보낸다.
- **메시지** — title `⚠️ 수집량 이상` · color 주황.
  description 에 `▼ fmkorea: 0건 (평소 ~14)` 형태의 라인들을 담고, field 에 run 시각 · 대상 회차 수를 넣는다.

### 3. 하드 실패 — 생애주기 (`on_failure_callback`)

`airflow/dags/bullet_in_daily.py` 의 `run_pipeline` 태스크에 실패 콜백을 부착한다.

- **순수 매핑 헬퍼** — `_failure_alert(context) -> (title, description, fields)` 를 DAG 모듈에 둔다.
  Airflow context dict 에서 `dag_id` · `task_id` · `run_id` · `try_number` · `duration` · `hostname` · `log_url` · `exception` 을 뽑아 embed 인자로 매핑한다.
  가짜 context dict 로 단위 테스트한다.
- **콜백** — `on_failure_callback` 이 `_failure_alert(context)` 로 인자를 만들어 `notify.send_alert(..., color=빨강)` 를 호출한다.
- **메시지 형식** — title `❌ 파이프라인 실패 — run_pipeline` .
  fields: `DAG/Task` · `Run` · `Try` · `Duration` · `Host` · `로그` (`[열기](log_url)`) .
  description 에 예외 요약을 담는다.

## 데이터 흐름

```
[Airflow run_pipeline 태스크]
      │
      ├─ main() 정상 실행
      │     │
      │     ├─ 수집 · dedup · enrich · 서빙
      │     ├─ (INSERT 직전) 지난 12회 source_counts 조회
      │     ├─ volume_anomalies(today, history)
      │     │        │
      │     │        ▼ 이상 소스 있으면
      │     │     notify.send_alert(⚠️ 수집량 이상, 주황)
      │     └─ pipeline_runs INSERT
      │
      └─ main() 예외 → 태스크 실패
            │
            ▼
      on_failure_callback → _failure_alert(context)
            │
            ▼
      notify.send_alert(❌ 파이프라인 실패, 빨강)
            │
            ▼
   DISCORD_WEBHOOK_URL 설정?
      ├─ 예 → httpx POST (embed)
      └─ 아니오 → logging.warning 폴백
```

## 검증 (TDD)

- **`volume_anomalies`** — ① 한 소스만 0 이면 그 소스만 flag ② today 에서 사라진 소스 flag ③ 저volume 소스는 floor 로 skip ④ history 2 회 미만이면 무탐지 ⑤ 정상 밴드 내면 무탐지.
- **`notify.send_alert`** — env 미설정이면 WARNING 로깅 · POST 안 함 · env 설정이면 올바른 embed payload 로 POST (httpx 모킹) · POST 예외를 삼킴.
- **`_failure_alert`** — 가짜 context dict 를 넣으면 기대한 title · fields 로 매핑.
- **`test_dag_import`** — 콜백 부착 후에도 DAG import 가 정상.

## 범위 밖 (명시)

- `on_retry_callback` · `on_success_callback` (retries 선행 필요 · success 노이즈) .
- 이상 이력 DB 저장 · 수집 현황 모니터링 뷰 · dbt 마트 (SLO-7 별도 트랙) .
- 신선도 · 증분 워터마크 (SLO-5) · 병렬화 실측 (SLO-1) .
- 동일 시각 (HOUR) 계절성 보정 (오탐 실측 후 판단) .

## 참조

- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` (Tier 3 · SLO-6) .
- 기존 함수: `src/bullet_in/quality.py` (`volume_anomaly`) · `tests/test_quality.py` .
- 연결 지점: `src/bullet_in/run.py` (pipeline_runs INSERT) · `airflow/dags/bullet_in_daily.py` .
