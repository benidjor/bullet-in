# 라이브 첫 수집에서 공식 소스 0건 — 셀렉터·피드 URL 드리프트

- **날짜**: 2026-06-12
- **영역**: adapters / ingest
- **심각도**: 중 (tier-0 공식 소스 누락, goal 소스 실패)

## 증상
`feat/live-e2e`에서 실제 사이트로 첫 수집 점검 시:
1. `arsenal_official`(RSS) — **0건** (tier 0 공식 소스인데 빈 결과).
2. `goal`(Playwright) — `wait_for_selector` 15s **타임아웃**.
3. `bbc_sport`·`football_london`(HTML) — 정상(16·58건).

`config/sources.yaml`의 selector·feed_url은 설계 단계의 **추정값**이라 실사이트와 어긋날 수 있는 구조.

## 진단 과정 (왜 이렇게 판단했는가)
어댑터를 **실 URL로 단독 probe**(파이프라인·DB·LLM 없이 `adapter.fetch()`만)해서 격리 진단.

1. **arsenal RSS**: 피드 URL을 직접 호출 → `https://www.arsenal.com/rss-feeds/news`가 **HTTP 404**(HTML 에러 페이지). UA를 브라우저로 바꿔도 동일 → URL 자체가 죽음.
   - 후보 탐침: `https://www.arsenal.com/rss.xml`은 200이지만 **2017년 글 1건뿐**(사실상 폐기된 피드). → arsenal.com이 실질 RSS를 폐기.
   - `https://www.arsenal.com/news`(HTML)는 200 + 현재 시즌 기사. 기사 링크 클래스 `responsive-card__wrapper`(nav 링크 `menu__link`와 구분됨).
2. **goal**: Playwright로 페이지를 띄워 anchor를 덤프 → 잡히는 건 `fco-global-navigation__item`(내비)·카테고리 링크뿐, 기사 링크 없음. → 동의(consent) 월 또는 지연 로딩으로 기사 DOM이 늦게/안 그려짐. 셀렉터 `a[data-testid='article-link']`는 더 이상 없음.

## 원인
`sources.yaml`의 selector/feed_url이 **실제 사이트 DOM·피드와 드리프트**.
- arsenal: 공식 RSS 폐기(많은 구단이 그랬음).
- goal: SPA 동의월/지연 로딩 + 셀렉터 변경.

트러블슈팅 시드(`README.md`)의 "Playwright 셀렉터 드리프트(대상 사이트 DOM 변경)"가 실현된 사례.

## 해결
- **arsenal**: RSS → HTML 스크랩으로 전환(`8d14f2f`).
  ```yaml
  adapter: html
  config:
    list_url: "https://www.arsenal.com/news"
    item_selector: "a.responsive-card__wrapper"
    base_url: "https://www.arsenal.com"
  ```
  라이브 검증: 현재 시즌 기사 16건, 빈 제목 0.
- **goal**: 동의월·셀렉터 추가 조사가 필요해 일시 `enabled: false`(`390b1fc`). 후속 트랙에서 consent 처리 + 기사 셀렉터 재발굴.

## 예방
- **머지 전 라이브 probe 의무화** — 신규/변경 소스는 어댑터 단독 `fetch()`로 실사이트 셀렉터를 검증한 뒤 활성화. 단위 테스트는 모킹이라 드리프트를 못 잡는다.
- probe 스니펫(재사용): 각 어댑터를 `config`에서 만들어 `await adapter.fetch()` 후 건수·샘플 제목·URL 출력.
- 소스 selector는 깨질 수 있는 외부 의존이므로, 수집 0건/타임아웃을 운영 알람 신호로 본다(런북 daily-operations §4).
