# Tier 1 ③ — 비-이적 'other' 서빙 opt-in 토글 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파이프라인이 이미 산출한 `transfer_stage='other'`(비-이적) 기사를 서빙에서 기본 숨기고, 사이드바 '기타' 체크박스로 사용자가 켤 수 있게 한다.

**Architecture:** 수집·분류·DB는 무수정. 서빙 3파일만 국소 변경한다. (1) `facet_counts`가 off-mission 개수를 별도 키 `other`로 반환 → (2) 템플릿이 off-mission 카드에 `style="display:none"`를 렌더(첫 로드부터 숨김; `applyFilters()`는 초기 로드 시 호출 안 됨) + 사이드바에 '기타' 체크박스 추가 → (3) `app.js`가 '기타' 체크 시에만 other 카드를 노출. DB 데이터 무삭제 → 완전 가역.

**Tech Stack:** Python 3.11 · uv · Jinja2 · pytest. 순수 정적 HTML/JS(빌드 스텝 없음).

**Spec:** `docs/superpowers/specs/2026-06-30-tier1-other-serving-toggle-design.md`

## Global Constraints

- **브랜치**: `feat/tier1-other-serving-toggle` 에서 작업, 태스크별 커밋, 종료 시 squash PR (GitHub Flow).
- **커밋 컨벤션**: `<type>(<scope>): 한국어 제목` + 본문(왜). scope=`serve`. 트레일러 필수:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **git 신원**: `benidjor <94089198+benidjor@users.noreply.github.com>`.
- **karpathy 수술적 변경**: 인접 코드·주석·포맷을 "개선"하지 말 것. 바뀐 모든 줄이 이 목표에 직접 추적돼야 함.
- **spec 대비 정제(중요)**: 기존 테스트 `test_facet_counts_includes_stage_excluding_other` 가 `"other" not in f["stage"]` 를 계약한다. 그러므로 other 개수는 `f["stage"]`에 넣지 않고 **별도 키 `f["other"]`** 로 노출한다.
- **off-mission 정의**: `transfer_stage` 가 6개 SIDEBAR 단계 중 하나가 **아닌** 모든 것(= `other` + `None`/미태깅). 카드 숨김 조건은 `not a._stage_badge`, 카운트는 `facet_counts`의 `else` 분기, app.js는 `!stage || stage==='other'` 로 **동일 집합**을 가리킨다.
- 테스트: `uv run pytest -q` 전건 통과 유지.

---

### Task 1: `facet_counts` 가 off-mission 개수를 `other` 키로 반환

**Files:**
- Modify: `src/bullet_in/serve/render.py:70-76` (`facet_counts`)
- Modify: `src/bullet_in/serve/render.py:135-137` (`render_article` 폴백 facets — 형태 일치)
- Test: `tests/test_serve_layout.py` (파일 끝에 추가)

**Interfaces:**
- Produces: `facet_counts(articles, sources)` 반환 dict에 `"other": int` 키 추가(6단계 외 전부의 개수). 기존 `"stage"` 는 6단계만 유지(불변).

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_serve_layout.py` 끝에 추가)

```python
def test_facet_counts_other_bucket_counts_offmission():
    arts = [
        {"transfer_stage": "rumour"},
        {"transfer_stage": "official"},
        {"transfer_stage": "other"},
        {},  # 미태깅(None)
    ]
    f = facet_counts(arts, {})
    assert f["other"] == 2            # other + None (= 비-displayable)
    assert "other" not in f["stage"]  # 기존 계약: stage에는 미포함
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_layout.py::test_facet_counts_other_bucket_counts_offmission -q`
Expected: FAIL — `KeyError: 'other'`

- [ ] **Step 3: 구현** — `render.py` `facet_counts` 의 stage 집계 블록(현재 70-76행)을 아래로 교체

```python
    stage_counts = {e: 0 for e, _, _ in _stage.SIDEBAR_STAGES}
    other_count = 0
    for a in articles:
        s = a.get("transfer_stage")
        if s in stage_counts:
            stage_counts[s] += 1
        else:
            other_count += 1
    return {"total": len(articles), "team": dict(teams),
            "outlets": outlets, "tiers": tiers, "stage": stage_counts,
            "other": other_count}
```

그리고 `render_article` 폴백 facets(현재 135-137행)에 `"other": 0` 추가:

```python
    if facets is None:
        facets = {"team": {}, "outlets": [], "tiers": {t: 0 for t in range(5)},
                  "total": 0, "stage": {}, "other": 0}
```

- [ ] **Step 4: 통과 확인 + 회귀 확인**

Run: `uv run pytest tests/test_serve_layout.py -q`
Expected: PASS (신규 + 기존 `test_facet_counts*` 모두)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_layout.py
git commit -m "$(cat <<'EOF'
feat(serve): facet_counts가 off-mission 개수를 other 키로 반환

사이드바 '기타' 토글 배지용. 기존 stage 계약(6단계·other 제외)은
유지하고 별도 키 other로 노출.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 템플릿 — off-mission 카드 기본 숨김 + 사이드바 '기타' 체크박스

**Files:**
- Modify: `src/bullet_in/serve/templates/index.html.j2:6` (카드 `<a>` 태그)
- Modify: `src/bullet_in/serve/templates/_layout.html.j2:36` (stage 루프 직후)
- Test: `tests/test_serve_render.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: Task 1의 `facets.other`, 그리고 `_decorate` 가 세팅하는 `a._stage_badge`(= `is_displayable`).
- Produces: index HTML의 off-mission 카드 `<a>` 에 `style="display:none"`; 사이드바에 `data-group="bucket" data-value="other"` 체크박스(기본 미체크).

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_serve_render.py` 끝에 추가)

```python
import re as _re

def test_index_hides_offmission_card_by_default():
    tr = _row(content_hash="t", transfer_stage="rumour")
    ot = _row(content_hash="o", transfer_stage="other")
    html = render_index([tr, ot], SOURCES, NOW)
    o_tag = _re.search(r'<a class="card"[^>]*href="article/o\.html"', html).group(0)
    t_tag = _re.search(r'<a class="card"[^>]*href="article/t\.html"', html).group(0)
    assert "display:none" in o_tag       # off-mission(other) 카드만 숨김
    assert "display:none" not in t_tag   # 이적 카드(rumour)는 노출

def test_sidebar_has_other_bucket_checkbox():
    html = render_index([_row(transfer_stage="other")], SOURCES, NOW)
    assert 'data-group="bucket"' in html
    assert 'data-value="other"' in html
    assert "기타" in html
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py::test_index_hides_offmission_card_by_default tests/test_serve_render.py::test_sidebar_has_other_bucket_checkbox -q`
Expected: FAIL — 카드에 `display:none` 없음 / `data-group="bucket"` 없음

- [ ] **Step 3: 구현**

`index.html.j2` 6행:

```jinja
  <a class="card" href="article/{{ a.content_hash }}.html"
```

를 아래로 교체(카드 `<a>` 에 조건부 style 추가):

```jinja
  <a class="card"{% if not a._stage_badge %} style="display:none"{% endif %} href="article/{{ a.content_hash }}.html"
```

`_layout.html.j2` 의 stage 루프 종료(36행 `{% endfor %}`) 바로 아래에 '기타' 체크박스 한 줄 추가:

```jinja
    {% endfor %}
    <label class="opt"><input type="checkbox" data-group="bucket" data-value="other"> 기타 <span class="ct">{{ facets.other or 0 }}</span></label>
```

- [ ] **Step 4: 통과 확인 + 회귀 확인**

Run: `uv run pytest tests/test_serve_render.py tests/test_serve_layout.py -q`
Expected: PASS (신규 2건 + 기존 render/layout 테스트 전건. 특히 기존 `test_index_other_stage_has_data_attr_but_no_badge` 는 style 추가와 무관하게 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/templates/index.html.j2 src/bullet_in/serve/templates/_layout.html.j2 tests/test_serve_render.py
git commit -m "$(cat <<'EOF'
feat(serve): off-mission 카드 기본 숨김 + 사이드바 '기타' 토글

첫 로드부터 other를 가리려면 서버가 display:none로 렌더해야 한다
(app.js applyFilters는 초기 로드 시 미호출). '기타' 체크박스는 기본 미체크.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `app.js` — '기타' 체크 시에만 other 노출

**Files:**
- Modify: `src/bullet_in/serve/static/app.js:26-48` (`applyFilters`)
- Test: `tests/test_serve_render.py` (파일 끝에 추가 — 정적 계약 검증)

**Interfaces:**
- Consumes: 사이드바의 `input[data-group=bucket][data-value=other]`(Task 2), 카드 `data-stage`(기존).
- Produces: 기본(미체크)엔 other 숨김, '기타' 체크 시 노출. `stage` 그룹 체크박스와 독립.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_serve_render.py` 끝에 추가)

```python
def test_app_js_has_other_bucket_toggle_contract():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-group=bucket" in js   # '기타' 토글 셀렉터
    assert "showOther" in js            # other 노출 분기
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py::test_app_js_has_other_bucket_toggle_contract -q`
Expected: FAIL — `showOther` / `data-group=bucket` 부재

- [ ] **Step 3: 구현** — `app.js` 의 `applyFilters` 함수(26-48행)를 아래로 교체

```javascript
function applyFilters() {
  const q = (searchInput.value || '').trim().toLowerCase();
  const outlets = checkedValues('outlet');
  const tiers = checkedValues('tier');
  const stages = checkedValues('stage');
  const showOther = !!side.querySelector('input[data-group=bucket][data-value=other]')?.checked;
  let shown = 0;
  for (const card of cards) {
    const okText = !q || (card.dataset.text || '').includes(q);
    const okOutlet = outlets.length === 0 || outlets.includes(card.dataset.outlet);
    const okTier = tiers.length === 0 || tiers.includes(card.dataset.tier);
    const st = card.dataset.stage;
    const isOther = !st || st === 'other';
    const okStage = isOther
      ? showOther
      : (stages.length === 0 || stages.includes(st));
    const visible = okText && okOutlet && okTier && okStage;
    card.style.display = visible ? '' : 'none';
    if (visible) shown++;
  }
  sortCards();
  const sort = side.querySelector('input[name=sort]:checked').dataset.value;
  const conds = outlets.length + tiers.length + stages.length + (showOther ? 1 : 0) + (q ? 1 : 0);
  fstatus.textContent = conds || q
    ? `적용됨 · 조건 ${conds}개 · ${shown}건`
    : `미적용 · 전체 ${shown}건`;
  applyBtn.classList.remove('dirty');
}
```

> `reset`(65-70행)은 `enabledBoxes().forEach(c => c.checked = (c.dataset.value === 'arsenal'))` 이 '기타'(value `other`) 를 자동으로 끄므로 **무수정**.

- [ ] **Step 4: 통과 확인 + 전건 회귀**

Run: `uv run pytest -q`
Expected: PASS (전건. 기존 `test_static_assets_exist_and_nonempty` 포함)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/static/app.js tests/test_serve_render.py
git commit -m "$(cat <<'EOF'
feat(serve): '기타' 체크 시에만 other 카드 노출

applyFilters가 other(및 미태깅)를 bucket 토글로 분기. 기본은 숨김,
체크 시 노출. stage 그룹과 독립. reset은 자동으로 기타를 끔.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: 수동 검증(진리표)** — app.js 동작은 단위 테스트 불가 → 빌드 후 육안 확인

```bash
set -a; source .env; set +a   # MARIADB_URL 로드 (이 프로젝트는 dotenv 미사용)
uv run python - <<'PY'
import os, yaml
from sqlalchemy import create_engine, text
from bullet_in.serve.render import write_site
COLS = ("content_hash,url,source_id,title_original,title_ko,summary_ko,summary3_ko,"
        "body_ko,image_url,outlet,journalist,team,transfer_stage,tier,confidence_score,published_at")
eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    rows = [dict(r) for r in c.execute(text(f"SELECT {COLS} FROM articles")).mappings()]
sources = {s["source_id"]: s for s in yaml.safe_load(open("config/sources.yaml"))["sources"]}
out = "/private/tmp/claude-501/-Users-aryijq-Documents-01-DE-project-bullet-in/d534afb4-a2ac-4332-9feb-e433567d6d61/scratchpad/site_preview"
write_site(rows, sources, out)
print("built", len(rows), "->", out)
PY
python3 -m http.server 8766 -d /private/tmp/claude-501/-Users-aryijq-Documents-01-DE-project-bullet-in/d534afb4-a2ac-4332-9feb-e433567d6d61/scratchpad/site_preview
```

브라우저 http://127.0.0.1:8766 에서 확인:
- [ ] 초기 로드: other(경기 평점·킷 공개 등)가 안 보이고 이적 단계 기사만 표시.
- [ ] 사이드바에 '기타 (N)' 체크박스 존재, 기본 미체크.
- [ ] '기타' 체크 + '필터 적용' → other 합류. '초기화' → 다시 숨김.
- [ ] '루머'만 체크 → rumour만. '루머'+'기타' → rumour + other.

> `site_preview`는 scratchpad(저장소 밖)라 정리 불필요.

---

## 완료 후

전건 `uv run pytest -q` 통과 + 수동 진리표 확인 후, `feat/tier1-other-serving-toggle` 를 squash PR(7섹션 한국어 본문, `--body-file`, Claude 서명 금지)로 올린다.
