# 설계 — fmkorea '퍼가기 금지' 글 처리 정책

`2026-06-11-source-credibility-design.md` §9.1 (미구현 · 이연)을 **실제 DOM 실측**으로 해소하는 설계.
live-e2e 트랙에서 fmkorea 소스를 활성화하기 위한 마지막 정책 조각.

## 0. 배경

fmkorea '축구 소식통' 보드의 일부 글은 작성자가 직접 번역한 2차 저작물이며 **'퍼가기 금지'**
표식이 붙는다 (예: `https://www.fmkorea.com/9940576222`). 이 번역 본문을 그대로 복제 · 요약해
서빙하면 저작권 · 평판 문제가 생긴다. §9.1은 "실제 페이지 없이는 추측"이라 이연됐고, 본 설계는
2026-06-28 실측 DOM을 근거로 확정한다.

### 0.1 실측으로 확정된 사실 (2026-06-28)

- **퍼가기 금지 표식**: `</article>` 바깥 `<strong>`에 고정 문자열 `[퍼가기가 금지된 글입니다 - 캡처
  방지 위해 글 열람 사용자 아이디/아이피가 자동으로 표기됩니다]`. 차단글 1건 · 일반글 0건으로 구분됨.
- **원문 링크**: 차단글 본문 (`.xe_content`) 말미에 **평문 URL** (`<p>https://m.gianlucadimarzio.com/...</p>`)로
  존재. `<a href>` 앵커가 아니다.
- **원문 사이트**: `og:title`/`og:description`가 안정적으로 존재 (예시는 이탈리아어). 전체 본문 스크래핑은
  `<article>` 없음 · `<p>` 소수 · JS 의존으로 취약 → og 메타만 사용.
- **리스트 셀렉터 드리프트**: config의 `item_selector: "h3.title a"`는 현재 DOM에서 **0 hit**.
  실제는 `a.title`(22 hit).

## 1. 범위

- **변경 파일**: `src/bullet_in/adapters/fmkorea.py`, `config/sources.yaml`, `tests/test_fmkorea_adapter.py`.
- **무변경 (중요)**: 스키마 (`schema.sql`), `enrich.py`, `models.py`, `pipeline.py`. 분기 ①을 기존 ko 경로에
  올려 per-item 번역 라우팅 · 스키마 변경을 회피한다 (§3.2 근거).

## 2. 감지 (detection)

```python
_REPOST_MARK = "퍼가기가 금지된 글입니다"
def _is_repost_blocked(article_html: str) -> bool:
    return _REPOST_MARK in article_html
```

## 3. 처리 분기

글 본문 HTML을 받아 분기한다.

| 조건 | `url` | `title`(원제목) | `body`(요약 입력) | `lang` | 결과 |
|---|---|---|---|---|---|
| 차단 + 원문URL + og 성공 (**분기①**) | **원문 URL** | fmkorea 한국어 헤드라인 | 원문 `og:description` | `ko` | ko경로: 제목 유지 + og 기반 ko 요약. **fmkorea 번역 본문 미저장** |
| 차단 + URL없음/og실패 (**분기②**) | 원문URL 또는 fmkorea | fmkorea 헤드라인 | 비움 | `ko` | 헤드라인+출처+tier+링크만 |
| 비차단 (**현행**) | fmkorea | 제목 | fmkorea 본문 | `ko` | 현행 ko 요약 |

### 3.1 원문 URL 추출

`.xe_content` 내부에서 **첫 외부 http(s) URL** (평문 · href 모두, fmkorea 도메인 제외)을 취한다.

### 3.2 분기①이 기존 ko 경로에 올라타는 근거

- `enrich.partition_translation_rows`는 `sources[source_id].lang`로만 ko/en 경로를 가른다. fmkorea는
  config `lang: ko`이므로 모든 fmkorea 글이 ko 경로 (`summarize_ko_rows`)로 간다.
- ko 경로는 번역 없이 `summary_ko`만 생성하되, **입력이 외국어여도 Gemini가 한국어 요약을 산출**한다.
  `title_ko`는 `title_original`을 그대로 둔다.
- 따라서 분기①의 **제목을 fmkorea 한국어 헤드라인**으로 두면 (이미 한국어) 번역이 불필요하고, **요약
  입력만 원문 og:description**으로 바꾸면 ko 경로가 그대로 동작한다. → 스키마 · enrich · 모델 변경 0.
- 헤드라인 재사용은 §9.1 분기 ②가 "헤드라인은 허용"으로 이미 승인한 범위. 저작권 핵심인 **본문**만
  복제하지 않으면 된다.

> 알려진 사소한 비용: 분기② (빈 body)도 ko 경로에 포함되어 Gemini 요약 호출을 1회 소비한다 (429 예산).
> 분기②는 og 추출 실패 시의 드문 폴백이라 허용하며, enrich 무변경 원칙 (§1)을 깨면서까지 빈 body를
> 필터링하지 않는다. 빈도가 문제되면 후속에서 다룬다.

### 3.3 원문 메타 추출

원문 URL을 fetch (리다이렉트 추적)해 `og:title`/`og:description`(없으면 `meta[name=description]`)을
추출. 둘 다 없으면 분기②로 폴백.

## 4. 저작권 · 출처 원칙

- 차단글: fmkorea **번역 본문 미복제** (raw 저장도 안 함). 서빙 링크 (`url`)는 **원 출처**를 가리킨다.
- tier: 제목 대괄호 매체명 → `credibility.resolve_tier`의 매체 tier(예: 디 마르지오→ITK). 분기①에서
  body가 og:description (외국어)이라 본문 기자명 매칭은 기대하지 않고 매체 tier로 귀결되며, 없으면
  기존 폴백 (4). 이는 §9.1과 일관.

## 5. 안티봇 / 429

- 현재 fmkorea는 200 정상 응답. 다만 리스트 fetch의 `raise_for_status()`가 429에 어댑터를 크래시시키므로,
  **429 식별 시 `WARNING` 로깅 + `[]` 반환** (enrich의 429 철학과 일관, 배치 보호). 글 단위 fetch는 이미
  `HTTPError` 스킵.

## 6. 부수 수정 (필수 — 라이브 검증 게이트)

- `config/sources.yaml`: `item_selector: "h3.title a"` → **`a.title`** (드리프트 수정). 미수정 시 글 0건
  매칭이라 정책을 라이브 검증할 수 없다.
- 정책 구현 · 검증 후 `enabled: false` → `true`.

## 7. 테스트

- `tests/test_fmkorea_adapter.py`(모킹 HTML):
  - (a) 차단 표식 감지 `_is_repost_blocked`.
  - (b) `.xe_content` 평문 원문 URL 추출.
  - (c) og 추출 성공 → 분기① (url=원문, title=헤드라인, body=og:description).
  - (d) og 없음/URL 없음 → 분기② (body 비움).
  - (e) 비차단 글 → 현행 (fmkorea 본문 저장) 유지.
- 머지 전 어댑터 단독 `fetch()` **라이브 스모크** (수동) — 셀렉터 드리프트 함정 대응.

## 8. 성공 기준

- 단위 테스트 (a)~(e) 통과.
- 라이브 스모크: 차단 아스날 글이 원문 링크로 치환되고 fmkorea 번역 본문이 저장되지 않음을 확인.
- `enabled: true` 상태로 종단 실행 시 fmkorea 글이 서빙 페이지에 원 출처 링크로 노출.
