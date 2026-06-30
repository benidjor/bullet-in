# 설계 — Tier 1 후속: 수집 필터 정제 (BBC 셀렉터 드리프트)

v1 완성 로드맵 (`docs/superpowers/2026-06-28-v1-completion-roadmap.md`)의 **Tier 1** 1-3 (이적 키워드 필터 정제) ·
1-1 (기존 데이터 정리) 후속 회차. 1차 스펙 (`2026-06-28-tier1-signal-quality-design.md`)에서
키워드 필터 · bbc_gossip · dup_count · arsenal 정리를 도입했고, Tier 2-b 라이브 관찰 (2026-06-30) 에서
그 키워드 필터로 못 거르는 잡음이 드러났다. 이 회차는 그 잡음을 정제한다.

## 목적
- 수집되는 항목이 실제로 "이적 기사" 가 되도록 신호 품질을 올린다.
- 핵심 잡음 **BBC 셀렉터 · 제목추출 드리프트** 를 제거하고, 그로 인해 적재된 기존 잡음을 정리한다.

## 배경 — 라이브 조사 (2026-06-30)
- **bbc_sport** (DB 34건) 중 진짜 기사는 ~4건. 나머지는 `data-testid="content-post"` (본문 임베드 인라인 링크 = teaser · "Read more" · nav) 와 `navigation` 링크. 또 진짜 카드도 제목이 `21:19 BST 29 June … , published at …` 식으로 깨져 적재됨 (`a.get_text()` 가 timestamp · visually-hidden 텍스트까지 연결).
  - 라이브 DOM: 진짜 카드는 조상 `data-testid="main-content"`, 헤드라인은 `span[class*="LinkPostHeadline"]` 에 깨끗이 존재. 쓰레기 인라인 링크는 `content-post` · `navigation` 하위.
  - 사용자가 football.london 사례로 든 `"Want more transfer stories? Read Thursday's full gossip column"` 도 실제로는 **bbc_sport** 였음.
- **football.london** (DB 153건) 라이브 키워드 통과 링크는 사실상 전부 진짜 이적 기사. 비-기사는 뉴스레터 링크 1건 (`"Get our best and latest Arsenal stories sent to your inbox …"`) 뿐이며, 이 링크는 **이적 키워드를 포함하지 않아 현 `title_contains` 필터에서 이미 차단**됨 (DB 잔존분은 PR #9 필터 도입 이전 legacy).
- **arsenal_official**: DB 0건 → 1차 스펙의 arsenal stale-cleanup 런북은 정리 대상 없음 (무효).

### ① 제외 패턴 (title_excludes) — 검토 결과 불필요
- 로드맵 1-3 이 물은 "비-기사 링크를 거르는 제외 패턴이 필요한지" 의 답: **현재 불필요.** 비-기사 링크의 출처가 모두 다른 메커니즘으로 이미 해결되기 때문.
  - BBC teaser · nav · read-more → 본 회차 ② 셀렉터 스코핑으로 탈락.
  - football.london 뉴스레터 → 키워드 미포함 → 기존 `title_contains` 가 이미 차단.
  - 키워드를 *포함한* 비-기사 링크는 라이브 조사에서 관찰되지 않음 → title_excludes 가 지금 잡을 대상이 없음 (YAGNI).
- 키워드-포함 비-기사 링크가 실제로 나타나면 그때 title_excludes 를 도입한다 (이번 범위 아님).

## 범위
- **변경 파일**: `src/bullet_in/adapters/html.py` · `src/bullet_in/adapters/factory.py` · `config/sources.yaml` · `tests/test_html_adapter.py` · `docs/runbook/` (정리 런북 1건) · 로드맵 (dup_count 완료 표시, 이미 반영).
- **무변경**: enrich · credibility · storage 스키마 · serve · run.py (서빙 쿼리 그대로) · football_london config.

### 범위 밖 (다음 회차)
- **③ 이적무관 실제 기사** (football.london 'other' 61건 등 — 경기리포트 · 평점 · 킷 · FFP): 제목이 깨끗하고 키워드를 실제 포함하므로 키워드/제외 필터로 못 잡음. "안 받기 / 숨기기 / 노출" 은 제품 정책 판단 → 별도 brainstorming.
- ① title_excludes (위 검토대로 불필요) · dup_count (커밋 `7ea0959` 로 이미 완료) · goal · x_afcstuff 복구.

---

## 1. BBC 셀렉터 · 제목 교정 (PR 본체)

### 결정
- `config/sources.yaml` `bbc_sport`:
  - `item_selector`: `a[href*='/sport/football/articles/']` → **`[data-testid='main-content'] a[href*='/sport/football/articles/']`** 로 좁힘. → `content-post` · `navigation` 하위 인라인 링크 (teaser · read-more · nav) 가 전부 탈락, 진짜 카드만 남음.
  - `title_selector`: **`span[class*='LinkPostHeadline']`** 추가 — 카드 안 헤드라인만 추출 (timestamp · visually-hidden 중복 제거).
- `HtmlAdapter` 에 선택적 `title_selector` 도입: 매칭 요소 안에서 sub-selector 로 제목 추출, 없으면 기존 `get_text()` 폴백. item_selector 는 매칭됐으나 sub-요소가 없으면 → 그 항목 skip (제목 없는 항목 적재 방지).

### 근거
- BBC team 페이지는 promo 카드 + 임베드 본문 + nav 가 섞인 혼합 피드. 키워드 필터로는 못 거르고 (제목이 깨져 키워드 매칭 자체가 불안정), **링크 형태 (셀렉터)** 가 본질적 해법.
- 범용 어댑터 확장 (title_selector) 채택 — BBC 전용 어댑터 신설 (코드 과다) · 정규식 후처리 (content-post 쓰레기 못 거름) 대비 최소 · 선언적 · 테스트 가능.

### 리스크
- BBC 해시 클래스 (`LinkPostHeadline`) · `data-testid` 는 외부 사이트 의존 → 드리프트 가능 (CLAUDE.md 함정). **머지 전 어댑터 단독 `fetch()` 라이브 검증 필수.** title_selector 폴백으로 최소 안전.

---

## 2. 기존 데이터 정리 (런북, ③ 보존)

### 결정
- **코드가 아니라 라이브 MariaDB 작업** → 절차 · SQL 을 `docs/runbook/` 에 문서화하고, COUNT 확인 → DELETE 순으로 신중 실행.
- **bbc_sport: 전건 삭제 후 고친 어댑터로 재수집.** 30/34 가 쓰레기 (인라인 링크 · 깨진 제목) 라 패턴별 수술 삭제보다 깔끔. 진짜 4건은 다음 run 에서 *깨끗한 제목으로* 재수집됨.
  - 트레이드오프: 현재 페이지에서 빠진 과거 BBC 기사는 유실 — 어차피 대부분 쓰레기라 수용.
- **football.london: 뉴스레터 legacy 링크만 삭제** (`title_original LIKE '%sent to your inbox%' OR LIKE '%newsletter%'`). **off-topic 실제 기사 (③) 는 보존.**
- arsenal stale-cleanup 런북 (`2026-06-28-arsenal-stale-cleanup.md`): "대상 0건 · 무효" 메모 추가.
- 정리 후 `uv run python -m bullet_in.run` 1회 → bbc 재수집 + 서빙 재생성.

---

## 에러 · 엣지
- `title_selector` None → 기존 `get_text()` 동작 (하위호환). item_selector 매칭됐으나 sub-요소 없음 → 항목 skip.
- 적용 순서 불변: 제목 추출 → title_contains (있으면) 검사. title_contains None 이면 전부 통과 (현행 유지).

## 테스트
- `tests/test_html_adapter.py` 추가 (모킹 HTML):
  - title_selector 로 카드 안 헤드라인만 추출 (timestamp · visually-hidden 섞인 구조에서 클린 제목).
  - title_selector 지정됐으나 sub-요소 없을 때 항목 skip.
  - title_selector None 일 때 기존 `get_text()` 동작 (하위호환 회귀 없음).
- 기존 테스트 회귀 없음.

## 라이브 검증 (머지 전 필수, 수동)
- `bbc_sport.fetch()` → main-content 카드만 (teaser · nav · read-more 없음), 제목 클린, 4건 내외.

## 성공 기준
- 위 단위 테스트 통과 + 기존 회귀 없음.
- 라이브에서 bbc_sport 가 깨끗한 제목의 main-content 기사만 수집.
- 정리 런북 실행 후: DB 에 bbc 쓰레기 · football.london 뉴스레터 없음, ③ 보존, 서빙 재생성.

## 참조
- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` (Tier 1)
- 1차 스펙: `docs/superpowers/specs/2026-06-28-tier1-signal-quality-design.md`
- 운영 한계 관찰: `docs/runbook/2026-06-30-transfer-stage-classification-ops.md`
- 셀렉터 드리프트 함정: `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`
