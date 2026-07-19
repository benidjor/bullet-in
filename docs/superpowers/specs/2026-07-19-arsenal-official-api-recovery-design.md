# arsenal_official 수집 복구 — GraphQL API 어댑터 전환 (경량 spec)

- 날짜: 2026-07-19
- 배경 SoT: `docs/superpowers/2026-07-19-post-v1-followup-tracks.md` §6 (복구 항목)
- 진단 실측: `docs/troubleshooting/2026-07-19-silent-zero-collection-blindspot.md`
- 성격: 스파이크 실측으로 주요 갈래가 해소된 상태의 경량 설계 기록.
  설계 갈래 4건 (필터 방식 · 재계약 범위 · 소급 범위 · 진행 형식) 은 사용자 확정 완료.

## 1. 배경 · 목표

공홈 전면 개편 (Next.js 전환 · 목록 클라이언트 렌더링) 으로 구 셀렉터가 무효화돼
arsenal_official 이 조용히 0건 수집 중이었다.
tier 0 최상 공신력 소스이자 트랙 ⑤ 오피셜 규칙 (`rule_stage`) 의 유일한 실데이터 공급원이라
복구 전까지 오피셜 필터가 제품 가치를 갖지 못한다.

목표:

- **수집 복구** — 신규 사이트 구조에서 남자팀 이적 · 재계약 기사를 다시 수집한다.
- **'sign' 제목 필터 대체** — 방출 오피셜 (트로사르 "joins Besiktas") 이 걸러지던 결함을
  taxonomy 판별로 해소해 §0 "영입 · 방출 모두 수집" 확정과 정합시킨다.
- **과거 소급** — 2026 여름 이적창 (6/1 이후) 의 밀린 오피셜 기사를 백필한다.

## 2. 스파이크 실측 (2026-07-19)

- 신규 사이트 = Next.js Pages Router.
  `__NEXT_DATA__` 의 SSR pageProps 에 기사 목록이 없어 정적 HTML 파싱 불가 (재확인).
- 비공식 GraphQL API `https://afc-prd.graph.arsenal.com/graphql` 가 인증 없이 응답 (HTTP 200).
  브라우저 UA · Origin 헤더만으로 충분 → **Playwright 불필요, httpx 단독 성립**.
- 목록 = `GetArticlesByTaxonomy` (JS 번들에서 쿼리 전문 추출).
  `pageNumber` / `pageSize` 페이지네이션 · `sortField: publishedDate` 최신순 동작.
  기사별 `title` · `path` · `publicationDate` · `articleType` · `taxonomies` 배열 반환.
- 본문 = `GetArticle(glideId)`.
  구조화 블록 배열이며 `TEXT` 블록의 `innerText` 로 본문, `HEADER` 블록에서 이미지 · 저자.
- 서버측 taxonomy 필터 인자는 슬러그 · 이름 · ID 모든 형식이 null 반환
→ 성립하지 않으므로 **어댑터 클라이언트측 필터** 채택.
- 기준 케이스 taxonomy 실측:

| 기사 | taxonomies (관련분) |
|---|---|
| Leandro Trossard joins Besiktas (7/15 방출 오피셜) | Transfer news · Men · News |
| Terms agreed with Besiktas for Trossard transfer (7/14) | Transfer news · Men · News |
| Josh Ogunnaike signs first professional contract | Contract news · Academy · News |

## 3. 확정 결정 (사용자, 2026-07-19)

- **필터 = taxonomy 판별** — 'sign' 제목 필터 제거.
  채택 조건: `articleType == "News"` AND `"Men" ∈ taxonomies`
  AND (`"Transfer news" ∈ taxonomies` OR `"Contract news" ∈ taxonomies`).
- **재계약 = Men 한정 포함** — 1군 재계약은 제품 가치가 있어 수집,
  아카데미 첫 프로계약 (Ogunnaike 류) 은 Men 필수 조건으로 차단.
- **소급 = 2026 여름 이적창** — 6/1 이후 Transfer news 기사 백필.
- **진행 형식 = 경량 spec + 직접 구현** (이 문서).

## 4. 설계

### 4.1 어댑터 — `ArsenalApiAdapter` (신규, `adapters/arsenal_api.py`)

- `source_type = "api"`, factory kind = `arsenal_api` (GuardianAdapter 선례).
- 엔드포인트 · 쿼리 전문은 어댑터 상수로 고정 (config 노출 없음 — 요청 밖 설정성 배제).
- fetch 흐름: 목록 쿼리를 `pages` 회 호출 (페이지당 50건)
→ §3 채택 조건으로 필터 → 채택 기사만 `GetArticle` 로 본문 fetch.
- RawItem payload 매핑 (guardian 선례 준수):
  `title` · `published` (publicationDate) · `body` (TEXT 블록 innerText 개행 결합)
  · `image_url` (HEADER image) · `authors` (HEADER author, 통상 "Arsenal Media").
- 기사 URL = `https://www.arsenal.com` + `path`.

### 4.2 config (`sources.yaml`)

- `adapter: html → arsenal_api`, `item_selector` · `title_contains` · `list_url` ·
  `body_selector` 제거.
- `pages: 2` (평시 — 최근 100건 ≈ 열흘 커버, 회차당 GraphQL POST 2회 + 채택분 본문 호출).

### 4.3 단계 태깅 — rule_stage 무변경 · 재계약 관찰 항목 종결

- `rule_stage("arsenal_official") = official` 유지 — 재계약 포함 전 수집분이 오피셜 태깅.
- 근거: 단계 enum 에 재계약이 없어 LLM 경로로 보내면 `other` (서빙 숨김) 로 떨어진다
→ 수집한 재계약을 보이게 하는 경로는 규칙 태깅뿐이고, 클럽 공식 발표라는 의미에서도 정합.
- 분류 런북 "알려진 한계" 의 재계약 항목은 이 결정으로 재검토 종결 — 의도된 동작으로 개정.

### 4.4 백필 — 여름 이적창 1회 소급

- 전용 백필 모듈 없음: 어댑터를 `pages=30` (5/23 도달 실측) 으로 단독 실행해
  6/1 컷오프 필터 후 표준 적재 경로 (RawStore → to_articles → upsert → rule 태깅) 를
  1회 통과시키는 스크립트로 소급했다 (2026-07-19 실행 완료 — 5건).
- 전체 파이프라인 종단 실행 대신 단독 스크립트를 쓴 이유
→ run.py 는 전 소스를 fetch 해 fmkorea 접촉 금지 제약과 충돌한다.
- 번역 (title_ko NULL) 은 하루 4회 정규 스케줄이 멱등 누적으로 흡수 (옵션 C)
→ mart 의 URL UNIQUE · content_hash dedup 으로 재실행도 안전하다.

## 5. 검증

- 단위 테스트: 목록 · 본문 응답 모킹으로 필터 규칙 (방출 오피셜 통과 · 아카데미 차단 ·
  Video 제외) · payload 매핑 검증.
- 라이브 단독 fetch: 어댑터 단독 `fetch()` 로 트로사르 방출 오피셜 · 합의 기사 수집 실증
  (셀렉터 드리프트 함정 — 머지 전 필수).
- 종단 확인: 백필 실행에서 수집분이 `rule_stage` 로 official 태깅되는지 확인
  (트랙 ⑤ 분류 축의 첫 실데이터 실증).

## 6. 리스크 · 한계

- **비공식 API 드리프트** — 쿼리 필드 변경 시 GraphQL validation 에러로 fetch 가 실패한다.
  구 셀렉터의 "평시와 구분 불가한 0건" 과 달리 **에러로 드러나는 실패**라 사각이 좁다.
  다만 필터 조건 (taxonomy 명칭) 변화로 인한 0건은 여전히 가능 — 감시 보강은 이 트랙 밖
  (트러블슈팅 문서에 아이디어로만 기록).
- buildId 는 GraphQL 엔드포인트와 무관해 배포마다 갱신할 값이 없다.
- fmkorea 접촉 없음 — 이 트랙은 arsenal.com 계열 (`afc-prd.graph.arsenal.com`) 만 접촉한다.
