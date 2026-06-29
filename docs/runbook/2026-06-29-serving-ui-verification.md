# 런북 — 서빙 UI 검증 (렌더 구조 + 브라우저 인터랙션)

정적 서빙 UI(`site/`)를 머지 전 검증한다. **단위 테스트는 Jinja 렌더 결과 일부만 모킹으로 보고, 클라이언트 JS(검색 · 필터 · 정렬 · 테마 토글)와 시각 레이아웃은 못 잡는다.** 셀렉터 드리프트를 어댑터 단독 `fetch()`로 라이브 검증하듯 (`docs/troubleshooting/2026-06-12-live-source-selector-drift.md`), 서빙도 실제 렌더 출력 + 실 브라우저 구동으로 확인한다.

## 언제 쓰나

- `serve/render.py` · 템플릿 · `static/{style.css,app.js}` 변경 후.
- 카드 `data-*` 계약 · 슬라이딩 윈도우 · outlet/이미지 폴백 · 검색/필터/정렬/테마 동작을 머지 전 확인할 때.

## 1단계 — 픽스처로 `site/` 생성

엣지를 모두 덮는 10건 픽스처(이미지 유/무 · `outlet` NULL=직접 EN 소스 · `journalist` 유/무 · `tier` 0–4 · 다문단 본문)로 사이트를 만든다. DB 불필요.

```bash
cd <repo>
uv run python - <<'PY'
from datetime import datetime, timedelta
from bullet_in.serve.render import write_site
now = datetime(2026, 6, 29, 12, 0, 0)
sources = {"bbc_sport": {"display_name": "BBC Sport"},
           "arsenal_official": {"display_name": "Arsenal.com"}}
rows = []
for i in range(10):
    rows.append(dict(
        content_hash=f"hash{i}", url="https://example.com/a%d" % i,
        source_id="bbc_sport" if i % 2 else "arsenal_official",
        title_original="Arsenal player %d" % i,
        title_ko="아스날, 선수 %d 영입 임박" % i,
        summary_ko="한 줄 요약 %d" % i,
        summary3_ko="첫째 줄 %d\n둘째 줄\n셋째 줄" % i,
        body_ko="첫 문단 본문입니다.\n둘째 문단 본문입니다.\n셋째 문단.",
        image_url=None if i % 3 == 0 else "https://picsum.photos/seed/%d/800/450" % i,
        outlet=None if i % 2 else "Arsenal Official",   # 홀수 i = outlet NULL → display_name 폴백 확인
        journalist="기자 %d" % i if i % 4 == 0 else None,
        team="arsenal", tier=i % 5, confidence_score=round(1 - (i % 5) / 4, 3),
        published_at=now - timedelta(hours=i)))
write_site(rows, sources, "site", now=now)
print("wrote site/")
PY
```

> `site/`는 빌드 산출물 → `.gitignore`에 포함, 커밋하지 않는다.

## 2단계 — 렌더 출력 구조 검증 (grep)

실제 HTML을 전수 확인한다. 기대값은 위 픽스처 기준.

스크랩 마크업 이스케이프 자체는 단위 테스트(`tests/test_serve_render.py::test_index_prefers_korean_title_and_escapes`)가 잠근다. 아래 grep은 구조 · 폴백 · 카운트 확인용.

```bash
cd site
# 인덱스
grep -o 'href="style.css"' index.html        # href="style.css"  (인덱스 root="")
grep -c 'PHOTO · 16:9' index.html            # 4  (image_url 없는 카드 플레이스홀더: i=0,3,6,9)
grep -o 'Arsenal <span class="ct">[0-9]*'    # Arsenal …10  (facet 카운트)
grep -o 'data-group="outlet" data-value="[^"]*"' index.html | sort -u
#   "Arsenal Official" / "BBC Sport"  (NULL outlet → display_name 폴백)
grep -c 'opt disabled' index.html            # 8  (영입 단계 4 + 타 구단 4 비활성 자리)

# 상세 (중앙 글 hash5)
grep -o 'href="../style.css"' article/hash5.html   # ../style.css  (상세 root="../")
grep -c 'class="mt"' article/hash5.html            # 5  (이웃 5목록)
grep -c 'nowtag">지금' article/hash5.html          # 1  (현재 글 배지 정확히 1개)
grep -o 'Arsenal <span class="ct">[0-9]*' article/hash5.html  # Arsenal …10  (상세 사이드바도 실제 facet)
```

슬라이딩 윈도우 가장자리(과거 끝 `hash9`)는 이웃이 선수 5·6·7·8·9, 현재=9로 끝에서 5개 유지되는지 확인.

## 3단계 — 실 브라우저 인터랙션 (Playwright)

프로젝트에 이미 설치된 Playwright(chromium)로 검색 · 필터 · 정렬 · 테마를 **실제 구동**한다(클릭/입력 → DOM 반영 단언). 스크린샷도 함께 캡처. 아래 스니펫을 임시 파일에 저장해 `uv run python <file>`로 실행한다(커밋하지 않는다).

검증 항목(전부 PASS여야 함):

| 항목 | 기대 |
|---|---|
| 초기 카드 | 10개 표시 |
| 테마 토글 | `html[data-theme]` light → dark, 버튼 🌙 → ☀️, `localStorage.theme=dark` |
| 테마 영속 | 새로고침 후 dark 유지 |
| 검색 `선수 3` | 1건만, 비우면 10건 복원 |
| 필터 tier 0 + 적용 | 2건(선수 0 · 5), 상태줄 `적용됨 · 조건 1개 · 2건` |
| 초기화 | 전체 복원 + 체크 해제 |
| 정렬 신뢰도순 | `data-confidence` 내림차순 |
| 정렬 최신순 | 가장 최근(선수 0) 선두 |

핵심 스니펫(전체 스크립트는 길어 요지만):

```python
from pathlib import Path
from playwright.sync_api import sync_playwright

INDEX = Path("site/index.html").resolve().as_uri()
def visible(pg):
    return pg.eval_on_selector_all(".grid .card",
        "els => els.filter(e => e.style.display !== 'none').map(e => e.querySelector('h2').textContent.trim())")

with sync_playwright() as p:
    pg = p.chromium.launch().new_page(viewport={"width": 1280, "height": 900})
    pg.goto(INDEX)
    assert len(visible(pg)) == 10
    pg.click("#themeBtn")                                    # 테마 토글
    assert pg.eval_on_selector("html", "e=>e.getAttribute('data-theme')") == "dark"
    pg.fill("#q", "선수 3")                                  # 실시간 검색
    assert visible(pg) == ["아스날, 선수 3 영입 임박"]
    pg.fill("#q", "")
    pg.check("input[data-group='tier'][data-value='0']"); pg.click("#applyBtn")  # 필터
    assert sorted(visible(pg)) == ["아스날, 선수 0 영입 임박", "아스날, 선수 5 영입 임박"]
    pg.click("#resetBtn")                                    # 초기화
    assert len(visible(pg)) == 10
    pg.screenshot(path="/tmp/index_light.png")
```

> **스크린샷 함정**: 테마 토글 직후 캡처하면 `body{transition:… color .2s}` 트랜지션 중간이 잡혀 글자가 흐릿하게 보인다.
> 시각 확인용 스크린샷은 토글 후 `pg.wait_for_timeout(400)` 뒤에 찍는다.
> 대비 진단은 스크린샷 대신 computed color로 확정: `getComputedStyle(card_h2).color` 가 다크의 `--ink`(`rgb(238,241,246)`)인지 확인.

## 기대 결과

- 2단계 grep 전부 기대값 일치.
- 3단계 Playwright 항목 전부 PASS.
- 단위 + 렌더 테스트: `uv run pytest -q` → 통합 skip 외 전부 PASS.

## 참고

- 계획 · spec: `docs/superpowers/plans/2026-06-29-tier2a-serving-ui.md`, `docs/superpowers/specs/2026-06-29-tier2a-detail-page-design.md` (§7)
- 인라인 CSS 인젝션 함정: `docs/troubleshooting/2026-06-29-jinja-autoescape-css-context-injection.md`
- 라이브 검증 철학(모킹이 못 잡는 드리프트): `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`
