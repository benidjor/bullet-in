# 침묵하던 감시의 실패 경로 (2026-09-04)

생존 감시 (`src/bullet_in/airflow_watch.py`) 는 `bullet_in_cycle` 이 조용히 안 도는 것을 잡으려고 만들었다.
그런데 그 감시 자신의 CLI 호출이 실패하는 경로가 침묵하고 있었다.
CLI 가 왜 실패했는지 안 남기고 그 자리를 "성공 실행이 없다" 로만 읽었고, 그래서 명령이 진짜로 잘못됐을 때와 정말 회차가 안 돌았을 때가 로그 위에서 구분이 안 됐다.
있지도 않은 플래그 하나가 단위 테스트 · 태스크 리뷰 · 최종 리뷰 셋을 다 지나갔다.

## 1. 증상

`airflow dags list-runs bullet_in_cycle -o json` 이 무슨 이유로든 실패하면 (인자 오류 · 권한 · 무엇이든) 감시는 이렇게 읽었다.

```python
age = latest_success_age(runs.stdout, now) if runs.returncode == 0 else None
problems = evaluate(hb.returncode == 0, age)
```

`age` 가 `None` 이면 `evaluate` 는 `"{DAG_ID} 의 성공 실행이 없다"` 를 문제 목록에 넣는다.
CLI 가 인자 오류로 죽어도, 진짜로 12시간 동안 회차가 한 번도 안 성공해도, 결과 문자열은 똑같았다.
어느 쪽인지는 이 알림만 보고는 갈리지 않았다.

## 2. 원인

경로 자체가 "실패하면 None, None 이면 문제로 본다" 는 정상적인 판정 로직이다.
그런데 그 경로에 **왜 `None` 이 나왔는지를 남기는 자리가 없었다.**

- CLI 명령의 종료 코드와 stderr 를 버렸다 — `subprocess.run` 의 결과를 age 계산에만 썼다.
- 그래서 명령 자체가 잘못됐다는 신호 (rc≠0) 와, 명령은 맞는데 대상이 없다는 신호 (rc=0 · 빈 목록) 가 같은 값 (`None`) 으로 합쳐졌다.

이 침묵 위에서 실제로 없던 플래그 하나가 오래 버텼다.
`jobs check --allow-multiple` 은 3.3.1 에서 `--limit` 을 같이 줘야 하는데, 없어서 매번 `rc=1` 로 죽었다.
단위 테스트는 이 CLI 를 모킹해서 통과했다 (모킹은 존재하지 않는 플래그를 못 잡는다).
태스크 리뷰와 최종 리뷰는 코드와 `--help` 를 읽었지만, 실제로 그 명령을 그 환경에서 부르지는 않았다 (`docs/troubleshooting/2026-09-04-what-only-showed-up-when-airflow-actually-ran.md` §4).
셋 다 지나갔다는 것은 이 플래그가 감시를 영원히 "성공 실행이 없다" 로만 울릴 수 있었다는 뜻이다 — 진짜 장애와 똑같은 모양이라 사람이 매번 처음부터 원인을 다시 찾아야 했을 것이다.

## 3. 해결

PR B 의 고침이 두 겹이었다.

1. **먼저 침묵하던 경로에 로그를 달았다.**
   ```python
   if runs.returncode != 0:
       log.warning("%s 실패 (rc=%d) — %s", "dags list-runs", runs.returncode, runs.stderr[:300])
   ```
   `jobs check` 실패에도 같은 자리를 뒀다.
   이 자체는 판정 값을 안 바꾼다 — `age` 는 여전히 `None` 이고 문제 목록도 똑같다.
   로그를 보면 사람이 "성공 실행이 없다" 와 "CLI 가 죽었다" 를 더는 헷갈리지 않는다.
2. **로그가 실제로 다음 결함을 드러냈다.**
   태스크 8 리허설 4 (15:23) 에서 감시를 처음 실제로 돌리자 `bullet-in-airflow-watch.service` 가 Traceback 으로 죽었다.
   경고 로그 (`dags list-runs 실패 (rc=1) — … --allow-multiple …`) 가 원인을 바로 보여줬고, 그 자리에서 `--allow-multiple` 이 3.3.1 에서 `--limit` 을 요구한다는 것을 알았다.
   로그가 없었다면 이 리허설도 "성공 실행이 없다" 로만 찍히고, 원인이 감시 자신의 명령 오류라는 것을 알아채기까지 더 오래 걸렸을 것이다.

같은 리허설에서 두 번째 결함도 났다.
`dags list-runs -o json` 의 stdout 앞줄에 structlog 경고 (`Could not import graphviz …`) 가 섞여 `json.loads` 가 「Extra data」 로 죽었다.
이 자리는 최종 리뷰가 이미 본 자리였다 — "stdout 이 지저분할 수 있다" 는 지적을 「can-wait」 로 다음으로 미뤄 뒀었다.
미뤄 둔 사이 라이브에서 그대로 Traceback 이 됐고, `deploy.cli_json` 과 감시 양쪽에서 첫 `[` 또는 `{` 로 시작하는 줄부터 읽게 하고 `PYTHONWARNINGS=ignore` 를 셸 환경에 더해 고쳤다.

## 4. 예방

- **실패하면 값을 조용히 바꾸는 경로는 로그부터 넣는다.**
  `None` · `0` · 빈 목록처럼 "괜찮아 보이는 값" 을 리턴하는 실패 경로가 가장 위험하다 — 결과만 보면 정상 케이스와 구분이 안 된다.
  이번에 그 로그 하나가 없었다면 두 번째 결함 (`--allow-multiple`) 도 몇 사이클 동안 "성공 실행이 없다" 뒤에 숨어 있었을 것이다.
- **"stdout 이 지저분할 수 있다" 는 지적을 미루는 것은 크래시를 미루는 것이다.**
  can-wait 로 접어 둔 자리가 다음 리허설에서 그대로 Traceback 으로 돌아왔다.
  외부 CLI 의 stdout 을 파싱하는 자리는 경고 · 로그가 섞일 수 있다는 전제를 코드 리뷰 단계에서 바로 반영한다.
- **모킹한 단위 테스트는 존재하지 않는 플래그를 못 잡는다.**
  CLI 인자가 맞는지는 그 바이너리를 실제로 불러야 확인된다 (앞 문서의 잣대 교훈과 같다).

## 함께 볼 것

- `docs/troubleshooting/2026-09-04-what-only-showed-up-when-airflow-actually-ran.md`
  — 같은 태스크 8 리허설에서 함께 드러난 아홉 자리 전체.
- `docs/runbook/2026-09-04-running-the-cycle-under-airflow.md` §4
  — 생존 감시 🚨 알림을 받았을 때 지금 할 일.
- `src/bullet_in/airflow_watch.py`
  — 경고 로그가 붙은 자리 (`_cli` · `main`).
