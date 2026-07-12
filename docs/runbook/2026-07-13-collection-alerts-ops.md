# 수집 이상 알림 운영 (2026-07-13)

## 목적

파이프라인이 깨졌을 때 Discord 로 통지하는 SLO-6 알림 (PR #34) 의 설정 · 해석 · 튜닝 · 롤백을 정리.

- 두 알림 경로 — 하드 실패 (파이프라인 예외 crash → Airflow `on_failure_callback`) · 소프트 드리프트 (실행은 성공했으나 한 소스가 조용히 0건 = 셀렉터 드리프트 → 소스별 수집량 이상탐지) .
- 공유 배관 — `src/bullet_in/notify.py` 의 `send_alert` 가 Discord embed 를 발송.

## Discord webhook 설정

알림은 `DISCORD_WEBHOOK_URL` 환경변수 하나로 켜고 끈다.

- **webhook URL 발급** — Discord 서버 → 서버 설정 → 연동 (Integrations) → 웹후크 → 새 웹후크 → 채널 선택 → 웹후크 URL 복사.
- **주입** — 이 프로젝트는 dotenv 미사용이므로 셸 export 로 넣는다.
  `.env` 에 `DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...` 를 추가하고 `set -a; source .env; set +a` 후 실행.
- **Airflow 환경** — DAG 워커 프로세스에도 같은 변수가 보여야 한다 (컨테이너 env · Airflow Variable → env 매핑 등 배포 방식에 맞춤) .
- **미설정 동작** — 변수가 없으면 발송하지 않고 `WARNING` 으로 제목 · 설명을 로깅한다 (폴백) .
  dev · CI 는 이 폴백으로 도므로 webhook 없이도 테스트가 깨지지 않는다.

## 알림 해석

두 종류의 embed 가 온다.

- **⚠️ 수집량 이상 (주황)** — 소프트 드리프트.
  실행은 성공했으나 소스별 수집량이 지난 이력 대비 2σ 밖.
  `▼` 는 드롭 (평소보다 급감, 셀렉터 드리프트 의심) · `▲` 는 스파이크 (급증, 중복 유입 · 페이지 구조 변화 의심) .
  라인 예: `▼ fmkorea: 0건 (평소 ~14)`.
- **❌ 파이프라인 실패 (빨강)** — 하드 실패.
  `run_pipeline` 태스크가 예외로 중단.
  fields 의 `로그` 링크 · `Try` · `Host` 로 Airflow 태스크를 특정하고, description 의 예외 요약 (최대 400자) 으로 원인을 좁힌다.

## 대응

- **▼ 드롭 알림** — 해당 소스를 라이브 재검증한다.
  대개 셀렉터 · feed_url 드리프트다 (`config/sources.yaml`) .
  어댑터 단독 `fetch()` 로 확인 (단위 테스트는 모킹이라 못 잡음) — `docs/troubleshooting/2026-06-12-live-source-selector-drift.md` 참조.
- **▲ 스파이크 알림** — 원문 중복 · 페이지 구조 변화 여부를 확인. 대개 무해하나 dedup · 파싱 회귀 신호일 수 있다.
- **❌ 실패 알림** — `로그` 링크로 스택트레이스 확인.
  흔한 원인 = Mongo · MariaDB 연결 실패 · Gemini 인증 · 미처리 예외.

## 튜닝 노브

임계값은 경험적이며 코드 상수로만 조정한다 (`src/bullet_in/quality.py` · `src/bullet_in/run.py`) .

- **`min_baseline` (기본 3.0)** — history 평균이 이 미만인 저volume 소스는 평가에서 제외 (오탐 억제) .
  뜸한 소스에서 오탐이 잦으면 올린다.
- **`sigma` (기본 2.0)** — 이상 판정 밴드 폭.
  오탐이 많으면 올리고 (둔감) , 미탐이면 내린다 (민감) .
- **history 윈도우 (기본 12 회, run.py 의 `LIMIT 12`)** — 이상 판정에 쓰는 과거 회차 수 (약 3 일) .
  파이프라인은 6 시간마다 4 회/일 도므로 12 회 ≈ 3 일 평균.
- **시간대 계절성 주의** — 12 회 윈도우는 하루 4 슬롯을 뭉갠 평균이라, 밤 시간대에 뜸한 소스가 소폭 오탐할 수 있다.
  주 신호 ("평소 >0 인데 0") 는 시간대와 무관하게 강건하므로 현재는 단순 윈도우를 쓴다.
  오탐이 실제로 관찰되면 동일 시각 (HOUR) 비교로 개선한다 (2 주 이상 이력 필요) .

## 검증

webhook 없이도 발송 로직을 확인할 수 있다.

```bash
uv run pytest tests/test_notify.py -v          # 발송 · 폴백 · 예외 삼킴 · 포맷 빌더
uv run pytest tests/test_quality.py -v          # 소스별 이상탐지 (volume_anomalies)
```

DAG 콜백 배선은 airflow 미설치 환경에서 다음으로 구조 검증한다 (`test_dag_import` 는 skip) .

```bash
uv run python -m py_compile airflow/dags/bullet_in_daily.py         # DAG 구문
uv run python -c "from bullet_in import notify; assert callable(notify.build_failure_alert)"   # 앱 계약
```

- **참고** — 로컬 `airflow/` 디렉터리가 pip `airflow` 패키지명을 가려, airflow 미설치 시 `test_dag_import` 는 `importorskip("airflow.models")` 로 skip 된다.
  전체 DAG 로드 검증은 airflow 가 설치된 환경 (Docker `apache/airflow:3.0.0`) 에서 DagBag 으로 확인.

## 실패 모드

- **webhook 오설정 · 만료** — `send_alert` 가 모든 예외를 삼켜 파이프라인을 죽이지 않는다 (미설정과 동일하게 WARNING 만) .
  좁은 except 로 인한 파이프라인 crash 함정은 `docs/troubleshooting/2026-07-13-alert-exception-swallow-gap.md` 참조.
- **알림 폭주** — 여러 소스가 동시에 드리프트하면 한 회차에 여러 라인이 한 embed 로 묶여 온다 (소스당 별도 메시지 아님) .
- **초기 데이터 부족** — 파이프라인 초기엔 소스별 history 가 2 회 미만이라 이상탐지가 무발화한다 (안전한 무알림) .

## 롤백

- 알림 기능은 신규 테이블 · 컬럼 · 마이그레이션이 없다 (기존 `pipeline_runs.source_counts` 읽기만) .
- `git revert` 로 롤백 가능하며 데이터 영향이 없다.
- 임시로 끄려면 `DISCORD_WEBHOOK_URL` 을 해제한다 (코드 변경 없이 WARNING 폴백으로 전환) .

## 참고

- PR #34 · spec/plan `docs/superpowers/{specs,plans}/2026-07-13-slo6-collection-alerts*`.
- 함정: `docs/troubleshooting/2026-07-13-alert-exception-swallow-gap.md`.
- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` (Tier 3 · SLO-6) .
