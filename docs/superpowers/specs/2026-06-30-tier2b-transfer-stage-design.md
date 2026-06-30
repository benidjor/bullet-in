# Bullet-in Tier 2-b — 영입 단계 분류 · 필터 설계

- **작성일**: 2026-06-30
- **상태**: 설계 합의 완료 (구현 전)
- **출처**: `docs/superpowers/specs/2026-06-29-tier2a-detail-page-design.md` §2-b, 로드맵 `docs/superpowers/2026-06-28-v1-completion-roadmap.md` Tier 2
- **한 줄 정의**: 각 기사를 LLM이 6개 영입 단계 (루머 → 관심 → 협상 중 → 개인 합의 → 메디컬 → 오피셜) 중 하나로 태깅하고, 이적이 아닌 글은 `other`로 두어, 사이드바 단계 필터를 활성화하고 카드 · 상세 페이지에 단계 배지를 표시한다.

---

## 0. 스코프 결정 (브레인스토밍 합의)

이번 회차 = **영입 단계 분류 · 필터 하나**에만 집중한다. spec §2-b의 나머지 묶음 (본문 인라인 이미지 · 소개/일정 페이지 · 타 구단 실데이터 · corroboration dedup)은 **이번 범위 아님** — 각각 별도 후속 트랙.

추가 확정 사항:
- **타 구단 UI 자리 제거**: 사이드바 팀 필터에서 Arsenal 외 "예정" 구단 (맨유 · 첼시 등) 비활성 자리를 **삭제**한다. 타 구단 실데이터 수집을 완성한 뒤 그때 다시 추가한다.
- **이적 아닌 글 처리**: 현재 코퍼스 (211건 중 203건 번역 완료) 에는 이적과 무관한 일반 뉴스 (예: "월드컵 스쿼드 분석") 가 다수 섞여 있다. 근본 원인은 **수집 단계의 이적 키워드 필터 (로드맵 Tier 1-3) 와 기존 데이터 정리 (Tier 1-1) 가 아직 미착수**이기 때문. 이번엔 그 글들을 `other` 단계로 태깅해 필터에서 자연 제외하고, **수집 필터 · 데이터 정리는 별도 후속 트랙**으로 분리한다.

---

## 1. 목표 & 성공 기준

**목표**
- 모든 기사에 LLM이 영입 단계를 1개 태깅한다 (신규 + 기존 backfill 포함).
- 사이드바 "영입 단계" 필터를 비활성 자리에서 **실기능으로 활성화**한다.
- 카드 · 상세 페이지에 단계 배지 (색상 점 + 한국어 라벨) 를 표시한다.

**성공 기준 (검증 가능)**
1. `articles.transfer_stage` 컬럼에 모든 기사가 7개 값 (`official` · `medical` · `personal_terms` · `negotiating` · `interest` · `rumour` · `other`) 중 하나를 갖는다 (분류 패스 완주 시 NULL 없음).
2. 이적과 무관한 기사는 `other`로 태깅되고, 사이드바 단계 필터를 걸면 **표시에서 제외**된다.
3. 사이드바 6개 단계 체크박스가 활성화되어, 체크한 단계의 카드만 남는다 (그룹 내 OR · 그룹 간 AND · 미체크 시 전체).
4. 인덱스 카드와 상세 페이지에 단계 배지가 표시된다 (`other`는 배지 생략).
5. 기존 203건이 재번역 없이 단계만 태깅된다 (backfill).
6. 429 발생 시 그 회차는 중단되고 남은 건은 다음 사이클에 누적 태깅된다 (멱등).

---

## 2. 단계 분류 (taxonomy)

7개 값. DB 저장은 영문 enum 문자열, UI 라벨은 한국어.

| enum | 한국어 라벨 | 의미 | css 클래스 | 사이드바 노출 |
|---|---|---|---|---|
| `official` | 오피셜 | 구단 공식 발표 | `s-off` | O |
| `medical` | 메디컬 | 메디컬 테스트 진행/통과 | `s-med` | O |
| `personal_terms` | 개인 합의 | 선수와 개인 조건 (연봉 등) 합의 | `s-personal` | O |
| `negotiating` | 협상 중 | 구단 간/에이전트 협상 진행 | `s-talk` | O |
| `interest` | 관심 | 구단이 실제 관심 표명/스카우팅 | `s-interest` | O |
| `rumour` | 루머 | 근거 약한 소문/연결설 | `s-rum` | O |
| `other` | (기타) | 이적이 아니거나 단계 판단 불가 | — | **X (체크박스 없음)** |

- 사이드바 표시 순서 (위 → 아래): 오피셜 · 메디컬 · 개인 합의 · 협상 중 · 관심 · 루머.
- `other`는 체크박스를 만들지 않는다. 단계 필터를 걸면 (어떤 단계든 체크 시) `other` 카드는 자연 제외되고, 아무 단계도 체크 안 하면 전체 표시된다.
- **단일 출처**: 위 매핑은 신규 모듈 `src/bullet_in/transfer_stage.py` 한 곳에 `(enum, 라벨, css 클래스, 순서)` 테이블로 정의한다. enrich (프롬프트 · 검증) · render (라벨 · 클래스) · 테스트가 이 모듈을 공유해 표류를 막는다.

---

## 3. 데이터 모델 변경

### 3.1 `articles` 테이블 (`schema.sql`)
| 컬럼 | 타입 | 용도 |
|---|---|---|
| `transfer_stage` | VARCHAR (32) NULL | 영입 단계 enum. NULL = 아직 미태깅. |

- 마이그레이션: `schema.sql`에 컬럼 추가. `ensure_schema()` 멱등 적용 흐름 (`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) 유지.

### 3.2 `Article` 모델 (`models.py`)
- `transfer_stage: str | None = None` 추가. 기존 필드 보존.

### 3.3 upsert (`mariadb.py`)
- INSERT 컬럼 목록에 `transfer_stage` 포함.
- **revision 변경 시 NULL 초기화 규칙에는 넣지 않는다** — 단계는 번역과 독립이다. upsert의 `ON DUPLICATE KEY UPDATE`에는 `transfer_stage`를 **넣지 않아 기존 값을 보존**한다 (INSERT 시에만 모델 기본값 NULL → 분류 패스가 채움). 본문 변경 (revision++) 시 단계 재분류는 이번 범위 아님 — 기존 단계를 유지한다.

---

## 4. LLM 단계 분류 (B안 — 분류 전용 패스)

번역과 **분리된 독립 패스**. 신규 · 기존 기사를 한 트리거로 균일 처리하고, 본문 재번역 없이 단계만 부여하며, 독립 재태깅이 가능하다.

### 4.1 트리거 (멱등)
- 신규 함수 `rows_missing_stage()` (`mariadb.py`): `SELECT content_hash, title_original, summary_ko FROM articles WHERE transfer_stage IS NULL`.
- 번역 트리거 (`rows_missing_translation`, `title_ko IS NULL`) 와 독립.

### 4.2 입력 · 프롬프트
- 입력: `title_original` (필수 신호) + `summary_ko` (있으면 보강; 미번역 신규 행은 NULL → 제목만). 본문 (`body_ko`) 은 28건뿐이라 미사용.
- **배치 분류**: 미태깅 행을 N건 (예: 20) 단위로 묶어 한 요청에 보낸다. 입력은 `[{content_hash, title, summary}, ...]`, 출력은 `[{content_hash, stage}, ...]` JSON 배열.
  - 배치 이유: 203건 backfill을 ~11콜로 끝내 RPM 부담을 없앤다 (Gemini 무료 티어는 분당 *요청 수* 한도). 이 배치 파싱이 이번 트랙의 유일한 추가 복잡도이며, 문서화된 429 함정을 직접 겨냥한 것이라 정당화된다.
- 프롬프트: 6개 단계 정의 + "이적과 무관하거나 단계 판단 불가 시 `other`" 규칙 명시. enum 값 목록은 `transfer_stage` 모듈에서 주입.

### 4.3 파싱 · 검증 · 저장
- 응답 JSON 배열을 `{content_hash: stage}`로 매핑.
- **검증**: stage가 허용 enum (7개) 에 없으면 `other`로 강등.
- **누락 처리**: 응답에 없는 `content_hash`는 NULL 유지 → 다음 사이클 재시도 (멱등).
- 신규 함수 `set_stage(content_hash, stage)` (`mariadb.py`): `UPDATE articles SET transfer_stage=:s WHERE content_hash=:h`.

### 4.4 429 전략 (기존 재사용)
- `_is_rate_limit()` 재사용. 429 식별 시 그 회차 **즉시 중단 · WARNING 로깅**, 남은 배치는 다음 사이클 누적. per-row/per-batch 백오프는 두지 않음 (스케줄이 재시도).

### 4.5 `run.py` 연결
- enrich (번역) 패스 뒤에 분류 패스 호출 추가: `rows_missing_stage()` → 배치 분류 → `set_stage()` 루프.

---

## 5. 서빙 (정적 HTML) 변경

### 5.1 사이드바 (`serve/templates/_layout.html.j2`)
- "영입 단계" 그룹: `disabled` · `예정` 제거. 6개 체크박스를 `transfer_stage` 모듈의 사이드바 노출 순서대로 렌더 — `data-group="stage" data-value="<enum>"` + 색상 점 (`<span class="stage s-xxx">`) + 라벨 + 카운트 `{{ facets.stage.get('<enum>', 0) }}`.
- **타 구단 자리 삭제**: 팀 필터에서 Arsenal 외 disabled 라벨 (맨유 등) 제거. Arsenal 한 줄만 남김.

### 5.2 CSS (`src/bullet_in/serve/static/style.css`)
- **정적 자산 원본은 `src/bullet_in/serve/static/{style.css,app.js}`** 이며 render.py (`_STATIC_DIR`, L147-148) 가 `site/`로 복사한다. `site/` 산출물은 직접 편집하지 않는다 (다음 렌더에 덮어쓰임).
- 점 색 2개 추가: `.s-personal` (개인 합의) · `.s-interest` (관심). 기존 4개 (`s-off` · `s-med` · `s-talk` · `s-rum`) 재사용. 색은 단계 순서가 직관적으로 읽히도록 선택 (예: 오피셜 초록 → 루머 회색 그라데이션 사이에 개인 합의 · 관심 배치).

### 5.3 app.js (`src/bullet_in/serve/static/app.js`)
- `applyFilters()`에 단계 필터 추가:
  ```js
  const stages = checkedValues('stage');
  const okStage = stages.length === 0 || stages.includes(card.dataset.stage);
  // visible = okText && okOutlet && okTier && okStage;
  ```
- `conds` 합산에 `stages.length` 추가.
- DOM contract 주석 (1행) 에 `[data-stage]` 추가.
- reset · dirty 로직은 기존 그대로 (단계 체크박스도 `enabledBoxes()` 에 포함되어 자동 처리).

### 5.4 카드 · 상세 (`index.html.j2` · `detail.html.j2`)
- 카드: `data-stage="{{ a._stage }}"` 속성 추가 + 칩 줄에 단계 배지 (`<span class="stage s-xxx"></span>` + 라벨). `other`는 배지 생략.
- 상세: 칩 영역에 동일 배지 추가.

### 5.5 render.py (`serve/render.py`)
- `_decorate()`: `transfer_stage` 모듈로 `a["_stage"]` (enum) · `a["_stage_label"]` · `a["_stage_class"]` 세팅. `other`/NULL은 배지 생략 플래그.
- `facet_counts()`: `stage` 카운터 추가 (`other` 제외, 사이드바 6개 단계만 집계). 반환 dict에 `"stage"` 키 포함.
- `render_article()`의 기본 facets stub에도 `stage` 키 추가.

---

## 6. 에러 처리 & 폴백

- 분류 응답 JSON 파싱 실패 → 그 배치 스킵 · WARNING 로깅, NULL 유지 (다음 사이클 재시도).
- stage 값이 허용 enum 밖 → `other`로 강등.
- 응답에 없는 `content_hash` → NULL 유지 (재시도).
- 429 → 회차 중단 · 누적 (멱등).
- `summary_ko` NULL (미번역 신규 행) → 제목만으로 분류 (분류는 번역과 독립이므로 번역 전에도 동작).

---

## 7. 테스트 전략

- **`transfer_stage` 모듈 (단위)**: enum ↔ 라벨 ↔ css 클래스 매핑 완전성, 사이드바 노출 순서, `other` 미노출.
- **enrich 분류 (단위 · 모킹)**: 배치 JSON (`[{content_hash, stage}]`) 파싱, 미허용 stage → `other` 강등, 응답 누락 hash는 NULL 유지, 파싱 실패 배치 스킵, 429 break.
- **mariadb (단위)**: `rows_missing_stage()` 트리거 (`transfer_stage IS NULL`), `set_stage()` 갱신.
- **render (단위)**: `facet_counts` stage 집계 (`other` 제외), `_decorate` 단계 라벨/클래스, 카드 `data-stage` 속성 존재, `other`/NULL 배지 생략.
- **app.js**: JS 단위 테스트 없음 (2-a 동일). render 산출물에 `data-stage` 존재를 Python 테스트로 검증 + 라이브 수동 확인 (단계 필터 체크 시 카드 필터링) 으로 커버.

---

## 8. 후속 트랙 (이번 범위 아님 — 기록)

- **이적 키워드 필터 (로드맵 Tier 1-3)**: BBC · football.london 일반 뉴스를 수집 단계에서 차단 (`HtmlAdapter.title_contains` 패턴). 이게 들어오면 `other` 비중이 크게 준다.
- **기존 데이터 정리 (Tier 1-1)**: 이미 적재된 이적 무관 기사 정리.
- spec §2-b의 나머지: 본문 인라인 이미지 (`<figure>`) · 소개/일정 페이지 · 타 구단 실데이터 수집 · corroboration dedup.

---

## 9. 참조
- 상위 spec: `docs/superpowers/specs/2026-06-29-tier2a-detail-page-design.md` (§2-b)
- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` (Tier 1 · Tier 2)
- 429 전략 · 멱등 누적: `CLAUDE.md` "자주 밟는 함정", 기존 `enrich.py`
- 셀렉터 드리프트 (후속 트랙 수집 변경 시): `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`
