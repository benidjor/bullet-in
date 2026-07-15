# 언론사 · 기자 facet tier 정렬 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ( `- [ ]` ) syntax for tracking.

**Goal:** 사이드바 facet 을 건수순에서 `tier` → `이름` 오름차순으로 재편하고, Tier 헤더 · 더보기 3단계 · 등재 / 미등재 구분선을 붙인다.

**Architecture:** `render.py` 가 tier 문자열 계약 ( `tier_key()` ) 을 단일 소스로 만들고, `facet_counts()` 가 tier 그룹 · 더보기 단계까지 계산된 뷰모델을 내려보낸다.
템플릿은 뷰모델을 그대로 그리고, `app.js` 는 단계 전개만 담당한다.
tier 조회에 `credibility.yaml` 레지스트리가 필요하므로 `registry` 를 `run.py` → `write_site` → `facet_counts` 로 통과시킨다.

**Tech Stack:** Python 3.11, Jinja2, 브라우저 JS ( 프레임워크 없음 ), pytest, uv.

**설계 SoT:** `docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md`.
브랜치 `feat/facet-tier-ordering` ( `origin/main` = `feb0213` 에서 분기 ).

## Global Constraints

- **화면 표기는 `Tier` 대문자** — 카드 칩 · facet · 더보기 버튼 · ops 제목.
  `data-tier` · URL 파라미터 `?tier=` 등 코드 식별자는 소문자 유지.
- **Tier 라벨은 공신력 단일 척도** — `Tier 0 · 공식` · `Tier 1 · 공신력 최상` · `Tier 1.5 · 공신력 상` · `Tier 2 · 공신력 중` · `Tier 3 · 공신력 하` · `Tier 4 · 공신력 최하`.
- **정렬은 `tier` → `이름` 오름차순** ( 대소문자 무시 ). 건수는 순서에 영향을 주지 않는다. 미등재 구간도 이름 오름차순.
- **초기 노출은 Tier 1.5 까지**. 더보기는 `Tier 2` → `Tier 3` → `Tier 4 + 미등재`. 빈 tier 는 단계에서 건너뛴다.
- **문서 서식** — 컨벤션 §2.2. `→` · `—` 는 줄 끝 금지, 한 줄 = 한 문장, `·` · 여는 괄호 양옆 띄우기 ( 코드 · URL · 경로 제외 ).
- **커밋** — `<type>(<scope>): 한국어 제목` + 도입 1–2문장 + 명사형 불릿 + `Refs:` + co-author 트레일러.
- **테스트 실행** — `uv run pytest -q`. DB · Airflow 없으면 통합 테스트는 skip 된다.

---

### Task 1: tier 문자열 계약 · 표기 통일

`tier_key()` 를 신설해 `data-tier` · facet `data-value` · URL 이 같은 문자열을 쓰게 만든다.
`app.js:74` 가 `tiers.includes(card.dataset.tier)` 로 문자열 동등 비교를 하므로 포매터가 갈라지면 필터가 조용히 깨진다.

**Files:**
- Modify: `src/bullet_in/serve/render.py:44-47` ( `tier_label` ) · `:123-126` ( `TIER_BUCKETS` )
- Test: `tests/test_serve_layout.py:26-29` ( 기존 `test_tier_label` 교체 )

**Interfaces:**
- Produces: `tier_key(tier) -> str` · `tier_label(tier) -> str` · `TIER_ORDER: list[float]` · `TIER_HEADINGS: dict[float, str]` · `INITIAL_MAX_TIER: float`.
  Task 3 · 4 가 이 이름들을 그대로 쓴다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_serve_layout.py` 의 기존 `test_tier_label` ( 26–29행 ) 을 아래로 **교체**한다.
import 줄 ( 2–5행 ) 에 `tier_key` · `TIER_ORDER` · `TIER_HEADINGS` 를 추가한다.

```python
from bullet_in.serve.render import (
    humanize_when, fmt_date, outlet_display, tier_label, tier_key,
    neighbor_window, facet_counts, TIER_ORDER, TIER_HEADINGS,
)

def test_tier_key_is_shortest_exact_form():
    # data-tier 와 facet data-value 가 문자열로 비교되므로 표기가 한 가지여야 한다
    assert tier_key(0) == "0"
    assert tier_key(1.0) == "1"
    assert tier_key(1.5) == "1.5"
    assert tier_key(4.0) == "4"
    assert tier_key(None) == ""

def test_tier_label_uses_capital_tier():
    assert tier_label(2) == "Tier 2"
    assert tier_label(2.0) == "Tier 2"
    assert tier_label(1.5) == "Tier 1.5"
    assert tier_label(None) == "Tier ?"

def test_tier_headings_are_credibility_scale():
    assert [TIER_HEADINGS[t] for t in TIER_ORDER] == [
        "Tier 0 · 공식",
        "Tier 1 · 공신력 최상",
        "Tier 1.5 · 공신력 상",
        "Tier 2 · 공신력 중",
        "Tier 3 · 공신력 하",
        "Tier 4 · 공신력 최하",
    ]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_layout.py -q -k "tier"`
Expected: FAIL — `ImportError: cannot import name 'tier_key'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/serve/render.py` 의 `tier_label` ( 44–47행 ) 을 아래로 교체한다.

```python
TIER_ORDER: list[float] = [0.0, 1.0, 1.5, 2.0, 3.0, 4.0]
INITIAL_MAX_TIER = 1.5                      # 초기 노출 상한 (spec §3.2)
TIER_HEADINGS: dict[float, str] = {
    0.0: "Tier 0 · 공식",
    1.0: "Tier 1 · 공신력 최상",
    1.5: "Tier 1.5 · 공신력 상",
    2.0: "Tier 2 · 공신력 중",
    3.0: "Tier 3 · 공신력 하",
    4.0: "Tier 4 · 공신력 최하",
}


def tier_key(tier) -> str:
    """data-tier · facet data-value · URL ?tier= 가 공유하는 표기.
    app.js 가 문자열 동등 비교를 하므로 포매터는 여기 하나만 둔다."""
    if tier is None:
        return ""
    return f"{float(tier):g}"               # 1.0 -> "1" · 1.5 -> "1.5"


def tier_label(tier) -> str:
    if tier is None:
        return "Tier ?"
    return f"Tier {tier_key(tier)}"
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_serve_layout.py -q -k "tier"`
Expected: PASS ( 3 passed )

- [ ] **Step 5: ops 버킷 라벨을 공신력 어휘로 바꾼다**

`src/bullet_in/serve/render.py:123-125` 의 `TIER_BUCKETS` 를 교체한다.

```python
TIER_BUCKETS = [(1.0, "Tier 1 — 공식 · 공신력 최상"),
                (2.0, "Tier 2 — 공신력 중"),
                (3.0, "Tier 3 — 공신력 하")]
```

`ETC_TIER_LABEL` ( 126행 ) 은 그대로 둔다.

- [ ] **Step 6: 소문자 `tier` 잔존을 찾아 고친다**

Run: `grep -rn "tier ?\|tier {\|\"tier \|1군\|2군\|ITK · 루머" src/bullet_in/serve/ tests/ docs/superpowers/specs/assets/`
`src/bullet_in/serve/templates/ops.html.j2:102` 의 `<h2>④ tier 분포 (전체 기사)</h2>` 를 `<h2>④ Tier 분포 (전체 기사)</h2>` 로 바꾼다.
`tests/test_serve_render.py:63` 의 `assert "tier 2" in html` 을 `assert "Tier 2" in html` 로 바꾼다.
`docs/superpowers/specs/assets/` 아래 목업은 과거 산출물이므로 **건드리지 않는다**.

- [ ] **Step 7: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: `test_facet_counts` 등 facet 관련은 아직 실패해도 된다 ( Task 3 에서 고친다 ).
`test_tier_label` · `test_serve_render.py::test_index_card_has_tier_chip` 계열은 PASS 여야 한다.

- [ ] **Step 8: 커밋**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/serve/templates/ops.html.j2 tests/test_serve_layout.py tests/test_serve_render.py
git commit -F - <<'EOF'
feat(serve): tier 문자열 계약 · Tier 표기 통일

data-tier 와 facet data-value 가 app.js 에서 문자열로 비교되는데 포매터가
갈라져 있어 1.5 를 넣으면 필터가 조용히 깨진다. 표기를 한 곳으로 모은다.

- tier_key(): 1.0 → "1" · 1.5 → "1.5" 최단 표기 · data-tier · URL 공유
- tier_label(): 소문자 tier → 대문자 Tier · int() 내림 제거
- TIER_ORDER · TIER_HEADINGS: 공신력 단일 척도 라벨 · 초기 노출 상한
- TIER_BUCKETS: ops 버킷도 동일 어휘 (1군 언론 · 2군 · ITK 루머 제거)

Refs: docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md §3.3 · §4.1

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 2: BBC 통합 — outlet 폴백 · bbc_gossip 설정

`outlet_display()` 가 `display_name` 으로 폴백해 `BBC Sport` · `BBC Football Gossip` 을 만드는데, 이 문자열은 `credibility.yaml` 에 없어 BBC 47건 중 46건이 tier 조회에 실패한다.
가운데에 `소스.outlet` 폴백을 넣고, 가십이 Tier 1 로 승격되지 않도록 `bbc_gossip` 의 `outlet` 을 제거한다.

**Files:**
- Modify: `src/bullet_in/serve/render.py:38-41` ( `outlet_display` )
- Modify: `config/sources.yaml` ( `bbc_gossip` 의 `outlet: BBC` 제거 )
- Test: `tests/test_serve_layout.py:20-24` ( 기존 `test_outlet_display_...` 에 케이스 추가 ) · `tests/test_credibility.py`

**Interfaces:**
- Consumes: 없음.
- Produces: `outlet_display(row, sources) -> str` — 폴백 사슬이 `기사.outlet` → `소스.outlet` → `소스.display_name` → `source_id` 로 바뀐다.
  Task 3 이 이 반환값을 facet 키로 쓴다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_serve_layout.py` 의 `test_outlet_display_prefers_outlet_then_displayname_then_id` ( 20–24행 ) 를 아래로 교체한다.

```python
def test_outlet_display_prefers_outlet_then_source_outlet_then_displayname_then_id():
    sources = {"bbc_sport": {"display_name": "BBC Sport", "outlet": "BBC"},
               "bbc_gossip": {"display_name": "BBC Football Gossip"}}
    # 기사에 실린 귀속 outlet 이 최우선
    assert outlet_display({"outlet": "The Athletic", "source_id": "x"}, sources) == "The Athletic"
    # 설정의 소스 outlet 으로 폴백 — BBC Sport 를 레지스트리 정식명 BBC 로 모은다
    assert outlet_display({"outlet": None, "source_id": "bbc_sport"}, sources) == "BBC"
    # 소스 outlet 이 없으면 display_name — 가십은 BBC 와 합치지 않는다
    assert outlet_display({"outlet": None, "source_id": "bbc_gossip"}, sources) == "BBC Football Gossip"
    assert outlet_display({"outlet": None, "source_id": "unknown"}, sources) == "unknown"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_layout.py -q -k outlet_display`
Expected: FAIL — `assert 'BBC Sport' == 'BBC'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/serve/render.py:38-41` 을 교체한다.

```python
def outlet_display(row: dict, sources: dict) -> str:
    """facet 키 · 카드 칩이 공유하는 언론사 표시명.
    소스 outlet 폴백이 없으면 display_name (BBC Sport) 이 키가 되는데
    이 문자열은 credibility.yaml 에 없어 tier 조회가 실패한다 (spec §3.4)."""
    src = sources.get(row.get("source_id"), {})
    return (row.get("outlet")
            or src.get("outlet")
            or src.get("display_name")
            or row.get("source_id") or "")
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_serve_layout.py -q -k outlet_display`
Expected: PASS

- [ ] **Step 5: 보정 중립 회귀 테스트를 쓴다**

`sources.yaml` 의 `outlet` 은 죽은 설정이 아니다.
`credibility.py:96` 의 소속 일치 보정이 `src.get("outlet")` 을 읽어 `min(j_tier, tier)` 승격을 건다.
`bbc_gossip` 에서 `outlet` 을 빼면 그 경로가 막히므로, 현재 동작이 중립임을 테스트로 고정한다.

`tests/test_credibility.py` 끝에 추가한다.

기존 `_item(source_id, payload)` 헬퍼 ( 26–28행 ) 를 그대로 쓴다.
`Registry` 를 import 목록 ( 4행 ) 에 추가한다.

```python
def test_gossip_without_source_outlet_keeps_tier_4():
    """bbc_gossip 의 outlet 제거로 소속 일치 보정 경로가 막힌다 (spec §3.4).
    통칭 라벨만 오는 현재 데이터에서는 결과가 중립임을 고정한다."""
    from bullet_in.credibility import Registry

    registry = Registry(journalists={"sami mokbel": 1.0},
                        outlets={"bbc": 1.0},
                        journalist_outlets={"sami mokbel": "BBC"})
    sources = {"bbc_gossip": {"tier": 4}}          # outlet 키 없음
    it = _item("bbc_gossip", {})

    # 통칭 라벨 — 등재 기자가 아니므로 보정이 걸리지 않는다
    assert resolve_tier(it, sources, registry, journalist="BBC Gossip") == 4.0
    # 등재 기자가 와도 소스 outlet 이 없으면 승격되지 않는다 (제거의 실제 효과)
    assert resolve_tier(it, sources, registry, journalist="Sami Mokbel") == 4.0
```

- [ ] **Step 6: 실패를 확인한다**

Run: `uv run pytest tests/test_credibility.py -q -k gossip`
Expected: PASS ( 설정 변경 전이라 이미 통과할 수 있다 — 이 테스트는 회귀 방지용 고정이다 )

- [ ] **Step 7: sources.yaml 을 고친다**

`config/sources.yaml` 의 `bbc_gossip` 블록에서 `outlet: BBC` 줄을 **삭제**한다 ( 39행 근처 ).
`bbc_sport` 의 `outlet: BBC` 는 **그대로 둔다**.
삭제한 줄 위에 주석을 남긴다.

```yaml
  - source_id: bbc_gossip
    display_name: BBC Football Gossip
    tier: 4
    # outlet 미지정 — 지정하면 facet 에서 BBC(Tier 1)로 합쳐져 가십 41건이 승격된다
    journalist_label: BBC Gossip
```

- [ ] **Step 8: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: facet 관련 실패만 남는다 ( Task 3 에서 고친다 ).

- [ ] **Step 9: 커밋**

```bash
git add src/bullet_in/serve/render.py config/sources.yaml tests/test_serve_layout.py tests/test_credibility.py
git commit -F - <<'EOF'
feat(serve): BBC 통합 — outlet 폴백 · 가십 분리

outlet_display 가 display_name 으로 폴백해 "BBC Sport" 를 facet 키로 만드는데
이 문자열이 credibility.yaml 에 없어 BBC 47건 중 46건이 tier 조회에 실패한다.
render.py:64 의 기자 정규화 주석이 경고하던 함정이 언론사에도 있었다.

- outlet_display: 기사.outlet → 소스.outlet → display_name 폴백 사슬 신설
- sources.yaml: bbc_gossip 의 outlet 제거 — 지정 시 가십 41건이 Tier 1 로 승격
- 회귀 고정: outlet 제거가 credibility.py:96 소속 일치 보정 경로를 막지만
  통칭 라벨만 오는 현재 데이터에선 결과 중립임을 테스트로 못박음
- 파급: BBC Sport 기사의 출처 칩이 "BBC" 로 표기 (의도된 변경)

Refs: docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md §3.4

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 3: facet_counts 재설계 — tier 그룹 · 더보기 단계

facet 뷰모델을 tier 그룹 · 더보기 단계까지 계산해 내려보낸다.
tier 조회에 레지스트리가 필요하므로 `registry` 를 인자로 받는다.

**Files:**
- Modify: `src/bullet_in/serve/render.py:83-118` ( `facet_counts` ) · `:336-343` ( `render_index` ) · `:357-361` ( `render_article` 폴백 ) · `:371-380` ( `write_site` )
- Modify: `src/bullet_in/run.py:96-97` ( `write_site` 호출 )
- Test: `tests/test_serve_layout.py:40-51` ( 기존 `test_facet_counts` 교체 )

**Interfaces:**
- Consumes: Task 1 의 `tier_key` · `TIER_ORDER` · `TIER_HEADINGS` · `INITIAL_MAX_TIER`. Task 2 의 `outlet_display`.
- Produces: `facet_counts(articles, sources, directory=None, registry=None) -> dict` 가 아래 모양을 낸다.
  Task 4 의 템플릿이 이 키들을 그대로 읽는다.

```python
{
  "total": int,
  "team": {"arsenal": int},
  "stage": {enum: int},
  "other": int,
  "tiers": [{"key": "0", "label": "Tier 0", "count": int}, ...],       # 신뢰도 facet
  "outlets": {
     "initial": [{"key": "1", "heading": "Tier 1 · 공신력 최상",
                  "items": [{"value": "BBC", "label": "BBC", "count": 7}]}],
     "stages":  [{"label": "더보기 · Tier 2", "groups": [...], "unregistered": []}],
  },
  "journalists": {"initial": [...], "stages": [...]},                   # 같은 모양
}
```

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_serve_layout.py` 의 `test_facet_counts` ( 40–51행 ) 를 아래로 교체한다.

```python
class _Reg:
    """facet_counts 가 쓰는 최소 레지스트리 (Registry 의 .outlets · .journalists 만)."""
    def __init__(self, outlets=None, journalists=None):
        self.outlets = outlets or {}
        self.journalists = journalists or {}

def test_facet_counts_groups_outlets_by_tier_then_name():
    arts = [
        {"source_id": "bbc", "outlet": None, "tier": 1, "team": "arsenal"},
        {"source_id": "ath", "outlet": "The Athletic", "tier": 1, "team": "arsenal"},
        {"source_id": "ath", "outlet": "The Athletic", "tier": 1, "team": "arsenal"},
        {"source_id": "ath", "outlet": "The Athletic", "tier": 1, "team": "arsenal"},
    ]
    sources = {"bbc": {"display_name": "BBC Sport", "outlet": "BBC", "tier": 1},
               "ath": {"display_name": "afcstuff"}}
    reg = _Reg(outlets={"bbc": 1.0, "the athletic": 1.0})
    f = facet_counts(arts, sources, registry=reg)

    t1 = [g for g in f["outlets"]["initial"] if g["key"] == "1"][0]
    # 건수는 BBC 1 < The Athletic 3 이지만 이름 오름차순이 이긴다
    assert [i["value"] for i in t1["items"]] == ["BBC", "The Athletic"]
    assert t1["heading"] == "Tier 1 · 공신력 최상"

def test_facet_counts_unregistered_goes_last_by_name():
    arts = [
        {"source_id": "af", "outlet": None, "tier": 4, "team": "arsenal"},
        {"source_id": "af", "outlet": None, "tier": 4, "team": "arsenal"},
        {"source_id": "sun", "outlet": "The Sun", "tier": 4, "team": "arsenal"},
    ]
    sources = {"af": {"display_name": "afcstuff (aggregator)"},   # tier 없음 → 미등재
               "sun": {"display_name": "The Sun", "tier": 4}}
    f = facet_counts(arts, sources, registry=_Reg(outlets={"the sun": 4.0}))
    last = f["outlets"]["stages"][-1]
    assert last["label"] == "더보기 · Tier 4 · 미등재"
    assert [i["value"] for i in last["unregistered"]] == ["afcstuff (aggregator)"]

def test_facet_counts_skips_empty_tier_stages():
    # Tier 1 과 Tier 3 만 존재 → 첫 더보기는 Tier 2 를 건너뛰고 Tier 3 을 연다
    arts = [
        {"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal"},
        {"source_id": "b", "outlet": "The Times", "tier": 3, "team": "arsenal"},
    ]
    sources = {"a": {}, "b": {}}
    reg = _Reg(outlets={"bbc": 1.0, "the times": 3.0})
    f = facet_counts(arts, sources, registry=reg)
    assert [s["label"] for s in f["outlets"]["stages"]] == ["더보기 · Tier 3"]

def test_facet_counts_tiers_include_one_point_five():
    arts = [
        {"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal"},
        {"source_id": "a", "outlet": "Sky Sports", "tier": 1.5, "team": "arsenal"},
    ]
    f = facet_counts(arts, {"a": {}}, registry=_Reg())
    rows = {t["key"]: t["count"] for t in f["tiers"]}
    assert rows == {"0": 0, "1": 1, "1.5": 1, "2": 0, "3": 0, "4": 0}
    assert [t["label"] for t in f["tiers"]][:3] == ["Tier 0", "Tier 1", "Tier 1.5"]

def test_facet_counts_journalist_tier_from_registry():
    arts = [{"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal",
             "journalist": "온스테인"},
            {"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal",
             "journalist": "Kaya Kaynak"}]
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}
    reg = _Reg(journalists={"온스테인": 1.0, "david ornstein": 1.0})
    f = facet_counts(arts, {"a": {}}, directory=directory, registry=reg)
    t1 = [g for g in f["journalists"]["initial"] if g["key"] == "1"][0]
    assert [i["label"] for i in t1["items"]] == ["David Ornstein (The Athletic)"]
    assert f["journalists"]["stages"][-1]["unregistered"][0]["value"] == "Kaya Kaynak"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_layout.py -q -k facet_counts`
Expected: FAIL — `TypeError: facet_counts() got an unexpected keyword argument 'registry'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/serve/render.py` 의 `facet_counts` ( 83–118행 ) 를 통째로 교체한다.

```python
def _outlet_tier(key: str, row: dict, sources: dict, registry) -> float | None:
    """등재 tier 우선, 없으면 소스 설정 tier (spec §3.4)."""
    if registry is not None:
        t = registry.outlets.get(key.lower())
        if t is not None:
            return float(t)
    t = sources.get(row.get("source_id"), {}).get("tier")
    return float(t) if t is not None else None


def _journalist_tier(row: dict, entry: dict, registry) -> float | None:
    if not entry["registered"] or registry is None:
        return None
    j = (row.get("journalist") or "").strip().lower()
    t = registry.journalists.get(j)
    if t is None:
        t = registry.journalists.get(entry["name"].lower())
    return float(t) if t is not None else None


def _facet_rows(counts: Counter, labels: dict, tiers: dict) -> dict:
    """tier 그룹 · 더보기 단계로 나눈 facet 뷰모델 (spec §3.1 · §3.2).
    TIER_ORDER 에 없는 tier (설정 오류) 는 미등재로 흘려보낸다."""
    def _item(n, c):
        return {"value": n, "label": labels.get(n, n), "count": c}

    def _sorted(pairs):
        return [_item(n, c) for n, c in sorted(pairs, key=lambda kv: kv[0].lower())]

    reg = [(n, c) for n, c in counts.items() if tiers.get(n) in TIER_ORDER]
    unreg = _sorted([(n, c) for n, c in counts.items() if tiers.get(n) not in TIER_ORDER])

    groups = {t: {"key": tier_key(t), "heading": TIER_HEADINGS[t],
                  "items": _sorted([x for x in reg if tiers[x[0]] == t])}
              for t in TIER_ORDER}

    initial = [groups[t] for t in TIER_ORDER
               if t <= INITIAL_MAX_TIER and groups[t]["items"]]

    rest = [t for t in TIER_ORDER if t > INITIAL_MAX_TIER]
    stages = []
    for t in rest:
        g = groups[t]
        is_last = (t == rest[-1])
        tail = unreg if is_last else []
        if not g["items"] and not tail:
            continue                        # 빈 tier 는 단계에서 건너뛴다
        if g["items"] and tail:
            label = f"더보기 · Tier {tier_key(t)} · 미등재"
        elif g["items"]:
            label = f"더보기 · Tier {tier_key(t)}"
        else:
            label = "더보기 · 미등재"
        stages.append({"label": label,
                       "groups": [g] if g["items"] else [],
                       "unregistered": tail})
    return {"initial": initial, "stages": stages}


def facet_counts(articles: list[dict], sources: dict, directory: dict | None = None,
                 registry=None) -> dict:
    teams = Counter(a.get("team") or "arsenal" for a in articles)

    o_ctr: Counter = Counter()
    o_tier: dict = {}
    for a in articles:
        key = outlet_display(a, sources)
        o_ctr[key] += 1
        o_tier[key] = _outlet_tier(key, a, sources, registry)

    j_ctr: Counter = Counter()
    j_labels: dict = {}
    j_tier: dict = {}
    for a in articles:
        e = journalist_entry(a, sources, directory)
        if e is None:
            continue
        j_ctr[e["name"]] += 1
        j_labels[e["name"]] = e["label"]
        j_tier[e["name"]] = _journalist_tier(a, e, registry)

    seen = Counter(tier_key(a.get("tier")) for a in articles if a.get("tier") is not None)
    tiers = [{"key": tier_key(t), "label": tier_label(t), "count": seen.get(tier_key(t), 0)}
             for t in TIER_ORDER]

    stage_counts = {e: 0 for e, _, _ in _stage.SIDEBAR_STAGES}
    other_count = 0
    for a in articles:
        s = a.get("transfer_stage")
        if s in stage_counts:
            stage_counts[s] += 1
        else:
            other_count += 1

    return {"total": len(articles), "team": dict(teams),
            "tiers": tiers, "stage": stage_counts, "other": other_count,
            "outlets": _facet_rows(o_ctr, {}, o_tier),
            "journalists": _facet_rows(j_ctr, j_labels, j_tier)}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_serve_layout.py -q -k facet_counts`
Expected: PASS ( 5 passed )

- [ ] **Step 5: registry 를 렌더 경로에 통과시킨다**

`render_index` ( 336–343행 ) · `write_site` ( 371–380행 ) 에 `registry=None` 을 추가하고 `facet_counts` 로 넘긴다.

```python
def render_index(articles: list[dict], sources: dict, now: datetime,
                 directory: dict | None = None, registry=None) -> str:
    ordered = [_decorate(a, sources, now, directory=directory)
               for a in _sorted_latest(articles)]
    facets = facet_counts(articles, sources, directory=directory, registry=registry)
    return _env().get_template("index.html.j2").render(
        articles=ordered, facets=facets, active="home", root="")
```

```python
def write_site(articles: list[dict], sources: dict, out_dir: str | Path,
               now: datetime | None = None,
               directory: dict | None = None, registry=None) -> None:
```

`write_site` 안의 두 호출을 고친다.

```python
    (out / "index.html").write_text(
        render_index(articles, sources, now, directory=directory, registry=registry),
        encoding="utf-8")
```

```python
    facets = facet_counts(articles, sources, directory=directory, registry=registry)
```

`render_article` 의 폴백 facets ( 358–361행 ) 를 새 모양으로 교체한다.

```python
    if facets is None:
        facets = {"team": {}, "tiers": [], "total": 0, "stage": {}, "other": 0,
                  "outlets": {"initial": [], "stages": []},
                  "journalists": {"initial": [], "stages": []}}
```

- [ ] **Step 6: run.py 배선을 고친다**

`src/bullet_in/run.py:96-97` 을 교체한다. `registry` 는 같은 함수 37행에서 이미 로드돼 있다 — 스코프를 눈으로 확인한다.

```python
    write_site(rows, sources, "site",
               directory=journalist_directory("config/credibility.yaml"),
               registry=registry)
```

- [ ] **Step 7: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 템플릿이 아직 옛 키를 읽어 `test_serve_render.py` 가 실패한다 ( Task 4 에서 고친다 ).
`test_serve_layout.py` 는 전부 PASS 여야 한다.

- [ ] **Step 8: 커밋**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/run.py tests/test_serve_layout.py
git commit -F - <<'EOF'
feat(serve): facet_counts tier 그룹화 · 더보기 단계 산출

facet 정렬이 건수순이라 football.london 205건(Tier 4)이 The Athletic
12건(Tier 1) 위에 선다. tier 그룹·단계까지 계산한 뷰모델을 내려보낸다.

- 정렬: tier → 이름 오름차순 · 미등재 구간도 이름순 (_ranked 건수순 대체)
- 더보기 단계: 초기 Tier 1.5 까지 · 빈 tier 건너뜀 · 마지막에 미등재 동반
- tier 조회: 등재 tier 우선 · 소스 설정 tier 폴백 · 그 외 미등재
- 신뢰도 facet: tiers 를 TIER_ORDER 리스트로 — Tier 1.5 신설 · int() 내림 제거
- registry 배선: run.py → write_site → render_index → facet_counts

Refs: docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md §3.1 · §3.2 · §3.7

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 4: 템플릿 · CSS — Tier 헤더 · 구분선 · 더보기

뷰모델을 그대로 그린다.
언론사 · 기자 facet 이 같은 모양이므로 Jinja 매크로 하나로 처리한다.

**Files:**
- Modify: `src/bullet_in/serve/templates/_layout.html.j2:39-60`
- Modify: `src/bullet_in/serve/templates/index.html.j2:9` ( `data-tier` )
- Modify: `src/bullet_in/serve/static/style.css:48` 근처
- Modify: `src/bullet_in/serve/render.py:292-327` ( `_decorate` 의 `data-tier` 용 키 )
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: Task 3 의 facets 뷰모델 · Task 1 의 `tier_key`.
- Produces: DOM 계약 — `.facetgroup` 스코프 · `.morestage` ( 접힌 단계 ) · `.morebtn[data-stage-btn]` ( 단계 버튼 ). Task 5 의 `app.js` 가 이 클래스들을 잡는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_serve_render.py` 끝에 추가한다.
기존 `test_sidebar_shows_registered_journalists_and_more_toggle` ( 345행 근처 ) 는 `#jmore` 구조를 검사하므로 **삭제**한다.

```python
def test_sidebar_renders_tier_heading_and_initial_only():
    rows = [_row(content_hash="h1", journalist="온스테인", outlet="The Athletic", tier=1),
            _row(content_hash="h2", journalist="Kaya Kaynak", outlet="The Sun", tier=4)]
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}

    class _Reg:
        outlets = {"the athletic": 1.0, "the sun": 4.0}
        journalists = {"온스테인": 1.0, "david ornstein": 1.0}

    html = render_index(rows, SOURCES, NOW, directory=directory, registry=_Reg())
    assert "Tier 1 · 공신력 최상" in html
    assert 'data-group="outlet" data-value="The Athletic"' in html
    # Tier 4 는 접힌 단계 안에 있고 버튼이 그것을 예고한다
    assert "더보기 · Tier 4 · 미등재" in html
    assert 'class="morestage"' in html

def test_index_card_data_tier_keeps_one_point_five():
    html = render_index([_row(tier=1.5)], SOURCES, NOW)
    assert 'data-tier="1.5"' in html

def test_sidebar_tier_facet_lists_one_point_five():
    html = render_index([_row(tier=1.5)], SOURCES, NOW)
    assert 'data-group="tier" data-value="1.5"' in html
    assert "Tier 1.5" in html

def test_layout_emits_no_whitespace_before_doctype():
    """매크로 정의를 {% endmacro %} 로 닫으면 개행이 새어나와 doctype 앞에 붙는다.
    눈에 안 띄는 회귀라 고정한다 — {% endmacro -%} 를 쓸 것."""
    html = render_index([_row()], SOURCES, NOW)
    assert html.startswith("<!doctype html>")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_render.py -q -k "tier_heading or one_point_five"`
Expected: FAIL — 템플릿이 옛 키를 읽어 `UndefinedError` 또는 assert 실패

- [ ] **Step 3: `_decorate` 에 tier 키를 추가한다**

`src/bullet_in/serve/render.py` 의 `_decorate` 에서 `a["_tier_label"]` 줄 ( 297행 ) 아래에 한 줄 추가한다.

```python
    a["_tier_key"] = tier_key(row.get("tier"))
```

- [ ] **Step 4: index.html.j2 의 data-tier 를 교체한다**

`src/bullet_in/serve/templates/index.html.j2:9` 를 교체한다.

```jinja
     data-tier="{{ a._tier_key }}"
```

- [ ] **Step 5: _layout.html.j2 의 facet 블록을 교체한다**

`src/bullet_in/serve/templates/_layout.html.j2` 의 39–60행 ( `<h4>소스 (언론사)</h4>` 부터 신뢰도 facet 끝까지 ) 을 교체한다.
매크로는 1행 `<!doctype html>` **바로 위**에 정의한다.

**검증된 사항 · 그대로 따를 것** — 이 배치는 실제 Jinja 렌더로 확인했다.

- `_layout.html.j2` 는 `{% extends %}` 되는 **부모**이므로, 최상단 매크로가 자기 `<aside>` 안에서 정상적으로 잡힌다.
- `{% endmacro %}` 를 **`{% endmacro -%}` 로 써야 한다**.
  `-%}` 를 빼면 정의 뒤 개행이 그대로 출력돼 `<!doctype html>` 앞에 빈 줄 3개가 붙는다 ( `_env()` 가 `trim_blocks` 를 안 켠다 ).
  `-%}` 를 넣으면 doctype 이 첫 문자로 붙는다.

```jinja
{% macro facet_opts(group, items) %}
  {% for it in items %}
  <label class="opt"><input type="checkbox" data-group="{{ group }}" data-value="{{ it.value }}"> {{ it.label }} <span class="ct">{{ it.count }}</span></label>
  {% endfor %}
{% endmacro -%}
{% macro facet_block(group, data) %}
<div class="facetgroup">
  {% for g in data.initial %}
  <div class="tierhead">{{ g.heading }}</div>
  {{ facet_opts(group, g["items"]) }}
  {% endfor %}
  {% for st in data.stages %}
  <div class="morestage" hidden>
    {% for g in st.groups %}
    <div class="tierhead">{{ g.heading }}</div>
    {{ facet_opts(group, g["items"]) }}
    {% endfor %}
    {% if st.unregistered %}
    <div class="unreghead"><span>미등재</span></div>
    {{ facet_opts(group, st.unregistered) }}
    {% endif %}
  </div>
  <button class="morebtn" type="button" hidden>{{ st.label }}</button>
  {% endfor %}
</div>
{% endmacro -%}
```

39–60행을 아래로 교체한다.

```jinja
    <h4>소스 (언론사)</h4>
    {{ facet_block('outlet', facets.outlets) }}

    <h4>기자</h4>
    {{ facet_block('journalist', facets.journalists) }}

    <h4>신뢰도 (Tier)</h4>
    {% for t in facets.tiers %}
    <label class="opt"><input type="checkbox" data-group="tier" data-value="{{ t.key }}"> {{ t.label }} <span class="ct">{{ t.count }}</span></label>
    {% endfor %}
```

- [ ] **Step 6: CSS 를 추가한다**

`src/bullet_in/serve/static/style.css` 의 `.morebtn` 규칙 ( 48행 ) 앞에 추가한다.

```css
.tierhead{margin:9px 0 3px;padding:0 9px;font-size:10px;letter-spacing:.07em;color:var(--muted);text-transform:uppercase}
.facetgroup>.tierhead:first-child{margin-top:2px}
.unreghead{display:flex;align-items:center;gap:7px;margin:10px 0 3px;padding:0 9px;font-size:10px;letter-spacing:.06em;color:var(--muted)}
.unreghead::before,.unreghead::after{content:"";flex:1;height:1px;background:var(--line)}
```

- [ ] **Step 7: 통과를 확인한다**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: PASS. 실패하면 매크로 정의 위치 ( `_layout.html.j2` 최상단 ) 와 `data.initial` · `st.groups` 키 이름을 Task 3 의 Interfaces 블록과 대조한다.

- [ ] **Step 8: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 전부 PASS ( 통합 테스트 skip 은 정상 )

- [ ] **Step 9: 커밋**

```bash
git add src/bullet_in/serve/templates/_layout.html.j2 src/bullet_in/serve/templates/index.html.j2 src/bullet_in/serve/static/style.css src/bullet_in/serve/render.py tests/test_serve_render.py
git commit -F - <<'EOF'
feat(serve): facet Tier 헤더 · 미등재 구분선 · 단계 더보기 렌더

Task 3 의 뷰모델을 그린다. 언론사·기자 facet 이 같은 모양이라 Jinja
매크로 하나로 처리하고, 접힌 단계와 버튼은 app.js 가 잡을 DOM 계약을 남긴다.

- facet_block 매크로: 언론사·기자 공용 · Tier 헤더 + 접힌 단계 + 단계 버튼
- 미등재 구분선: unreghead 의 ::before/::after 로 좌우 선
- data-tier: int() 내림 제거 → _tier_key 로 1.5 보존
- 신뢰도 facet: range(5) → facets.tiers 순회로 Tier 1.5 노출
- 제거: #jmore 이분법 토글 (등재/미등재 단일 버튼)

Refs: docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md §3.2 · §4.2

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 5: app.js — 단계 전개

`#jmore` 이분법 토글을 단계 전개로 바꾼다.
`enabledBoxes()` 가 접힌 체크박스도 포함하므로, 접힌 단계에 체크된 필터가 있으면 그 단계까지 펼치는 기존 가드 ( 58–59행 ) 를 유지해야 한다.

**Files:**
- Modify: `src/bullet_in/serve/static/app.js:30-33` · `:58-59` · `:119-120`
- Test: `tests/test_serve_render.py:18` ( 기존 `jmoreBtn` 단언 교체 )

**Interfaces:**
- Consumes: Task 4 의 `.facetgroup` · `.morestage` · `.morebtn`.
- Produces: 없음 ( 종단 ).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_serve_render.py` 의 `test_static_assets_exist_and_nonempty` 18행을 교체한다.
이 단언은 옛 토글을 검사하므로 그대로 두면 Task 5 가 끝나는 순간 깨진다.

```python
    assert "morestage" in js and "facetgroup" in js   # tier 단계 전개 계약
    assert "jmore" not in js                          # 옛 이분법 토글 제거
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_render.py -q -k static_assets`
Expected: FAIL — `assert 'morestage' in js`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/serve/static/app.js:30-33` 을 교체한다.

```js
// tier 단계 더보기 — 초기 Tier 1.5 까지, 클릭마다 다음 단계 (spec §3.2)
function setupMore(scope) {
  const stages = [...scope.querySelectorAll('.morestage')];
  const btns = [...scope.querySelectorAll('.morebtn')];
  let open = 0;                                  // 열린 단계 수
  const sync = () => {
    stages.forEach((s, i) => { s.hidden = i >= open; });
    btns.forEach((b, i) => { b.hidden = i !== open; });
  };
  btns.forEach((b, i) => { b.onclick = () => { open = i + 1; sync(); }; });
  // 접힌 단계에 체크된 필터가 있으면 거기까지 펼친다 (보이지 않는 필터 방지)
  stages.forEach((s, i) => { if (s.querySelector('input:checked')) open = Math.max(open, i + 1); });
  sync();
}
const setupAllMore = () =>
  document.querySelectorAll('.facetgroup').forEach(setupMore);
```

`restoreFromQuery()` 안의 58–59행 두 줄을 **삭제**한다 ( 가드가 `setupMore` 로 옮겨갔다 ).

```js
  // 접힌 더보기 안의 기자가 선택돼 있으면 펼친다 (보이지 않는 필터 방지)
  if (jmore && jmore.querySelector('input:checked')) expandMore();
```

- [ ] **Step 4: 전개 시점을 배선한다**

`app.js` 의 인덱스 분기 ( 119–120행 ) 를 교체한다.
`setupAllMore()` 는 `restoreFromQuery()` **뒤에** 불러야 복원된 체크 상태를 보고 펼칠 수 있다.

```js
  if (restoreFromQuery()) { setupAllMore(); applyFilters(); }  // 상세에서 넘어온 필터 상태 복원 · 적용
  else { setupAllMore(); sortCards(); }                        // 초기 정렬(최신순)
```

상세 페이지 분기 ( 121행 `} else {` 이후 ) 의 `if (side) side.addEventListener(...)` 줄 **위**에 추가한다.

```js
  setupAllMore();
```

- [ ] **Step 5: 통과를 확인한다**

Run: `uv run pytest tests/test_serve_render.py -q -k static_assets`
Expected: PASS

- [ ] **Step 6: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/serve/static/app.js tests/test_serve_render.py
git commit -F - <<'EOF'
feat(serve): 더보기를 tier 단계 전개로 교체

기자 facet 의 등재/미등재 이분법 토글을 tier 단계 전개로 바꾼다.
enabledBoxes() 가 접힌 체크박스도 필터에 넣으므로 '보이지 않는 필터'
가드를 단계 단위로 옮겨 유지한다.

- setupMore(): facetgroup 스코프별 단계 전개 · 버튼 하나만 노출
- 복원 가드: 접힌 단계에 체크된 필터가 있으면 그 단계까지 자동 전개
- 배선: restoreFromQuery 뒤에 호출 — 복원된 체크 상태를 보고 펼침
- 제거: jmore · expandMore 이분법 토글

Refs: docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md §3.2

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 6: Tom Canton Tier 4 등재

football.london 스태프 중 물량이 가장 많고 ( 58건 ) 쓸 만해 남기기로 한 기자를 등재한다.
소속 tier 와 소스 tier 가 둘 다 4라 `min(4, 4) = 4` 로 기사 tier 는 변하지 않는다.

**Files:**
- Modify: `config/credibility.yaml` ( `journalists` 목록 )
- Test: `tests/test_credibility.py`

**Interfaces:**
- Consumes: 없음.
- Produces: 없음 ( config 변경 ).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_credibility.py` 끝에 추가한다.

기존 `_item` 헬퍼와 `REG` 상수 ( 7행 ) 를 그대로 쓴다.
`journalist_directory` 를 import 목록 ( 4행 ) 에 추가한다.

```python
def test_tom_canton_registered_tier_4_is_neutral():
    """등재해도 기사 tier 는 안 바뀐다 — min(4, 4) = 4 (spec §3.6)."""
    from bullet_in.credibility import journalist_directory

    registry = load_registry(REG)
    assert registry.journalists["tom canton"] == 4.0
    assert registry.journalist_outlets["tom canton"] == "football.london"

    sources = {"football_london": {"tier": 4, "outlet": "football.london"}}
    it = _item("football_london", {})
    assert resolve_tier(it, sources, registry, journalist="Tom Canton") == 4.0

    # 기자 facet 에서 미등재 구간을 벗어난다
    d = journalist_directory(REG)
    assert d["tom canton"]["name"] == "Tom Canton"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_credibility.py -q -k tom_canton`
Expected: FAIL — `KeyError: 'tom canton'`

- [ ] **Step 3: 등재한다**

`config/credibility.yaml` 의 `journalists` 목록 끝 ( `Art de Roché` 줄 다음, `outlets:` 앞 ) 에 추가한다.

```yaml
  - {name: Tom Canton,        tier: 4,   outlet: football.london, aliases: ["톰 캔턴"]}
```

`aliases` 는 `_build()` 가 요구하는 필드다.
`load_registry` 가 `duplicate alias` 로 죽으면 기존 별칭과 충돌한 것이니 별칭을 조정한다.

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_credibility.py -q -k tom_canton`
Expected: PASS

- [ ] **Step 5: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add config/credibility.yaml tests/test_credibility.py
git commit -F - <<'EOF'
chore(credibility): Tom Canton 4티어 등재

football.london 스태프 중 물량이 가장 많고(58건) 남기기로 한 기자를
등재해 기자 facet 의 미등재 구간에서 Tier 4 로 옮긴다.

- 등재: Tom Canton · tier 4 · 소속 football.london
- tier 중립: 소속 tier 와 소스 tier 가 둘 다 4 → min(4,4)=4 로 기사 tier 무변화
- 라벨 무변화: journalist_entry 가 이미 "Tom Canton (football.london)" 생성
- 효과: 미등재 56명 → 55명

Refs: docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md §3.6

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 7: 육안 검증 — 실데이터 렌더

단위 테스트는 모킹이라 실제 사이드바가 스펙 §5 투영과 맞는지 못 잡는다.
`config/sources.yaml` · `credibility.yaml` 변경이 실데이터에서 의도대로 작동하는지 확인한다.

**Files:**
- 변경 없음 ( 검증 전용 )

**Interfaces:**
- Consumes: Task 1–6 전부.
- Produces: 없음.

- [ ] **Step 1: 실데이터로 사이드바를 렌더한다**

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from datetime import datetime
from sqlalchemy import create_engine, text
import yaml
from bullet_in.credibility import load_registry, journalist_directory
from bullet_in.serve.render import facet_counts

src = yaml.safe_load(open("config/sources.yaml"))
sources = {s["source_id"]: s for s in src["sources"]}
with create_engine(os.environ["MARIADB_URL"]).connect() as c:
    rows = [dict(r) for r in c.execute(text(
        "SELECT source_id,outlet,journalist,tier,team,transfer_stage FROM articles")).mappings()]
f = facet_counts(rows, sources,
                 directory=journalist_directory("config/credibility.yaml"),
                 registry=load_registry("config/credibility.yaml"))
for name in ("outlets", "journalists"):
    print("===", name, "===")
    for g in f[name]["initial"]:
        print(" ", g["heading"])
        for i in g["items"]:
            print("    %-34s %d" % (i["label"], i["count"]))
    for st in f[name]["stages"]:
        print("  [", st["label"], "]")
        for g in st["groups"]:
            print("   ", g["heading"])
            for i in g["items"]:
                print("      %-32s %d" % (i["label"], i["count"]))
        if st["unregistered"]:
            print("    --- 미등재", len(st["unregistered"]), "항목 ---")
print("=== tiers ===", [(t["label"], t["count"]) for t in f["tiers"]])
PY
```

- [ ] **Step 2: 스펙 §5 투영과 대조한다**

아래가 전부 맞아야 한다. 하나라도 어긋나면 멈추고 원인을 찾는다.

- 언론사 Tier 1 이 `BBC 7` → `The Athletic 12` 순 ( 건수 역순이 아님 )
- `BBC Football Gossip 41` 이 Tier 4 ( Tier 1 로 승격되지 않음 )
- 언론사 미등재가 `afcstuff (aggregator) 13` 하나
- 기자 Tier 1 이 `David Ornstein (The Athletic) 3` → `Sami Mokbel (BBC) 6` 순
- 기자 첫 더보기 라벨이 `더보기 · Tier 3` ( Tier 2 가 0명이라 건너뜀 )
- `Tom Canton (football.london) 58` 이 Tier 4
- 기자 미등재가 55항목
- `tiers` 가 `Tier 0 5 · Tier 1 19 · Tier 1.5 13 · Tier 2 5 · Tier 3 1 · Tier 4 265`

- [ ] **Step 3: 브라우저에서 상호작용을 확인한다**

```bash
uv run python -m bullet_in.run --concurrency 8
open site/index.html
```

- 더보기를 끝까지 눌러 단계가 하나씩 열리는지
- `Tier 1.5` 체크박스가 Sky Sports 기사만 남기는지
- 카드 칩이 `Tier 1` 대문자인지 · BBC Sport 기사 칩이 `BBC` 인지
- URL 에 `?tier=1.5` 가 남고, 그 URL 로 새로 열면 필터가 복원되는지
- 접힌 단계의 기자를 URL 로 지정하면 ( 예 `?journalist=Tom+Canton` ) 그 단계까지 자동으로 펼쳐지는지

- [ ] **Step 4: 계획 · 스펙 이탈을 기록한다**

구현 중 스펙과 달라진 게 있으면 `docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md` 를 고쳐 실제와 맞춘다.
새로 밟은 함정이 있으면 `docs/troubleshooting/2026-07-16-<주제>.md` 로 남긴다.

- [ ] **Step 5: 커밋 ( 문서 변경이 있을 때만 )**

```bash
git add docs/
git commit -F - <<'EOF'
docs(serve): facet tier 정렬 육안 검증 결과 반영

Refs: docs/superpowers/plans/2026-07-16-facet-tier-ordering.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## 범위 밖 ( 이 계획에서 하지 않는다 )

- **football.london 147건 서빙 숨기기** — 트랙 ③.
  정렬 키가 tier → 이름이라 건수가 바뀌어도 순서는 안 바뀌므로 두 트랙은 독립이다.
- **`arsenal_official` 소스가 기사를 0건 생산 중인 문제** — 별건.
  현재 `Arsenal.com` 5건은 전부 fmkorea 가 `[공홈]` 말머리로 귀속시킨 것이다.
- **접기 버튼** — YAGNI.
- **`docs/superpowers/specs/assets/` 아래 과거 목업의 tier 표기** — 과거 산출물이라 건드리지 않는다.
