# SP-B 배포 게이트 구현 계획 — 잔여 페이지 자동 정리 · 소스별 차등 서빙 (2026-07-20)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공개 전 게이트 두 가지를 구현한다 — `write_site` 가 DB 에서 빠진 기사의 잔여 페이지를 렌더마다 자동 삭제하고, 상세 페이지 본문을 소스별 서빙 모드 (full · excerpt) 로 차등 렌더한다.

**Architecture:** 순수 함수 2개 (`serving_mode` · `excerpt_paras`) 와 정리 함수 1개 (`sweep_orphan_pages`) 를 `serve/render.py` 에 추가하고, `render_article` 과 `write_site` 에 각각 배선한다.
서빙 모드는 `config/sources.yaml` 의 소스별 `serving` 키가 SoT 이고, 미지정 소스는 안전한 기본값 (excerpt) 으로 처리한다.

**Tech Stack:** Python 3.11 · Jinja2 · pytest · PyYAML. 스키마 · DB 변경 없음.

**Spec:** `docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md` §2.3 (차등 서빙) · §2.6 (잔여 페이지) · §3.1 (SP-B 범위) · §4 (검증 기준).

## Global Constraints

- 테스트 실행 명령은 `uv run pytest -q` (통합 테스트는 DB 없으면 자동 skip).
- 커밋 제목은 `<type>(<scope>): 한국어 제목`, 본문은 도입 1~2문장 + 명사형 불릿, `Refs:` 트레일러 (컨벤션 §1.1).
- co-author 트레일러는 설계 · 구현 역할 병기 (§1.3) — 아래 각 커밋 블록에 명시된 대로 사용.
- 수술적 변경 — 이 계획에 없는 인접 코드 · 주석 · 포맷을 고치지 않는다.
- 구현 diff 는 Edit 도구로만 만들고 bash 일괄 치환을 쓰지 않는다 (2026-07-20 파일 오염 사고 재발 방지).
- 라이브 재렌더 (379 → 205 실측) 는 이 계획 범위 밖 — main 통합 후 별도 수행 (주의: 데이터 작업은 main 통합 상태에서만).

## 파일 구조

- 수정: `src/bullet_in/serve/render.py` — 순수 함수 2개 + 정리 함수 1개 + `render_article` · `write_site` 배선.
- 수정: `src/bullet_in/serve/templates/detail.html.j2` — 발췌 안내문 블록.
- 수정: `src/bullet_in/serve/static/style.css` — `.excerpt-note` 스타일.
- 수정: `config/sources.yaml` — 소스 9종에 `serving` 키.
- 수정: `tests/test_serve_render.py` — 신규 테스트 + 기존 픽스처 `serving: full` 부여.
- 생성: `tests/test_serving_config.py` — config 계약 테스트.
- 수정: `docs/runbook/2026-06-29-serving-ui-verification.md` — 검증 절 추가.

---

### Task 1: 서빙 모드 · 발췌 순수 함수

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`interleave_body` 함수 아래에 추가)
- Test: `tests/test_serve_render.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: 없음 (독립 순수 함수).
- Produces: `serving_mode(source_id: str | None, sources: dict) -> str` ("full" | "excerpt" 반환) · `excerpt_paras(paras: list[str], limit: int = 300, max_paras: int = 2) -> list[str]`.
  Task 2 의 `render_article` 이 이 두 함수를 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_serve_render.py` 끝에 추가:

```python
# ---- SP-B 차등 서빙: serving_mode · excerpt_paras (spec §2.3) ----
from bullet_in.serve.render import serving_mode, excerpt_paras

def test_serving_mode_reads_config_and_defaults_to_excerpt():
    sources = {"bbc_sport": {"serving": "excerpt"}, "x_afcstuff": {"serving": "full"}}
    assert serving_mode("x_afcstuff", sources) == "full"
    assert serving_mode("bbc_sport", sources) == "excerpt"
    assert serving_mode("new_source", sources) == "excerpt"   # 미지정 소스 → 안전 기본값
    assert serving_mode(None, sources) == "excerpt"

def test_serving_mode_invalid_value_falls_back_to_excerpt():
    assert serving_mode("s", {"s": {"serving": "banana"}}) == "excerpt"

def test_excerpt_paras_takes_at_most_two_paragraphs():
    paras = ["짧은 첫 문단.", "둘째 문단.", "셋째 문단."]
    assert excerpt_paras(paras) == ["짧은 첫 문단.", "둘째 문단."]

def test_excerpt_paras_stops_when_first_paragraph_reaches_limit():
    long_first = "가" * 300
    assert excerpt_paras([long_first, "둘째"]) == [long_first]

def test_excerpt_paras_empty_input():
    assert excerpt_paras([]) == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k "serving_mode or excerpt_paras"`
Expected: FAIL — `ImportError: cannot import name 'serving_mode'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/serve/render.py` 의 `interleave_body` 함수 정의 바로 아래에 추가:

```python
def serving_mode(source_id: str | None, sources: dict) -> str:
    """소스별 상세 페이지 서빙 범위 (spec §2.3). config 미지정 · 미상 값은 안전한 기본값 excerpt."""
    mode = (sources.get(source_id) or {}).get("serving")
    return mode if mode in ("full", "excerpt") else "excerpt"


def excerpt_paras(paras: list[str], limit: int = 300, max_paras: int = 2) -> list[str]:
    """발췌 모드 본문 — 첫 1~2문단, 누적 limit 자 도달 시 중단 (문단 중간은 자르지 않음)."""
    out, total = [], 0
    for p in paras[:max_paras]:
        out.append(p)
        total += len(p)
        if total >= limit:
            break
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k "serving_mode or excerpt_paras"`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_render.py
git commit -m "feat(serve): 서빙 모드 판별 · 발췌 순수 함수

차등 서빙 (spec §2.3) 의 판별 계층을 렌더 배선과 분리해 먼저 만든다.

- serving_mode: config serving 키 판독, 미지정 · 미상 값은 excerpt 기본값
- excerpt_paras: 첫 1~2문단 · 누적 300자 컷, 문단 중간은 자르지 않음

Refs: docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md §2.3

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 2: render_article 발췌 분기 + 템플릿 안내문 + 스타일

**Files:**
- Modify: `src/bullet_in/serve/render.py:498-509` (`render_article`)
- Modify: `src/bullet_in/serve/templates/detail.html.j2:33-34` (body 닫는 div 와 origin 줄 사이)
- Modify: `src/bullet_in/serve/static/style.css` (파일 끝에 추가)
- Modify: `tests/test_serve_render.py:38` (`SOURCES` 픽스처) + 파일 끝 신규 테스트

**Interfaces:**
- Consumes: Task 1 의 `serving_mode` · `excerpt_paras`.
- Produces: `render_article` 이 article dict 에 `_excerpt: bool` 을 세팅하고, 템플릿이 `a._excerpt` 로 안내문을 분기.
  시그니처 변경 없음 — 기존 호출부 (write_site · 테스트) 수정 불필요.

- [ ] **Step 1: 기존 픽스처에 서빙 모드 명시**

`tests/test_serve_render.py` 38행의 모듈 픽스처를 다음으로 교체 (기존 상세 테스트들은 전문 렌더 동작을 검증하므로 full 로 고정):

```python
SOURCES = {"bbc_sport": {"display_name": "BBC Sport", "serving": "full"}}
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_serve_render.py` 끝에 추가 (`_dec` · `_ra` 는 262행에서 이미 import 됨):

```python
def test_detail_excerpt_mode_cuts_body_and_shows_notice():
    src = {"bbc_sport": {"display_name": "BBC Sport", "serving": "excerpt"}}
    row = _row(body_ko="첫 문단." + "가" * 300 + "\n둘째 문단.\n셋째 문단.")
    html = _ra(_dec(row, src, NOW), [], "h1", src, NOW)
    assert "셋째 문단" not in html                    # 발췌 범위 밖 본문 제외
    assert 'class="excerpt-note"' in html
    assert "원문 전체 보기" in html

def test_detail_full_mode_keeps_whole_body_without_notice():
    row = _row(body_ko="첫 문단.\n둘째 문단.\n셋째 문단.")
    html = _ra(_dec(row, SOURCES, NOW), [], "h1", SOURCES, NOW)
    assert "셋째 문단" in html
    assert "excerpt-note" not in html

def test_detail_excerpt_mode_drops_inline_images():
    src = {"bbc_sport": {"serving": "excerpt"}}
    row = _row(body_ko="문단1\n문단2\n문단3\n문단4",
               image_url="https://img/hero.jpg",
               images_json='["https://img/a.jpg", "https://img/b.jpg"]')
    html = _ra(_dec(row, src, NOW), [], "h1", src, NOW)
    assert "img/a.jpg" not in html and "img/b.jpg" not in html
```

- [ ] **Step 3: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k "excerpt_mode or full_mode"`
Expected: FAIL — excerpt-note 부재 · 셋째 문단 존재

- [ ] **Step 4: 구현**

`render_article` (render.py 498~509행) 을 다음으로 교체:

```python
def render_article(article: dict, neighbors: list[dict], current_hash: str,
                   sources: dict, now: datetime, facets: dict | None = None) -> str:
    # facets=None이면 빈 구조로 폴백 (하위 호환 유지)
    if facets is None:
        facets = {"team": {}, "tiers": [], "total": 0, "stage": {}, "other": 0,
                  "outlets": {"initial": [], "stages": []},
                  "journalists": {"initial": [], "stages": []}}
    article = dict(article)
    paras = [p for p in (article.get("body_ko") or "").split("\n") if p.strip()]
    article["_excerpt"] = serving_mode(article.get("source_id"), sources) == "excerpt"
    images = article.get("_images") or []
    if article["_excerpt"]:
        paras, images = excerpt_paras(paras), []
    article["_body_blocks"] = interleave_body(paras, images)
    return _env().get_template("detail.html.j2").render(
        a=article, neighbors=neighbors, active=None, root="../", facets=facets)
```

`detail.html.j2` 33~34행 (body 닫는 `</div>` 와 origin 줄) 사이에 안내문 블록 삽입:

```html
    </div>
    {% if a._excerpt %}
    <p class="excerpt-note">이 기사는 요약과 앞부분 발췌만 제공합니다 — <a href="{{ a.url }}" target="_blank" rel="noopener">원문 전체 보기 ↗</a></p>
    {% endif %}
    <p class="origin">출처: {{ a._outlet }}{% if a.journalist %} · {{ a.journalist }}{% endif %} · <a href="{{ a.url }}" target="_blank" rel="noopener">원문 기사 보기 ↗</a></p>
```

`style.css` 파일 끝에 추가:

```css
/* SP-B 차등 서빙 — 발췌 안내문 */
.excerpt-note{margin:18px 0 0;padding:12px 14px;border:1px solid var(--line);
  border-radius:9px;font-size:14px;color:var(--muted)}
.excerpt-note a{font-weight:600}
```

- [ ] **Step 5: 통과 확인 (신규 + 기존 상세 테스트 회귀)**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: 전체 passed (기존 상세 테스트는 픽스처 full 고정으로 동작 불변)

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/serve/templates/detail.html.j2 \
        src/bullet_in/serve/static/style.css tests/test_serve_render.py
git commit -m "feat(serve): 상세 페이지 소스별 차등 서빙 — 발췌 모드 렌더 · 안내문

언론사 기사 전문 번역을 공개 서빙에서 빼는 차등 서빙 (spec §2.3) 의 렌더 배선.

- render_article: serving_mode 가 excerpt 면 첫 1~2문단 (약 300자) 만 렌더 · 인라인 이미지 제외
- detail 템플릿: 발췌 안내문 + 원문 전체 링크 블록 (_excerpt 분기)
- 기존 테스트 픽스처는 serving full 로 고정해 전문 렌더 검증 유지

Refs: docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md §2.3

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>"
```

---

### Task 3: 잔여 페이지 자동 정리 + write_site 배선

**Files:**
- Modify: `src/bullet_in/serve/render.py` (상단 import + `write_site` 끝에 호출 + 신규 함수)
- Test: `tests/test_serve_render.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: 없음 (파일 시스템 + articles 목록만).
- Produces: `sweep_orphan_pages(articles: list[dict], out_dir: str | Path) -> list[str]` (삭제한 파일명 목록 반환).
  `write_site` 가 상세 페이지 생성 직후 호출 — 외부 호출부 (run.py · 재생성 스니펫) 는 시그니처 불변으로 자동 적용.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_serve_render.py` 끝에 추가:

```python
# ---- SP-B 잔여 페이지 자동 정리 (spec §2.6) ----
from bullet_in.serve.render import write_site, sweep_orphan_pages

def test_write_site_removes_orphan_pages(tmp_path):
    art = tmp_path / "article"
    art.mkdir(parents=True)
    (art / "orphan.html").write_text("stale", encoding="utf-8")
    rows = [_row(content_hash="keep1"), _row(content_hash="keep2", url="https://x/2")]
    write_site(rows, SOURCES, tmp_path, NOW)
    assert not (art / "orphan.html").exists()
    assert (art / "keep1.html").exists() and (art / "keep2.html").exists()

def test_write_site_skips_sweep_when_no_articles(tmp_path):
    art = tmp_path / "article"
    art.mkdir(parents=True)
    (art / "orphan.html").write_text("stale", encoding="utf-8")
    write_site([], SOURCES, tmp_path, NOW)
    assert (art / "orphan.html").exists()   # 렌더 대상 0건 → 오삭제 방어로 건너뜀

def test_sweep_orphan_pages_returns_removed_names(tmp_path):
    art = tmp_path / "article"
    art.mkdir(parents=True)
    (art / "keep1.html").write_text("x", encoding="utf-8")
    (art / "old1.html").write_text("x", encoding="utf-8")
    (art / "old2.html").write_text("x", encoding="utf-8")
    removed = sweep_orphan_pages([{"content_hash": "keep1"}], tmp_path)
    assert removed == ["old1.html", "old2.html"]
    assert (art / "keep1.html").exists()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q -k "orphan or sweep"`
Expected: FAIL — `ImportError: cannot import name 'sweep_orphan_pages'`

- [ ] **Step 3: 구현**

`render.py` 상단 import 절에 추가 (기존 import 뒤):

```python
import logging

log = logging.getLogger(__name__)
```

`excerpt_paras` 아래에 신규 함수:

```python
def sweep_orphan_pages(articles: list[dict], out_dir: str | Path) -> list[str]:
    """DB 에서 빠진 기사의 잔여 페이지 파일을 삭제한다 (spec §2.6). 삭제한 파일명 목록 반환.

    렌더 대상 0건은 DB 조회 실패와 구분할 수 없으므로 삭제를 건너뛴다 (오삭제 방어).
    """
    art_dir = Path(out_dir) / "article"
    if not articles:
        log.warning("잔여 페이지 정리 건너뜀 — 렌더 대상 0건 (DB 조회 실패 가능성)")
        return []
    valid = {a["content_hash"] for a in articles}
    removed = sorted(f.name for f in art_dir.glob("*.html") if f.stem not in valid)
    for name in removed:
        (art_dir / name).unlink()
    if removed:
        log.info("잔여 페이지 %d건 삭제 (DB 에서 빠진 기사)", len(removed))
    return removed
```

`write_site` 의 상세 페이지 생성 for 루프 종료 직후 · 정적 자산 복사 직전에 한 줄 삽입:

```python
    sweep_orphan_pages(articles, out)

    for asset in ("style.css", "app.js"):
        shutil.copyfile(_STATIC_DIR / asset, out / asset)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: 전체 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_render.py
git commit -m "feat(serve): 잔여 페이지 자동 정리 — write_site 가 DB 대조 삭제

재수집 · 행 삭제로 DB 에서 빠진 기사의 페이지 파일이 누적되는 문제 (실측 174건) 를
사이트를 다시 만들 때마다 자동으로 정리한다 (spec §2.6).

- sweep_orphan_pages: site/article/*.html 을 content_hash 목록과 대조해 고아 파일 삭제
- 오삭제 방어: 렌더 대상 0건이면 삭제를 건너뛰고 WARNING 로깅
- write_site 끝에 배선 — 호출부 시그니처 불변으로 run.py · 재생성 절차에 자동 적용

Refs: docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md §2.6

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 4: config 서빙 모드 선언 + 계약 테스트

**Files:**
- Modify: `config/sources.yaml` (소스 9종에 `serving` 키)
- Create: `tests/test_serving_config.py`

**Interfaces:**
- Consumes: Task 1 의 모드 값 집합 ("full" | "excerpt").
- Produces: 운영 config 의 소스별 `serving` 선언 — `load_sources` (score.py) 가 dict 로 그대로 실어 render 까지 전달 (코드 변경 불필요).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_serving_config.py` 신규 생성:

```python
"""config/sources.yaml 의 차등 서빙 선언 계약 (spec §2.3 매핑표)."""
import yaml
from pathlib import Path

FULL_SOURCES = {"arsenal_official", "x_afcstuff", "fmkorea"}

def _modes():
    data = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))
    return {s["source_id"]: s.get("serving") for s in data["sources"]}

def test_every_source_declares_valid_serving_mode():
    modes = _modes()
    invalid = {k: v for k, v in modes.items() if v not in ("full", "excerpt")}
    assert not invalid, f"serving 미선언 · 미상 값: {invalid}"

def test_full_mode_matches_spec_mapping():
    modes = _modes()
    assert {sid for sid, m in modes.items() if m == "full"} == FULL_SOURCES
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serving_config.py -q`
Expected: FAIL — serving 미선언 소스 목록 출력

- [ ] **Step 3: config 에 serving 키 추가**

`config/sources.yaml` 의 각 소스 블록에서 `display_name` 아래 줄에 삽입 (탭 아님, 스페이스 4칸 들여쓰기 유지).
언론사 6종 (bbc_sport · bbc_gossip · goal · football_london · guardian · skysports):

```yaml
    serving: excerpt   # 상세 페이지 서빙 범위 (spec §2.3) — 언론사 기사는 요약 + 발췌 + 원문 링크
```

전문 3종은 각각:

```yaml
    serving: full      # 상세 페이지 서빙 범위 (spec §2.3) — 구단 공식 발표문은 전문
```

```yaml
    serving: full      # 상세 페이지 서빙 범위 (spec §2.3) — 트윗 원문은 수십 단어 = 인용 수준
```

```yaml
    serving: full      # 상세 페이지 서빙 범위 (spec §2.3) — 퍼가기 금지 정책 (#85) 이 별도 처리
```

(순서대로 arsenal_official · x_afcstuff · fmkorea 블록에 삽입.)

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_serving_config.py tests/test_serve_render.py -q`
Expected: 전체 passed

- [ ] **Step 5: 커밋**

```bash
git add config/sources.yaml tests/test_serving_config.py
git commit -m "feat(config): 소스별 서빙 모드 선언 — 언론사 excerpt · 전문 3종 full

차등 서빙 매핑 (spec §2.3 표) 을 config 로 옮겨 SoT 로 만든다.
미선언 소스는 코드 기본값 (excerpt) 이 방어하지만, 운영 소스는 전부 명시한다.

- 언론사 6종 (bbc_sport · bbc_gossip · goal · football_london · guardian · skysports): excerpt
- arsenal_official · x_afcstuff · fmkorea: full (구단 공식 · 트윗 인용 수준 · 기존 정책)
- 계약 테스트: 전 소스 유효값 + full 집합이 spec 매핑과 일치

Refs: docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md §2.3

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>"
```

---

### Task 5: 검증 런북 절 + 전체 회귀

**Files:**
- Modify: `docs/runbook/2026-06-29-serving-ui-verification.md` (파일 끝에 절 추가)

**Interfaces:**
- Consumes: Task 2~4 의 동작 (안내문 · 정리 · config 매핑).
- Produces: 라이브 재렌더 후 사람이 돌릴 검증 절차 — SP-D 게이트 체크리스트가 이 절을 참조.

- [ ] **Step 1: 런북 절 추가**

`docs/runbook/2026-06-29-serving-ui-verification.md` 끝에 추가:

```markdown
## 차등 서빙 · 잔여 페이지 정리 검증 (SP-B, 2026-07-20)

라이브 재렌더 (main 통합 상태) 후 아래를 확인한다.

- 파일 수 = DB 행 수: `ls site/article/*.html | wc -l` 결과가 MariaDB articles 행 수와 일치해야 함 (잔여 페이지 0).
- 언론사 상세 페이지 = 발췌 + 안내문: `grep -l "excerpt-note" site/article/*.html | head -3` 이 파일 목록을 내야 함.
- 전문 3종 (x_afcstuff · fmkorea · arsenal_official) 상세 페이지 = 안내문 없음:
  해당 소스 기사의 content_hash 를 DB 에서 뽑아 그 파일에 excerpt-note 가 없는지 grep 으로 확인.
- 오삭제 방어: 강제로 빈 목록을 넘긴 재생성에서 "잔여 페이지 정리 건너뜀" WARNING 이 남아야 한다.
```

- [ ] **Step 2: 전체 테스트 회귀**

Run: `uv run pytest -q`
Expected: 전체 passed (통합 테스트는 DB · Airflow 없으면 skip) — 실패 시 해당 태스크로 돌아가 수정

- [ ] **Step 3: 커밋**

```bash
git add docs/runbook/2026-06-29-serving-ui-verification.md
git commit -m "docs(runbook): 차등 서빙 · 잔여 페이지 정리 검증 절 추가

SP-B 머지 후 라이브 재렌더에서 사람이 돌릴 확인 절차를 서빙 검증 런북에 싣는다.

- 파일 수 = DB 행 수 대조 · 발췌 안내문 유무의 소스별 확인 · 오삭제 방어 로그 확인

Refs: docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md §4

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>"
```

---

## 완료 후 (계획 범위 밖 · 컨트롤러 수행)

- 최종 리뷰 (Fable 5) → PR 생성 (7섹션 본문 · `--body-file`) → 사용자 머지.
- 머지 후 main 에서 라이브 재렌더 1회: 379 → 205 파일 실측 · 힌카피에 구표기 16건 삭제 확인 · 런북 검증 절 수행.
- 검증 결과는 PR 코멘트 또는 다음 세션 기록으로 남긴다.
