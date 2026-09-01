# 덮어써서 사라지는 값을 이력으로 남기는 레이크하우스 설계 (2026-09-02)

`articles` · `players` · `article_players` 는 같은 행을 계속 덮어쓴다.
기사 제목이 재번역되고 선수의 한글 이름이 고쳐지고 이적 단계가 다시 판정될 때, 직전 값은 아무 데도 남지 않는다.
이 설계는 그 값들을 Iceberg 테이블로 옮겨 시점별로 되짚을 수 있게 만든다.

저장은 GCS 에 두고 카탈로그는 Google 이 운영하는 Iceberg REST 엔드포인트를 빌린다.
적재는 회차 안에서 하지 않고 별도 타이머로 돌린다.

## 1. 이 일을 왜 하는가

값어치는 「클라우드 스택을 하나 더 써 본다」 가 아니다.
오브젝트 스토리지와 Iceberg 는 이미 다뤄 본 것이고, 여기서 새로 끝내는 것은 **컴팩션과 멱등성** 두 가지다.
PyIceberg 는 컴팩션 기능을 제공하지 않아서 (공식 문서가 「Compaction is planned」 라고 적어 두었다) 직접 만들어야 한다.

그리고 이 파이프라인에는 컴팩션이 선택 사항이 아니다.
아래 3.4 에서 재어 보면, 컴팩션과 스냅샷 만료를 넣지 않은 채로 두면 넉 달쯤 뒤에 적재가 스스로 멈춘다.

## 2. 착수 전 실측

계획을 세우기 전에 값 세 가지를 재기로 했었다.
셋 다 쟀고, 재는 과정에서 설계를 바꾸는 사실이 다섯 개 더 나왔다.

### 2.1. 카탈로그 비용은 과금 원장에서 직접 읽었다

가격표 웹페이지는 이 항목을 싣지 않는다.
대신 Cloud Billing Catalog API 로 `BigLake` 서비스 (`services/A6C3-245D-D767`) 의 SKU 51개를 받아 읽었다.

| SKU | 무료 구간 | 초과 단가 |
| --- | --- | --- |
| `Class A API call usage of the Lakehouse runtime catalog service` | 월 5,000회 | 0.0083 KRW/회 |
| `Class B API call usage of the Lakehouse runtime catalog service` | 월 50,000회 | 0.00124 KRW/회 |
| `BigLake Table Management` · `us-central1` | 없음 | **165.99 KRW/시간** |

세 번째 줄이 이 설계에서 피해야 할 자리다.
시간당 과금이라 한 달 내내 켜 두면 12만원이 넘는다.
이 SKU 는 BigQuery 가 관리하는 Iceberg 테이블에 붙고, 우리가 PyIceberg 로 직접 커밋하는 테이블에는 붙지 않는다.
그래서 「관리형 Iceberg 를 쓰지 않는다」 는 기존 결정에 금액 근거가 생겼다.

**Class A 예산이 두 개라는 점이 중요하다.**
GCS 의 Class A 5,000회와 카탈로그의 Class A 5,000회는 서로 다른 SKU 이고 각자 무료 구간을 갖는다.
그전 계산은 이 둘을 하나로 보고 있었다.

### 2.2. 이름이 바뀌었지만 주소는 그대로다

공식 문서 원문이다.

> As of April 20th, 2026, BigLake is now called Lakehouse.
> BigLake metastore is now called the Lakehouse runtime catalog.
> Lakehouse APIs, client libraries, CLI commands, and IAM names remain unchanged and still reference BigLake.

그래서 PyIceberg 설정에 쓰는 `https://biglake.googleapis.com/iceberg/v1/restcatalog` 는 여전히 유효하다.
바뀐 것은 문서 주소와 검색어뿐이다 (`docs.cloud.google.com/lakehouse/docs/...`).
IAM 역할 이름도 `roles/biglake.admin` 그대로다.

문서가 함께 못박은 제약이 넷 있다.

- Iceberg V2 이상만 지원한다.
- 데이터 파일은 Parquet 만 지원한다.
- `write.data.path` · `write.metadata.path` 를 기본값 외의 값으로 두는 것이 금지된다.
- **`metadata.json` 파일 크기가 1 MB 로 제한된다.**

마지막 줄이 3.4 의 출발점이다.

### 2.3. 커밋 한 번이 객체 4개를 만든다

로컬 파일시스템에 SQL 카탈로그를 두고 `append()` 를 41회 돌려 세었다.
매번 새로 생기는 파일이 정확히 4개였다.

| 파일 | 개수 |
| --- | --- |
| 데이터 Parquet | 1 |
| manifest (`*-m0.avro`) | 1 |
| manifest list (`snap-*.avro`) | 1 |
| `*.metadata.json` | 1 |

추정값 4가 맞았다.
**다만 이 값은 하한선이다.**
로컬 파일시스템에서 잰 것이라 GCS 에서만 발생하는 호출 (객체 목록 조회 등) 은 여기에 안 잡힌다.
실계정에 처음 붙일 때 결제 보고서로 다시 대조해야 한다.

### 2.4. 압축률은 평균으로 재면 틀린다

운영 MariaDB 6표를 그대로 읽어 Parquet 으로 썼다 (2026-09-02 04:58 KST · 읽기 전용).
값을 전부 문자열로 눕혀서 썼기 때문에 실제 스키마보다 불리한 쪽으로 잰 값이다.

| 표 | 행 | 원시 JSONL | Parquet · zstd | 압축률 |
| --- | --- | --- | --- | --- |
| `articles` | 999 | 8,650,536 | 3,005,591 | **2.88x** |
| `source_freshness` | 2,731 | 674,192 | 36,024 | 18.72x |
| `article_players` | 3,604 | 646,879 | 49,173 | 13.16x |
| `players` | 556 | 275,701 | 42,891 | 6.43x |
| `pipeline_runs` | 351 | 166,022 | 26,078 | 6.37x |
| `sources` | 0 | 0 | 해당 없음 | 해당 없음 |
| 합계 | | 10,413,330 | 3,159,757 | 3.30x |

추정은 3배에서 5배 사이였고 합계는 그 안에 들어왔다.
그런데 부피의 95%를 차지하는 `articles` 가 2.88배로 추정 하한보다 낮다.
한국어 본문과 요약이 열 단위로 모여도 잘 줄지 않기 때문이다.
반대로 `source_freshness` 는 같은 짧은 문자열이 반복돼 18배가 넘는다.

**그래서 저장량 예산은 `articles` 하나로 세운다.**
평균 압축률을 쓰면 실제보다 작게 잡힌다.

### 2.5. 컴팩션이 부피를 6배 되돌린다

회차마다 조금씩 쓰면 Parquet 의 압축이 거의 듣지 않는다.
같은 400행을 2행씩 200개 파일로 쓴 것과 한 파일로 쓴 것을 견주었다.

| | 조각 200개 | 한 파일 |
| --- | --- | --- |
| 합계 | 7,772,169 B | 1,264,036 B |
| 행당 | 19,430 B | 3,160 B |

**6.15배 차이이고 83.7%가 낭비다.**
하루 16행이 들어온다고 보면 연간 108 MiB 와 17.6 MiB 의 차이가 된다.

이 수치가 이 안건의 값어치를 대신 말해 준다.
「작은 파일은 성능에 좋지 않다」 는 교과서 문장이 아니라, 안 하면 저장 비용이 여섯 배가 되는 실제 손해다.

### 2.6. 컴팩션을 안 하면 넉 달 뒤 적재가 멈춘다

Iceberg 는 커밋할 때마다 스냅샷 목록을 `metadata.json` 에 누적한다.
41회 커밋을 돌리며 그 파일의 크기를 재니 스냅샷 하나가 **약 1,015 B**씩 더했다.

카탈로그의 한도가 1 MB 이므로 남은 스냅샷 수는 약 991개다.
표 하나가 하루 8회 커밋을 받으면 **991 ÷ 8 ≈ 124일**에 한도에 닿는다.

한도를 넘으면 커밋이 실패한다.
즉 스냅샷 만료는 있으면 좋은 기능이 아니라 **가동 조건**이다.

### 2.7. 확정 설계에 구멍이 하나 있다

「변경분과 일일 전량 스냅샷을 둘 다 적재한다」 가 확정된 결정이었다.
그런데 세 표 중 둘은 변경분을 잡을 재료를 갖고 있지 않다.

| 표 | 변경 시각 | 변경분을 잡을 수 있나 |
| --- | --- | --- |
| `articles` | `updated_at` · `ON UPDATE CURRENT_TIMESTAMP` | 가능 |
| `players` | `added_at` · `confirmed_at` · `archived_at` | **불가능** |
| `article_players` | `extracted_at` | **불가능** |

`players` 의 `confirmed_at` 과 `archived_at` 은 특정 상태 전이에만 찍힌다.
한글 이름이 고쳐지거나 소속이 바뀐 것은 흔적이 남지 않는다.
`article_players.extracted_at` 도 추출 시각이지 갱신 시각이 아니다.

**결정 자체를 바꾸지는 않는다.**
변경분을 원본 표에서 뽑는 대신 전량 스냅샷끼리 대조해서 도출하면 같은 결과를 얻는다.
자세한 방법은 3.2 에 적었다.

### 2.8. 실제로 바뀌는 양은 새로 들어오는 양보다 훨씬 많다

`articles` 999행 가운데 998행이 `updated_at` 과 `created_at` 이 서로 다르다.
최근 14일 기준으로 하루 평균 60.6행이 갱신됐는데, 새로 들어오는 기사는 하루 15행에서 17행 사이다.

날짜별로 보면 2026-08-29 에 365행, 2026-08-28 에 312행이 한꺼번에 갱신됐다.
표기 정정과 재번역 배치가 주기적으로 돌기 때문이다.

**이력의 값어치가 어디에 있는지를 이 수치가 말해 준다.**
새로 들어오는 기사가 아니라 소급 정정으로 사라지는 직전 값에 있다.

## 3. 결정

### 3.1. 무엇을 언제 적재하는가

테이블을 다섯 개 만든다.

| Iceberg 테이블 | 원본 | 주기 | 방식 |
| --- | --- | --- | --- |
| `mart_history.articles_changes` | `articles` | 회차마다 · 하루 8회 | `updated_at` 워터마크 이후 행 |
| `mart_history.articles_snapshot` | `articles` | 하루 1회 | 전량 |
| `mart_history.players_snapshot` | `players` | 하루 1회 | 전량 |
| `mart_history.article_players_snapshot` | `article_players` | 하루 1회 | 전량 |
| `mart_history.ops_daily` | `pipeline_runs` · `source_freshness` | 하루 1회 | 워터마크 이후 행 |

`pipeline_runs` 와 `source_freshness` 를 하루 1회로 묶은 것은 무료 구간을 지키기 위해서다.
두 표는 삽입만 일어나서 원본이 이미 이력이라 촘촘하게 뜰 이유도 없다.

`sources` 표는 넣지 않는다.
운영에서 0행이고 소스 정의는 `config/sources.yaml` 에 산다.

### 3.2. 변경 시각이 없는 표는 스냅샷을 대조해서 이력을 만든다

`players` 와 `article_players` 는 하루 1회 전량 스냅샷만 적재한다.
직전 스냅샷과 대조해서 무엇이 달라졌는지 도출하는 것은 읽는 쪽의 일이다.

이 방식이 오히려 멱등하다.
같은 날 두 번 돌려도 같은 `snapshot_date` 파티션을 덮어쓰므로 결과가 달라지지 않는다.
`dbt snapshot` 이 쓰는 방식과 같다.

두 표는 작다.
합쳐서 92 KB 이므로 매일 전량을 떠도 연간 33 MB 다.

`articles` 만 두 갈래로 적재한다.
`updated_at` 이 있어서 회차마다 촘촘히 잡을 수 있고, 부피가 커서 (전량 3.0 MiB) 매 회차 전량을 뜨면 무료 구간을 감당하지 못한다.

### 3.3. 적재는 회차 밖에서 별도 타이머로 돈다

`bullet-in.service` 안에 넣지 않는다.
게이트가 배포를 막는 자리이고 2026-08-31 에 실제로 세 시간 멈춘 적이 있는데, 원인이 아직 확정되지 않은 그 위에 네트워크와 인증을 더 얹지 않는다.

`bullet-in-backup.service` 와 같은 모양으로 유닛을 따로 둔다.
회차 타이머가 3시간 간격으로 돌므로, 적재 타이머는 그보다 20분 뒤에 돌게 어긋나 놓는다.
적재가 실패해도 회차와 배포는 영향을 받지 않고 `OnFailure` 로 알림만 나간다.

### 3.4. 무료 구간을 지키는 조건 넷

네 가지를 설계에 넣는다.
빠뜨리면 각각 다른 방식으로 무료 구간을 넘는다.

**넷째부터 적는다. 계획을 쓰고 나서야 나온 것이라 그전 목록에 없었다.**
테이블을 만들 때 `write.metadata.delete-after-commit.enabled` 를 켜고 `write.metadata.previous-versions-max` 를 준다.
안 켜면 커밋마다 `metadata.json` 이 하나씩 GCS 에 영구히 쌓인다.
실측으로 확인했다 (켠 테이블은 커밋 10회 뒤 4개가 남았고, 안 켠 테이블은 41회 뒤 42개가 남았다).
하루 8회 커밋이면 한 해에 객체 8,760개가 그냥 늘어난다.

**첫째, 스냅샷 만료를 매일 돌린다.**
2.6 에서 잰 대로 안 하면 약 124일에 커밋이 실패한다.
`expire_snapshots()` 로 최근 7일치만 남긴다.

**둘째, 컴팩션을 주 1회 돌린다.**
2.5 에서 잰 대로 안 하면 부피가 6.15배가 된다.
PyIceberg 에 기능이 없으므로 조각 데이터 파일을 읽어 한 파일로 다시 쓰는 코드를 만든다.

**셋째, 오래된 스냅샷 파티션을 솎는다.**
`articles_snapshot` 은 하루 3.0 MiB 이고 행이 하루 16행씩 늘어난다.
누적을 계산하면 **약 414일에 GCS 무료 5 GB 를 채운다.**
90일이 지난 `snapshot_date` 중 월요일이 아닌 것을 지운다.

Class A 호출은 이렇게 하면 아래와 같다.

| 항목 | 하루 | 한 달 |
| --- | --- | --- |
| `articles_changes` 회차 적재 · 8회 × 4객체 | 32 | 960 |
| 전량 스냅샷 3표 + `ops_daily` · 4회 × 4객체 | 16 | 480 |
| 컴팩션 · 주 1회 × 5표 × 4객체 | | 약 87 |
| 스냅샷 만료 · 5표 × 4객체 | 20 | 600 |
| 합계 | | **약 2,130** |

GCS 무료 5,000 안에 들어가고 여유가 절반 넘게 남는다.
카탈로그 Class A 는 커밋 수에 비례하므로 하루 13회 커밋 기준 월 800회 아래이고 역시 무료 구간 안이다.

**이 표의 값은 하한선이다** (2.3 참조).
첫 달 결제 보고서로 반드시 대조한다.

### 3.5. GCP 프로젝트와 권한

새 프로젝트를 판다.
결제 계정 `01E3C1-098D9D-58E612` 아래 세 번째가 된다 (`bullet-in-analytics` · `bullet-in-backup` 다음).

무료 한도는 프로젝트가 아니라 결제 계정 단위라서 프로젝트를 나눠도 손해가 없다.
대신 비용 보고서에서 Gemini 축과 갈려 보인다.

버킷은 `us-central1` 에 만든다.
GCS 5 GB 무료가 `us-east1` · `us-west1` · `us-central1` 세 곳에만 적용되고, 백업 버킷도 같은 리전에 있다.

백업 버킷은 현재 15.41 MiB 를 쓰고 있다.
보관 정책이 다 찬 정상 상태에서도 100 MB 안쪽이라 두 안건이 5 GB 를 나눠 써도 문제가 없다.

VM 에는 gcloud SDK 를 깔지 않는다.
`google-auth` 로 토큰만 받고 `httpx` 로 REST 를 부르는 경로가 백업에서 이미 돌고 있다.
PyIceberg 는 `auth: type: google` 로 같은 자격을 쓴다.

## 4. 이번 범위 밖

- **시계열 gold 모델과 대시보드.**
  이력이 며칠 쌓인 뒤라야 빈 차트가 안 나온다.
- **기존 `dbt/models/gold/` 3모델.**
  한 글자도 건드리지 않는다.
- **dbt 게이트를 웨어하우스로 옮기는 것.**
  게이트는 DuckDB 에 그대로 둔다.
- **Mongo `raw_items` 적재.**
  bronze 층은 이번에 다루지 않는다.

## 5. 위험

| 위험 | 어떻게 다루나 |
| --- | --- |
| Class A 실측값이 하한선이다 | 첫 달 결제 보고서를 서비스와 프로젝트 두 기준으로 대조한다 |
| `BigLake Table Management` SKU 가 붙으면 월 12만원 | 관리형 Iceberg 테이블을 만들지 않는다 · 첫 주 결제 보고서에서 이 SKU 가 0인지 확인한다 |
| `metadata.json` 1 MB 한도 | 스냅샷 만료를 매일 돌리고 남은 스냅샷 수를 로그에 남긴다 |
| 적재 실패가 회차를 죽이는 것 | 별도 유닛으로 분리하고 `OnFailure` 알림만 붙인다 |
| `gcloud auth login` 이 브라우저 인증이라 막히는 것 | 로컬 `gcloud` 가 이미 `benidjor@gmail.com` 으로 인증돼 있어 프로젝트 생성까지는 진행할 수 있다 |
| PyIceberg arm64 휠이 VM 에서 안 깔리는 것 | 계획의 첫 태스크가 VM 설치 확인이다 |

## 6. 이 문서가 근거로 삼은 실측

전부 2026-09-02 새벽 KST 에 직접 재거나 조회한 값이다.

- 카탈로그 SKU · Cloud Billing Catalog API `services/A6C3-245D-D767`
- 제약 넷 · `docs.cloud.google.com/lakehouse/docs/set-up-lakehouse-iceberg-rest-catalog`
- 커밋당 객체 수 · `metadata.json` 증가 · PyIceberg 0.11.1 로컬 SQL 카탈로그 41회 커밋
- 메타데이터 정리 속성의 효과 · 같은 카탈로그에서 속성을 켠 테이블과 안 켠 테이블 대조
- PyIceberg 호출 시그니처 · 계획서에 적은 코드를 0.11.1 에 그대로 돌려서 확인 (계획서 자체 점검 절에 결과를 실었다)
- 압축률 · 운영 MariaDB 6표 전량 (`articles` 999행 시점)
- 변경 시각 컬럼 · 같은 덤프의 열 구성
- 백업 버킷 사용량 · `gcloud storage du gs://bullet-in-backup-prod`
