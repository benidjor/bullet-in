# Tier 2-a 서빙 · 웹 UI 개편 (Plan 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR #11(Tier 2-a 백엔드)에서 채워진 `articles` 데이터를 의존성 0의 정적 웹 UI(이미지 카드 인덱스 + 별도 상세 페이지 + 검색 + 사이드바 필터 + 라이트/다크)로 렌더링한다.

**Architecture:** `serve/render.py`의 순수 헬퍼(시간 표기·outlet 폴백·facet 카운트·이웃 슬라이딩 윈도우)를 TDD로 만들고, Jinja2 템플릿(공용 레이아웃 + 인덱스 + 상세)과 정적 자산(`style.css`·`app.js`)을 목업에서 이식한다. `write_site()`가 `index.html` + `article/<content_hash>.html` N개 + 정적 자산 복사를 생성하고, `run.py`의 SELECT/호출부를 교체한다. 검색·필터·정렬·테마는 클라이언트(`app.js`)에서 카드의 `data-*` 속성으로 수행 — 서버 재요청 불필요.

**Tech Stack:** Python 3.11, Jinja2(기존 의존성, autoescape on), 순수 CSS, 바닐라 JS(빌드 도구·프레임워크 0), pytest.

## Global Constraints

- **의존성 0**: 빌드 도구·프레임워크·CDN·외부 JS/CSS 라이브러리 금지. 정적 파일(`style.css`·`app.js`)만. (spec §7.1)
- **상세 파일명 = `content_hash`**: `site/article/<content_hash>.html` (안정·회차 간 불변). (spec §7.1)
- **outlet 폴백**: 표시 언론사명 = `row["outlet"]` → 없으면 `sources[source_id]["display_name"]` → 그래도 없으면 `source_id`. (직접 EN 소스는 `outlet` NULL.)
- **이미지 폴백**: `image_url` 없으면 그라데이션 플레이스홀더 썸네일/히어로(목업 `.thumb`/`.hero`). (spec §7.2)
- **영입 단계 = 2-b**: 사이드바 "영입 단계" 그룹은 **비활성 자리(disabled)** 로만 노출, 카드 썸네일 단계 배지는 렌더하지 않는다(데이터 없음). 카드 칩은 **team · outlet · tier** 만. (spec §2-b, §7.2)
- **타 구단 = 2-b**: 사이드바 팀은 Arsenal만 활성, 그 외 `예정` disabled.
- **기본 정렬 = 최신순**(`published_at` desc). 신뢰도순은 `confidence_score` desc. (목업 정렬 라디오 기본값)
- **autoescape 유지**: 스크랩된 본문/제목은 Jinja autoescape로 이스케이프(XSS 안전). `| safe` 사용 금지.
- **산출물 본문은 한국어**. 공개 저장소: 코드/주석에 Claude 서명·이직 프레이밍 금지.
- 테스트 실행: `uv run pytest -q`.

---

## 파일 구조

**생성**
- `src/bullet_in/serve/templates/_layout.html.j2` — 공용 골격(head·topbar·검색·테마·사이드바·shell). 블록: `title`, `nav_active`, `content`.
- `src/bullet_in/serve/templates/detail.html.j2` — 상세 페이지(extends `_layout`).
- `src/bullet_in/serve/static/style.css` — 목업 CSS 이식(라이트/다크 변수).
- `src/bullet_in/serve/static/app.js` — 검색·필터 적용/초기화·정렬·테마 토글(바닐라).
- `tests/test_serve_layout.py` — 순수 헬퍼 단위 테스트.
- `tests/test_serve_render.py` — 인덱스/상세 렌더 HTML 구조 테스트(기존 `tests/test_render.py` 대체).

**수정**
- `src/bullet_in/serve/render.py` — 순수 헬퍼 + `render_index`/`render_article`/`write_site`로 전면 개편(기존 `render_page`/`write_page` 대체).
- `src/bullet_in/serve/templates/index.html.j2` — 미니멀 → 카드 그리드(extends `_layout`)로 교체.
- `src/bullet_in/run.py:55-59` — SELECT 컬럼 확장 + `write_site(rows, sources, "site")` 호출.

**삭제**
- `tests/test_render.py` — `render_page` 제거에 따라 `tests/test_serve_render.py`로 대체(Task 5에서).

---

## Task 1: 순수 렌더 헬퍼 (시간 · outlet · tier · 윈도우 · facet)

`render.py`에 외부 의존 없는 순수 함수를 먼저 만든다. 템플릿/IO 없음. 전부 단위 테스트로 고정.

**Files:**
- Modify: `src/bullet_in/serve/render.py`
- Test: `tests/test_serve_layout.py`

**Interfaces:**
- Consumes: 없음(표준 라이브러리 `datetime`, `collections.Counter`).
- Produces (이후 태스크가 의존하는 시그니처):
  - `humanize_when(dt: datetime, now: datetime) -> str` — "방금 전" / "N분 전" / "N시간 전" / "N일 전" / "YYYY-MM-DD"(7일 초과).
  - `fmt_date(dt: datetime) -> str` — "YYYY-MM-DD".
  - `outlet_display(row: dict, sources: dict) -> str` — outlet 폴백.
  - `tier_label(tier) -> str` — `None`→"tier ?", 그 외 "tier {int}".
  - `neighbor_window(n: int, idx: int, size: int = 5) -> tuple[int, int]` — 슬라이딩 윈도우 `(start, end)` (end 배타, 파이썬 슬라이스용).
  - `facet_counts(articles: list[dict], sources: dict) -> dict` — `{"total": int, "team": {"arsenal": int}, "outlets": [(name, count), ...], "tiers": {0..4: count}}`. outlets는 count desc, 동률은 이름 asc.

- [ ] **Step 1: 헬퍼 실패 테스트 작성**

`tests/test_serve_layout.py` 생성:

```python
from datetime import datetime
from bullet_in.serve.render import (
    humanize_when, fmt_date, outlet_display, tier_label,
    neighbor_window, facet_counts,
)

NOW = datetime(2026, 6, 29, 12, 0, 0)

def test_humanize_when_buckets():
    assert humanize_when(datetime(2026, 6, 29, 11, 59, 30), NOW) == "방금 전"
    assert humanize_when(datetime(2026, 6, 29, 11, 30, 0), NOW) == "30분 전"
    assert humanize_when(datetime(2026, 6, 29, 10, 0, 0), NOW) == "2시간 전"
    assert humanize_when(datetime(2026, 6, 27, 12, 0, 0), NOW) == "2일 전"
    # 7일 초과는 절대 날짜
    assert humanize_when(datetime(2026, 6, 1, 12, 0, 0), NOW) == "2026-06-01"

def test_fmt_date():
    assert fmt_date(datetime(2026, 6, 29, 9, 5)) == "2026-06-29"

def test_outlet_display_prefers_outlet_then_displayname_then_id():
    sources = {"bbc_sport": {"display_name": "BBC Sport"}}
    assert outlet_display({"outlet": "The Athletic", "source_id": "x"}, sources) == "The Athletic"
    assert outlet_display({"outlet": None, "source_id": "bbc_sport"}, sources) == "BBC Sport"
    assert outlet_display({"outlet": None, "source_id": "unknown"}, sources) == "unknown"

def test_tier_label():
    assert tier_label(2) == "tier 2"
    assert tier_label(2.0) == "tier 2"
    assert tier_label(None) == "tier ?"

def test_neighbor_window_centers_and_clamps():
    assert neighbor_window(10, 5) == (3, 8)   # 중앙: i-2..i+2
    assert neighbor_window(10, 0) == (0, 5)   # 최신 근처
    assert neighbor_window(10, 1) == (0, 5)
    assert neighbor_window(10, 9) == (5, 10)  # 과거 근처
    assert neighbor_window(10, 8) == (5, 10)
    assert neighbor_window(3, 1) == (0, 3)    # n<size: 전부
    assert neighbor_window(5, 2) == (0, 5)

def test_facet_counts():
    arts = [
        {"source_id": "bbc_sport", "outlet": "BBC Sport", "tier": 2, "team": "arsenal"},
        {"source_id": "bbc_sport", "outlet": "BBC Sport", "tier": 2, "team": "arsenal"},
        {"source_id": "x", "outlet": None, "tier": 0, "team": "arsenal"},
    ]
    sources = {"x": {"display_name": "afcstuff"}}
    f = facet_counts(arts, sources)
    assert f["total"] == 3
    assert f["team"] == {"arsenal": 3}
    assert f["outlets"] == [("BBC Sport", 2), ("afcstuff", 1)]
    assert f["tiers"] == {0: 1, 1: 0, 2: 2, 3: 0, 4: 0}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_layout.py -q`
Expected: FAIL — `ImportError: cannot import name 'humanize_when'`.

- [ ] **Step 3: 헬퍼 구현**

`src/bullet_in/serve/render.py` 상단(기존 import 아래)에 추가. 기존 `render_page`/`write_page`는 Task 5에서 교체하므로 지금은 그대로 둔다.

```python
from __future__ import annotations
from collections import Counter
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TPL_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def humanize_when(dt: datetime, now: datetime) -> str:
    delta = now - dt
    secs = delta.total_seconds()
    if secs < 60:
        return "방금 전"
    mins = int(secs // 60)
    if mins < 60:
        return f"{mins}분 전"
    hours = mins // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    if days <= 7:
        return f"{days}일 전"
    return dt.strftime("%Y-%m-%d")


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def outlet_display(row: dict, sources: dict) -> str:
    return (row.get("outlet")
            or sources.get(row.get("source_id"), {}).get("display_name")
            or row.get("source_id") or "")


def tier_label(tier) -> str:
    if tier is None:
        return "tier ?"
    return f"tier {int(tier)}"


def neighbor_window(n: int, idx: int, size: int = 5) -> tuple[int, int]:
    if n <= size:
        return (0, n)
    start = idx - size // 2
    if start < 0:
        start = 0
    end = start + size
    if end > n:
        end = n
        start = end - size
    return (start, end)


def facet_counts(articles: list[dict], sources: dict) -> dict:
    teams = Counter(a.get("team") or "arsenal" for a in articles)
    outlet_ctr = Counter(outlet_display(a, sources) for a in articles)
    outlets = sorted(outlet_ctr.items(), key=lambda kv: (-kv[1], kv[0]))
    tiers = {t: 0 for t in range(5)}
    for a in articles:
        t = a.get("tier")
        if t is not None and 0 <= int(t) <= 4:
            tiers[int(t)] += 1
    return {"total": len(articles), "team": dict(teams),
            "outlets": outlets, "tiers": tiers}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_serve_layout.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_layout.py
git commit -m "feat(serve): 렌더 순수 헬퍼(시간·outlet 폴백·tier·슬라이딩 윈도우·facet)"
```

---

## Task 2: 정적 자산 (style.css · app.js)

목업의 CSS/JS를 정적 파일로 이식한다. CSS는 인덱스·상세 양쪽 클래스를 모두 포함(합집합). JS는 목업의 "상태 텍스트만 갱신"을 **실제 카드 검색·필터·정렬**로 확장한다.

**Files:**
- Create: `src/bullet_in/serve/static/style.css`
- Create: `src/bullet_in/serve/static/app.js`
- Test: `tests/test_serve_render.py` (구조 가드만; 본 파일은 Task 5에서 확장)

**Interfaces:**
- Consumes: 템플릿이 생성하는 DOM 계약 — `#q`(검색 input), `.side`(사이드바), `#applyBtn`/`#resetBtn`/`#themeBtn`/`#fstatus`, `.grid`(인덱스에만 존재), 카드 `a.card[data-team][data-outlet][data-tier][data-published][data-confidence][data-text]`.
- Produces: 클라이언트 동작(테마 영속, 실시간 검색, 적용/초기화, 정렬). 자동 검증은 구조 가드 + 브라우저 수동 체크(Task 6).

- [ ] **Step 1: `style.css` 작성**

목업 `index.html`/`detail.html`의 `<style>` 전체를 합쳐 `src/bullet_in/serve/static/style.css`로 저장한다(두 목업의 규칙 합집합; 중복 규칙은 한 번만). `.thumb`/`.hero`/`.card`/`.side`/`.opt`/`.btn`/`.summary`/`.body`/`.origin`/`.more`/반응형 `@media` 포함. `:root`와 `html[data-theme="dark"]` 변수 블록을 그대로 옮긴다. (목업 파일: `docs/superpowers/specs/assets/2026-06-29-tier2a/{index,detail}.html` 의 `<style>` 본문 그대로.)

> 주의: 목업 CSS를 **수정 없이** 옮긴다. 클래스명을 바꾸면 템플릿(Task 3·4)이 어긋난다.

- [ ] **Step 2: `app.js` 작성**

`src/bullet_in/serve/static/app.js`:

```javascript
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

const enabledBoxes = () => [...side.querySelectorAll('input[type=checkbox]:not([disabled])')];
const checkedValues = (group) =>
  enabledBoxes().filter(c => c.dataset.group === group && c.checked).map(c => c.dataset.value);

function applyFilters() {
  const q = (searchInput.value || '').trim().toLowerCase();
  const outlets = checkedValues('outlet');
  const tiers = checkedValues('tier');
  let shown = 0;
  for (const card of cards) {
    const okText = !q || (card.dataset.text || '').includes(q);
    const okOutlet = outlets.length === 0 || outlets.includes(card.dataset.outlet);
    const okTier = tiers.length === 0 || tiers.includes(card.dataset.tier);
    const visible = okText && okOutlet && okTier;
    card.style.display = visible ? '' : 'none';
    if (visible) shown++;
  }
  sortCards();
  const sort = side.querySelector('input[name=sort]:checked').dataset.value;
  const conds = outlets.length + tiers.length + (q ? 1 : 0);
  fstatus.textContent = conds || q
    ? `적용됨 · 조건 ${conds}개 · ${shown}건`
    : `미적용 · 전체 ${shown}건`;
  applyBtn.classList.remove('dirty');
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
  sortCards(); // 초기 정렬(최신순)
} else {
  // 상세 페이지: 카드 없음 → 검색/필터는 상태만(목업 동작 유지)
  if (applyBtn) applyBtn.onclick = () => applyBtn.classList.remove('dirty');
  if (side) side.addEventListener('change', () => applyBtn && applyBtn.classList.add('dirty'));
}
```

- [ ] **Step 3: 자산 존재·계약 구조 가드 테스트 작성**

`tests/test_serve_render.py` 생성(자산 가드 부분만; 렌더 테스트는 Task 3·4에서 추가):

```python
from pathlib import Path

STATIC = Path("src/bullet_in/serve/static")

def test_static_assets_exist_and_nonempty():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-theme" in css and "--bg" in css      # 테마 변수
    assert ".card" in css and ".side" in css
    assert "data-outlet" in js and "data-tier" in js   # 카드 필터 계약
    assert "localStorage" in js                        # 테마 영속
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/static/style.css src/bullet_in/serve/static/app.js tests/test_serve_render.py
git commit -m "feat(serve): 정적 자산(테마·검색·필터·정렬 바닐라 JS + 목업 CSS 이식)"
```

---

## Task 3: 공용 레이아웃 + 인덱스 템플릿 · `render_index`

목업 골격(topbar·검색·테마·사이드바·shell)을 공용 레이아웃으로 만들고, 인덱스는 카드 그리드를 채운다. `render_index(articles, sources, now)`가 정렬·facet을 계산해 렌더.

**Files:**
- Create: `src/bullet_in/serve/templates/_layout.html.j2`
- Modify: `src/bullet_in/serve/templates/index.html.j2`
- Modify: `src/bullet_in/serve/render.py`
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: Task 1 헬퍼(`humanize_when`·`outlet_display`·`tier_label`·`facet_counts`), Task 2 정적 자산 계약.
- Produces: `render_index(articles: list[dict], sources: dict, now: datetime) -> str`. 정렬: `published_at` desc(최신). 카드 링크 `article/<content_hash>.html`.

- [ ] **Step 1: `_layout.html.j2` 작성**

목업의 topbar·scrim·shell·사이드바를 블록화. `facets`·`active` 컨텍스트를 받는다.

```jinja
<!doctype html>
<html lang="ko" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}Bullet-in{% endblock %}</title>
<link rel="stylesheet" href="{{ root }}style.css">
</head>
<body>
<div class="topbar"><div class="inner">
  <button class="iconbtn hamb" onclick="document.querySelector('.side').classList.toggle('open');document.querySelector('.scrim').classList.toggle('open')">☰</button>
  <a class="logo" href="{{ root }}index.html"><span class="crest">B</span>Bullet-in</a>
  <nav class="nav">
    <a class="{{ 'active' if active == 'home' else '' }}" href="{{ root }}index.html">홈</a>
    <a href="#">소개</a>
    <a href="#">일정</a>
  </nav>
  <label class="search">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3-3"/></svg>
    <input id="q" placeholder="선수·구단·이적 키워드 검색 (예: 요케레스, 재계약)">
  </label>
  <span class="spacer"></span>
  <button class="iconbtn" id="themeBtn" title="라이트/다크 전환">🌙</button>
</div></div>

<div class="scrim" onclick="document.querySelector('.side').classList.remove('open');this.classList.remove('open')"></div>

<div class="shell">
  <aside class="side">
    <h4>팀</h4>
    <label class="opt"><input type="checkbox" data-group="team" data-value="arsenal" checked> Arsenal <span class="ct">{{ facets.team.get('arsenal', 0) }}</span></label>
    <label class="opt disabled"><input type="checkbox" disabled> Manchester United <span class="soon">예정</span></label>
    <label class="opt disabled"><input type="checkbox" disabled> Chelsea <span class="soon">예정</span></label>
    <label class="opt disabled"><input type="checkbox" disabled> Liverpool <span class="soon">예정</span></label>
    <label class="opt disabled"><input type="checkbox" disabled> Tottenham <span class="soon">예정</span></label>

    <h4>영입 단계</h4>
    <label class="opt disabled"><input type="checkbox" disabled><span class="stage s-off"></span>오피셜 <span class="soon">예정</span></label>
    <label class="opt disabled"><input type="checkbox" disabled><span class="stage s-med"></span>메디컬 <span class="soon">예정</span></label>
    <label class="opt disabled"><input type="checkbox" disabled><span class="stage s-talk"></span>협상 중 <span class="soon">예정</span></label>
    <label class="opt disabled"><input type="checkbox" disabled><span class="stage s-rum"></span>루머 <span class="soon">예정</span></label>

    <h4>소스 (언론사)</h4>
    {% for name, count in facets.outlets %}
    <label class="opt"><input type="checkbox" data-group="outlet" data-value="{{ name }}"> {{ name }} <span class="ct">{{ count }}</span></label>
    {% endfor %}

    <h4>신뢰도 (Tier)</h4>
    {% for t in range(5) %}
    <label class="opt"><input type="checkbox" data-group="tier" data-value="{{ t }}"> tier {{ t }} <span class="ct">{{ facets.tiers[t] }}</span></label>
    {% endfor %}

    <h4>정렬</h4>
    <label class="opt sortrow"><input type="radio" name="sort" data-value="latest" checked> 최신순</label>
    <label class="opt sortrow"><input type="radio" name="sort" data-value="confidence"> 신뢰도순</label>

    <div class="fstatus" id="fstatus">미적용 · 전체 표시</div>
    <div class="actions">
      <button class="btn reset" id="resetBtn">초기화</button>
      <button class="btn apply" id="applyBtn">필터 적용</button>
    </div>
  </aside>

  <main>{% block content %}{% endblock %}</main>
</div>

<script src="{{ root }}app.js"></script>
</body>
</html>
```

> `root`는 상대 경로 접두사(인덱스="", 상세="../"). 정적 자산·내비 링크가 두 깊이에서 모두 동작하게 한다.

- [ ] **Step 2: `index.html.j2` 교체**

기존 미니멀 내용을 전부 지우고:

```jinja
{% extends "_layout.html.j2" %}
{% block title %}Bullet-in · 인덱스{% endblock %}
{% block content %}
<div class="grid">
{% for a in articles %}
  <a class="card" href="article/{{ a.content_hash }}.html"
     data-team="{{ a.team or 'arsenal' }}"
     data-outlet="{{ a._outlet }}"
     data-tier="{{ a.tier | int if a.tier is not none else '' }}"
     data-published="{{ a._published_iso }}"
     data-confidence="{{ a.confidence_score or 0 }}"
     data-text="{{ (a._title ~ ' ' ~ (a.summary_ko or '')) | lower }}">
    {% if a.image_url %}
    <div class="thumb" style="background-image:url('{{ a.image_url }}');background-size:cover;background-position:center"></div>
    {% else %}
    <div class="thumb">PHOTO · 16:9</div>
    {% endif %}
    <div class="pad">
      <div class="chips">
        <span class="chip team">{{ '아스날' if (a.team or 'arsenal') == 'arsenal' else a.team }}</span>
        <span class="chip src">{{ a._outlet }}</span>
        <span class="chip tier">{{ a._tier_label }}</span>
        <span class="when">{{ a._when }}</span>
      </div>
      <h2>{{ a._title }}</h2>
      <p>{{ a.summary_ko or "" }}</p>
    </div>
  </a>
{% endfor %}
</div>
{% endblock %}
```

> 템플릿이 행마다 헬퍼를 호출하지 않도록, `render_index`가 미리 `_title`·`_outlet`·`_tier_label`·`_when`·`_published_iso` 파생 키를 채워 넘긴다(아래 Step 4).

- [ ] **Step 3: 인덱스 렌더 실패 테스트 작성**

`tests/test_serve_render.py`에 추가:

```python
from datetime import datetime
from bullet_in.serve.render import render_index

NOW = datetime(2026, 6, 29, 12, 0, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"}}

def _row(**kw):
    base = dict(content_hash="h1", url="https://x/1", source_id="bbc_sport",
                title_original="Original", title_ko="한국어 제목", summary_ko="한 줄 요약",
                tier=2, confidence_score=0.5, image_url=None, outlet=None,
                team="arsenal", published_at=datetime(2026, 6, 29, 10, 0, 0))
    base.update(kw); return base

def test_index_card_has_data_attrs_and_link():
    html = render_index([_row()], SOURCES, NOW)
    assert 'href="article/h1.html"' in html
    assert 'data-outlet="BBC Sport"' in html   # outlet NULL → display_name 폴백
    assert 'data-tier="2"' in html
    assert 'data-published="2026-06-29T10:00:00"' in html
    assert 'data-confidence="0.5"' in html

def test_index_prefers_korean_title_and_escapes():
    html = render_index([_row(title_ko=None, title_original="A & B <script>x</script>")], SOURCES, NOW)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    html2 = render_index([_row()], SOURCES, NOW)
    assert "한국어 제목" in html2

def test_index_placeholder_when_no_image():
    html = render_index([_row(image_url=None)], SOURCES, NOW)
    assert "PHOTO · 16:9" in html
    html2 = render_index([_row(image_url="https://img/x.jpg")], SOURCES, NOW)
    assert "https://img/x.jpg" in html2

def test_index_sorts_latest_first():
    old = _row(content_hash="old", title_ko="옛날", published_at=datetime(2026, 6, 28, 0, 0))
    new = _row(content_hash="new", title_ko="최신", published_at=datetime(2026, 6, 29, 11, 0))
    html = render_index([old, new], SOURCES, NOW)
    assert html.index("최신") < html.index("옛날")

def test_index_renders_facet_counts_and_disabled_stage():
    html = render_index([_row(), _row(content_hash="h2")], SOURCES, NOW)
    assert "tier 2" in html
    # 영입 단계는 비활성 자리(2-b)
    assert "영입 단계" in html and html.count("disabled") >= 4
```

- [ ] **Step 4: `render_index` 구현**

`render.py`에 추가(기존 `render_page`/`write_page`는 Task 5에서 제거):

```python
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TPL_DIR),
        autoescape=select_autoescape(default_for_string=True, default=True),
    )


def _decorate(row: dict, sources: dict, now: datetime) -> dict:
    a = dict(row)
    a["_title"] = row.get("title_ko") or row.get("title_original") or ""
    a["_outlet"] = outlet_display(row, sources)
    a["_tier_label"] = tier_label(row.get("tier"))
    pub = row.get("published_at")
    a["_when"] = humanize_when(pub, now) if pub else ""
    a["_published_iso"] = pub.isoformat() if pub else ""
    a["_date"] = fmt_date(pub) if pub else ""
    return a


def _sorted_latest(articles: list[dict]) -> list[dict]:
    return sorted(articles,
                  key=lambda a: a.get("published_at") or datetime.min,
                  reverse=True)


def render_index(articles: list[dict], sources: dict, now: datetime) -> str:
    ordered = [_decorate(a, sources, now) for a in _sorted_latest(articles)]
    facets = facet_counts(articles, sources)
    return _env().get_template("index.html.j2").render(
        articles=ordered, facets=facets, active="home", root="")
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: PASS (자산 가드 1 + 인덱스 5 = 6 passed).

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/serve/templates/_layout.html.j2 src/bullet_in/serve/templates/index.html.j2 src/bullet_in/serve/render.py tests/test_serve_render.py
git commit -m "feat(serve): 공용 레이아웃 + 카드 인덱스 render_index(최신순·facet·outlet 폴백)"
```

---

## Task 4: 상세 템플릿 · `render_article` (3줄 요약 · 본문 · 출처 · 이웃 5목록)

상세 페이지: 히어로 + 칩 + 제목 + 3줄 요약 박스 + 전체 번역 본문 + 출처 + 하단 5목록(현재 글 중심 슬라이딩 윈도우).

**Files:**
- Create: `src/bullet_in/serve/templates/detail.html.j2`
- Modify: `src/bullet_in/serve/render.py`
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: Task 1 헬퍼, Task 3 `_layout.html.j2`·`_decorate`·`_sorted_latest`.
- Produces: `render_article(article: dict, neighbors: list[dict], current_hash: str, sources: dict, now: datetime) -> str`. `neighbors`는 슬라이딩 윈도우로 잘린 데코된 행들(현재 글 포함), 각 행에 `_is_current` 플래그.

- [ ] **Step 1: `detail.html.j2` 작성**

```jinja
{% extends "_layout.html.j2" %}
{% block title %}{{ a._title }} · Bullet-in{% endblock %}
{% block content %}
<a class="back" href="{{ root }}index.html">← 목록으로</a>
<article class="article">
  {% if a.image_url %}
  <div class="hero" style="background-image:url('{{ a.image_url }}');background-size:cover;background-position:center"></div>
  {% else %}
  <div class="hero">HERO IMAGE · 21:9</div>
  {% endif %}
  <div class="pad">
    <div class="chips">
      <span class="chip team">{{ '아스날' if (a.team or 'arsenal') == 'arsenal' else a.team }}</span>
      <span class="chip src">{{ a._outlet }}</span>
      <span class="chip tier">{{ a._tier_label }}</span>
      <span class="when">{{ a._date }}</span>
    </div>
    <h2 class="title">{{ a._title }}</h2>
    {% if a.summary3_ko %}
    <section class="summary">
      <h3>3줄 요약</h3>
      <ul>{% for line in a.summary3_ko.split('\n') if line.strip() %}<li>{{ line }}</li>{% endfor %}</ul>
    </section>
    {% endif %}
    <div class="body">
      {% for para in (a.body_ko or "").split('\n') if para.strip() %}<p>{{ para }}</p>{% endfor %}
    </div>
    <p class="origin">출처: {{ a._outlet }}{% if a.journalist %} · {{ a.journalist }}{% endif %} · <a href="{{ a.url }}" target="_blank" rel="noopener">원문 기사 보기 ↗</a></p>
  </div>
</article>

<section class="more">
  <h3>기사 목록 · 현재 글 중심</h3>
  <ul>
  {% for n in neighbors %}
    <li class="{{ 'cur' if n._is_current else '' }}">
      <a href="{{ root }}article/{{ n.content_hash }}.html">
        <span class="mt">{% if n._is_current %}<span class="nowtag">지금</span>{% endif %}{{ n._title }}</span>
        <span class="ms">{{ n._outlet }} · {{ n._tier_label }}</span>
      </a>
    </li>
  {% endfor %}
  </ul>
</section>
{% endblock %}
```

- [ ] **Step 2: 상세 렌더 실패 테스트 작성**

`tests/test_serve_render.py`에 추가:

```python
from bullet_in.serve.render import render_article, build_neighbors

def test_detail_shows_summary3_body_and_origin():
    a = _row(content_hash="cur", summary3_ko="첫째 줄\n둘째 줄\n셋째 줄",
             body_ko="첫 문단입니다.\n둘째 문단입니다.", journalist="사미 목벨",
             url="https://src/article")
    nb = build_neighbors([a], 0, SOURCES, NOW)
    html = render_article(_decorated(a), nb, "cur", SOURCES, NOW)
    assert "3줄 요약" in html
    assert "첫째 줄" in html and "셋째 줄" in html
    assert "<li>첫째 줄</li>" in html
    assert "<p>첫 문단입니다.</p>" in html and "<p>둘째 문단입니다.</p>" in html
    assert "사미 목벨" in html
    assert 'href="https://src/article"' in html

def test_detail_neighbor_window_marks_current():
    arts = [_row(content_hash=f"h{i}", title_ko=f"기사{i}",
                 published_at=datetime(2026, 6, 29, 12 - i, 0)) for i in range(10)]
    ordered = sorted(arts, key=lambda x: x["published_at"], reverse=True)
    idx = 5
    nb = build_neighbors(ordered, idx, SOURCES, NOW)
    assert len(nb) == 5
    cur = [n for n in nb if n["_is_current"]]
    assert len(cur) == 1 and cur[0]["content_hash"] == ordered[idx]["content_hash"]
    html = render_article(_decorated(ordered[idx]), nb, ordered[idx]["content_hash"], SOURCES, NOW)
    assert html.count("지금") == 1

def test_detail_small_corpus_shows_all():
    arts = [_row(content_hash=f"h{i}", title_ko=f"기사{i}") for i in range(3)]
    nb = build_neighbors(arts, 1, SOURCES, NOW)
    assert len(nb) == 3
```

테스트 헬퍼(파일 상단에 추가):

```python
def _decorated(row):
    from bullet_in.serve.render import _decorate
    return _decorate(row, SOURCES, NOW)
```

- [ ] **Step 3: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: FAIL — `cannot import name 'render_article'`.

- [ ] **Step 4: `render_article` + `build_neighbors` 구현**

`render.py`에 추가:

```python
def build_neighbors(ordered: list[dict], idx: int, sources: dict,
                    now: datetime) -> list[dict]:
    start, end = neighbor_window(len(ordered), idx)
    out = []
    for j in range(start, end):
        d = _decorate(ordered[j], sources, now)
        d["_is_current"] = (j == idx)
        out.append(d)
    return out


def render_article(article: dict, neighbors: list[dict], current_hash: str,
                   sources: dict, now: datetime) -> str:
    return _env().get_template("detail.html.j2").render(
        a=article, neighbors=neighbors, active=None, root="../")
```

> `article`은 이미 `_decorate`된 행을 받는다(`write_site`가 그렇게 넘김). 테스트는 `_decorated()`로 동일하게 전처리.

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: PASS (자산 1 + 인덱스 5 + 상세 3 = 9 passed).

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/serve/templates/detail.html.j2 src/bullet_in/serve/render.py tests/test_serve_render.py
git commit -m "feat(serve): 상세 페이지 render_article(3줄요약·본문·출처·이웃 5목록 윈도우)"
```

---

## Task 5: `write_site` 사이트 생성 + `run.py` 배선

`index.html` + `article/<content_hash>.html` N개 + 정적 자산 복사를 한 번에 생성하고, `run.py`의 SELECT/호출부를 교체한다. 기존 `render_page`/`write_page`와 `tests/test_render.py` 제거.

**Files:**
- Modify: `src/bullet_in/serve/render.py`
- Modify: `src/bullet_in/run.py:55-59`
- Delete: `tests/test_render.py`
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: Task 3·4 렌더 함수.
- Produces: `write_site(articles: list[dict], sources: dict, out_dir: str | Path, now: datetime | None = None) -> None`.

- [ ] **Step 1: `write_site` 실패 테스트 작성**

`tests/test_serve_render.py`에 추가:

```python
from bullet_in.serve.render import write_site

def test_write_site_creates_index_articles_and_assets(tmp_path):
    arts = [_row(content_hash=f"h{i}", title_ko=f"기사{i}",
                 published_at=datetime(2026, 6, 29, 12 - i, 0)) for i in range(3)]
    write_site(arts, SOURCES, tmp_path, now=NOW)
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "style.css").exists()
    assert (tmp_path / "app.js").exists()
    for i in range(3):
        assert (tmp_path / "article" / f"h{i}.html").exists()
    # 상세에서 정적 자산은 ../ 로 참조
    detail = (tmp_path / "article" / "h0.html").read_text(encoding="utf-8")
    assert 'href="../style.css"' in detail and 'src="../app.js"' in detail
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="style.css"' in index
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py::test_write_site_creates_index_articles_and_assets -q`
Expected: FAIL — `cannot import name 'write_site'`.

- [ ] **Step 3: `write_site` 구현 + 구식 함수 제거**

`render.py`에서 기존 `render_page`/`write_page`를 삭제하고 추가:

```python
import shutil


def write_site(articles: list[dict], sources: dict, out_dir: str | Path,
               now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    out = Path(out_dir)
    (out / "article").mkdir(parents=True, exist_ok=True)

    (out / "index.html").write_text(render_index(articles, sources, now),
                                    encoding="utf-8")

    ordered = _sorted_latest(articles)
    for idx, row in enumerate(ordered):
        a = _decorate(row, sources, now)
        neighbors = build_neighbors(ordered, idx, sources, now)
        html = render_article(a, neighbors, row["content_hash"], sources, now)
        (out / "article" / f"{row['content_hash']}.html").write_text(
            html, encoding="utf-8")

    for asset in ("style.css", "app.js"):
        shutil.copyfile(_STATIC_DIR / asset, out / asset)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: PASS (10 passed).

- [ ] **Step 5: `tests/test_render.py` 삭제 + 전체 테스트**

```bash
git rm tests/test_render.py
uv run pytest -q
```
Expected: 전체 PASS(통합 테스트는 DB 없으면 skip). `render_page` 참조 잔존 없음.

- [ ] **Step 6: `run.py` SELECT·호출부 교체**

`src/bullet_in/run.py:16` import 교체:

```python
from bullet_in.serve.render import write_site
```

`run.py:55-59`(SELECT + write_page)을 교체:

```python
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(
            "SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,"
            "summary3_ko,body_ko,image_url,outlet,journalist,team,tier,"
            "confidence_score,published_at "
            "FROM articles")).mappings().all()]
    write_site(rows, sources, "site")
```

> `sources`는 `run.py:23`에서 이미 `load_sources(...)`로 로드되어 있다(추가 로드 불필요).

- [ ] **Step 7: import·컴파일 확인 + 커밋**

Run: `uv run python -c "import bullet_in.run"`
Expected: 에러 없음.

```bash
git add src/bullet_in/serve/render.py src/bullet_in/run.py tests/test_serve_render.py
git commit -m "feat(serve): write_site(인덱스+상세 N개+자산 복사)·run.py SELECT/배선 교체"
```

---

## Task 6: 라이브 렌더 스모크 + 브라우저 수동 검증

실제 데이터/픽스처로 사이트를 생성해 바닐라 JS(검색·필터·정렬·테마)와 레이아웃을 브라우저에서 확인한다. 단위 테스트(모킹)는 JS 동작·시각 레이아웃을 못 잡으므로 필수.

**Files:**
- 없음(검증 전용). 필요 시 픽스처 스크립트는 scratchpad에만 둔다.

- [ ] **Step 1: 픽스처로 사이트 생성**

scratchpad에 임시 스크립트를 만들어 다양한 케이스(이미지 유/무, outlet NULL=EN 직접 소스, journalist 유/무, summary3 3줄, body 다문단, tier 0~4, 기사 10건+)를 가진 행으로 `write_site(..., "site")` 실행. 예:

```bash
uv run python - <<'PY'
from datetime import datetime, timedelta
from bullet_in.serve.render import write_site
now = datetime.utcnow()
sources = {"bbc_sport": {"display_name": "BBC Sport"},
           "arsenal_official": {"display_name": "Arsenal.com"}}
rows = []
for i in range(10):
    rows.append(dict(
        content_hash=f"hash{i}", url="https://example.com/a%d" % i,
        source_id="bbc_sport" if i % 2 else "arsenal_official",
        title_original="Arsenal sign player %d" % i,
        title_ko="아스날, 선수 %d 영입 임박" % i,
        summary_ko="한 줄 요약 %d" % i,
        summary3_ko="첫째 줄 %d\n둘째 줄\n셋째 줄" % i,
        body_ko="첫 문단 본문입니다.\n둘째 문단 본문입니다.\n셋째 문단.",
        image_url=None if i % 3 == 0 else "https://picsum.photos/seed/%d/800/450" % i,
        outlet=None if i % 2 else "Arsenal Official",
        journalist="기자 %d" % i if i % 4 == 0 else None,
        team="arsenal", tier=i % 5, confidence_score=round(1 - (i % 5) / 4, 3),
        published_at=now - timedelta(hours=i)))
write_site(rows, sources, "site", now=now)
print("wrote site/")
PY
ls -R site | head -40
```

- [ ] **Step 2: 브라우저에서 확인(수동 체크리스트)**

`site/index.html`을 브라우저로 연다(예: `open site/index.html`). 다음을 모두 확인:
- [ ] 카드 그리드 표시 · 이미지 있는 카드는 썸네일, 없는 카드는 플레이스홀더.
- [ ] 칩: team(아스날) · outlet(폴백 동작: EN 직접 소스도 표시) · tier. 시간 "N시간 전".
- [ ] 검색창 입력 시 카드 실시간 필터(제목·요약 부분일치).
- [ ] 사이드바 소스/티어 체크 → `필터 적용` 시 반영, `초기화` 시 Arsenal만 체크·검색어 비움·전체 표시.
- [ ] 정렬 라디오 최신순/신뢰도순 전환 시 카드 순서 변경(적용 시).
- [ ] 영입 단계 그룹은 비활성(흐리게)·`예정` 배지. 타 구단도 비활성.
- [ ] 테마 토글 → 다크/라이트 전환, 새로고침·페이지 이동 후에도 유지.
- [ ] 카드 클릭 → `article/<hash>.html` 이동. 상세: 히어로/플레이스홀더 · 3줄 요약 박스 · 다문단 본문 · 출처(outlet · journalist · 원문 링크 새 탭) · 하단 5목록(현재 글 `지금` 배지·중앙). 가장자리 글은 윈도우가 5개 유지.
- [ ] 상세에서 정적 자산(`../style.css`·`../app.js`) 정상 로드(스타일·테마 적용).

- [ ] **Step 3: 발견 이슈 수정**

수동 검증에서 발견된 시각/동작 결함은 해당 Task(템플릿=3·4, JS/CSS=2)로 돌아가 수정하고 재검증. 데이터 의존 결함(컬럼 누락 등)은 Task 5 SELECT 조정.

- [ ] **Step 4: 정리**

`site/`는 빌드 산출물 — `.gitignore`에 이미 포함됐는지 확인하고, 아니면 추가(커밋하지 않는다). scratchpad 픽스처는 커밋하지 않는다.

```bash
grep -q '^site/' .gitignore || printf 'site/\n' >> .gitignore
git add .gitignore && git commit -m "chore(serve): site/ 빌드 산출물 gitignore" || true
```

---

## Self-Review

**Spec §7 커버리지**
- §7.1 산출물 구조(index/article/style/app, 의존성 0, content_hash 파일명) → Task 5 `write_site`.
- §7.2 인덱스(썸네일+폴백, 칩 team·outlet·tier, 시간, 클릭 이동; 상단 로고·내비·검색·테마; 사이드바 팀·소스·tier·정렬·비활성 영입단계; data-* 속성) → Task 2·3, 레이아웃.
- §7.3 상세(히어로, 칩, 제목, 3줄 요약, 전체 본문, 출처) → Task 4.
- §7.4 하단 5목록 슬라이딩 윈도우(경계 4종) → Task 1 `neighbor_window` + Task 4 `build_neighbors`(테스트로 경계 고정).
- §7.5 `render.py`(index 유지·개편 + `write_article_pages` 대응=`write_site` 루프, Jinja `index.html.j2`/`detail.html.j2` 분리, CSS/JS 정적 복사) → Task 3·4·5.
- 사용자 주의(outlet NULL 폴백, image_url 폴백) → `outlet_display`/템플릿 조건(Task 1·3·4 테스트로 고정).
- §9 테스트(data-* 속성, 슬라이딩 윈도우 경계, content_hash 파일명, 라이브 검증) → Task 1·3·4·5·6.

**범위 밖(2-b) 확인**: 영입 단계 필터 기능·인라인 본문 이미지·소개/일정 콘텐츠·타 구단 데이터·의미 dedup은 이 계획에 없음(비활성 자리만). 의도된 제외.

**Placeholder 스캔**: 모든 코드 스텝에 실제 코드/명령/기대 출력 포함. TBD/“적절히 처리” 없음.

**타입 일관성**: `_decorate`가 채우는 파생 키(`_title`·`_outlet`·`_tier_label`·`_when`·`_date`·`_published_iso`)를 인덱스/상세 템플릿이 동일 이름으로 소비. `render_index`/`render_article`/`build_neighbors`/`write_site` 시그니처가 Task 간 일치. `neighbor_window`는 (start, end 배타) 일관.

---

## Execution Handoff

계획 완료 · `docs/superpowers/plans/2026-06-29-tier2a-serving-ui.md` 저장. 사용자 지시에 따라 **Subagent-Driven**(태스크별 신규 서브에이전트 + 태스크 간 2단계 리뷰)로 순차 실행 후 GitHub Flow + squash로 PR.
