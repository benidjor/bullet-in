# 새 화면이 공유 프런트엔드 전제를 깬다 (2026-08-03)

## 증상

선수 페이지를 붙이면서 기존 화면에는 없던 조합이 생겼고, 그 조합에서만 깨지는 것이 둘 나왔다.
둘 다 태스크별 리뷰 6회를 통과하고 **최종 전체 브랜치 리뷰에서 잡혔다.**

## 사례 1 · 선수 페이지에서 JavaScript 가 통째로 멈춘다

`app.js` 에 이런 분기가 있었다.

```javascript
const side = document.querySelector('.side');
const items = [...document.querySelectorAll('.daylist .item, .gossiplist .item')];
// ...
if (items.length) {                    // 인덱스
  side.addEventListener('change', ...);
}
```

선수 개별 페이지는 기사 목록을 `<div class="daylist plist">` 로 감싸므로 `items.length > 0` 이 된다.
동시에 필터 사이드바를 빼기 때문에 (`solo=true`) `side` 가 `null` 이다.
그래서 `side.addEventListener` 에서 `TypeError` 가 나고 **그 뒤 코드가 전부 실행되지 않는다.**

기존 화면 중에는 이 조합을 만드는 것이 없었다.

| 화면 | `.daylist .item` | `.side` | 결과 |
| --- | --- | --- | --- |
| 홈 · 전체 기사 | 있음 | 있음 | 정상 |
| 소개 | 없음 | 없음 | `items.length` 가 0 이라 통과 |
| 기사 상세 | 없음 | 있음 | `else if (side)` 로 빠짐 |
| **선수 페이지** | **있음** | **없음** | **널 참조** |

눈에 보이는 피해는 작았다.
카드는 서버 렌더이고 조회 기록 · 테마 토글은 파일 앞쪽이라 이미 등록된 뒤였다.
문제는 파일 뒤쪽이 죽는다는 것이고, 같은 브랜치가 파일 끝에 붙인 그룹 접기 핸들러가 정확히 그 자리에 있었다.
색인 페이지는 `.daylist` 가 없어 우연히 살아 있었을 뿐이다.

**고친 방법** — 조건에 널 검사를 더한 한 줄이다.

```javascript
if (items.length && side) {
```

## 사례 2 · 다크 모드에서만 배지가 안 읽힌다

새로 만든 이적 축 배지 여덟 개 중 둘 (`.t-indone` · `.t-loanin`) 이 흰 글자에 채움 배경이었다.

| 배지 | 라이트 대비 | 다크 대비 |
| --- | --- | --- |
| `.t-indone` (흰 글자 · `--green` 채움) | 5.36 : 1 | **2.10 : 1** |
| `.t-loanin` (흰 글자 · `--yellow` 채움) | 4.17 : 1 | **2.14 : 1** |

라이트 테마에서는 멀쩡해 보인다.
다크 테마 토큰은 밝은 쪽으로 조정돼 있어 (`--green: #54C97C` · `--yellow: #E0A83C`) 흰 글자와의 대비가 무너진다.
WCAG AA 최소치 4.5 : 1 은 물론 큰 글자 기준 3 : 1 에도 못 미친다.

**고친 방법** — 여덟 배지를 채움 배경 없이 텍스트 색 + 테두리로 통일하고, 구분은 색 4종 × 테두리 2종 (실선 = 영입 · 파선 = 방출) 으로 냈다.
양쪽 테마에서 5.0 : 1 이상이 된다.

## 왜 태스크별 리뷰가 못 잡았나

둘 다 **한 태스크의 diff 안에서는 결함이 아니다.**

- 널 참조는 `app.js` 를 건드린 태스크와 `player.html.j2` 를 만든 태스크가 달랐다.
각 diff 만 보면 둘 다 정상이다.
깨지는 것은 두 파일이 만나는 지점이고, 그 지점은 어느 diff 에도 안 나온다.
- 대비 붕괴는 CSS 를 추가한 태스크의 diff 에 다 들어 있었으나, 라이트 테마 값만 보면 통과한다.
다크 토큰은 같은 파일 위쪽에 이미 있던 것이라 diff 에 안 나온다.

최종 전체 리뷰는 브랜치 전체와 기존 코드를 함께 보므로 둘 다 잡았다.
**태스크별 리뷰만으로 머지하면 이런 유형은 통과한다.**

## 다음에 새 화면을 붙일 때 볼 것

- **그 화면이 기존 화면에 없던 DOM 조합을 만드는가.**
공유 스크립트가 전제하는 요소 (사이드바 · 목록 컨테이너 · 버튼) 중 이 화면에 없는 것을 적어 보고, 그 요소를 가드 없이 쓰는 곳이 있는지 찾는다.
- **새 색을 라이트 · 다크 양쪽에서 계산한다.**
눈으로 보지 말고 토큰 값으로 대비비를 구한다.
이 저장소의 다크 토큰은 라이트와 밝기 방향이 반대라 한쪽만 보면 반드시 놓친다.
- **회귀 가드를 문자열 계약으로 남긴다.**
pytest 가 브라우저를 띄우지 않으므로 실제 동작은 검증할 수 없다.
대신 `tests/test_serve_render.py` 의 `.morebtn[hidden]{display:none}` 선례처럼, 셀렉터 · 규칙 · 렌더 결과의 짝을 문자열로 고정하면 이름이 바뀔 때 깨진다.

이번에 남긴 가드는 넷이다.

```python
# app.js 가 사이드바 없는 화면을 견디는가
assert "items.length && side" in js
# 그 널 참조를 유발하는 조합이 실제로 만들어지는가
assert 'class="daylist' in html and 'class="side"' not in html
# 접기가 시각 효과를 갖는가
assert re.search(r"\.plgrp\.folded \.playerlist\s*\{[^}]*display\s*:\s*none", css)
# 배지 여덟 종이 전부 정의돼 있는가
for cls in EIGHT_BADGE_CLASSES: assert cls in css
```

## 참조

- 선수 페이지 스펙: `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` §5.3
- 같은 패턴의 선례 (표시 계층 하드코딩): `docs/troubleshooting/2026-08-02-badge-condition-collides-with-hide-policy.md`
- 계약을 문자열로 고정한 선례: `tests/test_serve_render.py::test_static_assets_exist_and_nonempty`
