# 재시도가 성공을 만들자 코어 덤프 넷이 아무에게도 안 보였다 (2026-09-18)

- **영역**: dbt 게이트 / 관측 / 안건 2ν
- **관련 문서**: `docs/troubleshooting/2026-09-01-the-gate-blocked-and-the-journal-could-not-say-why.md` · `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` §3.2
- **관련 안건**: 2ν dbt게이트급사 (죽는 자리 확정 · 확장 내부 결함은 미확정)

## 1. 증상

관측 기록을 검토하다 「코어 덤프는 다음에 -11 이 나면 받는다」 고 말하려던 참이었다.
말하기 전에 VM 을 봤더니 덤프가 이미 넷 있었다.

```
$ coredumpctl list
Thu 2026-09-03 17:08  python3.12   SIGSEGV  829K   ← 09-03 설치 때의 시험 세그폴트
Fri 2026-09-04 15:43  python3.11   SIGSEGV  21.0M  ← dbt build (manual run)
Sat 2026-09-05 18:02  python3.11   SIGSEGV  20.9M
Wed 2026-09-09 15:02  python3.11   SIGSEGV  21.0M
Tue 2026-09-15 21:01  python3.11   SIGSEGV  20.9M
```

Airflow 의 `gate` 태스크 로그 넷에 같은 시각의 경고가 있었다.

```
WARNING dbt 가 신호로 죽었다 (종료코드 -11 · 시도 1/2)
```

네 번 모두 두 번째 `dbt build` 가 통과해 실행은 success 로 끝났다.
`airflow dags list-runs` 는 정규 실행 105/105 success 를 보여 주고, 저널에도 차단이 없다.
**세그폴트는 2주 동안 네 번 더 났는데, 실패로 드러난 적이 없어 아무도 덤프를 열지 않았다.**

## 2. 원인 — 통과가 관측을 지웠다

09-03 에 코어 덤프 받는 쪽을 깔면서 정한 신호는 「다음에 게이트가 -11 로 죽으면 `coredumpctl info -1`」 이었다.
같은 날 계획서에 「한 번 재시도로 지나간 급사도 2ν 의 관측으로 센다 (경고 줄을 grep)」 라고도 적어 두었다.
그런데 09-04 에 들어간 재시도 1회 (`run_gate(crash_retries=1)`) 는 신호로 죽은 실행을 성공으로 바꾼다.
그 뒤로 -11 은 차단이 아니라 로그 한 줄로만 남았고, 그 줄을 grep 하는 사람이 없었다.

이것은 [`2026-08-15-verification-that-silently-passes.md`](2026-08-15-verification-that-silently-passes.md) 와 같은 병이다.
실패를 흡수하는 장치 (재시도 · 억제 · 폴백) 를 넣을 때는 흡수한 횟수를 세는 지표나 알림을 같이 넣어야 한다.
그러지 않으면 그런 실패는 통과 안으로 사라진다.

## 3. 덤프가 말한 것 — 죽는 자리는 `mysql_scanner` 다

```
$ coredumpctl info -1
Signal: 11 (SEGV)
Command Line: /home/ubuntu/bullet-in/.venv/bin/python3 .venv/bin/dbt build
#0  … mysql_scanner.duckdb_extension + 0x13ade18
#1  … mysql_scanner.duckdb_extension + 0x13adebc
…
#16 … mysql_scanner.duckdb_extension + 0x217f20
#17 … _duckdb.cpython-311-aarch64-linux-gnu.so + 0x1f6abe4
```

스택 위쪽 열일곱 단이 전부 `~/.duckdb/extensions/v1.5.3/linux_arm64/mysql_scanner.duckdb_extension` 안이다.
09-03 에 「남은 후보는 DuckDB `mysql_scanner` 확장의 하드 크래시 하나」 라고 추정한 것이 확정됐다.
확장이 디버그 심볼 없이 배포돼 함수 이름은 `n/a` 라, 확장 안의 어느 결함인지는 이 덤프로 더 좁힐 수 없다.
`dbt/profiles.yml` 에는 같은 확장의 다른 결함 (attach 테이블 위 집계에서 바인더 오류) 을 `disabled_optimizers: "extension"` 으로 우회한 기록이 이미 있다.

## 4. 얼마나 자주 나나 — 7/150

「몇 번 중 몇 번」 을 말하려면 분모가 필요했고, 게이트 실행 수는 두 층에 나뉘어 있다.

| 층 | 기간 | 게이트 실행 | 신호로 죽음 |
| --- | --- | --- | --- |
| systemd 저널 `bullet-in.service` | 08-31 16:27 (게이트 도입) ~ 09-04 15:07 | 40 (「dbt 게이트 통과」 37 + 「배포를 세웠다」 3) | 3 (08-31 21:05 -11 · 09-01 09:03 **-7 SIGBUS** · 09-03 03:06 -11) |
| Airflow `task_id=gate` 로그 | 09-04 ~ 09-17 15:00 | 110 (로그 111 중 `Skipping task` 1 제외) | 4 (전부 재시도로 통과) |
| 합계 | | 150 | 7 |

- 09-01 의 차단은 -11 이 아니라 -7 (버스 오류) 이었다.
  같은 종류의 「OS 가 메모리 접근 위반으로 강제 종료」 라 같이 셌지만, 엄밀한 세그폴트 수는 6 이다.
- CI 는 뺐다.
  CI 의 dbt 는 빈 표를 보는 다른 환경이고, 09-03 03:12 의 1건은 CI 실행 183회 (dbt 진입 08-31 이후) 중 하나다.
- `dbt/logs/dbt.log` 는 분모로 못 쓴다.
  10 MB 에서 회전해 09-10 이전이 잘려 있다.

## 5. 남긴 것

- **안건 2ν 의 다음 단계가 바뀐다.**
  「다음 -11 을 기다린다」 가 아니라 「덤프 넷이 있고 자리는 확정됐으니 `mysql_scanner` 의 버전 · 알려진 이슈를 찾는다」 다.
  덤프는 하나에 약 21 MB 로 넷이 `/var/lib/systemd/coredump/` 에 있다.
- **재시도로 지나간 급사를 세는 자리가 없다.**
  수집 현황 대시보드나 감시 발송에 「신호로 죽었다」 경고 줄 수를 올리는 것이 후보다.
- 관측 요약은 「3회 관측」 을 「7/150회 관측, 재시도 1회 적용 후 4/4회 배포 정상, 코어 덤프로 에러 위치를 DuckDB 의 MariaDB 커넥터로 특정」 으로 고쳤다.

## 6. 교훈

- **흡수 장치에는 계수기를 붙인다.**
  재시도 · 억제 · 폴백이 실패를 성공으로 바꾸는 순간 그 실패는 화면에서 사라진다.
  「경고 줄을 grep 한다」 는 다짐은 계수기가 아니다.
- **「아직 없다」 는 말은 확인한 뒤에 한다.**
  덤프가 없다고 말하려던 순간 명령 하나가 넷을 보여 줬다.
  [`verify-sentences-before-asserting-them`] 의 실물 하나 더다.
