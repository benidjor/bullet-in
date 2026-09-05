# 런북 — README · 슬라이드용 라이브 화면 캡처

배포된 사이트의 화면을 README 나 슬라이드에 넣을 크기로 찍는 절차다.
2026-09-06 README 개편 (#473) 에서 전체 기사 · 행동 지표 · 수집 현황 셋을 이 절차로 찍었고 그때 밟은 함정 넷을 함께 적는다.

## 1. 언제 찍나

머지 뒤 바로 찍지 않는다.
사이트는 다음 정각 회차 (KST 0 · 3 · 6 · 9 · 12 · 15 · 18 · 21시) 의 `advance` 가 코드를 받고 `publish` 가 그린 뒤에 바뀐다.
정각 5분 뒤에 먼저 배포를 확인한다.

```bash
curl -sL https://bullet-in.pages.dev/ops.html | grep -c 'class="sec"'        # 10
curl -sL https://bullet-in.pages.dev/behavior.html | grep -c 'class="sec"'   # 9
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cat ~/bullet-in/state/deploy.json'   # current 가 머지 커밋
```

`-L` 이 없으면 308 과 빈 응답이 오고 그 빈 결과가 「이상 없음」 으로 읽힌다 (`docs/troubleshooting/` 의 배포본 curl 함정).

## 2. 무엇으로 찍나

Playwright 의 Chromium 을 프로젝트 venv 에서 부른다.
Chrome 확장 (Chrome MCP) 의 스크린샷은 이 환경에서 `params.clip.scale` 역직렬화 오류로 깨진 적이 있어 쓰지 않는다.

venv 는 메인 체크아웃의 것을 쓴다.
문서 워크트리에서 `uv run` 을 치면 uv 가 새 venv 를 3.14 로 만든다 (저장소에 `.python-version` 이 없다).
그 venv 는 지우고 (`rm -rf .venv`) 메인에서 돈다.

## 3. 절차

기존 캡처 (`docs/assets/serving-page-live.png`) 가 1440 × 900 · 배율 1 이므로 같은 크기로 맞춘다.
대시보드는 전체 페이지가 4,700 에서 5,200px 이라 README 에 다 넣으면 읽히지 않는다.
위 1,500px 만 잘라 넣고 링크로 라이브를 가리킨다.

```python
from playwright.sync_api import sync_playwright
OUT = "<워크트리>/docs/assets"
BASE = "https://bullet-in.pages.dev"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="ko-KR")
    pg.goto(f"{BASE}/all.html", wait_until="load"); pg.wait_for_timeout(3500)
    pg.screenshot(path=f"{OUT}/serving-page-live.png")                     # 뷰포트만
    for name, path in (("dashboard-behavior-live.png", "/behavior.html"), ("dashboard-ops-live.png", "/ops.html")):
        pg.goto(f"{BASE}{path}", wait_until="load"); pg.wait_for_timeout(1200)
        pg.screenshot(path=f"{OUT}/{name}", full_page=True, clip={"x": 0, "y": 0, "width": 1440, "height": 1500})
    b.close()
```

찍은 파일은 `Read` 나 뷰어로 한 번 눈으로 본다.
크기는 `file <png>` 로 확인한다.

## 4. 함정 넷

### 4.1. `/articles.html` 은 소프트 404 다

Cloudflare Pages 는 없는 경로에 200 으로 첫 화면을 돌려준다.
`/articles.html` 을 찍으면 홈이 찍히고 이미지 수까지 홈과 같아 눈치채기 어렵다.
진짜 목록 페이지는 `all.html` 이다.
경로는 첫 화면의 `href` 를 세어 확인한다.

```bash
curl -sL https://bullet-in.pages.dev/ | grep -o 'href="[a-z]*\.html"' | sort | uniq -c | sort -rn | head
```

### 4.2. 홈 대표 기사 사진이 헤드리스에서 빈 자리로 나온다

홈의 대표 기사 (`article.lead`) 와 주요 소식 카드는 구단 공식 기사라 사진이 `assets.arsenal.com` 에서 온다.
헤드리스 Chromium 에서 그 요청이 `net::ERR_BLOCKED_BY_ORB` 로 막혀 (응답이 이미지가 아니어서 Chrome 이 버린다) 사진 자리가 비고 사이드 카드가 좁게 접힌다.
보통 Chrome 의 UA 문자열을 넣어도 같다.
실제 브라우저에서도 같은지는 2026-09-06 시점에 미확인이다.
그래서 README 첫 캡처는 홈 대신 `all.html` 로 찍었다 (다른 매체 이미지는 뜬다).

### 4.3. 「깨진 이미지 수」 는 뜻이 없다

`document.images` 가운데 `naturalWidth == 0` 인 것을 세면 `all.html` 에서 864 중 853 이 나온다.
그 대부분은 뷰포트 밖의 lazy 이미지라 아직 요청도 안 된 것이다.
깨진 것을 세려면 `requestfailed` 이벤트의 호스트를 모은다.
그러면 `assets.arsenal.com` 하나만 남는다.

### 4.4. `networkidle` 을 기다리면 안 끝날 수 있다

GA4 수집 요청과 lazy 이미지가 이어져 `wait_until="networkidle"` 이 늦어진다.
`load` 뒤 고정 대기 (1 에서 3초) 가 안정적이다.
대시보드는 정적 SVG 라 1초면 충분하다.

## 5. 뒤처리

캡처 파일 이름은 옛 문서가 가리키는 것을 바꾸지 않는다 (`serving-page-live.png` 는 내용만 갈았다).
새 이름은 화면 이름을 그대로 쓴다 (`dashboard-behavior-live.png` · `dashboard-ops-live.png`).
슬라이드가 같은 캡처를 쓰면 같은 시각의 것을 쓰고 캡처 시각을 캡션에 적는다.
