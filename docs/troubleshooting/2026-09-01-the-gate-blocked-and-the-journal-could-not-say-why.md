# dbt 게이트가 배포를 세웠는데 저널로는 이유를 알 수 없었다 (2026-09-01)

- **영역**: dbt / 게이트 / 관측
- **관련 PR**: #408
- **관련 안건**: 2ν dbt게이트급사 (원인 미확정 · 대기)

## 증상

2026-08-31 21:05 KST 회차가 실패로 끝나고 사이트가 약 3시간 갱신을 멈췄다.
디스코드 장애 알림은 정상으로 왔고, 저널에는 이 한 줄이 남았다.

```
ERROR dbt 게이트가 배포를 세웠다 — run_results.json 을 못 읽었다:
      [Errno 2] No such file or directory: 'dbt/target/run_results.json'
      · dbt 출력: ... UserWarning: resource_tracker: There appear to be 2 leaked semaphore objects
```

**게이트는 설계대로 동작했다** — 차단이 났고 `ExecStartPost` 가 안 돌아 배포가 안 나갔다.
문제는 **왜 차단이 났는지를 저널로 답할 수 없었다는 것**이다.
실려 있는 것은 원인이 아니라 무해한 종료 경고였다.

다음 회차 (00:02) 가 통과하며 스스로 복구됐고, 저널 전체 기간에서 이것이 유일한 실패다.

## 원인 — 진단을 버리는 자리가 셋이었다

`src/bullet_in/dbt_gate.py` 의 진단 수집이 이랬다.

```python
tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
```

- **`stderr or stdout` 이 stdout 을 통째로 버린다.**
  dbt 는 오류를 **stdout** 에 쓴다.
  stderr 에 경고 한 줄만 있어도 `or` 가 그것을 골라 진짜 로그가 전부 사라진다.
- **`[-3:]`** — 살아남은 것도 마지막 세 줄뿐이다.
- **종료 코드를 안 남긴다.**
  결과 파일이 없는 분기에서 `proc.returncode` 를 어디에도 안 적어, `-9` (강제 종료) · `-11` (세그폴트) · `1` · `2` (dbt 자체 실패) 가 구별되지 않았다.

## 진실이 남아 있던 자리

**`~/bullet-in/dbt/logs/dbt.log` 하나뿐이다.**
dbt 가 스스로 남기고 회차마다 이어 쓴다.

이 파일로 보니 dbt 는 **노드 29개 중 22개를 통과**시켰다.
23번째 (`slo_rollup` · table 머티리얼라이제이션) 실행 중에 **오류도 트레이스백도 없이 로그가 끊겼다.**

## 해결

PR #408 로 셋을 고쳤다.

- **`_diagnosis` 신설** — 종료 코드 + stdout · stderr 각 마지막 6줄 + `dbt.log` 경로를 한 줄로 담는다.
- **두 실패 분기가 같은 진단을 쓴다** — 결과 파일 없음 · 종료 코드는 실패인데 차단 항목 없음.
- **디스코드 상한 대응** — embed 필드 값이 1024자를 넘으면 메시지가 통째로 거부돼 **장애 알림 자체가 안 온다.**
  저널에는 전문을 남기고 알림에서만 자른다.

고친 뒤 같은 상황의 저널은 이렇게 나온다.

```
종료코드 -11 · stdout: Running with dbt=1.11.11 / 23 of 29 START sql table model
main.gold_slo_rollup / Runtime Error in model gold_slo_rollup · stderr:
UserWarning: resource_tracker: ... · 전체 로그는 dbt/logs/dbt.log
```

## 이 회차에 내가 세 번 틀린 잣대

### 1. 디렉터리 시각으로 실행 여부를 판단했다

`dbt/target/` 의 `compiled/` 와 `run/` 이 낡은 시각이라 「컴파일도 못 했다」 고 단정했다.
**dbt 는 같은 파일명을 덮어써서 디렉터리 mtime 이 안 바뀐다.**
`dbt.log` 를 열고 나서야 노드 22개가 통과했음을 알았다.

### 2. 표본 둘로 패턴을 말했다

실패 회차의 systemd 요약에만 `memory peak` 이 없는 것을 보고 신호라고 읽었다.
**과거 30회를 세니 성공 회차 대부분에도 없었다** (있는 것은 셋뿐).
산발적 보고이지 고장의 흔적이 아니었다.

### 3. 소급 확인 수단을 늦게 셌다

`coredumpctl` 이 설치돼 있지 않아 코어 덤프가 없다는 것을 나중에 알았다.
**확인 수단이 남아 있는지를 먼저 세고 나서 조사 계획을 짜야 한다.**

## 배제한 원인 셋 (실측)

- **OOM 아님** — 커널 로그에 해당 시간대 항목 0건 · 성공 회차의 메모리 피크가 2.1G (VM 23Gi)
- **컨테이너 재시작 아님** — MariaDB · Mongo 둘 다 6주 연속 가동
- **타임아웃 아님** — 게이트 `timeout=600` 인데 실행은 약 10초

## 남은 후보와 미확정

**DuckDB `mysql_scanner` 확장의 하드 크래시.**
트레이스백 없는 급사와 세마포어 누수 경고가 그 모양과 맞아떨어지고, `dbt/profiles.yml` 이 이미 이 조합의 알려진 버그 때문에 `disabled_optimizers: "extension"` 을 걸어 두고 있다.

**확정하지 못했다.**
확정하려면 종료 코드가 필요한데 그때 게이트가 그 값을 버렸다.

## 예방

- **PR #408 이 종료 코드를 남긴다** — 재발하면 저널 한 줄로 조사 방향이 갈린다.
- **게이트 런북에 §3.1 을 넣었다** — 저널로 원인이 안 나오면 `dbt/logs/dbt.log` 를 연다 · 디렉터리 시각으로 실행 여부를 판단하지 않는다.
- **안건 2ν 를 발동 조건과 함께 등재했다** — 게이트가 `ran=False` 로 **두 번째** 차단을 냈을 때 연다.
  그때 종료 코드가 다음 행동을 가른다 (`-9` 는 커널 로그 · `-11` 이면 그제야 `systemd-coredump` · `1` · `2` 는 `dbt.log` 로 충분).
- **지금 계측을 더 얹지 않는다** — 첫 계측의 산출을 아직 한 번도 못 봤고 관측이 하나뿐이라, 재발이 없으면 근거 없는 부채로 남는다.

## 관련

- 런북 = `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` §3.1
- 게이트 설계 = `docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md`
- 같은 종류의 함정 = `docs/troubleshooting/2026-08-15-verification-that-silently-passes.md`
