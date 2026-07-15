# journalist 백필 · 기자 신뢰도 운영 런북 (2026-07-16)

기자 중심 트랙 (PR #54) 이 도입한 `journalist` 채움 · tier 보정 · 기자 facet 의 운영 절차.
백필 CLI 실행, 채움률 판독, tier 보정이 걸리는 조건, 재발 시 진단 순서를 담는다.

## 1. 백필 CLI

기존 기사의 `journalist` 를 채운다.
raw 저장소에 원본 HTML 이 없어 기사 URL 재fetch 가 유일한 경로다.

```bash
set -a; source .env; set +a          # 이 프로젝트는 dotenv 미사용 — 필수
uv run python -m bullet_in.backfill_journalist --limit 5 --dry-run   # 리허설
uv run python -m bullet_in.backfill_journalist                       # 전건
```

- **멱등** — `journalist IS NULL` 인 행만 재시도한다. 중복 실행해도 채운 값을 덮지 않는다.
- **대상 산출** — 통칭 소스 (`journalist_label` 보유) 는 재fetch 없이 일괄 UPDATE, 나머지는 `adapter == "html"` 이고 `config.body_selector` 를 가진 소스만 재fetch.
- **간격** — 소스별 순차 · 항목 간 1.5초 (`REQUEST_GAP_SEC`). 실패 건에도 간격이 걸린다 (`try/finally`).
- **실패 격리** — 404 · 타임아웃 · 저자 부재는 NULL 유지 · 건너뛰고 소스별 성공 / 실패 집계를 출력한다.

### 1.1. `--dry-run` 판독 주의

통칭 소스는 dry-run 에서 **`stats` 집계에 잡히지 않고 `[dry-run]` 로그로만 남는다**.
최종 요약에 재fetch 소스만 뜨므로 "통칭 0건" 으로 오판하지 말 것.

```
INFO [dry-run] arsenal_official → journalist='Arsenal Official' 일괄
INFO [dry-run] bbc_gossip → journalist='BBC Gossip' 일괄
bbc_sport: 성공 5 · 실패 0          ← 통칭 2소스는 이 요약에 없음
```

### 1.2. fmkorea 는 대상이 아니다

fmkorea 도 `config.body_selector` 를 갖지만 `adapter: fmkorea` 라 `fetch_ids` 에서 빠진다.
**이 조건을 지우면 fmkorea 가 233건 규모로 1.5초 간격 재fetch 대상이 되어 2시간 접근 규칙을 깬다** (430 이 65분 이상 잔존 — `docs/troubleshooting/2026-07-15-benchmark-rate-limit-self-interference.md`).

## 2. 채움률 판독

```bash
set -a; source .env; set +a
uv run python -c "
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ['MARIADB_URL'])
with e.connect() as c:
    for r in c.execute(text('SELECT source_id, COUNT(*) n, SUM(journalist IS NOT NULL) wj '
                            'FROM articles GROUP BY source_id ORDER BY n DESC')):
        print(f'  {r[0]:18} {r[2]:3}/{r[1]:3}')
"
```

2026-07-16 전건 백필 직후 기준선:

| source_id | 채움 | 비고 |
|---|---|---|
| football_london | 205/205 | |
| bbc_gossip | 41/41 | 통칭 `BBC Gossip` |
| x_afcstuff | 13/13 | 인용 핸들 |
| goal | 12/12 | |
| skysports | 7/10 | 미채움 = 무기명 |
| bbc_sport | 6/6 | |
| fmkorea | 6/21 | 미채움 = 말머리에 기자 없는 게시글 |

**정상적인 미채움 2종** — 아래는 결함이 아니므로 조사하지 말 것.

- **무기명 기사** — `author` 가 `{"@id": "#Publisher"}` 인 발행사 귀속 기사 (Sky Sports 의 Paper Talk 등).
- **fmkorea 말머리 무기자** — `[언론사]` 만 있고 기자명이 없는 게시글.

## 3. tier 보정이 걸리는 조건

고정 소스의 tier 는 기본이 `sources.yaml` 값이고, **아래를 모두 만족할 때만** `min(기자 tier, 소스 tier)` 로 승격한다.

1. 기자가 `credibility.yaml` 에 등재
2. 그 기자에 `outlet` 이 지정됨 (프리랜서는 미지정 — 아래 §3.1)
3. 그 `outlet` 이 기사 소스의 `sources.yaml` `outlet` 과 **문자열 일치**

`min` 이므로 승격만 가능하고 강등은 불가능하다.

### 3.1. 프리랜서는 tier 무조정 (설계)

여러 매체에 기고하는 기자 (Charles Watts · Fabrizio Romano) 는 `outlet` 을 지정하지 않는다.
표시 (바이라인 · facet) 만 하고 tier 는 소스 값을 유지한다 — 사용자 결정이다.
동적 소스 (`x_mentions` · `fmkorea`) 의 기자 조회 경로는 이 규칙과 무관하게 기존대로 동작한다.

### 3.2. "승격이 하나도 안 걸린다" 는 정상일 수 있다

2026-07-16 실측 기준 **승격 0건**이다. 버그가 아니라 레지스트리 구성의 귀결이다.

| 소속 일치 조합 | 결과 |
|---|---|
| Sami Mokbel (1) @ bbc_sport (1) | `min` = 1 — 동률, 무동작 |
| Dharmesh Sheth (1.5) @ skysports (1.5) | `min` = 1.5 — 동률, 무동작 |
| Sami Mokbel (1) @ bbc_gossip (4) | 통칭 `BBC Gossip` 이 선점 — 설계대로 |

tier 4 소스 (goal · football.london) 에 소속 지정 기자가 없어서 승격 여지가 없다.
**발효 조건** — 소스를 보유한 매체 (BBC · Sky Sports · Goal.com · football.london · The Guardian) 소속 기자가 레지스트리에 추가될 때.

### 3.3. 소속 일치는 문자열 대조다

`credibility.yaml` 의 outlet 정식명과 `sources.yaml` 의 `outlet` 이 **한 글자라도 다르면 가드가 조용히 안 걸린다**.
레지스트리 · 소스 설정을 건드린 뒤에는 대조할 것.

```bash
uv run python -c "
import yaml
from bullet_in.score import load_sources
reg = yaml.safe_load(open('config/credibility.yaml', encoding='utf-8'))
names = {o['name'] for o in reg['outlets']}
for sid, s in load_sources('config/sources.yaml').items():
    o = s.get('outlet')
    if o and o not in names:
        print(f'  불일치: {sid} outlet={o!r} — 레지스트리에 없음')
print('대조 완료')
"
```

## 4. 기자 facet 판독

사이드바 "기자" 섹션은 **등재 기자 상시 노출 + 미등재 더보기 토글** 구조다.

- **정규화** — 저장값이 소스마다 다르다 (fmkorea 한글 말머리 `온스테인` · X 핸들 `@David_Ornstein` · html 풀네임 `David Ornstein`). `journalist_directory` 가 레지스트리 정식명으로 병합한다.
  **정규화 없이 집계하면 같은 기자가 facet 에서 갈라지고 필터가 깨진다.**
- **필터 키** — 체크박스 `data-value` 와 카드 `data-journalist` 는 **같은 정규화 정식명**이어야 한다. 어긋나면 필터가 조용히 0건을 낸다.
- **라벨** — 등재는 레지스트리 `outlet`, 미등재는 수집 소스의 `outlet`, 통칭 (`journalist_label` 과 값이 같을 때) 은 괄호 생략.

정규화 동작 확인 (생성 사이트 파싱):

```bash
python3 - <<'PY'
import re, pathlib
h = pathlib.Path("site/index.html").read_text(encoding="utf-8")
vals = set(re.findall(r'data-group="journalist" data-value="([^"]+)"', h))
cards = set(re.findall(r'data-journalist="([^"]*)"', h)) - {""}
print("체크박스에만 있음:", vals - cards)   # 비어야 정상
print("카드에만 있음:", cards - vals)       # 비어야 정상
PY
```

## 5. 신규 소스 추가 시 체크

1. `sources.yaml` 에 `outlet` 을 **레지스트리 정식명으로** 기입 (§3.3 대조 실행).
2. 저자 개념이 없는 집계 칼럼이면 `journalist_label` 로 통칭 지정 (예: `BBC Gossip`).
3. 어댑터 단독 `fetch()` 로 **소스별** authors 채움률 확인 — 총합이 아니라 소스별로 볼 것 (`docs/troubleshooting/2026-07-16-json-ld-author-extraction-traps.md`).
4. 채움률이 낮으면 기사 페이지의 JSON-LD `author` 원값을 직접 확인 — 무기명 (`@id` 참조) 인지, 파서가 못 잡는 형태인지 구분.

## 6. 참고

- spec: `docs/superpowers/specs/2026-07-16-journalist-track-design.md` · plan: `docs/superpowers/plans/2026-07-16-journalist-track.md` · PR #54.
- 저자 추출 함정: `docs/troubleshooting/2026-07-16-json-ld-author-extraction-traps.md`.
- 레지스트리 큐레이션: `docs/runbook/2026-07-15-credibility-registry-ops.md` · `docs/troubleshooting/2026-07-15-credibility-registry-curation-traps.md`.
- 말투 백필 (별개 축): `docs/runbook/2026-07-15-tone-backfill-ops.md`.
