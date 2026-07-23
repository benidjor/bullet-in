# 프리뷰 CSS 캐시가 남아 코드가 멀쩡한데 버그로 오진한 사례 (2026-07-23)

UI 개편 리뷰 중 히어로 밴드가 브라우저 폭 끝까지 풀블리드로 나와 레이아웃 버그로 판단했으나, 실제 원인은 브라우저가 이전 `style.css` 를 캐시하고 있던 것이었다.
코드는 이미 옳았고, 진단에 한 차례 헛걸음을 했다.

## 1. 증상

- 밴드를 사이드바 위 전폭으로 올리며 `.bandwrap` 에 `max-width: var(--max)` (1180px) 를 줬는데, 넓은 화면에서 히어로만 폭 끝까지 퍼지고 topbar · 최신 소식은 1180px 로 중앙 정렬돼 어긋났다.
- 소스 CSS 파일에는 규칙이 분명히 있었다.

## 2. 왜 버그로 오해했나

- 규칙이 파일에 있으니 당연히 적용된 줄 알고, `.bandwrap` 의 폭 계산 · 부모 구조를 먼저 의심했다.
- 프리뷰를 여러 번 재렌더 · 재방문했는데도 그대로라, 캐시가 아니라 코드 문제라고 넘겨짚었다.

## 3. 실제 원인

- 로컬 프리뷰 서버 (`python -m http.server`) 는 `Cache-Control` 을 보내지 않는다.
- 브라우저가 `style.css` 를 메모리 캐시에서 재검증 없이 재사용해, `.bandwrap` 규칙이 없던 옛 CSS 로 페이지를 그렸다.
- 그래서 CSSOM 에 `.bandwrap` 규칙 자체가 없었고 (`max-width` computed = `none`), 파일에는 있었다.

## 4. 진단 방법 — 파일 · CSSOM · computed 를 갈라 본다

세 층을 따로 확인하면 캐시 문제인지 코드 문제인지 바로 갈린다.

- **파일** — `grep bandwrap style.css` 로 서빙 파일에 규칙이 있는지.
- **computed** — 브라우저에서 `getComputedStyle(el).maxWidth` 가 `none` 인지 (규칙이 안 먹은 신호).
- **CSSOM** — 로드된 스타일시트를 순회해 그 셀렉터 규칙이 실제로 파싱돼 있는지.
파일엔 있는데 CSSOM 엔 없으면 캐시 (또는 파싱 오류) 다.
- **캐시버스터 fetch** — `fetch('style.css?_=' + Date.now())` 로 파일을 직접 받아 규칙 유무를 확인하면 파일 자체는 최신임이 드러난다.

주의 — CSSOM 규칙을 훑을 때 `rule.style.maxWidth` 로 값 유무를 판단하면 `var()` 값에는 빈 문자열이 반환돼 오탐이 난다.
셀렉터 매칭은 `rule.selectorText` · `rule.cssText` 로 확인한다.

## 5. 확인 · 임시 해소

- 검증 중에는 링크를 캐시버스터로 갈아 끼워 최신 CSS 를 강제 로드하면 즉시 맞는 레이아웃이 확인된다.

```js
const old = document.querySelector('link[rel="stylesheet"]');
const link = document.createElement('link');
link.rel = 'stylesheet';
link.href = 'style.css?v=' + Date.now();
link.onload = () => old && old.remove();
document.head.appendChild(link);
```

- 사용자 화면에서는 하드 리로드 (`Cmd + Shift + R`) 로 캐시를 비운다.

## 6. 배포 함의 — 정적 호스팅은 캐시 무효화가 필요하다

- 이 문제는 로컬 프리뷰만의 일이 아니다.
- 정적 배포 (Cloudflare Pages 등) 에서도 배포 후 사용자 브라우저가 옛 `style.css` · `app.js` 를 계속 쓰면 개편이 안 보인다.
- 대응은 자산 URL 에 버전 · 해시를 붙이거나 (`style.abc123.css`), 짧은 `Cache-Control` 로 재검증을 강제하는 것이다.
- 지금 서빙은 자산 파일명이 고정 (`style.css` · `app.js`) 이라, 공개 전에 캐시 무효화 방식을 정해 두는 편이 안전하다.

## 7. 교훈

- 재렌더했는데 화면이 안 바뀌면 코드를 파기 전에 캐시부터 의심한다 (파일 · CSSOM · computed 세 층 대조).
- 파일에 규칙이 있는데 화면에 안 먹으면 십중팔구 캐시다.
- 정적 사이트는 파일명이 고정이면 캐시가 오래 남으니, 공개 전 자산 버저닝을 결정한다.
