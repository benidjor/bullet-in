# 버튼을 옮기자 그 버튼이 안 눌리게 됐다 (2026-08-28)

공개 전날 사용자가 라이브를 훑다가 「관련 보도를 눌러도 안 펼쳐진다」 고 알렸다.
닷새 전에 넣은 마크업 변경이 그 버튼을 찾던 자바스크립트를 조용히 끊어 놓았다.

## 1. 무엇이 깨졌나

`app.js` 는 버튼 바로 다음 형제에서 목록을 찾았다.

```js
const rel = btn.nextElementSibling;
rel.hidden = !rel.hidden;
```

2026-08-28 (#364) 에 「두 버튼을 한 줄에 나란히」 를 넣으면서 버튼이 `.blocknav` 안으로 들어갔다.

```html
<div class="blocknav">
  <a class="storylink">…</a>
  <button class="reltoggle">관련 보도 63건</button>
</div>
<div class="related" hidden>…</div>
```

버튼의 다음 형제가 없어져 `nextElementSibling` 이 `null` 이 됐고, 클릭하면 `TypeError` 만 나고 아무 일도 안 일어났다.

## 2. 왜 아무도 못 봤나

세 겹이 겹쳤다.

- **테스트가 마크업을 안 본다** — 단위 테스트는 `app.js` 를 **문자열로** 읽어 특정 구문이 들어 있는지만 확인한다. 문자열은 그대로였다.
- **오류가 화면에 안 보인다** — 콘솔에만 남고 카드는 멀쩡히 그려진다.
- **그 기능을 쓰는 다른 판정이 있었다** — 같은 회차의 안건 τ 측정이 「관련 보도 47개가 전부 `hidden` 이라 **눌러야 보인다**」 고 적었다. 그 문장을 쓸 때 실제로 누르지는 않았다.

**「눌러야 보인다」 를 적으면서 눌러 보지 않은 것이 이 버그를 한 회차 더 살렸다.**

## 3. 고친 방법

블록을 기준으로 찾는다 — 같은 파일의 필터 코드가 이미 쓰던 방식이다.

```js
const rel = btn.closest('.block')?.querySelector('.related');
if (!rel) return;
```

## 4. 다음에 밟지 않으려면

- **마크업의 위치를 바꾸는 변경은 그 요소를 관계로 찾는 코드를 함께 본다.**
  `nextElementSibling` · `previousElementSibling` · `parentNode.children[n]` 이 그런 코드다.
  한 파일 안에서 `closest()` 로 찾는 자리와 형제로 찾는 자리가 섞여 있으면 특히 위험하다.
- **자바스크립트 계약 테스트는 「이 문자열이 있다」 가 아니라 「이 관계가 성립한다」 로 적는다.**
  이번에는 문자열 검사가 통과하면서 동작이 죽어 있었다.
- **화면 동작을 문서에 적을 때는 그 동작을 한 번 시켜 본다.**
  「눌러야 보인다」 는 관측이 아니라 코드를 읽고 쓴 추정이었다.

## 함께 볼 것

- `docs/runbook/2026-08-28-rendering-the-home-page-before-you-deploy-it.md` — 배포 전에 브라우저로 실제 동작을 재는 절차
- `docs/troubleshooting/2026-08-23-unit-tests-passed-but-discord-flattened-the-alert.md` — 단위 테스트가 통과하고도 바깥 렌더러에서 깨진 같은 모양
