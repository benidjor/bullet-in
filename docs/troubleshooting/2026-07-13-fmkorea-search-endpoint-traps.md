# fmkorea 검색 엔드포인트 함정 (2026-07-13)

fmkorea 어댑터를 첫 페이지 스캔에서 검색 엔드포인트로 전환 (PR #32) 하며 드러난, 검색 특유의 비자명한 함정 5종.
구 방식 (본문 원문 URL 추출 · 게시판 공지 의존) 함정은 `docs/troubleshooting/2026-06-29-fmkorea-discovery-extraction.md` 참조.

## 배경

- **대상** — fmkorea `search.php` 검색 결과로 아스날 · 전담기자 글을 수집하는 경로 (`src/bullet_in/adapters/fmkorea.py` 의 `_discover`) .
- **성격** — 아래 5종은 크래시가 아니라 조용히 0건 · 오탐 · 피드 오염으로 새는 함정이라, 값 · 로그 확인 없이는 발견이 어렵다.

## 함정 1 — 검색 결과 HTML 이 게시판 리스트와 다름

같은 셀렉터를 재사용하면 수집 0건이 되는 구조 차이.

- **증상** — 게시판용 `item_selector: a.title` 을 검색 결과에 쓰면 0건.
- **원인** — 검색 결과 페이지는 제목 앵커가 `a.hx` 이고, href 는 `/index.php?...&document_srl=NNNNN&...` 형태다 (게시판 리스트의 `a.title` · `/NNNNN` 와 다름) .
  - 댓글 수 앵커 `a.replyNum` 도 `document_srl` 을 담아, 무분별하게 긁으면 댓글 링크가 섞인다.
- **해결** — 검색 경로는 `item_selector: a.hx` 를 쓰고, href 에서 `document_srl` 을 뽑아 정규 글 URL `https://www.fmkorea.com/{srl}` 로 구성한다 (`_post_url_from_href`) .
  - `a.hx` 만 선택하면 `replyNum` 은 자연 제외된다.
- **예방** — fmkorea 셀렉터 변경 시 게시판 · 검색 두 경로를 구분해 라이브 검증한다 (모킹은 구조 차이를 못 잡음) .

## 함정 2 — 다단어 키워드가 공백에서 토큰 분리돼 오탐

기자명 등 공백 있는 키워드를 그냥 넣으면 엉뚱한 글이 섞인다.

- **증상** — `드 로셰` (The Athletic 아스날 기자) 로 검색하니 `로셰인 토마스` (다른 인물) 가 든 웨스트햄 글이 섞임.
- **원인** — fmkorea 검색은 공백으로 키워드를 토큰으로 쪼개 OR 매칭한다.
  `드 로셰` → `드` · `로셰` → `로셰인` 에 걸린다.
- **해결** — 라틴 정확구문을 따옴표로 감싼다 — `"de roche"` (fmkorea 본문에 원문 바이라인이 라틴으로도 실림) .
  - credibility alias 도 같은 이유로 bare `로셰` 는 넣지 않고 `드 로셰` · `드로셰` · `de roche` 만 쓴다.
- **예방** — 공백 · 짧은 토큰 키워드는 라이브 결과를 훑어 오탐을 확인한 뒤 채택한다.

## 함정 3 — 넓은 키워드 `title_content` 는 타팀 글로 피드를 오염

`아스날` 을 제목+본문으로 검색하면 본문에만 언급된 타팀 글이 대량 유입된다.

- **증상** — `아스날` 을 `search_target=title_content` 로 검색한 20건 중 13건이 본문에만 아스날이 언급된 타팀 · 일반 글 (맨유 · 맨시티 · 토트넘 · 본머스 등) 이었다.
  - fmkorea 는 소스가 fmkorea 면 `team` 을 아스날로 고정하므로, 이 타팀 글이 아스날 피드에 그대로 노출된다.
- **원인** — 이적 글은 본문에서 경쟁 구단을 교차 언급해, 본문 매칭은 본질적으로 노이즈가 많다.
- **해결** — 넓은 키워드 (`아스날`) 는 `search_target=title` 로 좁힌다 (방식 B) .
  - 전담기자 키워드 (`"de roche"` · `온스테인`) 는 바이라인이 제목이 아니라 본문에 있으므로 `title_content` 를 유지한다.
- **트레이드오프** — 선수명 제목 아스날 글 (제목에 아스날 없이 `가브리엘 …`) 중 비-전담기자 글은 놓칠 수 있다.
  - 전담기자 글은 기자 그물이 잡고, 그 외 링크 선수 글은 별도 워치리스트 track 대상이다.

## 함정 4 — 다중 키워드 union 의 순차 채움이 뒤 키워드를 굶김

`max_posts` 를 순서대로 채우면 앞 키워드가 cap 을 소진해 뒤 키워드가 무발화한다.

- **증상** — 키워드 순서가 `[아스날, "de roche", 온스테인]` 이고 `max_posts=15` 일 때, `아스날` 이 15건을 채우면 기자 그물 (de Roché · Ornstein) 이 한 건도 안 잡힌다.
  - 월드컵 저볼륨 등 아스날 글이 적을 땐 안 드러나, 정상 볼륨에서 조용히 핵심 기능이 죽는다.
- **원인** — `_discover` 가 키워드를 순회하며 `len(matched) >= max_posts` 에서 즉시 return 하면, 뒤 키워드는 검색조차 반영되지 않는다.
- **해결** — 키워드별 결과를 모아 라운드로빈으로 `max_posts` 를 배분한다 (`_round_robin`) .
  - 모든 그물이 cap 안에서 공평히 대표된다.
- **예방** — 다중 키워드 union 은 "cap 은 총량 · 배분은 라운드로빈" 을 기본으로 삼는다.

## 함정 5 — HTTP 430 rate-limit (429 아님)

반복 fetch 시 fmkorea 는 429 가 아니라 430 으로 차단한다.

- **증상** — 짧은 시간에 fetch 를 여러 번 돌리면 검색 GET 이 `HTTP 430` 을 반환하고 수집 0건 (20분+ 지속) .
- **원인** — fmkorea 고유 rate-limit 코드가 430 이다.
  429 만 처리하면 이 경우를 못 잡고 예외가 전파된다.
- **해결** — 검색 GET 실패는 429 뿐 아니라 그 외 HTTP 상태 · 전송 오류 (`httpx.HTTPError`) 도 그 키워드만 로깅 · 스킵해 다른 키워드의 부분 결과를 보존한다.
  - `gather_all` 의 소스별 격리로 타 소스는 무영향.
- **주의** — 실제 파이프라인은 하루 4회 저빈도라 430 은 반복 테스트 fetch 의 artifact 다.
  - 라이브 검증 시엔 fetch 간 충분한 간격을 둔다.

## 참고

- 어댑터 — `src/bullet_in/adapters/fmkorea.py` (`_discover` · `_post_url_from_href` · `_round_robin`) .
- 운영 절차 — `docs/runbook/2026-07-13-fmkorea-search-adapter-ops.md` .
- 설계 — `docs/superpowers/specs/2026-07-04-fmkorea-search-journalist-follow-design.md` .
- 구 방식 추출 함정 — `docs/troubleshooting/2026-06-29-fmkorea-discovery-extraction.md` .
