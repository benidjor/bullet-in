# 클라이언트 렌더링 소스의 비공식 GraphQL API 발굴 — 프로브 함정 3종

- 날짜: 2026-07-19 (arsenal_official 복구 스파이크 중 실측)
- 관련: spec `docs/superpowers/specs/2026-07-19-arsenal-official-api-recovery-design.md`,
  복구 PR #68, 발견 경위 `docs/troubleshooting/2026-07-19-silent-zero-collection-blindspot.md`
- 적용 범위: 목록이 클라이언트 렌더링이라 정적 fetch 가 불가한 소스의 복구 스파이크 일반
  (goal 어댑터류 후속 복구에 재사용 가능).

## 1. 발굴 절차 (성립 확인된 경로)

arsenal.com 개편 사이트에서 아래 순서로 비공식 API 를 찾아 httpx 단독 수집을 성립시켰다.

1. 프레임워크 마커 grep — 목록 페이지 HTML 에서 `__NEXT_DATA__` · `__NUXT__` 류를 찾는다
   (arsenal.com 은 `__NEXT_DATA__` = Next.js Pages Router).
2. SSR props 확인 — `__NEXT_DATA__` 의 `pageProps` 에 목록 데이터가 있으면 HTML 파싱만으로 끝.
   arsenal.com 은 목록이 없었다 (클라이언트 Apollo 호출)
→ 다음 단계로.
3. 번들 URL 추출 — `_buildManifest.js` 에서 대상 라우트의 페이지 청크 + 공유 청크 목록을 얻는다.
4. 청크에서 엔드포인트 · 쿼리 발굴 — 청크 파일들을 받아
   `https://` URL grep (→ `afc-prd.graph.arsenal.com/graphql`) 과
   `query <이름>` grep (→ `GetArticlesByTaxonomy` · `GetArticle` 전문) 으로 추출한다.
5. 직접 호출 검증 — 추출한 쿼리를 그대로 POST 해 인증 · 헤더 요구를 확인한다
   (arsenal.com 은 인증 불요, `bullet-in/0.1` UA · Origin 생략도 허용).

## 2. 함정 1 — resolver 가 에러 없이 null 을 돌려준다

- **증상**: 같은 쿼리인데 호출 형식 · 인자에 따라 `{"data": {"...": null}}` 이 **errors 배열 없이** 온다.
  익명 인라인 쿼리 + `articleTypes: "News"` 조합은 null, 번들 원형 (named operation +
  variables + `articleTypes: ""`) 은 정상 — 어느 요소가 원인인지는 서버가 알려주지 않는다.
- **판독**: HTTP 200 + errors 없음 + data null 은 "결과 0건" 이 아니라 **인자 · 형식 불성립**이다.
  GraphQL validation 에러 (필드 오타 등) 는 errors 로 오지만, resolver 수준 거부는 조용한 null 로 온다.
- **대응**: 프로브는 항상 **번들 원형 그대로** (operationName · 전체 variables · 기본값) 시작하고,
  한 요소씩만 바꿔가며 null 경계를 찾는다.
  원형부터 변형해 시작하면 "API 가 안 된다" 로 오판한다 (이번 스파이크에서 실제 발생).

## 3. 함정 2 — 서버측 필터 인자가 전 형식 불성립

- **증상**: `taxonomy` 인자에 슬러그 (`news`) · 표시명 (`Transfer news`) · 숫자 ID (`3943`) ·
  콤마 결합 어느 형식을 줘도 null (함정 1 과 같은 조용한 null).
- **배경**: 프론트엔드는 필터 UI 의 React context 값을 넘기는데, 그 값 체계 (URL `?filters=39` 류)
  는 응답의 `taxonomiesIds` 와 다른 ID 공간으로 보이며 대응표를 얻을 경로가 없었다.
- **대응**: 서버측 필터를 포기하고 **무필터 목록 + 클라이언트측 필터**로 우회한다.
  응답에 기사별 `taxonomies` 배열이 포함돼 손실이 없고, 어댑터 필터 규칙이 코드로 남아
  테스트 가능해진다 (`adapters/arsenal_api.py` `_accept`).
- 서버측 필터 재시도에 시간을 쓰지 말 것 — 페이지네이션 + 클라이언트 필터로 충분하다.

## 4. 함정 3 — introspection 부분 차단 · 필드명 발굴 우회

- **증상**: `__type(name: "Article")` 이 `_no_fields_accessible` 한 개를 돌려준다
  (introspection 자체는 살아 있으나 필드 목록만 차단).
- **우회 2경로**:
  1. 번들 내 **다른 쿼리의 selection** 에서 필드명을 얻는다
     — 목록 쿼리에 없던 `publicationDate` · `taxonomiesIds` 는 `GetArticle` 쿼리 전문에 있었다.
  2. **validation 에러 메시지를 시행착오 프로브로 활용**한다
     — 존재하지 않는 필드는 `no such field on type ArticleResponse: publishedDate` 처럼
     타입명까지 알려줘, 후보 필드명을 하나씩 넣어보면 스키마를 더듬을 수 있다.
- 목록 쿼리 selection 은 번들 원형에 없는 필드도 (같은 타입이면) 추가 요청이 성립한다
  — 목록 쿼리에 `publicationDate` 를 추가해 증분 기준 날짜를 확보했다.

## 5. 관련

- 어댑터 운영 · 실패 모드: `docs/runbook/2026-07-19-arsenal-official-api-adapter-ops.md`
- 셀렉터 드리프트 일반론: `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`
→ 이번 건 이후 arsenal_official 은 셀렉터가 아니라 쿼리 계약 드리프트 축으로 이동했다.
