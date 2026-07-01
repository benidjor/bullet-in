# Tier 1 ③ — 비-이적 'other' 서빙 opt-in 토글 설계 (2026-06-30)

## 배경 · 문제

`config/sources.yaml`의 football.london · bbc_gossip 등은 아스날 일반 뉴스를 폭넓게 수집한다.
이 중 상당수는 **진짜 기사지만 이적 뉴스가 아니다** — 경기 리포트 · 선수 평점 · 킷 공개 ·
FFP · 월드컵 · 부상 업데이트 · 스타디움 마스터플랜 · 역사 기사, 그리고 일부 타구단 이적.
이들은 "transfer · move · deal" 등 키워드를 실제로 포함하므로 수집 키워드 필터
(`HtmlAdapter.title_contains`) 로는 못 거른다.

영입 단계 분류 (`transfer_stage`) 는 이런 기사를 `other` 버킷으로 분류한다. 그러나 서빙은
`SELECT … FROM articles` 전건을 렌더하고 단계 필터를 기본 적용하지 않아, off-mission `other`
기사가 메인 피드에 그대로 노출된다.

### 라이브 점검 (2026-06-30, 적재 189건)

| stage | n | 비고 |
|---|---|---|
| **other** | **66 (35 %)** | 거의 전부 football_london (63) · bbc_gossip (3) |
| rumour | 59 | |
| interest | 28 | |
| negotiating | 24 | |
| official | 10 | |
| personal_terms | 2 | |

`other` 가 단일 최대 버킷이며 사실상 football.london 한 소스에서 나온다.

## 정책 결정 (확정)

세 안 중 **ⓑ 서빙 단계 처리**, 그 안에서 **사이드바 opt-in 토글** 을 채택한다.

- **ⓐ 수집 단계 필터 (기각)**: 이 기사들이 transfer 키워드를 포함해 키워드 필터로 못 거른다.
  LLM 관련성 판단을 수집 시점에 **중복** 투입해야 하고 (분류는 이미 파이프라인에서 무료로 나옴),
  오탐 시 DB에 아예 안 들어와 **영구 재현율 손실**이다.
- **ⓑ 서빙 단계 (채택)**: `other` 판정이 이미 계산돼 있어 LLM 추가비용 0 · 재현율 손실 0 ·
  완전 가역. 그 안에서 — 하드 숨김 대신 — **사이드바 opt-in 토글**로 기본은 숨기되 사용자가
  켤 수 있게 해, 오분류로 `other` 에 빠진 진짜 이적도 복구 가능하게 한다.
- **ⓒ 현행 유지 (기각)**: off-mission 35 % 가 기본 노출된 채로 남는다.

### 로드맵 정합

이 트랙은 로드맵 (`docs/superpowers/2026-06-28-v1-completion-roadmap.md`) Tier 1 ③ 의 후속이다.
원제목은 "이적 키워드 필터"(수집 단계) 였으나, 위 라이브 관찰에 따라 **서빙 opt-in 으로 피벗**한다.

## 핵심 제약 (구현 정확도)

`app.js` 의 `applyFilters()` 는 **초기 로드 시 호출되지 않는다** (init 에서 `sortCards()` 만 실행).
필터는 Apply 클릭 · 검색 입력 · reset 시에만 동작한다. 따라서 "기본 other 숨김"은 app.js 로직만
바꿔선 안 되고, **서버가 off-mission 카드를 `display:none` 으로 렌더**해야 첫 로드부터 숨겨진다.
이후 사용자가 '기타'를 켜고 Apply 하면 `applyFilters()` 가 인라인 스타일을 override 해 표시한다.

## 데이터 흐름 (변경 없음)

수집 · enrich · classify · DB · `run.py` 의 전건 SELECT 는 **무수정**. 파이프라인이 이미 산출한
`transfer_stage` 를 서빙에서 소비할 뿐이다. 변경은 **서빙 3파일에 국소**된다.

## 컴포넌트 변경 (3곳)

### 1. `src/bullet_in/serve/render.py` — `facet_counts()`
`stage_counts` 에 `other` 카운트를 추가한다. 현재는 `SIDEBAR_STAGES` 6개만 세므로 '기타 (66)'
배지 표시를 위한 카운트가 없다. `other` 를 세어 `stage` 패싯에 포함한다.

### 2. `src/bullet_in/serve/templates/index.html.j2` — 카드 · 사이드바
- **카드**: off-mission (`not a._stage_badge`) 이면 `style="display:none"` 인라인 추가 →
  첫 로드부터 숨김. (`is_displayable` 가 false 인 대상 = `other` + null · 미분류.)
- **사이드바**: stage 루프 아래 구분선 + `data-group="bucket" data-value="other"` 체크박스 1개.
  라벨 '기타 {{ facets.stage.get('other', 0) }}', **기본 미체크**.

> 사이드바 마크업은 `_layout.html.j2` 의 공유 `<aside class="side">` 에 있다. stage 루프
> (`{% for enum, label, css in stages %}`) 바로 다음에 '기타' 항목을 추가한다.

### 3. `src/bullet_in/serve/static/app.js` — `applyFilters()`
```js
const stages = checkedValues('stage');           // 6개 실단계
const showOther = side.querySelector(
  'input[data-group=bucket][data-value=other]')?.checked;
// 루프 내부:
const isOther = !card.dataset.stage || card.dataset.stage === 'other';
const okStage = isOther ? !!showOther
              : (stages.length === 0 || stages.includes(card.dataset.stage));
```
- `conds` 에 `+ (showOther ? 1 : 0)` 를 더한다.
- `reset` 은 기존 로직 (`c.checked = (c.dataset.value === 'arsenal')`) 이 '기타' 체크박스
  (value `other`) 를 자동으로 끄므로 **무수정** — reset 시 other 다시 숨김.

## 동작 진리표

| 사이드바 상태 | 메인 피드 |
|---|---|
| 초기 로드 (미적용) | 이적 6단계만, other 숨김 |
| Apply (아무것도 안 체크) | 동일 — other 숨김 |
| '루머' 체크 | rumour 만 |
| '기타' 체크 | 이적 6단계 + other |
| '루머' + '기타' | rumour + other |

## 안전성 · 가역성

- DB 데이터 무삭제 → 완전 가역. 오분류로 `other` 에 빠진 진짜 이적도 '기타' 체크로 복구 가능
  (하드 숨김 대비 장점).
- detail 페이지는 전건 계속 생성 (other 카드 클릭 가능). 상세 페이지 사이드바의 '기타'는
  기존 필터처럼 목업 동작 (그리드 없음).

## 테스트 (성공 기준)

- `facet_counts`: `other` 포함 데이터 → `stage['other']` 카운트 정확 (단위 테스트).
- `render_index`: off-mission 카드에 `display:none` 인라인 존재 · 이적 카드엔 없음
  (HTML 문자열 검증).
- 사이드바에 `data-group="bucket" data-value="other"` 체크박스 렌더 · 기본 미체크.
- app.js 는 기존 관행대로 JS 단위 테스트 없음 → 위 동작 진리표를 **수동 검증 항목**으로 남긴다
  (`uv run python -m bullet_in.run` 후 `site/index.html` 육안 확인).

## 범위 밖 (YAGNI)

- 수집 단계 필터 · LLM 관련성 재판정.
- `other` 세분류 (비-이적 아스날 vs 타구단 이적 구분).
- 분류 정확도 개선 · 프롬프트 수정.
- detail 페이지 사이드바의 실제 필터 동작화.

## 참조

- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` (Tier 1 ③)
- 직전 트랙 spec: `docs/superpowers/specs/2026-06-30-tier1-collection-filter-refinement-design.md`
- 운영 관찰: `docs/runbook/2026-06-30-transfer-stage-classification-ops.md`
- 단계 분류 모듈: `src/bullet_in/transfer_stage.py` (`SIDEBAR_STAGES` · `OTHER` · `is_displayable`)
