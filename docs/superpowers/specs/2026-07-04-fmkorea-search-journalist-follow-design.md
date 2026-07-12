# fmkorea 검색 경로 전환 · 아스날 전담기자 팔로우 설계 (2026-07-04)

fmkorea 어댑터가 football_news 첫 페이지만 스캔해 실행 간 밀려난 아스날 글 (특히 페이월 The Athletic 원문) 을 놓치는 문제를, fmkorea 검색 엔드포인트로 전환하고 아스날 전담기자 (Ornstein · de Roché) 정확구문 검색을 얹어 해소하는 설계.

## 배경 · 문제

현재 `FmkoreaAdapter` 는 `list_url` (football_news 게시판 첫 페이지) 을 1회 GET 해 `item_selector: a.title` 로 제목을 긁고, 제목에 `아스날` · `Arsenal` 이 든 글만 `max_posts` (10) 까지 취한다.

이 구조는 세 가지를 놓친다.

- **밀림** — football_news 는 전 축구 뉴스가 섞이는 고회전 게시판이라, 실행과 실행 사이에 떴다 밀려난 아스날 글은 첫 페이지 밖으로 사라져 영구 유실된다.
- **제목 한정** — `가브리엘의 블로킹` · `빅토르 요케레스와 자신감` 처럼 선수 · 감독명으로 된 아스날 글은 제목에 `아스날` 토큰이 없어 필터에서 탈락한다.
- **Athletic 변종 누락** — 말머리 `디 애슬래틱` (래) · 리터럴 `The Athletic` 은 `OUTLET_MAP` 에 없어 페이월 분기로 못 가고, 원문 fetch 를 시도하거나 드롭된다.

라이브 검증 (2026-07-04) 근거.

- 실행 1회 수집이 2건에 그쳤고 그중 Athletic 은 0건이었다 (월드컵 저볼륨 · 첫 페이지 밀림 복합).
- fmkorea 검색 `search.php?...search_keyword=아스날&search_target=title_content` 는 `[디 애슬레틱]` · `[BBC]` · `[더 선]` · `[텔레그래프]` 등 키워드 정밀 매칭된 아스날 글을 페이지 밀림 없이 반환한다.
- 검색 `"de roche"` (따옴표 정확구문) 는 20건 전부 The Athletic 이며 오염 0건, 그중 19건이 `아스날` 검색 첫 페이지에 없는 de Roché 아스날 분석글이었다.

## 목적 · 성공 기준

- fmkorea 어댑터가 검색 엔드포인트 기반으로 아스날 글을 밀림 없이 수집한다.
- Ornstein · de Roché (Athletic 아스날 전담기자) 의 글을 정확구문 검색으로 팔로우한다 (비-아스날 글 포함, 아래 '설계 결정' 참조).
- Athletic 말머리 변종을 모두 페이월 분기로 라우팅해 한국어 본문을 보존한다.
- de Roché 를 credibility 에 등록해 본문 바이라인으로 tier 를 귀속한다.
- 수집 결과를 경로별로 브리핑하고, 프론트엔드 미리보기 화면으로 확인한다.

## 설계 결정 (합의)

- **아스날 관련성 가드 없음** — 기자 정확구문 검색 결과는 전부 수용한다.
  즉 de Roché 가 (공동) 기고한 비-아스날 Athletic 글 (PSG · 일반 PL 등) 도 피드에 포함된다.
- **근거** — 사용자 의도는 "아스날 전담기자의 기사를 볼 수 있게" 이므로, 팀 필터가 아니라 기자 팔로우가 목표다.
  아스날 전용 피드에 기자 팔로우를 더한 형태가 된다.
- **정확구문 필수** — fmkorea 검색은 공백으로 토큰을 쪼개 OR 매칭한다.
  `드 로셰` 를 그냥 넣으면 `드` · `로셰` 로 쪼개져 `로셰인 토마스` (다른 인물) 같은 오탐이 섞이므로, 라틴 정확구문 `"de roche"` 를 쓴다.
- **아스날 넓은 그물은 제목 한정 (`search_target=title`)** — 라이브 검증 (2026-07-04) 에서 `아스날` 제목+본문 검색 20건 중 13건이 본문에만 아스날이 언급된 타팀 · 일반 글 (맨유 · 맨시티 · 토트넘 · 본머스 등) 이었다.
  피드 오염을 막기 위해 `아스날` 키워드는 제목 검색으로 좁힌다.
- **기자 그물은 제목+본문 (`search_target=title_content`)** — Ornstein · de Roché 바이라인은 본문에 있어 제목+본문 검색을 유지한다.
  선수명 제목 아스날 분석글 (`가브리엘의 블로킹` 등) 은 전담기자 그물이 잡는다.
- **키워드별 라운드로빈 cap** — `max_posts` 는 키워드를 순서대로 채우지 않고 라운드로빈으로 배분한다.
  순차 채움은 앞 키워드 (`아스날`) 가 cap 을 소진해 뒤 키워드 (기자 그물) 를 굶기기 때문이다.
- **검색 GET 실패는 그 키워드만 스킵** — 429 뿐 아니라 그 외 HTTP · 전송 오류도 그 키워드 회차만 로깅 · 스킵해 다른 키워드의 부분 결과를 보존한다.

## 컴포넌트

### 1. fmkorea 어댑터 — 다중 키워드 검색 union

`FmkoreaAdapter` 를 첫 페이지 스캔에서 검색 엔드포인트 union 으로 바꾼다.

- **검색 키워드 3종** — `아스날` (전 아웃렛 아스날 넓은 그물) · `"de roche"` (정확구문) · `온스테인` .
  각 키워드로 `search.php?mid=<board>&search_keyword=<kw>&search_target=<target>` 를 GET 한다 (`아스날` → title · 기자 → title_content) .
  키워드별 `target` 을 포함한 키워드 목록 · 검색 URL 템플릿은 config 로 뺀다 (`config/sources.yaml` 의 fmkorea `config`) .
- **결과 파싱** — 검색 결과 제목 앵커는 `a.hx` 다 (`a.title` 아님) .
  댓글 수 앵커 `a.replyNum` 은 제외한다.
  href 는 `/index.php?...&document_srl=NNNNN&...` 형태이므로, `document_srl` 을 뽑아 정규 글 URL `https://www.fmkorea.com/{srl}` 로 구성한다.
- **union · dedup** — 3개 검색 결과를 `document_srl` 기준으로 합치고 중복을 제거한다 (한 글이 여러 키워드에 걸려도 1건) .
  `max_posts` 는 키워드별 라운드로빈으로 배분해 모든 그물이 대표되게 한다 (순차 채움 금지) .
- **제목 키워드 필터 제거** — 각 검색 키워드가 곧 relevance 이므로 기존 `_matches` (제목에 아스날 포함) 는 쓰지 않는다.
  이래야 전담기자의 선수명 아스날 글 · 비-아스날 글이 통과한다.
- **본문 · 라우팅 · RawItem 생성** — 기존 로직을 재사용한다.
  글 fetch → `parse_bracket` 로 말머리 outlet · journalist 파싱 → `_extract_original_url` 로 원문 URL → outlet 이 페이월이면 한국어 본문 보존 (lang=ko) , 무료면 원문 fetch (lang=en) .
- **429 · fetch 실패** — 검색 GET 이 429 면 그 키워드 회차만 스킵하고 로깅한다 (기존 리스트 429 처리와 동형) .
  개별 글 fetch 실패는 그 글만 스킵하고 배치는 지속한다.

### 2. Athletic 말머리 변종 매핑

`parse_bracket` 이 참조하는 `OUTLET_MAP` 에 Athletic 변종을 추가한다.

- `디 애슬래틱` (래) → `The Athletic` .
- `The Athletic` 리터럴 → `The Athletic` (이미 통과하나 명시) .
- 기존 `디 애슬레틱` · `디애슬레틱` 유지.
- 효과 — 변종 말머리 글이 `PAYWALLED_OUTLETS` 분기로 가 한국어 본문을 보존한다.

### 3. credibility.yaml — Art de Roché 등록

`journalists` 에 항목을 추가한다.

- `{name: Art de Roché, tier: 1.5, aliases: ["드 로셰", "드로셰", "de roche"]}` .
- bare `로셰` 는 `로셰인` 오탐 위험이라 alias 에서 제외한다.
- 근거 — `resolve_tier` 의 fmkorea 분기는 제목 + 본문 소문자 substring 으로 journalist alias 를 매칭하므로, 본문 바이라인 (드 로셰 · de Roche) 이 tier 1.5 로 귀속된다.

### 4. Part 2 — 수집 브리핑

새 어댑터를 라이브 `fetch()` 로 실행하고 결과를 정리해 보고한다.

- 총 수집 건수 · 아웃렛 분포.
- 키워드 경로별 예시 (아스날 net vs de Roché · Ornstein net) .
- Athletic 페이월 보존 건수 · de Roché · Ornstein 아스날 글 캡처 예시.

### 5. Part 3 — 프론트엔드 반영 미리보기

Part 2 에서 수집한 글을 실제 서빙 렌더러로 화면에 반영한다.

- 수집 RawItem 을 `articles` 행 dict 로 변환해 `write_site` 로 미리보기 디렉터리 (예: `site-preview/`) 에 렌더한다.
- fmkorea 제목은 이미 한국어라 그대로 렌더되고, 3줄 요약은 Gemini paraphrase 를 이 소량 건에만 실행한다.
- 완성된 index · 상세 HTML 을 브라우저로 열어 화면 · 스크린샷으로 제시한다.
- 전체 DB 파이프라인 대신 이 글들에 집중한 미리보기다 (사용자 요청 "2번에서 가져온 기사들" 에 대응) .

## 데이터 흐름

```
search.php(아스날)      ┐
search.php("de roche")  ├─→ a.hx 파싱 · document_srl 정규화 ─→ union·dedup
search.php(온스테인)    ┘
   ─→ 글 fetch ─→ parse_bracket(outlet·journalist)
       ─→ 페이월(Athletic 변종 포함): 한국어 본문 보존(ko)
       ─→ 무료: 원문 fetch(en)
   ─→ RawItem[]  ─→ [Part2 브리핑]  ─→ write_site(site-preview) ─→ [Part3 화면]
```

## 테스트

- **단위 (모킹)** — 검색 결과 HTML 픽스처로 `a.hx` 파싱 · `replyNum` 제외 · `document_srl` 정규화 · union dedup 을 검증한다.
- **단위** — `parse_bracket` 이 `디 애슬래틱` · `The Athletic` 변종을 The Athletic 으로 매핑하는지 검증한다.
- **단위** — de Roché 본문 픽스처에 `resolve_tier` 가 tier 1.5 를 부여하는지 검증한다.
- **라이브** — 실 `fetch()` 로 셀렉터 · 검색 · 페이월 분기를 확인한다 (모킹이 못 잡는 드리프트) .
- **미리보기 렌더** — 수집 건으로 `write_site` 가 index · 상세 HTML 을 생성하는지 확인한다.

## 범위 밖 (YAGNI)

- 검색 페이지네이션 (2페이지 이상) — 첫 페이지 검색 결과로 충분한지 라이브로 판단 후 필요 시 별건.
- afcstuff X 경로 (SP2-a) 튜닝 — 이번 트랙과 무관, 월드컵 종료 후 재측정.
- SP2-b (Athletic URL ↔ fmkorea 능동 연결) — 수동 경로가 Athletic 을 커버하므로 불필요 (드롭 확정) .
- 아스날 링크 선수 워치리스트 — 제목에 아스날 없이 선수명 + 이적 키워드 (관심 · 이적 · 협상) 로 링크 선수의 타팀 이적 글을 잡는 아이디어.
  선수 DB 큐레이션 · 선수별 검색 비용 (429) · 노후 정리가 필요한 별도 서브시스템이라 자체 track 으로 분리한다.

## 참조

- 어댑터 — `src/bullet_in/adapters/fmkorea.py` .
- tier 산출 — `src/bullet_in/credibility.py` (`resolve_tier` fmkorea 분기) .
- 서빙 렌더 — `src/bullet_in/serve/render.py` (`write_site`) .
- 설정 — `config/sources.yaml` · `config/credibility.yaml` .
