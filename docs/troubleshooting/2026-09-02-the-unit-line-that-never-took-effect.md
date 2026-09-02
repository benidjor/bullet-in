# 유닛에 적은 자격 한 줄이 한 번도 안 걸렸다 (2026-09-02)

변경 이력 적재 유닛에 GCP 자격을 지정하는 줄을 넣었는데 실행에서 무시됐다.
손으로 돌린 검증 넷이 전부 통과했고 유닛으로 돌린 첫 실행에서야 드러났다.

## 1. 무엇이 일어났나

VM 의 `.env` 에는 백업용 자격이 적혀 있다.

```
GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-backup.json
```

변경 이력 쪽은 다른 계정을 써야 한다.
백업 계정에는 객체를 지울 권한이 없는데, 유지보수가 컴팩션과 스냅샷 만료로 파일을 지우기 때문이다.

그래서 유닛에 이렇게 적었다.

```ini
EnvironmentFile=/home/ubuntu/bullet-in/.env
Environment=GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json
ExecStart=/home/ubuntu/.local/bin/uv run python -m bullet_in.warehouse load
```

`sudo systemctl start` 를 부르니 이렇게 죽었다.

```
pyiceberg.exceptions.ForbiddenError: RESTError 403
"message": "Caller does not have required permission to use project 601205180150."
"reason": "USER_PROJECT_DENIED"
```

## 2. 신원부터 확정했다

오류 문구만 보면 권한 설정이 모자란 것처럼 읽힌다.
그래서 **어느 계정으로 붙었는지**를 먼저 갈랐다.

같은 명령을 백업 키로 손수 돌려 보았다.

```bash
ssh ... 'env GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-backup.json \
  ICEBERG_CATALOG_URI=... ICEBERG_WAREHOUSE=... \
  uv run --project /home/ubuntu/bullet-in python -m bullet_in.warehouse show'
```

똑같은 403 이 났다.
변경 이력 키로 돌리면 정상으로 끝난다.

**즉 권한이 모자란 것이 아니라 유닛이 백업 계정으로 붙어 있었다.**
추측으로 넘어가지 않고 대조로 확정한 자리다.

## 3. 왜 그런가

systemd 문서가 `EnvironmentFile=` 을 이렇게 설명한다.

> Settings from these files override settings made with `Environment=`.

**줄 순서와 상관없다.**
`Environment=` 를 뒤에 적어도 파일에서 읽은 값이 나중에 들어와 앞의 값을 덮어쓴다.

`Environment=` 는 유닛을 읽을 때 정해지는 값이고 `EnvironmentFile=` 은 프로세스를 띄우기 직전에 읽는다.
읽는 시점이 늦은 쪽이 최종 값이 된다.

## 4. 어떻게 고쳤나

`ExecStart=` 를 `/usr/bin/env` 로 감쌌다.

```ini
EnvironmentFile=/home/ubuntu/bullet-in/.env
ExecStart=/usr/bin/env GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json \
  /home/ubuntu/.local/bin/uv run python -m bullet_in.warehouse load
```

`env` 는 프로세스를 띄우는 순간에 값을 넣으므로 이 순서를 타지 않는다.
`Environment=` 줄은 지웠다.
남겨 두면 동작하는 것처럼 읽힌다.

### 다른 길 둘을 버린 이유

- **`.env` 에서 그 줄을 빼고 유닛마다 지정** — 백업 유닛까지 손대야 하고 `.env` 를 직접 읽어 쓰는 운영 절차에서 자격이 빠진다.
- **`EnvironmentFile=` 을 하나 더 추가** — 파일끼리는 나중에 적은 쪽이 앞의 값을 덮어쓰므로 동작은 한다. 다만 버전 관리 밖 파일이 하나 더 늘고 그 존재를 아는 사람만 고칠 수 있다.

## 5. 왜 검증에서 안 걸렸나

이 회차의 검증이 넷이었고 전부 통과했다.

| 검증 | 어떻게 돌렸나 |
| --- | --- |
| 접속 스모크 | 환경변수를 명령줄에 직접 얹음 |
| 첫 적재 | 같음 |
| 멱등 | 같음 |
| 유지보수 | 같음 |

**넷 다 `.env` 를 아예 안 읽는 경로다.**
`EnvironmentFile=` 이 나오지 않으니 덮어쓰기가 일어날 자리가 없었다.

유닛을 새로 들이는 변경인데 **유닛으로는 한 번도 안 돌린 채 「검증 완료」 라고 적었다.**

## 6. 다음에 어떻게 할까

- **유닛을 도입하거나 고치는 변경은 `systemctl start` 로 한 번 돌려야 검증이 끝난다.** 손으로 돌린 명령이 통과한 것은 그 명령이 통과한다는 뜻일 뿐이다.
- **자격이나 설정이 여러 곳에서 오면 실제 값을 실행 경로에서 확인한다.** `systemctl show <유닛> -p Environment` 는 유닛 파일의 `Environment=` 만 보여 주고 `EnvironmentFile=` 의 결과는 안 보여 준다. 이 명령으로는 문제를 못 본다.
- **오류 문구가 가리키는 곳부터 고치지 않는다.** 여기서는 「권한을 더 주라」 는 안내가 붙어 있었는데, 그대로 따랐으면 백업 계정에 레이크하우스 권한을 주는 엉뚱한 수정이 됐다.

## 7. 함께 볼 것

- 운영 절차 — `docs/runbook/2026-09-02-warehouse-history-load.md`
- 유닛 원본 — `infra/systemd/bullet-in-warehouse.service` · `infra/systemd/bullet-in-warehouse-maint.service`
- 배포 뒤 유닛이 저장소와 갈릴 수 있다 — `git pull` 로 작업 트리가 갱신돼도 `/etc/systemd/system` 은 `install-units.sh` 를 돌려야 따라온다.
