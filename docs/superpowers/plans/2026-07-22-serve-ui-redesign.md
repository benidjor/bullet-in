# serve/ UI 개편 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 에디토리얼 문법 · 공신력 위계 · 사건 묶음으로 서빙 화면을 개편한다 (스펙 2건 · 단일 PR).

**Architecture:** 표시 계층 (`src/bullet_in/serve/`) 만 고친다.
render.py 는 순수 뷰모델 헬퍼로 위계 · 톱스토리 · 날짜 묶기 · 사건 클러스터를 계산하고, 템플릿 · CSS · JS 가 그 결과를 그린다.
수집 · 분류 · enrich · 저장 스키마는 건드리지 않는다.

**Tech Stack:** Python 3.11 · Jinja2 · 바닐라 CSS/JS · pyftsubset (폰트 서브셋) · pytest.

## Global Constraints

스펙에서 그대로 옮긴 값이다.
모든 태스크의 요구사항에 암묵적으로 포함된다.

- 강조색은 셋뿐이다 — `--red` (확정 · 이적 합의 · 링크 · 워드마크) · `--green` (협상 중) · `--yellow` (개인 합의) · 나머지는 무채색 (스펙1 §4.1).
- 떠 있는 카드 · 그림자를 쓰지 않는다 · 모서리 반경 0–2px · 이모지 없음 (아이콘은 인라인 SVG) (스펙1 §4.3).
- 내부 등급 문자열 (`Tier 1.5`) 을 카드 · 상세 · 사이드바 어디에도 노출하지 않는다 (스펙1 §7.1).
- 위계 배경 · 여백 규칙은 반드시 `.item` 으로 범위를 좁힌다 (등급 클래스가 밴드 `.meta` 에도 붙어 새어 나감) (스펙2 §3.1).
- 하위 등급 요약문은 마크업 단계에서 뺀다 (CSS 로 가리지 않는다 — HTML 에 남으면 검색엔진 · 스크린리더에 노출) (스펙2 §3.1).
- 최신성 판정은 `published_at` 으로 한다 (화면 표시 문자열을 되읽지 않는다) (스펙2 §6.1).
- 폰트는 자체 호스팅한다 (외부 CDN 금지) (스펙1 §4.2).
- 다크는 `prefers-color-scheme` 기본 + `html[data-theme]` 덮어쓰기 · `color-scheme` 을 `data-theme` 별로 고정 (스펙1 §4.3 · 스펙2 §11).
- 서빙 사건 사전은 정규형만 담는다 (변형은 glossary 가 enrich 에서 접음) (스펙2 §4.2.2).
- 소유권 경계 — 다음은 수정하지 않는다 (스펙1 §15).
`config/sources.yaml` 의 `serving` 값 · `render.py` 의 `serving_mode()` · `_excerpt` 줄 · `detail.html.j2` 의 `excerpt-note` 블록 (자리만 유지) · `quality.py` · `enrich.py` · `transfer_stage.py` · `render.py` 의 `gossip_itemize()` 와 `bbc_gossip` 분기 판정 로직 · `infra/` · `README.md` · vm-cohost · afcstuff 런북.
- 테스트 기준선 = 515 passed · 1 skipped (스펙1 §17 의 492 는 낡음).

## File Structure

| 파일 | 책임 |
|---|---|
| `src/bullet_in/serve/render.py` | 뷰모델 — 표시 단계 매핑 · 독자 등급 라벨 · KST · 날짜 묶기 · 톱스토리 선정 · 사건 클러스터 · 대표 · 결말 · 관련 보도 · 가십 분리 · about |
| `src/bullet_in/serve/templates/_layout.html.j2` | 공용 골격 — 헤더 · 사이드바 순서 · 공신력 컨트롤 · 다크 토글 · 폰트 |
| `src/bullet_in/serve/templates/index.html.j2` | 톱스토리 밴드 · 날짜 구분 · 사건 블록 · 가십 구역 |
| `src/bullet_in/serve/templates/detail.html.j2` | 원제 병기 · 메타 그리드 · 번역 고지 · 본문 · 원문 박스 |
| `src/bullet_in/serve/templates/about.html.j2` | 신설 — 소개 페이지 |
| `src/bullet_in/serve/static/style.css` | 전면 개편 — 토큰 · 세리프 · 위계 · 다단 · 다크 |
| `src/bullet_in/serve/static/app.js` | 소스 · 기자 OR 결합 · 공신력 연동 · 자동 펼침 · 다크 토글 |
| `src/bullet_in/serve/static/fonts/` | 신설 — Noto Serif KR 700 · 900 · Pretendard woff2 서브셋 |
| `tests/serve/test_render_redesign.py` | 신설 — 뷰모델 헬퍼 단위 테스트 |

기존 `tests/` 의 render 테스트는 시그니처가 바뀌는 헬퍼만 갱신하고 나머지는 손대지 않는다.

## 클러스터링 데이터 원천 (Phase 2 선행 확인)

- 선수 사전 = `config/name_map.yaml` 의 `names:` 키 (정규형 한글 인명).
glossary 가 변형을 enrich 에서 접으므로 서빙은 정규형만 안다 (스펙2 §4.2.2).
- 구단 검출 = `config/club_map.yaml` 의 `clubs:` (결말 판정 · 행선지 칩).
- render.py 가 받는 컬럼 (`bullet_in.run.SERVING_SELECT_SQL`) — `title_ko` · `body_ko` · `transfer_stage` · `tier` · `published_at` · `published_precision` · `title_original` 이 클러스터 · 대표 · 번역 대기 판정 입력이다.

---

## Phase 0 — 폰트 자체 호스팅

### Task 0: 폰트 서브셋 · @font-face

**Files:**
- Create: `src/bullet_in/serve/static/fonts/NotoSerifKR-{700,900}.subset.woff2`
- Create: `src/bullet_in/serve/static/fonts/Pretendard-{400,600,700}.subset.woff2`
- Modify: `src/bullet_in/serve/render.py:579` (`write_site` 의 자산 복사 목록에 `fonts/` 추가)

**Interfaces:**
- Produces: `@font-face` 규칙 (Task 4 의 style.css 가 `url("fonts/…")` 로 참조).

- [ ] **Step 1: fonttools 설치**

Run: `uv add --dev fonttools brotli`
Expected: 설치 성공 · `uv run python -c "import fontTools"` 무오류.

- [ ] **Step 2: 원본 글꼴 확보 · 서브셋**

Noto Serif KR (OFL) 과 Pretendard (OFL) 원본 ttf/otf 를 받아 한국어 + 라틴 + 숫자 + 문장부호로 서브셋한다.
서브셋 명령 (가중치마다 반복):

```bash
uv run pyftsubset NotoSerifKR-Bold.otf \
  --unicodes="U+0020-007E,U+00A0-00FF,U+AC00-D7A3,U+3130-318F,U+2010-2027,U+2032-2033,U+2018-201F" \
  --layout-features='*' --flavor=woff2 \
  --output-file=src/bullet_in/serve/static/fonts/NotoSerifKR-700.subset.woff2
```

- [ ] **Step 3: write_site 자산 복사 확장**

`write_site` 끝의 자산 복사 루프가 `style.css` · `app.js` 만 옮긴다.
`fonts/` 디렉터리 전체를 `out/fonts/` 로 복사하도록 한 줄 추가한다.

- [ ] **Step 4: 렌더 후 파일 존재 확인**

Run: 렌더 전용 패스 실행 후 `ls site/fonts/`
Expected: woff2 5개 존재.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/serve/static/fonts src/bullet_in/serve/render.py pyproject.toml uv.lock
git commit -m "feat(serve): 한국어 서브셋 폰트 자체 호스팅 — Noto Serif KR · Pretendard"
```

---

## Phase 1 — 비-클러스터링 시각 체계 (번역 무관 · 먼저)

### Task 1: 표시 단계 매핑 · 독자 등급 라벨

**Files:**
- Modify: `src/bullet_in/serve/render.py` (신규 순수 헬퍼)
- Test: `tests/serve/test_render_redesign.py`

**Interfaces:**
- Produces:
`display_stage(enum: str | None) -> dict | None` — `{"label", "tone", "filled"}` · 미표시 단계는 None.
`reader_tier(tier: float | None) -> str` — 독자 표기 (`구단 공식` · `공신력 최상` … · 미상은 빈 문자열).
- Consumes: `bullet_in.transfer_stage.SIDEBAR_STAGES` (enum 목록).

- [ ] **Step 1: 실패 테스트**

```python
from bullet_in.serve import render as R

def test_display_stage_groups_medical_into_negotiating():
    assert R.display_stage("official") == {"label": "오피셜", "tone": "red", "filled": True}
    assert R.display_stage("agreed") == {"label": "이적 합의", "tone": "red", "filled": False}
    assert R.display_stage("medical") == {"label": "협상 중", "tone": "green", "filled": False}
    assert R.display_stage("negotiating") == {"label": "협상 중", "tone": "green", "filled": False}
    assert R.display_stage("personal_terms") == {"label": "개인 합의", "tone": "yellow", "filled": False}
    assert R.display_stage("interest") == {"label": "관심", "tone": "gray", "filled": False}
    assert R.display_stage("rumour") == {"label": "루머", "tone": "gray", "filled": False}
    assert R.display_stage("other") is None
    assert R.display_stage(None) is None

def test_reader_tier_hides_internal_grade():
    assert R.reader_tier(0.0) == "구단 공식"
    assert R.reader_tier(1.0) == "공신력 최상"
    assert R.reader_tier(1.5) == "공신력 상"
    assert R.reader_tier(2.0) == "공신력 중"
    assert R.reader_tier(3.0) == "공신력 하"
    assert R.reader_tier(4.0) == "공신력 최하"
    assert R.reader_tier(None) == ""
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/serve/test_render_redesign.py -q` · Expected: FAIL (AttributeError).
- [ ] **Step 3: 구현** — `display_stage` (스펙1 §5 표) · `reader_tier` (스펙1 §7.1 표) 를 render.py 에 추가.
- [ ] **Step 4: 통과 확인** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(serve): 표시 단계 매핑 · 독자 등급 라벨 헬퍼`.

### Task 2: KST 변환 · 날짜 묶기 · 번역 대기 표지

**Files:**
- Modify: `src/bullet_in/serve/render.py`
- Test: `tests/serve/test_render_redesign.py`

**Interfaces:**
- Produces:
`to_kst(dt: datetime) -> datetime` — UTC → KST (+9h).
`group_by_day(articles: list[dict], now: datetime) -> list[dict]` — `[{"label", "date", "articles"}]` · 오늘 · 어제 · `7월 19일 (일)` 라벨 (KST 기준).
`time_in_group(row: dict, now: datetime) -> str` — `22:37` · day 정밀도 · 폴백 시 빈 문자열.
`title_pending(row: dict) -> bool` — `title_ko` 없이 `title_original` 폴백 중인지 (번역 대기 표지).

- [ ] **Step 1: 실패 테스트**

```python
from datetime import datetime
from bullet_in.serve import render as R

def test_to_kst_adds_nine_hours():
    assert R.to_kst(datetime(2026, 7, 20, 1, 0)) == datetime(2026, 7, 20, 10, 0)

def test_group_by_day_labels_today_and_yesterday():
    now = datetime(2026, 7, 20, 3, 0)   # KST 12:00
    a = {"content_hash": "a", "published_at": datetime(2026, 7, 20, 2, 0), "published_precision": "time"}
    b = {"content_hash": "b", "published_at": datetime(2026, 7, 19, 2, 0), "published_precision": "time"}
    groups = R.group_by_day([a, b], now)
    assert groups[0]["label"] == "오늘"
    assert groups[1]["label"] == "어제"

def test_time_in_group_blank_for_day_precision():
    now = datetime(2026, 7, 20, 3, 0)
    assert R.time_in_group({"published_at": datetime(2026, 7, 20, 1, 30),
                            "published_precision": "time"}, now) == "10:30"
    assert R.time_in_group({"published_at": datetime(2026, 7, 20, 1, 30),
                            "published_precision": "day"}, now) == ""

def test_title_pending_when_ko_missing_and_original_english():
    assert R.title_pending({"title_ko": None, "title_original": "Arsenal sign X"}) is True
    assert R.title_pending({"title_ko": "아스날 X 영입", "title_original": "Arsenal sign X"}) is False
```

- [ ] **Step 2: 실패 확인** · **Step 3: 구현** (스펙1 §6.2 · §12 · 스펙2 §11.1) · **Step 4: 통과 확인**.
- [ ] **Step 5: Commit** — `feat(serve): KST 변환 · 날짜 묶기 · 번역 대기 표지 헬퍼`.

### Task 3: 톱스토리 선정 (히어로 · 주요 소식) — 사건 dedup 제외

**Files:**
- Modify: `src/bullet_in/serve/render.py`
- Test: `tests/serve/test_render_redesign.py`

**Interfaces:**
- Produces:
`arsenal_subject(row: dict) -> bool` — 제목 (`title_ko`) 이 `아스날` 로 시작하는지 (스펙2 §5 근사).
`top_story_key(row: dict) -> tuple` — 정렬 키 (상위 3등급만 · 아스날 주체 · 공신력 · 단계 · 최신 · 이미지 유무).
`pick_top_stories(articles, now) -> dict` — `{"lead": row|None, "mains": list[row]}` (히어로 1 + 주요 4).
- Consumes: `display_stage` · `to_kst` (Task 1 · 2).
- Note: 사건 겹침 dedup 은 Phase 2 Task 14 에서 이 함수에 얹는다.

- [ ] **Step 1: 실패 테스트**

```python
from datetime import datetime
from bullet_in.serve import render as R

def _row(**k):
    base = {"title_ko": "제목", "tier": 1.0, "transfer_stage": "rumour",
            "published_at": datetime(2026, 7, 20), "published_precision": "time",
            "image_url": "https://x/y.jpg"}
    base.update(k); return base

def test_top_story_excludes_below_top_three_tiers():
    now = datetime(2026, 7, 20, 12, 0)
    low = _row(tier=4.0, title_ko="아스날 트로사르 방출")
    hi = _row(tier=0.0, title_ko="레안드로 트로사르 베식타스 이적")
    picks = R.pick_top_stories([low, hi], now)
    assert picks["lead"] is hi          # tier 4 는 후보 제외 (상위 3등급만)

def test_arsenal_subject_beats_higher_tier():
    now = datetime(2026, 7, 20, 12, 0)
    leak = _row(tier=1.0, title_ko="맨시티, 아스날 유망주 은두카 영입")
    ours = _row(tier=1.5, title_ko="아스날, 요케레스 영입 임박")
    picks = R.pick_top_stories([leak, ours], now)
    assert picks["lead"] is ours        # 아스날 주체가 공신력보다 앞 (스펙2 §5 2번)

def test_arsenal_subject_startswith():
    assert R.arsenal_subject({"title_ko": "아스날, 요케레스 영입"}) is True
    assert R.arsenal_subject({"title_ko": "첼시, 로저스 영입 합의"}) is False
```

- [ ] **Step 2: 실패 확인** · **Step 3: 구현** (스펙2 §5 · §5.1 · arsenal.com 배제 규칙은 애초에 넣지 않음) · **Step 4: 통과 확인**.
- [ ] **Step 5: Commit** — `feat(serve): 톱스토리 선정 — 상위 3등급 · 아스날 주체 우선`.

### Task 4: CSS 토큰 · 활자 · 다크 기반

**Files:**
- Rewrite: `src/bullet_in/serve/static/style.css`

**Deliverable:** 스펙1 §4 전체를 반영한 CSS 기반.
- `:root` 토큰 표 (스펙1 §4.1 라이트 · `@media (prefers-color-scheme: dark)` + `html[data-theme]` 다크 · §4.3).
- `@font-face` (Task 0 의 woff2 · `font-display: swap` · 시스템 폴백 · 스펙1 §4.2).
- 제목 · 워드마크 세리프 (Noto Serif KR) · 본문 · UI 산세리프 (Pretendard) (스펙1 §4.2).
- 떠 있는 카드 · 그림자 제거 · 괘선 · 여백으로 구역 분리 · 반경 0–2px (스펙1 §4.3).
- `color-scheme` 을 `html[data-theme="light"]` · `[dark]` 로 각각 고정 (스펙2 §11 체크박스 반전 방지).

- [ ] **Step 1: 토큰 · 폰트 · 기반 규칙 작성** (§4.1 · §4.2 · §4.3).
- [ ] **Step 2: 렌더 후 육안 확인** — 렌더 전용 패스 → `site/index.html` 열어 세리프 제목 · 무카드 · 라이트/다크 전환.
- [ ] **Step 3: Commit** — `feat(serve): CSS 토큰 · 세리프 활자 · 다크 기반`.

### Task 5: 레이아웃 헤더 · 사이드바 재구성

**Files:**
- Rewrite: `src/bullet_in/serve/templates/_layout.html.j2`
- Modify: `src/bullet_in/serve/render.py` (facet 항목에 `data-tier` 내보내기 · 스펙1 §7.2)

**Deliverable:**
- 헤더 재구성 · 상단 단계 탭 바 제거 (사이드바와 중복 · 스펙1 §7) · `일정` 내비 제거 · `소개` → `about.html` (스펙1 §10).
- 이모지 테마 아이콘 (`🌙`) → 인라인 SVG · 첫 페인트 전 다크 무깜빡임 인라인 스크립트 (스펙1 §4.3).
- 사이드바 순서 = 팀 → 영입 단계 → 공신력 → 소스 → 기자 (스펙1 §7) · 단계 · 공신력 기본 펼침 · 소스 · 기자 기본 접힘.
- 공신력 = 독자 라벨 · `전체` 기본 선택 · 체크박스 다중 (스펙1 §7.1) · `scrollbar-gutter: stable` (§7).
- facet 소스 · 기자 항목마다 `data-tier` 출력 (등급 미상은 빈 값 · 스펙1 §7.2).
- 사이드바에 색 점 없음 — 라벨만 (스펙1 §5 말미).

- [ ] **Step 1: 템플릿 재작성 · render.py facet data-tier 추가.**
- [ ] **Step 2: 구조 확인** — `grep 'data-tier' site/index.html` · 단계 탭 바 부재 · `data-theme` 인라인 스크립트 확인.
- [ ] **Step 3: Commit** — `feat(serve): 헤더 · 사이드바 재구성 · 공신력 컨트롤 · data-tier`.

### Task 6: app.js — 소스 · 기자 OR 결합 · 공신력 연동

**Files:**
- Rewrite: `src/bullet_in/serve/static/app.js`

**Deliverable:**
- 필터 결합을 `(소스 OR 기자) AND 공신력 AND 단계 AND 검색` 으로 (스펙1 §8).
- 공신력 등급 선택 시 그 등급 소스 · 기자 자동 체크 + 접힌 그룹 자동 펼침 (`data-tier` 기준 · 스펙1 §7.2).
- 자동 체크 항목 개별 해제 가능 · 손대면 상태줄에 `직접 고름` (스펙1 §7.2).
- `전체` 토글 로직 (하나 고르면 전체 풀림 · 모두 풀면 전체 복귀 · §7.1).
- 다크 토글을 SVG 아이콘으로 (이모지 제거) · URL 계약 (`?outlet=&journalist=&tier=&stage=`) 유지 · 상태줄 조건 개수 갱신 (스펙1 §8).

- [ ] **Step 1: OR 결합 · 공신력 연동 · 자동 펼침 구현.**
- [ ] **Step 2: 브라우저 검증** — 공신력 최상 선택 → The Athletic · David Ornstein · Sami Mokbel 체크 · 하나 해제 → `직접 고름` (스펙1 §17). VM 재렌더 데이터로 확인.
- [ ] **Step 3: Commit** — `feat(serve): 소스 · 기자 OR 결합 · 공신력 연동 자동 펼침`.

### Task 7: 인덱스 — 톱스토리 밴드 · 위계 · 날짜 목록 (평면)

**Files:**
- Rewrite: `src/bullet_in/serve/templates/index.html.j2`
- Modify: `src/bullet_in/serve/render.py` (`render_index` 가 톱스토리 · 날짜 그룹 · 위계 채널을 넘김)
- Modify: `src/bullet_in/serve/static/style.css` (밴드 · 2열 가로형 · 위계 채널)

**Deliverable:**
- 톱스토리 밴드 — 리드 1 (21:9 · 세리프 28px · 리드문 · 언론사 · 공신력 · 시각) + 주요 소식 4 (88px 3:2 · 두 줄 제목) (스펙1 §6.1).
- 최신 소식 = 2열 가로형 (132px 3:2 썸네일 · 제목 2 · 요약 2 · 메타 1) · 항목 사이 얇은 괘선 (스펙1 §6.2).
- 날짜 구분 (오늘 · 어제 · `7월 19일 (일)` · 건수) · 섹션 제목 오른쪽 `KST 기준` (스펙1 §6.2).
- 위계 채널 (스펙2 §3.1) — 제목 급수 · 색 · 요약 유무 · 출처 점 · 등급 클래스가 `--tone` · `--dotf` 만 세팅.
- 상위 두 등급만 배경 음영 (`.item` 범위 한정 · 다크 `#252220` / 레드 14%) (스펙2 §3.2).
- 하위 등급 요약문은 마크업에서 제외 (CSS 숨김 아님 · 스펙2 §3.1).
- 밴드 리드 · 주요 소식은 사건 dedup 없이 Task 3 결과로 채운다 (Phase 2 에서 dedup 얹음).

- [ ] **Step 1: render_index 확장 · index 템플릿 · CSS 작성.**
- [ ] **Step 2: 확인** — 밴드 · 날짜 구분 · 상위 두 등급 배경 (밴드 메타 줄에 안 샘) · 라이트/다크.
- [ ] **Step 3: Commit** — `feat(serve): 톱스토리 밴드 · 공신력 위계 · 날짜 묶음 목록`.

### Task 8: 상세 페이지

**Files:**
- Rewrite: `src/bullet_in/serve/templates/detail.html.j2`
- Modify: `src/bullet_in/serve/static/style.css` · `src/bullet_in/serve/render.py` (원제 · 메타 그리드용 뷰모델)

**Deliverable (스펙1 §9 배치 순서):**
1. 목록 링크 · 2. 단계 배지 · 3. 제목 세리프 36px · 4. 원문 제목 병기 (회색 · `title_original`) · 5. 리드문 · 6. 메타 그리드 (언론사 · 기자 · 공신력 · 발행일) · 7. 자동 번역 고지 (스펙1 §9 문구) · 8. 히어로 · 9. 핵심 요약 (붉은 상단 괘선 · `자동 생성`) · 10. 본문 17px/1.88 · 11. 원문 박스 (언론사 · 기자 · 날짜 · 원문 링크 버튼) · 12. 함께 볼 소식 · 13. 저작권 · 번역 안내 푸터.
- §9.1 라운드업 단신 재작성 — `gossip_itemize()` 판정 로직 무수정 · `{% elif b.type == 'item' %}` 분기 유지 · 시각만 좌측 2px 괘선 + 들여쓰기 · 출처는 알약 배지 대신 작은 회색 글자 (`--navy` · `--chip` 옛 토큰 제거 · 새 토큰).
- `excerpt-note` 블록은 자리만 유지 (스펙1 §15).

- [ ] **Step 1: detail 템플릿 · CSS · 원제 뷰모델 작성.**
- [ ] **Step 2: 확인** — 원제 병기 · 메타 그리드 · 번역 고지 · 원문 박스 · 가십 상세는 단신 괘선.
- [ ] **Step 3: Commit** — `feat(serve): 상세 페이지 — 원제 병기 · 메타 그리드 · 원문 박스`.

### Task 9: 소개 페이지 · 내비게이션

**Files:**
- Create: `src/bullet_in/serve/templates/about.html.j2`
- Modify: `src/bullet_in/serve/render.py` (`render_about()` · `write_site` 가 `about.html` 생성)

**Deliverable (스펙1 §10):**
- `render_about() -> str` · `write_site` 가 `about.html` 을 낸다.
- 담을 내용 — 서비스 목적 · 소스 구성 · 공신력 등급 체계 · 자동 번역 고지 · 저작권 정책.
- 인덱스 · 상세 하단에도 저작권 · 자동 번역 한 문단 요약.

- [ ] **Step 1: about 템플릿 · render_about · write_site 연결.**
- [ ] **Step 2: 확인** — `site/about.html` 생성 · 내비 `소개` 링크 작동 · `일정` 부재.
- [ ] **Step 3: Commit** — `feat(serve): 소개 페이지 신설 · 내비 정리`.

---

## Phase 2 — 사건 묶음 (선수 사전 의존 · 나중)

### Task 10: 선수 사전 로드 · 구단 검출 · 전환어 주인공

**Files:**
- Modify: `src/bullet_in/serve/render.py`
- Test: `tests/serve/test_render_redesign.py`

**Interfaces:**
- Produces:
`load_player_names(path) -> list[str]` — `name_map.yaml` 의 `names:` 키 (정규형).
`club_in_title(first_clause: str, club_map) -> str | None` — 제목 첫 절의 비-아스날 구단 정규형.
`protagonist(title: str, players: list[str]) -> str | None` — 전환어 규칙 (스펙2 §4.3).
- Consumes: `config/name_map.yaml` · `config/club_map.yaml`.

- [ ] **Step 1: 실패 테스트**

```python
from bullet_in.serve import render as R

PLAYERS = ["로저스", "디오망데", "트로사르"]

def test_protagonist_after_transition_word():
    # '놓친' 뒤 선수가 주인공 (스펙2 §4.3)
    assert R.protagonist("아스날, 로저스 놓친 후 디오망데 측과 접촉", PLAYERS) == "디오망데"

def test_protagonist_no_transition_uses_first():
    assert R.protagonist("아스날, 트로사르 재계약 임박", PLAYERS) == "트로사르"

def test_protagonist_transition_without_dict_player_keeps_first():
    assert R.protagonist("아스날, 로저스 놓친 후 다른 선수 물색", PLAYERS) == "로저스"
```

- [ ] **Step 2: 실패 확인** · **Step 3: 구현** (스펙2 §4.2 부분 일치 · §4.3 전환어 목록 `놓친 · 대신 · 대체 · 무산 · 결렬 · 실패 · 포기 · 떠난`) · **Step 4: 통과 확인**.
- [ ] **Step 5: Commit** — `feat(serve): 선수 사전 로드 · 구단 검출 · 전환어 주인공 판별`.

### Task 11: 사건 클러스터

**Files:**
- Modify: `src/bullet_in/serve/render.py` · Test: `tests/serve/test_render_redesign.py`

**Interfaces:**
- Produces:
`cluster_events(articles, players) -> list[dict]` — `[{"key": 선수명, "articles": [...]}]` · 날짜 경계 없음 (스펙2 §4.1) · 주인공 기준 (스펙2 §4.2 사전 1순위).
- Consumes: `protagonist` (Task 10).

- [ ] **Step 1: 실패 테스트** — 같은 주인공 기사가 한 묶음으로 · 주인공 없는 기사는 단독 묶음.
- [ ] **Step 2: 실패 확인** · **Step 3: 구현** · **Step 4: 통과 확인**.
- [ ] **Step 5: Commit** — `feat(serve): 사건 클러스터 — 주인공 기준 · 날짜 무경계`.

### Task 12: 대표 선정 (6순위)

**Files:**
- Modify: `src/bullet_in/serve/render.py` · Test: `tests/serve/test_render_redesign.py`

**Interfaces:**
- Produces:
`pick_representative(articles) -> dict` — 6순위 (스펙2 §6.1) — 구단 공식 → 최하 제외 → 아스날 주어 (제목 시작 1순위 · 본문 언급 2순위 · 없음 3순위) → 최신 (`published_at`) → 공신력 → 단계.
- Consumes: `arsenal_subject` (Task 3) · `pick_top_stories` 정렬과 공유.

- [ ] **Step 1: 실패 테스트**

```python
from datetime import datetime
from bullet_in.serve import render as R

def _r(**k):
    b = {"title_ko": "제목", "tier": 2.0, "transfer_stage": "rumour", "body_ko": "",
         "published_at": datetime(2026, 7, 20)}; b.update(k); return b

def test_lowest_tier_cannot_represent_when_higher_exists():
    afc = _r(tier=4.0, title_ko="아스날, 로저스 영입 추진")   # 최하 · 아스날 주어
    sky = _r(tier=1.0, title_ko="첼시, 로저스 영입 합의")
    rep = R.pick_representative([afc, sky])
    assert rep is sky        # 최하 제외 가드 (스펙2 §6.1 2번 · 로저스 사고)

def test_official_always_represents():
    off = _r(tier=0.0, title_ko="첼시, 로저스 영입 공식 발표")
    ars = _r(tier=1.5, title_ko="아스날, 로저스 관심")
    assert R.pick_representative([off, ars]) is off
```

- [ ] **Step 2: 실패 확인** · **Step 3: 구현** · **Step 4: 통과 확인**.
- [ ] **Step 5: Commit** — `feat(serve): 대표 선정 6순위 — 최하 제외 · 아스날 주어 우선`.

### Task 13: 결말 카드 · 관련 보도 갈래

**Files:**
- Modify: `src/bullet_in/serve/render.py` · Test: `tests/serve/test_render_redesign.py`

**Interfaces:**
- Produces:
`ending_card(cluster) -> dict | None` — 결말 판정 (스펙2 §6.2 첫 절 · 단계 협상 중 이상 · 제목 비-아스날 시작 · 행선지 구단).
`related_reports(cluster, rep, ending) -> dict` — `{"arsenal": [...], "other": [...]}` · 각 갈래 시간순 · 결말 있으면 다른 구단 갈래 위 (스펙2 §6.3).
- Consumes: `club_in_title` · `pick_representative`.

- [ ] **Step 1: 실패 테스트** — 결말 판정 (첫 절 한정 · `…` 뒤 무시) · 갈래 분리 · 결말 시 다른 구단 위 · 갈래 내 시간순.
- [ ] **Step 2: 실패 확인** · **Step 3: 구현** · **Step 4: 통과 확인**.
- [ ] **Step 5: Commit** — `feat(serve): 결말 카드 · 관련 보도 관점 갈래 · 시간순`.

### Task 14: 가십 분리 · 톱스토리 사건 dedup

**Files:**
- Modify: `src/bullet_in/serve/render.py` · Test: `tests/serve/test_render_redesign.py`

**Interfaces:**
- Produces:
`is_gossip_cluster(cluster) -> bool` — 묶음의 모든 기사가 최하 등급일 때만 (스펙2 §7.1).
`pick_top_stories(...)` 확장 — 주요 소식 4건이 서로 다른 사건이도록 (스펙2 §5 · 클러스터 key dedup).
- Consumes: `cluster_events` · `pick_representative`.

- [ ] **Step 1: 실패 테스트**

```python
from datetime import datetime
from bullet_in.serve import render as R

def _r(**k):
    b = {"title_ko": "제목", "tier": 4.0, "transfer_stage": "rumour",
         "published_at": datetime(2026, 7, 20)}; b.update(k); return b

def test_gossip_only_when_all_lowest():
    assert R.is_gossip_cluster({"articles": [_r(), _r()]}) is True
    assert R.is_gossip_cluster({"articles": [_r(), _r(tier=1.5)]}) is False   # 상위 섞이면 본 목록
```

- [ ] **Step 2: 실패 확인** · **Step 3: 구현** (톱 밴드 주요 소식은 사건 key 로 dedup) · **Step 4: 통과 확인**.
- [ ] **Step 5: Commit** — `feat(serve): 가십 분리 · 톱스토리 사건 dedup`.

### Task 15: 인덱스 사건 블록 · 다단 · 가십 구역

**Files:**
- Modify: `src/bullet_in/serve/templates/index.html.j2` · `src/bullet_in/serve/static/style.css` · `src/bullet_in/serve/render.py` (`render_index` 가 클러스터 · 결말 · 갈래 · 가십 구역을 넘김)

**Deliverable:**
- 최신 소식을 사건 블록으로 (대표 카드 + 결말 줄 + 접히는 관련 보도) (스펙2 §5.2 · §5.3).
- 날짜 구분선 건수 = `묶음 N개 · 보도 M건` (스펙2 §4.1).
- 신문 다단 (`column-count: 2`) · 사건 블록 분리 금지 (`break-inside: avoid` + `-webkit-column-break-inside`) · 그리드 항목 `min-width: 0` (스펙2 §8).
- 묶음 수 적으면 1열 폴백 (스펙2 §8) · 목록 썸네일 칸 제거 (밴드는 유지 · 스펙2 §8).
- 결말 행선지 칩 = 무채색 테두리 (`.dest` · 스펙2 §5.2) · 관련 보도 이름표 상황별 (`{구단}행 관련` · `아스날 쪽 보도` · `영입 경쟁` · 스펙2 §5.3).
- 가십 구역 = 3열 압축 · 좌측 괘선 없음 · 단계 배지 유지 · 헤더 `묶음 N개` + 각주 · 이름 `가십` (스펙2 §7).

- [ ] **Step 1: render_index 확장 · 사건 블록 · 다단 · 가십 CSS 작성.**
- [ ] **Step 2: 확인** — VM 재렌더 → 밴드 4건이 다 다른 사건 · 로저스 대표 = 아스날 주어 · 결말 줄 첼시 · 디오망데 전환어 · 다단 미분리 · 폭 1440/1200/1040/390 (스펙2 §13).
- [ ] **Step 3: Commit** — `feat(serve): 사건 블록 · 신문 다단 · 가십 구역`.

---

## Phase 3 — 검증

### Task 16: 전체 검증 · 재렌더 · 스크린샷

- [ ] **Step 1: 전체 테스트** — Run: `uv run pytest -q` · Expected: 신규 테스트 포함 전건 통과 · 기준선 515 + 신규 · 1 skipped.
- [ ] **Step 2: VM 재렌더** — 런북 `docs/runbook/2026-07-22-mockup-rerender-from-vm.md` — VM articles → 로컬 `bulletin_mock` → `MARIADB_URL=…/bulletin_mock` 로 렌더 전용 패스.
- [ ] **Step 3: 스크린샷** — 폭 1440 · 1200 · 1040 · 390 × 라이트 · 다크 · 인덱스 · 상세 (스펙1 §17 · 스펙2 §13).
- [ ] **Step 4: 합격 기준** — 밴드 4건 다른 사건 · 대표/결말/전환어 · 공신력 연동 조작 · 썸네일 균일 · 다크 배지 대비.
- [ ] **Step 5: Commit** — 스크린샷을 `docs/assets/` 또는 스펙 assets 로 (커밋 메시지 `docs(serve): 개편 검증 캡처`).

---

## Phase 4 — PR

### Task 17: 리베이스 · humanize · push · PR

- [ ] **Step 1: 최신 main 리베이스 후 재렌더 확인** (스펙1 §18).
- [ ] **Step 2: about 산문 · PR 본문 humanize-korean fast 점검** (CLAUDE.md 자연스러운 한국어 규칙).
- [ ] **Step 3: push + PR 생성** (`--body-file` · 7섹션 · Claude 서명 금지 · 머지는 사용자 · [[pr-merge-by-user]]).
- [ ] **Step 4: PR 본문에 검증 캡처 · 기준선 첨부.**

---

## Self-Review — 스펙 커버리지

- 스펙1 §4 토큰 · 활자 · 다크 → Task 4 · §5 단계 표시 → Task 1 · §6 인덱스 → Task 7 · §7 사이드바 → Task 5 · §7.2 연동 → Task 6 · §8 OR 결합 → Task 6 · §9 상세 → Task 8 · §9.1 라운드업 → Task 8 · §10 소개 → Task 9 · §11 이미지 → Task 4 · 7 · §12 시각 → Task 2 · §14 파일 → File Structure · §15 소유권 → Global Constraints · §16.1 arsenal.com → Task 3 (배제 미도입).
- 스펙2 §3 위계 → Task 7 · §4 묶음 → Task 10 · 11 · §5 톱스토리 → Task 3 · 14 · §6 대표 → Task 12 · §6.2 결말 → Task 13 · §6.3 관련 보도 → Task 13 · §7 가십 → Task 14 · 15 · §8 레이아웃 → Task 15 · §11 체크박스 반전 → Task 4 · §11.1 번역 대기 → Task 2 · §11.2 트윗 제목 → 재렌더 후 관찰 (Task 16).
- 폰트 → Task 0 · 소유권 경계 보존 (`gossip_itemize` · `bbc_gossip` · `serving_mode` · `excerpt-note`) → Task 8 · Global Constraints.
