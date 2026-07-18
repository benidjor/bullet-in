# hidden 속성이 작성자 CSS 에 무력화됨 (2026-07-16)

facet tier 정렬 트랙 ( 계획 `docs/superpowers/plans/2026-07-16-facet-tier-ordering.md` ) 의 라이브 검증에서 발견.
단계 더보기 버튼이 JS 로 `hidden` 을 설정해도 화면에서 안 숨었다.
pytest · 코드 리뷰 · 노드 시뮬레이션이 **셋 다 못 잡았고** 실브라우저만 잡았다.

## 증상

사이드바 facet 의 더보기 버튼이 단계마다 하나씩 나와야 하는데 **5개가 한꺼번에** 쌓여 보였다.

```
화면에 보이는 버튼 = ['더보기 · Tier 2', '더보기 · Tier 3', '더보기 · Tier 4 · 미등재',
                    '더보기 · Tier 3', '더보기 · Tier 4 · 미등재']
```

`app.js` 의 `setupMore()` 는 `btns.forEach((b, i) => { b.hidden = i !== open; })` 로 **정확히 설정하고 있었다**.

## 원인

`style.css` 의 `.morebtn{display:block; ...}` 이 브라우저 기본 스타일시트의 `[hidden] { display: none }` 을 덮어썼다.

**작성자 스타일시트의 `display` 선언은 UA 스타일시트를 항상 이긴다** — 특정도와 무관하다 ( 캐스케이드 origin 우선순위 ).
따라서 요소에 `display` 를 지정하는 순간 `hidden` 속성은 그 요소에서 무력화된다.

Playwright 계측:

```
btn2.hidden                       = True      ← JS 는 제대로 설정
getComputedStyle(btn2).display    = "block"   ← CSS 가 이김
btn2.offsetParent !== null        = True      ← 그래서 보임
```

대조군 — `.morestage` 는 `style.css` 에 `display` 규칙이 없어 `hidden` 이 정상 동작했다 ( `display: none` ).
즉 **단계는 잘 숨고 버튼만 안 숨는** 비대칭이 단서였다.

## 수정

작성자 스타일시트 안에서 다시 명시한다.

```css
.morebtn[hidden]{display:none}
```

`!important` 는 불필요하다 — `.morebtn[hidden]` 이 `.morebtn` 보다 특정도가 높다.
전역 `[hidden]{display:none!important}` 도 만들지 않았다 ( 다른 요소는 정상 동작 중이라 범위를 넓힐 이유가 없다 ).

## 이 함정의 성질

- **기존 결함이었다** — 옛 `expandMore()` 의 `jmoreBtn.hidden = true` 도 같은 문제를 갖고 있었다.
  버튼이 하나뿐이라 "더보기를 눌러도 버튼이 안 사라진다" 정도로 눈에 덜 띄었고, 단계 더보기가 1개 → 5개로 증폭시켜 드러났다.
- **테스트가 구조적으로 못 잡는다** — `pytest` 는 `app.js` · `style.css` 를 **문자열로만** 검사한다.
  `assert "morestage" in js` 는 식별자 존재만 증명하고 실동작은 아무것도 보장하지 않는다.
- **코드 리뷰도 못 잡는다** — JS 만 보면 완벽하다. CSS 와 UA 스타일시트의 상호작용은 두 파일을 겹쳐 봐야 보인다.
- **노드 시뮬레이션도 못 잡는다** — 리뷰어가 `sync()` 알고리즘을 스텁으로 재현해 6개 시나리오를 통과시켰지만, 스텁에는 CSS 가 없다.

## 재발 방지

- `hidden` 속성으로 토글하는 요소에 `display` 를 지정하려면 **`[hidden]` 짝 규칙을 같이 넣는다**.
- 정적 자산 (`app.js` · `style.css`) 변경은 **브라우저 검증이 유일한 행동 게이트**다.
  pytest 문자열 단언은 계약 표식일 뿐 검증이 아니다 — 계획서의 라이브 검증 태스크를 생략하지 말 것.
- 증상이 "일부만 동작" 일 때 ( 단계는 숨는데 버튼은 안 숨음 ) 두 요소의 CSS 차이를 먼저 본다.

## 참고

- 설계: `docs/superpowers/specs/2026-07-16-facet-tier-ordering-design.md` §3.2
- 수정 커밋: `0f5b1a0`
- 검증: 실브라우저 계측 5개 → 2개 ( facet 별 첫 버튼 ) · 클릭 시 1단계 전진 · 전체 23/23 PASS
