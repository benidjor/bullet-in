# 소스 확장 설계 — goal 복구 + guardian · skysports 신규 등재 (2026-07-15)

로드맵 SoT ( `docs/superpowers/2026-06-28-v1-completion-roadmap.md` ) Tier 4 항목 10 "goal (Playwright) 복구" 에 사용자 지시 신규 소스 3종 ( guardian · skysports · telegraph ) 을 합친 트랙.
사전 정찰 ( `.superpowers/next-track/goal-recon-2026-07-15.md`, curl 실측 ) 을 근거로 브레인스토밍에서 범위 · 접근을 확정했다.

## 1. 배경 · 문제

- **goal 비활성 장기화** — 2026-06-12 ( 390b1fc ) 셀렉터 · 동의창 문제로 `enabled: false` 후 방치.
  기존 URL 의 팀 슬러그 ID 자체가 바뀌어 ( 404 ) 셀렉터 수리만으로는 복구 불가.
- **최초 등재 사유 소멸** — goal 은 "Playwright 필수 시연 지점" 으로 선정됐으나 ( plans/2026-05-27 ), 현재 뉴스 페이지는 정적 HTML 로 전문 서빙된다 ( 정찰 실측: 511KB, 링크 26건이 curl 응답에 존재 ).
  Playwright 시연 역할은 x_afcstuff 가 대체 중.
- **상위 신뢰도 언론 소스 공백** — 현행 고정 소스는 tier 0 ( 공식 ) · 2 ( bbc_sport ) · 4 ( gossip · football.london ) 구성.
  credibility.yaml 이 1.5 로 배정한 Guardian · Sky Sports 는 outlets 사전에만 있고 수집 소스가 아니었다.

## 2. 목표 · 비목표

- **목표** — goal 을 HtmlAdapter 로 전환 복구하고 guardian ( Open Platform API ) · skysports ( HtmlAdapter ) 를 신규 등재.
- **목표** — 3종 모두 bbc_sport 와 동일한 이적 키워드 필터 ( title_contains ) 를 적용해 이적 무관 유입과 Gemini 무료 티어 부하를 억제.
- **목표** — guardian 항목도 상세 페이지 데이터 계약 ( body_source · image_url ) 을 첫 등재부터 충족.
- **비목표** — telegraph 등재: Akamai 403 ( HTTP 레벨 봇 차단, 브라우저 UA 로도 403 ) + 본문 페이월로 고비용 · 저수율.
  Playwright 우회 spike 자체가 고비용이고 통과해도 수율이 낮아 이번 트랙에서 제외한다.
  핵심 기자 ( Matt Law 등 ) 단론은 x_afcstuff 경유로 이미 유입된다.
- **비목표** — 이적 키워드 필터의 파이프라인 공통 단계 승격 ( 접근안 B 기각 ): 기존 소스 동작 경로를 바꿔 회귀 위험이 신규 등재 밖으로 번지고, html 어댑터의 "본문 fetch 전 필터" 최적화를 해친다.
- **비목표** — README §소스 표 갱신: SLO-1 트랙 ( 별도 세션 ) 이 README 를 수정 중이라 머지 충돌 회피를 위해 후속으로 미룬다 ( §8 ).
- **비목표** — credibility.yaml 변경: Guardian 1.5 · Sky Sports 1.5 · Goal.com 2 가 outlets 에 기배정돼 있어 손댈 것이 없다.

## 3. 확정 결정 ( 브레인스토밍 합의 )

| 논점 | 결정 | 근거 |
|---|---|---|
| goal 처리 | HtmlAdapter 전환 복구 | 정적 서빙 실측 · Playwright 사유 소멸 · 브라우저 의존 제거 |
| guardian 경로 | Open Platform API | 셀렉터 드리프트 면역 · 기존 guardian_api.py 활성화 · 키 발급 완료 |
| telegraph | 제외 | Akamai 403 + 페이월, spike 비용 대비 수율 낮음 |
| 이적 필터 | 3종 모두 bbc_sport 동일 리스트 | 서비스 성격 일관 · enrich 부하 억제 |
| 구현 접근 | A안 ( guardian 어댑터만 소폭 확장 ) | goal · skysports 는 config 만 — 기존 소스 회귀 위험 0 |

## 4. 소스 구성 ( sources.yaml )

### 4.1. goal — 기존 항목 수정

```yaml
- source_id: goal
  display_name: Goal.com
  tier: 2
  medium: newspaper
  adapter: html            # playwright → html
  config:
    list_url: "https://www.goal.com/en/team/arsenal/news/4dsgumo7d4zupm2ugsvm4zm4d"   # 신규 슬러그
    item_selector: "a[href^='/en/news/']:not([aria-label]), a[href^='/en/lists/']:not([aria-label])"
    base_url: "https://www.goal.com"
    title_contains: [bbc_sport 와 동일 리스트]
    body_selector: (라이브 검증에서 확정)
  enabled: true
```

- **셀렉터 초안 근거** — 기사 링크는 class 없는 `/en/news/...` · `/en/lists/...` 앵커이고, 이미지용 앵커 ( `aria-label="Image"` ) 가 같은 href 로 중복돼 `:not([aria-label])` 로 배제.
- **여자팀 필터 불요** — 여자팀은 별도 슬러그 ( `arsenal-women/...` ) 라 남자팀 슬러그 URL 만으로 스코프 완결 ( 정찰 실측 ).

### 4.2. guardian — 신규 등재

```yaml
- source_id: guardian
  display_name: The Guardian
  tier: 1.5
  medium: newspaper
  adapter: guardian_api
  config:
    tag: "football/arsenal"
    title_contains: [bbc_sport 와 동일 리스트]
  enabled: true
```

### 4.3. skysports — 신규 등재

```yaml
- source_id: skysports
  display_name: Sky Sports
  tier: 1.5
  medium: newspaper
  adapter: html
  config:
    list_url: "https://www.skysports.com/arsenal"
    item_selector: (뉴스 컨테이너 스코프 우선, 라이브 검증에서 확정)
    base_url: "https://www.skysports.com"
    title_contains: [bbc_sport 와 동일 리스트]
    body_selector: (라이브 검증에서 확정)
  enabled: true
```

- **셀렉터 수용 기준** — 네비게이션의 `/football/news/` 혼입 링크 ( 멤버십 Q&A 등 ) 를 배제하고 기사 링크만 잡을 것.
  컨테이너 스코프가 안 되면 섹션 id 필터 ( 예: `/football/news/11670/` ) 를 차선으로.
- **tier 표기** — `models.py` 의 `tier: float` 라 1.5 를 그대로 쓴다 ( credibility.yaml outlets 배정값 ).

## 5. GuardianAdapter 확장 ( ~20줄 )

### 5.1. q → tag 교체

- **현행 문제** — `q=Arsenal` 은 전문 검색이라 본문에 Arsenal 이 스치는 타 구단 기사 · 월드컵 라이브블로그가 혼입 ( 2026-07-15 발급 키로 실측 ).
- **교체** — `tag=football/arsenal` 은 HTML 페이지 `/football/arsenal` 과 동일한 태그 스코프로 아스날 기사만 반환 ( 실측 확인 ).
  기존 `query` · `section` 파라미터는 폐기하고 config 의 `tag` 로 대체 ( 호출자는 factory 뿐 ).

### 5.2. 필드 확장 · payload 계약

- **show-fields** — `trailText` → `trailText,bodyText,thumbnail` + `page-size: 20` ( HTML 페이지 유니크 16건 수준 커버 ).
  bodyText · thumbnail 모두 developer 키 응답에 실재함을 실측 확인 ( 2026-07-15 ).
- **payload 매핑** — `pipeline.py` 소비 계약에 정렬.

| payload 키 | API 필드 | 파이프라인 소비 |
|---|---|---|
| title | webTitle | title |
| published | webPublicationDate | published_at |
| summary | fields.trailText | body_excerpt |
| body | fields.bodyText | body_source ( 본문번역 · 3줄요약 ) |
| image_url | fields.thumbnail | image_url ( 카드 이미지 ) |

- **title_contains 시맨틱** — HtmlAdapter 와 동일 ( 소문자 부분일치, str | list 수용, 미지정 시 전건 통과 ).

### 5.3. factory 배선 · 키 누락 처리

- **배선** — guardian_api 분기에 `c.get("tag")` · `c.get("title_contains")` 전달.
- **키 누락** — 현행 `os.environ["GUARDIAN_API_KEY"]` 는 KeyError 로 build 단계에서 파이프라인 전체를 죽인다.
  키 부재 시 해당 소스만 skip + `WARNING` 로깅으로 바꿔 다른 소스 수집을 지속한다 ( fmkorea 429 대응과 같은 격리 패턴, 다음 사이클 재시도 ).

## 6. 에러 처리 · 리스크

- **fetch 실패 격리는 기존 것으로 충분** — `ingest.py` 의 소스별 try/except 가 goal 슬러그 재변경 404 · API 장애 · 셀렉터 드리프트를 해당 소스만 errors 로 격리.
  지속 실패는 SLO-5 신선도 워터마크가 알림으로 잡는다 ( 신규 소스도 자동 편입 ).
  → 신규 에러 처리 코드 없음.
- **goal SSR 변동 리스크** — 정적 서빙 여부가 지역 · 세션에 따라 다를 수 있음 ( 정찰 메모 ).
  라이브 검증 ( §7 ) 에서 httpx UA 로 재확인하고, 비정적이면 goal 만 트랙에서 분리 재평가.
- **키 시크릿 취급** — GUARDIAN_API_KEY 는 `.env` 에만 두고 spec · 커밋 · 테스트 픽스처에 넣지 않는다.
  developer 키 한도 ( 500 calls/day ) 는 사이클당 1콜이라 여유.

## 7. 테스트 · 라이브 검증

- **단위 테스트 ( httpx 모킹, 픽스처 기대값 손 재계산 )**
  - GuardianAdapter: 키워드 필터 통과 / 차단 · payload 매핑 · fields 결손 시 빈 값 처리.
  - factory: tag · title_contains 배선, 키 누락 시 skip + WARNING ( 다른 어댑터는 정상 생성 ).
- **라이브 검증 ( 머지 전 필수 )** — 단위 테스트는 모킹이라 셀렉터 드리프트를 못 잡는다 ( CLAUDE.md 함정 ).
  3종 각각 어댑터 단독 `fetch()` 를 실행해 goal · skysports 셀렉터와 body_selector 를 확정.
- **병렬 세션 제약** — 03:00 ~ 03:15 KST ( SLO-1 벤치 3회차 창 ) 대량 fetch 자제 · fmkorea 미접근.
- **SLO-1 실측치 무영향 확인** — 3종 모두 정적 / API 라 병렬 수집 시간은 x_afcstuff ( 42s ) 지배 구도 유지.

## 8. PR 전략 · 후속

- **PR 크기** — 전체 diff ≤ 200 LOC 면 단일 PR.
  초과 시 ① goal + skysports ( config 만 ) ② guardian ( 어댑터 + 테스트 ) 로 분할.
- **머지 순서** — SLO-1 PR ( 별도 세션 ) 선머지 가능 — 파일 겹침이 없어 충돌은 없고, 머지 전 origin/main 리베이스만 확인.
- **후속 작업 ( 이번 트랙 제외 )**
  - README §소스 표에 3종 반영 ( SLO-1 머지 후 ).
  - telegraph 재평가: RSS · 서드파티 피드 등 대체 경로가 확인될 때만 재검토.
