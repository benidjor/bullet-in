# BBC 셀렉터가 "0건이 아니라 잘못된 형태"를 긁는 드리프트 · 제목 깨짐

- **날짜**: 2026-06-30
- **영역**: adapters / ingest
- **심각도**: 중 (bbc_sport 34건 중 ~30건 비-기사 · 깨진 제목, 단계 분류 오분류 유발)

## 증상
Tier 2-b 라이브 관찰에서 `bbc_sport` (`list_url: …/sport/football/teams/arsenal`) 적재 34건 중 진짜 기사는 ~4건뿐:
1. **비-기사 인라인 링크** — teaser (`"Want more transfer stories? Read Thursday's full gossip column"`) · read-more (`"Read more on Rice's importance …"`) · nav/유틸 (`"How to get Premier League score updates"` · `"…download your World Cup 2026 wallchart"`).
2. **제목 깨짐** — 진짜 카드도 제목이 `21:19 BST 29 June Bournemouth reject Arsenal interest in Scott , published at 21:19 …` 식으로 timestamp · 메타가 본문 헤드라인과 이어붙음.
3. 깨진 · teaser 제목이 `title_contains` 키워드 필터를 **통과**해 단계 분류까지 가서 `rumour` 등으로 **그럴듯하게 오분류**됨.

기존 드리프트 (`2026-06-12-live-source-selector-drift.md`) 와 **증상 클래스가 다름**: 그건 "수집 0건 · 타임아웃 · 빈 제목" 이라 운영 알람 (수집량 이상) 에 걸리지만, 이건 셀렉터가 *결과를 반환* 하므로 알람에 안 걸리고 잘못된 데이터가 조용히 적재됨 → 발견이 더 어려움.

## 진단 과정 (왜 이렇게 판단했는가)
어댑터를 실 URL로 단독 probe (파이프라인 · DB · LLM 없이) 하고 BeautifulSoup 으로 DOM 을 격리 분석.

1. **링크 형태 분류** — `a[href*='/sport/football/articles/']` 가 19개 매칭. 각 anchor 의 가장 가까운 `data-testid` 조상으로 분류하니 깔끔히 갈림:
   - `data-testid="main-content"` (4) — 진짜 promo 카드.
   - `data-testid="content-post"` (14) — 페이지에 임베드된 본문 · 라이브피드 안의 인라인 링크 (teaser · read-more · nav).
   - `data-testid="navigation"` (1) — 내비.
2. **제목 깨짐 원인** — 진짜 카드 `<a>` 안에 span 이 셋: `class*="Timestamp"` (`21:19 BST 29 June`) · `class="visually-hidden …"` (헤드라인 중복 + `, published at …`) · `class*="LinkPostHeadline"` (시각 표시 헤드라인). `a.get_text()` 가 이 셋을 전부 이어붙여 제목이 오염됨. 깨끗한 헤드라인은 `span[class*="LinkPostHeadline"]` 하나에만 있음.

## 원인
- BBC team 페이지는 promo 카드 + 임베드 본문 + nav 가 섞인 **혼합 피드**. `href` 패턴 (`/articles/`) 만으로는 링크 형태를 구분할 수 없음 — 진짜 카드도 임베드 본문 속 인라인 링크도 같은 href 형태.
- `get_text()` 는 시각적으로 숨겨진 (`visually-hidden`) · 메타 (timestamp · `published at`) 텍스트까지 무차별 연결.

## 해결 (PR #20)
- **안정 컨테이너로 스코핑** — `item_selector` 를 href 패턴 단독에서 `data-testid` 조상 결합으로:
  ```yaml
  # config/sources.yaml  bbc_sport
  item_selector: "[data-testid='main-content'] a[href*='/sport/football/articles/']"
  title_selector: "span[class*='LinkPostHeadline']"
  ```
  → `content-post` · `navigation` 인라인 링크가 전부 탈락.
- **헤드라인 서브요소 추출** — `HtmlAdapter` 에 선택적 `title_selector` 추가 (매칭 요소 안에서 sub-selector 로 제목 추출, 미발견 시 항목 skip, 미지정 시 `get_text()` 폴백). bbc_sport 에 `span[class*='LinkPostHeadline']` 지정 → timestamp · visually-hidden 제거된 클린 제목.
- 라이브 검증: bbc_sport 2건, 제목 클린 (앞 timestamp · `published at` 없음), 인라인 링크 0.
- 이미 적재된 잡음은 정리 런북 `docs/runbook/2026-06-30-bbc-collection-cleanup.md` 로 제거 후 재수집.

## 예방
- **라이브 probe 시 건수만 보지 말 것** — 0건이 아니어도 정상이 아닐 수 있다. 제목 샘플 · 링크 형태를 눈으로 확인해 teaser · nav · 깨진 제목이 없는지 본다.
- **혼합 피드 소스는 안정 컨테이너로 스코핑** — `href` 패턴 + semantic 컨테이너 (`data-testid` 등) 조합. 본문 임베드 영역 (`content-post`) 을 명시적으로 배제.
- **get_text 가 chrome 을 흡수하면 `title_selector`** — 카드 안에 timestamp · visually-hidden 등이 섞이는 사이트는 헤드라인 요소를 sub-selector 로 직접 지정.
- **해시 CSS 클래스는 드리프트 축** — `ssrcss-18dafkj-…` 같은 해시 prefix 는 BBC 빌드마다 바뀔 수 있다. 의미 접미사 (`*LinkPostHeadline`) · `data-testid` 같은 안정 축으로 매칭하고, 머지 전 라이브 `fetch()` 로 재검증. 0건/깨진 제목이면 드리프트 신호.
- 관련: 기본 드리프트 (0건 · 타임아웃) `2026-06-12-live-source-selector-drift.md`, 운영 알람 `docs/runbook/2026-05-27-daily-operations.md §4`.
