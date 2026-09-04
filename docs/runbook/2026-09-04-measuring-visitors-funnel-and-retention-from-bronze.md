# bronze 에서 방문자 · 퍼널 · 리텐션을 세는 법

행동 지표 화면이 아직 보여 주지 않는 값 (DAU · 신규와 재방문 · 세션 · 퍼널 · 리텐션 · 시간대 · 선수 페이지) 을 레이크하우스 bronze 에서 직접 세는 절차다.
2026-09-04 대시보드 개편 목업을 만들 때 쓴 스크립트를 정리했고 코드 PR 에서 gold 표로 옮길 때 검증 기준값을 다시 뽑는 데 쓴다.

## 1. 전제

- VM 에서 돈다.
  `~/bullet-in` 에서 `.env` 를 소싱하고 레이크하우스 키를 `GOOGLE_APPLICATION_CREDENTIALS` 로 준다 (DAG 의 `warehouse_load` 태스크와 같은 자격).
- 읽는 표는 셋이다.
  silver `behavior.ga4_events_flat` (이벤트 한 줄이 한 행 · 56컬럼), gold `behavior.fact_card_click` (카드 클릭만 · `card_slug` 포함), MariaDB `players` (이적 상태).
- 사용자 키는 `user_pseudo_id` 하나다.
  `bi_cid` 와 섞지 않는다 ([트러블슈팅](../troubleshooting/2026-09-04-two-keys-double-the-visitor-count.md)).
- 날짜는 `event_date_kst` 를 쓴다.
  공개 전 시험 방문 (08-24) 은 `>= 2026-08-28` 로 자른다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17
cd ~/bullet-in && set -a; . ./.env; set +a
GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json ~/.local/bin/uv run python /tmp/measure.py
```

## 2. 표 읽기

```python
from collections import Counter, defaultdict
from bullet_in import warehouse as w
cat = w.load_catalog()
cols = ["event_date_kst", "event_name", "user_pseudo_id", "ga_session_id", "session_engaged",
        "device_category", "traffic_source", "traffic_medium", "page_location", "engagement_time_msec",
        "card_surface", "n_journalist", "n_tier", "event_at"]
rows = cat.load_table(f"{w.BEHAVIOR_NS}.{w.GA4_FLAT_TABLE}").scan().to_arrow().select(cols).to_pylist()
rows = [r for r in rows if r["event_date_kst"] and r["event_date_kst"] >= "2026-08-28"]
```

`select` 에 없는 컬럼을 적으면 `KeyError` 로 바로 죽는다.
컬럼 이름은 `scan().to_arrow().schema.names` 로 먼저 본다.

## 3. DAU · 신규와 재방문 · 세션

```python
first = {}
for r in rows:
    u, d = r["user_pseudo_id"], r["event_date_kst"]
    first[u] = min(first.get(u, d), d)
day = defaultdict(lambda: {"users": set(), "new": set(), "sessions": set(), "engaged": set(), "clicks": 0})
for r in rows:
    u, d, b = r["user_pseudo_id"], r["event_date_kst"], day[r["event_date_kst"]]
    b["users"].add(u)
    if first[u] == d: b["new"].add(u)
    sid = (u, r["ga_session_id"]); b["sessions"].add(sid)
    if r["session_engaged"] in (1, "1", True): b["engaged"].add(sid)
    if r["event_name"] == "bi_card_click": b["clicks"] += 1
for d in sorted(day):
    b = day[d]; print(d, len(b["users"]), len(b["new"]), len(b["users"]) - len(b["new"]), len(b["sessions"]), len(b["engaged"]), b["clicks"])
```

세션은 (사용자, `ga_session_id`) 쌍으로 센다.
`ga_session_id` 만 쓰면 사용자가 달라도 같은 값이 겹칠 수 있다.
2026-09-04 기준값 = 7일 사용자 890 · 세션 1,502 · 참여 세션 61%.

## 4. 퍼널

```python
entry, click, click2, ret = set(), Counter(), set(), set()
days_of = defaultdict(set)
for r in rows:
    u = r["user_pseudo_id"]; days_of[u].add(r["event_date_kst"])
    if r["event_name"] == "bi_entry": entry.add(u)
    if r["event_name"] == "bi_card_click": click[u] += 1
clickers = {u for u, n in click.items() if n >= 1}
click2 = {u for u, n in click.items() if n >= 2}
returned = {u for u, ds in days_of.items() if len(ds) > 1}
print(len(entry), len(clickers), len(click2), len(returned & clickers))
```

단계는 진입 → 카드 클릭 → 2건 이상 클릭 → 재방문 (2일 이상 방문) 이고 앞 단계의 부분집합이어야 한다.
원문 이동 (`bi_origin_exit`) 은 목표가 아니라 새는 곳이라 단계에 넣지 않고 곁가지로 둔다.
2026-09-04 기준값 = 863 → 221 → 97 → 71.

## 5. 리텐션 삼각형

```python
from datetime import date, timedelta
coh = defaultdict(set)
for u, fd in first.items(): coh[fd].add(u)
last = max(day)
for fd in sorted(coh):
    base = coh[fd]; f = date.fromisoformat(fd); row = []
    for k in range(7):
        dk = (f + timedelta(k)).isoformat()
        row.append(None if dk > last else sum(1 for u in base if dk in days_of[u]))
    print(fd, len(base), row)
```

칸은 「첫 방문일이 fd 인 사용자 가운데 k 일 뒤에 온 사람 수」 다.
비율로 바꿀 때 D+0 은 정의상 100% 라 색 눈금에서 뺀다.
2026-09-04 기준값 = 공개일 코호트 666명의 D+1 55명 (8%).

## 6. 요일 × 시간대

```python
from datetime import timezone, timedelta
KST = timezone(timedelta(hours=9)); heat = defaultdict(set)
for r in rows:
    if r["event_name"] not in ("bi_entry", "session_start") or r["event_date_kst"] == "2026-08-29": continue
    ts = r["event_at"]
    if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
    k = ts.astimezone(KST); heat[(k.isoweekday(), k.hour)].add(r["user_pseudo_id"])
```

공개일 (토요일 0시에 590명) 을 빼지 않으면 그 한 칸이 눈금을 다 차지한다.
회차 시각 (KST 0 · 3 · 6 · 9 · 12 · 15 · 18 · 21시) 을 같은 축에 표시하면 「회차가 독자보다 먼저 도는가」 를 읽을 수 있다.

## 7. 선수 페이지

```python
import re
from bullet_in.serve import render as R
players = R.load_page_players()
base = lambda p: re.sub(r"[^a-z0-9]", "", (p.get("surname") or "").lower()) or "player"
counts = Counter(base(p) for p in players); dupes = {s for s, n in counts.items() if n > 1}
by_slug = {R.player_slug(p.get("surname") or "", p["id"], dupes): p for p in players}
pv = Counter()
for r in rows:
    m = r["event_name"] == "page_view" and re.search(r"/player/([^/?#]+)", r["page_location"] or "")
    if m: pv[m.group(1)] += 1
for slug, n in pv.most_common(12):
    p = by_slug.get(slug, {}); print(p.get("ko_name", slug), R._TRANSFER_GROUP_OF.get(p.get("transfer_status") or ""), n)
```

슬러그는 화면이 만드는 규칙 (`player_slug` · 동성이면 `성-id`) 을 그대로 다시 만들어야 명단과 붙는다.
이적 상태 다섯 (영입 진행 중 · 이적 확정 · 이적 무산 · 타 클럽행 · 방출 진행 중) 은 화면의 `_TRANSFER_GROUP_OF` 를 쓴다.
선수 카드 클릭은 `card_slug` 가 비어 있어 선수별로 못 나눈다 ([트러블슈팅 §3](../troubleshooting/2026-09-04-three-charts-that-pointed-at-the-wrong-layer.md)).

## 8. 마트 쪽 (지연 · 주별 구성 · 소스 커버리지)

```sql
-- 발행 → 수집 지연 (시간) · 07-14 이후 · 30일 넘는 것 제외 · p50 · p95 는 파이썬에서
SELECT source_id, TIMESTAMPDIFF(MINUTE, published_at, fetched_at) / 60 AS lag_h
FROM articles WHERE published_at IS NOT NULL AND fetched_at >= '2026-07-14'
  AND fetched_at >= published_at AND TIMESTAMPDIFF(DAY, published_at, fetched_at) <= 30;
-- 주별 등급 · 단계 구성
SELECT YEARWEEK(fetched_at, 3) yw, tier, COUNT(*) FROM articles WHERE fetched_at >= '2026-07-13' GROUP BY yw, tier;
-- 소스 × 주 신규 건수는 articles.fetched_at 이 아니라 pipeline_runs.source_counts (JSON) 를 주로 묶는다
SELECT started_at, source_counts FROM pipeline_runs WHERE started_at >= '2026-06-12';
```

`fetched_at` 으로 소스 커버리지를 그리면 재수집 backfill 때문에 6월이 빈다 ([트러블슈팅 §1](../troubleshooting/2026-09-04-three-charts-that-pointed-at-the-wrong-layer.md)).

## 9. 기준값 (2026-09-04 19:24 KST 추출)

| 값 | 수 |
| --- | --- |
| 사용자 7일 · 세션 · 참여 세션 비율 | 890 · 1,502 · 61% |
| 공개일 DAU · 신규 | 688 · 666 |
| 퍼널 | 863 → 221 → 97 → 71 |
| 신뢰도 · 기자 필터 사용자 · 원문 이동 | 53 · 7 |
| 기사 상세를 본 사용자 | 254 |
| 선수 페이지 뷰 · 목록 뷰 | 108 · 71 |
| 모바일 비율 · fmkorea 참조 비율 | 66% · 70% |

코드 PR 의 gold 표가 이 값과 다르면 표가 아니라 이 절차와 어디가 다른지를 먼저 찾는다.
