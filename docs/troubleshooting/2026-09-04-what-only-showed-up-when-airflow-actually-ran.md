# 실물에서만 드러난 Airflow 함정 (2026-09-04)

안건 2ε 구현은 확인 단계를 셋 거쳤다.
계획서 태스크 0 이 착수 전 실물 검증 넷을 SQLite 기준으로 쟀고, PR B 최종 리뷰가 Airflow 3.3.1 을 따로 깔아 소스와 `--help` 를 대조했고, 그래도 남은 자리 셋이 태스크 8 (실물 설치 · 실행) 에서야 드러났다.
아홉 자리 전부 확인이 없었던 것이 아니라, 확인마다 못 보는 축이 따로 있었다.

## 1. SQLite 로 띄운 확인 — Postgres 드라이버 구멍은 못 본다

태스크 0 은 상주 메모리 · `skip_on_exit_code` · 판정 컨텍스트 메서드 · 실패 콜백 키를 SQLite 기준 Airflow 로 확인했다 (스펙 §9.1).
실제 설치는 메타데이터 DB 가 Postgres 라 `db migrate` 가 비동기 엔진도 함께 만든다 (`settings.py` 의 `configure_orm` → `_configure_async_session`).
`psycopg2-binary` 는 동기 드라이버라, 태스크 8 1단계 (12:07) 에서 `ModuleNotFoundError: asyncpg` 로 설치가 죽었다.
처방은 `apache-airflow[postgres]` 로 바꿔 asyncpg 를 함께 까는 것이었다 (재실행 8.7초).

이 자리는 태스크 0 이 잰 넷 중 어디에도 없었다 — 확인 항목이 아니라 확인에 쓴 기반 (SQLite) 자체가 다른 조합이었다.

## 2. `--help` 머리만 본 확인 — 인자 형식 · 플래그 조합 · stdout 내용은 안 보인다

태스크 0 은 판정 컨텍스트 메서드가 있는지를 `states-for-dag-run --help` 로만 확인했다.
그 확인이 답한 것은 "그 명령이 있다" 뿐이고, 다음 셋은 어디에도 안 걸렸다.

- `dags list-runs` 의 dag_id 가 위치 인자라는 것 (플래그가 아니다).
- `jobs check --allow-multiple` 이 `--limit` 을 같이 요구한다는 것.
- `dags list-runs -o json` 의 stdout 앞에 structlog 경고 줄이 섞여 나온다는 것.

세 자리 다 명령이 "있다" 는 맞았고, 어떻게 불러야 하는지와 무엇을 돌려주는지가 확인 밖이었다.

## 3. 리뷰어가 3.3.1 을 실제로 깔아서 잡은 것

PR B 최종 리뷰는 여기서 한 걸음 더 나갔다.
Airflow 3.3.1 을 따로 설치해 소스와 `--help` 를 대조했고, 그렇게 넷을 잡았다.

- `judge` 태스크 셸이 `airflow tasks states-for-dag-run` 을 부르기 전에 메타데이터 DB 접속이 막혀 있는 것 — Task SDK 가 태스크 프로세스를 fork 한 직후 `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` 을 `airflow-db-not-allowed:///` 로 덮어써서다.
  `BashOperator` 는 `os.environ.copy()` 로 그 값을 그대로 물려받으므로, CLI 를 부르기 전에 `airflow.env` 를 다시 읽어 접속 문자열을 되살리게 고쳤다.
- `dags list-runs` 의 dag_id 위치 인자 (위 §2 에서 못 봤던 자리를 여기서 잡았다).
- `dagrun_timeout` 초과가 미완 태스크를 전부 SKIPPED 로 바꿔 `judge` 도 태스크 콜백도 안 도는 것 — DAG 수준 `on_failure_callback` 을 새로 달았다.
- `AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL` 이 3.0 에서 `[dag_processor] refresh_interval` 로 옮겨져 기동마다 deprecated 경고를 냈다.

소스와 `--help` 를 실제로 열어 보는 확인이 여기까지는 닿는다.

## 4. 그래도 유닛이 실제로 도는 순간에만 난 것

리뷰가 설치까지 했는데도 둘은 남았다 — 소스를 읽고 `--help` 를 대조하는 것과, 유닛이 실제로 그 명령을 부르는 것은 다른 확인이었다.

- **`jobs check --allow-multiple`** — 태스크 8 리허설 4 (15:23) 에서 `rc=1` 로 죽었다.
  `--limit` 없이 `--allow-multiple` 만 주면 3.3.1 이 거부한다.
  PR B 가 넣은 실패 경로 경고 로그 (§ 아래 문서) 가 이 실패를 드러냈다 — 로그가 없었다면 심박 축은 계속 「없음」 으로만 찍혔을 것이다.
- **`dags list-runs -o json` 의 stdout 오염** — 같은 리허설에서 `json.loads` 가 `Extra data: line 1 column 5 (char 4)` 로 죽었다.
  stdout 첫 줄이 structlog 경고 (`Could not import graphviz …`) 였고, 그 줄의 `2026` 이 숫자로 파싱돼 JSON 파서가 그 자리에서 멈췄다.
  최종 리뷰는 이 자리를 「can-wait」 로 유예했었다 (아래 문서에 이어서 적는다).

## 자리를 하나 빠뜨린 것도 아홉 번째다

`deploy_site` 의 `bash_command` 가 `.sh` 로 끝나 `BashOperator` 가 그것을 Jinja 템플릿 파일로 읽으려 드는 것과, 격리 venv 테스트가 쓰던 `DagBag(include_examples=…)` 가 3.3.1 생성자에 없는 것은 위 셋보다 먼저, 태스크 4 구현자의 자기 검토에서 잡혔다.
설치 없이도 코드를 다시 읽는 것만으로 잡히는 자리가 있었다는 뜻이고, 그래서 아홉 자리 전부가 "실물이 아니면 못 잡는다" 는 아니었다.

## 잣대의 교훈

- **SQLite 로 띄운 확인은 Postgres 드라이버 구멍을 숨긴다.**
  기반을 실물과 다르게 두면 확인 항목이 다 맞아도 설치가 죽을 수 있다.
- **`--help` 를 읽는 것은 그 명령을 부르는 것이 아니다.**
  인자 순서 · 플래그 조합 · 표준출력에 무엇이 섞여 나오는지는 `--help` 밖이다.
- **유닛이 실제로 부르는 명령은 유닛과 같은 환경에서 한 번 실행해 봐야 한다.**
  소스를 읽고 `--help` 를 대조하는 확인이 셋을 잡았어도, 실행 자체는 다른 층의 확인이었다.

## 함께 볼 것

- `docs/troubleshooting/2026-09-04-a-watch-that-could-only-ever-cry-wolf.md`
  — §4 의 두 자리 (침묵하던 실패 경로 · stdout 오염) 를 더 자세히 다룬다.
- `docs/troubleshooting/2026-09-04-three-rulers-that-measured-the-wrong-thing.md`
  — 같은 구현 회차에서 잣대 자체가 틀렸던 사례 셋 (워크트리 테스트 · PSS · `pkill -f`).
- `docs/superpowers/specs/2026-09-04-airflow-migration-design.md` §9.1
  — 착수 전 실물 검증 넷과 그 한계.
- `docs/runbook/2026-09-04-running-the-cycle-under-airflow.md` §6.4
  — 아홉 자리를 짧은 표로.
