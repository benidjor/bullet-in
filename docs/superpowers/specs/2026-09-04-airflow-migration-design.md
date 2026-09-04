# 회차를 systemd 타이머에서 Airflow 로 옮기는 설계 (2026-09-04)

3시간 회차는 지금 systemd 유닛 하나가 통째로 든다.
수집 · 번역 · 렌더 · 게이트가 한 프로세스이고, 어느 단계가 죽었는지는 `journalctl` 을 grep 해야 보이며, 다시 돌리려면 회차 전체를 다시 돈다.
이 설계는 그 회차를 Airflow DAG 하나로 옮기되, systemd 가 지금 주는 성질 셋 (밀린 회차 보정 · 유닛 실패 알림 · 회차 시작과 끝의 배포 훅) 을 잃지 않는 것을 목표로 한다.

안건 `2ε` 의 설계다.
구현 계획은 별도 문서로 쓴다.

## 1. 지금 상태와 실측 (2026-09-04 02시대 KST)

### 1.1. 스케줄은 systemd 타이머 다섯이다

| 유닛 | 주기 | 하는 일 |
| --- | --- | --- |
| `bullet-in` | 3시간 (하루 8회) | 회차 전체 · 앞뒤에 배포 자동화 |
| `bullet-in-watchlist` | 하루 4회 | 링크 선수 회전 검색 |
| `bullet-in-warehouse` | 회차 20분 뒤 | 마트 변경 이력을 Iceberg 로 적재 |
| `bullet-in-backup` | 매일 | 논리 덤프를 GCS 로 |
| `bullet-in-warehouse-maint` | 매일 | 컴팩션 · 스냅샷 만료 · 고아 청소 |

다섯 전부 `Persistent=true` 와 `OnFailure=bullet-in-fail-notify@%n.service` 가 걸려 있다.
회차 유닛은 여기에 배포 자동화 (스펙 2026-09-03 · 안건 2β) 를 훅 셋으로 든다.

```
ExecStartPre   deploy advance        (origin/main 을 내려받는다)
ExecStart      python -m bullet_in.run
ExecStartPost  infra/deploy-site.sh  (wrangler pages deploy)
ExecStopPost   deploy judge          ($SERVICE_RESULT · $EXIT_STATUS 로 판정 · 롤백)
```

### 1.2. 회차 본체는 함수 하나이고 멱등은 절반이다

`run.py` 의 `main` 은 588줄 함수 하나다.
번역 · 분류 · 말투 백필은 DB 에 「무엇이 남았나」 를 다시 묻는다 (`rows_missing_translation` · `rows_missing_stage` · 검출 기반 재선별).
그래서 그 셋은 어디서 끊겨도 다음 실행이 이어받는다.

수집 단계의 값 여덟은 그렇지 않다.
원본 목록 · 후보 계수 · 수집 소요 · 시작 시각 · 어댑터 퍼널 · 오류 목록 · 적재 통계 · 신규 건수가 메모리로 끝까지 흘러, 회차 끝의 SLO-6 이상탐지 · 신선도 알림 · 운영 화면 · 회차 행 (`pipeline_runs`) 기록에 쓰인다.
잔여 안건 표의 「이미 멱등이고 단계 재개가 된다」 는 이 여덟을 빼고 한 말이다.

회차 행에는 `dag_run_id` 열이 이미 있고 코드가 `AIRFLOW_CTX_DAG_RUN_ID` 환경변수를 읽어 채운다.
5월의 Airflow 시절 흔적이라 태스크와 회차 행을 잇는 자리가 이미 있다.

### 1.3. VM 실측

| 항목 | 값 |
| --- | --- |
| 기기 | Oracle 무료 A1 arm64 · 4 vCPU · 23Gi · 다른 프로젝트 (seoulnow) 와 동거 |
| 메모리 | used 11Gi · available 11Gi |
| 큰 상주 프로세스 | seoulnow Flink 잡 둘 3.4G · 3.0G · Kafka 1.0G · MinIO 1.8G · Postgres 2.0G |
| bullet-in 몫 | MariaDB 0.2G · Mongo 0.4G |
| 디스크 | 48G 중 22G 여유 |
| 부하 | load 0.4 에서 0.9 · 가동 105일 |
| Airflow | 없음 (`which airflow` 빈 결과 · `~/airflow` 없음) |
| 파이썬 | 시스템 3.12.3 · 프로젝트는 uv 가 3.11 로 고정 |

2026-07-20 설계가 Airflow standalone 을 뺀 근거는 「하루 4회 회차를 위해 상시 약 1GB 를 지불한다」 였다.
그때의 여유와 지금의 11Gi 는 다른 값이고 그 근거는 더 이상 성립하지 않는다.
돈은 0원 그대로다.
VM 이 무료 티어이고 Cloudflare Pages · 제미나이 호출은 이 설계로 늘지 않는다 (번역은 `title_ko IS NULL` 행만 보내므로 단계를 쪼개도 호출 수가 같다).

### 1.4. 실패는 드물고 짧다

저널이 남아 있는 2026-08-31 이후 나흘 반 동안 회차 실패는 3회다.
그중 2회가 dbt 세그폴트 (안건 2ν · 종료 코드 -11 · 비결정적) 이고 1회는 게이트 위반이다.
회차 한 번의 CPU 소요는 3분 30초 안팎이다.
「실패한 단계만 다시 돌린다」 가 아끼는 것은 회당 몇 분이고, 429 는 이미 번역만 멈추고 다음 회차가 잇는다.

서비스 통증만으로는 이 전환을 정당화할 수 없다.
그것을 알고 하는 전환이다 (§2.2).

### 1.5. Airflow 3 문서에서 확인한 것

- `airflow standalone` 은 SQLite 를 쓰고 문서가 「운영 부적합」 이라고 못박는다.
  운영은 구성 요소를 따로 띄우고 메타데이터 DB 를 따로 둔다.
- 운영 지원 DB 는 PostgreSQL 13 에서 17 과 MySQL 8.0 뿐이다.
  MariaDB 는 지원 목록에 없고, 스케줄러 문서에 「10.6 미만은 안 된다」 한 줄만 있다.
  지금 마트의 MariaDB 11 은 「막지는 않지만 시험되지 않은 조합」 이다.
- DAG 번들의 버전 고정은 git 번들에서만 되고, 로컬 디스크 번들은 「도는 중 파일이 바뀌면 불일치가 날 수 있다」 고 적혀 있다.
- `catchup=False` 는 「활성화 시점에 가장 최근 구간 하나만 실행」 이다.
  systemd `Persistent=true` 와 같은 성질이다.
- Airflow 3 은 태스크에서 메타데이터 DB 를 직접 읽지 않고 태스크 컨텍스트 메서드를 쓰라고 한다.
  CLI `airflow tasks states-for-dag-run … -o json` 은 있다.

## 2. 목표와 잣대

### 2.1. 목표

회차가 Airflow DAG 로 돌고, 어느 단계가 죽었는지가 화면에 보이며, 세그폴트는 같은 회차 안에서 한 번 더 시도되고, 배포 자동화 (전진 · 판정 · 롤백) 와 밀린 회차 보정과 실패 알림이 지금과 같은 결과를 낸다.

Airflow 가 새로 주는 것은 셋이다.

- 재시도가 코드가 아니라 설정이고, 그 이력이 남는다.
- 어느 단계가 죽었는지를 grep 없이 본다.
- 웨어하우스 적재가 「회차 20분 뒤」 라는 시계 어긋내기 대신 의존으로 붙는다.

### 2.2. 잣대 셋과 결론

잣대는 서비스 통증 · 포트폴리오의 끝맺음 · 면접 방어다 (메모리 `portfolio-goal-junior-data-engineer` · `measure-completion-not-stack-names`).

- 서비스 통증은 §1.4 대로 거의 없다.
- 포트폴리오에 Airflow 는 이미 둘 있다 (15분 주기 DAG · Variable 증분).
  둘 다 「스케줄러로 썼다」 이고, 태스크 단위 재시도 설계 · 실패 콜백 · 배포와 롤백을 DAG 안에 넣은 것 · 오케스트레이터 자체의 생존은 없다.
  세 번째 사용은 값어치가 없고, 값어치는 「systemd 의 성질을 보전하며 옮긴 설계」 에서만 나온다.
- 세 축 (경쟁력 · 완성도 · 위기 대처) 중 전환이 확실히 이기는 것은 위기 대처 서술 하나이고, 완성도는 첫 몇 주 마이너스다.

사용자가 2026-09-04 새벽에 이 대조를 보고 「전환」 을 골랐다.
기각한 안 둘은 다음이다.

- **얇은 전환** (DAG 태스크 하나가 `systemctl start` 로 회차 유닛을 부르고 기다린다)
  — 화면과 실행 이력만 얻고 위 이야기를 하나도 못 만든다.
- **폐기** (`airflow/` 를 지우고 비교만 문서로 남긴다)
  — 정직하지만 2026-09-01 재평가 (「보류가 아니라 뒤 순위」) 를 뒤집는다.

## 3. 결정

### 3.1. 범위 — 회차와 웨어하우스 적재

옮기는 것은 회차와 웨어하우스 적재 둘이다.
워치리스트 · 백업 · 유지보수는 systemd 에 남는다.
그 셋은 단계가 하나라 쪼갤 것이 없고 재시도 · 관측의 이득이 0 이다.
백업은 「Airflow 가 죽어도 돌아야 하는 것」 이라 오케스트레이터 밖에 두는 것이 설계상 맞다.

적재를 함께 옮기는 이유는 이것이 Airflow 가 주는 실제 변경 중 가장 뚜렷하기 때문이다.
지금은 「회차 20분 뒤」 로 순서를 보장하는데, 회차가 늦어지면 적재가 앞서 돈다.
DAG 뒤에 의존으로 붙이면 그 창이 사라진다.

기각한 안은 「회차 하나만」 (스케줄러가 둘로 남고 얻는 변경이 없다) 과 「다섯 전부」 (옮기는 손만 들고 백업이 오케스트레이터에 묶인다) 다.

### 3.2. 태스크 — 파이프라인 넷과 오케스트레이션 넷

자르는 잣대는 둘이다.
다시 돌릴 때 값어치가 달라지는 자리와, 값이 메모리로 건너가지 않는 자리다.
이 둘이 같은 곳에서 갈리는 지점이 회차 본체에 셋 있어서 파이프라인 태스크가 넷이 된다.

| 태스크 | 하는 일 | 재실행하면 | 재시도 |
| --- | --- | --- | --- |
| `collect` | 수집 · 후보 계수 · 절벽 · 커버리지 · 채택 누락 알림 · 원본 저장 · 마트 upsert · 회차 행 삽입 | 소스에 다시 닿는다 | 0 (어댑터가 자체 재시도 · 소스 접촉이 비용) |
| `enrich` | 번역 · 재작성 게이트 · 선수 추출 · 명단 · 구단 관측 · 분류 · 말투 백필 | DB 가 남은 행을 다시 주므로 멱등 | 0 (429 는 다음 회차 · 지금 정책) |
| `publish` | 서빙 행 조회 · 사이트 렌더 · SLO-6 · 신선도 · 회차 행 갱신 · 운영 화면 · 행동 화면 · 표지 | 파일 재생성뿐 | 1 |
| `gate` | dbt build · 급사는 종료 코드 3 | 세그폴트가 비결정적이라 한 번 더가 실제로 회차를 살린다 | Airflow 는 0 · 급사만 단계 안에서 1 (§6.2) |

enrich 안의 번역 · 분류 · 말투는 셋 다 「DB 에 남은 행을 묻고 제미나이를 부른다」 는 같은 종류라 사이를 갈라도 재시도 정책이 안 달라지고 값도 안 건너간다.
기각한 안은 「여섯 + 넷 = 열」 (화면에서 세 단계가 따로 보이지만 다시 돌릴 일이 없고 클라이언트 초기화만 셋으로 는다) 과 「둘 + 넷 = 여섯」 (게이트 재시도가 렌더까지 되돌리고 단계별 재시도라는 명분이 거의 사라진다) 이다.

오케스트레이션 태스크 넷은 앞 결정이 정한 것이다.
`advance` · `judge` 는 2β 가 그대로 옮겨 오고, `deploy_site` 는 이미 별도 스크립트이며, `warehouse_load` 는 §3.1 이 붙였다.

### 3.3. 메타데이터 DB — Postgres 컨테이너

`docker-compose.yml` 에 `airflow-db` (Postgres 16) 서비스 하나와 볼륨 하나를 더한다.
지원 조합이고, 마트 장애가 스케줄러까지 번지지 않으며, 유휴 메모리는 약 50MB 다.
백업 유닛에 `pg_dump` 한 줄이 붙는다.

기각한 안은 기존 MariaDB 11 에 DB 를 더하는 것 (미지원 조합 · dbt 게이트가 두드리는 인스턴스에 오케스트레이터 상태가 함께 산다) 과 동거 프로젝트의 Postgres 를 빌리는 것 (다른 프로젝트 수명에 묶인다) 이다.
마트 저장소를 Postgres 로 옮기자는 결정이 아니다.
마트는 MariaDB 그대로다 (메모리 `mariadb-stays-postgres-was-never-needed`).

### 3.4. 태스크는 전부 셸 호출

태스크는 `BashOperator` 로 `uv run python -m bullet_in.run --stage <이름> --run-id {{ run_id }}` 를 부른다.
DAG 파일은 파싱 시 `bullet_in` 을 import 하지 않는다.

이 결정이 세 문제를 한 번에 푼다.

- Airflow 의존과 프로젝트 의존 (pydantic v2 · httpx · Playwright) 이 안 섞인다.
  5월 런북이 이미 이 격리를 요구하고 있다.
- 각 태스크가 새 프로세스라 `advance` 뒤의 코드를 자연히 본다.
  지금 `ExecStartPre` 뒤에 `ExecStart` 가 도는 것과 같은 순서다.
- 단계 함수가 Airflow 없이도 같은 명령으로 돈다.
  로컬 · 테스트 · systemd 되돌림이 전부 이 진입점 하나를 쓴다.

### 3.5. systemd 에 남는 것과 새로 생기는 것

- 워치리스트 · 백업 · 유지보수 유닛 셋은 그대로다.
- 회차 · 웨어하우스 타이머 둘은 비활성으로 두되 유닛 파일은 남긴다.
  Airflow 를 세워야 할 때 되돌리는 길이다 (§8).
- Airflow 구성 요소 셋을 systemd 유닛으로 띄운다.
  systemd 가 사라지는 것이 아니라 한 층 위로 올라간다.
- 새 타이머 하나 `bullet-in-airflow-watch` 가 오케스트레이터 생존을 본다 (§4.4).
  지금 `OnFailure` 가 덮던 「유닛 자체가 죽은 경우」 를 이것이 잇는다.

## 4. 구성

### 4.1. Airflow 설치

| 항목 | 값 |
| --- | --- |
| 위치 | `/home/ubuntu/airflow-venv` (uv venv · Python 3.11 · 공식 constraints 파일) |
| `AIRFLOW_HOME` | `/home/ubuntu/airflow` |
| DAG 폴더 | `/home/ubuntu/bullet-in/airflow/dags` (저장소 체크아웃 그대로) |
| 실행기 | `LocalExecutor` · `parallelism=2` · `max_active_tasks_per_dag=2` |
| 메타데이터 DB | `postgresql+psycopg2://…@127.0.0.1:5433/airflow` (컨테이너 `airflow-db`) |
| 화면 | api-server 를 `127.0.0.1:8080` 에만 묶는다 · SSH 터널로 본다 · 밖으로 열지 않는다 |
| 설정 파일 | `infra/airflow/airflow.cfg` 에 위 값을 두고 설치 스크립트가 `AIRFLOW_HOME` 으로 복사한다 |

버전은 계획서가 설치 시점의 최신 3.x 를 고정한다.
`airflow/requirements.txt` 의 `apache-airflow==3.0.0` 은 그때 같이 올린다.

### 4.2. 유닛 넷

| 유닛 | 종류 | 내용 |
| --- | --- | --- |
| `airflow-api-server.service` | 상주 | `airflow api-server --port 8080` · `Restart=on-failure` · `After=docker.service network-online.target` |
| `airflow-scheduler.service` | 상주 | `airflow scheduler` · 같은 재시작 규칙 · `LimitCORE=infinity` (게이트 세그폴트 코어 덤프가 이 프로세스의 자식에서 난다) |
| `airflow-dag-processor.service` | 상주 | `airflow dag-processor` · 같은 재시작 규칙 |
| `bullet-in-airflow-watch.timer` · `.service` | 매시 | §4.4 의 감시 스크립트 · `OnFailure` 는 기존 템플릿 유닛 |

셋 다 `EnvironmentFile=/home/ubuntu/airflow/airflow.env` 로 `AIRFLOW_HOME` 과 DB 주소를 받는다.
프로젝트의 `.env` 는 Airflow 프로세스에 주지 않는다.
태스크 셸이 직접 읽는다 (§4.3).
`install-units.sh` 는 이 넷을 함께 설치하고 회차 · 웨어하우스 타이머의 활성화 줄을 뺀다.

### 4.3. DAG `bullet_in_cycle`

```
advance → collect → enrich → publish → gate → deploy_site → judge
                                   └──────────────────────→ warehouse_load
```

| 매개변수 | 값 | 지금의 대응 |
| --- | --- | --- |
| `schedule` | `0 */3 * * *` (UTC) | `OnCalendar=*-*-* 00/3:00:00 UTC` |
| `catchup` | `False` | `Persistent=true` (최근 구간 한 번) |
| `max_active_runs` | 1 | 이중 실행 금지 |
| `dagrun_timeout` | 30분 | `TimeoutStartSec=1800` |
| `default_args.on_failure_callback` | `notify.build_failure_alert` | `OnFailure` |

| 태스크 | 명령 | 재시도 | 규칙 |
| --- | --- | --- | --- |
| `advance` | `deploy advance` | 0 | 실패해도 뒤가 돈다 (지금 `ExecStartPre=-` 와 같다 · 셸이 종료 코드를 0 으로 바꾼다) |
| `collect` | `run --stage collect` | 0 | |
| `enrich` | `run --stage enrich` | 0 | |
| `publish` | `run --stage publish` | 1 | |
| `gate` | `run --stage gate` | 0 | `skip_on_exit_code=3` (§6.2) |
| `deploy_site` | `infra/deploy-site.sh` | 1 | 기본 (`all_success`) |
| `judge` | `deploy judge --from-airflow` | 0 | `all_done` |
| `warehouse_load` | `env GOOGLE_APPLICATION_CREDENTIALS=… warehouse load` | 0 | `publish` 뒤 · `all_done` |

셸 명령의 앞부분은 전부 같다.

```
cd /home/ubuntu/bullet-in && set -a && . ./.env && set +a && /home/ubuntu/.local/bin/uv run …
```

`warehouse_load` 만 지금 유닛의 `env GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json` 감싸기를 그대로 옮긴다.
`.env` 의 자격이 백업 계정이라 적재 전용 계정으로 덮어야 하는 사정은 유닛 주석 그대로다.

`warehouse_load` 가 `all_done` 인 이유는 지금 타이머가 회차 결과와 무관하게 도는 것과 같은 성질을 지키기 위해서다.
게이트가 막은 회차도 마트에는 이번 회차 행이 들어가 있고, 변경 이력은 그것을 적재해야 한다.

DAG 파일에 남는 파이썬은 오퍼레이터 선언과 콜백 배선뿐이다.
`from bullet_in import notify` 는 콜백 함수 안에서 지연 import 한다.

### 4.4. 생존 감시

`infra/airflow/watch.py` 가 매시 두 축을 잰다.

- 스케줄러 심박 — `airflow jobs check --job-type SchedulerJob` 의 종료 코드.
- 마지막 성공 — `bullet_in_cycle` 의 가장 최근 성공 실행이 4시간 안인가 (REST API 또는 CLI · 계획서가 하나를 고른다).

두 축인 이유가 있다.
스케줄러가 살아 있어도 DAG 가 일시정지됐거나 파싱이 깨지면 회차가 조용히 안 돈다.
심박만 보면 그 경우를 못 잡고, 마지막 성공만 보면 원인이 안 갈린다.

어느 축이든 깨지면 사고 채널로 한 장 보낸다.
같은 상태가 이어지는 동안은 4시간마다 한 번만 다시 보낸다 (신선도 알림의 재알림 규칙과 같은 방식).

## 5. 회차 본체의 단계 분리

### 5.1. 단계 함수 넷

`run.py` 의 `main` 을 네 함수로 가른다.
경계는 §3.2 표의 행이다.

| 함수 | 시작 | 끝 |
| --- | --- | --- |
| `collect(run_id)` | 설정 · 어댑터 · 수집 | `mart.upsert` · 회차 행 삽입 |
| `enrich(run_id)` | 제미나이 클라이언트 · 사전 · 명단 | 말투 백필 |
| `publish(run_id)` | 서빙 행 조회 | 표지 (`build.json`) |
| `gate(run_id)` | dbt build | `enforce_gate` |

`main(concurrency)` 은 `run_id` 하나를 만들어 넷을 차례로 부르는 껍데기로 남는다.
각 단계는 자기 재료 (엔진 · 마트 · 선수 저장소 · 어댑터 인정 집합 · 사전 · 명단) 를 스스로 만든다.
지금도 그렇게 만들고 있으므로 새로 생기는 조회는 없고, 단계마다 한 번씩 만드는 비용만 는다.

### 5.2. CLI

```
python -m bullet_in.run                         # 지금과 같다 · 넷을 차례로
python -m bullet_in.run --stage collect --run-id <값>
python -m bullet_in.run --stage enrich  --run-id <값>
python -m bullet_in.run --stage publish --run-id <값>
python -m bullet_in.run --stage gate    --run-id <값>
```

`--run-id` 는 `--stage` 와 함께만 받는다.
DAG 는 Airflow 의 `run_id` 를 넘기고, 회차 행의 `dag_run_id` 열에는 지금처럼 `AIRFLOW_CTX_DAG_RUN_ID` 가 들어간다.
`run_id` 열은 `--run-id` 값을 그대로 쓴다.

### 5.3. 회차 행의 두 단계 기록

수집 값 여덟이 단계 사이를 건너는 길은 회차 행이다.

- `collect` 가 끝날 때 회차 행을 삽입한다.
  지금 채우는 열 (시작 시각 · 수집 소요 · 소스별 건수 · 후보 계수 · 신규 · 중복 · 차단 · 오류 수 · 성공률) 에 JSON 열 `fetch_detail` 을 더해 오류 목록과 어댑터 퍼널을 담는다.
  `finished_at` · `duration_sec` 은 비워 둔다.
- `publish` 가 `run_id` 로 그 행을 읽어 SLO-6 · 신선도 알림 · 운영 화면에 쓰고, 끝에서 `finished_at` · `duration_sec` 을 갱신한다.

따라 고치는 것 넷이다 (원안은 둘이었고 나머지 둘은 PR #461 리뷰가 잡았다 · `docs/troubleshooting/2026-09-04-a-row-written-twice-and-the-readers-nobody-counted.md`).

- 절벽 판정은 지금처럼 행 삽입 앞에 두지만, 삽입이 upsert 라 재실행이 자기 행을 직전 회차로 읽지 않도록 자기 `run_id` 를 제외한다.
- SLO-6 의 이력 조회 (`ORDER BY started_at DESC LIMIT 12`) 는 이번 행이 이미 들어가 있으므로 자기 `run_id` 를 제외하는 조건 한 줄을 더한다.
- 운영 화면 집계 (`ops_snapshot`) 는 `finished_at IS NOT NULL` 인 행만 읽는다.
  중간에 죽은 회차가 남긴 미완 행을 렌더가 합산하면 `TypeError` 로 화면이 멈춘다.
- 웨어하우스 적재 (`load_ops`) 의 `pipeline_runs` 워터마크는 `started_at` 이 아니라 `finished_at` 이다.
  적재 타이머가 회차 도중에 들어와도 미완 행을 복사하지 않는다.

회차 행 삽입은 `INSERT … ON DUPLICATE KEY UPDATE` 다.
원본 저장과 마트 upsert 는 이미 멱등이라 같은 `run_id` 로 `collect` 를 다시 돌려도 이 한 줄이 마지막 문장에서 죽지 않는다.

XCom 을 쓰지 않는 이유는 §3.4 의 세 번째 항목이다.
값이 회차 행에 있으면 단계 함수가 Airflow 없이도 같은 길로 값을 받는다.

## 6. 배포 자동화의 이식

### 6.1. 전진

`advance` 는 안 바뀐다.
첫 태스크가 같은 명령을 부르고, 셸이 종료 코드를 0 으로 바꿔 전진 실패가 회차를 잃지 않게 한다 (스펙 2026-09-03 §5 의 첫 원칙).
사전 점검 · 차단 목록 · 상태 파일 전부 그대로다.

### 6.2. 게이트 급사는 「건너뜀」 이다

게이트는 지금처럼 급사 (dbt 가 신호로 죽음) 에 종료 코드 `3` 을 낸다.
`gate` 태스크에 `skip_on_exit_code=3` 을 주면 급사가 「실패」 가 아니라 「건너뜀」 으로 찍힌다.
뒤의 `deploy_site` 는 기본 규칙 (`all_success`) 에 따라 함께 건너뛴다.
지금 systemd 에서 `ExecStart` 실패가 `ExecStartPost` 를 막는 것과 같은 결과가 규칙 하나로 난다.

급사의 재시도는 Airflow 가 아니라 게이트 단계 안에서 한다.
건너뜀은 Airflow 가 재시도하지 않고, 반대로 `retries=1` 을 주면 위반 (`1`) 이 실패라서 헛되이 한 번 더 돈다.
원하는 것과 정반대라 `gate` 태스크의 Airflow 재시도는 0 이다.
대신 `run_gate` 가 dbt 를 돌린 뒤 신호 종료 (`returncode < 0`) 일 때만 한 번 더 돌리고, 두 번째도 신호 종료면 그때 `3` 을 낸다.
위반은 첫 시도에서 `1` 로 끝난다.
systemd 로 되돌린 상태에서도 같은 재시도가 살아 있다는 것이 이 자리의 덤이다.

Airflow 의 상태 어휘 (성공 · 실패 · 건너뜀) 가 스펙 2026-09-03 §8 의 세 갈래 (통과 · 위반 · 급사) 와 하나씩 맞는다.
판정기가 저널을 읽거나 파일을 뒤질 필요가 없다.

### 6.3. 판정의 입력 대응

`judge` 는 마지막 태스크이고 `all_done` 이다.
입력이 「유닛 결과 · 종료 코드」 에서 「앞 태스크 일곱의 상태」 로 바뀐다.
`deploy.py` 에 `--from-airflow` 를 더하고, 그 안에서 상태를 지금 `decide` 의 두 값으로 옮긴다.

| 앞 태스크 상태 | `service_result` | `exit_status` | 판정 |
| --- | --- | --- | --- |
| `advance` 부터 `deploy_site` 까지 전부 성공 | `success` | | 표지 대조 · 반영 완료 |
| `gate` 건너뜀 (그래서 `deploy_site` 도 건너뜀) | `exit-code` | `3` | 보류 |
| 그 밖에 하나라도 실패 | `exit-code` | 실패한 태스크 이름 | 롤백 |
| `dagrun_timeout` (30분) 초과 | (판정 자체가 안 돈다) | | 판정 없음 |

시간 초과는 판정기의 입력이 아니라 판정기가 못 도는 경우다.
`judge` 를 포함한 미완 태스크가 전부 `SKIPPED` 로 바뀌고 `judge` 자신도 돌지 못하므로 DAG 수준 `on_failure_callback` (§7) 이 알림만 보낸다.
전진 여부에 따라 `pending` 이 참인 채로 다음 회차로 넘어가고, 다음 회차의 `judge` 가 그 `pending` 을 이어 판정한다.
회차 결과와 무관하게 도는 것이라 판정 재료가 아니다.
`decide` · `rollback` · 표지 대조 · 알림 서식은 한 줄도 안 바뀐다.
2β 가 남긴 판정 테스트가 그대로 살고, 새로 검증할 것은 이 대응표 하나다.

상태를 읽는 방법은 §9.1 의 미검증 항목이다.
`ti.get_task_states` 가 있으면 그것을, 없으면 CLI `airflow tasks states-for-dag-run <dag> <run_id> -o json` 을 판정 셸이 먼저 부르고 그 JSON 을 `--from-airflow` 에 넘긴다.

### 6.4. 롤백과 DAG 파일

롤백은 저장소를 직전 커밋으로 되돌리므로 DAG 파일도 되돌린다.
DAG 파일이 얇아서 (§4.3) 실질은 작지만, dag-processor 가 다음 파싱에서 그것을 읽는다.
Airflow 3 은 실행마다 DAG 버전을 고정하므로 도는 중인 실행은 안 깨져야 하고, 이것을 §9.4 의 리허설 항목으로 확인한다.

DAG 구조를 바꾸는 PR 은 회차 사이에 머지한다는 규율을 런북에 적는다.

## 7. 실패 처리와 알림

- 태스크 실패 알림은 태스크 단위 콜백으로 지금의 `notify.build_failure_alert` 를 쓴다.
  제목의 `run_pipeline` 고정 문구를 태스크 이름으로 바꾼다.
- 재시도 중인 실패는 알리지 않는다.
  Airflow 는 재시도가 남아 있으면 실패 콜백을 안 부르고 소진됐을 때만 부른다.
  systemd 가 회차당 한 장 내던 것과 같은 빈도다.
- 429 정책은 그대로다.
  `enrich` 는 재시도 0 이고 남은 행은 다음 회차가 집는다.
- 세그폴트는 게이트 단계 안의 재시도 1회로 같은 회차 안에서 한 번 더 시도하고, 두 번째도 죽으면 건너뜀 → 배포 없음 → 판정 보류다 (§6.2).
  코어 덤프는 §4.2 의 `LimitCORE` 가 받는다.
- 오케스트레이터 자체의 고장은 §4.4 가 본다.
- 배포 자동화의 알림 여섯 (반영 완료 · 보류 · 롤백 · 표지 불일치 · 전진 실패 · 판정기 예외) 은 서식이 안 바뀐다.
  2β 런북의 대응 명령만 `systemctl start` 에서 DAG 트리거로 바뀐다 (§11).

## 8. 전환 절차 (이중 실행 금지)

1. 설치만 한다.
   venv · Postgres 컨테이너 · 유닛 넷 · DAG 를 올리되 DAG 는 일시정지 상태로 둔다.
   systemd 타이머는 그대로 돈다.
2. 리허설을 systemd 회차 직후에 손으로 한 번 돌린다.
   그 시점에는 남은 번역 행이 거의 없어 제미나이 호출이 몇 건뿐이다.
   산출물 (회차 행 · 사이트 · 표지 · 반영 알림) 이 직전 systemd 회차와 같은 모양인지 대조한다.
   같은 값일 필요는 없다.
   새 기사 몇 건이 그 사이 들어올 수 있다.
3. 리허설이 통과하면 타이머 둘을 먼저 끄고 DAG 를 활성화한다.
   순서가 반대면 한 구간에 회차가 두 번 돈다.
4. 첫 사흘은 회차마다 회차 행 · 반영 알림 · 화면의 태스크 이력을 대조한다.
5. 되돌릴 일이 생기면 DAG 일시정지 → 타이머 둘 활성화, 두 명령이다.
   유닛 파일을 남기는 이유가 이것이다.

## 9. 검증

### 9.1. 착수 전 실물 검증 넷

계획서의 첫 태스크다.
하나라도 어긋나면 설계로 돌아온다.

- Airflow 3 이 VM (arm64 · Python 3.11 · uv) 에 constraints 로 설치되는가, 상주 메모리 실측이 얼마인가.
- `BashOperator` 의 `skip_on_exit_code` 가 3.x 표준 프로바이더에 있는가.
  없으면 게이트 셸에서 `3` 을 기본 건너뜀 코드 (`99`) 로 바꿔 내는 것으로 대신한다.
- 판정 태스크가 같은 실행의 앞 태스크 상태를 읽는 컨텍스트 메서드 (`ti.get_task_states`) 가 있는가.
  없으면 CLI 로 대신한다 (§6.3).
- 실패 콜백 컨텍스트에 `build_failure_alert` 가 쓰는 키 (`task_instance` · `exception` · `run_id` · `log_url`) 가 3.x 에도 있는가.

SQLite 로 띄운 확인은 이 넷을 답해도 Postgres 드라이버 구멍은 보여 주지 않는다.
`db migrate` 가 만드는 비동기 엔진은 메타데이터 DB 가 Postgres 일 때만 켜지므로, 그 구멍은 실물 설치 (태스크 8) 에서야 드러났다 (`docs/troubleshooting/2026-09-04-what-only-showed-up-when-airflow-actually-ran.md`).

### 9.2. 단위 테스트

- 단계 함수 넷이 같은 DB 상태에서 `main` 과 같은 결과를 내는지.
  기존 회차 테스트는 단계 진입점을 통과하도록 조정하고 새로 쓰지 않는다.
- 회차 행의 두 단계 기록 (`collect` 삽입 · `publish` 갱신) 과 `fetch_detail` 의 왕복.
- SLO-6 이력이 자기 `run_id` 를 제외하는지.
- 게이트 안의 급사 재시도 — 신호 종료 두 번이면 `3` · 신호 종료 뒤 통과면 `0` · 위반은 한 번에 `1`.
- 상태 일곱 → 두 값 대응표 (§6.3) 의 세 갈래.
- 감시 스크립트의 두 축 판정과 재알림 억제.

### 9.3. DAG 파싱

5월 런북 (`docs/runbook/2026-05-27-airflow-dag-verification.md`) 의 격리 venv 절차를 되살려 `tests/test_dag_import.py` 가 실제로 돌게 한다.
지금은 프로젝트 venv 에 Airflow 가 없어 skip 만 된다.
CI 에는 넣지 않는다 (Airflow 설치가 무겁다).
계획서가 로컬 검증 단계로 둔다.

### 9.4. 라이브 리허설

- §8 의 2.
- 2β 리허설과 같은 `rollback` → `unblock` → 손 시작을 DAG 위에서 한 번.
  손 시작은 `airflow dags trigger bullet_in_cycle` 이다.
- 도는 중 롤백 — 회차가 도는 동안 `rollback` 을 쳐도 그 실행이 끝까지 가는지 (§6.4).
- 게이트 건너뜀 — 게이트 셸이 `3` 을 내게 한 번 꾸며 `deploy_site` 가 건너뛰고 판정이 「보류」 를 내는지.
- 감시 — 스케줄러를 잠깐 세우고 다음 시각의 감시가 사고 채널에 한 장 내는지.

## 10. 범위 밖

- 워치리스트 · 백업 · 유지보수의 이관.
- Airflow 화면의 외부 공개 · 인증 (관리자 계정 하나 · SSH 터널로 끝).
- dbt 를 Airflow 태스크로 더 쪼개기.
- Airflow 버전 업그레이드 자동화.
- 안건 2ν 의 원인.
- `run.py` 의 다른 정리 (단계 분리에 필요한 것만 건드린다).

## 11. 함께 고칠 문서

- `CLAUDE.md` 머리의 스케줄 문단 — 회차와 적재는 Airflow · 셋은 systemd · 전진과 판정은 DAG 첫 · 끝 태스크.
- `README.md` 의 스케줄 행과 「보존 자산」 문구.
- `docs/runbook/2026-05-27-daily-operations.md` 의 「보존 자산」 줄.
- `docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md` §2 — 급하면 `airflow dags trigger`.
- `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` — 재시도 1회와 건너뜀.
- 2β 런북 — 알림 여섯의 대응 명령.
- `docs/superpowers/specs/2026-09-03-deploy-automation-design.md` §12 에 이 문서로의 포인터 한 줄.
- `docs/MIGRATION.md` — 3.x 실제 운영 버전.
- 잔여 안건 표의 2ε 행.
- 새 런북 하나 — Airflow 를 세우고 되돌리는 법 · 화면 여는 법 (SSH 터널) · 감시 알림을 받았을 때.

## 12. 참조

- 잔여 안건 표의 `2ε` 행 · 2026-09-01 재평가.
- `docs/superpowers/specs/2026-09-03-deploy-automation-design.md`
  — 전진 · 판정 · 롤백의 원 설계 · §8 게이트 종료 코드.
- `docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md` §2.2
  — Airflow 를 운영에서 뺀 당시 근거.
- `docs/runbook/2026-05-27-airflow-dag-verification.md` · `docs/MIGRATION.md`
  — 격리 venv 검증과 2.9 → 3.0 이관.
- `infra/systemd/bullet-in.service` · `bullet-in-warehouse.service`
  — 옮기는 유닛 둘의 현재 모양.
- Airflow 3 문서 — 설치 전제 · DB 지원 · DAG 번들 · catchup · 콜백 (2026-09-04 확인).
