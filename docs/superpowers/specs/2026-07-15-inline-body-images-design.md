# 본문 인라인 이미지 — 추출 · 저장 · 상세 렌더 설계 (2026-07-15)

v1 마감 3트랙 중 ② (로드맵 `../2026-06-28-v1-completion-roadmap.md` "v1 마감 범위").
수집 단계에서 기사 본문의 이미지를 추출 · 저장하고, 상세 페이지 본문 문단 사이에 렌더한다.
완료 기준은 상세 페이지에 본문 이미지가 표시되는 것.

## 배경 · 문제

- 현재 이미지는 기사당 og:image 1장 (`image_url`) 뿐 — 카드 썸네일 (16:9) 과 상세 히어로 (21:9) 가 이 한 장을 겸용하고, 본문은 텍스트만 흐른다.
- site-preview 목업 (미커밋, 참고용) 은 본문 흐름 중간에 16:9 이미지 블록 (`.body .imgph`) 을 배치하는 디자인이다.
- 본문 추출이 평문화 (`get_text(" ", strip=True)`) 라 원문의 이미지 위치는 물론 문단 경계도 추출 단계에서 소실되고, 번역 (Gemini) 이 문단을 재구성한다.
  → 원문 내 이미지 위치를 살리려면 추출 구조화 + 번역 마커 보존이 필요해 비용 · 리스크가 크다.

## 확정 결정 (brainstorming 합의)

- **위치 비보존**: 이미지 URL 목록만 원문 등장 순서로 저장하고, 렌더 시 문단 사이에 규칙 배치한다.
  번역 파이프라인 무접촉 · 마커 훼손 리스크 0 · 뉴스 요약 서비스에서 위치 오차의 실사용 비용이 낮다는 판단.
- **핫링크**: URL 참조만 저장한다. 다운로드 · 재호스팅은 하지 않는다 — 라이선스 이미지 (게티 등) 재배포 부담 회피, 현행 히어로와 동일한 지위.
- **히어로 관계**: 인라인 목록에서 히어로와 같은 이미지를 제거하고, og:image가 없으면 인라인 1번을 히어로로 승격한다.
- **소스 범위**: 원문 HTML을 확보하는 모든 경로 + fmkorea 게시글 + Guardian.
  fmkorea 게시글 이미지는 높은 확률로 원문 기사 이미지의 재게재라 포함한다 (사용자 결정).
- **광고 필터**: 본문 컨테이너 밖 · 광고 네트워크 · 아이콘류를 수집에서 제외한다 (사용자 요구).
- **백필 없음**: 신규 수집분부터 적용한다.
  하루 4회 수집으로 자연 누적되므로 트랙 ③ 캡처 시점에는 충분하고, 필요 시 ③에서 선별 백필을 추가한다.

## 설계

### 1. 데이터 모델 · 스키마

- `articles`에 `images_json TEXT` 컬럼 1개 추가 — JSON 배열 `["url1", "url2", ...]`, 원문 등장 순서, 저장 상한 10장.
- `schema.sql`의 기존 패턴 (`ADD COLUMN IF NOT EXISTS`) 으로 멱등 부트스트랩 — 수동 적용 불필요.
- 별도 테이블 대신 JSON 컬럼인 이유: 읽기 패턴이 기사 단위 렌더 하나뿐이라 조인 · 개별 쿼리가 필요 없다.
- pydantic `Article`에 `images: list[str] = []` 추가.
  기존 행은 NULL → 빈 목록으로 취급 (이미지 없는 기사와 동일 렌더).

### 2. 추출 — 공통 파서 + 소스별 연결

`meta.py`에 공통 함수 `extract_body_images(html, container_selector) -> list[str]`를 신설한다.

- 본문 컨테이너 내부의 `<img>`만 순서대로 수집한다.
- 필터:
  - 광고 · 트래커 도메인 제외 (doubleclick · taboola · outbrain · googlesyndication 등 소규모 하드코딩 목록)
  - `aside` · 관련기사 블록 내부 제외
  - `width`/`height` 속성 기준 한 변 120px 미만 제외 (아이콘 · 픽셀 트래커)
  - `data:` URI · `.svg` 제외
  - 동일 URL 중복 제거
- lazy-load 해석: `src`가 비었거나 플레이스홀더면 `data-src` → `srcset` (최대 해상도 후보) 순으로 실제 URL을 취한다.
  상대 URL은 기사 URL 기준으로 절대화한다.

소스별 연결 — 전부 이미 받아온 HTML 재사용, 신규 네트워크 요청 없음:

| 경로 | 연결 지점 |
|---|---|
| html 6곳 (arsenal_official · bbc_sport · bbc_gossip · goal · football_london · skysports) | `html.py` 기사 페이지 fetch 자리에서 `payload["images"]` 추가 |
| fmkorea → 비페이월 원문 | 원문 HTML에서 추출 |
| fmkorea → 페이월 (Athletic) | 게시글 본문 (`.xe_content`) 에서 추출 |
| x_afcstuff → 백트래킹 승격 | `resolve_and_fetch` 결과에서 추출해 `promote_cited_item`으로 전달 |
| guardian | `show-fields`에 `body` (HTML) 추가 후 해당 필드에서 추출 — `bodyText` 본문 경로는 무변경 |

- 제외: x_afcstuff 순수 트윗 (본문 없음, 트윗 이미지는 기존 `image_url` 경로 유지).

### 3. 저장 파이프라인

- `pipeline.to_articles`: `images=item.raw_payload.get("images") or []`.
- `MartStore` upsert와 `run.py` 컬럼 목록에 `images_json` 추가 — JSON 직렬화는 저장 직전 1곳.
- enrich (Gemini) 는 완전 무접촉 — 번역 프롬프트 · 기존 `body_ko` 데이터에 영향 없음.
- dbt 품질 게이트: nullable 신규 컬럼이라 기존 테스트에 영향 없음, 별도 게이트 추가 없음.

### 4. 렌더 — 인터리브 · 히어로 승격 · 방어

`render.py`:

- `images_json` 파싱 → 기존 `image_url`과 같은 정규식으로 URL 검증.
- 히어로 중복 제거: 쿼리스트링 제거 후 비교로 `image_url`과 같은 이미지를 인라인 목록에서 제외.
- 히어로 승격: `image_url`이 없으면 인라인 1번을 히어로 · 카드 썸네일로 쓰고 인라인 목록에서 제거.
  렌더 시점 승격이라 저장 데이터는 원형 유지.

`detail.html.j2` · CSS:

- 본문 문단 루프에서 2문단마다 이미지 1장 삽입, 이미지 소진 시 중단.
  문단보다 이미지가 많으면 잔여는 렌더하지 않는다.
- `<figure class="imgph"><img loading="lazy" referrerpolicy="no-referrer" onerror="figure 숨김"></figure>`
  → 핫링크 차단 (fmkorea CDN 포함) · 만료 URL은 빈 자리 없이 사라지는 실패 모드.
- CSS는 목업 `.body .imgph` (16:9 · 라운드) 를 실제 `<img>`용으로 옮겨 적용한다.
  site-preview/는 참고만 하고 커밋하지 않는다.

## 스코프 경계

- 포함: 인라인 이미지 추출 · 저장 · 상세 렌더, 부산물로서의 히어로 · 카드 채움율 개선 (승격), Guardian `body` 필드 추가.
- 제외: 인덱스 카드 UI 개편, 이미지 캡션 (위치 비보존과 함께 제외 — 캡션은 문단 맥락 종속이라 위치가 어긋나면 어색), 기존 296건 백필, 이미지 다운로드 인프라, 문서 · 캡처 (트랙 ③).

## 에러 처리

- 추출 실패 (파싱 예외 등) → 빈 목록 폴백.
  이미지는 부가 정보이므로 기사 수집 자체를 막지 않는다.
- 렌더: URL 검증 탈락 · `onerror` 숨김으로 깨진 이미지 미노출.

## 검증 · 완료 기준

- 단위: 추출 필터링 (광고 도메인 · 크기 · lazy-load · 상대 URL · 중복), 렌더 인터리브 (2문단 규칙 · 소진 · 잔여 버림), 히어로 중복 제거 · 승격.
- 라이브 (머지 전, 함정 노트 준수): 어댑터 단독 `fetch()`로 html 6곳 + fmkorea + Guardian에서 실제 이미지 수집 확인.
  단위 테스트는 모킹이라 셀렉터 드리프트를 못 잡는다.
  fmkorea는 접근 2h 간격 규칙 내 1회.
- 완료: 라이브 수집 후 상세 페이지에 본문 이미지 표시.

## 열어 둔 판단 (plan 단계 확정)

- 광고 · 트래커 도메인 목록의 최종 범위 — 단위 테스트 케이스로 고정한다.
- `extract_article_body` (fmkorea 원문 · 백트래킹 경로) 와 이미지 추출의 본문 컨테이너 공유 방식 — 같은 컨테이너 탐지 로직을 재사용할지, 별도 휴리스틱일지.

## 참조

- 로드맵: `../2026-06-28-v1-completion-roadmap.md` "v1 마감 범위 (2026-07-15 확정)"
- 디자인 목업: `site-preview/` (미커밋 — 카드 PHOTO 16:9 · 상세 HERO 21:9 · 본문 `.imgph`)
- 셀렉터 드리프트 함정: `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`
- fmkorea 정책 · 429 규칙: CLAUDE.md "자주 밟는 함정"
