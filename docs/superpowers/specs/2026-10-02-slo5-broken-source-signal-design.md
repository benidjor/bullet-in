# SLO-5 가 「끊김」 만 재도록 신호를 나누는 설계 (2026-10-02)

## 1. 배경

### 1.1. 문제

SLO-5 는 소스마다 마지막 원본 수집 이후 경과 시간이 임계 (`freshness_hours`) 를 넘었는지로 「끊김」 을 판정한다 (`quality.evaluate_freshness`).
이적 시장이 닫힌 뒤 BBC Sport · Sky Sports · The Guardian 은 이적 키워드에 맞는 기사가 드물어져, 소스는 멀쩡한데 새 원본이 0 이 된다.
이 「조용함」 이 「끊김」 과 같은 신호로 들어와서, 어떤 임계를 골라도 오탐 아니면 늦은 탐지 중 하나를 받아들여야 한다.

경위와 재측정은 `docs/troubleshooting/2026-10-01-a-threshold-cannot-tell-a-quiet-source-from-a-broken-one.md` 가 정본이다.
이 설계는 그 문서 §6 이 남긴 과제를 푼다.

### 1.2. 이미 있는 재료

- **HTML 어댑터 깔때기** — 실행마다 목록 페이지의 `selected → deduped → titled → passed` 를 `pipeline_runs.fetch_detail.funnels` 에 남긴다 (`adapters/html.py`).
  셀렉터가 깨지면 `selected` 나 `titled` 가 0 이 된다.
- **후보 수** (`pipeline_runs.candidate_counts`) — 필터를 통과한 뒤의 수라서 HTML 에서는 `passed` 와 같다.
  조용한 날에는 0 이 되므로 끊김 판정 재료로는 쓸 수 없다.
- **후보 절벽 알림** (#218 · `quality.candidate_cliffs`) — 직전 실행에 후보가 있다가 이번에 0 이 되는 전이를 한 번 알린다.
  이 설계는 이 알림을 건드리지 않는다.
- **X 와 fmkorea 의 실행 중 정보** — X 어댑터는 필터 전 트윗 목록 (`raw_tweets`) 을, fmkorea 어댑터는 검색 실패 수와 실패 코드 (`search_failure_codes`) 를 실행 중에만 갖고 있고 저장하지 않는다.
- **레이크하우스 적재** — `warehouse.ensure_table` 이 기존 표에 `union_by_name` 으로 새 칼럼을 붙인다.
  MariaDB 표에 칼럼을 **추가만** 하면 `ops_source_freshness` 는 다음 적재에서 칼럼이 자동으로 붙고 옛 행은 빈 값이 된다.
- **SLO-5 를 읽는 곳 둘** — 수집 현황 화면 (`serve/ops_view.py` 의 `_freshness` · `_tiles` · `_slo_rows`) 과 dbt Gold (`dbt/models/gold/gold_slo_rollup.sql` 의 `sum(stale)`) 이다.

### 1.3. 이 설계가 정한 것

브레인스토밍에서 사용자가 고른 답이다.

| 질문 | 답 | 절 |
| --- | --- | --- |
| SLO-5 는 무엇을 재는가 | 「끊긴 소스 0」 만 잰다 · 조용함은 화면에 따로 보인다 | 2.1 |
| X · fmkorea 의 응답 판정 재료 | 두 어댑터에 작은 깔때기 기록을 더한다 | 2.2 · 3.1 |
| 응답은 있는데 새 원본이 없을 때 | 소스별 상한을 넘으면 끊김으로 센다 · 상한은 비수기 최대 공백 기반 | 2.3 |
| 판정 결과를 어디에 남기는가 | `source_freshness` 에 칼럼 셋을 더한다 | 3.2 |
| 무응답 몇 번이면 끊김인가 | 2회 연속 | 2.1 |

---

## 2. 판정 규칙

### 2.1. 상태 넷

감시 대상은 `silence_cap_hours` 가 있는 소스 일곱 곳이다 (bbc_sport · bbc_gossip · guardian · skysports · x_afcstuff · x_ornstein · fmkorea).
공홈 (`arsenal_official`) 과 Goal 은 지금처럼 감시에서 뺀다.

| 상태 | `state` 값 | 조건 | SLO-5 | 알림 |
| --- | --- | --- | --- | --- |
| 끊김 | `broken` | 목록 무응답 2회 연속 · 또는 경과 > 상한 | 센다 | 보낸다 |
| 응답 없음 1회 | `no_response` | 이번 실행만 무응답 | 안 센다 | 안 보낸다 |
| 조용함 | `quiet` | 목록 응답 · 경과 > `freshness_hours` · 경과 ≤ 상한 | 안 센다 | 안 보낸다 |
| 정상 | `ok` | 그 밖 | 안 센다 | — |

판정 순서는 위에서 아래다.
경과가 상한을 넘으면 응답 여부와 상관없이 끊김이다.

### 2.2. 「목록이 응답했다」 의 뜻

이번 실행에 그 소스의 예외 (`fetch_detail.errors`) 가 없고, 깔때기가 아래 조건을 만족하면 응답한 것이다.

| 어댑터 | 응답 조건 | 무응답이 되는 고장 |
| --- | --- | --- |
| `html` | `selected > 0` 이고 `titled > 0` | 목록 셀렉터 변경 · 제목 셀렉터 변경 · 차단 |
| `x_playwright` | `scraped > 0` | 로그인 만료 (로그인 화면) · 계정 접근 차단 |
| `fmkorea` | `searched > 0` 이고 `listed > 0` | 모든 검색어 430 · 검색 결과 셀렉터 변경 |

- fmkorea 는 검색어 가운데 하나라도 성공하면 응답으로 본다.
  일부 검색어만 430 을 받는 일은 흔하고, 그때도 수집은 이어진다.
- 예외가 없는데 깔때기가 비어 있으면 무응답으로 본다.
  깔때기 기록이 고장 난 것도 감시가 눈을 감은 상태라서 알려야 한다.

### 2.3. 상한

상한은 「이만큼 새 원본이 없으면 조용함이 아니라 고장」 이라는 선이다.
목록이 옛 글만 계속 보여 주는 고장 (사이트 갱신 정지 · 캐시된 페이지 · 오래된 검색 결과) 은 응답 조건을 통과하므로 상한만이 잡는다.

07-31 의 억제 규칙 (#174 · 「후보가 잡히면 알리지 않는다」) 이 이런 안전판 없이 13일 침묵을 만들었다 (`docs/troubleshooting/2026-08-15-alert-suppression-becomes-silence.md`).

값은 비수기 (2026-09-02 부터 09-30) 원본 공백 최대값의 1.2 배를 하루 단위로 올린 것이다.
공백 최대값은 트러블슈팅 2026-10-01 §3 의 표에서 가져왔다.

| 소스 | 비수기 최대 (h) | × 1.2 | `silence_cap_hours` | 지금 `freshness_hours` |
| --- | --- | --- | --- | --- |
| bbc_sport | 201.0 | 241.2 | 264 (11일) | 96 |
| skysports | 219.0 | 262.8 | 264 (11일) | 120 |
| guardian | 457.2 | 548.6 | 552 (23일) | 192 |
| x_afcstuff | 144.0 | 172.8 | 192 (8일) | 24 |
| x_ornstein | 228.0 | 273.6 | 288 (12일) | 120 |
| bbc_gossip | 27.0 | 32.4 | 48 (2일) | 24 |
| fmkorea | 31.4 | 37.7 | 48 (2일) | 24 |

- Guardian 은 원래 뜸한 소스라서 「옛 글만 보이는」 고장을 최대 23일 뒤에 잡는다.
  셀렉터 깨짐 · 차단처럼 목록이 응답하지 않는 고장은 소스와 상관없이 6시간 안에 잡는다.
- 상한은 계절이 바뀌어도 그대로 둔다.
  성수기 공백은 비수기보다 짧아서 (트러블슈팅 §3) 비수기 기준 상한은 성수기에 오탐을 내지 않는다.

### 2.4. 경과의 기준

경과는 지금처럼 원본 수집 (`raw_items`) 의 마지막 시각에서 잰다 (설계 2026-08-20 §3.1).
기사 표 워터마크 (`stored_fetched_at`) 는 지금처럼 기록으로만 남는다.

### 2.5. `freshness_hours` 의 새 역할

지금 임계는 판정에서 빠지고 화면의 「조용함」 표시선이 된다.
`stale` 칼럼은 계속 「경과 > `freshness_hours`」 를 기록하므로 7월부터 쌓인 이력과 뜻이 같다.

### 2.6. 연속 무응답의 계산과 첫 실행

- `miss_streak` 은 응답하면 0, 무응답이면 직전 행의 값 + 1 이다.
- 직전 행이 없거나 직전 행에 `miss_streak` 이 비어 있으면 (이 설계 배포 전의 행) 0 으로 본다.
  그래서 배포 뒤 첫 실행에서는 무응답이 있어도 `no_response` 까지만 간다.
- 직전 행은 지금처럼 `MartStore.previous_freshness` 가 읽는다 (이번 실행 행을 넣기 전).

---

## 3. 기록과 저장

### 3.1. 어댑터 깔때기

| 어댑터 | `funnel` 키 | 뜻 |
| --- | --- | --- |
| `html` | `selected` · `deduped` · `titled` · `passed` | 지금 그대로 |
| `x_playwright` (새로) | `scraped` · `passed` | 타임라인에서 긁은 트윗 (필터 전) · 필터 뒤 후보 |
| `fmkorea` (새로) | `keywords` · `searched` · `listed` · `passed` | 검색어 수 · 한 페이지라도 성공한 검색어 수 · 검색 결과에서 읽은 글 (필터 전) · 필터 뒤 후보 |

- 세 어댑터 모두 `fetch()` 첫 줄에서 `self.funnel = {}` 로 초기화한다.
  중간에 예외가 나면 빈 깔때기와 오류가 함께 남는다.
- `run.adapter_funnels` 가 어댑터의 `funnel` 속성을 모아 `fetch_detail.funnels` 에 넣는 지금 경로를 그대로 쓴다.
  `pipeline_runs` 스키마는 바뀌지 않는다.
- fmkorea 의 `listed` 는 검색 결과 셀렉터 (`item_selector`) 가 고른 글의 수다.
  이미 적재된 글 · `[공홈]` 말머리 · 제목 필수어 필터로 빠지는 글도 센다.

### 3.2. `source_freshness` 칼럼 추가

`schema.sql` 에 `ALTER TABLE source_freshness ADD COLUMN IF NOT EXISTS` 세 줄을 더한다.

| 칼럼 | 타입 | 뜻 |
| --- | --- | --- |
| `state` | `VARCHAR(16) NULL` | `ok` · `quiet` · `no_response` · `broken` |
| `miss_streak` | `INT NULL` | 연속 무응답 횟수 |
| `cap_hours` | `FLOAT NULL` | 그 실행에 쓴 상한 |

- `stale` 과 `threshold_hours` 는 뜻을 바꾸지 않는다.
- 레이크하우스 `ops_source_freshness` 는 다음 적재에서 세 칼럼이 붙는다 (1.2).
- 백업은 표 단위 덤프라 바꿀 것이 없다.

### 3.3. 설정

`config/sources.yaml` 의 감시 대상 일곱 곳에 `silence_cap_hours` 를 적고, 근거 (비수기 최대 공백과 측정 기간) 를 주석으로 남긴다.
값이 없는 소스는 감시에서 뺀다.

### 3.4. 판정 위치와 함수

판정은 지금 신선도 판정이 도는 자리 (`run.py` 의 게시 단계) 에서 한다.
그 자리에는 그 실행의 깔때기 · 오류 · 후보 수가 `pipeline_runs` 행에서 읽혀 와 있다 (`FetchSummary.funnels` · `FetchSummary.errors`).

`quality.py` 에 표준 라이브러리만 쓰는 순수 함수 둘을 더한다.

- `responded(adapter: str, funnel: dict | None, errored: bool) -> bool` — 2.2 의 표를 그대로 옮긴다.
- `evaluate_states(records, responded_map, caps, previous) -> None` — `SourceFreshness` 에 `state` · `miss_streak` · `cap_hours` 를 채운다.

`SourceFreshness` 데이터클래스에 세 필드를 더하고, `MartStore.record_freshness` 와 `previous_freshness` 가 세 칼럼을 쓰고 읽는다.

---

## 4. 알림 · 화면 · dbt

### 4.1. 알림

- 끊김만 디스코드로 보낸다.
  `no_response` 와 `quiet` 는 지금 「신선도 판정」 로그 한 줄에 소스 이름과 함께 남긴다.
- 끊김이 된 실행에 한 번 보내고, 끊김이 이어지면 48시간마다 다시 보낸다 (`FRESHNESS_REALERT_HOURS` 그대로).
  지금처럼 직전 행과 비교하는 무상태 판정이다.
  - 상한으로 끊긴 경우 — 상한을 넘은 시간을 48시간 구간으로 센다.
  - 무응답으로 끊긴 경우 — `miss_streak` 이 2 를 넘은 횟수를 16회 (3시간 × 16 = 48시간) 구간으로 센다.
  - 직전 행이 끊김이 아니었거나, 끊긴 사유가 바뀌었거나, 구간이 올라가면 보낸다.
  - 상한을 고친 실행은 지금 임계 규칙과 같이 비교 기준이 없다고 보고 보낸다.
- 문안에는 사유를 적는다.
  - 무응답 — 「목록 무응답 2회 연속」 · 오류 문자열 · 깔때기 숫자
  - 상한 — 「목록은 응답 · 새 원본 N일째 없음 (상한 M일)」
- 지금 `quality.freshness_alert_split` 의 자리를 새 분할 함수 (`broken_alert_split`) 가 맡는다.
  `notify.build_freshness_alert` 는 사유를 받아 문안을 가르도록 고친다.

### 4.2. 수집 현황 화면 (`ops.html`)

- 신선도 절 표에 상태 칸을 둔다 (네 상태 · 색 넷).
- 미터는 상한 대비로 바꾸고, `freshness_hours` 는 미터 위 표시선 (조용함 기준) 으로 그린다.
- 위 타일 「Stale Sources」 를 「Broken Sources · 끊긴 소스 (SLO-5)」 로 바꾸고 끊김 수를 센다.
- SLO 표 5행 「소스 신선도 · 끊긴 소스 0」 은 끊김 수를 쓴다.
- 절 설명문 「미터가 다 차면 수집이 끊겼다」 를 새 규칙에 맞게 고친다.
- `state` 가 빈 옛 행은 「판정 이전」 으로 표시한다.

### 4.3. dbt Gold

- `stg_source_freshness` 가 `state` 를 고른다.
- `gold_slo_rollup` 의 SLO-5 를 `sum(case when stale ...)` 에서 `state = 'broken'` 인 소스 수로 바꾸고, 지표 설명 「수집 끊긴 소스 수 (최신 run)」 는 그대로 둔다.
- `stg_source_freshness.state` 에 `accepted_values` 테스트를 두고 `where: state is not null` 로 옛 행을 뺀다.
  게이트의 dbt 테스트는 21 종에서 22 종이 된다.

---

## 5. 시험 · 검증 · 배포

### 5.1. 단위 테스트

판정 함수부터 테스트로 쓴다.

- **상태 전이 표** — 응답 · 무응답 1회 · 2회 연속 · 응답으로 회복 · 조용함 · 상한 초과 · 감시 제외 · 첫 실행 (직전 행 없음 · 직전 행의 `miss_streak` 빈 값) · 상한을 고친 실행.
- **07-31 함정** — 매 실행 목록이 응답하는데 새 원본이 상한을 넘도록 없으면 반드시 끊김이 된다.
- **재알림** — 상한 끊김 · 무응답 끊김 각각 48시간 구간마다 한 번만 보내고, 사유가 바뀌면 다시 보낸다.
- **응답 판정** — 어댑터 셋 × (예외 · 빈 깔때기 · 0 · 정상).
  fmkorea 는 전부 430 · 일부 430 · 결과 0 을 따로 잰다.
- **어댑터 깔때기** — X 는 저장해 둔 트윗 목록으로, fmkorea 는 저장해 둔 검색 결과 HTML 로 `funnel` 값을 잰다.
- **화면 · dbt** — 상태 칸 렌더 · 타일과 SLO 5행이 같은 수를 쓰는지 · `gold_slo_rollup` 이 끊김만 세는지.

픽스처는 `schema.sql` 의 실제 칼럼 이름과 실제 값 모양 (`threshold_hours` 는 `float`) 을 쓴다.
진행 중인 구간 · 빈 구간 · 허용된 빈 값 · 뒤집힌 값을 넣는다.

### 5.2. 머지 전 과거 이력 대입

09-02 부터 09-30 까지의 `pipeline_runs` 와 `source_freshness` 에 새 규칙을 대입해, 그 기간 끊김이 몇 번 났을지 센다.

- 기대는 「거의 0 · 났다면 실제 오류 실행」 이다.
- 그 기간에는 X · fmkorea 깔때기가 없으므로 두 소스는 오류 기록만으로 응답을 판정한다.
- 운영 DB 를 읽는 읽기 전용 스크립트로 돌리고, 결과를 PR 본문 §4 에 싣는다.

### 5.3. 배포 뒤 확인

배포는 회차가 한다 (`bullet_in.deploy advance` · `judge`).

- 첫 실행 — 세 칼럼이 채워지는지 · 로그의 상태별 개수 · `ops.html` 의 SLO-5 값과 상태 칸.
- 둘째 실행 — `miss_streak` 이 직전 행을 따라가는지.
- 다음 레이크하우스 적재 — `ops_source_freshness` 에 세 칼럼이 붙는지.
- 게이트 (dbt 테스트 22 종) 통과와 judge 「반영 완료」.

### 5.4. 되돌리기

PR 을 되돌리면 판정이 지금 방식으로 돌아간다.
추가한 칼럼 셋은 남아도 읽는 곳이 없어 무해하다.

### 5.5. 함께 고칠 문서

- `docs/runbook/2026-08-20-freshness-threshold-recalibration.md` 에 「상한 정하는 법」 절을 더하고, `freshness_hours` 가 조용함 표시선으로 바뀐 것을 적는다.
- README SLO 표의 SLO-5 칸은 배포 뒤 실측을 보고 따로 고친다.

---

## 6. 기각한 대안

- **SLO 를 둘로 나누기 (끊김 · 신선도)** — 신선도 지표가 비수기에 계속 빨갛고, 「SLO 6종」 이라는 서술이 바뀐다.
- **지표는 그대로 두고 표시만 더하기** — 오탐이라는 문제 자체가 남는다.
- **X · fmkorea 를 후보 수로 판정하기** — Ornstein 은 `#AFC` 필터 뒤 후보가 비수기에 0 이 흔해, 끊김과 조용함이 다시 같은 신호가 된다.
- **X · fmkorea 만 지금 임계 방식으로 두기** — 소스마다 규칙이 둘이고 Ornstein 오탐이 남는다.
- **모든 소스에 같은 상한 (14일)** — 매일 나오는 가십 · fmkorea 의 「옛 글만 보이는」 고장을 14일 동안 모른다.
- **상한 = 지금 임계 × 2** — afcstuff 상한이 48시간이 되어, 비수기 최대 공백 144시간에서 다시 오탐이 난다.
- **칼럼 없이 읽는 쪽에서 계산하기** — 같은 판정 로직이 알림 · 화면 · dbt 세 곳에 생기고, dbt 가 JSON 을 풀어야 한다.
- **`stale` 의 뜻을 끊김으로 바꾸기** — 바꾼 날 앞뒤로 같은 칼럼의 뜻이 달라져 이력이 섞인다.
- **무응답 1회에 바로 끊김** — 소스 한 곳 단위 단발 오류 (13주 435회 중 21회 · 전부 `error_count = 1` · 트러블슈팅 2026-09-11) 마다 SLO-5 가 흔들린다.
- **최근 4회 중 3회** — 탐지가 최대 12시간 늦고 판정에 이력 넷이 필요하다.

## 7. 범위 밖

- 조용함 알림 · 회복 알림 · 상한 자동 조정은 넣지 않는다.
- 후보 절벽 알림 (#218) 과 수집량 이상탐지 (SLO-6) 는 건드리지 않는다.
- BBC Sport 깔때기의 `titled 2/9` (트러블슈팅 §2) 가 영상 타일 때문인지 셀렉터 일부 어긋남인지는 이 설계에서 재지 않는다.
