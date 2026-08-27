# DB 없이 화면 변경을 확인하는 절차 (2026-08-27)

정적 자산 (`app.js` · `style.css`) 이나 템플릿을 고쳤을 때, **배포 전에 진짜 브라우저에서** 확인하는 방법이다.

로컬에는 렌더에 쓸 데이터가 없다 (선수 페이지는 아예 안 만들어진다 · `local-mart-cannot-render-player-pages`).
그런데 **이미 배포된 HTML 이 곧 실제 데이터**다.
거기에 새 자산만 얹으면 데이터 없이도 화면이 그대로 재현된다.

## 1. 언제 쓰나

- 필터 · 정렬 · 접기처럼 **자바스크립트가 만드는 화면**을 고쳤을 때.
- 격자 · 폭처럼 **CSS 가 만드는 화면**을 고쳤을 때.
- 템플릿의 자리 표시 문구 같은 작은 변경은 이 절차가 과하다 (배포 뒤 확인으로 충분).

**서버 렌더 결과가 바뀌는 변경에는 못 쓴다** — 그때는 운영 사본에 서빙 코드를 그대로 호출해 계수를 재는 쪽이 맞다.

## 2. 절차

```bash
mkdir -p /tmp/vtest && cd /tmp/vtest
curl -sL https://bullet-in.pages.dev/index.html -o index.html   # 실제 데이터가 든 화면
cp <워크트리>/src/bullet_in/serve/static/app.js .               # 고친 자산만 얹는다
cp <워크트리>/src/bullet_in/serve/static/style.css .
python3 -m http.server 8899                                     # file:// 은 안 된다 (모듈 · fetch 제약)
```

배포본은 `app.js` · `style.css` 를 같은 폴더에서 상대 경로로 읽으므로, 그 둘만 바꿔 놓으면 나머지는 그대로 산다.

확인이 끝나면 서버를 내린다.

```bash
pkill -f "http.server 8899"
```

## 3. 브라우저에서 재는 법

눈으로만 보지 말고 **수치를 뽑는다.**
클릭으로 필터를 거는 것보다 자바스크립트로 상태를 만들고 값을 읽는 편이 빠르고 재현된다.

```javascript
// 필터를 걸고 격자가 펴지는지
const cb = document.querySelector('input[data-group="journalist"][data-value="David Ornstein"]');
cb.checked = true;
cb.dispatchEvent(new Event('change', {bubbles: true}));
document.getElementById('applyBtn').click();
await new Promise(r => setTimeout(r, 300));
const dls = [...document.querySelectorAll('.daylist')].filter(d => d.style.display !== 'none');
({보이는_그룹: dls.length,
  solo: dls.filter(d => d.classList.contains('solo')).length,
  카드폭: dls[0].querySelector('.block')?.getBoundingClientRect().width,
  목록폭: dls[0].getBoundingClientRect().width})
```

```javascript
// 검색이 엔터에서만 걸리는지
const vis = () => [...document.querySelectorAll('.daylist .item')].filter(i => i.style.display !== 'none').length;
const q = document.getElementById('q');
q.value = '콘사';
q.dispatchEvent(new Event('input', {bubbles: true}));      // 입력만
const 입력만 = vis();
q.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
({입력만, 엔터후: vis()})
```

**전후를 같은 잣대로 잰다.**
2026-08-27 에는 이렇게 나왔다 — 필터 적용 시 보이는 날짜 그룹 22개 중 21개가 카드 한 장이라 한 열로 펴졌고 (카드 폭 741px = 목록 폭), 검색은 입력만 했을 때 70건 그대로 · 엔터에서 10건이 됐다.

## 4. 함정

- **배포본을 받는 시점이 곧 데이터 시점이다.** 회차가 돌면 값이 달라진다 — 잰 값을 적을 때 받은 시각을 함께 적는다.
- **`file://` 로 열지 말 것.** 배포본은 상대 경로 자산을 읽고 일부 API 가 막힌다.
- **캐시.** 자산을 다시 고치면 브라우저가 옛 파일을 쓸 수 있다 — 강제 새로고침하거나 포트를 바꾼다.
- **이 절차는 서버 렌더를 안 본다.** 템플릿을 고쳤으면 배포본 HTML 에는 그 변경이 없다 (예 — 자리 표시 문구). 그 부분은 배포 뒤에 확인한다.

## 관련

- `docs/runbook/2026-08-20-predicting-display-delta-without-rendering.md` — 서버 계수를 렌더 없이 재는 절차 (이 문서와 짝)
- `docs/runbook/2026-07-19-enrich-only-pass.md` §4 — 사이트 재생성
- PR — #349 (필터 화면 두 건을 이 절차로 확인)
