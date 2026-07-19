# fmkorea 검색 어댑터 운영 (2026-07-13)

fmkorea 검색 엔드포인트 어댑터 (`fmkorea`, PR #32) 의 운영 절차 · 라이브 검증 · 실패 진단.
비자명한 함정은 `docs/troubleshooting/2026-07-13-fmkorea-search-endpoint-traps.md` 참조.

## 목적

- fmkorea `search.php` 를 키워드별로 검색해 아스날 · The Athletic 전담기자 (Ornstein · de Roché) 글을 수집.
- 게시판 첫 페이지 스캔의 밀림 (실행 간 밀려난 글 유실) 을 검색 엔드포인트로 해소.

## 검색 구성

`config/sources.yaml` 의 fmkorea `config` 로 검색을 제어한다.

- **`search_url`** — `{keyword}` · `{target}` 자리표시를 담은 템플릿 (`search.php?...&search_target={target}&search_keyword={keyword}`) .
- **`search_keywords`** — 키워드별 `{keyword, target}` 목록.
  - `아스날` → `title` (제목 한정, 타팀 오염 차단) .
  - `"de roche"` · `온스테인` → `title_content` (기자 바이라인은 본문에 있음) .
- **`item_selector`** — `a.hx` (검색 결과 제목 앵커, 게시판 `a.title` 아님) .
- **`max_posts`** — union 총량 cap. 키워드별 라운드로빈으로 배분.

## 라이브 검증 (머지 전 · 정기)

셀렉터 · 검색 구조 · 페이월 분기는 모킹이 못 잡으므로 실 `fetch()` 로 확인한다.

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import asyncio, yaml, logging, sys
from collections import Counter
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open("config/sources.yaml"))
adp = [a for a in build_adapters(cfg) if a.source_id == "fmkorea"][0]
items = asyncio.run(adp.fetch())
print("수집:", len(items))
print("아웃렛:", dict(Counter(i.raw_payload["outlet"] for i in items)))
print("페이월(ko):", sum(1 for i in items if i.raw_payload["lang"] == "ko"))
for i in items[:8]:
    p = i.raw_payload
    print(" ", p["outlet"], "|", p["lang"], "|", (p["title"] or "")[:60])
PY
```

- **기대** — 아스날 · Athletic 글이 수집되고, Athletic (페이월) 은 `lang=ko` (한국어 본문 보존) , 무료 아웃렛은 `lang=en` (원문 영어 본문) .
- **전담기자 확인** — `[디 애슬레틱-온스테인]` 등 기자 그물 글이 섞여 나오면 라운드로빈이 정상 발화 중.

## 로그 해석 (INFO `bullet_in.adapters.fmkorea`)

로그 문구별 의미 · 조치.

- **`검색 429(rate limit) kw=…`** — 그 키워드 검색이 rate-limit. 그 회차만 스킵 (다음 사이클 누적) .
- **`검색 HTTP <code> kw=…`** — 429 외 상태 (특히 `430` = fmkorea rate-limit) . 그 키워드만 스킵.
- **`검색 실패 kw=… err=…`** — 전송 오류 (타임아웃 · 연결) . 그 키워드만 스킵.
- **`원문/말머리 해소 실패 — 스킵 url=…`** — 말머리 파싱 실패 또는 본문에 원문 URL 부재. 그 글만 드롭.
- **`퍼가기 금지 + 페이월 — 헤드라인만 저장 url=…`** — 퍼가기 금지 글의 페이월 (Athletic) 분기.
  본문 · 게시글 이미지 미복제, 헤드라인 + 출처 · tier + 원문 링크만 저장 (spec §9.1 ②). 정상 동작.

## 퍼가기 금지 글 처리 (spec §9.1)

작성자 직접 번역 2차 저작물에 붙는 '퍼가기 금지' 표식의 감지 · 분기 (2026-07-19 구현).

- **표식 실측 DOM** — `[퍼가기가 금지된 글입니다 - …]` `<strong>` 이 `.rd_body` 직하위 · 본문 (`.xe_content`) · 댓글 영역 밖.
  `_is_repost_blocked()` 는 이 구조로 감지해 본문이 문구를 인용해도 오탐하지 않는다.
- **무료 아웃렛** — 분기 불필요. 현행 무료 경로가 원문을 fetch 해 en 본문을 쓰므로 fmkorea 본문은 원래 미복제.
- **페이월 (Athletic)** — 감지 시 헤드라인-온리 (위 로그). og 이미지는 원문 기사에서 가져오므로 유지.
- **표식 드리프트 주의** — fmkorea 가 표식 문구 · 위치를 바꾸면 감지가 조용히 꺼져 본문 복제가 재개된다.
  Athletic 항목의 body 유무 분포가 갑자기 전건 채움으로 돌아오면 표식 드리프트를 의심하고 실DOM 재확인.

## 키워드 · target 튜닝

`config/sources.yaml` 의 `search_keywords` 를 관측 근거로 조정한다.

- **넓은 그물** — 팀 키워드 (`아스날`) 는 `title` 유지 (타팀 오염 차단) .
- **기자 추가** — 새 전담기자는 `title_content` 로 추가하되, 공백 있는 이름은 따옴표 정확구문 (`"de roche"`) 으로 넣어 토큰 분리 오탐을 막는다.
- **cap** — `max_posts` 는 union 총량. 키워드 수 대비 너무 낮으면 각 그물 대표 수가 줄고, 너무 높으면 글당 fetch 가 늘어 430 위험.

## rate-limit (HTTP 430) 주의

fmkorea 는 반복 fetch 를 430 으로 차단한다.

- **원인** — 짧은 시간에 fetch 를 여러 번 돌리면 430 (429 아님) · 20분+ 지속.
- **정상 운영** — 파이프라인은 하루 4회 저빈도라 무관. 어댑터가 430 을 키워드별 스킵해 크래시 없이 degrade.
- **라이브 검증 시** — fetch 간 충분한 간격을 두고, 연속 재실행을 피한다.

## 셀렉터 드리프트 진단

수집이 갑자기 0건이면 아래로 분기한다.

```
수집 0
  ├─ 로그에 430/429/HTTP        → rate-limit (간격 두고 재시도)
  ├─ 로그 조용 · 검색은 200     → a.hx 셀렉터 드리프트 (검색 결과 HTML 재확인)
  └─ 원문/말머리 해소 실패 다수  → 말머리 형식 · 본문 출처 URL 관례 변경
```

## 롤백

- **소스 끄기** — `config/sources.yaml` 에서 `fmkorea.enabled: false` 로 즉시 비활성.
- **검색 키워드 되돌리기** — `search_keywords` 를 이전 값으로 되돌림.
- **마이그레이션 불필요** — DB 스키마 변경이 없어 되돌림에 마이그레이션이 불필요하다.

## 참고

- 어댑터 — `src/bullet_in/adapters/fmkorea.py` .
- 함정 — `docs/troubleshooting/2026-07-13-fmkorea-search-endpoint-traps.md` .
- tier 산출 — `src/bullet_in/credibility.py` (`resolve_tier` fmkorea 분기, 제목+본문 substring) .
- 설계 — `docs/superpowers/specs/2026-07-04-fmkorea-search-journalist-follow-design.md` .
