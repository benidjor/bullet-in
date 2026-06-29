# 설계 — Tier 1: 데이터 · 신호 품질 정리 + BBC 가십 소스

v1 완성 로드맵 (`docs/superpowers/2026-06-28-v1-completion-roadmap.md`)의 **Tier 1**. 작은 변경 4건을 한 트랙으로 묶는다.

## 목적
- 이적시장 신호를 키우고 잡음을 줄인다: 일반 뉴스 소스에 이적 키워드 필터, 전 구단 이적 가십 소스 추가.
- 관측 데이터 정확화 (중복 · 소스별 신규 수), 과거 잘못 적재된 데이터 정리.

## 범위
- **변경 파일**: `src/bullet_in/adapters/html.py`, `src/bullet_in/pipeline.py`, `src/bullet_in/run.py`, `config/sources.yaml`, `tests/test_html_adapter.py`, `tests/test_pipeline.py`, `docs/runbook/`(신규 1건).
- **무변경**: enrich · credibility · storage 스키마 · serve.

---

## 1. 이적 키워드 필터 (bbc_sport + football_london)

### 결정
- `HtmlAdapter.title_contains`를 **`str | list[str] | None`** 으로 일반화. 리스트면 제목 (소문자)에 키워드가 **하나라도 포함**되면 통과 (substring 매칭 = 재현율 우선). 단일 문자열 · None은 현행 그대로 (하위호환).
- 적용 소스: `bbc_sport`, `football_london`. arsenal (`"sign"` 단일) · fmkorea (한국어, 이번 범위 아님)는 불변.

### 키워드 리스트 (영어, 넓게)
`transfer, sign, signed, signing, deal, loan, bid, fee, medical, agree, agreed, join, joins, target, linked, links, contract, swap, move, talks`

### 근거
- 정밀도보다 재현율 우선 — 이적 뉴스 누락 최소화가 목표 (일부 비이적 오탑재 허용).

---

## 2. bbc_gossip 신규 소스

### 결정
- `config/sources.yaml`에 항목 추가, **기존 HtmlAdapter 재사용 (코드 변경 없음)**:
  - `list_url: https://www.bbc.com/sport/football/gossip`
  - `item_selector: "a[href*='/sport/football/articles/']"` (bbc_sport와 동일; 라이브 24건 확인)
  - `tier: 4`(루머=최하위 신뢰, confidence 0.0), `medium: newspaper`, `enabled: true`
  - **필터 없음** — 전 구단 가십 전부 수집 (아스날 외 포함, 사용자 요구).

### 동작 · 함의
- 가십 페이지는 bbc_sport와 동일 구조 (일별 가십 칼럼 기사 링크 목록). 제목만 수집 → en 경로에서 제목 번역 (본문 전체 번역은 Tier 2).
- 아스날 전용이던 서빙 페이지에 타구단 가십도 노출된다 (의도된 변경).

---

## 3. dup_count · source_counts 정확 기록

### 문제
- `run.py`가 `pipeline_runs` 적재 시 `dup_count=0` · `source_counts={sid:0}`를 하드코딩 → 중복률 · 소스별 수집량 SLO 근거 데이터 오염.
- `to_articles`는 중복을 분류해 skip하지만 그 수를 반환하지 않는다.

### 결정
- `to_articles` 반환을 `list[Article]` → **`tuple[list[Article], dict]`** 로 변경.
  - `stats = {"dup_count": int, "source_counts": {source_id: 신규_또는_변경_수}}`.
  - `dup_count` = `classify` 결과가 `"duplicate"`인 항목 수. `source_counts` = 실제 append된 Article의 source_id별 집계.
- `run.py`: 호출처 (1곳)에서 unpack, INSERT의 `dup_count` · `source_counts`를 stats로 교체.

---

## 4. arsenal 과거 데이터 정리 (런북 + SQL, 미실행)

### 문제
- arsenal_official이 "영입 (sign) 전용 고정밀 소스"로 재정의되기 전 적재된 비-영입 기사 (여자팀 · 잡다, 약 31건)가 `articles` · 서빙 페이지에 잔존 · 노출 중.

### 결정
- 일회성 데이터 정리. **코드가 아니라 라이브 MariaDB 작업**이라, 절차 · SQL을 `docs/runbook/`에 문서화하고 실행은 사용자가 직접 (드라이런 방지).
- 삭제 기준 (현재 'sign' 필터와 정합):
  ```sql
  DELETE FROM articles
  WHERE source_id = 'arsenal_official'
    AND LOWER(title_original) NOT LIKE '%sign%'
    AND (title_ko IS NULL OR LOWER(title_ko) NOT LIKE '%sign%');
  ```
- 절차: ① 동일 조건 `SELECT COUNT(*)`로 대상 수 확인 → ② DELETE → ③ 서빙 페이지 재생성 (다음 run 또는 write_page).

---

## 에러 · 엣지
- 필터 리스트가 빈 값/None → 전체 통과 (현행 유지).
- bbc_gossip 셀렉터가 가십 외 링크를 잡을 경우 → 가십 칼럼만 있는 페이지라 위험 낮음. 필요 시 후속 `title_contains: ["gossip"]` 안전망 (이번 범위 아님).
- `to_articles` 빈 입력 → `{"dup_count": 0, "source_counts": {}}`.

## 테스트
- `tests/test_html_adapter.py`: (a) 리스트 키워드 — 매칭 통과 · 비매칭 제외, (b) 단일 문자열 하위호환, (c) None/빈 → 전체 통과.
- `tests/test_pipeline.py`: 중복 섞인 입력 → `to_articles`의 `dup_count` · `source_counts` 정확.
- 라이브 스모크 (수동): `bbc_gossip.fetch()` >0건; `bbc_sport` · `football_london`은 필터 후 이적 키워드 제목만.

## 성공 기준
- 위 단위 테스트 통과 + 기존 테스트 회귀 없음.
- 라이브 스모크에서 bbc_gossip 수집 · 이적 필터 동작 확인.
- `pipeline_runs`에 실제 `dup_count` · `source_counts` 기록.
- arsenal 정리 런북 문서 존재 (실행은 사용자).

## 참조
- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` (Tier 1)
- 초기 설계: `docs/superpowers/specs/2026-05-27-bullet-in-design.md` (§6 소스 전략, §10 SLO)
