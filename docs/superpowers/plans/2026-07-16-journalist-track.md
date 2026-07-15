# 기자 중심 트랙 구현 계획 (2026-07-16)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기사 페이지에서 저자를 추출해 저장하고, 소속 일치 등재 기자 기준으로 tier를 보정하며, 사이드바 기자 facet과 상세 → 필터된 인덱스 이동을 구현한다.

**Architecture:** 공통 파서 `extract_authors` (meta.py) 가 JSON-LD → meta author 체인으로 저자 목록을 뽑아 어댑터가 `raw_payload["authors"]`로 싣고, `pipeline.select_journalist`가 대표 1명을 골라 `resolve_tier`에 넘긴다.
레지스트리는 기자별 `outlet` 소속을 갖고, 소속이 기사 소스와 일치하는 등재 기자에만 `min(기자 tier, 소스 tier)` 가드를 적용한다.
서빙은 단일 조회 맵 `journalist_directory`로 alias → 정식명 정규화 · 등재 판정 · 언론사 라벨을 한 번에 해결하고, 필터 상태는 URL 쿼리로 직렬화해 상세 → 인덱스로 전달한다.

**Tech Stack:** Python 3.11 · uv · pytest · respx · BeautifulSoup · SQLAlchemy (MariaDB) · Jinja2 · 바닐라 JS.

**Spec:** `docs/superpowers/specs/2026-07-16-journalist-track-design.md`

**Branch:** `feat/journalist-track` — 이미 존재 (spec 커밋 `35f627d` 포함), 그대로 이어서 작업한다.

**계획 수립 중 스펙 개정 2건** (스펙 파일에 반영 완료 — 초안 대비 차이):

- 백필 경로: `scripts/backfill_journalist.py` → `src/bullet_in/backfill_journalist.py` (`python -m bullet_in.backfill_journalist`).
  `scripts/`는 설치 패키지 밖이라 테스트에서 import 가 불가능하고 (sys.path 조작 필요), 저장소에 이미 패키지 내 CLI 전례 (`bullet_in.benchmark` · `bullet_in.run`) 가 있다.
- 백필 재fetch 대상 조건에 `adapter == "html"` 추가 — fmkorea 가 `body_selector` 를 가져 조건 누락 시 재fetch 대상에 섞이고 2h 접근 규칙을 깬다.

## Global Constraints

- **기자는 부가 정보** — 저자 추출 실패는 기사 수집을 절대 막지 않는다 (파서가 빈 목록 폴백, `journalist` NULL).
- **tier 보정 조건 (스펙 §2)**: 등재 기자이고 `outlet` 소속이 기사 소스의 `outlet`과 **일치할 때만** `min(기자 tier, 소스 tier)`.
  프리랜서 (`outlet` 미지정 — Watts · Romano) · 미등재 기자는 표시 전용, tier 무조정.
- **동적 소스 (`credibility: x_mentions` · `fmkorea`) 경로는 무변경** — 기존 `resolve_tier` 분기를 건드리지 않는다.
- **추가 네트워크 요청 0회** (수집 경로) — 이미 받아온 응답에서만 저자를 뽑는다.
- **통칭**: arsenal_official → `Arsenal Official`, bbc_gossip → `BBC Gossip`. 통칭은 미등재 취급 → facet 더보기 그룹, 라벨 괄호 생략.
- **facet · 카드 · 필터의 기자 키는 항상 정규화된 정식명** — 체크박스 `data-value`와 카드 `data-journalist`가 다르면 필터가 조용히 깨진다.
- 기존 스타일 준수: 어댑터 테스트는 respx 모킹 (`tests/test_html_adapter.py` 패턴), DB 테스트는 `tests/integration/` (DB 없으면 skip), 테스트는 CWD = 저장소 루트 가정.
- 실행 전 `set -a; source .env; set +a` 필수 (dotenv 미사용).
- fmkorea 라이브 접근 2h 간격 — 이 트랙은 fmkorea를 건드리지 않으므로 해당 없음.
- 커밋: 컨벤션 §1.1 (도입 1–2문장 + 명사형 불릿) · §1.3 (트레일러 = 실제 작업 모델).
  아래 커밋 블록의 트레일러는 실제 실행 모델로 맞춘다 (설계 · 구현이 같은 모델이면 라벨 없이 한 줄).

---

### Task 1: 공통 파서 `extract_authors` (meta.py)

**Files:**
- Modify: `src/bullet_in/adapters/meta.py`
- Test: `tests/test_meta.py`

**Interfaces:**
- Consumes: 없음 (순수 파서).
- Produces: `extract_authors(html: str) -> list[str]` — JSON-LD `author` → `meta[name=author]` 폴백 체인으로 저자명을 등장 순서 · 중복 제거해 반환. Task 4 · 5 · 9가 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_meta.py` 끝에 추가:

```python
from bullet_in.adapters.meta import extract_authors

def test_authors_from_json_ld_multiple_in_order():
    # BBC 실측 형태: NewsArticle.author 배열에 Person 2명
    html = ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[{"@type":"Person","name":"Alastair Telfer"},'
            '{"@type":"Person","name":"Sami Mokbel"}]}</script>')
    assert extract_authors(html) == ["Alastair Telfer", "Sami Mokbel"]

def test_authors_from_nested_json_ld_graph():
    # @graph 중첩 안의 author 도 재귀 탐색으로 찾는다
    html = ('<script type="application/ld+json">'
            '{"@graph":[{"@type":"WebPage"},'
            '{"@type":"NewsArticle","author":{"@type":"Person","name":"Raff Tindale"}}]}'
            '</script>')
    assert extract_authors(html) == ["Raff Tindale"]

def test_authors_accepts_string_author():
    html = ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":"Moataz Elgammal"}</script>')
    assert extract_authors(html) == ["Moataz Elgammal"]

def test_authors_dedupes_preserving_order():
    html = ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[{"@type":"Person","name":"Sami Mokbel"},'
            '{"@type":"Person","name":"Sami Mokbel"}]}</script>')
    assert extract_authors(html) == ["Sami Mokbel"]

def test_authors_falls_back_to_meta_author():
    html = '<meta name="author" content="Raff Tindale">'
    assert extract_authors(html) == ["Raff Tindale"]

def test_authors_json_ld_wins_over_meta():
    html = ('<meta name="author" content="Desk">'
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":{"@type":"Person","name":"Real Person"}}</script>')
    assert extract_authors(html) == ["Real Person"]

def test_authors_excludes_url_and_empty_values():
    # BBC 실측: article:author 는 Facebook URL — 저자명이 아니다
    html = ('<meta property="article:author" content="https://www.facebook.com/BBCSport/">'
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[{"@type":"Person","name":""},'
            '{"@type":"Person","name":"https://example.test/profile"},'
            '{"@type":"Person","name":"Dharmesh Sheth"}]}</script>')
    assert extract_authors(html) == ["Dharmesh Sheth"]

def test_authors_survives_broken_json_ld():
    html = ('<script type="application/ld+json">{ not json ]</script>'
            '<meta name="author" content="Kaya Kaynak">')
    assert extract_authors(html) == ["Kaya Kaynak"]

def test_authors_empty_when_absent():
    assert extract_authors("<html><body><p>no author</p></body></html>") == []

def test_authors_falls_back_when_json_ld_authors_all_invalid():
    # JSON-LD author 가 있으나 유효 저자 0명 → meta 폴백이 걸려야 한다
    html = ('<meta name="author" content="Real Fallback Author">'
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[{"@type":"Person","name":""},'
            '{"@type":"Person","name":"https://example.test/profile"}]}</script>')
    assert extract_authors(html) == ["Real Fallback Author"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_meta.py -q -k authors`
Expected: FAIL — `ImportError: cannot import name 'extract_authors'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/meta.py` 끝에 추가 (파일 상단 import에 `import json` 추가):

```python
def _walk_authors(node) -> list[str]:
    """JSON-LD 트리를 재귀 탐색해 author 값을 등장 순서로 수집한다."""
    found: list[str] = []
    if isinstance(node, dict):
        if "author" in node:
            a = node["author"]
            for it in (a if isinstance(a, list) else [a]):
                if isinstance(it, dict):
                    name = it.get("name")
                    if isinstance(name, str):
                        found.append(name)
                elif isinstance(it, str):
                    found.append(it)
        for v in node.values():
            found += _walk_authors(v)
    elif isinstance(node, list):
        for v in node:
            found += _walk_authors(v)
    return found

def _normalize_authors(names: list[str]) -> list[str]:
    """저자 목록을 정규화: 빈 문자열 · URL 형태 배제 · 중복 제거 · 순서 보존."""
    out: list[str] = []
    for n in names:
        n = (n or "").strip()
        # URL 형태 (article:author 의 SNS 링크 등) 는 저자명이 아니다
        if not n or n.lower().startswith(("http://", "https://")):
            continue
        if n not in out:
            out.append(n)
    return out

def extract_authors(html: str) -> list[str]:
    """기사 저자명을 JSON-LD → meta[name=author] 순으로 추출한다.
    라이브 실측 (2026-07-16) 상 html 5소스 모두 JSON-LD 로 저자를 노출한다.
    기자는 부가 정보 — 어떤 실패도 빈 목록으로 폴백해 수집을 막지 않는다."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        names: list[str] = []
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "")
            except (json.JSONDecodeError, TypeError):
                continue          # 깨진 LD 하나가 나머지를 막지 않는다
            names += _walk_authors(data)
        out = _normalize_authors(names)
        # JSON-LD 에서 유효 저자를 찾지 못했다면 meta[name=author] 폴백
        if not out:
            tag = soup.find("meta", attrs={"name": "author"})
            if tag and tag.get("content"):
                out = _normalize_authors([tag["content"]])
        return out
    except Exception:
        return []
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_meta.py -q`
Expected: PASS (기존 이미지 · og 테스트 포함 전부 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/meta.py tests/test_meta.py
git commit -m "$(cat <<'EOF'
feat(adapters): 기사 저자 추출 파서 — JSON-LD · meta author 체인

html 소스 5곳이 모두 JSON-LD로 저자를 노출한다는 라이브 실측에 따라,
소스별 CSS 셀렉터 없이 동작하는 공통 파서를 추가한다.

- extract_authors: JSON-LD author 재귀 수집 (Person · 문자열형) → meta[name=author] 폴백
- 배제 규칙: URL 형태 값 (article:author SNS 링크) · 빈 문자열 · 중복
- 실패 격리: 깨진 LD 스킵 · 예외 시 빈 목록 (수집 무영향)

Refs: docs/superpowers/specs/2026-07-16-journalist-track-design.md
EOF
)"
```

---

### Task 2: 레지스트리 확장 — 기자 소속 · 프랑스 3매체 · 단일 조회 맵

**Files:**
- Modify: `config/credibility.yaml`
- Modify: `src/bullet_in/credibility.py`
- Test: `tests/test_credibility.py`

**Interfaces:**
- Consumes: 없음.
- Produces:
  - `Registry.journalist_outlets: dict[str, str]` — alias · 정식명 (lower) → 소속 언론사 정식명. `outlet` 지정 기자만 등재. Task 3의 min 가드가 사용한다.
  - `Registry.journalists`에 정식명 (lower) 키 추가 — 추출 결과가 "Sami Mokbel" 같은 풀네임이라 alias 키만으로는 매치되지 않는다.
  - `journalist_directory(path) -> dict[str, dict]` — alias · 정식명 (lower) → `{"name": 정식명, "outlet": 소속 | None}`. Task 6 (render) 이 사용한다.
- 주의: `journalist_display_names`는 Task 6에서 `journalist_directory`로 대체 · 제거한다. 이 태스크에선 남겨 둔다 (run.py가 아직 사용 중).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_credibility.py` 끝에 추가:

```python
def test_load_registry_includes_canonical_name_key():
    # html 추출 결과는 풀네임 — alias 키만으론 매치 불가 (spec §2)
    r = load_registry(REG)
    assert r.journalists["sami mokbel"] == 1.0
    assert r.journalists["david ornstein"] == 1.0

def test_registry_journalist_outlets_only_for_affiliated():
    r = load_registry(REG)
    assert r.journalist_outlets["sami mokbel"] == "BBC"
    assert r.journalist_outlets["@skysports_sheth"] == "Sky Sports"
    # 프리랜서 (여러 매체 기고) 는 소속 미지정 → 조회 부재
    assert "charles watts" not in r.journalist_outlets
    assert "fabrizio romano" not in r.journalist_outlets

def test_registry_registers_french_outlets():
    r = load_registry(REG)
    assert r.outlets["l'équipe"] == 2.0
    assert r.outlets["레키프"] == 2.0
    assert r.outlets["rmc"] == 1.0
    assert r.outlets["foot mercato"] == 4.0

def test_journalist_directory_maps_alias_and_name():
    from bullet_in.credibility import journalist_directory
    d = journalist_directory("config/credibility.yaml")
    assert d["온스테인"] == {"name": "David Ornstein", "outlet": "The Athletic"}
    assert d["@fabrizioromano"]["name"] == "Fabrizio Romano"
    assert d["fabrizio romano"]["outlet"] is None      # 프리랜서
    assert d["sami mokbel"] == {"name": "Sami Mokbel", "outlet": "BBC"}
    assert "kaya kaynak" not in d                       # 미등재
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_credibility.py -q`
Expected: FAIL — `AttributeError: 'Registry' object has no attribute 'journalist_outlets'`

- [ ] **Step 3: `config/credibility.yaml` 수정**

`journalists:` 블록을 아래로 통째 교체한다 (소속 확인 가능한 기자만 `outlet` 기입 — Watts · Romano · X 계정은 미지정).
**주의: 비ASCII 리터럴 (한글 alias · `Art de Roché` · `L'Équipe`) 을 한 글자도 바꾸지 말 것.**

```yaml
journalists:
  - {name: David Ornstein,    tier: 1,   outlet: The Athletic,    aliases: ["@David_Ornstein", "온스테인", "Ornstein"]}
  - {name: Sami Mokbel,       tier: 1,   outlet: BBC,             aliases: ["@SamiMokbel1_DM", "@SamiMokbel_BBC", "목벨", "Mokbel"]}
  - {name: Fabrizio Romano,   tier: 1.5, aliases: ["@FabrizioRomano", "로마노", "Romano"]}
  - {name: James McNicholas,  tier: 1.5, outlet: The Athletic,    aliases: ["@_JamesMcNicholas", "@gunnerblog", "맥니콜라스", "McNicholas"]}
  - {name: handofarsnal,      tier: 1.5, aliases: ["@handofarsnal"]}
  - {name: Dharmesh Sheth,    tier: 1.5, outlet: Sky Sports,      aliases: ["@skysports_sheth", "셰스", "Sheth"]}
  - {name: Charles Watts,     tier: 3,   aliases: ["@charles_watts", "찰스 왓츠", "Watts"]}
  - {name: Amy Lawrence,      tier: 2,   outlet: The Athletic,    aliases: ["@amylawrence71", "에이미 로런스", "Lawrence"]}
  - {name: Teamnewsandtix,    tier: 2,   aliases: ["@Teamnewsandtix", "팀뉴스앤틱스"]}
  - {name: James Olley,       tier: 2,   outlet: ESPN,            aliases: ["@JamesOlley", "올리", "Olley"]}
  - {name: Gary Jacob,        tier: 3,   outlet: The Times,       aliases: ["@garyjacob", "게리 제이콥", "Jacob"]}
  - {name: Simon Collings,    tier: 3,   outlet: Evening Standard, aliases: ["@sr_collings", "사이먼 콜링스", "Collings"]}
  - {name: Gianluca Di Marzio,tier: 3,   outlet: Sky Italia,      aliases: ["@DiMarzio", "디 마르지오", "Di Marzio"]}
  - {name: Sam Dean,          tier: 2,   outlet: The Telegraph,   aliases: ["@SamJDean", "샘 딘", "Sam Dean"]}
  - {name: Miguel Delaney,    tier: 3,   outlet: The Independent, aliases: ["@MiguelDelaney", "미겔 델라니", "델라니", "Delaney"]}
  - {name: Matt Law,          tier: 2,   outlet: The Telegraph,   aliases: ["@Matt_Law_DT"]}
  - {name: LatteFirm,         tier: 3,   aliases: ["@LatteFirm"]}
  - {name: Art de Roché,     tier: 1.5, outlet: The Athletic,    aliases: ["@ArtdeRoche", "드 로셰", "드로셰", "de roche"]}
```

`outlets:` 블록 끝 (`arseblog` 줄 다음) 에 프랑스 3매체를 추가한다:

```yaml
  - {name: L'Équipe,        tier: 2,   aliases: ["레키프", "L'Equipe", "L'Équipe", "lequipe"]}
  - {name: RMC Sport,       tier: 1,   aliases: ["RMC", "RMC 스포르", "RMC Sport"]}
  - {name: Foot Mercato,    tier: 4,   aliases: ["풋 메르카토", "Foot Mercato", "footmercato"]}
```

- [ ] **Step 4: `credibility.py` 구현**

`Registry.__init__`를 교체:

```python
class Registry:
    def __init__(self, journalists: dict[str, float], outlets: dict[str, float],
                 journalist_outlets: dict[str, str] | None = None):
        self.journalists = journalists  # alias·정식명(lower) -> tier
        self.outlets = outlets
        self.journalist_outlets = journalist_outlets or {}  # 소속 지정 기자만 (프리랜서 부재)
```

`load_registry`를 교체:

```python
def load_registry(path) -> Registry:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    jour: dict[str, float] = {}
    out: dict[str, float] = {}
    _build(data.get("journalists", []), jour)
    _build(data.get("outlets", []), out)
    j_outlets: dict[str, str] = {}
    for e in data.get("journalists", []) or []:
        # 정식명 키 — html 추출 결과는 풀네임이라 alias 만으론 매치 불가.
        # aliases 에 이미 이름이 있는 항목 (Sam Dean 등) 이 있어 setdefault.
        jour.setdefault(e["name"].lower(), float(e["tier"]))
        if e.get("outlet"):
            for key in [e["name"], *e["aliases"]]:
                j_outlets[key.lower()] = e["outlet"]
    return Registry(jour, out, j_outlets)
```

`journalist_display_names` 아래에 추가:

```python
def journalist_directory(path) -> dict[str, dict]:
    """alias · 정식명(lower) -> {"name": 정식 영문명, "outlet": 소속 | None}.
    바이라인 표기 · facet 정규화 · 등재 판정을 한 번에 해결하는 서빙용 조회 맵."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for e in data.get("journalists", []) or []:
        entry = {"name": e["name"], "outlet": e.get("outlet")}
        for key in [e["name"], *e["aliases"]]:
            out.setdefault(key.lower(), entry)
    return out
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_credibility.py tests/test_pipeline.py -q`
Expected: PASS (기존 alias · 중복 검사 · x_mentions 테스트 전부 유지)

- [ ] **Step 6: 비ASCII 전사 검증** (컨벤션 — subagent 전사 손실 함정)

Run: `git diff config/credibility.yaml | grep -c "Roché\|L'Équipe\|온스테인"`
Expected: 1 이상 출력되고, 아래 코드포인트 대조가 `OK` 를 출력할 것

Run:
```bash
uv run python -c "
import yaml
d = yaml.safe_load(open('config/credibility.yaml', encoding='utf-8'))
names = [e['name'] for e in d['journalists']]
outs = [e['name'] for e in d['outlets']]
assert 'Art de Roché' in names, names
assert \"L'Équipe\" in outs, outs
assert len(d['journalists']) == 18 and len(d['outlets']) == 23
print('OK')
"
```

- [ ] **Step 7: 커밋**

```bash
git add config/credibility.yaml src/bullet_in/credibility.py tests/test_credibility.py
git commit -m "$(cat <<'EOF'
feat(credibility): 기자 소속 필드 · 정식명 조회 · 프랑스 3매체 등재

고정 소스의 기자 tier 보정과 서빙 facet 이 쓸 레지스트리 기반을 넓힌다
— 소속 일치 판정과 풀네임 조회가 없으면 두 기능 모두 성립하지 않는다.

- 기자 outlet 필드: 소속 확인 가능한 12명 (프리랜서 Watts · Romano · X 계정은 미지정)
- Registry.journalist_outlets · 정식명 (lower) 키: 추출 풀네임 매치 경로
- journalist_directory: alias · 정식명 → 이름 · 소속 단일 조회 맵 (서빙용)
- outlets 등재: L'Équipe 2 · RMC Sport 1 · Foot Mercato 4

Refs: docs/superpowers/specs/2026-07-16-journalist-track-design.md
EOF
)"
```

---

### Task 3: 소스 메타 (`outlet` · `journalist_label`) · tier min 가드

**Files:**
- Modify: `config/sources.yaml`
- Modify: `src/bullet_in/credibility.py:39-74` (`resolve_tier`)
- Test: `tests/test_credibility.py`

**Interfaces:**
- Consumes: `Registry.journalist_outlets` (Task 2).
- Produces: `resolve_tier(item, sources: dict, registry: Registry | None, journalist: str | None = None) -> float | None`
  — 기존 3인자 호출은 그대로 동작한다 (`journalist=None` → 보정 없음). Task 5 · 9가 `journalist=` 를 넘긴다.
- `sources.yaml` 신규 키: `outlet` (레지스트리 outlet 정식명), `journalist_label` (통칭).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_credibility.py` 끝에 추가:

```python
def test_fixed_source_promotes_tier_for_affiliated_journalist():
    # Sheth (1.5, Sky Sports) @ skysports (1.5) → min(1.5, 1.5)
    r = load_registry(REG)
    sources = {"skysports": {"tier": 1.5, "outlet": "Sky Sports"}}
    it = _item("skysports", {"title": "Alvarez latest"})
    assert resolve_tier(it, sources, r, journalist="Dharmesh Sheth") == 1.5
    # 가상의 승격: 같은 기자가 tier 4 소스에 실렸다면 1.5 로 승격
    sources4 = {"skysports": {"tier": 4, "outlet": "Sky Sports"}}
    assert resolve_tier(it, sources4, r, journalist="Dharmesh Sheth") == 1.5

def test_fixed_source_min_guard_never_demotes():
    # 레지스트리 실수로 기자 tier 가 소스보다 낮아도 (Delaney 3 @ tier 1 소스) 강등 없음
    r = load_registry(REG)
    sources = {"indep": {"tier": 1, "outlet": "The Independent"}}
    it = _item("indep", {"title": "x"})
    assert resolve_tier(it, sources, r, journalist="Miguel Delaney") == 1.0

def test_fixed_source_freelancer_does_not_adjust_tier():
    # Watts (3) 는 여러 매체 기고 — 소속 미지정 → 표시 전용, tier 무조정 (사용자 결정)
    r = load_registry(REG)
    sources = {"goal": {"tier": 4, "outlet": "Goal.com"}}
    it = _item("goal", {"title": "x"})
    assert resolve_tier(it, sources, r, journalist="Charles Watts") == 4.0

def test_fixed_source_mismatched_outlet_does_not_adjust_tier():
    # 등재 기자라도 소속이 기사 소스와 다르면 보정하지 않는다
    r = load_registry(REG)
    sources = {"goal": {"tier": 4, "outlet": "Goal.com"}}
    it = _item("goal", {"title": "x"})
    assert resolve_tier(it, sources, r, journalist="Sami Mokbel") == 4.0

def test_fixed_source_unregistered_journalist_keeps_source_tier():
    r = load_registry(REG)
    sources = {"football_london": {"tier": 4, "outlet": "football.london"}}
    it = _item("football_london", {"title": "x"})
    assert resolve_tier(it, sources, r, journalist="Raff Tindale") == 4.0

def test_fixed_source_without_journalist_keeps_legacy_behavior():
    r = load_registry(REG)
    sources = {"bbc_sport": {"tier": 1, "outlet": "BBC"}}
    assert resolve_tier(_item("bbc_sport", {"title": "x"}), sources, r) == 1.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_credibility.py -q -k fixed_source`
Expected: FAIL — `TypeError: resolve_tier() got an unexpected keyword argument 'journalist'`

- [ ] **Step 3: `config/sources.yaml` 수정**

각 소스에 `outlet:` 을 추가하고, 통칭 2곳에 `journalist_label:` 을 추가한다.
`tier` 줄 아래에 한 줄씩 삽입 (동적 소스 x_afcstuff · fmkorea 는 건드리지 않는다):

| source_id | 추가할 줄 |
|---|---|
| arsenal_official | `outlet: Arsenal.com` · `journalist_label: Arsenal Official` |
| bbc_sport | `outlet: BBC` |
| bbc_gossip | `outlet: BBC` · `journalist_label: BBC Gossip` |
| goal | `outlet: Goal.com` |
| football_london | `outlet: football.london` |
| guardian | `outlet: The Guardian` |
| skysports | `outlet: Sky Sports` |

예 (arsenal_official · bbc_gossip):

```yaml
  - source_id: arsenal_official
    display_name: Arsenal.com
    tier: 0
    outlet: Arsenal.com               # 레지스트리 outlet 정식명 — 기자 소속 일치 판정용
    journalist_label: Arsenal Official  # 조직 바이라인 통칭 (추출 대신 고정 표기)
    medium: official
```

```yaml
  - source_id: bbc_gossip
    display_name: BBC Football Gossip
    tier: 4
    outlet: BBC
    journalist_label: BBC Gossip      # 집계 칼럼 — 저자 개념 없음, 상세 미방문
    medium: newspaper
```

- [ ] **Step 4: `resolve_tier` 구현**

`src/bullet_in/credibility.py`의 `resolve_tier` 시그니처와 마지막 고정 소스 분기를 교체:

```python
def resolve_tier(item, sources: dict, registry: "Registry | None",
                 journalist: str | None = None) -> float | None:
    """항목 1건의 tier 를 산출. None 이면 호출측에서 그 항목을 버린다."""
```

(x_mentions · fmkorea 분기는 그대로 두고) 파일 끝 고정 소스 분기를 교체:

```python
    # 고정 소스: tier 미지정(설정 누락 등)이면 None → 항목 drop
    tier = src.get("tier")
    if tier is None:
        return None
    tier = float(tier)
    # 소속이 기사 소스와 일치하는 등재 기자만 min 가드로 승격 (spec §2).
    # 프리랜서 (outlet 미지정) · 미등재 기자는 표시 전용 — tier 무조정.
    if journalist and registry is not None:
        key = journalist.lower()
        j_tier = registry.journalists.get(key)
        j_outlet = registry.journalist_outlets.get(key)
        if j_tier is not None and j_outlet and j_outlet == src.get("outlet"):
            return min(j_tier, tier)
    return tier
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_credibility.py tests/test_score.py tests/test_pipeline.py tests/test_adapter_factory.py -q`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add config/sources.yaml src/bullet_in/credibility.py tests/test_credibility.py
git commit -m "$(cat <<'EOF'
feat(credibility): 고정 소스 기자 tier 보정 — 소속 일치 min 가드

고정 소스의 tier 가 소스 단위 값에만 묶여 있어 등재 기자의 기사도 소스
tier 에 머물던 문제를 푼다 — 승격만 허용하는 min 가드로 강등 여지를 없앤다.

- resolve_tier(journalist=) 선택 인자: 기존 3인자 호출 동작 불변
- 보정 조건: 등재 기자 + outlet 소속이 기사 소스와 일치 → min (기자, 소스)
- 무조정: 프리랜서 (소속 미지정) · 미등재 · 소속 불일치 · 동적 소스 경로
- sources.yaml: outlet (소속 판정 · facet 표기) · journalist_label (통칭 2곳)

Refs: docs/superpowers/specs/2026-07-16-journalist-track-design.md
EOF
)"
```

---

### Task 4: 어댑터 배선 — `payload["authors"]` (html · guardian)

**Files:**
- Modify: `src/bullet_in/adapters/html.py:53-65`
- Modify: `src/bullet_in/adapters/guardian_api.py:33` · `:54-65`
- Test: `tests/test_html_adapter.py` · `tests/test_guardian_adapter.py`

**Interfaces:**
- Consumes: `extract_authors` (Task 1).
- Produces: `raw_payload["authors"]: list[str]` — html (`body_selector` 있는 소스) · guardian 항목에 실린다. Task 5가 소비한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_html_adapter.py` 끝에 추가:

```python
@respx.mock
def test_html_adapter_collects_authors_from_detail():
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    detail = ('<html><head><script type="application/ld+json">'
              '{"@type":"NewsArticle","author":[{"@type":"Person","name":"Alastair Telfer"},'
              '{"@type":"Person","name":"Sami Mokbel"}]}</script></head>'
              '<body><div class="article-body"><p>Deal done.</p></div></body></html>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["authors"] == ["Alastair Telfer", "Sami Mokbel"]

@respx.mock
def test_html_adapter_authors_absent_when_detail_fetch_fails():
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(500))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload.get("authors", []) == []
```

`tests/test_guardian_adapter.py` 끝에 추가 (파일 상단의 기존 `_resp` 헬퍼 · import 를 그대로 쓴다):

```python
@respx.mock
def test_guardian_adapter_carries_byline_as_authors():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal agree deal for Rogers", "webUrl": "https://g.test/1",
         "webPublicationDate": "2026-07-15T10:00:00Z",
         "fields": {"trailText": "t", "bodyText": "b", "byline": "David Hytner"}}]))
    a = GuardianAdapter("guardian", "key", title_contains=["deal"])
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["authors"] == ["David Hytner"]

@respx.mock
def test_guardian_adapter_authors_empty_without_byline():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal agree deal for Rogers", "webUrl": "https://g.test/1",
         "webPublicationDate": "2026-07-15T10:00:00Z",
         "fields": {"trailText": "t", "bodyText": "b"}}]))
    a = GuardianAdapter("guardian", "key", title_contains=["deal"])
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["authors"] == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_html_adapter.py tests/test_guardian_adapter.py -q -k author`
Expected: FAIL — `KeyError: 'authors'`

- [ ] **Step 3: `html.py` 구현**

`src/bullet_in/adapters/html.py`의 import 줄과 본문 fetch 블록을 교체:

```python
        from bullet_in.adapters.meta import (extract_og_image, extract_body_images,
                                             extract_authors)
```

```python
                if self.body_selector:
                    try:
                        rb = await c.get(url)
                        rb.raise_for_status()
                        el = BeautifulSoup(rb.text, "html.parser").select_one(self.body_selector)
                        payload["body"] = el.get_text(" ", strip=True) if el else ""
                        payload["image_url"] = extract_og_image(rb.text)
                        payload["images"] = extract_body_images(
                            rb.text, self.body_selector, base_url=url)
                        payload["authors"] = extract_authors(rb.text)
                    except httpx.HTTPError:
                        payload["body"] = ""  # 본문 실패 — 제목만 유지, 다음 회차 재시도
```

- [ ] **Step 4: `guardian_api.py` 구현**

`show-fields` 값에 `byline` 을 추가:

```python
        self.params = {"tag": tag, "api-key": api_key,
                       "show-fields": "trailText,bodyText,body,thumbnail,byline",
                       "show-elements": "image",
                       "order-by": "newest", "page-size": 20}
```

`raw_payload` 에 `authors` 를 추가 (`images` 줄 다음):

```python
                                            "images": _element_images(x.get("elements", []))
                                                or extract_body_images(
                                                    f.get("body", ""), base_url=x["webUrl"]),
                                            # byline 은 단일 문자열 — 대표 선정은 pipeline 책임
                                            "authors": [f["byline"]] if f.get("byline") else []}))
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_html_adapter.py tests/test_guardian_adapter.py -q`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/adapters/html.py src/bullet_in/adapters/guardian_api.py tests/test_html_adapter.py tests/test_guardian_adapter.py
git commit -m "$(cat <<'EOF'
feat(adapters): html · guardian 저자 배선 — payload authors

이미 받아온 응답에서만 저자를 뽑아 추가 네트워크 요청 없이 수집 경로에
저자를 싣는다 — 대표 1명 선정은 레지스트리를 아는 pipeline 책임으로 남긴다.

- html: 본문 fetch 자리에서 extract_authors 호출 (body_selector 소스 한정)
- guardian: show-fields 에 byline 추가 → 단일 문자열을 authors 목록으로
- 실패 격리: 상세 fetch 실패 · byline 부재 → authors 부재 · 빈 목록

Refs: docs/superpowers/specs/2026-07-16-journalist-track-design.md
EOF
)"
```

---

### Task 5: 대표 기자 선정 (pipeline)

**Files:**
- Modify: `src/bullet_in/pipeline.py:27-67`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `raw_payload["authors"]` (Task 4), `resolve_tier(journalist=)` (Task 3), `Registry.journalists` (Task 2), `sources[sid]["journalist_label"]` (Task 3).
- Produces: `select_journalist(item, src: dict, registry: "Registry | None") -> str | None`
  — 대표 기자 1명. Task 9 (백필) 가 재사용한다.
- `to_articles` 시그니처는 불변.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pipeline.py` 끝에 추가:

```python
from bullet_in.pipeline import select_journalist

def _html_item(source_id, payload):
    return RawItem(source_id=source_id, source_type="html",
                   url="https://x.test/a", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"published": "2026-07-15T10:00:00Z", **payload})

def test_select_journalist_prefers_registered_author():
    # BBC 실측: Telfer(미등재) + Mokbel(등재) → 등재자 대표
    it = _html_item("bbc_sport", {"title": "x", "authors": ["Alastair Telfer", "Sami Mokbel"]})
    assert select_journalist(it, {"tier": 1}, REG) == "Sami Mokbel"

def test_select_journalist_falls_back_to_first_author():
    it = _html_item("football_london", {"title": "x", "authors": ["Raff Tindale", "Tom Canton"]})
    assert select_journalist(it, {"tier": 4}, REG) == "Raff Tindale"

def test_select_journalist_uses_source_label_when_configured():
    it = _html_item("arsenal_official", {"title": "x", "authors": ["Arsenal Media"]})
    src = {"tier": 0, "journalist_label": "Arsenal Official"}
    assert select_journalist(it, src, REG) == "Arsenal Official"

def test_select_journalist_label_applies_without_authors():
    # bbc_gossip: 상세 미방문 → authors 없음, 통칭만으로 채워진다
    it = _html_item("bbc_gossip", {"title": "x"})
    assert select_journalist(it, {"tier": 4, "journalist_label": "BBC Gossip"}, REG) == "BBC Gossip"

def test_select_journalist_keeps_existing_payload_value():
    # 동적 소스 (x · fmkorea) 는 이미 journalist 를 실어 보낸다 — 그대로 존중
    it = _html_item("fmkorea", {"title": "x", "journalist": "온스테인",
                                "authors": ["Someone Else"]})
    assert select_journalist(it, {"credibility": "fmkorea"}, REG) == "온스테인"

def test_select_journalist_none_when_no_authors():
    assert select_journalist(_html_item("goal", {"title": "x"}), {"tier": 4}, REG) is None

def test_to_articles_promotes_tier_for_affiliated_journalist():
    raw = [_html_item("skysports", {"title": "Alvarez latest", "authors": ["Dharmesh Sheth"]})]
    sources = {"skysports": {"source_id": "skysports", "tier": 4, "outlet": "Sky Sports"}}
    arts, _ = to_articles(raw, sources, seen={}, registry=REG)
    assert arts[0].journalist == "Dharmesh Sheth"
    assert arts[0].tier == 1.5                       # min(1.5, 4) → 승격
    assert arts[0].confidence_score == 0.625

def test_to_articles_keeps_source_tier_for_unregistered_journalist():
    raw = [_html_item("football_london", {"title": "Alvarez latest", "authors": ["Raff Tindale"]})]
    sources = {"football_london": {"source_id": "football_london", "tier": 4,
                                   "outlet": "football.london"}}
    arts, _ = to_articles(raw, sources, seen={}, registry=REG)
    assert arts[0].journalist == "Raff Tindale" and arts[0].tier == 4.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_pipeline.py -q -k journalist`
Expected: FAIL — `ImportError: cannot import name 'select_journalist'`

- [ ] **Step 3: 구현**

`src/bullet_in/pipeline.py`에 함수 추가 (`_published` 아래):

```python
def select_journalist(item, src: dict, registry: "Registry | None") -> str | None:
    """항목의 대표 기자 1명 — 기존 값 · 소스 통칭 · 추출 저자 (등재자 우선) 순.
    journalist 컬럼은 단일 문자열 — 복수 저자는 대표 1명만 남긴다 (spec 확정 결정)."""
    j = item.raw_payload.get("journalist")
    if j:
        return j                                   # 동적 소스 (x · fmkorea) 가 이미 실은 값
    label = src.get("journalist_label")
    if label:
        return label                               # 조직 바이라인 통칭 (추출값보다 우선)
    authors = item.raw_payload.get("authors") or []
    if registry is not None:
        for a in authors:
            if a.lower() in registry.journalists:
                return a
    return authors[0] if authors else None
```

`to_articles` 루프 앞부분을 교체:

```python
    for item in raw:
        src = sources.get(item.source_id, {})
        journalist = select_journalist(item, src, registry)
        tier = resolve_tier(item, sources, registry, journalist=journalist)
        if tier is None:
            continue
```

같은 루프의 `journalist=` 인자를 교체:

```python
            journalist=journalist,
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_pipeline.py tests/test_credibility.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/pipeline.py tests/test_pipeline.py
git commit -m "$(cat <<'EOF'
feat(pipeline): 대표 기자 선정 · tier 보정 연결

어댑터가 실은 저자 목록에서 대표 1명을 골라 저장하고, 같은 값을 tier 산출에
넘겨 소속 일치 등재 기자의 승격이 실제로 걸리게 한다.

- select_journalist: 기존 값 → 소스 통칭 → 추출 저자 (등재자 우선 · 첫 번째 폴백)
- to_articles: 기자 선정 후 resolve_tier(journalist=) 호출 순으로 재배치
- 복수 저자는 대표 1명만 (journalist 단일 문자열 계약 유지)

Refs: docs/superpowers/specs/2026-07-16-journalist-track-design.md
EOF
)"
```

---

### Task 6: 서빙 뷰모델 — 기자 정규화 · facet · 바이라인

**Files:**
- Modify: `src/bullet_in/serve/render.py:63-82` (`facet_counts`) · `:256-291` (`_decorate`) · `:300-304` (`render_index`) · `:318-328` (`render_article`) · `:331-350` (`write_site`)
- Modify: `src/bullet_in/run.py:13` · `:96-97`
- Modify: `src/bullet_in/credibility.py` (`journalist_display_names` 제거)
- Test: `tests/test_serve_layout.py` · `tests/test_serve_render.py` · `tests/test_credibility.py`

**Interfaces:**
- Consumes: `journalist_directory` (Task 2), `sources[sid]["outlet"]` · `["journalist_label"]` (Task 3).
- Produces:
  - `journalist_entry(row: dict, sources: dict, directory: dict | None) -> dict | None`
    — `{"name": 정규화 정식명 (필터 · 집계 키), "label": "기자 (언론사)" 표시, "registered": bool}` 또는 None (기자 없음).
  - `facet_counts(articles, sources, directory=None)` 반환에 `"journalists": {"registered": [(name, label, count), ...], "more": [...]}` 추가 (각 건수 내림차순 · 동수는 이름순).
  - `_decorate(row, sources, now, directory=None)` — `names=` 파라미터를 대체한다. `a["_journalist"]` (필터 키) · `a["_byline"]` (표시 라벨) 을 싣는다.
  - `render_index(articles, sources, now, directory=None)` · `write_site(articles, sources, out_dir, now=None, directory=None)`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_serve_layout.py` 끝에 추가:

```python
from bullet_in.serve.render import journalist_entry

DIR = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"},
       "david ornstein": {"name": "David Ornstein", "outlet": "The Athletic"},
       "charles watts": {"name": "Charles Watts", "outlet": None}}
JSOURCES = {"bbc_sport": {"display_name": "BBC Sport", "outlet": "BBC"},
            "goal": {"display_name": "Goal.com", "outlet": "Goal.com"},
            "arsenal_official": {"display_name": "Arsenal.com", "outlet": "Arsenal.com",
                                 "journalist_label": "Arsenal Official"}}

def test_journalist_entry_normalizes_alias_and_labels_outlet():
    e = journalist_entry({"journalist": "온스테인", "source_id": "bbc_sport"}, JSOURCES, DIR)
    assert e == {"name": "David Ornstein", "label": "David Ornstein (The Athletic)",
                 "registered": True}

def test_journalist_entry_registered_without_outlet_shows_name_only():
    e = journalist_entry({"journalist": "Charles Watts", "source_id": "goal"}, JSOURCES, DIR)
    assert e["label"] == "Charles Watts" and e["registered"] is True

def test_journalist_entry_unregistered_uses_source_outlet():
    e = journalist_entry({"journalist": "Kaya Kaynak", "source_id": "goal"}, JSOURCES, DIR)
    assert e == {"name": "Kaya Kaynak", "label": "Kaya Kaynak (Goal.com)", "registered": False}

def test_journalist_entry_label_omits_parens_for_source_label():
    e = journalist_entry({"journalist": "Arsenal Official", "source_id": "arsenal_official"},
                         JSOURCES, DIR)
    assert e == {"name": "Arsenal Official", "label": "Arsenal Official", "registered": False}

def test_journalist_entry_none_when_missing():
    assert journalist_entry({"journalist": None, "source_id": "goal"}, JSOURCES, DIR) is None
    assert journalist_entry({"journalist": "  ", "source_id": "goal"}, JSOURCES, DIR) is None

def test_facet_counts_splits_registered_and_more():
    arts = [
        {"journalist": "온스테인", "source_id": "bbc_sport"},          # alias → 정규화
        {"journalist": "David Ornstein", "source_id": "bbc_sport"},   # 같은 기자 — 합산돼야
        {"journalist": "Kaya Kaynak", "source_id": "goal"},
        {"journalist": "Kaya Kaynak", "source_id": "goal"},
        {"journalist": "Kaya Kaynak", "source_id": "goal"},
        {"journalist": "Arsenal Official", "source_id": "arsenal_official"},
        {"journalist": None, "source_id": "goal"},                    # 집계 제외
    ]
    f = facet_counts(arts, JSOURCES, directory=DIR)
    assert f["journalists"]["registered"] == [
        ("David Ornstein", "David Ornstein (The Athletic)", 2)]
    assert f["journalists"]["more"] == [
        ("Kaya Kaynak", "Kaya Kaynak (Goal.com)", 3),
        ("Arsenal Official", "Arsenal Official", 1)]

def test_facet_counts_journalists_empty_without_directory():
    f = facet_counts([{"journalist": None, "source_id": "goal"}], JSOURCES)
    assert f["journalists"] == {"registered": [], "more": []}
```

`tests/test_serve_render.py`의 기존 두 테스트를 교체하고 (`names=` 계약 소멸), 새 테스트를 추가:

```python
def test_decorate_resolves_byline_to_canonical_english():
    row = _row(journalist="온스테인", body_ko="본문")
    a = _dec(row, SOURCES, NOW,
             directory={"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}})
    assert a["_byline"] == "David Ornstein (The Athletic)"
    assert a["_journalist"] == "David Ornstein"

def test_decorate_byline_passthrough_when_unregistered():
    a = _dec(_row(journalist="Hugo Guillemet", body_ko="본문"), SOURCES, NOW)
    assert a["_byline"] == "Hugo Guillemet"
    assert a["_journalist"] == "Hugo Guillemet"

def test_index_card_has_journalist_data_attr():
    html = render_index([_row(journalist="온스테인")], SOURCES, NOW,
                        directory={"온스테인": {"name": "David Ornstein", "outlet": None}})
    assert 'data-journalist="David Ornstein"' in html   # 체크박스 값과 같은 정규화 키

def test_index_card_journalist_attr_empty_when_missing():
    html = render_index([_row()], SOURCES, NOW)
    assert 'data-journalist=""' in html
```

`tests/test_credibility.py`의 `test_journalist_display_names_maps_alias_to_canonical` 을 삭제한다 (Task 2의 `test_journalist_directory_maps_alias_and_name` 이 대체).

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_serve_layout.py -q -k journalist`
Expected: FAIL — `ImportError: cannot import name 'journalist_entry'`

- [ ] **Step 3: `render.py` 구현**

`facet_counts` 위에 추가:

```python
def journalist_entry(row: dict, sources: dict, directory: dict | None) -> dict | None:
    """기사 1건의 기자 뷰 — 정규화 이름 (필터 · 집계 키) · 표시 라벨 · 등재 여부.
    저장값은 소스마다 형태가 다르다 (fmkorea 한글 말머리 · x 핸들 · html 풀네임)
    → 레지스트리 정식명으로 정규화하지 않으면 같은 기자가 facet 에서 갈라진다."""
    j = (row.get("journalist") or "").strip()
    if not j:
        return None
    src = sources.get(row.get("source_id")) or {}
    entry = (directory or {}).get(j.lower())
    if entry:
        name, outlet, registered = entry["name"], entry["outlet"], True
    else:
        name, outlet, registered = j, src.get("outlet"), False
    if j == src.get("journalist_label") or not outlet:
        label = name                       # 통칭 · 소속 미상 → 괄호 생략
    else:
        label = f"{name} ({outlet})"
    return {"name": name, "label": label, "registered": registered}
```

`facet_counts` 시그니처 · 반환을 교체:

```python
def facet_counts(articles: list[dict], sources: dict, directory: dict | None = None) -> dict:
```

`stage_counts` 루프 다음, `return` 앞에 추가:

```python
    reg_ctr: Counter = Counter()
    more_ctr: Counter = Counter()
    labels: dict[str, str] = {}
    for a in articles:
        e = journalist_entry(a, sources, directory)
        if e is None:
            continue
        (reg_ctr if e["registered"] else more_ctr)[e["name"]] += 1
        labels[e["name"]] = e["label"]

    def _ranked(ctr: Counter) -> list[tuple[str, str, int]]:
        return [(n, labels[n], c)
                for n, c in sorted(ctr.items(), key=lambda kv: (-kv[1], kv[0]))]
```

`return` 문을 교체:

```python
    return {"total": len(articles), "team": dict(teams),
            "outlets": outlets, "tiers": tiers, "stage": stage_counts,
            "other": other_count,
            "journalists": {"registered": _ranked(reg_ctr), "more": _ranked(more_ctr)}}
```

`_decorate` 시그니처 · 바이라인 블록을 교체:

```python
def _decorate(row: dict, sources: dict, now: datetime,
              directory: dict | None = None) -> dict:
```

```python
    e = journalist_entry(row, sources, directory)
    a["_journalist"] = e["name"] if e else ""   # 카드 data 속성 · 필터 키
    a["_byline"] = e["label"] if e else None    # 표시 라벨 — 기자 (언론사)
    return a
```

`render_index` 를 교체:

```python
def render_index(articles: list[dict], sources: dict, now: datetime,
                 directory: dict | None = None) -> str:
    ordered = [_decorate(a, sources, now, directory=directory)
               for a in _sorted_latest(articles)]
    facets = facet_counts(articles, sources, directory=directory)
    return _env().get_template("index.html.j2").render(
        articles=ordered, facets=facets, active="home", root="")
```

`render_article` 의 facets 폴백에 기자 키를 추가 (없으면 상세 렌더가 깨진다):

```python
    if facets is None:
        facets = {"team": {}, "outlets": [], "tiers": {t: 0 for t in range(5)},
                  "total": 0, "stage": {}, "other": 0,
                  "journalists": {"registered": [], "more": []}}
```

`write_site` 를 교체:

```python
def write_site(articles: list[dict], sources: dict, out_dir: str | Path,
               now: datetime | None = None,
               directory: dict | None = None) -> None:
    """인덱스·상세 N개·정적 자산을 out_dir에 일괄 생성한다."""
    now = now or datetime.utcnow()
    out = Path(out_dir)
    (out / "article").mkdir(parents=True, exist_ok=True)

    (out / "index.html").write_text(
        render_index(articles, sources, now, directory=directory), encoding="utf-8")

    ordered = _sorted_latest(articles)
    # 패싯은 전체 기사 기준으로 한 번만 계산해 모든 상세 페이지에 전달
    facets = facet_counts(articles, sources, directory=directory)
    for idx, row in enumerate(ordered):
        a = _decorate(row, sources, now, directory=directory)
        neighbors = build_neighbors(ordered, idx, sources, now)
        html = render_article(a, neighbors, row["content_hash"], sources, now, facets=facets)
        (out / "article" / f"{row['content_hash']}.html").write_text(
            html, encoding="utf-8")

    for asset in ("style.css", "app.js"):
        shutil.copyfile(_STATIC_DIR / asset, out / asset)
```

- [ ] **Step 4: `run.py` · `credibility.py` 배선**

`src/bullet_in/run.py:13` 교체:

```python
from bullet_in.credibility import load_registry, journalist_directory
```

`src/bullet_in/run.py:96-97` 교체:

```python
    write_site(rows, sources, "site",
               directory=journalist_directory("config/credibility.yaml"))
```

`src/bullet_in/credibility.py`에서 `journalist_display_names` 함수를 삭제한다 (`journalist_directory`가 대체 — 이 변경이 만든 고아).

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_serve_layout.py tests/test_serve_render.py tests/test_credibility.py tests/test_serve_ops.py -q`
Expected: PASS

Run: `uv run pytest -q`
Expected: PASS (통합 테스트는 DB 없으면 skip)

Run: `grep -rn "journalist_display_names" src/ tests/`
Expected: 출력 없음 (고아 제거 확인)

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/run.py src/bullet_in/credibility.py tests/test_serve_layout.py tests/test_serve_render.py tests/test_credibility.py
git commit -m "$(cat <<'EOF'
feat(serve): 기자 뷰모델 — 정규화 · facet 분리 · 기자 (언론사) 바이라인

소스마다 저장 형태가 달라 (한글 말머리 · 핸들 · 풀네임) 같은 기자가 갈라지던
문제를 레지스트리 정식명 정규화로 없애고, facet · 카드 · 바이라인이 같은 키를
쓰게 맞춘다.

- journalist_entry: 정규화 이름 (필터 키) · 표시 라벨 · 등재 여부 단일 산출
- facet_counts.journalists: 등재 · 더보기 그룹 분리 (건수 내림차순 · 동수 이름순)
- 라벨 규칙: 등재는 레지스트리 outlet · 미등재는 소스 outlet · 통칭은 괄호 생략
- names → directory 파라미터 교체 · journalist_display_names 제거 (고아)

Refs: docs/superpowers/specs/2026-07-16-journalist-track-design.md
EOF
)"
```

---

### Task 7: 사이드바 기자 섹션 · 더보기 · 카드 속성 (템플릿 · CSS)

**Files:**
- Modify: `src/bullet_in/serve/templates/_layout.html.j2:39-42` 부근
- 확인만: `src/bullet_in/serve/templates/index.html.j2:6-13` — 카드 `data-journalist` 는 Task 6 에서 이미 반영 (Task 6 브리프의 테스트가 요구)
- Modify: `src/bullet_in/serve/static/style.css`
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: `facets.journalists.registered` · `.more` (Task 6), `a._journalist` (Task 6).
- Produces: DOM 계약 — 체크박스 `input[data-group=journalist][data-value=<정규화 이름>]`, 카드 `data-journalist`, 더보기 컨테이너 `#jmore` · 버튼 `#jmoreBtn`. Task 8이 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_serve_render.py` 끝에 추가:

```python
def test_sidebar_shows_registered_journalists_and_more_toggle():
    rows = [_row(content_hash="h1", journalist="온스테인"),
            _row(content_hash="h2", journalist="Kaya Kaynak"),
            _row(content_hash="h3", journalist="Kaya Kaynak")]
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}
    html = render_index(rows, SOURCES, NOW, directory=directory)
    assert "기자" in html
    # 등재 기자는 바로 노출
    assert 'data-group="journalist" data-value="David Ornstein"' in html
    assert "David Ornstein (The Athletic)" in html
    # 미등재는 더보기 토글 뒤
    assert 'id="jmore"' in html and 'id="jmoreBtn"' in html
    assert "더보기 1명" in html
    assert html.index('id="jmore"') < html.index('data-value="Kaya Kaynak"')

def test_sidebar_omits_more_toggle_when_all_registered():
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}
    html = render_index([_row(journalist="온스테인")], SOURCES, NOW, directory=directory)
    assert 'id="jmoreBtn"' not in html
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k sidebar`
Expected: FAIL — `assert '기자' in html` 또는 `data-group="journalist"` 부재

- [ ] **Step 3: `_layout.html.j2` 구현**

"소스 (언론사)" 블록과 "신뢰도 (Tier)" 블록 사이에 삽입:

```jinja
    <h4>기자</h4>
    {% for name, label, count in facets.journalists.registered %}
    <label class="opt"><input type="checkbox" data-group="journalist" data-value="{{ name }}"> {{ label }} <span class="ct">{{ count }}</span></label>
    {% endfor %}
    {% if facets.journalists.more %}
    <div id="jmore" hidden>
      {% for name, label, count in facets.journalists.more %}
      <label class="opt"><input type="checkbox" data-group="journalist" data-value="{{ name }}"> {{ label }} <span class="ct">{{ count }}</span></label>
      {% endfor %}
    </div>
    <button class="morebtn" id="jmoreBtn" type="button">더보기 {{ facets.journalists.more | length }}명</button>
    {% endif %}
```

- [ ] **Step 4: `index.html.j2` 확인 (구현 아님)**

카드 `<a>` 의 `data-journalist="{{ a._journalist }}"` 는 Task 6 브리프의 테스트 (`test_index_card_has_journalist_data_attr`) 가 요구해 이미 추가됐다.
`grep -n 'data-journalist' src/bullet_in/serve/templates/index.html.j2` 로 존재만 확인하고 중복 추가하지 말 것.
DOM contract 주석 갱신이 남아 있으면 그것만 수행한다.

- [ ] **Step 5: `style.css` 구현**

`.opt.disabled .soon` 규칙 다음 줄에 추가 (변수는 기존 것만 사용 — `--ink` · `--line` · `--muted` · `--chip`):

```css
.morebtn{display:block;width:100%;margin:2px 0 4px;padding:7px 9px;border:1px dashed var(--line);border-radius:9px;background:none;color:var(--muted);font:inherit;font-size:12px;cursor:pointer}
.morebtn:hover{background:var(--chip);color:var(--ink)}
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `uv run pytest tests/test_serve_render.py tests/test_serve_layout.py -q`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/serve/templates/_layout.html.j2 src/bullet_in/serve/templates/index.html.j2 src/bullet_in/serve/static/style.css tests/test_serve_render.py
git commit -m "$(cat <<'EOF'
feat(serve): 사이드바 기자 facet — 등재 우선 노출 · 미등재 더보기

기자 단위로 기사를 좁힐 수 있게 사이드바에 기자 섹션을 신설한다 — 핵심 ITK ·
등재 기자가 수집량 많은 로컬 스태프에 밀리지 않도록 그룹을 나눠 노출한다.

- 등재 그룹 상시 노출 · 미등재 그룹은 더보기 토글 (#jmore · #jmoreBtn) 뒤
- 체크박스 값 · 카드 data-journalist = 정규화 정식명 (필터 매칭 키 일치)
- morebtn 스타일: 기존 변수 (--line · --muted · --chip · --ink) 재사용

Refs: docs/superpowers/specs/2026-07-16-journalist-track-design.md
EOF
)"
```

---

### Task 8: 기자 필터 · URL 상태 동기화 · 상세 → 인덱스 이동 (app.js)

**Files:**
- Modify: `src/bullet_in/serve/static/app.js`
- Test: `tests/test_serve_render.py:5-13` (정적 자산 계약 테스트)

**Interfaces:**
- Consumes: DOM 계약 (Task 7) — `data-group=journalist` 체크박스 · 카드 `data-journalist` · `#jmore` · `#jmoreBtn` · `.logo` 의 index href.
- Produces: URL 쿼리 계약 — `?outlet=..&tier=..&stage=..&bucket=other&journalist=..&sort=confidence&q=..` (다중 선택은 같은 키 반복).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_serve_render.py` 상단의 `test_static_assets_exist_and_nonempty` 를 교체:

```python
def test_static_assets_exist_and_nonempty():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-theme" in css and "--bg" in css      # 테마 변수
    assert ".card" in css and ".side" in css
    assert "s-interest" in css and "s-personal" in css  # 신규 단계 점 색
    assert ".morebtn" in css                           # 기자 더보기 버튼
    assert "data-outlet" in js and "data-tier" in js   # 카드 필터 계약
    assert "data-stage" in js                          # 단계 필터 계약
    assert "localStorage" in js                        # 테마 영속
    assert "journalist" in js                          # 기자 필터 계약
    assert "URLSearchParams" in js                     # 필터 상태 URL 직렬화
    assert "replaceState" in js                        # 인덱스 URL 동기화
    assert "jmoreBtn" in js                            # 더보기 토글
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k static_assets`
Expected: FAIL — `assert 'URLSearchParams' in js`

- [ ] **Step 3: 구현**

`src/bullet_in/serve/static/app.js` 를 아래 전문으로 교체 (테마 블록은 그대로 유지):

```javascript
// DOM contract: a.card[data-outlet][data-tier][data-stage][data-published][data-confidence][data-text][data-journalist]
// URL contract: ?outlet=..&tier=..&stage=..&bucket=other&journalist=..&sort=confidence&q=..  (다중 선택은 키 반복)

// 테마 토글 (목업 이식: localStorage 영속, 페이지 간 유지)
const root = document.documentElement, themeBtn = document.getElementById('themeBtn');
const saved = localStorage.getItem('theme'); if (saved) root.setAttribute('data-theme', saved);
const syncTheme = () => { themeBtn.textContent = root.getAttribute('data-theme') === 'dark' ? '☀️' : '🌙'; };
syncTheme();
themeBtn.onclick = () => {
  const n = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', n); localStorage.setItem('theme', n); syncTheme();
};

// 사이드바 + 검색 + 필터/정렬 (인덱스에서만 카드에 작용)
const side = document.querySelector('.side');
const fstatus = document.getElementById('fstatus');
const applyBtn = document.getElementById('applyBtn');
const resetBtn = document.getElementById('resetBtn');
const searchInput = document.getElementById('q');
const grid = document.querySelector('.grid');
const cards = grid ? [...grid.querySelectorAll('.card')] : [];

// URL 직렬화 대상 그룹 (team 은 항상 arsenal — 제외)
const URL_GROUPS = ['outlet', 'tier', 'stage', 'journalist', 'bucket'];

const enabledBoxes = () => [...side.querySelectorAll('input[type=checkbox]:not([disabled])')];
const checkedValues = (group) =>
  enabledBoxes().filter(c => c.dataset.group === group && c.checked).map(c => c.dataset.value);

// 기자 더보기 토글 — 미등재 기자는 접힌 채 시작
const jmore = document.getElementById('jmore'), jmoreBtn = document.getElementById('jmoreBtn');
const expandMore = () => { if (jmore) jmore.hidden = false; if (jmoreBtn) jmoreBtn.hidden = true; };
if (jmoreBtn) jmoreBtn.onclick = expandMore;

function filterParams() {
  const p = new URLSearchParams();
  for (const g of URL_GROUPS) for (const v of checkedValues(g)) p.append(g, v);
  const sort = side.querySelector('input[name=sort]:checked')?.dataset.value;
  if (sort && sort !== 'latest') p.set('sort', sort);
  const q = (searchInput?.value || '').trim();
  if (q) p.set('q', q);
  return p;
}

function restoreFromQuery() {
  const p = new URLSearchParams(location.search);
  if (![...p.keys()].length) return false;
  const want = {};
  for (const g of URL_GROUPS) want[g] = p.getAll(g);
  enabledBoxes().forEach(c => {
    const g = c.dataset.group;
    if (URL_GROUPS.includes(g)) c.checked = want[g].includes(c.dataset.value);
  });
  const sort = p.get('sort') === 'confidence' ? 'confidence' : 'latest';
  const sortBox = side.querySelector(`input[name=sort][data-value=${sort}]`);
  if (sortBox) sortBox.checked = true;
  if (searchInput) searchInput.value = p.get('q') || '';
  // 접힌 더보기 안의 기자가 선택돼 있으면 펼친다 (보이지 않는 필터 방지)
  if (jmore && jmore.querySelector('input:checked')) expandMore();
  return true;
}

function applyFilters() {
  const q = (searchInput.value || '').trim().toLowerCase();
  const outlets = checkedValues('outlet');
  const tiers = checkedValues('tier');
  const stages = checkedValues('stage');
  const journalists = checkedValues('journalist');
  const showOther = !!side.querySelector('input[data-group=bucket][data-value=other]')?.checked;
  let shown = 0;
  for (const card of cards) {
    const okText = !q || (card.dataset.text || '').includes(q);
    const okOutlet = outlets.length === 0 || outlets.includes(card.dataset.outlet);
    const okTier = tiers.length === 0 || tiers.includes(card.dataset.tier);
    const okJournalist = journalists.length === 0 || journalists.includes(card.dataset.journalist);
    const st = card.dataset.stage;
    const isOther = !st || st === 'other';
    const okStage = isOther
      ? showOther
      : (stages.length === 0 || stages.includes(st));
    const visible = okText && okOutlet && okTier && okJournalist && okStage;
    card.style.display = visible ? '' : 'none';
    if (visible) shown++;
  }
  sortCards();
  const conds = outlets.length + tiers.length + stages.length + journalists.length
    + (showOther ? 1 : 0) + (q ? 1 : 0);
  fstatus.textContent = conds || q
    ? `적용됨 · 조건 ${conds}개 · ${shown}건`
    : `미적용 · 전체 ${shown}건`;
  applyBtn.classList.remove('dirty');
  // 필터된 뷰를 북마크·공유·뒤로가기로 되살릴 수 있게 상태를 URL에 남긴다
  const qs = filterParams().toString();
  history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
}

function sortCards() {
  if (!grid) return;
  const key = side.querySelector('input[name=sort]:checked').dataset.value;
  const ordered = [...cards].sort((a, b) => {
    if (key === 'confidence') {
      return parseFloat(b.dataset.confidence || 0) - parseFloat(a.dataset.confidence || 0);
    }
    return (b.dataset.published || '').localeCompare(a.dataset.published || ''); // 최신순
  });
  for (const c of ordered) grid.appendChild(c);
}

if (grid) {
  side.addEventListener('change', () => applyBtn.classList.add('dirty'));
  applyBtn.onclick = applyFilters;
  resetBtn.onclick = () => {
    enabledBoxes().forEach(c => { c.checked = (c.dataset.value === 'arsenal'); });
    side.querySelector('input[name=sort][data-value=latest]').checked = true;
    if (searchInput) searchInput.value = '';
    applyFilters();
  };
  if (searchInput) searchInput.addEventListener('input', applyFilters);
  if (restoreFromQuery()) applyFilters();  // 상세에서 넘어온 필터 상태 복원 · 적용
  else sortCards();                        // 초기 정렬(최신순)
} else {
  // 상세 페이지: 카드가 없다 → 필터 적용은 필터된 인덱스로 이동 (spec ③).
  // 인덱스 경로는 로고 링크에서 얻는다 (Jinja root 를 JS 로 넘기지 않기 위함).
  const indexHref = document.querySelector('.logo')?.getAttribute('href') || 'index.html';
  if (side) side.addEventListener('change', () => applyBtn && applyBtn.classList.add('dirty'));
  if (applyBtn) applyBtn.onclick = () => {
    const qs = filterParams().toString();
    location.href = qs ? `${indexHref}?${qs}` : indexHref;
  };
  if (resetBtn) resetBtn.onclick = () => {
    enabledBoxes().forEach(c => { c.checked = (c.dataset.value === 'arsenal'); });
    side.querySelector('input[name=sort][data-value=latest]').checked = true;
    if (searchInput) searchInput.value = '';
    applyBtn && applyBtn.classList.remove('dirty');
  };
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/static/app.js tests/test_serve_render.py
git commit -m "$(cat <<'EOF'
feat(serve): 기자 필터 · URL 필터 상태 · 상세에서 필터된 인덱스 이동

상세 페이지의 필터 적용이 무동작이던 문제를 URL 쿼리 직렬화로 푼다 — 같은
계약으로 인덱스 필터도 북마크 · 공유 · 뒤로가기에서 되살아난다.

- journalist 그룹 필터: 카드 data-journalist OR 매칭
- URL 계약: outlet · tier · stage · bucket · journalist · sort · q (키 반복)
- 인덱스: 적용 시 replaceState 기록 · 로드 시 쿼리 복원 후 자동 적용
- 상세: 적용 시 로고 href 기준으로 필터된 인덱스 이동 · 초기화는 로컬 해제
- 더보기 토글 · 접힌 그룹에 선택된 기자가 있으면 자동 펼침

Refs: docs/superpowers/specs/2026-07-16-journalist-track-design.md
EOF
)"
```

---

### Task 9: journalist 백필 (1회성 CLI)

**Files:**
- Create: `src/bullet_in/backfill_journalist.py`
- Test: `tests/test_backfill_journalist.py`

**Interfaces:**
- Consumes: `extract_authors` (Task 1), `select_journalist` (Task 5), `resolve_tier(journalist=)` (Task 3), `load_sources` · `load_registry` · `confidence_from_tier`.
- Produces: `journalist_update(html: str, sid: str, url: str, sources: dict, registry) -> dict`
  — `{"journalist": str | None, "tier": float | None, "confidence_score": float}`.
- CLI: `uv run python -m bullet_in.backfill_journalist [--limit N] [--dry-run]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_backfill_journalist.py` 생성:

```python
import asyncio
from pathlib import Path
import httpx, respx
from bullet_in import backfill_journalist as bf
from bullet_in.backfill_journalist import journalist_update
from bullet_in.credibility import load_registry

REG = load_registry(Path("config/credibility.yaml"))
SOURCES = {
    "skysports": {"source_id": "skysports", "tier": 4, "outlet": "Sky Sports"},
    "football_london": {"source_id": "football_london", "tier": 4, "outlet": "football.london"},
    "goal": {"source_id": "goal", "tier": 4, "outlet": "Goal.com"},
}

def _ld(*names):
    people = ",".join('{"@type":"Person","name":"%s"}' % n for n in names)
    return ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[%s]}</script>' % people)

def test_update_promotes_tier_for_affiliated_journalist():
    out = journalist_update(_ld("Dharmesh Sheth"), "skysports", "https://x/1", SOURCES, REG)
    assert out == {"journalist": "Dharmesh Sheth", "tier": 1.5, "confidence_score": 0.625}

def test_update_keeps_source_tier_for_unregistered():
    out = journalist_update(_ld("Raff Tindale"), "football_london", "https://x/2", SOURCES, REG)
    assert out == {"journalist": "Raff Tindale", "tier": 4.0, "confidence_score": 0.0}

def test_update_keeps_source_tier_for_freelancer():
    # Watts 는 소속 미지정 → 표시만, tier 무조정 (사용자 결정)
    out = journalist_update(_ld("Charles Watts"), "goal", "https://x/3", SOURCES, REG)
    assert out == {"journalist": "Charles Watts", "tier": 4.0, "confidence_score": 0.0}

def test_update_picks_registered_author_among_many():
    out = journalist_update(_ld("Alastair Telfer", "Dharmesh Sheth"), "skysports",
                            "https://x/4", SOURCES, REG)
    assert out["journalist"] == "Dharmesh Sheth"

def test_update_journalist_none_when_no_author():
    out = journalist_update("<html><body>no author</body></html>", "goal",
                            "https://x/5", SOURCES, REG)
    assert out["journalist"] is None and out["tier"] == 4.0

# --- backfill() 재fetch 루프 — 실패 건도 요청 간격을 지키는지 (DB · 네트워크는 전부 모킹) ---

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
    def mappings(self):
        return self
    def all(self):
        return self._rows

class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
    def execute(self, *a, **k):
        return _FakeCursor(self._rows)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

class _FakeEngine:
    """engine.begin() 은 호출되면 실패 — 이 테스트는 실패 건만 다뤄 UPDATE 를 타면 안 된다."""
    def __init__(self, rows):
        self._rows = rows
    def connect(self):
        return _FakeConn(self._rows)
    def begin(self):
        raise AssertionError("실패 건만 있는 테스트에서 engine.begin() 이 호출됨")

_FETCH_SOURCES = {
    "testsrc": {"source_id": "testsrc", "tier": 4, "outlet": "Test Outlet",
                "adapter": "html", "config": {"body_selector": "article"}},
}
_ROWS = [
    {"content_hash": "h1", "url": "https://x.test/1", "source_id": "testsrc"},
    {"content_hash": "h2", "url": "https://x.test/2", "source_id": "testsrc"},
    {"content_hash": "h3", "url": "https://x.test/3", "source_id": "testsrc"},
]

@respx.mock
def test_backfill_sleeps_after_failed_rows(monkeypatch):
    """404 · 저자 부재로 continue 되는 건도 성공 건과 동일하게 간격을 지켜야 한다
    (마지막 건은 기존 의도대로 sleep 생략)."""
    respx.get("https://x.test/1").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/2").mock(return_value=httpx.Response(200, text="<html>no author</html>"))
    respx.get("https://x.test/3").mock(return_value=httpx.Response(404))

    monkeypatch.setenv("MARIADB_URL", "sqlite://dummy")
    monkeypatch.setattr(bf, "load_sources", lambda path: _FETCH_SOURCES)
    monkeypatch.setattr(bf, "load_registry", lambda path: REG)
    monkeypatch.setattr(bf, "create_engine", lambda url: _FakeEngine(_ROWS))

    sleep_calls = []
    async def fake_sleep(sec):
        sleep_calls.append(sec)
    monkeypatch.setattr(bf.asyncio, "sleep", fake_sleep)

    stats = asyncio.run(bf.backfill())

    assert stats["testsrc"] == {"ok": 0, "fail": 3}
    # i=0 (404) · i=1 (저자 부재) 는 마지막이 아니므로 각각 sleep, i=2 (404) 는 마지막이라 생략.
    assert len(sleep_calls) == 2
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backfill_journalist.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.backfill_journalist'`

- [ ] **Step 3: 구현**

`src/bullet_in/backfill_journalist.py` 생성:

```python
"""기존 기사의 journalist 백필 (1회성).

raw 저장소에 원본 HTML 이 없어 기사 URL 재fetch 가 유일한 경로다.
통칭 소스 (journalist_label) 는 재fetch 없이 일괄 채운다.
멱등 — 재실행 시 journalist IS NULL 인 행만 다시 시도한다.

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_journalist --limit 5 --dry-run
    uv run python -m bullet_in.backfill_journalist
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from datetime import datetime, timezone
import httpx
from sqlalchemy import bindparam, create_engine, text
from bullet_in.adapters.meta import extract_authors
from bullet_in.credibility import load_registry, resolve_tier
from bullet_in.models import RawItem
from bullet_in.pipeline import select_journalist
from bullet_in.score import load_sources, confidence_from_tier

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 소스별 순차 · 요청 간격 (라이브 사이트 부담 회피)

def journalist_update(html: str, sid: str, url: str, sources: dict, registry) -> dict:
    """재fetch 한 기사 HTML → 저장할 journalist · tier · confidence_score.
    선정 · 보정 규칙은 수집 경로와 같은 함수를 재사용한다 (규칙 이중화 방지)."""
    item = RawItem(source_id=sid, source_type="html", url=url,
                   fetched_at=datetime.now(timezone.utc),
                   raw_payload={"authors": extract_authors(html)})
    src = sources.get(sid, {})
    journalist = select_journalist(item, src, registry)
    tier = resolve_tier(item, sources, registry, journalist=journalist)
    return {"journalist": journalist, "tier": tier,
            "confidence_score": confidence_from_tier(tier)}

_SELECT_SQL = text(
    "SELECT content_hash, url, source_id FROM articles "
    "WHERE journalist IS NULL AND source_id IN :sids ORDER BY source_id, published_at DESC"
).bindparams(bindparam("sids", expanding=True))   # text() 의 IN 은 expanding 필수
_UPDATE_SQL = text(
    "UPDATE articles SET journalist=:j, tier=:t, confidence_score=:c "
    "WHERE content_hash=:h")

async def backfill(limit: int | None = None, dry_run: bool = False) -> dict[str, dict]:
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    # 재fetch 대상 = html 어댑터 · 상세를 읽는 소스 (body_selector) · 통칭 없는 곳.
    # adapter 조건이 없으면 fmkorea (config 에 body_selector 보유) 가 섞여 2h 규칙을 깬다.
    fetch_ids = [sid for sid, s in sources.items()
                 if s.get("adapter") == "html"
                 and s.get("config", {}).get("body_selector")
                 and not s.get("journalist_label")]
    label_ids = [sid for sid, s in sources.items() if s.get("journalist_label")]
    engine = create_engine(os.environ["MARIADB_URL"])
    stats: dict[str, dict] = {}

    # 1) 통칭 소스 — 재fetch 없이 일괄 UPDATE
    for sid in label_ids:
        label = sources[sid]["journalist_label"]
        if dry_run:
            log.info("[dry-run] %s → journalist=%r 일괄", sid, label)
            continue
        with engine.begin() as c:
            n = c.execute(text("UPDATE articles SET journalist=:j "
                               "WHERE journalist IS NULL AND source_id=:s"),
                          {"j": label, "s": sid}).rowcount
        stats[sid] = {"ok": n, "fail": 0}
        log.info("%s: 통칭 %r %d건", sid, label, n)

    # 2) 재fetch 대상 — 소스별 순차 · 간격
    with engine.connect() as c:
        rows = [dict(r) for r in
                c.execute(_SELECT_SQL, {"sids": fetch_ids}).mappings().all()]
    if limit:
        rows = rows[:limit]
    log.info("재fetch 대상 %d건 (소스 %s)", len(rows), ", ".join(fetch_ids))

    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "bullet-in/0.1"}) as client:
        for i, row in enumerate(rows):
            sid = row["source_id"]
            st = stats.setdefault(sid, {"ok": 0, "fail": 0})
            try:
                try:
                    r = await client.get(row["url"])
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    st["fail"] += 1                  # 404 · 타임아웃 → NULL 유지 · 다음 건
                    log.warning("fetch 실패 %s: %r", row["url"], e)
                    continue
                upd = journalist_update(r.text, sid, row["url"], sources, registry)
                if upd["journalist"] is None:
                    st["fail"] += 1
                    log.warning("저자 부재 %s", row["url"])
                    continue
                if dry_run:
                    log.info("[dry-run] %s → %r tier=%s", row["url"], upd["journalist"], upd["tier"])
                else:
                    with engine.begin() as c:
                        c.execute(_UPDATE_SQL, {"j": upd["journalist"], "t": upd["tier"],
                                                "c": upd["confidence_score"],
                                                "h": row["content_hash"]})
                st["ok"] += 1
            finally:
                # 실패 건 (continue) 도 finally 로 간격을 보장 — 성공 건만 간격이 걸리면
                # 429 · 430 레이트리밋에서 연속 실패가 지연 없이 반복돼 차단이 악화된다.
                if i < len(rows) - 1:
                    await asyncio.sleep(REQUEST_GAP_SEC)
    return stats

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="기존 기사 journalist 백필 (멱등)")
    ap.add_argument("--limit", type=int, default=None, help="재fetch 대상 상한 (드라이런 검증용)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    args = ap.parse_args()
    stats = asyncio.run(backfill(limit=args.limit, dry_run=args.dry_run))
    for sid, s in sorted(stats.items()):
        print(f"{sid}: 성공 {s['ok']} · 실패 {s['fail']}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backfill_journalist.py -q`
Expected: PASS (6 passed)

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 5: 커밋**

scope 는 `backfill` 이 아니라 컨벤션 §1.2 승인 세트의 `credibility` 를 쓴다 — 이 모듈의
주제가 기자 · tier 산출이고, 선례 `c174b15 chore(credibility): 기자 핸들 백필 · Sam Dean 등재`
가 같은 성격에 이 scope 를 썼다.

```bash
git add src/bullet_in/backfill_journalist.py tests/test_backfill_journalist.py
git commit -m "$(cat <<'EOF'
feat(credibility): 기존 기사 journalist 백필 CLI

raw 저장소에 원본 HTML 이 없어 재fetch 가 유일한 경로 — 수집 경로와 같은
선정 · 보정 함수를 재사용해 규칙이 두 벌로 갈라지지 않게 한다.

- journalist_update: extract_authors → select_journalist → resolve_tier 조합
- 통칭 소스 (arsenal_official · bbc_gossip): 재fetch 없이 일괄 UPDATE
- 재fetch 소스: 소스별 순차 · 1.5초 간격 (실패 건 포함 finally 로 보장) · --limit 드라이런
- 멱등 · 실패 격리: 404 · 저자 부재는 NULL 유지 · 소스별 성공 · 실패 집계 출력
- 단위테스트: 실패 건에서도 요청 간격이 걸리는지 검증 (respx · 엔진 모킹)

Refs: docs/superpowers/specs/2026-07-16-journalist-track-design.md
EOF
)"
```

---

### Task 10: 라이브 검증 · 백필 실행 · PR

**Files:**
- 코드 변경 없음 (검증에서 드러난 결함만 수정).

**Interfaces:**
- Consumes: Task 1–9 전부.

- [ ] **Step 1: 어댑터 단독 라이브 검증** (컨벤션 — 셀렉터 드리프트는 모킹 테스트가 못 잡는다)

Run:
```bash
set -a; source .env; set +a
uv run python -c "
import asyncio, os, yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open('config/sources.yaml'))
ids = {'bbc_sport', 'goal', 'football_london', 'skysports', 'guardian'}
cfg['sources'] = [s for s in cfg['sources'] if s['source_id'] in ids]
for a in build_adapters(cfg):
    items = asyncio.run(a.fetch())
    got = [it.raw_payload.get('authors') for it in items]
    filled = sum(1 for g in got if g)
    print(f'{a.source_id}: {len(items)}건 · authors 채움 {filled}건 · 예시 {got[:2]}')
"
```
Expected: 5소스 모두 `authors 채움` 이 1건 이상 (수집 0건인 소스는 예외 — 그 경우 목록 자체가 비었는지 확인).
채움 0건인 소스가 있으면 그 소스의 기사 URL 하나를 직접 열어 마크업 변화를 확인하고, Task 1 파서를 고친 뒤 이 단계를 다시 실행한다.

- [ ] **Step 2: 백필 드라이런**

Run:
```bash
set -a; source .env; set +a
uv run python -m bullet_in.backfill_journalist --limit 5 --dry-run
```
Expected: `[dry-run] https://... → '이름' tier=...` 형태 로그 5건 · 예외 없음 · DB 무변경.

Run (DB 무변경 확인):
```bash
set -a; source .env; set +a
uv run python -c "
import os, re
from sqlalchemy import create_engine, text
e = create_engine(os.environ['MARIADB_URL'])
with e.connect() as c:
    print(c.execute(text('SELECT COUNT(*) FROM articles WHERE journalist IS NOT NULL')).scalar_one())
"
```
Expected: `19` (백필 전 기준선 — x_afcstuff 13 + fmkorea 6)

- [ ] **Step 3: 백필 전건 실행**

Run:
```bash
set -a; source .env; set +a
uv run python -m bullet_in.backfill_journalist
```
Expected: 소스별 `성공 N · 실패 M` 요약 출력. 재fetch 233건 × 1.5초 → 약 6분 소요.

- [ ] **Step 4: 채움률 · tier 보정 검증**

Run:
```bash
set -a; source .env; set +a
uv run python -c "
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ['MARIADB_URL'])
with e.connect() as c:
    for r in c.execute(text('SELECT source_id, COUNT(*) n, SUM(journalist IS NOT NULL) wj '
                            'FROM articles GROUP BY source_id ORDER BY n DESC')):
        print(r)
    print('--- 상위 기자')
    for r in c.execute(text('SELECT journalist, COUNT(*) n FROM articles '
                            'WHERE journalist IS NOT NULL GROUP BY journalist '
                            'ORDER BY n DESC LIMIT 10')):
        print(r)
"
```
Expected: arsenal_official · bbc_gossip 는 100% 채움, 나머지 html 소스는 대부분 채움 (일부 404 로 NULL 잔존 허용).
`fmkorea` 15건은 여전히 NULL (한글 말머리에 기자가 없는 게시글 — 정상).

- [ ] **Step 5: 사이트 재생성 · 육안 확인**

Run:
```bash
set -a; source .env; set +a
uv run python -c "
import os
from sqlalchemy import create_engine, text
from bullet_in.score import load_sources
from bullet_in.credibility import journalist_directory
from bullet_in.serve.render import write_site
e = create_engine(os.environ['MARIADB_URL'])
with e.connect() as c:
    rows = [dict(r) for r in c.execute(text(
        'SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,'
        'summary3_ko,body_ko,image_url,images_json,outlet,journalist,team,'
        'transfer_stage,tier,confidence_score,published_at FROM articles')).mappings().all()]
write_site(rows, load_sources('config/sources.yaml'), 'site',
           directory=journalist_directory('config/credibility.yaml'))
print('rendered', len(rows))
"
python3 -m http.server 8765 --directory site
```
브라우저에서 `http://localhost:8765/index.html` 확인:
- 사이드바 "기자" 섹션에 등재 기자가 `이름 (언론사)` 로 노출되고, "더보기 N명" 클릭 시 미등재 기자 · 통칭이 펼쳐진다.
- 기자 체크 → "필터 적용" → 카드가 좁혀지고 URL 에 `?journalist=...` 가 남는다.
- 그 URL 을 새 탭에 붙여넣으면 체크 상태 · 필터가 복원된다.
- 상세 페이지로 들어가 사이드바에서 기자 · tier 를 체크하고 "필터 적용" → 필터가 걸린 인덱스로 이동한다.
- 상세 바이라인이 `이름 (언론사)` 로 보인다.
확인 후 `Ctrl-C` 로 서버를 내린다.

- [ ] **Step 6: 전체 테스트 · PR**

Run: `uv run pytest -q`
Expected: PASS

```bash
git push -u origin feat/journalist-track
```

PR 본문은 `.github/pull_request_template.md` 의 7섹션 구조 · 주석 세칙 (명사형 불릿 · `**핵심어** — 설명` · LOC 기준) 을 직접 대조해 작성하고 `--body-file` 로 전달한다.
**Claude 서명 금지** (컨벤션 §2.7).

```bash
gh pr create --title "feat(journalist): 기자 추출 · 소속 일치 tier 보정 · 기자 facet · 상세 필터 이동" --body-file /tmp/pr-body.md
```

---

## 부록: 라이브 실측 기준선 (2026-07-15 · 2026-07-16)

- `journalist` 채움: x_afcstuff 13/13 · fmkorea 6/21 · html 소스 0/274.
- 소스별 적재: football_london 205 · bbc_gossip 41 · fmkorea 21 · x_afcstuff 13 · goal 12 · skysports 10 · bbc_sport 6 · guardian 0 · arsenal_official 0.
- guardian 0건 원인: `GUARDIAN_API_KEY` 추가 (7/15 19:47) 가 마지막 실행 (7/15 10:26) 이후 — 키 · 어댑터 정상 (단독 fetch 3건 통과).
- arsenal_official 0건 원인: 현행 고정밀 필터 (남자팀 URL + 제목 `sign`) — 공식 영입 발표가 있어야 적재된다. 정상 동작.
