# 계측을 붙이고 실제로 도착하는지 증명하는 절차 (2026-08-24)

공개 준비 회차에서 GA4 계측과 BigQuery 내보내기를 붙이며 쓴 절차다.
**「붙였다」 로 끝내면 안 되는 자리**라 도착을 증명하는 단계까지 포함한다.

## 1. 이 절차가 답하는 질문

- 계측을 어디에 배선하고 값은 어디에 두는가
- **정기 회차가 그 값을 읽는지** 어떻게 확인하는가 (빠뜨려도 오류가 안 나는 자리다)
- 이벤트가 **수집처에 도착했는지** 어떻게 확인하는가
- 고지 문구와 실제 수집이 어긋나지 않게 어떻게 묶는가

## 2. 배선

### 2.1. 측정 ID 는 환경변수로 받고 기본값을 비운다

```python
# src/bullet_in/serve/render.py
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "")
```

템플릿은 이 값이 있을 때만 스크립트를 넣는다.

**기본값을 비우는 이유는 목업이다.**
운영 사본을 로컬에 렌더해 화면을 고르는 일이 잦은데, 그때 계측이 함께 들어가면 **목업을 띄우는 것만으로 운영 수치가 흐려진다.**

**값은 공개 값이라 `.env.example` 에 적는다.**
측정 ID 는 페이지 소스에 그대로 실리므로 숨길 것이 없고, 운영 환경에만 두면 나중에 어디서 왔는지 못 따라간다.

### 2.2. 이벤트마다 익명 식별자와 시각을 싣는다

```js
gtag('event', name, Object.assign({}, params,
  { bi_cid: BI_CID, bi_ts: new Date().toISOString() }));
```

**이 둘은 나중에 채울 수 없다.**
없이 모으면 그 기간의 행동을 영영 사람 단위로 못 묶는다.

**세션 경계는 여기서 정하지 않는다.**
식별자와 시각만 있으면 세션은 나중에 어떤 정의로든 다시 만들 수 있고, 지금 정의를 굳히면 그때 바꾸기 어려워진다.

식별자는 브라우저 저장이 막혔을 때를 대비한다 — 저장이 안 되면 고정값으로 떨어뜨리고 이벤트는 그대로 보낸다.

### 2.3. 고지와 계측을 같은 조건에 묶는다

```jinja
{% if ga_id %}
  <h2 id="stats">접속 통계</h2>
  …
{% endif %}
```

**안 모으면서 「수집합니다」 라고 적으면 그 문장 자체가 사실과 어긋난다.**
반대로 모으면서 고지를 빠뜨리는 조합도 이 배선에서는 구조적으로 안 나온다.

검사도 양쪽을 본다 — 꺼진 렌더에 고지가 **없고**, 켜진 렌더에 **있는지**.

## 3. 운영 반영

### 3.1. 값을 넣고 셸이 읽는지 본다

```bash
ssh <호스트> 'cd ~/bullet-in && printf "GA_MEASUREMENT_ID=G-XXXXXXXXXX\n" >> .env'
ssh <호스트> 'cd ~/bullet-in && set -a && . ./.env && set +a && echo "$GA_MEASUREMENT_ID"'
```

`.env` 는 **덧붙이기만** 한다 (`>>`).

### 3.2. 정기 회차가 그 값을 읽는지 따로 확인한다 — 빠뜨려도 오류가 안 난다

손으로 재생성 · 배포하면 계측이 들어간다.
**그다음 정기 회차가 산출물을 다시 만들 때도 그 값을 읽는지는 별개 질문이다.**
안 읽으면 회차가 계측 없는 산출물로 조용히 덮는다 — 오류도 알림도 없다.

```bash
# 유닛이 그 파일을 환경으로 읽는가
ssh <호스트> 'grep -iE "EnvironmentFile|WorkingDirectory" /etc/systemd/system/bullet-in.service'

# 회차가 만든 산출물에 실제로 남았는가 (회차 뒤에 센다)
ssh <호스트> 'cd ~/bullet-in/site && echo "$(grep -rl -F "G-XXXXXXXXXX" . | wc -l) / $(find . -name "*.html" | wc -l)"'
```

**계수가 전체보다 하나 적은 것이 정상일 수 있다** — 이 저장소에서는 `ops.html` 이 공통 레이아웃을 안 써서 빠진다 (운영 뷰는 계측 대상이 아니다).

## 4. 도착 증명 — 층을 셋으로 가른다

| 층 | 무엇을 보나 | 무엇으로 |
| --- | --- | --- |
| ① 붙었다 | 산출물에 스크립트 · 표식이 있다 | `grep` · 단위 테스트 |
| ② 불렸다 | 브라우저가 함수를 호출했고 인자가 맞다 | 콘솔 · `dataLayer` |
| ③ 도착했다 | 수집처가 그것을 받았다 | 전송 요청 · 수집처 화면 |

**①과 ②를 보고 ③을 말하면 안 된다.**
경위는 `docs/troubleshooting/2026-08-24-we-called-gtag-and-nothing-arrived.md` 에 있다.

### 4.1. ② 를 보는 법

라이브 배포본에서 실제로 눌러 무엇이 나가는지 읽는다.

```js
const sent = [];
const real = window.gtag;
window.gtag = function () { sent.push([...arguments]); return real.apply(this, arguments); };
// 카드 · 필터 · 원문 링크를 눌러 본다 (이동은 preventDefault 로 막는다)
sent.map(a => a[1]);
```

`window.dataLayer` 를 그대로 읽으면 페이지 로드 때 이미 나간 이벤트까지 보인다.

### 4.2. 차단 여부를 먼저 가른다

```js
typeof window.google_tag_data   // 진짜 gtag.js 가 돌면 'object'
typeof window.ga                // 차단기 대체 스크립트가 흔히 만드는 전역
```

네트워크에서는 **`/g/collect` 요청이 있는가** 하나만 본다.
`gtag/js` 가 200 으로 오는 것은 태그 로더일 뿐이라 근거가 못 된다.

**검증은 확장 프로그램이 없는 창에서 한다** (시크릿 창 · 다른 브라우저 · 휴대폰).

### 4.3. ③ 을 보는 법

수집처 화면에서 **이벤트 이름**이 뜨는지 본다 (GA4 는 보고서 → 실시간 개요 → 「이벤트 이름별 이벤트 수」).

**매개변수는 이 화면에 안 나온다.** 맞춤 측정기준을 등록하거나 원본 내보내기를 봐야 한다.
원본을 따로 받을 계획이면 화면에 등록할 필요가 없다 — **여기서 확인할 것은 「이벤트가 도착하는가」 하나다.**

## 5. 원본 내보내기 (GA4 → BigQuery)

### 5.1. 붙이기 전에 청구 기준선을 잰다

**붙인 뒤 늘어난 금액의 원인을 가르려면 지금 값을 알아야 한다.**

결제 → 보고서 → 그룹화 기준을 **서비스** 와 **프로젝트** 로 각각 열어 두 잣대가 같은 값을 가리키는지 본다.
이 회차에서는 이 조회가 문서에 적힌 금액이 **실제의 1/7** 인 것을 잡았다.

### 5.2. 설정

| 항목 | 선택 | 이유 |
| --- | --- | --- |
| 데이터 스트림 및 이벤트 | 전체 · 제외 없음 | 원본을 받는 것이 목적이다 |
| 광고 식별자 포함 | ❌ | 앱이 없고 개인정보 축에서 가장 민감하다 |
| 이벤트 · 매일 | ✅ | 하루 한 번 전체 내보내기 |
| 이벤트 · 스트리밍 | ❌ | **별도 과금**이고 실시간이 필요한 용도가 없다 |
| 사용자 데이터 · 일별 | ❌ | 세션 · 사용자 집계는 이벤트로 계산된다 |
| 데이터셋 위치 | 가까운 리전 | **만든 뒤에는 못 바꾼다** |

### 5.3. 위치를 바꾸려면 지우고 다시 만든다

데이터셋 위치는 생성 뒤 변경 불가다.

1. GA4 → 관리 → BigQuery 링크 → **링크 삭제** (GA4 에 쌓인 데이터는 안 지워진다)
2. BigQuery 탐색기에서 **데이터셋이 있으면 삭제** — 남아 있으면 새 링크가 그 위치를 그대로 쓴다
3. 다시 연결하며 위치를 고른다

**첫 내보내기 전이면 잃을 것이 없다.** 이 회차에서는 연결 당일이라 데이터셋이 아직 0개였다.

### 5.4. 도착은 다음 날 확인한다

「매일」 내보내기는 하루 한 번 돌므로 **연결 직후에는 데이터셋도 테이블도 없는 것이 정상**이다.

```sql
SELECT event_name, COUNT(*) AS n
FROM `<프로젝트>.analytics_<속성ID>.events_YYYYMMDD`
WHERE event_name LIKE 'bi_%'
GROUP BY event_name
ORDER BY n DESC
```

속성 ID 는 GA4 주소창의 `…p<숫자>` 에서 읽는다.

**링크를 지웠다 다시 만든 날은 그날 분이 온전히 담길지 장담할 수 없다** — 테이블을 열어 봐야 갈린다.

### 5.5. 쌓인 원본을 조회하는 법 (2026-09-02 추가)

내보내기는 **행 하나가 이벤트 하나인 로그**다.
집계된 형태가 아니고 매개변수는 컬럼이 아니라 `event_params` 라는 키 · 값 배열에 들어 있다.

```bash
# 날짜별 이벤트 수와 방문자 수
bq query --project_id=bullet-in-analytics --use_legacy_sql=false \
  'SELECT _TABLE_SUFFIX AS d, COUNT(*) AS events, COUNT(DISTINCT user_pseudo_id) AS users
   FROM `bullet-in-analytics.analytics_551139164.events_*` GROUP BY d ORDER BY d'

# 한 이벤트가 싣고 있는 매개변수 목록
bq query --project_id=bullet-in-analytics --use_legacy_sql=false \
  'SELECT p.key, COUNT(*) AS n
   FROM `bullet-in-analytics.analytics_551139164.events_*`, UNNEST(event_params) p
   WHERE event_name = "bi_card_click" GROUP BY p.key ORDER BY n DESC'
```

데이터셋은 `analytics_551139164` 이고 위치는 `asia-northeast3` 다.

### 5.6. 잇는 키가 둘이다 (2026-09-03 개정)

`bi_card_click` 과 `bi_origin_exit` 이 싣는 `card_hash` 가 마트의 `articles.content_hash` 다.
2026-09-02 에 표본 5건을 뽑아 운영 DB 와 대조했고 5건 모두 붙었다.

**선수 카드에는 기사 해시가 없어 `card_slug` 를 따로 심었다** (PR #439).
그 값은 `players.slug` 이고 선수 페이지 주소와 같다.

| 키 | 어디에 붙나 | 무엇과 잇나 |
| --- | --- | --- |
| `card_hash` | 기사 카드 · 주요 소식 항목 · 타임라인 제목 · 원문 이탈 | `articles.content_hash` |
| `card_slug` | 선수 카드 | `players.slug` |

함께 실리는 축이 `card_stage` · `card_tier` · `card_outlet` · `card_surface` 라, 우리 마트의 같은 컬럼과 대조까지 된다.

**조인할 때 알아야 할 것 셋이 있다.**

- **한 키가 클릭 전체에 있지는 않다** — 표면마다 붙는 키가 달라서, 어느 쪽으로 조인하는지에 따라 남는 행이 다르다 (아래 5.9).
- **표본이 한쪽으로 쏠려 있다** — 6일치 13,035건 중 공개일 (2026-08-29) 하루가 58%다.
- **하루 늦게 도착한다** — 일별 내보내기라 3시간 회차 주기와 안 맞는다.

### 5.7. 파이프라인으로 가져올 때 리전을 맞출 필요는 없다

내보내기는 `asia-northeast3` 에 있고 변경 이력 레이크하우스는 `us-central1` 에 있다.

**리전이 같아야 한다는 요구는 BigQuery 가 자기 일로 파일을 옮길 때 걸린다** (`EXPORT DATA` · 로드 작업).
클라이언트가 행을 읽어 우리가 다른 곳에 쓰는 경로에는 안 걸린다.

`src/bullet_in/warehouse.py` 가 이미 그 모양이다.
MariaDB 에서 읽어 pyarrow 로 바꾸고 `us-central1` 의 Iceberg 에 쓴다.
출처를 BigQuery 로 하나 더 늘리면 되고, 그래서 버킷 리전을 옮길 이유가 없다.

**이그레스 요금은 2026-09-02 에 쟀다** (아래 5.11).

### 5.8. 무엇이 얼마나 쌓였는지 세는 조회 (2026-09-03 추가)

먼저 이벤트 종류와 건수를 본다.

```bash
bq --project_id=bullet-in-analytics query --use_legacy_sql=false --format=pretty \
  'SELECT event_name, COUNT(*) AS n
   FROM `bullet-in-analytics.analytics_551139164.events_*`
   GROUP BY event_name ORDER BY n DESC'
```

2026-09-02 기준으로 10종이 나왔고 우리가 심은 `bi_` 로 시작하는 넷은 4,007건으로 전체의 31% 였다.
나머지는 향상된 측정이 자동으로 붙이는 것이다.

파라미터 키와 그 타입 분포는 이렇게 본다.

```bash
bq --project_id=bullet-in-analytics query --use_legacy_sql=false --format=pretty \
  'SELECT p.key, COUNT(*) AS n,
          COUNTIF(p.value.string_value IS NOT NULL) AS s,
          COUNTIF(p.value.int_value IS NOT NULL) AS i,
          COUNTIF(p.value.double_value IS NOT NULL) AS d
   FROM `bullet-in-analytics.analytics_551139164.events_*`, UNNEST(event_params) AS p
   GROUP BY p.key ORDER BY n DESC'
```

키는 39개였고 **둘은 같은 키가 두 타입으로 온다.**
`session_engaged` 는 문자열 12,231건과 정수 804건이고, `card_tier` 는 정수 406건과 실수 41건이다.
키마다 타입을 정하려 들면 이런 예외를 손으로 다뤄야 하므로, 평탄화할 때는 값을 전부 문자열로 모으고 숫자로 쓸 때만 변환한다.

**한글 별칭을 쓰면 질의가 깨진다.**
`COUNT(*) AS 전체` 처럼 적으면 `Illegal input character` 가 나므로 별칭은 영문으로 둔다.

### 5.9. 조인 키가 빈 행의 원인은 표면 종류다

`bi_card_click` 의 `card_hash` 가 74% 에만 있어 처음에는 「조인하면 4분의 1이 사라진다」 로 읽었다.
어느 화면에서 눌렸는지로 나눠 보니 사라지는 것이 아니었다.

```bash
bq --project_id=bullet-in-analytics query --use_legacy_sql=false --format=pretty \
  'SELECT (SELECT value.string_value FROM UNNEST(event_params) WHERE key="card_surface") AS surface,
          COUNT(*) AS n,
          COUNTIF((SELECT value.string_value FROM UNNEST(event_params) WHERE key="card_hash") IS NOT NULL) AS with_hash
   FROM `bullet-in-analytics.analytics_551139164.events_*`
   WHERE event_name="bi_card_click" GROUP BY surface ORDER BY n DESC'
```

| 표면 | 건수 | 정체 | 지금 |
| --- | --- | --- | --- |
| `item` | 432 | 기사 카드 | 처음부터 해시 보유 |
| `mitem` | 88 | 홈의 주요 소식 항목 | **PR #437 에서 해시를 심었다** |
| `pcard` | 48 | 선수 카드 | **PR #439 에서 `card_slug` 를 심었다** |
| `relitem` | 15 | 템플릿에 주석으로만 남은 옛 마크업 | 이을 대상이 없다 |
| `tltitle` | 4 | 선수 페이지 타임라인 제목 | **PR #437 에서 해시를 심었다** |

**셋 다 같은 모양이었다.**
주소에는 값이 이미 있는데 계측이 읽는 `data-` 속성만 없었다.
`pcard` 는 처음에 「기사가 아니니 원래 없는 것이 맞다」 고 봤다가, 마크업을 확인하고 판단을 거뒀다.

**표면에 새 마크업을 더할 때는 계측이 읽을 속성도 함께 단다.**
안 달면 클릭은 기록되는데 무엇을 눌렀는지가 안 남고, 그 사실은 나중에 표면별로 나눠 세어 보기 전까지 안 보인다.

**`relitem` 이 알려 주는 것이 중요하다.**
지금 화면에 없는 마크업이 기록에는 살아 있다.
행동 기록은 과거 배포본의 흔적을 담으므로 **표면 값의 목록을 코드에 박으면 안 된다.**

### 5.10. 같은 행동이 두 번 도착한다

우리 계측 4,007건에서 51건이 겹친다.

```bash
bq --project_id=bullet-in-analytics query --use_legacy_sql=false --format=pretty \
  'WITH e AS (SELECT event_name, user_pseudo_id, event_timestamp,
       (SELECT value.string_value FROM UNNEST(event_params) WHERE key="bi_cid") AS bi_cid,
       (SELECT value.string_value FROM UNNEST(event_params) WHERE key="bi_ts") AS bi_ts
     FROM `bullet-in-analytics.analytics_551139164.events_*` WHERE event_name LIKE "bi_%")
   SELECT COUNT(*) AS total,
          COUNT(DISTINCT FORMAT("%s|%s|%s", bi_cid, bi_ts, event_name)) AS uniq_cid_ts,
          COUNT(DISTINCT FORMAT("%s|%d|%s", user_pseudo_id, event_timestamp, event_name)) AS uniq_pseudo_ts
   FROM e'
```

겹친 행들은 클라이언트 · 클라이언트 시각 · 페이지가 모두 같고 GA4 의 수집 시각만 다르다.
같은 행동이 두 번 도착한 것이다.

**그래서 `user_pseudo_id` 와 수집 시각은 중복 판정에 쓸 수 없다.**
같은 행동이 서로 다른 시각으로 오므로 겹침을 못 잡는다.
우리가 심은 `bi_cid` 와 `bi_ts` 가 자연키 노릇을 하고, `bi_cid` 는 4,007건 전량에 있다.

### 5.11. 나가는 데이터의 양과 요금을 재는 법

BigQuery 에서 GCP 밖으로 행을 읽어 오면 이그레스 요금이 붙는다.
**응답이 압축되므로 압축 전후를 둘 다 재야 실제 과금 대상을 안다.**

```bash
TOKEN=$(gcloud auth print-access-token)
BASE=https://bigquery.googleapis.com/bigquery/v2/projects/bullet-in-analytics
TBL=datasets/analytics_551139164/tables/events_20260901/data

curl -s -o /dev/null -w '%{size_download}\n' -H "Authorization: Bearer $TOKEN" "$BASE/$TBL?maxResults=100000"
curl -s -o /dev/null --compressed -w '%{size_download}\n' -H "Authorization: Bearer $TOKEN" "$BASE/$TBL?maxResults=100000"
```

2026-09-02 에 하루치 821행으로 재니 비압축 11,815,192 바이트 · gzip 228,728 바이트였다.
**51배로 줄어든다** — GA4 의 JSON 은 빈 칸이 끝없이 반복되는 구조라 그렇다.

읽는 라이브러리 (`google-cloud-bigquery`) 는 gzip 을 기본으로 요청하므로 실제로 나가는 것은 압축된 쪽이다.
단가는 `within Asia` 기준 165.99 KRW/GiB 이고 무료 구간이 없어서 월 6.7 MiB 면 약 1.1원이다.
단가를 다시 뽑는 절차는 `docs/runbook/2026-09-02-reading-gcp-prices-from-the-billing-catalog.md` 에 있다.

### 5.12. 파이썬으로 읽을 때는 자격 증명이 따로다

`bq` 명령이 되는 것과 파이썬 라이브러리가 되는 것은 다른 자격 증명을 본다.
`bq` 는 gcloud 로그인을 쓰고 라이브러리는 Application Default Credentials 를 본다.

```bash
gcloud auth application-default login     # 브라우저가 한 번 열린다
```

이것 없이 `bigquery.Client()` 를 만들면 `DefaultCredentialsError` 가 난다.
운영에서는 서비스 계정 키를 쓰는데, 그 계정은 `bullet-in-lakehouse` 프로젝트에 속해 있어 `bullet-in-analytics` 를 읽을 권한을 따로 붙여야 한다 (`roles/bigquery.dataViewer` 와 `roles/bigquery.jobUser`).

중첩 구조를 그대로 받는 것은 확인했다.

```python
from google.cloud import bigquery
tbl = bigquery.Client(project="bullet-in-analytics").list_rows(
    "bullet-in-analytics.analytics_551139164.events_20260901").to_arrow()
# 821행 · 31컬럼 · 1.0초 · event_params 배열 보존
```

**`google-cloud-bigquery-storage` 는 필요 없다.**
없으면 REST 경로로 받는다는 경고가 뜨지만 중첩까지 정상으로 온다.

## 6. 예산 알림 — 상한선이 아니라 조기 경보

결제 → 예산 및 알림 (또는 개요 화면의 빠른 카드) 에서 결제 계정 전체에 월 예산을 건다.

- **금액은 지금 예상치보다 넉넉하게 잡는다.** 예상치에 딱 맞추면 이번 달에 바로 울려 경고가 무뎌진다.
- **지출을 막지 않는다.** 넘어도 서비스는 그대로 돌고 메일만 온다.
- 만든 뒤 임계값과 수신자를 화면에서 한 번 확인한다.

## 7. 우리 레이크하우스로 들일 때 미리 확인한 것 (2026-09-03)

행동 기록을 Iceberg 로 옮기는 설계는 세 가지를 확인하지 않은 채 끝났다.
구현에 들어가기 전에 셋을 한 번에 재고 그 결과를 여기 남긴다.

### 7.1. 프로젝트를 건너 읽는 권한

적재를 도는 서비스 계정은 `bullet-in-lakehouse` 프로젝트의 것이고 내보내기는 `bullet-in-analytics` 에 있다.
역할 둘을 붙여야 한다.

```bash
gcloud projects add-iam-policy-binding bullet-in-analytics \
  --member=serviceAccount:bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com \
  --role=roles/bigquery.dataViewer
```

`roles/bigquery.jobUser` 도 같은 방식으로 붙인다.
붙었는지는 정책에서 되읽어 확인한다.

```bash
gcloud projects get-iam-policy bullet-in-analytics \
  --flatten=bindings[].members \
  --filter=bindings.members:bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com \
  --format='value(bindings.role)'
```

두 줄이 나와야 한다.
`add-iam-policy-binding` 은 성공하면 정책 전문을 그대로 뱉어서 어느 역할이 붙었는지가 출력에 안 드러난다.
그래서 붙이는 명령의 성공 여부가 아니라 되읽은 목록으로 판정한다.

### 7.2. 잰 값 셋

VM 에서 서비스 계정으로 돌려 확인했다.
로컬에서 돌리면 사용자 계정이 쓰이므로 권한을 재는 뜻이 없다.

| 확인한 것 | 값 |
| --- | --- |
| 서비스 계정으로 표 목록 읽기 | 6개 |
| 하루치 읽기 | 821행 · 31컬럼 |
| 중첩 구조를 카탈로그에 커밋 | 821행 그대로 들어갔다 |
| 스키마 진화 | `union_by_name` 뒤 31 → 32컬럼 · 다시 실어 1,642행 |
| arm64 VM 의 패키지 설치 | `google-cloud-bigquery` 가 전이 의존 26개와 함께 붙었다 |

`event_params` 배열과 `device` · `geo` · `traffic_source` 레코드가 형태를 잃지 않고 커밋됐다.
설계가 대비책으로 적어 둔 「평탄화된 형태로만 받기」 는 쓸 일이 없다.

### 7.3. 표를 지워도 파일은 남는다

시험용 표를 `drop_table` 로 지운 뒤 저장소를 보니 객체 10개 · 385,590 바이트가 그대로 있었다.
카탈로그에서 이름만 사라지고 데이터 파일과 메타데이터는 남는다.

```bash
gcloud storage ls -r "gs://bullet-in-lakehouse-prod/<네임스페이스>/**"
gcloud storage rm -r "gs://bullet-in-lakehouse-prod/<네임스페이스>"
```

시험 삼아 만든 표는 지운 뒤 저장소까지 확인한다.
안 그러면 아무도 안 읽는 파일에 요금이 계속 붙고, 무료 구간 안이라 청구서로도 안 드러난다.

## 8. 참조

- 도착을 못 본 경위 — `docs/troubleshooting/2026-08-24-we-called-gtag-and-nothing-arrived.md`
- 회차 반영 · 배포 — `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` §6.1
- 재생성 스니펫 — `docs/runbook/2026-07-19-enrich-only-pass.md` §4
- 구현 PR — #333 (계측 코드 · 색인 · 링크 미리보기) · #335 (측정 ID 주입 · 접속 통계 고지)
