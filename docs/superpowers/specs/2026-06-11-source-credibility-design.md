# 소스 재구성 + 공신력 레지스트리 설계 명세

- 작성일: 2026-06-11
- 브랜치: `feat/source-credibility`
- 상태: 승인됨 (구현 대기)

## 1. 배경 / 목표

라이브 e2e 트랙에서 수집 소스를 재구성한다.

1. **Guardian 제거** — API 키 의존을 없애고 활성 소스에서 제외.
2. **X 수집 대상을 afcstuff로 교체** — afcstuff는 자체 속보원이 아니라 ITK · 기자 기사를
   요약 · 재방송하는 **순수 애그리게이터**다. 따라서 트윗마다 본문에 인용된 `@계정`을
   보고 **공신력 (tier)을 동적으로** 결정한다. 인용된 기자가 없으면 그 트윗은 버린다 (규칙 C).
3. **fmkorea '축구 소식통' 보드 추가** — https://www.fmkorea.com/football_news 의 글
   제목을 아스날 키워드로 거르고, 매치된 글의 본문까지 크롤링한다. fmkorea 제목은
   `[디 애슬레틱] 제목`처럼 **대괄호에 매체**를 명시하므로 이를 공신력 판단에 쓴다.

이를 위해 X · fmkorea가 공유하는 **단일 공신력 레지스트리**와, 항목별 tier를 산출하는
**전용 해석 모듈**을 도입한다.

## 2. 공신력 모델

tier 숫자가 낮을수록 공신력이 높다. 기존 `confidence()`의 `1.0 - tier/4.0` 매핑을 유지한다.

### 2.1 기자 명단 (tier / X 핸들 · 한국어 별칭 — 핸들은 구현 시 실제 계정 검증)

| tier | 기자 | 매체 | 별칭 (예시) |
|---|---|---|---|
| 1   | David Ornstein | 디 애슬레틱 | `@David_Ornstein`, 온스테인, Ornstein |
| 1   | Sami Mokbel | BBC | `@SamiMokbel1_DM`, 목벨, Mokbel |
| 1.5 | Fabrizio Romano | 가디언 | `@FabrizioRomano`, 로마노, Romano |
| 1.5 | James McNicholas | 디 애슬레틱/Gunnerblog | `@_JamesMcNicholas`, 맥니콜라스 |
| 1.5 | handofarsnal | ITK | `@handofarsnal` |
| 2   | Charles Watts | 골닷컴 | `@charles_watts`, 찰스 와츠 |
| 2   | Amy Lawrence | 디 애슬레틱 | `@amylawrence71`, 에이미 로런스 |
| 2   | 팀뉴스앤틱스 | ITK | `@Teamnewsandtix` |
| 2   | James Olley | ESPN | `@JamesOlley`, 올리 |
| 3   | Gary Jacob | 더 타임스 | 게리 제이콥 |
| 3   | Simon Collings | 이브닝 스탠다드 | 사이먼 콜링스 |
| 3   | Gianluca Di Marzio | 스카이 이탈리아 | 디 마르지오, Di Marzio |

> Sky Sports는 자체 매체가 있어 X 기자 매칭 대상에서 제외 (아래 매체 표에만 둠).

### 2.2 매체 명단 (fmkorea 대괄호 · 본문 매칭용)

| tier | 매체 | 한국어 별칭 (예시) |
|---|---|---|
| 1   | The Athletic | 디 애슬레틱, 애슬레틱 |
| 1   | BBC | BBC |
| 1.5 | The Guardian | 가디언 |
| 1.5 | Sky Sports | 스카이 스포츠, 스카이, Sky |
| 2   | Goal.com | 골닷컴, 골 |
| 2   | ESPN | ESPN |
| 3   | The Times | 더 타임스, 타임스 |
| 3   | Evening Standard | 이브닝 스탠다드 |
| 3   | The Telegraph | 텔레그래프 |
| 3   | Daily Mail | 데일리 메일 |
| 3   | Sky Italia | 스카이 이탈리아, 디 마르지오 |
| 4   | The Sun / Mirror / Express | 더 선, 미러, 익스프레스 |
| 4   | football.london / 90min / HITC / Caught Offside | 풋볼런던, 90min, HITC |

## 3. 컴포넌트

### 3.1 `config/credibility.yaml` (신규)

```yaml
journalists:
  - {name: David Ornstein, tier: 1,   aliases: ["@David_Ornstein", "온스테인", "Ornstein"]}
  - {name: Sami Mokbel,    tier: 1,   aliases: ["@SamiMokbel1_DM", "목벨", "Mokbel"]}
  # ...
outlets:
  - {name: The Athletic, tier: 1,   aliases: ["디 애슬레틱", "애슬레틱", "Athletic"]}
  - {name: BBC,          tier: 1,   aliases: ["BBC"]}
  # ...
```

### 3.2 `src/bullet_in/credibility.py` (신규)

```python
def load_registry(path) -> Registry:
    """journalists/outlets 를 읽어 별칭(소문자)→tier 룩업 2개를 만든다.
    tier 누락·중복 별칭은 로드 시 에러."""

def resolve_tier(item, sources, registry) -> float | None:
    """항목 1건의 tier 를 산출. None 이면 호출측에서 그 항목을 버린다."""
```

해석 규칙 (소스 설정의 `credibility` 모드로 분기):

- **고정 소스** (`credibility` 미지정): 소스의 정적 `tier` 반환.
- **`x_mentions`** (afcstuff): `raw_payload["text"]`에서 `@(\w+)` 추출 → 기자 핸들 별칭과
  대소문자 무시 매칭. 매치가 있으면 **최저 tier 숫자** (최고 공신력) 반환, 없으면 **None**.
- **`fmkorea`**: ① 제목 `[대괄호]` · 본문에서 기자 별칭 매칭 → 기자 tier. ② 없으면 제목
  대괄호 매체 별칭 매칭 → 매체 tier. ③ 둘 다 없으면 **tier 4** (버리지 않음).

### 3.3 afcstuff X 소스

기존 `x_handofarsnal` 직접 수집을 **afcstuff로 교체**. handofarsnal은 레지스트리에
기자 (1.5)로 남으므로, afcstuff가 인용하면 1.5로 잡힌다. XAdapter 코드는 변경 없음
(handle만 교체). `raw_payload["text"]`에 `@멘션`이 포함됨을 전제.

### 3.4 `src/bullet_in/adapters/fmkorea.py` (신규 전용 어댑터)

- 보드 목록 페이지에서 글 제목 · 링크 추출 → **제목 키워드 필터** (`["아스날","Arsenal"]`,
  대소문자 무시) → 매치된 글만 남김.
- 매치된 글마다 **본문 페이지를 fetch**해 본문 텍스트를 수집 (기자명 파싱 · 요약용).
- `raw_payload = {"title": <대괄호 포함 원제목>, "body": <본문 발췌>, "lang": "ko"}`.
- 수집 방식: **정적 httpx 우선**, 차단 시 Playwright 폴백 (구현 단계에서 실제 테스트로 확정).
- 본문 fetch 실패 시 그 글만 스킵 (배치 중단 안 함).

### 3.5 enrich 한국어 분기 (번역 스킵 · 요약 수행)

`rows_missing_translation()` 쿼리에 `source_id`를 포함시키고, `run.py`에서 소스의
`lang`으로 분기한다. Gemini API의 용도는 두 가지다 — ① 번역, ② 요약.

- **ko 소스** (fmkorea): **번역은 스킵** (`title_ko=원제목`), 그러나 **요약은 수행**한다.
  `summarize_ko_rows(...)`로 한국어 본문을 한국어 한 줄 요약 (`summary_ko`)으로 생성.
  요약 호출 실패 시 본문 발췌 (`body_excerpt[:200]`)로 graceful fallback.
- **en 소스**: 기존대로 `enrich_rows(...)`가 번역 + 요약을 함께 수행.

### 3.6 `pipeline.py` 변경

`to_articles`에서 항목별로 `resolve_tier(item, sources, registry)` 호출:

```python
tier = resolve_tier(item, sources, registry)
if tier is None:
    continue                     # afcstuff 인용 없음 → 제외
...
tier=tier, confidence_score=round(max(0.0, 1.0 - tier/4.0), 3)
```

`registry`를 `to_articles` 인자로 추가하고, `run.py`에서 `load_registry()` 결과를 주입.

### 3.7 sources.yaml 변경

- `guardian` 항목 **삭제**.
- `x_handofarsnal` → `x_afcstuff`(handle `afcstuff`), `credibility: x_mentions` 추가, 정적 tier 제거.
- `fmkorea` 항목 **추가** (adapter `fmkorea`, `credibility: fmkorea`, `lang: ko`,
  키워드 · list_url 설정).
- 고정 소스 (arsenal_official · bbc_sport · goal · football_london)는 정적 tier 유지.

### 3.8 Guardian 제거 범위

- sources.yaml 항목 · `.env.example`의 `GUARDIAN_API_KEY` · 관련 문서 제거.
- **어댑터 코드 · 테스트는 보존** (`guardian_api.py`, 해당 테스트) — 재활성이 쉽고 무해.
  factory의 `guardian_api` 분기도 유지.

## 4. 데이터 흐름

```
ingest → RawItems
  → to_articles: 항목마다 resolve_tier()  [고정 | x_mentions | fmkorea]
       └ None → 제외(afcstuff 인용 없음)
  → enrich: ko 소스=번역 스킵+한국어 요약, en 소스=Gemini 번역+요약
  → store(MariaDB) → serve(site/index.html)
```

## 5. 소결정 (확정값)

| # | 항목 | 결정 |
|---|---|---|
| a | fmkorea 제목 키워드 | `["아스날", "Arsenal"]` (대소문자 무시) |
| b | fmkorea 수집 방식 | 정적 httpx 우선, 차단 시 Playwright 폴백 |
| c | fmkorea 본문 수집 | 수집함 (기자 파싱 · 요약용) |
| d | ko 소스 번역/요약 | 번역 스킵 (`title_ko=원제목`) + Gemini로 한국어 요약 (`summary_ko`), 실패 시 본문발췌 폴백 |
| e | Guardian 제거 범위 | 설정 · env · 문서 제거, 어댑터 코드 · 테스트 보존 |

## 6. 에러 처리

- `resolve_tier`: 미지의 핸들/매체는 규칙대로 (제외 또는 폴백 4), 예외 없이 종료.
- fmkorea 본문 fetch 실패: 해당 글만 스킵, 배치 지속.
- `load_registry`: 시작 시 검증 (tier 누락 · 중복 별칭 → 조기 에러).

## 7. 테스트 전략

- `tests/test_credibility.py`:
  - `x_mentions`: 트윗 텍스트 @핸들 1개 · 복수 (최저 tier 선택) · 없음 (None).
  - `fmkorea`: 제목 대괄호 매체 → 매체 tier, 본문 기자명 → 기자 tier (우선), 둘 다 없음 → 4.
  - `load_registry`: 정상 로드 + tier 누락 에러.
- `tests/test_fmkorea_adapter.py`: HTML 모킹으로 키워드 필터 · 대괄호 추출 검증.
- `to_articles`: afcstuff None 항목 드롭, fmkorea 폴백 4 반영.
- 기존 테스트 전부 유지 (녹색).

## 8. 영향 파일 요약

| 파일 | 변경 |
|---|---|
| `config/credibility.yaml` | 신규 |
| `config/sources.yaml` | guardian 삭제, afcstuff · fmkorea 반영 |
| `src/bullet_in/credibility.py` | 신규 (레지스트리 로드 + resolve_tier) |
| `src/bullet_in/adapters/fmkorea.py` | 신규 어댑터 |
| `src/bullet_in/adapters/factory.py` | fmkorea 분기 추가 |
| `src/bullet_in/pipeline.py` | resolve_tier 사용, None 드롭, registry 인자 |
| `src/bullet_in/run.py` | load_registry 주입, ko/en enrich 분기 |
| `src/bullet_in/storage/mariadb.py` | rows_missing_translation 에 source_id 포함 |
| `.env.example` / 문서 | GUARDIAN_API_KEY 제거 |
| `tests/` | test_credibility, test_fmkorea_adapter 신규 |

## 9. 향후 작업 (live-e2e 트랙으로 이연)

### 9.1 fmkorea '퍼가기 금지' 글 처리 정책 (미구현 — 실제 DOM 필요)

fmkorea '축구 소식통'의 일부 글은 **작성자가 직접 번역한 2차 저작물**이며 '퍼가기 금지'
표식이 붙는다 (예: `https://www.fmkorea.com/9940576222`). 이 본문을 그대로 복제 · 요약해
서빙하면 저작권 · 평판 문제가 생긴다. 결정: **무시하고 크롤 (❌) 대신, 원 출처 기반으로 처리한다.**

처리 분기 — **퍼가기 금지 여부**로 나눈다:

1. **퍼가기 금지 감지** → fmkorea 번역 본문은 **저장 · 요약하지 않는다**.
   - ① 본문에서 **원문 링크 (The Athletic · BBC 등) 추출 가능 + 접근 가능 (비페이월)**
     → 원문을 가져와 **en 경로 (번역+요약)**, 공신력은 해당 매체/기자 tier.
   - ② 원문이 **페이월/링크 없음** → **제목 (헤드라인) + 출처 · tier + 링크만** (본문 미복제), 또는 스킵.
2. **퍼가기 금지가 아닌 글** → 현행대로 fmkorea 본문을 `summarize_ko_rows`로 한국어 요약.

구현 시 필요 (실제 페이지 없이는 추측이 되어 이연):
- `_is_repost_blocked(html)` — 퍼가기 금지 표식 감지 (실제 DOM 표식 확인 필요).
- 본문에서 **원문 캐노니컬 링크 추출** 로직 (출처 표기 위치 · 형식 확인 필요).
- 페이월 감지 + 폴백 (헤드라인/링크만) 경로.
- 안티봇: 방금 라이브 점검에서 fmkorea가 **HTTP 429**를 반환 → 요청 레이트 · UA · 간격 조정 또는 Playwright 폴백 검토.

> 이 정책은 afcstuff (X)와 동일한 "**애그리게이터는 원 출처를 가리키는 발견 surface**" 철학의 연장이다.
