# 전체 기사 · 선수 모아보기 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스펙 `docs/superpowers/specs/2026-07-26-serve-explore-pages-design.md` 의 두 화면 (전체 기사 평면 페이지 · 선수 색인 + 타임라인) 과 인덱스 더보기 UX 를 두 개의 PR 로 구현한다.

**Architecture:** 모든 변경은 정적 렌더 (`serve/render.py` + Jinja 템플릿 + `app.js`) 안에서 끝난다.
PR-1 이 카드 매크로를 공용화하고 평면 목록 · 주 단위 더보기를 만들며, PR-2 가 그 위에 귀속 헬퍼 · 선수 화면 · ops 미매칭을 얹는다.
DB · 수집 · enrich 는 건드리지 않는다.

**Tech Stack:** Python 3.11 · Jinja2 · vanilla JS · pytest.

## Global Constraints

- 테스트: `uv run pytest -q` 전체 통과가 각 Task 의 종료 조건 (기준선 581 passed · 1 skipped).
- TDD: 실패 테스트 먼저 (`tests/test_serve_render.py` · `test_serve_layout.py` 에 추가, `test_serve_*` 패턴).
- 커밋: `<type>(serve): 한국어 제목` + 본문 (도입 1–2문장 + 명사형 불릿) + 트레일러 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` (구현 모델이 다르면 역할 라벨 병기).
- git 신원: `benidjor <94089198+benidjor@users.noreply.github.com>`.
- 무수정 유지: `config/name_map.yaml` (읽기만) · `protagonist()` · `cluster_events()` · 사건 묶음 로직 · `config/sources.yaml`.
- 검증은 전부 로컬 (docker mariadb `bulletin` + 렌더 + 브라우저) — VM 미접촉.
- 렌더 재현 스크립트: 세션 scratchpad 의 `render_local.py` (로컬 DB 205행 → 사이트 생성) 재사용.
- PR 본문: 7섹션 + 템플릿 주석 세칙 (`**핵심어** — 설명` 라벨 · 이중 불릿 · 백틱) + humanize-korean fast 1회 · 머지는 사용자.

---

# Phase 1 — PR-1: 목록 개선 (브랜치 `feat/serve-list-improvements`, origin/main 에서 분기)

### Task 1: 카드 매크로 공용화 (`_cards.html.j2`)

**Files:**
- Create: `src/bullet_in/serve/templates/_cards.html.j2`
- Modify: `src/bullet_in/serve/templates/index.html.j2` (매크로 정의 3개 삭제 → import)

**Interfaces:**
- Produces: `_cards.html.j2` 의 `stage_badge(s)` · `card(a, dest, when, cls, show_cred, thumb, hidden)` · `relitem(a, rep)` — 이후 Task (all.html · player.html) 가 import 해서 쓴다.

- [ ] **Step 1: 순수 리팩터 — 매크로 이동**

`index.html.j2` 상단의 `{% macro stage_badge(...) %}` · `{% macro card(...) %}` · `{% macro relitem(...) %}` 세 정의를 그대로 잘라 `_cards.html.j2` 새 파일에 붙인다 (내용 무변경).
`index.html.j2` 의 `{% extends %}` 바로 아래에 추가:

```jinja
{% from "_cards.html.j2" import stage_badge, card, relitem %}
```

- [ ] **Step 2: 회귀 확인**

Run: `uv run pytest -q`
Expected: 581 passed (리팩터 전과 동일 — 신규 테스트 없음, 렌더 결과 불변).

- [ ] **Step 3: Commit**

```bash
git add src/bullet_in/serve/templates/_cards.html.j2 src/bullet_in/serve/templates/index.html.j2
git commit -m "refactor(serve): 카드 매크로를 _cards.html.j2 로 공용화 (all · player 페이지 준비)"
```

### Task 2: 전체 기사 페이지 (all.html)

**Files:**
- Create: `src/bullet_in/serve/templates/all.html.j2`
- Modify: `src/bullet_in/serve/render.py` (`render_all` 신설 · `write_site` 에 all.html 추가), `src/bullet_in/serve/templates/_layout.html.j2` (네비 · sortSel 조건)
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: `group_by_day(articles, now)` (기존 — `{"label","date","articles"}` 반환) · `_decorate` · `facet_counts` · Task 1 의 `card` 매크로.
- Produces: `render_all(articles, sources, now, directory=None, registry=None, outlet_dir=None) -> str`, `write_site` 산출물 `all.html`.

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_serve_render.py` 끝에 추가)

```python
# ── 전체 기사 페이지 (spec 2026-07-26 §3) ────────────────────────────

from bullet_in.serve.render import render_all


def test_all_page_flat_without_clusters():
    # 같은 주인공 2건도 묶지 않고 낱개 카드로 — relitem 이 없어야 한다
    a1 = _row(content_hash="f1", title_ko="아스날, 에제 영입 합의", tier=2,
              transfer_stage="agreed")
    a2 = _row(content_hash="f2", title_ko="아스날, 에제 이적 임박", tier=4,
              transfer_stage="rumour", source_id="bbc_sport")
    html = render_all([a1, a2], SOURCES, NOW)
    assert 'href="article/f1.html"' in html
    assert 'href="article/f2.html"' in html
    assert "relitem" not in html
    assert 'class="reltoggle"' not in html


def test_all_page_daygroup_carries_date_attr():
    html = render_all([_row()], SOURCES, NOW)
    assert 'data-date="2026-06-29"' in html


def test_all_page_nav_active_and_sidebar():
    html = render_all([_row()], SOURCES, NOW)
    assert 'href="all.html"' in html          # 네비 항목
    assert 'id="applyBtn"' in html            # 필터 사이드바 재사용


def test_index_nav_links_all_page():
    html = render_index([_row()], SOURCES, NOW)
    assert 'href="all.html"' in html
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k all_page`
Expected: FAIL — `ImportError: cannot import name 'render_all'`.

- [ ] **Step 3: 구현**

`render.py` — `render_index` 아래에 추가:

```python
def render_all(articles: list[dict], sources: dict, now: datetime,
               directory: dict | None = None, registry=None,
               outlet_dir: dict | None = None) -> str:
    """전체 기사 평면 페이지 — 사건 묶음 없이 날짜 그룹 + 시간순 낱개 카드 (spec §3)."""
    ordered = [_decorate(a, sources, now, directory=directory, outlet_dir=outlet_dir)
               for a in _sorted_latest(articles)]
    days = group_by_day(ordered, now)
    facets = facet_counts(articles, sources, directory=directory, registry=registry,
                          outlet_dir=outlet_dir)
    return _env().get_template("all.html.j2").render(
        days=days, facets=facets, active="all", root="")
```

`write_site` 의 `index.html` 라인 뒤에 추가:

```python
    (out / "all.html").write_text(
        render_all(articles, sources, now, directory=directory, registry=registry,
                   outlet_dir=outlet_dir),
        encoding="utf-8")
```

`templates/all.html.j2` 신설:

```jinja
{% extends "_layout.html.j2" %}
{% from "_cards.html.j2" import card %}
{% block title %}전체 기사 · Bullet-in{% endblock %}

{% block content %}
<div class="sechead"><h2>전체 기사</h2><span class="kst">시각 KST 기준 · 묶음 없이 시간순</span></div>
<div class="latest{{ ' latestcut' if days|length > 3 }}">
{% for day in days %}
<div class="daygroup{{ ' dg-extra' if loop.index > 3 }}" data-date="{{ day.date }}">
<div class="daydiv"><span class="d">{{ day.label }}</span><span class="c">보도 {{ day.articles|length }}건</span></div>
<div class="daylist">
  {% for a in day.articles %}
  <div class="block">{{ card(a, thumb=True) }}</div>
  {% endfor %}
</div>
</div>
{% endfor %}
</div>
{% if days|length > 3 %}<button class="latestmore" id="latestMore" type="button">이전 날짜 더보기 · {{ days|length - 3 }}개 날짜</button>{% endif %}
{% endblock %}
```

주의: `index.html.j2` 의 본문 블록 이름을 확인해 동일 블록 (`content` 가 아니면 그 이름) 을 쓴다.
카드를 `<div class="block">` 으로 감싸는 이유 — 기존 `app.js` 의 `sortBlocks` · `hideEmpty` 가 블록 단위로 동작하므로 필터 · 정렬이 무수정으로 이 페이지에서도 작동한다.

`_layout.html.j2` 네비 (홈 다음 줄):

```jinja
    <a class="{{ 'active' if active == 'all' else '' }}" href="{{ root }}all.html">전체 기사</a>
```

sortSel 조건 `{% if active == 'home' %}` → `{% if active in ('home', 'all') %}`.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest -q`
Expected: 기존 + 신규 4건 전체 통과.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/serve/ tests/test_serve_render.py
git commit -m "feat(serve): 전체 기사 평면 페이지 (all.html) — 묶음 없이 시간순 · 필터 사이드바 재사용"
```

### Task 3: 주 단위 더보기 · 접기 (인덱스 + 전체 기사)

**Files:**
- Modify: `src/bullet_in/serve/templates/index.html.j2` (daygroup 에 data-date), `src/bullet_in/serve/static/app.js` (`expandLatest` 블록 교체), `src/bullet_in/serve/static/style.css` (`.wcut` 규칙)
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: `group_blocks_by_day` 가 반환하는 `day.date` (기존).
- Produces: `.daygroup[data-date]` DOM 계약 (Task 4 의 가십 로직과 같은 `wcut` 클래스 방식).

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_index_daygroup_carries_date_attr():
    # 주 단위 더보기 (spec §4) 의 JS 계약 — 날짜 그룹이 data-date 를 가진다
    html = render_index([_row()], SOURCES, NOW)
    assert 'class="daygroup' in html
    assert 'data-date="2026-06-29"' in html
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k daygroup_carries`
Expected: FAIL (`data-date` 부재).

- [ ] **Step 3: 렌더 구현**

`index.html.j2` 의 daygroup 여는 태그를 다음으로 교체:

```jinja
<div class="daygroup{{ ' dg-extra' if loop.index > 3 }}" data-date="{{ day.date }}">
```

- [ ] **Step 4: app.js — 주 단위 로직으로 교체**

기존 `── 최신 소식 주 단위 더보기` 블록 (`latestWrap` · `expandLatest` · `latestMore.onclick`) 을 다음으로 교체:

```js
// ── 최신 소식 · 전체 기사 — 주 단위 더보기 · 접기 (spec §4) ─────────
const latestWrap = document.querySelector('.latest');
const latestMore = document.getElementById('latestMore');
const dayGroups = latestWrap ? [...latestWrap.querySelectorAll('.daygroup')] : [];
const LATEST_INIT = 3;
function latestHiddenCount() {
  if (latestWrap?.classList.contains('latestcut'))
    return dayGroups.filter(g => g.classList.contains('dg-extra')).length;
  return dayGroups.filter(g => g.classList.contains('wcut')).length;
}
function latestSync() {
  if (!latestMore) return;
  const n = latestHiddenCount();
  latestMore.textContent = n
    ? (latestWrap.classList.contains('latestcut')
        ? `이전 날짜 더보기 · ${n}개 날짜` : `이전 7일 더보기 · ${n}개 날짜`)
    : '접기';
}
function latestReveal() {
  const vis = dayGroups.filter(g => !g.classList.contains('wcut')
    && !(latestWrap.classList.contains('latestcut') && g.classList.contains('dg-extra')));
  const oldest = new Date(vis[vis.length - 1].dataset.date);
  oldest.setDate(oldest.getDate() - 7);                    // 7일 창 확장
  if (latestWrap.classList.contains('latestcut')) {
    latestWrap.classList.remove('latestcut');
    dayGroups.forEach((g, i) => { if (i >= LATEST_INIT) g.classList.add('wcut'); });
  }
  dayGroups.forEach(g => { if (new Date(g.dataset.date) >= oldest) g.classList.remove('wcut'); });
  latestSync();
}
function latestCollapse() {
  dayGroups.forEach(g => g.classList.remove('wcut'));
  latestWrap.classList.add('latestcut');
  latestSync();
  latestWrap.previousElementSibling?.scrollIntoView();     // 구역 상단 (sechead) 보정
}
function expandLatest() {                                  // 필터 활성 시 전체 전개 (기존 계약)
  latestWrap?.classList.remove('latestcut');
  dayGroups.forEach(g => g.classList.remove('wcut'));
  if (latestMore) latestMore.hidden = true;
}
if (latestMore) latestMore.onclick = () =>
  latestHiddenCount() ? latestReveal() : latestCollapse();
if (latestMore) latestSync();
```

`style.css` — `.latest.latestcut` 규칙 아래에 추가:

```css
.daygroup.wcut{display:none}                     /* 주 단위 더보기 — JS 가 관리 */
```

- [ ] **Step 5: 통과 · 회귀 확인**

Run: `uv run pytest -q`
Expected: 전체 통과 (JS 는 pytest 대상 아님 — Task 5 의 브라우저 검증으로 확인).

- [ ] **Step 6: Commit**

```bash
git add src/bullet_in/serve/
git commit -m "feat(serve): 이전 날짜 더보기를 주 단위 펼침 · 접기로 (인덱스 · 전체 기사 공용)"
```

### Task 4: 가십 — 2열 배치 · 주 단위 더보기

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`render_index` 가십 블록), `src/bullet_in/serve/templates/index.html.j2` (가십 루프), `src/bullet_in/serve/static/app.js` (가십 블록 교체), `src/bullet_in/serve/static/style.css`
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: `_sort_ts` · 가십 목록 (Task 이전과 동일 구조 · `_dup` 포함).
- Produces: 가십 카드의 `gwk` 클래스 (최신 가십 기준 7일 밖) · 목록의 `weekcut` 초기 클래스 — 기존 `gx`/`morecut` (개수 컷) 대체.

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_gossip_older_than_week_marked_gwk():
    # 가십 초기 노출 = 최신 가십 기준 최근 7일 (spec §4 — 24건 개수 컷 대체)
    recent = _row(content_hash="g1", source_id="bbc_gossip", tier=4,
                  title_ko="아스날, 촐리스 루머",
                  published_at=datetime(2026, 6, 29, 10, 0))
    old = _row(content_hash="g2", source_id="bbc_gossip", tier=4,
               title_ko="아스날, 진첸코 루머",
               published_at=datetime(2026, 6, 20, 10, 0))
    html = render_index([recent, old], {**SOURCES, "bbc_gossip":
        {"display_name": "BBC Football Gossip", "serving": "full"}}, NOW)
    i_old = html.index('href="article/g2.html"')
    seg_old = html[max(0, i_old - 400):i_old]
    assert "gwk" in seg_old                    # 7일 밖 → 초기 숨김 표식
    i_new = html.index('href="article/g1.html"')
    seg_new = html[max(0, i_new - 400):i_new]
    assert "gwk" not in seg_new
    assert "weekcut" in html                   # 숨길 것이 있으면 목록에 초기 컷
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k gwk`
Expected: FAIL (`gwk` 미출력).

- [ ] **Step 3: 렌더 구현**

`render_index` 의 가십 정렬 (`gossip.sort(...)`) 뒤에 추가:

```python
    if gossip:
        newest = _sort_ts(gossip[0])[0]
        cut = newest - timedelta(days=7)
        for g in gossip:
            g["_gwk"] = _sort_ts(g)[0] < cut   # 최신 가십 기준 7일 밖 → 초기 숨김
    gossip_hidden = sum(1 for g in gossip if g.get("_gwk") and not g.get("_dup"))
```

`render_index` 의 반환 `render(...)` 호출에 `gossip_hidden=gossip_hidden` 추가.

`index.html.j2` 가십 구간 교체 — 목록 클래스 · 카드 cls · 버튼:

```jinja
<div class="gossiplist{{ ' weekcut' if gossip_hidden }}">
  {% for a in gossip %}{{ card(a, when=a._gwhen, cls='dupcard' if a._dup else ('gwk' if a._gwk else ''), hidden=a._dup, show_cred=False) }}{% endfor %}
</div>
{% if gossip_hidden %}<button class="gossipmore" id="gossipMore" type="button">이전 날짜 가십 더보기 · {{ gossip_hidden }}건</button>{% endif %}
```

기존 `morecut` · `gx` · 24건 관련 조각 (`ns.vis` 카운터 포함) 은 삭제한다 — 개수 컷이 날짜 컷으로 대체됐다.

`style.css`:

```css
.gossiplist{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 28px;align-items:start}
.gossiplist.weekcut .item.gwk{display:none}       /* 초기 7일 컷 (서버 표식) */
.gossiplist .item.wcut{display:none}              /* 주 단위 더보기 — JS 관리 */
```

기존 `.gossiplist.morecut .item.gx` 규칙은 삭제.
데스크톱 3열 → 2열이므로 기존 미디어쿼리의 2열 규칙 (317행) 과 중복되면 정리한다.

- [ ] **Step 4: app.js — 가십 주 단위 로직**

기존 `── 가십 더보기` 블록 (`expandGossip` · `gossipMore.onclick`) 을 교체:

```js
// ── 가십 — 주 단위 더보기 · 접기 (초기 = 최근 7일, 서버 gwk 표식) ────
const gossipList = document.querySelector('.gossiplist');
const gossipMore = document.getElementById('gossipMore');
const gossipCards = gossipList ? [...gossipList.querySelectorAll('.item:not(.dupcard)')] : [];
function gossipHiddenCount() {
  if (gossipList?.classList.contains('weekcut'))
    return gossipCards.filter(c => c.classList.contains('gwk')).length;
  return gossipCards.filter(c => c.classList.contains('wcut')).length;
}
function gossipSync() {
  if (!gossipMore) return;
  const n = gossipHiddenCount();
  gossipMore.textContent = n ? `이전 날짜 가십 더보기 · ${n}건` : '접기';
}
function gossipReveal() {
  const vis = gossipCards.filter(c => !c.classList.contains('wcut')
    && !(gossipList.classList.contains('weekcut') && c.classList.contains('gwk')));
  const oldest = new Date(vis[vis.length - 1].dataset.published);
  oldest.setDate(oldest.getDate() - 7);
  if (gossipList.classList.contains('weekcut')) {
    gossipList.classList.remove('weekcut');
    gossipCards.forEach(c => { if (c.classList.contains('gwk')) c.classList.add('wcut'); });
  }
  gossipCards.forEach(c => {
    if (new Date(c.dataset.published) >= oldest) c.classList.remove('wcut');
  });
  gossipSync();
}
function gossipCollapse() {
  gossipCards.forEach(c => c.classList.remove('wcut'));
  gossipList.classList.add('weekcut');
  gossipSync();
  document.querySelector('.gossiphead')?.scrollIntoView();
}
function expandGossip() {                        // 필터 활성 시 전체 전개 (기존 계약)
  gossipList?.classList.remove('weekcut');
  gossipCards.forEach(c => c.classList.remove('wcut'));
  if (gossipMore) gossipMore.hidden = true;
}
if (gossipMore) gossipMore.onclick = () =>
  gossipHiddenCount() ? gossipReveal() : gossipCollapse();
if (gossipMore) gossipSync();
```

주의: `expandGossip` · `expandLatest` 는 `applyFilters` 초입에서 호출되는 기존 계약 (#133) 을 그대로 유지한다 — 필터가 걸리면 컷 전부 해제.
`dupcard` 는 인라인 `display:none` (별개 메커니즘) 이라 컷 클래스와 간섭하지 않는다.

- [ ] **Step 5: 통과 · 회귀 확인**

Run: `uv run pytest -q`
Expected: 전체 통과.
가십 24건 컷 관련 기존 테스트가 있으면 (검색: `grep -rn 'gx\|morecut' tests/`) 날짜 컷 계약으로 갱신한다.

- [ ] **Step 6: Commit**

```bash
git add src/bullet_in/serve/ tests/
git commit -m "feat(serve): 가십을 2열 배치 · 주 단위 더보기로 (24건 개수 컷 대체)"
```

### Task 5: PR-1 검증 · PR 생성

**Files:**
- 없음 (검증 · 문서만).

- [ ] **Step 1: 전체 테스트 + 로컬 렌더**

```bash
uv run pytest -q
uv run python <scratchpad>/render_local.py    # 로컬 DB → 사이트 재생성
```

- [ ] **Step 2: 브라우저 체크리스트** (localhost 정적 서버)

- 인덱스: 초기 3일 그룹 → 더보기 = 7일씩 추가 (라벨 갱신) → 전부 펼치면 "접기" → 접기 = 초기 복귀 + 스크롤 보정.
- 가십: 2열 · 초기 최근 7일 → 더보기 7일씩 → 접기.
- 전체 기사: 낱개 카드 · 관련 보도 없음 · 필터 (소스 · 단계 · 검색어) 동작 · 정렬 셀렉트 동작 · 주 단위 더보기.
- 필터 적용 시 컷 자동 전개 (#133 계약) · 초기화 후 상태.
- 라이트 · 다크 전환.

- [ ] **Step 3: PR 생성**

PR 본문 7섹션 작성 → humanize-korean fast 1회 → `gh pr create --base main --body-file ...`.
제목: `feat(serve): 전체 기사 페이지 · 주 단위 더보기 · 가십 2열`.
머지는 사용자 — 머지 후 Phase 2 착수.

---

# Phase 2 — PR-2: 선수 트랙 (브랜치 `feat/serve-player-pages`, PR-1 머지 후 origin/main 에서 분기)

### Task 6: 귀속 · 단계 · 집계 헬퍼 (TDD)

**Files:**
- Modify: `src/bullet_in/serve/render.py`
- Test: `tests/test_serve_layout.py`

**Interfaces:**
- Consumes: `load_player_names()` · `filter_stage(row)` · `_sort_ts` · `display_stage` (기존).
- Produces (이후 Task 가 그대로 사용):
  - `load_player_map(path="config/name_map.yaml") -> dict[str, str]` — 한글 정규형 → 영문 성.
  - `attribution_players(row, sources, players) -> list[str]` — 소스별 하이브리드 귀속 (spec §7.2).
  - `player_slug(name, surname, taken: set[str]) -> str` — 소문자 영문 성, 충돌 시 한글키 해시 4자 접미.
  - `player_stats(articles, sources) -> list[dict]` — 선수별 `{"name","slug","articles"(최신순),"count","stage","stage_rank","last_ts"}`, 정렬 완료 (이적 후보 = 단계 순위 → 기사 수 → 최근, 스쿼드 = 기사 수순, `"squad": bool` 필드로 구분).

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_serve_layout.py` 끝에 추가)

```python
# ── 선수 귀속 · 집계 (spec 2026-07-26 §7) ───────────────────────────

from datetime import datetime
from bullet_in.serve.render import attribution_players, player_slug, player_stats

X_SRC = {"x_afcstuff": {"display_name": "afcstuff", "credibility": "x_mentions"}}
NEWS_SRC = {"skysports": {"display_name": "Sky Sports", "outlet": "Sky Sports"}}
PLAYERS = ["기마랑이스", "에제", "콘사"]


def test_attribution_news_source_title_only():
    # 언론사 기사는 제목 기준 — 본문에만 나온 선수는 미귀속 (spec §7.2)
    row = {"source_id": "skysports", "title_ko": "아스날, 에제 영입 합의",
           "summary_ko": "콘사 언급", "body_ko": "본문에 기마랑이스와 콘사가 나온다"}
    assert attribution_players(row, NEWS_SRC, PLAYERS) == ["에제"]


def test_attribution_x_source_scans_full_text():
    # X (x_mentions) 는 전문 대조 — 제목이 만들어낸 축약이라 (spec §7.2)
    row = {"source_id": "x_afcstuff", "title_ko": "아스날, 에제 영입 논의",
           "summary_ko": "", "body_ko": "본문에 기마랑이스 · 콘사 영입 협상도 언급"}
    assert set(attribution_players(row, X_SRC, PLAYERS)) == {"에제", "기마랑이스", "콘사"}


def test_player_slug_collision_gets_suffix():
    taken = {"eze"}
    s = player_slug("에제2", "Eze", taken)
    assert s != "eze" and s.startswith("eze-")


def _art(h, title, stage, ts, src="skysports", body=""):
    return {"content_hash": h, "source_id": src, "title_ko": title,
            "summary_ko": "", "body_ko": body, "transfer_stage": stage,
            "published_at": ts, "published_precision": "time", "fetched_at": ts}


def test_player_stats_solo_article_sets_stage():
    # 귀속 1명 기사만 단계 확정 (spec §7.3)
    solo = _art("s1", "아스날, 에제 영입 합의", "agreed", datetime(2026, 7, 20, 9, 0))
    multi = _art("s2", "아스날, 에제 · 콘사 동반 관심", "interest",
                 datetime(2026, 7, 21, 9, 0))
    stats = {s["name"]: s for s in player_stats([solo, multi], NEWS_SRC)}
    assert stats["에제"]["stage"] == "agreed"      # 라운드업 (multi) 은 단계에 미반영
    assert stats["에제"]["count"] == 2             # 기사 수에는 반영
    assert stats["콘사"]["stage"] is None          # 단독 기사 없음 → 확정 단계 없음
    assert stats["콘사"]["squad"] is True


def test_player_stats_sorted_stage_then_count():
    # A안 정렬: 단계 순위 → 기사 수 → 최근 보도일 (spec §5)
    agreed = _art("a1", "아스날, 에제 영입 합의", "agreed", datetime(2026, 7, 19, 9, 0))
    rumour1 = _art("r1", "아스날, 콘사 루머", "rumour", datetime(2026, 7, 21, 9, 0))
    rumour2 = _art("r2", "아스날, 콘사 이적설", "rumour", datetime(2026, 7, 20, 9, 0))
    order = [s["name"] for s in player_stats([agreed, rumour1, rumour2], NEWS_SRC)
             if not s["squad"]]
    assert order == ["에제", "콘사"]               # 합의 (건수 1) 가 루머 (건수 2) 보다 위
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_layout.py -q -k 'attribution or player_'`
Expected: FAIL — ImportError.

- [ ] **Step 3: 구현** (`render.py` — `load_player_names` 아래에)

```python
def load_player_map(path: str = "config/name_map.yaml") -> dict[str, str]:
    """선수 사전 전체 — 한글 정규형 → 영문 성 (slug 원료)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return dict((data.get("names") or {}).items())


def attribution_players(row: dict, sources: dict, players: list[str]) -> list[str]:
    """선수 페이지 귀속 (spec §7.2) — X 는 전문, 그 외는 제목 대조.
    사건 묶음의 protagonist 와 별개 규칙 (그쪽은 무수정)."""
    src = sources.get(row.get("source_id"), {})
    if src.get("credibility") == "x_mentions":
        text = " ".join(filter(None, [row.get("title_ko"), row.get("summary_ko"),
                                      row.get("body_ko")]))
    else:
        text = row.get("title_ko") or ""
    return [p for p in players if p in text]


def player_slug(name: str, surname: str, taken: set) -> str:
    """소문자 영문 성 slug. 충돌 시 한글키 해시 4자 접미 (렌더 경고는 호출부)."""
    base = re.sub(r"[^a-z0-9]", "", (surname or "").lower()) or "player"
    if base not in taken:
        return base
    import hashlib
    return f"{base}-{hashlib.sha256(name.encode()).hexdigest()[:4]}"


# 단계 순위 (spec §5) — 낮을수록 상위. medical 은 협상 중 표시 그룹과 동급.
_STAGE_RANK = {"official": 0, "agreed": 1, "medical": 2, "negotiating": 2,
               "personal_terms": 3, "interest": 4, "rumour": 5}


def player_stats(articles: list[dict], sources: dict) -> list[dict]:
    """선수별 귀속 기사 · 확정 단계 · 정렬 (spec §5 · §7). 기사 0건 선수는 제외."""
    name_map = load_player_map()
    players = sorted(name_map.keys(), key=len, reverse=True)
    acc: dict[str, dict] = {}
    for a in _sorted_latest(articles):               # 최신순 순회 → articles 최신순 적재
        names = attribution_players(a, sources, players)
        for n in names:
            e = acc.setdefault(n, {"name": n, "articles": [], "stage": None,
                                   "stage_ts": None})
        for n in names:
            acc[n]["articles"].append(a)
        if len(names) == 1:                          # 단독 귀속만 단계 확정 (spec §7.3)
            st = filter_stage(a)
            e = acc[names[0]]
            ts = _sort_ts(a)[0]
            if st in _STAGE_RANK and (e["stage_ts"] is None or ts > e["stage_ts"]):
                e["stage"], e["stage_ts"] = st, ts
    taken: set = set()
    out = []
    for n, e in acc.items():
        slug = player_slug(n, name_map.get(n, ""), taken)
        if "-" in slug and slug not in taken:
            log.warning("선수 slug 충돌 — 해시 접미 적용: %s → %s", n, slug)
        taken.add(slug)
        e.update(slug=slug, count=len(e["articles"]),
                 last_ts=_sort_ts(e["articles"][0])[0],
                 stage_rank=_STAGE_RANK.get(e["stage"], 99),
                 squad=e["stage"] is None)
        out.append(e)
    transfer = sorted([e for e in out if not e["squad"]],
                      key=lambda e: (e["stage_rank"], -e["count"], e["last_ts"]),
                      reverse=False)
    transfer.sort(key=lambda e: (e["stage_rank"], -e["count"]))
    squad = sorted([e for e in out if e["squad"]], key=lambda e: -e["count"])
    return transfer + squad
```

정렬 보조 설명: `transfer` 는 단계 순위 오름차순 → 기사 수 내림차순 → 최근 보도일 내림차순.
튜플 한 번으로 쓰려면 `key=lambda e: (e["stage_rank"], -e["count"], -e["last_ts"].timestamp())`.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest -q`
Expected: 전체 통과.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_layout.py
git commit -m "feat(serve): 선수 귀속 · 단계 확정 · 집계 헬퍼 (소스별 하이브리드 · 보수 단계 규칙)"
```

### Task 7: 선수 색인 (players.html)

**Files:**
- Create: `src/bullet_in/serve/templates/players.html.j2`
- Modify: `src/bullet_in/serve/render.py` (`render_players`) · `src/bullet_in/serve/templates/_layout.html.j2` (네비 '선수' · solo 변수) · `src/bullet_in/serve/static/style.css` (색인 카드)
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: Task 6 의 `player_stats` · `display_stage` · `fmt_date`.
- Produces: `render_players(articles, sources, now) -> str`, 링크 계약 `player/<slug>.html`.

- [ ] **Step 1: 실패 테스트 작성**

```python
# ── 선수 색인 (spec §5) ─────────────────────────────────────────────

from bullet_in.serve.render import render_players


def test_players_index_orders_by_stage_then_count():
    agreed = _row(content_hash="p1", title_ko="아스날, 에제 영입 합의",
                  transfer_stage="agreed")
    rumour = _row(content_hash="p2", title_ko="아스날, 콘사 루머",
                  transfer_stage="rumour")
    html = render_players([agreed, rumour], SOURCES, NOW)
    assert html.index("에제") < html.index("콘사")
    assert 'href="player/eze.html"' in html
    assert "이적 후보" in html and "스쿼드 · 기타" in html
```

주의: `_row` 의 기본 source 는 `bbc_sport` (언론사 → 제목 귀속) 이므로 제목에 사전 정규형 (에제 · 콘사) 이 그대로 있어야 귀속된다.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k players_index`
Expected: FAIL — ImportError.

- [ ] **Step 3: 구현**

`render.py`:

```python
def render_players(articles: list[dict], sources: dict, now: datetime) -> str:
    stats = player_stats(articles, sources)
    for e in stats:
        e["_badge"] = display_stage(e["stage"])
        e["_last"] = fmt_date(to_kst(e["last_ts"]))
    return _env().get_template("players.html.j2").render(
        stats=stats, active="players", root="", solo=True)
```

`templates/players.html.j2`:

```jinja
{% extends "_layout.html.j2" %}
{% block title %}선수 · Bullet-in{% endblock %}
{% block content %}
<div class="sechead"><h2>선수</h2><span class="kst">단계 · 보도량 기준 정렬</span></div>
<div class="playerlist">
  <h3 class="plgroup">이적 후보</h3>
  {% for e in stats if not e.squad %}
  <a class="pcard" href="player/{{ e.slug }}.html">
    <span class="pname">{{ e.name }}</span>
    {% if e._badge %}<span class="stage {{ e._badge.tone }}{{ ' filled' if e._badge.filled }}">{{ e._badge.label }}</span>{% endif %}
    <span class="pmeta">기사 {{ e.count }}건 · 최근 {{ e._last }}</span>
  </a>
  {% endfor %}
  <h3 class="plgroup">스쿼드 · 기타</h3>
  {% for e in stats if e.squad %}
  <a class="pcard" href="player/{{ e.slug }}.html">
    <span class="pname">{{ e.name }}</span>
    <span class="pmeta">기사 {{ e.count }}건 · 최근 {{ e._last }}</span>
  </a>
  {% endfor %}
</div>
{% endblock %}
```

`_layout.html.j2`:
- 네비에 `<a class="{{ 'active' if active == 'players' else '' }}" href="{{ root }}players.html">선수</a>` 추가 (전체 기사 다음).
- 사이드바 조건 `{% if not about_page %}` → `{% if not about_page and not solo %}`, shell 클래스 `{{ ' solo' if about_page or solo }}` (선수 화면은 필터 사이드바 없음 — 전역 facet 건수와 선수 부분집합이 어긋나는 혼동 방지).

`style.css` (블록 규칙 근처에 추가):

```css
.playerlist{max-width:760px}
.plgroup{margin:22px 0 6px;font-size:12px;letter-spacing:.08em;color:var(--dim)}
.pcard{display:flex;gap:10px;align-items:center;padding:10px 4px;border-bottom:1px solid var(--hair)}
.pcard .pname{font-family:var(--serif);font-weight:700;font-size:16px}
.pcard .pmeta{margin-left:auto;font-size:12px;color:var(--dim);font-variant-numeric:tabular-nums}
.pcard:hover .pname{color:var(--red)}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest -q`

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/serve/ tests/test_serve_render.py
git commit -m "feat(serve): 선수 색인 페이지 — A안 정렬 (단계 > 기사 수 > 최근) · 스쿼드 그룹 분리"
```

### Task 8: 선수 페이지 (타임라인 + 기사 목록) · write_site 통합

**Files:**
- Create: `src/bullet_in/serve/templates/player.html.j2`
- Modify: `src/bullet_in/serve/render.py` (`render_player` · `write_site` 생성 · 고아 정리) · `src/bullet_in/serve/static/style.css` (타임라인)
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: Task 6 `player_stats` · Task 1 `card` 매크로 · `_decorate`.
- Produces: `render_player(entry, sources, now, ...) -> str`, `write_site` 산출물 `players.html` · `player/<slug>.html`.

- [ ] **Step 1: 실패 테스트 작성**

```python
# ── 선수 페이지 (spec §6) ───────────────────────────────────────────

from bullet_in.serve.render import render_player, player_stats


def test_player_page_timeline_newest_first():
    old = _row(content_hash="t1", title_ko="아스날, 에제 관심",
               transfer_stage="interest", published_at=datetime(2026, 6, 27, 10, 0))
    new = _row(content_hash="t2", title_ko="아스날, 에제 영입 합의",
               transfer_stage="agreed", published_at=datetime(2026, 6, 29, 10, 0))
    entry = player_stats([old, new], SOURCES)[0]
    html = render_player(entry, SOURCES, NOW)
    assert html.index("t2.html") < html.index("t1.html")   # 타임라인 최신 먼저
    assert "이적 합의" in html and "관심" in html            # 노드 단계 배지
    assert 'class="tlnode"' in html


def test_write_site_emits_player_pages(tmp_path):
    rows = [_row(content_hash="w1", title_ko="아스날, 에제 영입 합의",
                 transfer_stage="agreed")]
    write_site(rows, SOURCES, tmp_path)
    assert (tmp_path / "players.html").exists()
    assert (tmp_path / "player" / "eze.html").exists()


def test_write_site_sweeps_stale_player_pages(tmp_path):
    (tmp_path / "player").mkdir(parents=True)
    (tmp_path / "player" / "ghost.html").write_text("x", encoding="utf-8")
    write_site([_row(title_ko="아스날, 에제 영입 합의", transfer_stage="agreed")],
               SOURCES, tmp_path)
    assert not (tmp_path / "player" / "ghost.html").exists()
```

`write_site` import 는 파일 상단에 이미 있는지 확인 후 없으면 추가.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k player_page`
Expected: FAIL.

- [ ] **Step 3: 구현**

`render.py`:

```python
def render_player(entry: dict, sources: dict, now: datetime,
                  directory: dict | None = None,
                  outlet_dir: dict | None = None) -> str:
    """선수 페이지 — 머리 · 타임라인 (최신순) · 평면 기사 목록 (spec §6)."""
    arts = [_decorate(a, sources, now, directory=directory, outlet_dir=outlet_dir)
            for a in entry["articles"]]                    # 이미 최신순 (Task 6)
    return _env().get_template("player.html.j2").render(
        e=entry, badge=display_stage(entry["stage"]), articles=arts,
        last=fmt_date(to_kst(entry["last_ts"])),
        active="players", root="../", solo=True)
```

`write_site` 에 (all.html 라인 뒤):

```python
    stats = player_stats(articles, sources)
    (out / "players.html").write_text(
        render_players(articles, sources, now), encoding="utf-8")
    (out / "player").mkdir(parents=True, exist_ok=True)
    keep = set()
    for e in stats:
        keep.add(f"{e['slug']}.html")
        (out / "player" / f"{e['slug']}.html").write_text(
            render_player(e, sources, now, directory=directory,
                          outlet_dir=outlet_dir),
            encoding="utf-8")
    for p in (out / "player").glob("*.html"):              # 사전 제외 선수 고아 정리
        if p.name not in keep:
            p.unlink()
```

`templates/player.html.j2`:

```jinja
{% extends "_layout.html.j2" %}
{% from "_cards.html.j2" import card %}
{% block title %}{{ e.name }} · Bullet-in{% endblock %}
{% block content %}
<div class="phead">
  <h2>{{ e.name }}</h2>
  {% if badge %}<span class="stage {{ badge.tone }}{{ ' filled' if badge.filled }}">{{ badge.label }}</span>{% endif %}
  <span class="pmeta">기사 {{ e.count }}건 · 최근 보도 {{ last }}</span>
</div>
<div class="timeline">
  {% for a in articles %}
  <div class="tlnode">
    <span class="tldate">{{ a._date }}</span>
    {% if a._stage_disp %}<span class="stage {{ a._stage_disp.tone }}{{ ' filled' if a._stage_disp.filled }}">{{ a._stage_disp.label }}</span>{% endif %}
    <a class="tltitle" href="{{ root }}article/{{ a.content_hash }}.html">{{ a._title }}</a>
    <span class="tlsrc">{{ a._outlet }}</span>
  </div>
  {% endfor %}
</div>
<div class="sechead"><h2>기사</h2></div>
<div class="daylist plist">
  {% for a in articles %}<div class="block">{{ card(a, thumb=True) }}</div>{% endfor %}
</div>
{% endblock %}
```

주의: `card` 매크로의 상세 링크는 `article/...` 상대 경로라 depth 1 (`player/`) 에서 깨진다.
`_cards.html.j2` 의 card · relitem href 를 `{{ root }}article/...` 로 바꾸고, 이 변수를 쓰는 기존 페이지 (index · all 은 `root=""`) 회귀를 전체 테스트로 확인한다.

`style.css`:

```css
.phead{display:flex;gap:12px;align-items:baseline;margin:18px 0 8px}
.phead h2{font-family:var(--serif);font-size:26px}
.phead .pmeta{margin-left:auto;font-size:12px;color:var(--dim)}
.timeline{border-left:2px solid var(--hair);margin:12px 0 26px;padding-left:14px}
.tlnode{display:flex;gap:10px;align-items:baseline;padding:7px 0;font-size:13px}
.tlnode .tldate{color:var(--dim);font-variant-numeric:tabular-nums;white-space:nowrap}
.tlnode .tltitle{flex:1;min-width:0}
.tlnode .tltitle:hover{color:var(--red)}
.tlnode .tlsrc{color:var(--dim);white-space:nowrap}
.plist{grid-template-columns:repeat(2,minmax(0,1fr));display:grid;gap:0 28px}
```

- [ ] **Step 4: 통과 · 회귀 확인**

Run: `uv run pytest -q`
Expected: 전체 통과 (root 경로 변경 회귀 포함).

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/serve/ tests/test_serve_render.py
git commit -m "feat(serve): 선수 페이지 — 단계 타임라인 (최신순) · 평면 기사 목록 · 고아 정리"
```

### Task 9: ops 미매칭 목록

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`unmatched_articles` · `write_ops` 인자) · `src/bullet_in/serve/templates/ops.html.j2` · `src/bullet_in/run.py` (호출부)
- Test: `tests/test_serve_ops.py`

**Interfaces:**
- Consumes: Task 6 `attribution_players` · `filter_stage` · `load_player_names`.
- Produces: `unmatched_articles(articles, sources) -> list[dict]` (`{"title","source","date"}` 최신순) · `write_ops(..., unmatched=None)`.

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_serve_ops.py` 의 기존 픽스처 스타일 확인 후 추가)

```python
from bullet_in.serve.render import unmatched_articles

def test_unmatched_requires_stage_and_no_player():
    src = {"skysports": {"display_name": "Sky Sports"}}
    hit = {"source_id": "skysports", "title_ko": "아스날, 스콧 영입 논의",
           "summary_ko": "", "body_ko": "", "transfer_stage": "interest",
           "published_at": datetime(2026, 7, 21, 9, 0),
           "published_precision": "time", "fetched_at": datetime(2026, 7, 21, 9, 0)}
    known = dict(hit, title_ko="아스날, 에제 영입 논의")   # 사전 선수 → 제외
    nostage = dict(hit, transfer_stage=None)              # 단계 없음 → 제외
    rows = unmatched_articles([hit, known, nostage], src)
    assert [r["title"] for r in rows] == ["아스날, 스콧 영입 논의"]
```

- [ ] **Step 2: 실패 확인 → 구현**

```python
def unmatched_articles(articles: list[dict], sources: dict) -> list[dict]:
    """영입 단계가 있는데 사전 귀속 0명인 기사 — name_map 확장 후보 (spec §8)."""
    players = load_player_names()
    out = []
    for a in _sorted_latest(articles):
        if filter_stage(a) not in _STAGE_RANK:
            continue
        if attribution_players(a, sources, players):
            continue
        ts = _sort_ts(a)[0]
        out.append({"title": a.get("title_ko") or a.get("title_original") or "",
                    "source": a.get("source_id") or "",
                    "date": fmt_date(to_kst(ts))})
    return out
```

`write_ops(snapshot, sources, out_dir, now=None, unmatched=None)` 로 인자 추가 → 템플릿에 `unmatched` 전달.
`ops.html.j2` 에 표 섹션 추가 (기존 표 스타일 재사용):

```jinja
<h3>선수 사전 미매칭 (영입 단계 있음 · 귀속 0명 — name_map 추가 후보)</h3>
<table><thead><tr><th>날짜</th><th>소스</th><th>제목</th></tr></thead><tbody>
{% for r in unmatched %}<tr><td>{{ r.date }}</td><td>{{ r.source }}</td><td>{{ r.title }}</td></tr>{% endfor %}
</tbody></table>
```

`run.py` 의 `write_ops(...)` 호출에 `unmatched=unmatched_articles(rows, sources)` 추가 (rows = SERVING_SELECT_SQL 결과 — 이미 그 위에서 조회함, 스코프 확인).

- [ ] **Step 3: 통과 확인 → Commit**

```bash
uv run pytest -q
git add src/bullet_in/serve/ src/bullet_in/run.py tests/test_serve_ops.py
git commit -m "feat(serve): ops 에 선수 사전 미매칭 기사 표 — name_map 확장 후보 발굴"
```

### Task 10: PR-2 검증 · PR 생성

- [ ] **Step 1: 전체 테스트 + 로컬 렌더 + 브라우저 체크리스트**

- 색인: 그룹 2개 · A안 정렬 근거가 카드에 보임 · 네비 '선수' 활성.
- 선수 페이지: 타임라인 최신순 · 단계 배지 · 기사 목록 · 상세 링크 (depth 1 경로) 동작.
- 실측 대조: 에제 · 기마랑이스 등 2~3명을 로컬 DB 로 직접 세어 카운트 일치 확인.
- ops: 미매칭 표에 스콧류 트윗 노출.
- 라이트 · 다크.

- [ ] **Step 2: PR 생성**

제목: `feat(serve): 선수 색인 · 선수 페이지 (단계 타임라인) · ops 사전 미매칭`.
본문 7섹션 + humanize fast → `gh pr create` → 머지는 사용자.

---

## Self-Review 기록

- 스펙 커버리지: §3 → Task 2, §4 → Task 3 · 4, §5 → Task 6 · 7, §6 → Task 8, §7 → Task 6, §8 → Task 9, §2 순서 → Phase 구조. 잔여 없음.
- 타입 일관성: `player_stats` 반환 필드 (`slug` · `count` · `stage` · `squad` · `last_ts` · `articles`) 를 Task 7 · 8 이 그대로 소비.
- 알려진 위험: `_cards.html.j2` href 의 `root` 도입 (Task 8) 이 index · all 회귀를 만들 수 있음 — 전체 테스트 + 브라우저로 확인하도록 명시.
