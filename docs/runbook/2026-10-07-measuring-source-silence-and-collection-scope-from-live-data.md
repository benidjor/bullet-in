# 운영 데이터로 원문의 새 글 공백과 수집 범위를 재는 법 (2026-10-07)

SLO-5 상한을 다시 정하거나, 수집 범위 (설계 2026-10-07) 가 무엇을 받고 버리는지 볼 때 쓰는 절차다.
2026-10-05 · 06 에 실제로 쓴 조회와 스크립트를 옮겼다.

## 1. 지킬 것

| 항목 | 내용 |
| --- | --- |
| 운영 DB | 읽기 전용 조회만 한다 |
| 외부 사이트 | 소스마다 한 번만 받고, 출력은 파일로 남긴다 · 출력을 다시 보려고 다시 받지 않는다 |
| 시각 | 저장값은 UTC 다 · 화면 · 알림은 KST 를 함께 쓴다 |
| 진행 중 공백 | 끝나지 않은 공백은 하한이다 · 상한 근거로 쓸 때는 「끝난 최장」 과 나눠 적는다 |

VM 의 DB 컨테이너는 이렇게 부른다.

```bash
VM="ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17"
# Mongo (원본 저장소)
$VM "docker exec bullet-in-mongo-1 mongosh bulletin --quiet --eval '...'"
# MariaDB (서빙 DB)
$VM 'docker exec bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin --batch -e "..."'
```

## 2. 원본의 발행 시각 보유율

원본 문서의 발행 시각은 최상위가 아니라 `raw_payload` 안에 있다.
언론사 · 공식 소스 · fmkorea 는 `raw_payload.published`, X 는 `raw_payload.created_at` 이다.
최상위 `published_at` 을 세면 전부 0건이 나온다 (2026-10-02 에 실제로 그렇게 틀렸다).

```javascript
db.raw_items.aggregate([
  {$group: {_id: {s: "$source_id", m: {$substr: ["$fetched_at", 0, 7]}}, n: {$sum: 1},
            pub: {$sum: {$cond: [{$ifNull: ["$raw_payload.published", false]}, 1, 0]}},
            cre: {$sum: {$cond: [{$ifNull: ["$raw_payload.created_at", false]}, 1, 0]}}}},
  {$sort: {"_id.s": 1, "_id.m": 1}}
]).forEach(x => print(x._id.s, x._id.m, (x.pub + x.cre) + "/" + x.n))
```

2026-10-05 기준으로 2026-08 이후는 모든 소스가 100% 다.

## 3. 원문에 새 글이 없던 기간 — 발행 시각 기준 공백

### 3.1. 받기

```javascript
db.raw_items.find({source_id: {$in: ["skysports", "x_ornstein", "bbc_sport"]}},
  {_id: 0, source_id: 1, fetched_at: 1, p: "$raw_payload.published", c: "$raw_payload.created_at"})
  .forEach(x => print(JSON.stringify(x)))
```

출력을 로컬 파일 (`raw-times.jsonl`) 로 받는다.

### 3.2. 세기

소스마다 발행 시각을 정렬해 이웃한 두 값의 간격 가운데 최장을 찾는다.
같은 계산을 `fetched_at` 으로도 해 두 값을 나란히 적는다.

```python
from dateutil import parser
# rows = 파일의 JSON 줄들 · pub = r.get("p") or r.get("c")
ts = sorted({parser.parse(pub) for pub in pubs})
longest = max((b - a).total_seconds() / 3600 for a, b in zip(ts, ts[1:]))
ongoing = (now - ts[-1]).total_seconds() / 3600      # 하한
```

### 3.3. 두 값이 다르면

수집 시각 간격이 훨씬 짧으면 같은 글이 다시 저장되고 있다는 신호다 (트윗 해시 흔들림 · 안건 2κ).
그 구간의 원본을 시각순으로 뽑아 발행 시각이 옛 값인 원본이 있는지 본다.
위쪽 한계로 쓸 값은 발행 시각 간격이다.

## 4. 목록이 실제로 바뀐 시각

원본은 이적 필터 같은 판정을 통과한 글만 남으므로, 목록 자체의 변화는 목록 지문 (`list_sig` · 2026-10-02 부터) 으로 본다.

```sql
SELECT source_id, checked_at, state, list_changed_at, cap_hours, LEFT(list_sig, 8) sig
FROM source_freshness
WHERE source_id IN ('skysports', 'x_ornstein') AND checked_at >= '2026-10-03'
ORDER BY source_id, checked_at;
```

`list_changed_at` 이 계속 같으면 목록이 그대로다.
상한 (`cap_hours`) 에 닿는 시각은 `list_changed_at + cap_hours` 다.

## 5. 수집 범위가 무엇을 받는지 — 목록 1회 수집

### 5.1. 언론사 목록 제목 받기

HTML 소스는 `HtmlAdapter.fetch` 의 목록 단계 (선택자 · 주소 중복 제거 · 제목 추출) 를 그대로 옮긴 스크립트로 목록 페이지만 받는다.
상세 페이지는 받지 않는다.
RSS 는 피드를 한 번 받아 `feedparser` 로 제목만 꺼낸다.

설정 (`config/sources.yaml`) 의 `list_url` · `item_selector` · `title_selector` · `title_attr` · `base_url` 을 그대로 읽어야 실제 수집과 같은 제목이 나온다.

### 5.2. 공식 소스 기사 받기

운영 어댑터를 그대로 한 번 돌리되, 채택 판정 (`arsenal_api._accept`) 을 감싸 모든 기사의 제목 · 종류 · 태그를 기록한다.

```python
from bullet_in.adapters import arsenal_api as m
seen, orig = [], m._accept
def spy(art, *a, **k):
    seen.append({"title": art.get("title"), "type": art.get("articleType"),
                 "tax": art.get("taxonomies")})
    return orig(art, *a, **k)
m._accept = spy
asyncio.run(m.ArsenalApiAdapter("arsenal_official", window_hours=24 * 7).fetch())
```

7일 창이면 사이트맵 1회와 기사별 GraphQL 수십 회다.

### 5.3. 규칙 대 보기

받은 제목에 판정 규칙을 돌려 갈래별 수와 버린 제목을 본다.
수집 범위 확대가 들어간 뒤에는 `bullet_in.scope.ScopeRule` 과 `factory.scope_rules` 를 그대로 부른다 (규칙을 손으로 다시 쓰지 않는다).
명단은 운영 DB 에서 읽는다.

```sql
SELECT full_name, surname FROM players
WHERE status = 'confirmed' AND category IN ('squad', 'manager') ORDER BY id;
```

2026-10-06 실측 제목과 명단은 `tests/fixtures/scope_titles_2026-10-06.json` 에 있다.

## 6. 배포 뒤 버린 제목 훑기

수집 범위 확대가 배포되면 소스마다 `fetch_detail.funnels.<소스>.dropped` 에 버린 제목이 남는다.
2주 동안 모아 중복 없이 훑고, 받아야 했는데 버린 제목이 주당 몇 건인지 센다 (설계 2026-10-07 §5.2).

```sql
SELECT started_at,
       JSON_EXTRACT(fetch_detail, '$.funnels.guardian.dropped') AS dropped,
       JSON_EXTRACT(fetch_detail, '$.funnels.guardian.passed_by') AS passed_by
FROM pipeline_runs
WHERE started_at >= '2026-10-08'
ORDER BY started_at;
```

목록은 실행마다 같은 글이 반복되므로 제목을 집합으로 모은 뒤 센다.

## 7. 함정

| 함정 | 피하는 법 |
| --- | --- |
| 최상위 필드만 세서 「없음」 | `raw_payload` 안을 함께 센다 (§2) |
| 수집 시각 간격을 원문에 새 글이 없던 기간으로 읽음 | 발행 시각 간격과 나란히 적는다 (§3.3) |
| 목록 지문이 없는 기간의 「목록 그대로」 | 지문이 기록된 기간만 센다 (2026-10-02 부터) |
| 로컬에서 스크립트를 돌리면 `uv` 가 파이썬 3.14 가상환경을 새로 만든다 | `uv run --python 3.11` 로 고정한다 |
| 측정 스크립트가 운영 코드와 다른 규칙을 씀 | 운영 함수를 import 해 부른다 (§5.3) |
