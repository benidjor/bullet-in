# 머지된 코드를 회차가 스스로 반영하고 판정하는 설계 (2026-09-03)

`main` 에 머지된 코드는 지금 사람이나 세션이 VM 에 들어가 `git pull` 을 해야 실서비스에 닿는다.
2026-09-03 하루에만 두 세션이 합쳐 여섯 번 손으로 배포했다.
이 설계는 그 손을 없애되, 「자동 pull 만 붙인다」 가 아니라 **전진 · 첫 회차 판정 · 롤백** 을 한 묶음으로 만든다.

안건 `2β` 의 설계다.
구현 계획은 별도 문서로 쓴다.

## 1. 지금 상태와 실측 (2026-09-03 19시대 KST)

### 1.1. 배포 경로는 유닛 하나 안에 있다

`infra/systemd/bullet-in.service` 가 회차 전체를 든다.

```
ExecStartPre   docker compose up -d --wait
ExecStart      uv run python -m bullet_in.run        (끝에 dbt 게이트)
ExecStartPost  infra/deploy-site.sh                  (wrangler pages deploy)
OnFailure      bullet-in-fail-notify@.service        (디스코드 사고 채널)
```

`ExecStart` 가 0 아닌 코드로 끝나면 systemd 는 `ExecStartPost` 를 돌리지 않는다.
그래서 게이트가 막은 회차는 배포가 나가지 않고 라이브는 직전 산출물 그대로다.

같은 체크아웃 `/home/ubuntu/bullet-in` 을 유닛 다섯이 읽는다.
회차 · 워치리스트 · 웨어하우스 · 백업 · 유지보수다.
어느 하나가 코드를 바꾸면 나머지는 각자 다음 실행에서 그 코드를 본다.

### 1.2. VM 의 상태

- `main` 브랜치 · 원격은 https · `8d52ba8` (PR #449 까지).
- 작업 트리에는 추적 안 되는 파일만 있다 (`.wrangler/` · 백필 로그 몇 개).
  `git merge --ff-only origin/main` 을 막는 것이 없다.
- `uv 0.11.29` · `wrangler 4.112.0` · `curl` 있음.
- 배포본에 커밋 표지가 없다.
  `render.py` · `run.py` 어디에도 커밋 해시를 싣는 자리가 없다.
- Cloudflare 쪽 `wrangler pages deployment list` 의 Source 열에는 배포 시점의 커밋이 남는다.
  「어느 커밋의 배포가 나갔나」 는 이미 조회할 수 있지만 「라이브가 그것을 서빙하나」 는 못 잰다.
- GitHub 저장소에 Actions secret 이 하나도 없다.
  Actions 에서 VM 으로 들어가는 길은 없다.

### 1.3. 착수 입력 넷 중 셋은 실측으로 답이 났다

리뷰 세션이 짚은 설계 입력 넷 (게이트 급사와 위반의 구분 · 설정은 코드와 함께 가지 않음 · `uv sync` 시점 · 배포본 확인은 `curl -L`) 을 실물에 대 봤다.

- **`uv sync` 는 따로 돌릴 필요가 없다.**
  uv 문서상 `uv run` 은 실행 전에 잠금 파일과 가상환경을 자동으로 맞춘다 (`--no-sync` · `--frozen` 을 주지 않는 한).
  유닛 다섯이 전부 `uv run` 으로 시작하므로 의존을 더한 PR 도 다음 실행에서 자동 설치된다.
  게이트 런북 §3 의 「`dbt` 실행 파일이 없다 = `uv sync` 를 안 돌렸다」 줄은 이 동작과 어긋난다.
  남는 실패 유형은 「동기화 자체가 실패하면」 하나다.
- **배포본은 VM 의 httpx 로도 받힌다.**
  `https://bullet-in.pages.dev/` 를 리다이렉트를 따라가며 받으면 200 · 1,109,123 바이트다.
  UA 를 붙이든 안 붙이든 같다.
  판정기는 httpx 를 쓰되 0바이트 · 비 200 · 표지 불일치를 전부 실패로 센다.
- **systemd 의 `ExecStopPost=` 가 판정 자리다.**
  `ExecStart` 가 실패해도 항상 돌고, `$SERVICE_RESULT` · `$EXIT_CODE` · `$EXIT_STATUS` 를 환경변수로 받는다 (VM 의 `man systemd.service` 로 확인).
- **게이트 급사와 위반은 지금 코드에서 안 갈린다.**
  `run.py` 에 명시적 종료 코드가 없고 게이트는 두 경우 모두 `SystemExit(1)` 이다.
  §8 에서 가른다.

## 2. 목표와 실패 유형

### 2.1. 목표

머지되면 다음 회차가 자동으로 그 코드로 돌고, 잘못되면 되돌아오며, 반영 여부를 사람이 안 봐도 안다.

### 2.2. 성공 조건보다 먼저 센 실패 유형

코드가 P 에서 N 으로 전진한 뒤 첫 회차가 끝나는 모양을 전부 세면 아홉이다.

| 번호 | 실패 | 지금 드러나는가 | 코드 탓인가 |
| --- | --- | --- | --- |
| F1 | pull 자체 실패 (네트워크 · ff 거부) | 없음 (지금은 사람이 pull) | 아니다 |
| F2 | 의존 동기화 실패 (`uv run` 이 설치에서 죽음) | `OnFailure` | 대체로 코드 |
| F3 | `run.py` 가 예외로 죽음 | `OnFailure` | 대체로 코드 (DB 다운도 같은 모양) |
| F4 | 게이트 위반 (`blocked > 0`) | 게이트 알림 | 갈린다 (새 코드가 나쁜 행을 썼거나 · 데이터 부채) |
| F5 | 게이트 급사 (`ran=False`) | 게이트 알림 | 종료 코드로 갈린다 (`-11` 은 2ν · `1` · `2` 는 코드 의심) |
| F6 | 배포 스크립트 실패 (HTML 50건 미만 · wrangler 오류) | `OnFailure` | 50건 미만이면 코드 · wrangler 면 인프라 |
| F7 | 배포는 성공인데 라이브가 안 바뀜 (캐시 · 0바이트) | 없음 | 아니다 |
| F8 | 새 설정이 `.env` 에 없어 조용히 반쯤 돎 | 없음 | 코드와 운영 사이 |
| F9 | 다 통과했는데 화면이 틀림 (조판 · 수치) | 사람 눈 | 코드 |

F7 · F8 · F9 가 「자동화가 조용히 지나칠 실패」 다.
지금은 사람이 로그를 보니 가끔 걸리고, 사람을 빼면 그 그물이 사라진다.
F9 는 자동 판정으로 못 잡으므로 수동 롤백 경로를 남기는 것이 설계에 들어간다.

## 3. 결정

### 3.1. 접근 — 회차 유닛 안에서 완결한다 (pull 식)

전진은 회차 시작에, 판정은 회차 끝에, 둘 다 `bullet-in.service` 안에서 돈다.
VM 은 밖으로 fetch 만 하고 새 자격 증명이 생기지 않는다.

기각한 안 셋이다.

- **자동 pull 만**
  — 잔여 안건 표가 이미 기각했다.
  잘못된 커밋이 머지되면 다음 회차가 조용히 그것을 배포하고 아무도 모른다.
- **GitHub Actions 가 VM 으로 미는 push 식**
  — 머지 몇 분 안에 회차를 한 번 더 돌리고 GitHub 에 배포 상태를 붙일 수 있다.
  대신 VM 개인키를 공개 저장소의 secret 에 두어야 하고, 머지마다 소스 접촉이 한 번 늘고, 러너가 30분을 기다리다 죽으면 VM 이 반쯤 전진한 채 남는다.
  판정 · 롤백은 어차피 VM 의 `ExecStopPost` 에 있어야 하므로 이 안은 pull 식을 만든 뒤 얹는 겹이지 대신하는 것이 아니다.
  제미나이 요금은 두 배가 되지 않는다.
  번역은 `title_ko IS NULL` 인 행만 보내므로 (`storage/mariadb.py` 의 `rows_missing_translation`) 추가 회차는 다음 회차 몫을 앞당길 뿐이다.
  더 붙는 것은 재작성 게이트에 재큐된 몇 건의 시도 한 번이다.
- **pull 식 + 10분마다 전진만 하는 타이머**
  — 다른 유닛도 빨리 새 코드를 보지만, 다른 유닛이 도는 중에 작업 트리가 바뀌고 전진과 판정이 다른 프로세스로 갈려 상태 파일이 필수가 된다.
  화면은 어차피 회차 때만 바뀌므로 얻는 것이 작다.

반영 지연의 잣대는 코드가 디스크에 닿는 시각이 아니라 화면이 바뀌는 시각이다.
배치 서비스에서는 둘이 다르고 뒤의 것만 통증이다.
급하면 지금 런북대로 `sudo systemctl start --no-block bullet-in.service` 를 한 번 치면 전진 · 판정 · 배포가 그 자리에서 돈다.
새 장치가 필요 없다.

### 3.2. 롤백은 넓게 발동한다

첫 회차가 어떤 이유로든 실패하면 직전 커밋으로 되돌린다.
예외는 dbt 세그폴트 (`-11` · 안건 2ν) 하나다.
그것은 코드 탓이 아님이 확정돼 있으니 되돌리지 않고 다음 회차에 다시 판정한다.

헛롤백의 비용은 「직전 코드로 한 회차 더 돌고 사람이 한 번 봄」 이라 오늘과 같다.
놓치는 것이 없다.
대신 DB 다운 · 데이터 부채로 실패한 회차도 코드를 되돌리므로, 알림이 원인을 단정하지 않는 문장을 갖는다 (§10).

좁게 발동하는 안 (코드 탓이 분명한 F2 · F3 · F6 만) 은 새 코드가 나쁜 행을 써서 게이트에 걸린 F4 를 못 되돌린다.
그 경우 여덟 회차가 같은 자리에서 막히고 사람이 되돌려야 한다.

### 3.3. 설정 그물은 목록 대조와 체크리스트 둘 다

코드 안에 필수 키 목록을 두고 전진 전에 VM 환경과 대조한다 (§5 · §9).
PR 템플릿에도 항목을 둔다.
목록 대조가 그물이고 체크리스트는 안내다.

## 4. 구성

### 4.1. 모듈 하나 · 명령 넷

`src/bullet_in/deploy.py` 에 둔다.

| 명령 | 언제 | 하는 일 |
| --- | --- | --- |
| `advance` | 회차 시작 (`ExecStartPre`) | fetch · 비교 · 사전 점검 · 체크아웃 (§5) |
| `judge` | 회차 끝 (`ExecStopPost`) | 유닛 결과로 판정 · 표지 대조 · 롤백 (§6) |
| `rollback` | 사람이 (F9) | 자동 롤백과 같은 함수 (§7) |
| `unblock <sha>` | 사람이 (헛롤백 뒤) | 차단 목록에서 뺀다 (§7) |

`preflight` 는 `advance` 가 새 코드로 부르는 내부 명령이다.

### 4.2. 상태 파일

`state/deploy.json` 하나다.
`state/` 는 이미 gitignore 돼 있고 `behavior_metrics.json` 이 같은 자리에 산다.

```json
{"current": "<sha>", "previous": "<sha>", "pending": true,
 "blocked": ["<sha>"], "advanced_at": "2026-09-04T00:03:12+00:00"}
```

- `pending` 이 참이면 「전진한 뒤 아직 판정 안 함」 이다.
- `blocked` 는 판정에 실패한 커밋의 목록이다.
  `origin/main` 이 그 해시에 머물러 있는 동안 전진하지 않는다.
  새 커밋이 위에 오면 (해시가 달라지면) 전진한다.

### 4.3. 유닛 변경 — 두 줄

```ini
ExecStartPre=/usr/bin/docker compose up -d --wait
ExecStartPre=/bin/sleep 10
ExecStartPre=-/home/ubuntu/.local/bin/uv run python -m bullet_in.deploy advance
ExecStart=/home/ubuntu/.local/bin/uv run python -m bullet_in.run --concurrency 8
ExecStartPost=/home/ubuntu/bullet-in/infra/deploy-site.sh
ExecStopPost=/home/ubuntu/.local/bin/uv run python -m bullet_in.deploy judge
```

`ExecStartPre=` 앞의 `-` 는 「이 단계가 실패해도 회차를 계속한다」 는 systemd 표기다.
`advance` 자체도 0 으로 끝나게 짜지만 예상 밖 예외까지 덮는다.
전진 실패로 회차를 잃지 않는 것이 이 설계의 첫 원칙이다.

나머지 유닛 넷은 그대로다.

### 4.4. 배포본 표지 — `site/build.json`

`run.py` 가 렌더할 때 한 파일을 더 쓴다.

```json
{"commit": "<git rev-parse HEAD>", "rendered_at": "<iso>", "run_id": "<uuid>"}
```

`deploy-site.sh` 는 `site/` 를 통째로 올리므로 따로 손댈 것이 없다.
판정기는 `https://bullet-in.pages.dev/build.json` 을 받아 `commit` 을 상태 파일의 `current` 와 대조한다.

## 5. 전진 (`advance`)

순서대로 돈다.
어느 단계에서 멈추든 회차는 현재 코드로 계속 돈다.

1. `git fetch origin`.
   실패하면 로그만 남기고 끝낸다 (일시적 네트워크 · 다음 회차에 다시).
2. `origin/main` 이 `HEAD` 와 같으면 끝낸다.
   대부분의 회차가 여기서 끝난다.
3. `origin/main` 이 `blocked` 에 있으면 끝낸다.
4. `git merge --ff-only origin/main`.
   거부되면 (VM 트리가 갈라짐) 사고 채널에 알리고 끝낸다.
   자동으로 `reset` 하지 않는다.
   갈라진 것은 사람이 만든 것이라 사람이 봐야 한다.
5. 새 코드로 사전 점검을 돈다.
   `uv run` 이 의존을 맞춘 뒤 `python -m bullet_in.deploy preflight` 를 부른다.
   하는 일은 둘이다.
   `bullet_in.run` 을 import 해 본다 (문법 · import 오류를 회차 전에 잡는다).
   `REQUIRED_ENV` (§9) 와 환경을 대조해 빠진 키를 센다.
6. 사전 점검이 실패하면 `git reset --hard <직전>` 으로 되돌리고, 그 커밋을 `blocked` 에 넣고, 사고 채널에 알린다.
   회차는 직전 코드로 돈다.
7. 통과하면 상태 파일에 `previous` · `current` · `pending: true` 를 쓰고 끝낸다.

사전 점검이 새 코드로 도는 것이 핵심이다.
필수 키 목록은 새 코드 안에 있으므로 (PR 이 키를 더하면 목록도 그 PR 에 실린다) 점검은 「이 코드가 필요로 하는 것」 을 그 코드에게 묻는 꼴이다.

## 6. 판정 (`judge`)

입력은 셋이다.
systemd 가 주는 `$SERVICE_RESULT` (success · exit-code · timeout · signal 등) 와 `$EXIT_STATUS` (주 프로세스 종료 코드), 상태 파일의 `pending`.

`pending` 이 아니면 아무것도 안 한다.
평소 회차 실패는 지금처럼 `OnFailure` 가 알린다.

`pending` 이면 표대로 처리한다.

| 유닛 결과 | 뜻 | 처리 |
| --- | --- | --- |
| `success` · 표지 일치 | 회차 · 게이트 · 배포 다 통과 | 「반영 완료」 알림 (리뷰 채널) · `pending` 해제 |
| `success` · 표지 불일치 | F7 · 코드 탓 아님 | 되돌리지 않음 · `pending` 해제 · 사고 채널 알림 |
| `exit-code` · 상태 `3` | 게이트 급사 (dbt 가 신호로 죽음 · 2ν) | 되돌리지 않음 · `pending` 유지 · 리뷰 채널에 「판정 보류 · 다음 회차에 다시」 |
| 그 밖 전부 (`exit-code` `1` · `timeout` · `signal` …) | F2 · F3 · F4 · F5 의 코드 의심 · F6 | 롤백 (§7) |

### 6.1. 표지 대조

`https://bullet-in.pages.dev/build.json` 을 httpx 로 받는다 (리다이렉트 따라감 · 타임아웃 20초).
최상위 도메인이 배포 직후 잠깐 옛 것을 돌려주는 일이 있어 20초 간격으로 3회까지 다시 받는다.
비 200 · 0바이트 · JSON 아님 · `commit` 불일치를 전부 「불일치」 로 센다.
빈 응답이 성공으로 읽힐 자리를 없애는 것이다.

### 6.2. 판정기 자신의 고장

`judge` 가 예외로 죽으면 사고 채널에 알리고 0 으로 끝낸다.
판정기가 유닛 결과를 바꾸면 안 된다.

## 7. 롤백

### 7.1. 자동 롤백이 하는 넷

- `git reset --hard <previous>`.
- `blocked` 에 `current` 를 넣는다.
- `pending` 을 해제한다.
- 사고 채널에 알린다 (§10).

의존은 다음 유닛 시작의 `uv run` 이 되돌린 잠금 파일에 맞춘다.

### 7.2. 수동 명령 둘 — 자동과 같은 함수

- `python -m bullet_in.deploy rollback`
  — 자동 롤백과 같은 함수를 부른다.
  F9 (다 통과했는데 화면이 틀림) 때 사람이 쓴다.
  화면 자체는 다음 회차가 직전 코드로 렌더해 덮거나, 급하면 Cloudflare 대시보드의 롤백을 쓴다.
- `python -m bullet_in.deploy unblock <sha>`
  — 롤백이 헛것이었을 때 (원인이 DB 다운이었음) 새 커밋 없이 같은 커밋을 다시 전진시킬 수 있게 차단을 푼다.
  JSON 을 손으로 고쳐도 되지만 런북에 명령 하나로 적는 편이 안전하다.

자동과 수동이 같은 함수라서 사람이 되돌린 기록과 기계가 되돌린 기록이 같은 상태 파일 · 같은 알림 형태로 남는다.
런북 스니펫이 코드와 갈려 사고 난 이 저장소의 이력 (재렌더 스니펫 표류 4회) 을 되풀이하지 않는 장치다.

### 7.3. 되돌리지 않는 것 셋

- **화면 (Cloudflare 배포본)**
  — 되돌릴 필요가 없다.
  첫 회차가 실패했으면 배포가 안 나갔고 라이브는 직전 회차 산출물 그대로다.
  화면을 되돌려야 하는 경우는 F9 하나이고 그것은 §7.2 의 수동 경로다.
- **DB**
  — 실패한 회차가 죽기 전에 Mongo · MariaDB 에 쓴 행은 남는다.
  수집 · 번역은 upsert 라 대부분 다음 회차가 덮지만, 새 코드가 잘못된 값을 썼다면 그것은 운영 데이터 정정이고 승인 사항이다.
- **`.env` · 설정**
  — 건드리지 않는다.
  사전 점검이 전진 전에 막으므로 설정이 코드보다 앞서 있는 상태만 생기고, 앞선 키는 무해하다.

롤백 순간 워치리스트 · 웨어하우스 유닛이 도는 중이면 그 프로세스는 이미 import 한 코드로 끝까지 돈다.
디스크만 바뀐다.

## 8. 게이트 종료 코드 — 하나만 가른다

`dbt_gate.GateResult` 에 `dbt_returncode: int | None` 을 더하고 `run_gate` 가 채운다.
`enforce_gate` 는 「`ran=False` 이고 dbt 가 신호로 죽음 (`dbt_returncode < 0`)」 일 때만 `SystemExit(3)` 으로 끝낸다.
나머지는 지금처럼 `1` 이다.

dbt 가 설정 오류로 `1` · `2` 를 내며 못 돈 경우는 코드 의심이 맞으므로 `1` 에 남는다.
판정기는 저널을 파싱하거나 결과 파일을 읽지 않고 `$EXIT_STATUS` 하나로 갈린다.
정보를 내는 쪽이 코드 하나를 더 쓰는 것이 읽는 쪽이 똑똑해지는 것보다 싸다.

## 9. 필수 키 목록과 PR 템플릿

### 9.1. `REQUIRED_ENV`

`deploy.py` 안의 상수 하나다.
잣대는 「없으면 유닛 다섯 중 하나가 조용히 반쯤 도는 키」 다.
죽는 키는 이미 `OnFailure` 가 잡으니 목록의 값어치는 조용한 쪽에 있다.

첫 목록은 VM `.env` 에 오늘 전부 있는 것만이다 (2026-09-03 확인).

| 키 | 없으면 |
| --- | --- |
| `MARIADB_URL` · `MONGO_URI` · `GEMINI_API_KEY` | 회차가 죽는다 (사전 점검이 회차 전에 잡게 하려고 둔다) |
| `CLOUDFLARE_API_TOKEN` · `CLOUDFLARE_ACCOUNT_ID` | 배포 스크립트가 죽는다 |
| `DISCORD_WEBHOOK_INCIDENT` · `DISCORD_WEBHOOK_REVIEW` | 알림이 조용히 안 나간다 (이 설계 전체가 알림에 기댄다) |
| `GA4_DATASET` | 행동 지표 갈래가 조용히 건너뛴다 (2026-09-03 실물 사례) |
| `ICEBERG_CATALOG_URI` · `ICEBERG_WAREHOUSE` · `GCS_BACKUP_BUCKET` | 웨어하우스 · 백업 유닛이 조용히 건너뛴다 |

선택으로 남기는 것은 `FMKOREA_PROXY` · `GUARDIAN_API_KEY` · `X_EMAIL` · `X_PASSWORD` · `X_USERNAME` · `MONGO_DB` (기본값 있음) · `GA_MEASUREMENT_ID` · `DISCORD_WEBHOOK_TREND` · `DISCORD_WEBHOOK_URL` 이다.
소스 하나가 빠지는 것은 기존 신선도 알림이 따로 잡는다.

### 9.2. PR 템플릿 §6 체크리스트에 한 줄

```
- [ ] 설정 키 — 새 환경변수가 있으면 REQUIRED_ENV 에 올리고 머지 전에 VM .env 에 넣음 (없으면 「해당 없음」)
```

`.claude/tools/check-pr-format.py` 는 체크리스트 줄을 검사 대상에서 빼므로 항목을 더해도 깨지지 않는다.

## 10. 알림

전진 한 번에 알림 한 번을 원칙으로 한다.
회차마다 내지 않는다.

| 사건 | 채널 | 내용 |
| --- | --- | --- |
| 반영 완료 | 리뷰 | P → N · 두 해시 · 표지 일치 · 회차 `run_id` |
| 전진 거부 (사전 점검) | 사고 | N · 사유 (import 오류 원문 한 줄 · 빠진 키 이름) · 「직전 코드로 회차를 돌렸다」 |
| ff 거부 | 사고 | 「VM 트리가 `origin/main` 과 갈라졌다」 · `git status` 요약 |
| 판정 보류 (종료 코드 3) | 리뷰 | 「게이트 급사 · 다음 회차에 다시 판정」 |
| 표지 불일치 | 사고 | 「배포는 나갔는데 라이브 표지가 다르다」 · 받은 것 (상태 코드 · 바이트 수 · `commit`) |
| 롤백 | 사고 | N → P · 두 해시 · 유닛 결과와 종료 코드 · 저널 명령 한 줄 · **「코드 탓이 아닐 수 있다 (DB 다운 · 데이터 부채도 같은 모양)」** · 「새 커밋이 오면 다시 전진 · 같은 커밋을 다시 보려면 `unblock`」 |

디스코드 서식은 추정으로 고르지 않고 한 번 쏴서 고른다.
문자열 테스트는 바깥 렌더러를 못 본다.

## 11. 검증

### 11.1. 단위 테스트

- 판정은 순수 함수로 만든다.
  `(유닛 결과 · 종료 코드 · 상태) → 행동` 이고 §6 표의 네 행과 「`pending` 아님」 을 전부 검사한다.
- 전진 · 롤백 · `unblock` 은 임시 git 저장소 (bare origin + clone) 를 만들어 실제 git 으로 검사한다.
  ff · 차단 목록 · 사전 점검 거부 · 되돌림 · `unblock` 각 하나씩이다.
- 표지 대조는 httpx 를 모킹해 200 일치 · 0바이트 · 불일치 · 3회 재시도를 본다.
- 게이트 종료 코드 3 은 `test_dbt_gate.py` 에 신호 종료 케이스를 더해 본다.

### 11.2. 라이브 리허설 (구현 세션)

이 기능을 싣는 PR 자체는 마지막 손배포로 올린다.
올린 뒤 셋을 실제로 돌린다.

1. 알려진 정상 쌍 (P · N) 에 대해 `rollback` 수동 명령을 친다.
   되돌림 · 사고 채널 알림 · `blocked` 에 N 이 들어간 것을 본다.
2. `unblock N` 을 친다.
3. 다음 회차를 기다리거나 손으로 시작한다.
   자동 전진 · 「반영 완료」 알림 · `build.json` 의 `commit` 이 N 인 것을 본다.

이것으로 롤백 함수 · 전진 · 판정 성공 경로가 라이브로 한 번씩 돈다.
깨진 코드를 `main` 에 올리지 않고도 되돌림 경로가 실제 git · 실제 알림으로 돈다.

### 11.3. 라이브로 못 재는 것

- 종료 코드 3 (급사 보류) 경로는 2ν 가 다시 날 때까지 단위 테스트뿐이다.
- 사전 점검 거부 경로는 일부러 깨진 커밋을 `main` 에 올리지 않는 한 단위 테스트뿐이다.
- 표지 불일치 경로도 같다.

## 12. 범위 밖 · 함께 바뀌는 것

범위 밖은 다섯이다.
GitHub Actions 연동 (대상이 늘거나 머지 빈도가 오르면 이 설계 위에 얹는다) · 화면 오류 자동 감지 (F9) · DB 되돌림 · 2ν 의 원인 · 다른 유닛의 개별 판정.

계획서가 함께 고쳐야 할 문서는 다음이다.

- `.github/workflows/ci.yml` 의 「배포와 운영 회차 — VM 반영 · 재렌더 · 화면 확인은 사람의 몫」 요약.
- `docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md` §2 「코드 반영」
  — 자동으로 바뀌고, 급하면 회차를 손으로 시작한다는 줄로.
- `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` §3 의 `uv sync` 줄 정정.
- `CLAUDE.md` 의 스케줄 문단에 전진 · 판정 한 줄.
- 세션 규율 메모리 「머지 뒤 배포까지 묻지 않는다」
  — 배포가 회차 몫이 되므로 세션 몫은 「반영 완료 알림을 확인한다」 로.
- 새 런북 하나
  — 알림 여섯 가지를 받았을 때 각각 무엇을 보고 무엇을 치는지 (`rollback` · `unblock` · 회차 손 시작).

2026-09-04 스펙 (`docs/superpowers/specs/2026-09-04-airflow-migration-design.md`) 이 전진 · 판정을 systemd 유닛의 `ExecStartPre` · `ExecStopPost` 에서 DAG `bullet_in_cycle` 의 첫 · 끝 태스크로 옮겼다.
입력만 바뀌고 (유닛 결과 · 종료 코드 → 앞 태스크 일곱의 상태) 판정 규칙 (`decide`) 은 그대로다.

## 13. 참조

- 잔여 안건 표의 `2β` 행 · 트랙 메모리 `deploy-and-confirm-automation-track`.
- `docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md`
  — 게이트가 배포를 세우는 구조.
- `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md`
  — 급사 · 위반의 구분과 코어 덤프.
- `docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md`
  — 이 설계가 없애는 손 절차.
- `docs/troubleshooting/2026-09-02-the-unit-line-that-never-took-effect.md`
  — `EnvironmentFile=` 이 `Environment=` 를 덮는 systemd 동작.
