# 변경 이력 적재 운영 절차 (2026-09-02)

운영 마트의 `articles` · `players` · `article_players` 는 덮어쓰기로 갱신되어 이전 값이 사라진다.
그 값을 GCS 위의 Iceberg 테이블로 옮겨 두는 타이머가 둘 있다.
여기서는 그 둘을 어떻게 보고 어떻게 고치는지 적는다.
설계는 `docs/superpowers/specs/2026-09-02-history-lakehouse-design.md` 에 있다.

## 무엇이 언제 도는가

| 유닛 | 시각 | 하는 일 |
| --- | --- | --- |
| `bullet-in-warehouse.timer` | 3시간 간격 · KST 00 · 03 · 06 · 09 · 12 · 15 · 18 · 21시 20분 | 변경분 적재 · 하루 첫 회차에 전량 스냅샷 |
| `bullet-in-warehouse-maint.timer` | 하루 1회 · KST 11시 40분 | 컴팩션 · 스냅샷 만료 · 오래된 파티션 솎기 |

적재는 회차보다 18분 뒤에 돈다.
회차가 마트를 다 쓴 뒤에 읽으려고 그렇게 뒀다.
회차의 임계 경로 밖이라 여기서 실패해도 배포는 막히지 않는다.

유지보수를 11시 40분에 둔 것은 그 시각이 백업과 회차 사이의 빈 자리이기 때문이다.

## 자원과 자격

| 항목 | 값 |
| --- | --- |
| GCP 프로젝트 | `bullet-in-lakehouse` |
| 버킷 | `gs://bullet-in-lakehouse-prod` · `us-central1` |
| 카탈로그 | `bullet-in-lakehouse-prod` · `gcs-bucket` 형 |
| 서비스 계정 | `bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com` |
| 키 | `/home/ubuntu/.bullet-in-lakehouse.json` |

`.env` 의 `GOOGLE_APPLICATION_CREDENTIALS` 는 백업 계정을 가리킨다.
백업 계정에는 객체를 지울 권한이 없다.
유지보수는 파일을 지워야 하므로 변경 이력 유닛 둘만 자기 계정을 쓴다.
자격을 옮길 일이 생기면 `.env` 가 아니라 두 유닛의 `ExecStart=` 를 고친다.

**`Environment=` 로는 못 덮는다.**
systemd 가 `EnvironmentFile=` 을 나중에 읽어 `Environment=` 로 지정한 값을 덮어쓰기 때문이다.
줄 순서를 바꿔도 결과가 같아서 `ExecStart=` 를 `/usr/bin/env` 로 감쌌다.
이것을 모르고 `Environment=` 로 적었다가 유닛이 백업 계정으로 붙어 403 `USER_PROJECT_DENIED` 가 났다.

## 자원을 처음부터 다시 만들 때

카탈로그를 만드는 명령이 헷갈리는 자리라 적어 둔다.

**REST API 로는 못 만든다.**
`https://biglake.googleapis.com/v1/projects/.../catalogs` 에 POST 하면 400 이 온다.
그 v1 API 는 Hive 계열 메타스토어라 Iceberg 카탈로그를 만드는 메서드가 없다.

전용 `gcloud` 명령을 쓴다.

```bash
gcloud projects create bullet-in-lakehouse --name="bullet-in lakehouse"
gcloud billing projects link bullet-in-lakehouse --billing-account=01E3C1-098D9D-58E612
gcloud services enable biglake.googleapis.com storage.googleapis.com --project=bullet-in-lakehouse

gcloud storage buckets create gs://bullet-in-lakehouse-prod \
  --project=bullet-in-lakehouse --location=us-central1 --uniform-bucket-level-access

gcloud biglake iceberg catalogs create bullet-in-lakehouse-prod \
  --catalog-type=gcs-bucket --project=bullet-in-lakehouse
```

**카탈로그 종류가 `warehouse` 값의 형태를 정한다.**

| 종류 | `ICEBERG_WAREHOUSE` |
| --- | --- |
| `gcs-bucket` | `gs://<버킷 이름>` · 카탈로그 이름이 곧 버킷 이름이다 |
| `biglake` (= `lakehouse`) | `bl://projects/<프로젝트>/catalogs/<카탈로그>` |

우리는 `gcs-bucket` 을 쓴다.
버킷 하나만 쓰므로 다중 버킷 매핑의 이점이 없고, `warehouse.py` 가 `gs://` 를 그대로 받는다.

권한은 이렇게 준다.

```bash
gcloud iam service-accounts create bullet-in-lakehouse \
  --project=bullet-in-lakehouse --display-name="bullet-in lakehouse writer"

gcloud projects add-iam-policy-binding bullet-in-lakehouse \
  --member="serviceAccount:bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com" \
  --role="roles/biglake.editor"

gcloud storage buckets add-iam-policy-binding gs://bullet-in-lakehouse-prod \
  --member="serviceAccount:bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com" \
  --role="roles/storage.objectUser"
```

공식 문서는 테이블 생성에 `roles/biglake.admin` 이 필요하다고 적었으나 `roles/biglake.editor` 로 충분하다.
그 역할의 권한 목록에 `tables.create` 와 `namespaces.create` 가 들어 있다 (`gcloud iam roles describe roles/biglake.editor` 로 확인).

**키는 저장소 밖에 둔다.**
백업 키와 같은 관례로 `/home/ubuntu/.bullet-in-lakehouse.json` 에 놓고 `chmod 600` 을 건다.

접속만 확인하려면 다음이 `prefix` 를 돌려주면 된다.

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://biglake.googleapis.com/iceberg/v1/restcatalog/v1/config?warehouse=gs://bullet-in-lakehouse-prod"
```

## 손으로 돌리고 쌓인 것을 보는 법

타이머를 기다리지 않고 한 번 돌리려면 다음을 부른다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "sudo systemctl start bullet-in-warehouse.service"
```

쌓인 내용을 보려면 다음을 부른다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "set -a; . /home/ubuntu/bullet-in/.env; set +a; \
   GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json \
   /home/ubuntu/.local/bin/uv run --project /home/ubuntu/bullet-in \
   python -m bullet_in.warehouse show"
```

표마다 행 수 · 데이터 파일 수 · 부피 · 남은 Iceberg 스냅샷 수가 한 줄로 나온다.

## 적재가 실패했을 때 보는 순서

셋을 순서대로 본다.
앞의 것이 멀쩡한데 뒤에서 죽는 경우가 대부분이라 순서를 지키는 편이 빠르다.

1. **유닛 상태** — `systemctl status bullet-in-warehouse.service --no-pager -l` 로 종료 코드와 마지막 로그를 본다.
2. **인증** — 로그에 `Using Google Default Application Credentials` 가 안 보이면 키 경로가 틀렸다.
   유닛의 `Environment=` 줄과 `/home/ubuntu/.bullet-in-lakehouse.json` 의 존재를 확인한다.
3. **카탈로그 접속** — 다음이 `prefix` 를 돌려주면 주소와 권한은 살아 있다.

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://biglake.googleapis.com/iceberg/v1/restcatalog/v1/config?warehouse=gs://bullet-in-lakehouse-prod"
```

적재가 한 회차 빠져도 다음 회차가 받아 준다.
워터마크는 실제로 가져온 행에서만 앞으로 가므로 실패한 구간은 다음번에 함께 딸려 온다.

## 비용을 어떻게 확인하는가

**가격표 웹페이지를 보지 않는다.**
카탈로그 항목은 거기 아예 없고 `cloud.google.com/biglake/pricing` 은 404 다.
조회 절차의 정본은 `docs/runbook/2026-09-02-reading-gcp-prices-from-the-billing-catalog.md` 다.

실제 청구는 GCP 결제 보고서에서 두 기준으로 각각 본다.

- **서비스 기준** — `Cloud Storage` 와 `BigLake` 가 따로 잡힌다.
  Class A 무료 5,000회가 둘에 각각 붙으므로 하나로 합쳐 세면 안 된다.
- **프로젝트 기준** — `bullet-in-lakehouse` 만 떼어 본다.
  Gemini 축 (안건 ξ) 과 섞이지 않게 프로젝트를 새로 판 이유가 이것이다.

**`BigLake Table Management` SKU 가 0인지 반드시 확인한다.**
`us-central1` 에서 시간당 165.99 KRW 라 한 달 상시면 12만원이 넘는다.
관리형 Iceberg 테이블을 만들지 않는 한 붙지 않으므로 0이 아니면 누군가 관리형 테이블을 만든 것이다.

## 스냅샷은 카탈로그가 하나만 남긴다 (2026-09-03 실측으로 고쳐 씀)

처음에는 「스냅샷이 하나에 약 1,015 바이트씩 `metadata.json` 에 쌓여 1 MB 한도에 닿으면 약 124일에 커밋이 실패한다」 고 적었다.
그 전제는 틀렸다.
`articles_changes` 를 열어 보니 커밋 8회에 `snapshots` 1 · `snapshot-log` 8 이다.
우리는 만료 속성을 걸지 않았는데도 그렇고, Google 문서에서 그 정책을 설명하는 문장은 못 찾았다.

그래서 이렇게 읽는다.

- `show` 의 스냅샷 수는 늘 1 이고, 유지보수의 「스냅샷 만료 — 1개에서 1개로」 는 정상이다
- 타임 트래블 · 스냅샷 롤백은 이 카탈로그에서 못 쓴다 — 이력은 데이터 행 (변경분 표 + 일일 스냅샷 파티션) 에만 있다
- **컴팩션과 gold 의 덮어쓰기가 갈아 끼운 옛 데이터 파일은 아무 참조 없이 GCS 에 남는다** — 표준 Iceberg 라면 스냅샷 만료가 함께 지우는 것인데, 스냅샷이 먼저 사라져 지울 계기가 없다

첫 유지보수 (2026-09-03 11:44 KST) 뒤 `articles_changes` 는 표가 1개를 가리키는데 GCS 에는 parquet 9개였고, 버킷이 하루 만에 8,865,742 에서 23,001,079 바이트가 됐다.

## 고아 파일 청소

유지보수가 표마다 `data/` 아래 객체를 나열해, 현재 스냅샷의 파일 집합에 없고 **생성 시각이 3일 넘은** 것을 지운다.
3일은 Apache Iceberg 의 `remove_orphan_files` 기본값과 같다.
Iceberg 는 데이터 파일을 먼저 쓰고 목록을 나중에 갱신하므로, 「목록에 없다」 가 「버려도 된다」 와 같은 말이 아니다.
살아 있는 집합을 먼저 받고 나열은 그 뒤에 한다 — 순서를 바꾸면 그 사이에 커밋된 새 파일이 고아로 보인다.

로그는 표마다 한 줄이다.

```
고아 청소 — data/ 객체 9개 · 살아 있는 것 1 · 3일 안 된 것 8 · 지움 0
```

정상 상태에서는 「살아 있는 파일 + 최근 3일 안에 고아가 된 파일」 만 남는다.
`metadata/` 는 건드리지 않는다 (옛 `metadata.json` 은 `previous-versions-max` 로 카탈로그가 관리한다).
`drop_table` 뒤에 남은 파일은 표가 없어 살아 있는 집합을 못 만드므로 이 청소가 못 보고, 손으로 지운다.

데이터 파일 수가 표마다 계속 늘 때는 컴팩션이 안 걸린 것이다.
조각난 채로 두면 행당 부피가 6.15배가 된다.
먼저 `systemctl list-timers` 로 `bullet-in-warehouse-maint.timer` 의 `LAST` 를 확인한다.

## 첫 유지보수에서 실제로 나온 값 (2026-09-03 11:44 KST)

| 표 | 파일 (전 → 후) | 부피 (전 → 후) |
| --- | --- | --- |
| `articles_changes` | 8 → 1 | 3,466,211 → 3,169,988 B |
| `articles_snapshot` | 2 → 1 | 6,189,909 → 5,796,951 B |
| `ga4_events` (중첩 bronze) | 6 → 1 | 1,158,658 → 751,623 B |
| `ga4_events_flat` | 6 → 1 | 453,063 → 334,845 B |

열 표 전부 행 수가 그대로였고, 중첩 구조를 전량 읽어 덮어쓰는 길이 실물에서 처음 돌았다.

## 첫 적재에서 실제로 나온 값 (2026-09-02 16:50 KST)

| 표 | 행 | 파일 | 부피 |
| --- | --- | --- | --- |
| `articles_changes` | 1,010 | 1 | 3,046,702 B |
| `articles_snapshot` | 1,010 | 1 | 3,046,702 B |
| `players_snapshot` | 564 | 1 | 46,621 B |
| `article_players_snapshot` | 3,647 | 1 | 51,556 B |
| `ops_pipeline_runs` | 355 | 1 | 29,549 B |
| `ops_source_freshness` | 2,759 | 1 | 44,849 B |

행 수는 여섯 다 MariaDB 실제 값과 일치했다.
버킷 전체는 객체 36개 · 6,362,434 바이트였다.

같은 명령을 한 번 더 돌려 봤지만 행은 늘지 않았다.
변경분은 워터마크가 막고 전량 스냅샷은 하루 1회 게이트가 막는다.

로그에 `UserWarning: Delete operation did not match any records` 가 그날 첫 스냅샷마다 한 번 나오는데 고장이 아니다.
그날 파티션을 덮어쓰려고 지우기를 먼저 부르는데 아직 그 파티션이 없어서 나오는 경고다.

`WARNING Failed to delete metadata file gs://.../metadata/0000N-....metadata.json` 도 고장이 아니다 (2026-09-03 확인).
테이블 속성 `write.metadata.previous-versions-max=5` 에 따라 PyIceberg 가 여섯 번째 커밋부터 가장 오래된 `metadata.json` 을 지우려 하는데, Lakehouse 카탈로그가 서버 쪽에서 먼저 지워 버려 클라이언트의 삭제가 빈손이 된다.
지우려던 파일이 GCS 에 없고 남은 파일이 표마다 6개 (이전 5 + 현재) 면 정상이다.

## 행동 기록 갈래 (2026-09-03 추가)

같은 유닛이 마트 이력 말고 사이트 방문자의 행동 기록도 싣는다.
출처가 BigQuery 라 앞의 것과 접속하는 곳이 다르지만 새 유닛을 만들지 않고 이 타이머에 얹었다.

### 무엇이 어디에 쌓이나

네임스페이스 `behavior` 아래에 표 넷이 있다.

| 표 | 층 | 무엇 |
| --- | --- | --- |
| `ga4_events` | bronze | BigQuery 가 준 31컬럼 그대로 · 중첩 구조도 그대로 |
| `ga4_events_flat` | silver | 파라미터를 컬럼으로 펴고 겹친 행을 접은 것 |
| `fact_card_click` | gold | 카드 클릭 한 건이 한 행 |
| `dim_date` | gold | 날짜 · 요일 · 공개일로부터 며칠째 |

기사와 선수 디멘션은 새로 만들지 않고 `mart_history` 의 스냅샷을 참조한다.

### 설정 하나가 필요하다

`.env` 에 데이터셋 주소가 있어야 이 갈래가 돈다.

```
GA4_DATASET=bullet-in-analytics.analytics_551139164
```

없으면 로그에 「GA4_DATASET 이 없어 넘어간다」 를 남기고 조용히 지나간다.
개발 환경에는 이 값이 없는 것이 정상이다.

자격은 마트 이력과 같은 서비스 계정을 쓴다.
그 계정이 다른 프로젝트를 읽어야 해서 `bullet-in-analytics` 에 `roles/bigquery.dataViewer` 와 `roles/bigquery.jobUser` 를 붙여 두었다.

### 세 층이 각자 자기 워터마크를 본다

층마다 판정이 따로 돈다.

- **원본** — BigQuery 의 `events_YYYYMMDD` 목록에서 아직 안 실은 날짜
- **평탄화본** — 원본에 있으나 아직 안 편 날짜
- **gold** — 평탄화본 전량에서 매번 다시 세운다 (덧붙이지 않고 갈아 끼운다)

**앞 층의 진행에 얹으면 안 된다.**
처음에는 평탄화를 원본 적재 루프 안에서 돌렸는데, 그러면 원본이 먼저 완성된 뒤에는 평탄화가 한 번도 안 돈다.
로그가 「새로 실을 날짜가 없다」 로 정상처럼 보여서 운영에 붙이고 나서야 드러났다.

### 도착이 하루 늦다

구글 애널리틱스의 일별 내보내기는 다음 날 09:44 에서 10:28 KST 사이에 도착한다.
3시간 회차 주기와 안 맞지만 날짜가 판정 단위라 못 집은 회차가 있어도 다음 회차가 같은 판정으로 집어 온다.

### 화면은 집계 파일을 거친다

적재가 끝나면 `state/behavior_metrics.json` 에 축별 집계를 떨어뜨린다.
회차의 렌더가 그 파일을 읽어 `site/behavior.html` 을 그리고, 기존 배포 절차가 그대로 올린다.

**렌더가 Iceberg 를 직접 읽지 않는 것이 요점이다.**
그러면 회차마다 카탈로그 인증과 GCS 왕복이 붙고 그 실패가 배포를 막는 게이트 앞에서 회차를 흔든다.
집계 파일이 없으면 페이지를 안 그리고 회차는 그대로 끝난다.

**행동 갈래가 실패하면 유닛이 실패로 끝나 `OnFailure=` 알림이 온다 (2026-09-03 개정).**
마트 이력 적재는 그 앞에서 이미 끝났으므로 잃는 것이 없다.
처음에는 예외를 삼키고 경고만 남겼는데, 그러면 유닛이 0 으로 끝나 알림이 안 뜨고 집계 파일이 조용히 낡는다.

집계는 클릭이 단계 · 등급을 안 실어 왔어도 기사 해시가 있으면 마트 스냅샷에서 채운다.
주요 소식과 타임라인 제목이 2026-09-03 까지 해시만 실었기 때문이다 (화면 「(없음)」 52 = 주요 소식 24 + 선수 카드 26 + 타임라인 2).
선수 카드는 기사가 아니라 그대로 「(없음)」 에 남고, 매체는 마트 컬럼 하나와 안 맞물려 못 채운다.

페이지 주소는 `https://bullet-in.pages.dev/behavior` 이고 검색엔진 색인은 막아 두었다.
`curl` 로 받을 때는 `-L` 을 붙인다 — 안 붙이면 308 만 받고 본문이 0바이트로 온다.

### 첫 적재에서 실제로 나온 값 (2026-09-03 KST)

| 항목 | 값 |
| --- | --- |
| 원본 | 6일치 13,035행 · 1,158,658바이트 |
| 평탄화본 | 12,984행 · 453,063바이트 · 컬럼 50 |
| 접힌 행 | 51 (설계가 BigQuery 질의로 잰 값과 같다) |
| 팩트 | 577행 (BigQuery 의 중복 제거 결과와 같다) |
| 집계 기준 | 클릭 271건 (전체 577건에서 공개일 306건 제외) |

**부피가 층을 지나며 줄어든다.**
BigQuery 원본이 13,523,735바이트인데 Parquet 으로 1/12 이 되고 평탄화하면 다시 절반 아래로 내려간다.
중첩 구조를 펴면 키 이름의 반복이 사라지기 때문이다.

## 첫 결제 대조 일정

커밋당 GCS 연산 수는 로컬 파일시스템에서 잰 하한선이라 실제 청구가 더 나올 수 있다.
GCS 에서만 나는 호출은 그 측정에 안 잡혔다.

- **2026-09-09** — 첫 주 대조 · Class A 회수가 무료 5,000회 대비 어디쯤인지 본다
- **2026-10-02** — 첫 달 대조 · `BigLake Table Management` 가 0인지 함께 본다

두 날짜는 잔여 안건 메모리에도 남겼다.
