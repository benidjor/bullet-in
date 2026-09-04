# 런북 — 회차가 Airflow 아래에서 도는 법

회차와 웨어하우스 적재는 2026-09-04 15:51 KST 부터 VM 의 Airflow 3.3.1 DAG `bullet_in_cycle` 로 돈다.
설계는 `docs/superpowers/specs/2026-09-04-airflow-migration-design.md` 에 있고 이 문서는 그 설계를 세운 뒤의 운영 절차를 모은다.

## 1. 무엇이 어디서 도나

DAG 는 태스크 여덟이고 전부 `BashOperator` 다 (Airflow venv 는 프로젝트를 import 하지 않는다).

```
advance → collect → enrich → publish → gate → deploy_site → judge
                                   └──────────────────────→ warehouse_load
```

| 태스크 | 명령 | 재시도 | 규칙 |
| --- | --- | --- | --- |
| `advance` | `deploy advance` (실패해도 `\|\| true` 로 뒤가 돈다) | 0 | `all_success` |
| `collect` | `run --stage collect` | 0 (재수집은 원본을 다시 훑는다 — 사람이 태스크 clear) | `all_success` |
| `enrich` | `run --stage enrich` | 0 (429 는 다음 회차가 잇는다) | `all_success` |
| `publish` | `run --stage publish` | 1 | `all_success` |
| `gate` | `run --stage gate` | 0 (급사 재시도는 게이트 함수 안에서 이미 한 번) | `all_success` · `skip_on_exit_code=3` |
| `deploy_site` | `infra/deploy-site.sh` (끝에 공백 — `.sh` 로 끝나면 BashOperator 가 Jinja 템플릿 파일로 읽으려 든다) | 1 | `all_success` |
| `judge` | `tasks states-for-dag-run` 뒤 `deploy judge --from-airflow` | 0 | `all_done` |
| `warehouse_load` | `warehouse load` (전용 서비스 계정으로 감싼다) | 0 | `all_done` · `publish` 뒤 |

`gate` 가 종료 코드 `3` (신호 종료 두 번째도 실패) 을 내면 「실패」 가 아니라 「건너뜀」 으로 찍히고 뒤의 `deploy_site` 도 기본 규칙에 따라 함께 건너뛴다.
`judge` · `warehouse_load` 는 `all_done` 이라 앞이 어떻게 끝났든 돈다.
`catchup=False` · `max_active_runs=1` · `dagrun_timeout=30분` 은 지금까지의 systemd 타이머 성질 (밀린 회차는 최근 구간 한 번 · 이중 실행 금지) 을 그대로 옮겼다.

자리는 이렇다.

| 항목 | 값 |
| --- | --- |
| Airflow venv | `/home/ubuntu/airflow-venv` |
| `AIRFLOW_HOME` | `/home/ubuntu/airflow` |
| 설정 | `~/airflow/airflow.env` (저장소 `infra/airflow/airflow.env` 복사본) |
| DAG 폴더 | `/home/ubuntu/bullet-in/airflow/dags` (저장소 체크아웃 그대로) |
| 메타데이터 DB | compose 서비스 `airflow-db` (Postgres 16 · `127.0.0.1:5433`) |
| 태스크 로그 | `~/airflow/logs/dag_id=bullet_in_cycle/run_id=<run>/task_id=<task>/attempt=<n>.log` |

워치리스트 · 백업 · 유지보수는 그대로 systemd 타이머로 돈다.
회차 · 웨어하우스 타이머 (`bullet-in.timer` · `bullet-in-warehouse.timer`) 는 유닛 파일이 남아 있지만 비활성이다 (§5 되돌리기의 경로).

구현이 스펙과 다른 자리가 둘 있다.
생존 감시 스크립트는 `src/bullet_in/airflow_watch.py` 다 (스펙 §4.4 는 `infra/airflow/watch.py` 를 적었다).
Airflow 설정 파일은 `infra/airflow/airflow.env` 다 (스펙 §4.1 은 `airflow.cfg` 를 적었다).
둘 다 구현 단계에서 더 단순한 자리로 옮겨졌고 동작은 스펙과 같다.

## 2. 화면 여는 법

api-server 는 `127.0.0.1:8080` 에만 묶여 있어 SSH 터널로 본다.

```bash
ssh -i ~/.ssh/seoulnow_deploy -L 8080:127.0.0.1:8080 ubuntu@155.248.164.17
```

터널을 연 채로 브라우저에서 `http://127.0.0.1:8080` 을 연다.
계정은 `admin` 이고 비밀번호는 첫 api-server 기동 때 생긴 파일에 있다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cat ~/airflow/simple_auth_manager_passwords.json.generated'
```

api-server 저널에는 「SimpleAuthManager is active but the deployment shape looks like production … Use a real auth manager」 경고가 남는다.
화면을 루프백 한 곳에만 묶고 SSH 터널로만 연다는 전제 위에서 이 경고는 수용한다 — 밖으로 열 계획이 없다.

## 3. 손으로 회차 시작 · 특정 단계만 다시

CLI 를 손으로 칠 때는 Airflow 환경변수를 먼저 읽는다.

```bash
set -a; . ~/airflow/airflow.env; set +a
PYTHONWARNINGS=ignore ~/airflow-venv/bin/airflow dags trigger bullet_in_cycle
```

`unpause` 는 스케줄이 켜져 있는데 최근 구간 실행이 없을 때만 그 구간 실행을 하나 만든다.
이미 최근 구간 실행이 있으면 (예: 방금 켰는데 정시 스케줄이 아직 안 지났으면) 아무 일도 안 일어난다 — 새 실행이 필요하면 `dags trigger` 를 쓴다.

특정 단계만 다시 돌리려면 화면에서 그 태스크를 눌러 Clear 한다.
`collect` 는 Airflow 재시도가 0 인 것과 별개로 사람이 언제든 clear 로 다시 돌릴 수 있다 — 다만 clear 하면 그 소스들을 다시 훑으므로, 원인이 코드가 아니라 일시적인 것 (네트워크 · 소스 쪽) 인지 먼저 본다.
`gate` 를 clear 하면 게이트만 다시 돌고 `deploy_site` · `judge` 가 그 뒤를 잇는다.

## 4. 알림을 받았을 때

**태스크 실패 (❌)** — 실패 콜백이 사고 채널에 「❌ 파이프라인 실패 — `<task_id>`」 를 보낸다.
로그 링크를 눌러 그 태스크의 로그를 연다.
`collect` · `enrich` · `publish` · `gate` (위반) · `deploy_site` 중 하나가 실패하면 `judge` 가 뒤이어 「⏪ 코드 롤백」 을 낸다 (2β 규칙 그대로 · `docs/runbook/2026-09-04-when-the-cycle-deploys-itself.md` §2).

**DAG 수준 실패** — `dagrun_timeout` (30분) 을 넘기면 스케줄러가 미완 태스크를 전부 SKIPPED 로 바꾸고 그 상태에서는 태스크 콜백이 하나도 안 불린다 (콜백은 태스크가 진짜로 실행되고 실패했을 때만 붙는다).
DAG 레벨 `on_failure_callback` 이 이 자리를 잇는다 — task_id `dag_run` 으로 사고 채널에 한 장 보내고 「시간 초과면 judge 가 안 돌아 판정이 없다 · 다음 회차가 잇는다」 를 본문에 싣는다.
`pending` 이 참인 채로 다음 회차로 넘어가고 다음 회차의 `judge` 가 그 `pending` 을 이어 판정한다 — 판정이 없어도 회차가 조용히 사라지지 않게 하려고 이 콜백을 둔다.
`judge` · `warehouse_load` 처럼 `all_done` 인 리프가 성공하면 실행 전체는 success 로 끝나므로, 중간 태스크가 실패해도 그 태스크의 콜백 한 장만 온다.
리프 (`judge` · `warehouse_load`) 자체가 실패하면 실행 전체가 failed 로 끝나 DAG 콜백까지 겹쳐, 태스크 콜백과 합쳐 두 장이 온다.

**생존 감시 (🚨)** — `bullet-in-airflow-watch.timer` 가 매시 37분 (UTC) 에 두 축을 잰다: 스케줄러 심박 (`airflow jobs check --job-type SchedulerJob`) 과 `bullet_in_cycle` 의 최근 성공 실행이 4시간 안인가.
「성공 실행」 은 judge 까지 도달한 실행이다 — `judge` 가 `all_done` 이라 중간 태스크가 실패해도 리프가 끝나면 DAG 실행 상태는 success 이기 때문이다.
어느 축이든 깨지면 사고 채널에 「🚨 Airflow 가 회차를 안 돌리고 있다」 가 오고 같은 상태가 이어지는 동안은 4시간마다 한 번만 다시 온다.
알림 본문이 알려 주는 확인 명령 둘이다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'systemctl status airflow-scheduler airflow-dag-processor airflow-api-server'
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'set -a; . ~/airflow/airflow.env; set +a; ~/airflow-venv/bin/airflow dags state bullet_in_cycle'
```

`api-server` 도 셋에 들어가는 이유가 있다 — 화면만이 아니라 태스크 실행 API (`execution_api_server_url`) 를 내므로, 셋 중 하나라도 죽으면 회차가 못 돈다.
셋 다 `Restart=on-failure` · `RestartSec=10` 이다.

**배포 자동화의 알림 여섯** (✅ 반영 완료 · ⏸ 판정 보류 · ⏪ 롤백 · 🚧 사전 점검 실패 · 🚧 VM 트리 분기 · 🚧 라이브 표지 불일치) 은 서식 · 대응이 안 바뀌었다.
`docs/runbook/2026-09-04-when-the-cycle-deploys-itself.md` 를 그대로 본다 — 대응 명령만 DAG 트리거 · 태스크 로그로 바뀌었다.

## 5. 되돌리기

Airflow 를 세우고 systemd 타이머로 되돌려야 할 때는 두 명령을 이 순서로 친다.

```bash
set -a; . ~/airflow/airflow.env; set +a
~/airflow-venv/bin/airflow dags pause bullet_in_cycle

sudo systemctl enable --now bullet-in.timer bullet-in-warehouse.timer
```

**반대 순서는 금지다.**
타이머를 먼저 켜면 DAG 가 도는 채로 systemd 회차도 같은 구간에 겹쳐 돌아 이중 실행이 난다.

되돌리는 조건은 연속 두 회차가 Airflow 탓 (스케줄러 · 워커 · 파싱) 으로 안 돌 때다.
데이터 탓 (게이트 위반 · 소스 차단) 은 되돌릴 이유가 아니다 — 그것은 systemd 로 돌아가도 똑같이 겪는다.

수동 `deploy rollback` (사람이 화면을 보고 되돌리는 경우) 은 소스 트리를 직전 커밋 (`state/deploy.json` 의 `previous`) 으로만 되돌린다.
`current` 값은 그대로 두고 되돌린 커밋을 `blocked` 목록에 넣는다 (2β 설계 · `bad`/`good` 을 `previous`/`current` 로 다시 잇는 것은 `unblock` 뒤 재전진의 몫이다).

**롤백은 되돌리기 도구가 자기 자신을 들여온 커밋보다 앞으로 가면 안 된다.**
그 앞 커밋에는 `src/bullet_in/deploy.py` 가 없어서 되돌린 순간 `unblock` · `advance` · `judge` 가 전부 「모듈 없음」 으로 죽고 손 `git pull` 만이 복구 경로다.
실물로 겪은 함정과 고친 리허설 순서는 `docs/troubleshooting/2026-09-04-a-rollback-that-deletes-the-rollback-tool.md` 를 본다.

## 6. 전환 기록

### 6.1. 2026-09-04 타임라인

| 시각 (KST) | 무엇 |
| --- | --- |
| 12:07 – 12:09 | 1단계 설치 — `db migrate` 가 `asyncpg` 없이 죽음 → `apache-airflow[postgres]` 로 고쳐 재실행 |
| 15:07 – 15:14 | 2단계 — systemd 회차 종료 직후 DAG `unpause` + 손 실행, 대조 다섯 통과 |
| 15:15 – 15:22 | 리허설 1 (게이트 건너뜀) — `gate` 를 `exit 3` 으로 꾸며 `deploy_site` skip · `judge` 「보류 없음」 확인 |
| 15:23 – 15:40 | 리허설 2 (감시) — 첫 시도가 Traceback 으로 죽음 → PR #464 머지 → 재시도로 🚨 · 심박 OK 확인 |
| 15:35 | 리허설 3 — PR #464 를 DAG 손 실행으로 반영 (Airflow 아래에서 전진 · 판정이 실제로 돈 첫 회차) |
| 15:41 – 15:50 | 리허설 4 (도는 중 롤백 + 되살리기) — 회차가 도는 동안 `rollback` → `unblock` → 재전진 |
| 15:51 | 전환 완료 — `bullet-in.timer` · `bullet-in-warehouse.timer` `disable --now` → DAG `unpause` → 감시 타이머 시작 |
| 18:00 | 첫 정규 실행 (`scheduled__2026-09-04T09:00:00+00:00`) |

### 6.2. 실측

- 설치: 첫 실행 실패 뒤 재실행 8.7초 (venv 재사용 · uv 캐시).
- 상주 메모리: PSS 547 MB (Airflow 프로세스 여섯 + Postgres 백엔드 몫) — 태스크 0 의 509 MB (SQLite) 와 같은 급.
- 손 실행 둘 (`scheduled__…06:00:00` 앞 · `manual__…06:07:47` 뒤): 소요 3분 20초 · 3분 16초, 전부 태스크 여덟 success — systemd 회차와 같은 급.
- 리허설 1 (게이트 건너뜀) 의 `collect` 는 2분 45초 (재파싱 대기가 겹쳤다) — 다른 회차는 1분 22초 안팎.

### 6.3. 리허설 결과

| 리허설 | 결과 |
| --- | --- |
| 게이트 건너뜀 | `gate` · `deploy_site` skipped · `judge` success (「판정 대기 없음」) |
| 감시 (첫 시도) | `bullet-in-airflow-watch.service` Traceback 으로 실패 — PR #464 로 고침 |
| 감시 (재시도) | 🚨 한 장 → 고침 뒤 「심박 OK · 문제 0 · 발송 False」 |
| PR #464 를 DAG 위에서 반영 | advance 「전진 3dfa06a → d9cd66d」 · judge 「반영 완료」 |
| 도는 중 롤백 | 실행 중인 태스크를 안 건드리고 끝까지 감 · `judge` 「판정 대기 없음」 (rollback 이 pending 을 지웠다) |
| 되살리기 (`unblock` → 재전진) | advance 「전진 3dfa06a → d9cd66d」 · judge 「반영 완료」 |

### 6.4. 결함 아홉 — 리뷰가 미리 잡은 것 여섯 · 실물에서만 드러난 것 셋

태스크 0 의 SQLite 검증과 최종 코드 리뷰 (3.3.1 을 깔아 소스 대조) 가 아홉 자리 중 여섯을 실물 전에 잡았고, 나머지 셋은 실물 설치 · 실행에서야 드러났다.
어떻게 찾았는지와 잣대의 교훈은 `docs/troubleshooting/2026-09-04-what-only-showed-up-when-airflow-actually-ran.md` 를 본다.
감시 스크립트의 침묵하던 실패 경로 하나는 별도로 `docs/troubleshooting/2026-09-04-a-watch-that-could-only-ever-cry-wolf.md` 에 있다.

**리뷰가 미리 잡은 것 (여섯)**

| 자리 | 증상 | 처방 | 누가 |
| --- | --- | --- | --- |
| `judge` 태스크 셸 | Task SDK 가 DB 접속을 막아 둠 | CLI 앞에 `airflow.env` 재로딩 | PR B 최종 리뷰 |
| 감시 `dags list-runs` | dag_id 가 위치 인자인데 `-d` 로 넘김 → 영구 오탐 | 인자 정정 + 실패 경로 경고 로그 | PR B 최종 리뷰 |
| `dagrun_timeout` 초과 | `judge` 도 태스크 콜백도 안 돎 | DAG 수준 `on_failure_callback` | PR B 최종 리뷰 |
| `AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL` | 기동마다 deprecated 경고 | `AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL` 로 정정 | PR B 최종 리뷰 |
| `deploy_site` 의 `.sh` 끝 | BashOperator 가 Jinja 템플릿 파일로 읽으려 함 | 명령 끝에 공백 하나 | 태스크 4 구현자 자기 검토 |
| 격리 venv 테스트의 `DagBag(include_examples=…)` | 3.3.1 생성자에 그 인자가 없음 | `DagBag(dag_folder=…)` · `--noconftest` | 태스크 4 구현자 자기 검토 |

**실물에서만 드러난 것 (셋)**

| 자리 | 증상 | 처방 | 누가 · 언제 |
| --- | --- | --- | --- |
| 설치 `db migrate` | `ModuleNotFoundError: asyncpg` | `apache-airflow[postgres]` | 태스크 8 1단계 · 12:07 |
| 감시 `jobs check --allow-multiple` | 3.3.1 은 `--limit` 도 요구 → rc=1 | 플래그 제거 | 태스크 8 리허설 4 · 15:23 |
| 감시 `dags list-runs -o json` | structlog 경고가 stdout 앞줄에 섞여 JSON 파싱 실패 | 첫 `[`/`{` 줄부터 읽기 + `PYTHONWARNINGS=ignore` | 태스크 8 리허설 4 · 15:23 |

### 6.5. 첫 24시간

정규 실행 8회의 대조는 09-05 에 이 절에 덧붙인다 (지금은 대조 예정).
