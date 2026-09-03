# 런북 — dbt 품질 게이트가 배포를 세웠을 때

회차 맨 끝에서 `dbt build` 가 돈다.
지켜야 할 계약이 깨지면 회차가 0 아닌 코드로 끝난다.
systemd 는 `ExecStart` 가 실패하면 `ExecStartPost` 를 안 돌리므로 그 회차의 배포가 나가지 않는다.
화면은 직전 산출물 그대로 남는다.

설계는 `docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md` 에 있다.

## 1. 먼저 보는 것

사고 채널에 「🚧 dbt 품질 게이트 — 배포를 세웠습니다」 가 온다.
그 알림에 어떤 테스트가 몇 행에서 깨졌는지 적혀 있다.
`OnFailure` 알림에는 유닛이 죽었다는 사실만 있으므로 원인은 앞의 알림에서 본다.

저널에서 같은 내용을 다시 읽으려면 이렇게 한다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'journalctl -u bullet-in.service -n 200 --no-pager | grep -i "게이트"'
```

나오는 줄은 셋 중 하나다.

- `dbt 게이트 통과 — 차단 0 · 경고 N` — 배포가 나갔다
- `dbt 게이트 경고 N건 — <테스트> <행수>` — 경고만 있고 배포는 나갔다
- `dbt 게이트가 배포를 세웠다 — <사유>` — 배포가 안 나갔다

## 2. 축을 가른다

**계약 축이 깨졌으면 파이프라인이 고장 났다.**
키 중복 · 필수값 결측 · 선수 참조 깨짐이 여기 든다.
정상 운영에서는 나올 수 없는 값이다.
데이터를 고치기 전에 무엇이 그런 행을 만들었는지 먼저 본다.

**품질 축이 임계를 넘었으면 부채가 갑자기 커졌다.**
고아 귀속 100건 초과 · 값 이탈 20건 초과 · 값 결측 200건 초과가 여기 든다.
임계는 관측한 사건 크기에서 뽑았다.
그래서 임계를 넘었다는 것은 평소와 다른 일이 일어났다는 뜻이다.

**게이트 자체가 못 돌았을 수도 있다.**
사유가 `dbt 를 못 돌렸다` 나 `run_results.json 을 못 읽었다` 로 시작하면 그렇다.
데이터 결함이 아니라 설치 · 접속 문제다.

## 3. 게이트가 못 돈 경우

VM 에서 직접 불러 본다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -c "
import os
from pathlib import Path
from bullet_in import dbt_gate
r = dbt_gate.run_gate(Path(\"dbt\"), os.environ[\"MARIADB_URL\"])
print(\"ran =\", r.ran, \"· error =\", r.error)
print(\"blocked =\", [(t.name, t.failures) for t in r.blocked])
print(\"warned  =\", [(t.name, t.failures) for t in r.warned])
"'
```

- **`dbt` 실행 파일이 없다** — 배포할 때 `uv sync` 를 안 돌렸다.
  `dbt-duckdb` 는 운영 의존성이라 `uv sync` 만으로 설치된다.
- **접속 실패** — `profiles.yml` 은 `.env` 의 `MARIADB_URL` 에서 파생한 다섯 변수를 읽는다.
  주소 · 포트 · 사용자 · 비밀번호 · 데이터베이스가 그 한 줄에서 나온다.
- **결과 파일을 못 읽었다** — 이번 회차가 판정을 안 남겼다는 뜻이다.
  `run_gate` 는 부르기 전에 직전 결과 파일을 지우므로, 파일이 없다는 것은 이번 회차의 침묵이다.
  **「아무것도 못 돌았다」 로 읽지 마라** — 2026-08-31 21:05 에는 노드 29개 중 22개를 통과시키고 중간에 끊겼다.
  어디까지 갔는지는 아래 §3.1 로 본다.

### 3.1. 저널로 원인이 안 나오면 dbt 자체 로그를 연다

게이트가 알림과 저널에 싣는 것은 **압축한 진단 한 줄**이다.
종료 코드와 stdout · stderr 의 마지막 몇 줄을 담지만, 그것으로 부족한 날이 있다.

**전문은 `~/bullet-in/dbt/logs/dbt.log` 에만 있다.**
dbt 가 스스로 남기고 회차마다 이어 쓰므로, 실패한 시각으로 잘라 읽는다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "grep -n '21:05:' ~/bullet-in/dbt/logs/dbt.log | tail -40"
```

- **어디까지 갔는지** 는 `N of M PASS` 줄로 읽는다.
- **로그가 오류 없이 뚝 끊기면** 예외로 죽은 것이 아니라 프로세스가 끊긴 것이다.
  종료 코드가 음수면 신호로 죽은 것이고, 그때는 커널 로그에서 OOM 을 확인한다.
- **`dbt/target/` 의 디렉터리 시각으로 실행 여부를 판단하지 마라.**
  dbt 는 같은 파일명을 덮어써서 디렉터리 mtime 이 안 바뀐다.
  2026-08-31 에 이 시각을 보고 「컴파일도 못 했다」 고 잘못 판단한 적이 있다.

### 3.2. 종료 코드가 -11 이면 코어 덤프를 연다

같은 자리 (`gold_slo_rollup` · 29개 중 23번째) 에서 세그폴트로 죽은 것이 2026-08-31 21:05 와 2026-09-03 03:06 두 번이다.
트레이스백이 없어 어느 라이브러리인지는 코어 덤프로만 짚을 수 있다.

**유닛은 코어를 남기게 되어 있다.**
`bullet-in.service` 의 `LimitCORE=infinity` 가 그 설정이다 (2026-09-03).
소프트 한도가 0 이면 커널이 코어를 안 쓰므로 이 줄이 없으면 아래가 전부 헛일이다.

**VM 에는 받는 쪽이 있어야 한다.**
Ubuntu 기본은 apport 가 `kernel.core_pattern` 을 쥐고 있고, 패키지가 아닌 실행 파일 (uv 가 만든 venv 의 python) 의 코어는 다루지 않는다.
한 번만 이렇게 바꾼다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'sudo apt-get install -y systemd-coredump && sudo systemctl disable --now apport &&
   sudo sysctl -p /usr/lib/sysctl.d/50-coredump.conf && cat /proc/sys/kernel/core_pattern'
```

`|/usr/lib/systemd/systemd-coredump ...` 가 나오면 됐다.
**받는 쪽은 2026-09-03 17:08 KST 에 준비됐다.**
설치 뒤 시험 세그폴트가 `coredumpctl list` 에 `SIGSEGV · present · 829 KB` 로 잡혔고 apport 는 `inactive` 다.
설치 출력에 커널 업그레이드 대기 (재부팅 권고) 와 docker 재시작 보류가 떠 있었는데, 둘 다 회차 사이에 재부팅하면 풀린다.

받는 쪽이 제대로 붙었는지는 일부러 죽여 본다 (운영 DB 를 안 건드린다).

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -c "ulimit -c unlimited; python3 -c \"import ctypes; ctypes.string_at(0)\""; coredumpctl list | tail -2'
```

**다음에 게이트가 -11 로 죽으면 이렇게 본다.**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'coredumpctl list | tail -5; coredumpctl info -1 | head -40'
```

`info` 의 스택 위쪽에 `duckdb` · `mysql_scanner` 같은 이름이 보이면 그것이 후보다.
코어 파일 자체는 `/var/lib/systemd/coredump/` 에 남고 기본 상한이 프로세스당 2 GB 라 디스크 (여유 22 GB · 2026-09-03) 를 함께 본다.

## 4. 고아 귀속이 늘었을 때

기사 신원 (`content_hash`) 이 갈릴 때 선수 귀속이 따라가지 못하면 고아가 된다.
어쩌다 그렇게 되는지와 고치는 법은 `docs/troubleshooting/2026-08-31-the-upsert-rewrote-the-hash-and-cut-the-links.md` 에 있다.

### 4.1. 지우기 전에 그 해시가 돌아올 수 있는지 본다

트윗은 같은 글이 회차마다 다르게 읽혀 해시가 **두 값 사이를 왕복한다.**
지금 고아인 귀속이 다음 회차에 되살아날 수 있다.
지우면 그 선수 페이지에서 그 기사가 영영 빠진다.

### 4.2. 회차 전후로 해시를 떠서 대조한다

로그만 보면 「안 뜬 것」 이 「코드가 안 돎」 인지 「이번엔 대상이 없었음」 인지 안 갈린다.

```bash
# 회차 전
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.hash_snapshot save'

# 회차 후
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.hash_snapshot diff'
```

나오는 것은 기사 수 · 고아 수 · 해시가 갈린 기사 목록이다.
해시가 갈렸는데 고아가 안 늘었으면 참조 이동이 제 일을 했다.

### 4.3. 그래도 지워야 한다면

되살아날 여지가 없다고 판단했을 때만 지운다.

```bash
# 대상 수를 먼저 세어 사용자에게 보인다 (DB 를 안 만진다)
uv run python -m bullet_in.migrate_url_identity --dry-run

# 승인을 받은 뒤에만
uv run python -m bullet_in.migrate_url_identity --apply --purge-orphans
```

- **`merge_groups` 와 `migrations` 가 0 인지 확인한다** — 0 이 아니면 이 실행이 고아 삭제 말고 다른 일도 한다.
- **지우기 전에 백업을 뜬다** (`uv run python -m bullet_in.backup_orphans`).
- **삭제 도구가 아닌 별도 조회로 검산한다** — `article_players` 총수가 지운 수만큼만 줄었는지 본다.

## 5. 배포를 다시 내보내는 법

원인을 고친 뒤 회차를 한 번 돌리면 게이트가 다시 판정한다.
통과하면 배포가 나간다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'sudo systemctl start --no-block bullet-in.service'
```

**회차가 끝났는지는 `ActiveState` 로 잰다.**
`systemctl is-active --quiet` 는 쓰면 안 된다 — `Type=oneshot` 유닛은 도는 동안 `activating` 이라 그 검사가 즉시 통과하고 직전 회차의 결과를 이번 회차 것으로 읽는다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'until [ "$(systemctl show bullet-in.service -p ActiveState --value)" != "activating" ]; do sleep 20; done;
   systemctl show bullet-in.service -p Result -p ExecMainStatus'
```

## 6. 임계를 올리고 싶을 때

**숫자만 올리지 않는다.**
설계 §2.3 의 표에 임계마다 그 값이 나온 관측이 적혀 있다.
근거 없이 올리면 게이트가 서서히 무력해진다.
그렇게 된 게이트는 있으나 마나다.

올려야 한다면 새 관측을 먼저 만들고 그 값을 근거 칸에 함께 적는다.

## 7. 이 게이트가 안 보는 것

- **CI 의 dbt 는 빈 표를 본다** — 값 이탈과 고아 귀속은 운영 회차에서만 드러난다.
- **차단이 배포를 막은 것은 운영에서 두 번이다** (2026-08-31 21:05 · 2026-09-03 03:06 · 둘 다 §3.2 의 세그폴트).
  둘 다 `ExecStartPost` 가 안 돌아 직전 화면이 남았고, 다음 회차 (자동 · 수동) 가 통과해 풀렸다.
  두 번째는 배포 뒤 저널을 `--since '10 min ago'` 로만 봐서 50분 전의 실패를 못 봤다 — 회차 목록 (`Starting` · `Finished` · `Failed`) 을 하루치로 먼저 본다.

