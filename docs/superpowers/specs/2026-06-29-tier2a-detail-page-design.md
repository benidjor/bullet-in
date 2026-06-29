# Bullet-in Tier 2-a — 전체 본문 번역 · 3줄 요약 · 기사 상세 페이지 · 웹 UI 개편 설계

- **작성일**: 2026-06-29
- **상태**: 설계 합의 완료 (구현 전)
- **출처 로드맵**: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` Tier 2
- **한 줄 정의**: EN 소스 전체 본문을 수집 · 번역하고, 1줄/3줄 요약과 대표 이미지를 붙여, 헤드라인 클릭 시 별도 상세 페이지 (상단 3줄 요약 + 전체 번역 본문 + 출처)를 보여주며, 검색 · 필터 · 다크모드를 갖춘 정적 웹 UI로 개편한다.

---

## 1. 목표 & 성공 기준

**목표**
- EN 소스 기사 **전체 본문**을 수집하고 한국어로 **전체 번역**한다.
- 1줄 요약 (인덱스용) + **3줄 요약** (상세용)을 생성한다.
- 헤드라인 클릭 → **별도 상세 페이지** (상단 3줄 요약 + 하단 전체 번역 본문 + 출처 + 하단 기사 목록).
- fmkorea를 **발견 (discovery) 소스**로 재정의: 글의 원 (原) 언론사 기사를 찾아 처리 (아래 §4.3).
- 정적 웹 UI 개편: 이미지 카드 인덱스 + 상단 검색 + 좌측 필터 사이드바 + 라이트/다크.

**성공 기준 (검증 가능)**
1. EN 소스 기사의 상세 페이지에 **전체 번역 본문 + 3줄 요약 + 출처 링크**가 표시된다.
2. fmkorea 글: 출처가 **디 애슬레틱이면** fmkorea 번역본을 문장 변형해 표시, **그 외 무료 매체면** 원문을 fetch해 직접 번역해 표시한다.
3. EN 소스와 fmkorea가 **같은 원문 URL**을 가리키면 한 기사로 합쳐지고, **EN 쪽이 남는다**.
4. 인덱스 카드 클릭 시 해당 기사 **상세 페이지 (별도 HTML)** 로 이동한다.
5. 검색창이 카드를 실시간 필터하고, 사이드바 (팀 · 소스 · 티어 · 정렬)는 **`필터 적용`** 시 반영, **`초기화`** 시 기본값 복원된다.
6. 라이트/다크 토글이 동작하고 페이지 간 유지된다.
7. 상세 페이지 하단에 **현재 기사 포함 5개** 목록이 현재 글을 중심으로 표시된다 (가장자리는 슬라이딩 윈도우).

---

## 2. 스코프

### 2-a (이번 spec / 이번 PR)
- EN 소스 전체 본문 수집 (어댑터 `body_selector`).
- 대표 이미지 (`og:image`) 수집 → 썸네일/히어로.
- enrich 확장: 단일 호출로 `title_ko` + `summary_ko` (1줄) + `summary3_ko` (3줄) + `body_ko` (전체).
- fmkorea 발견 소스화 (말머리 파싱 · 원문 URL 추출 개선 · 디 애슬레틱 변형 분기).
- dedup: 원문 URL 기준, EN/X 우선.
- 서빙 개편: 이미지 카드 인덱스 + 상세 페이지 (별도 파일) + 검색 + 사이드바 필터 (**팀 · 소스 · 티어 · 정렬**) + 라이트/다크 + 상단 내비.

### 2-b (후속 spec / 별도 PR) — **이번 범위 아님**
- **영입 단계 분류 · 필터** (루머→관심→협상→개인합의→메디컬→오피셜): 기사별 LLM 단계 태깅 필요.
- 본문 **인라인 이미지** (`<figure>`) 수집 · 표시.
- 소개/일정 페이지 콘텐츠.
- URL이 다른 **같은-사건 의미 dedup** (헤드라인 · 기자 매칭) = corroboration stretch.
- 타 구단 (Man Utd · Chelsea 등) 실데이터 수집 (이번엔 UI 필터 자리만 마련, `team` 필드 도입).

---

## 3. 데이터 모델 변경

### 3.1 `articles` 테이블 (스키마) 신규 컬럼
| 컬럼 | 타입 | 용도 |
|---|---|---|
| `summary3_ko` | TEXT | 3줄 요약 (줄바꿈 `\n` 구분). 상세 상단용. |
| `body_ko` | TEXT | 표시용 한국어 **전체 본문**. |
| `body_source` | TEXT | 수집된 원본 본문 (EN 원문 / 디 애슬레틱은 fmkorea 번역본). enrich 입력 · 재처리용. |
| `image_url` | VARCHAR (1024) | 대표 이미지 (og:image) URL. |
| `outlet` | VARCHAR (128) | 표시 언론사명 (예: BBC, The Athletic). `source_id` (수집 경로)와 구분. |
| `journalist` | VARCHAR (128) NULL | 기자/바이라인 (있을 때). |
| `team` | VARCHAR (32) DEFAULT 'arsenal' | 팀 필터용. v1은 arsenal 고정. |

- `summary_ko` (기존, 1줄)는 그대로 유지 — 인덱스 카드용. `summary3_ko`는 상세용 (설계 선택 B: 1줄/3줄 분리).
- 마이그레이션: `schema.sql`에 컬럼 추가 (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 또는 신규 `CREATE` 반영). `ensure_schema()` 멱등 적용 흐름 유지.

### 3.2 `Article` 모델 (`models.py`)
위 컬럼에 대응하는 필드 추가 (`summary3_ko`, `body_ko`, `body_source`, `image_url`, `outlet`, `journalist`, `team`). 기존 필드는 보존.

---

## 4. 수집 (어댑터) 변경

### 4.1 EN 소스 전체 본문 — `HtmlAdapter`에 `body_selector` 추가 (선택 A)
- fmkorea 어댑터와 동일 패턴: 목록 수집 후 각 기사 URL을 추가 fetch → `body_selector`로 본문 추출 → `raw_payload["body"]`.
- 소스별 `body_selector`를 `config/sources.yaml`에 추가 (BBC · football.london · arsenal 등). **머지 전 어댑터 단독 `fetch()` 라이브 검증 필수** (셀렉터 드리프트 — `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`).
- 부분 실패 규칙: 본문 fetch 실패 시 제목만 저장하고 `body_ko`는 비워 둠 (다음 회차 재시도). 배치는 지속.

### 4.2 대표 이미지 (`og:image`)
- 각 기사 상세 fetch 시 `og:image` (없으면 `twitter:image`) 메타를 추출해 `image_url`에 저장.
- 유료 매체 (디 애슬레틱) fmkorea 경로의 이미지는 **fmkorea 재업로드본이 아니라 원문 페이지 og:image**를 사용 (정책 안전).

### 4.3 fmkorea = 발견 소스 (재정의)
fmkorea 축구소식통 게시판 규칙 (공지 818271708 · 8677095961 · 9299550074)에 근거:
- **말머리 `[언론사]`/`[언론사 - 기자]`/`[언론사-독점]` 필수** → 언론사 · 기자 · `독점` 플래그를 제목에서 파싱.
- **출처 링크 필수** (본문 끝 평문 URL) · **인용기사 · SNS 출처 금지** (원문=정식 기사) · **국내 (KO) · 해외 (EN) 중복 시 국내 삭제** (EN 우선).

처리 흐름:
1. og:title에서 말머리 파싱 → `outlet`, `journalist`, `독점` 여부. (한글 언론사명 → 정규 표기 매핑 테이블: `디 애슬레틱`→The Athletic 등. 못 읽으면 폴백.)
2. 본문에서 **원문 URL 추출** — 현재 `_extract_original_url`이 `a[href]`를 평문보다 우선해 **기자 프로필/임베드 링크를 오인**하는 버그가 있음 (실측: post 10007542458). → **본문 끝 평문 출처 URL을 우선**하도록 수정.
3. 분기:
   - **디 애슬레틱 (유료, 하드코딩 목록)**: 영어 원문 접근 불가 → **fmkorea 한국어 번역본을 enrich에서 문장 변형 (paraphrase)** 하여 `body_ko`/요약 생성. `body_source`=fmkorea 번역본.
   - **그 외 (무료)**: 원문 URL fetch → `body_source`=영어 원문 → enrich에서 **직접 번역**.
   - **원문 URL/말머리 둘 다 실패**: 그 글 **스킵 + WARNING 로깅** (fmkorea 자체 텍스트는 표시하지 않음).
4. `article.url` = **원문 URL** (디 애슬레틱은 원문 기사 URL) → §6 dedup이 EN/X와 자동 병합.

> 유료 매체 목록은 **`디 애슬레틱` 하나만** 하드코딩 (설정 리스트로 두어 향후 추가 가능).

---

## 5. Enrich 변경

### 5.1 단일 호출 통합 출력
- EN/무료 경로 프롬프트: 입력 `title_original` + `body_source` → 출력 JSON
  `{ "title_ko", "summary_ko"(1줄), "summary3_ko"(문자열 3개 배열), "body_ko"(전체 번역) }`.
  - `summary3_ko`는 모델이 **3개 문자열 배열**로 반환 → 저장 시 `\n`으로 join해 TEXT 컬럼에 보관 (표시에서 `\n` 분해).
- 호출 수는 **기사당 1콜 유지** (RPM 불변), `max_output_tokens`만 전체 본문에 맞게 상향. 429 전략 (4회/일 멱등 누적 · 429 시 회차 중단)은 그대로 재사용.
- 파싱: 기존 `_extract` 정규식 안전망 확장 (4키). 일부 키 누락 시 해당 기사 스킵 + 로깅 (멱등 재시도).

### 5.2 디 애슬레틱 (유료) 변형 프롬프트
- 입력: fmkorea 한국어 번역본 (`body_source`). 작업: **번역이 아니라 문장 변형 (paraphrase)** + 1줄/3줄 요약. 사실 · 수치 · 고유명사 · 인용 불변 (의미 보존), 표현만 변경. 출력 JSON 동형.

### 5.3 KO 경로 (기존 `summarize_ko_rows`)
- fmkorea가 디 애슬레틱 외 무료 매체 원문으로 해소되면 EN 경로를 타므로, 순수 KO 요약 경로의 비중은 축소. 디 애슬레틱 변형 경로가 이를 대체.

### 5.4 멱등 트리거 & 저장
- `rows_missing_translation()`: 트리거는 `title_ko IS NULL` 유지 (미번역분만).
- `set_translation()`: `title_ko` · `summary_ko` · `summary3_ko` · `body_ko`를 함께 기록하도록 확장.
- `upsert()` INSERT/UPDATE 컬럼 목록에 신규 필드 반영. revision 변경 시 번역 4필드 NULL 초기화 규칙 유지.

---

## 6. Dedup (원문 URL 기준, EN/X 우선)

- fmkorea-해소 기사의 `url`이 원문 URL이므로, 기존 `canonical_url` + `content_hash(title,url)` + MariaDB UNIQUE + `classify()`가 **같은 원문을 자동 병합** (1-4의 URL 동일 케이스).
- **소스 우선순위**: 같은 url이 EN/X와 fmkorea 양쪽에서 올 때 EN/X를 남긴다. 구현: `to_articles` 입력 raw를 **소스 우선순위 (공식 · EN · X > fmkorea) 순으로 정렬**해 first-seen이 EN/X가 되도록 한다. (현 `classify`는 first-seen 유지이므로 정렬만으로 충족.)
- URL이 다른 같은-사건 의미 dedup은 **2-b**.

---

## 7. 서빙 (정적 HTML 개편)

승인된 목업: `docs/superpowers/specs/assets/2026-06-29-tier2a/{index,detail}.html`.

### 7.1 산출물 구조
```
site/
  index.html            # 이미지 카드 그리드 + 검색 + 사이드바 + 내비
  article/<content_hash>.html   # 기사별 상세 페이지(별도 파일)
  style.css             # 순수 CSS(라이트/다크 변수)
  app.js                # 바닐라 JS(검색·필터 적용/초기화·테마 토글)
```
- 의존성 0 (빌드 도구 · 프레임워크 없음). 정적 파일만.
- 상세 파일명은 **`content_hash`** (안정 · 회차 간 불변).

### 7.2 인덱스
- 카드: 썸네일 (`image_url`, 없으면 그라데이션 플레이스홀더) + 헤드라인 (`title_ko`) + 1줄 요약 (`summary_ko`) + 칩 (team · outlet · tier) + 시간. 카드 클릭 → `article/<hash>.html`.
- 상단: 로고 + 내비 (홈/소개/일정 — 소개/일정은 2-b 콘텐츠) + 검색창 + **최우측** 테마 토글.
- 좌측 사이드바 (sticky, 독립 스크롤): **팀** (Arsenal 활성, 타 구단 "예정" 비활성) · **소스 (언론사, `outlet` 개별 체크)** · **신뢰도 (tier 0~4 개별 체크)** · **정렬** (최신/신뢰도, 라디오) · 하단 sticky **`초기화` / `필터 적용`** 버튼 + 상태줄.
  - **영입 단계** 그룹은 사이드바에 **비활성 자리 (disabled)** 로만 노출하고 기능은 **2-b**에서 활성화 (목업은 활성처럼 보이나 2-a에선 비활성 처리).
- 카드에 `data-team` · `data-outlet` · `data-tier` · `data-published` · `data-confidence` 속성 → `app.js`가 검색/필터/정렬 수행 (클라이언트 사이드, 서버 불필요). `필터 적용` 클릭 시 반영, `초기화` 시 기본값.

### 7.3 상세 페이지
- 인덱스와 동일 골격 (상단 검색 · 내비 · 테마, 좌측 사이드바).
- 본문: 히어로 이미지 (`image_url`) + 칩 + 제목 + **3줄 요약 박스** (`summary3_ko`) + **전체 번역 본문** (`body_ko`) + 출처 (`outlet` · `journalist` · 원문 링크).
- 하단 **기사 목록 5개**: 현재 글 중심 슬라이딩 윈도우 (아래 §7.4), 썸네일 없음, 현재 글 `지금` 배지 + 하이라이트.

### 7.4 하단 5목록 슬라이딩 윈도우 (생성 시 계산, `render`에서)
정렬된 기사 배열에서 현재 글 인덱스 `i`, 전체 `n`:
- 기본: `[i-2 .. i+2]` (현재 중앙).
- `i<2` (최신 근처): `[0 .. 4]`.
- `i>n-3` (과거 근처): `[n-5 .. n-1]`.
- `n<5`: 전부 표시.
- 한쪽이 부족하면 반대쪽으로 채워 **항상 최대 5개**.

### 7.5 `render.py`
- `write_page` (인덱스) 유지 · 개편 + 신규 `write_article_pages(articles)` (상세 N개 생성, 이웃 5목록 계산 포함).
- Jinja 템플릿 분리: `index.html.j2`, `detail.html.j2`. CSS/JS는 정적 파일로 복사.

---

## 8. 에러 처리 & 폴백

- 본문 fetch 실패 → 제목만 저장, `body_ko` 공백, 다음 회차 재시도.
- og:image 없음 → 플레이스홀더 썸네일.
- 말머리 파싱 실패 → 출처 링크 도메인으로 outlet 추정, 그래도 실패면 글 스킵 + 로깅.
- 원문 URL 없음 → 글 스킵 + 로깅 (fmkorea 텍스트 미표시).
- enrich 키 누락/429 → 해당 회차 스킵 · 누적 (멱등).

---

## 9. 테스트 전략

- **어댑터 (단위 · 모킹)**: `HtmlAdapter` body_selector 본문 추출, og:image 추출; fmkorea 말머리 파싱 (`[BBC - 사미 목벨]` · `[디 애슬레틱-독점]` 등 실측 케이스), **원문 URL 추출 버그픽스** (끝쪽 평문 > 기자 프로필 앵커 — post 10007542458 회귀 케이스), 디 애슬레틱 분기, 스킵 + 로깅.
- **enrich**: 통합 4키 JSON 파싱, 코드펜스 안전망; 디 애슬레틱 변형 프롬프트 분기 선택.
- **dedup**: 소스 우선순위 정렬로 EN/X가 fmkorea보다 first-seen 되는지.
- **render**: 상세 페이지 생성, 5목록 슬라이딩 윈도우 경계 (최신/과거/n<5), 카드 `data-*` 속성, 상세 파일명=content_hash.
- **라이브 검증**: 신규/변경 `body_selector`는 머지 전 어댑터 단독 `fetch()` 실측 (단위 테스트는 모킹이라 드리프트 못 잡음).

---

## 10. 참조
- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` (Tier 2)
- 초기 설계: `docs/superpowers/specs/2026-05-27-bullet-in-design.md` (§4 · §8 · §15)
- fmkorea 정책: `docs/superpowers/specs/2026-06-28-fmkorea-repost-policy-design.md`, 메모리 `fmkorea-repost-policy`
- 셀렉터 드리프트: `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`
- 승인 목업: `docs/superpowers/specs/assets/2026-06-29-tier2a/`
