# 정적 사이트 serve 변경의 브라우저 검증 런북 (2026-07-19)

facet tier 정렬 트랙 ( PR #56 ) 에서 pytest · 코드 리뷰 · 노드 시뮬레이션이 셋 다 놓치고 실브라우저만 잡은 결함 ( `docs/troubleshooting/2026-07-16-hidden-attr-defeated-by-author-css.md` ) 이 나왔다.
그 결함이 드러낸 절차를 재사용 가능한 형태로 남긴다 — `app.js` · `style.css` · 템플릿 상호작용을 바꾼 serve 트랙은 머지 전 이 절차를 밟는다.

## 1. 언제 이 런북을 쓰나

- `src/bullet_in/serve/static/app.js` · `style.css` 변경
- `_layout.html.j2` 등 상호작용 요소 ( 토글 · 더보기 · 필터 체크박스 ) 를 건드리는 템플릿 변경
- `hidden` · `display` · `classList` · `history` 조작이 얽히는 변경

**pytest 는 이 층을 검증하지 못한다.**
`tests/test_serve_render.py` 는 `app.js` · `style.css` 를 **문자열로만** 검사한다 ( `assert "morestage" in js` ).
식별자의 존재를 증명할 뿐 실동작은 아무것도 보장하지 않는다.
브라우저 검증이 이 층의 유일한 행동 게이트다.

## 2. 절차

### 2.1. 실데이터로 사이트 생성

```bash
set -a; source .env; set +a          # 이 프로젝트는 dotenv 미사용 — 필수
uv run python -m bullet_in.run --concurrency 8     # 또는 write_site 직접 호출로 site/ 재생성
```

`site/index.html` 이 최신 코드로 렌더됐는지 확인한다.
정적 자산 ( `style.css` · `app.js` ) 은 `write_site` 가 복사하므로, 소스만 고치고 사이트를 안 지으면 옛 자산이 남는다.

### 2.2. 생성물 정합 ( 브라우저 없이 선검사 )

브라우저를 띄우기 전에 문자열 계약부터 본다.

```bash
uv run python - <<'PY'
import re
s = open("site/index.html", encoding="utf-8").read()
print("doctype 첫 문자 :", s.startswith("<!doctype html>"))
cards = set(re.findall(r'data-tier="([^"]*)"', s))
facet = set(re.findall(r'data-group="tier" data-value="([^"]*)"', s))
print("카드 ⊆ 필터    :", cards <= facet, "| 고아:", sorted(cards - facet) or "없음")
PY
```

- **doctype 첫 문자** — 매크로를 `{% endmacro -%}` 로 안 닫으면 앞에 개행이 샌다.
- **카드 `data-tier` ⊆ 필터 `data-value`** — 어긋나면 그 카드는 필터로 걸러낼 수 없는 고아가 된다 ( 문자열 동등 비교 계약 ).

### 2.3. 실브라우저 상호작용 검증

`site/` 를 로컬 http 로 띄우고 Playwright 로 구동한다.
**`file://` 이 아니라 http 여야 한다** — `history.replaceState` 등이 `file://` 에서 다르게 동작한다.
**`uv run python` 으로 실행한다** — 시스템 python3 은 브라우저 미설치.

```python
import http.server, socketserver, threading, functools, pathlib
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path("site")
socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(("127.0.0.1", 8731),
      functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
with sync_playwright() as p:
    pg = p.chromium.launch().new_page()
    pg.goto("http://127.0.0.1:8731/index.html")
    # ... 클릭 · 필터 · URL 왕복 검증 ...
srv.shutdown()
```

검증할 시나리오 ( facet 트랙 기준, 상호작용 UI 마다 조정 ):

- **초기 노출** — 숨어야 할 요소가 실제로 안 보이는가 ( `is_visible()` · `offsetParent` )
- **클릭 전개** — 한 번 클릭이 정확히 한 단계만 진행하는가
- **완전 전개 · 소진** — 끝까지 열면 버튼이 남지 않는가
- **URL 왕복** — `?tier=1.5` 로 재방문 시 체크 상태 · 필터 결과가 복원되는가
- **독립성** — 한 필터를 열어도 다른 필터는 그대로인가

### 2.4. 회귀 탐지 실증 ( 강한 검증 )

테스트가 통과한다는 사실은 그 테스트가 계약을 지킨다는 뜻이 아니다.
새로 추가한 회귀 테스트는 **일부러 깨보고 빨간불을 확인**한다.

```bash
# 예: _outlet_tier 폴백을 return None 으로 임시 변경 → 그 테스트만 FAIL 하는가
# 확인 후 반드시 git checkout 으로 원복 · git diff src/ 가 비어야 커밋
```

facet 트랙에서 이 절차가 **무방비 테스트 3건**을 걸러냈다.
`_outlet_tier` 폴백은 지워도 377 passed 로 통과를 유지했다 ( 존재 이유를 안 지킴 ).

## 3. 자주 밟는 함정

- **`hidden` 이 안 먹음** — 요소에 `display` 를 지정하면 브라우저 기본 `[hidden]{display:none}` 을 이긴다.
  `.morebtn[hidden]{display:none}` 처럼 짝 규칙을 명시해야 한다.
  증상이 "일부만 동작" ( 단계는 숨는데 버튼은 안 숨음 ) 이면 두 요소의 CSS 차이를 먼저 본다.
  상세: `docs/troubleshooting/2026-07-16-hidden-attr-defeated-by-author-css.md`.
- **옛 정적 자산 잔존** — 소스만 고치고 사이트를 안 지으면 `site/style.css` · `site/app.js` 가 옛 버전이다.
  검증 전 `write_site` 재실행 또는 자산 복사를 확인한다.
- **`file://` 검증** — 실사용 경로는 `open site/index.html` 이지만, JS 왕복 검증은 http 서버로 띄운다.

## 4. 남은 과제

- **CI 상설화** — 이 절차는 현재 수동이다.
  serve 변경의 행동 게이트가 사람 손에 달려 있어, 라이브 검증 태스크를 생략하면 결함이 통과한다.
  Playwright 하네스를 CI 에 상설화하는 것이 근본 해법이다 ( 별도 트랙 ).

## 5. 참고

- 트러블슈팅: `docs/troubleshooting/2026-07-16-hidden-attr-defeated-by-author-css.md`
- 설계: `docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md` §7
- PR: #56 ( facet tier 정렬 )
