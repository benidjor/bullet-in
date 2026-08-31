# 운영 DB 백업 · 복구 런북 (2026-09-01)

기사 · 선수 명단 · 선수 귀속 · 회차 기록 · 수집 원본을 매일 GCS 로 내보내고, 필요할 때 되살리는 절차.
2026-09-01 까지 이 서비스에는 백업이 하나도 없었다
— 없다는 것을 확인한 기록은 `docs/troubleshooting/2026-09-01-looking-for-a-restore-procedure-and-finding-no-backup.md` 다.

**이 문서는 백업 절차와 복구 절차를 한 곳에 둔다.**
되살려 본 적 없는 백업은 백업이 아니다.
만드는 쪽만 적어 두면 복구가 되는지 확인하지 않은 채 안전하다고 믿게 된다.

## 1. 무엇을 지키나

| 자산 | 실제 부피 | 백업 방식 |
| --- | --- | --- |
| MariaDB `bulletin` 6표 | 논리 덤프 gzip 2,291,503 바이트 | `mariadb-dump --single-transaction --skip-extended-insert` |
| MongoDB `bulletin.raw_items` | 아카이브 gzip 1,734,975 바이트 | `mongodump --archive --gzip` |
| `.env` · `x_cookies.json` | — | **대상 아님** (로컬 맥에 사본이 있다) |
| 코드 · 문서 | — | **대상 아님** (GitHub) |

부피는 2026-09-01 05:15 KST 에 VM 에서 직접 쟀다.
1회분 합계가 약 4.0 MB 다.
`articles` 증가 속도가 하루 15 ~ 17행이라 1년 뒤에도 1회분이 약 25 MB 다.

**도커 볼륨을 통째로 뜨지 않는다.**
볼륨은 739 MB 인데 그 안의 실제 데이터가 4 MB 다
— 나머지는 WiredTiger 와 InnoDB 가 미리 잡아 둔 파일이다.
논리 덤프라야 다른 호스트 · 다른 DB 버전에 넣을 수 있다는 것이 더 큰 이유다.

## 2. 언제 · 무엇이 도나

- `bullet-in-backup.timer` 가 매일 01:30 UTC (KST 10:30) 에 한 번 깨운다.
- 회차는 3시간마다 00/3시 UTC 에 돌고 감시 배치는 10 · 13 · 16 · 19시 30분 UTC 에 돈다
— 01:30 UTC 는 그 사이의 빈 시각이다.
- `Persistent=true` 를 두었다
— VM 이 꺼졌다 켜지면 놓친 백업을 한 번 돌린다.
- 유닛이 실패하면 `OnFailure=bullet-in-fail-notify@%n.service` 가 걸려 기존 Discord 사고 채널로 알린다
— 알림 경로를 새로 만들지 않았다.

세대는 날짜가 정한다.

| 세대 | 언제 | 보관 | 벌 수 |
| --- | --- | --- | --- |
| `daily/` | 매일 | 8일 | 7 ~ 8 |
| `weekly/` | 일요일 | 35일 | 4 ~ 5 |
| `monthly/` | 매달 1일 | 400일 | 12 ~ 13 |

일요일과 매달 1일에는 같은 파일을 두세 번 올린다.
1회분이 4 MB 라 중복으로 드는 비용이 얼마 안 되고, 그 대신 보관 기간을 GCS 수명주기 규칙 셋으로 끝낼 수 있다.

**세대를 가르는 날짜는 UTC 기준이다.**
타이머가 01:30 UTC 에 돌 때는 UTC 날짜와 KST 날짜가 같으므로 평소에는 헷갈릴 일이 없다.
다만 KST 로 자정과 오전 9시 사이에 손으로 돌리면 UTC 로는 아직 전날이라, KST 1일 새벽에 돌린 백업은 `monthly/` 로 안 간다.

## 3. 어디에 쌓이나

```
gs://bullet-in-backup-prod/daily/2026-09-01T01-30-00Z/mariadb.sql.gz
gs://bullet-in-backup-prod/daily/2026-09-01T01-30-00Z/mongo.archive.gz
gs://bullet-in-backup-prod/daily/2026-09-01T01-30-00Z/manifest.json
```

`manifest.json` 이 복구 검증의 유일한 기준이다.
백업 시점의 표별 행 수 · `raw_items` 건수 · 덤프 부피 · 그때의 git 커밋을 담는다.

**그 행 수는 운영 DB 에 물어서 채우지 않는다.**
덤프 파일 안의 INSERT 를 세고 (`--skip-extended-insert` 를 쓰는 이유가 이것이다), `raw_items` 건수는 mongodump 가 stderr 에 찍는 값을 읽는다.
운영 DB 에 다시 물으면 덤프를 뜬 시점과 행 수를 센 시점 사이에 회차가 끼어들 수 있다.
그러면 매니페스트가 덤프 파일과 어긋나서 복구 대조가 멀쩡한 백업을 실패로 찍는다.
INSERT 를 한 줄씩 쓰는 대가는 압축 뒤 0.2% 다 (2,287,679 → 2,291,503 바이트).

**VM 의 서비스 계정에는 삭제 권한이 없다.**
`roles/storage.objectCreator` 와 `roles/storage.objectViewer` 둘만 준다
— 지우는 일은 GCS 수명주기 규칙이 하므로 VM 이 통째로 털려도 과거 백업은 남는다.

## 4. 처음 세팅하는 절차

이 절의 작업은 한 번만 한다.
**2026-09-01 에 이미 실행했으므로 프로젝트 · 버킷 · 서비스 계정 · 키가 다 있다.**
아래는 처음부터 다시 만들어야 할 때 쓰는 기록이고, 평소에는 §5 · §6 으로 간다.

### 4.1 GCP 프로젝트 · 버킷

```bash
export PATH="/opt/homebrew/share/google-cloud-sdk/bin:$PATH"
gcloud auth login
gcloud projects create bullet-in-backup --name="bullet-in backup"
gcloud billing projects link bullet-in-backup --billing-account=<결제계정>
gcloud services enable storage.googleapis.com --project=bullet-in-backup
gcloud storage buckets create gs://bullet-in-backup-prod \
  --project=bullet-in-backup --location=us-central1 \
  --uniform-bucket-level-access --default-storage-class=STANDARD
```

리전을 `us-central1` 로 고정한다
— GCS 무료 5 GB 는 `us-east1` · `us-west1` · `us-central1` 에서만 나온다.
무료 한도는 프로젝트가 아니라 **결제 계정** 단위라, 프로젝트를 새로 파도 한도가 늘지 않는다.

### 4.2 수명주기 규칙

```bash
gcloud storage buckets update gs://bullet-in-backup-prod --lifecycle-file=infra/backup/lifecycle.json
```

규칙이 없는 세대가 생기면 그 세대는 영원히 안 지워져 무료 한도를 잠식한다.
`tests/test_backup.py` 가 세대 셋에 모두 보관 일수가 있는지 검사한다.

### 4.3 서비스 계정 · 키

```bash
gcloud iam service-accounts create bullet-in-backup \
  --project=bullet-in-backup --display-name="bullet-in backup writer"
gcloud storage buckets add-iam-policy-binding gs://bullet-in-backup-prod \
  --member=serviceAccount:bullet-in-backup@bullet-in-backup.iam.gserviceaccount.com \
  --role=roles/storage.objectCreator
gcloud storage buckets add-iam-policy-binding gs://bullet-in-backup-prod \
  --member=serviceAccount:bullet-in-backup@bullet-in-backup.iam.gserviceaccount.com \
  --role=roles/storage.objectViewer
gcloud iam service-accounts keys create /tmp/bullet-in-backup.json \
  --iam-account=bullet-in-backup@bullet-in-backup.iam.gserviceaccount.com
```

### 4.4 VM 에 얹기

```bash
scp -i ~/.ssh/seoulnow_deploy /tmp/bullet-in-backup.json ubuntu@155.248.164.17:/home/ubuntu/.bullet-in-backup.json
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'chmod 600 /home/ubuntu/.bullet-in-backup.json'
```

`.env` 에 두 줄을 더한다.

```
GCS_BACKUP_BUCKET=bullet-in-backup-prod
GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-backup.json
```

키 파일을 올린 뒤 로컬 사본은 지운다.
저장소에는 절대 넣지 않는다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cd ~/bullet-in && git pull && ./infra/systemd/install-units.sh'
```

## 5. 백업을 손으로 한 번 돌리기

정기 배포 직전 · 운영 데이터를 고치기 직전처럼 지금 당장 한 벌이 필요할 때 쓴다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a && \
   /home/ubuntu/.local/bin/uv run python -m bullet_in.backup run'
```

쌓인 백업을 세려면 이렇게 한다.

```bash
... python -m bullet_in.backup list --generation daily
```

**회차가 도는 중에 돌려도 된다.**
`--single-transaction` 이라 표를 안 잠근다.
그래도 회차 중에 뜨면 그 회차가 데이터를 쓰는 도중의 상태가 담긴다.
급하지 않으면 `systemctl show bullet-in.service -p ActiveState --value` 로 `inactive` 를 확인하고 돌린다.

## 6. 복구

### 6.1 연습 (운영을 안 건드린다)

**분기마다 한 번은 이것을 돌린다.**
백업이 도는 것과 되살아나는 것은 다른 사실이다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a && \
   /home/ubuntu/.local/bin/uv run python -m bullet_in.backup restore \
     --prefix daily/<시각> --target-db bulletin_restore_check'
```

`--target-db` 에 기본값을 두지 않았다
— 되살릴 자리를 매번 손으로 적게 해서 연습이 운영을 덮는 일을 막는다.

명령이 표마다 「기대 · 복구」 를 나란히 찍는다.
하나라도 어긋나면 0 이 아닌 종료 코드로 끝난다.
연습이 끝나면 연습용 DB 를 지운다.

```bash
docker exec bullet-in-mariadb-1 mariadb -uroot -pbulletin \
  -e 'DROP DATABASE bulletin_restore_check'
docker exec bullet-in-mongo-1 mongosh --quiet \
  --eval 'db.getSiblingDB("bulletin_restore_check").dropDatabase()'
```

### 6.2 실제 복구 (운영을 덮는다)

**이것은 되돌릴 수 없다.**
`--target-db bulletin` 을 적는 순간 지금 운영 DB 가 지워지고 백업 시점으로 바뀐다.

밟는 순서는 이렇다.

- 타이머를 먼저 멈춘다
— `sudo systemctl stop bullet-in.timer bullet-in-watchlist.timer`.
- 지금 DB 가 조금이라도 살아 있으면 **먼저 §5 로 한 벌 뜬다**
— 복구가 잘못돼도 돌아올 자리가 생긴다.
- 되살릴 백업을 §5 의 `list` 로 고른다.
- `--target-db bulletin` 으로 §6.1 의 명령을 돌린다.
- 대조가 통과하면 타이머를 다시 켜고 한 회차를 지켜본다.

**복구 뒤 첫 회차는 반드시 눈으로 본다.**
`content_hash` 와 URL UNIQUE 로 중복이 막히므로 재수집이 행을 늘리지는 않는다.
다만 백업 시점 이후에 들어왔던 기사는 소스에서 이미 내려갔으면 다시 안 들어온다.

## 7. 복구 연습 기록

| 날짜 | 되살린 백업 | 대상 | 결과 |
| --- | --- | --- | --- |
| 2026-09-01 05:40 KST | `daily/2026-08-31T20-38-41Z` | `bulletin_restore_check` | **통과** — 6표와 `raw_items` 까지 7개 대조가 전부 일치 |

첫 연습에서 대조한 값은 `article_players` 3,492 · `articles` 969 · `pipeline_runs` 343 · `players` 538 · `source_freshness` 2,675 · `sources` 0 · `raw_items` 1,634 이었다.
연습이 끝난 뒤 연습용 DB 둘을 지웠고, 운영 DB 는 건드리지 않았다.

## 8. 이 설계가 일부러 안 한 것

- **볼륨 스냅샷 · Oracle 블록 볼륨 백업**
— 같은 클라우드 계정 안이라 계정이 잠기면 VM 과 함께 잃는다.
- **회차마다 백업**
— 최악의 손실이 24시간치 (약 17행) 이고, 그 대신 객체 수와 검증 대상이 8배가 된다.
- **암호화 · 압축의 이중화**
— GCS 가 저장 시 암호화하고 덤프는 이미 gzip 이다.
- **`.env` 백업**
— 로컬 맥에 사본이 있고, 비밀값을 클라우드에 한 벌 더 두는 쪽이 손해가 크다.
- **새 파이썬 패키지**
— `google-auth` 와 `httpx` 가 이미 의존성에 들어 있어서 gcloud SDK 를 VM 에 얹지 않았다.

## 관련

- 백업이 없다는 것을 확인한 기록 = `docs/troubleshooting/2026-09-01-looking-for-a-restore-procedure-and-finding-no-backup.md`
- VM 구성 = `docs/runbook/2026-07-20-vm-cohost-bootstrap.md`
- 운영 절차 전반 = `docs/runbook/2026-05-27-daily-operations.md`
- 조용히 통과하는 검증 = `docs/troubleshooting/2026-08-15-verification-that-silently-passes.md`

