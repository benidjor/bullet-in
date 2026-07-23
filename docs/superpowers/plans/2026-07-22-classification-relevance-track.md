# 분류 · 공신력 · 관련성 정리 계획 (트랙 B)

> **For agentic workers:** REQUIRED SUB-SKILL: 각 항목은 brainstorming → (필요 시) spec → SDD 로 진행한다.
> 재분류 · 백필은 되돌릴 수 없으므로 스냅샷을 먼저 뜬다.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR #121 이 소유권 경계로 제외한 분류 · 공신력 · 관련성 문제를 표시 계층 밖에서 바로잡는다.

**Architecture:** enrich · credibility · 수집 계층을 고친다.
서빙 (`src/bullet_in/serve/`) 은 건드리지 않는다 — 표시는 저장된 tier · stage · team 을 그대로 읽는다.

**Tech Stack:** Python 3.11 · google-genai (enrich 분류) · SQLAlchemy · pytest.

## Global Constraints

- **새 브랜치를 main 에서 판다** (PR #121 머지 후 최신 main 기준).
- 저장된 `tier` · `transfer_stage` · `team` 은 enrich 시점 값이라, config · 프롬프트만 고치면 **기존 행은 안 바뀐다** — 재분류/백필이 뒤따라야 화면에 반영된다.
- 재분류 · 백필 전 스냅샷 필수 (`docs/runbook/2026-07-19-enrich-only-pass.md` §5 · 백필 스냅샷 관례).
- 운영 SoT = seoulnow VM · 로컬 mart 는 낡음 — 라이브 반영은 VM 에서.
- 사전 항목 추가 시 부분 문자열 함정 3종 선점검 (`docs/troubleshooting/2026-07-22-glossary-substring-traps.md`).
- PR 머지는 사용자 직접.

## 착수 전 확인 (진단부터)

- **로컬 mart 는 낡을 수 있으니** 스펙 · 머지된 PR 을 먼저 검색한다 (`check-specs-before-diagnosing`).
- 다섯 항목 (B1 공신력 값 · B2 단계 정확도 · B3 관련성 · B4 발행 시각 · B5 제목 번역) 을 하나의 PR 로 묶을지 나눌지는 brainstorming 에서 결정한다.
성격이 갈린다 — config (B1) · enrich 프롬프트 (B2) · 신규 설계 (B3) · 어댑터+재수집 (B4) · enrich 재번역 (B5).

---

## Task B1: 공신력 등재 · 값 정정 (리뷰 1 · 2026-07-23 사용자 정정)

**Files:** `config/credibility.yaml` · (재분류 스크립트)

- 사용자가 두 인물을 착각했음이 확인됨 → **Ben Jacobs → tier 3 · Gary Jacob → tier 2** 로 확정 (원래 계획은 Ben → 2 였음).
  - **Gary Jacob** (`@garyjacob` · The Times) — 현재 tier 3.
소속 The Times outlet 이 tier 2 라 기자가 아웃렛보다 낮은 역전 → **tier 2 로 상향** (값 수정).
  - **Ben Jacobs** (`@JacobsBen` · CBS) — 현재 미등재 (`@JacobsBen` 은 talkSPORT 주석에만 · 아웃렛 폴백 경로) → **tier 3 로 신규 등재**.
여러 매체 · 소셜에 걸쳐 활동하므로 아웃렛 매핑을 사용자와 확정한다.

- [ ] **Step 1:** `config/credibility.yaml` — Gary Jacob tier 3 → 2 수정 · Ben Jacobs (tier 3 · 별칭 `@JacobsBen` · 한글 표기) 등재 · 부분 문자열 충돌 점검.
- [ ] **Step 2:** 두 기자의 기존 기사 재분류 (해당 행 `tier` 재계산) — 재분류 대상 · 절차는 런북 참조.
- [ ] **Step 3:** 화면에서 Gary Jacob tier 2 · Ben Jacobs tier 3 표시 확인.
- [ ] **Step 4:** Commit — `chore(credibility): Gary Jacob tier 2 상향 · Ben Jacobs tier 3 등재`.

## Task B2: 영입 단계 분류 정확도 — 구두 합의 (리뷰 2-5)

**Files:** `src/bullet_in/enrich.py` (STAGE_PROMPT) · (재분류)

- `cc2c7b58` "첼시, 모건 로저스 영입 **구두 합의**" 가 `negotiating` 으로 저장됐다.
"구두 합의" 는 `agreed` (이적 합의) 에 가깝다 — 분류 프롬프트가 "합의" 신호를 협상 중으로 떨어뜨린다.
- **범위 결정** — 프롬프트에 구두 합의 · 원칙적 합의 → `agreed` 예시를 보강할지, 임계 표현 목록을 둘지 brainstorming 에서 정한다.
- 프롬프트를 고쳐도 기존 행은 그대로라 재분류가 필요하다 (트리거 `transfer_stage IS NULL` 복원 후 재실행 · 런북 `2026-06-30-transfer-stage-classification-ops.md`).

- [ ] **Step 1:** 오분류 사례 수집 (구두 합의 · 원칙적 합의류가 negotiating 으로 떨어진 행) · 실측 근거로 프롬프트 조정 방향 확정.
- [ ] **Step 2:** STAGE_PROMPT 보강 + enum 동기화 가드 테스트 유지.
- [ ] **Step 3:** 대상 행 재분류 · 분포 검증 · 사례 재확인.
- [ ] **Step 4:** Commit — `fix(enrich): 구두 합의류를 이적 합의로 분류 — 단계 프롬프트 보강`.

## Task B3: 아스날 무관 기사 관련성 필터 (리뷰 5 · 스펙 §16.3)

**Files:** `src/bullet_in/adapters/fmkorea.py` 또는 분류 계층 · (백필 정리)

- fmkorea 게시판에 타 구단 소식도 올라오는데 관련성 판별이 없어 `team=arsenal` 로 저장돼 그대로 실린다.
실사례 = 노팅엄 포레스트 크사버 슐라거 영입 기사.
- **가장 큰 설계 결정이라 brainstorming → spec 이 선행돼야 한다** — 관련성을 수집 시 필터할지 (제목 아스날 키워드 강화) · enrich 분류로 뺄지 (아스날 관련 여부 판정) · 서빙에서 숨길지 (표시 토글, PR #22 선례).
- 스펙 §16.3 이 "수집 · 분류 계층 문제" 로 명시 — 표시 계층 우회는 임시책일 뿐.

- [ ] **Step 1:** brainstorming — 관련성 판별 위치 (수집 필터 vs enrich 분류 vs 서빙 토글) 결정 · 실사례로 오탐 · 미탐 범위 측정.
- [ ] **Step 2:** spec 작성 (판별 기준 · 되돌림성 · 기존 무관 행 처리).
- [ ] **Step 3:** SDD 구현 + 라이브 검증 (무관 기사 제외 확인).
- [ ] **Step 4:** Commit · PR.

## Task B4: afcstuff · goal 발행 시각 어댑터 precision (2026-07-23 발견)

**Files:** `src/bullet_in/adapters/x_playwright.py` · goal 어댑터 · (재수집)

- 가십 카드가 발행 시각을 못 보여 주는 근본 원인 — 어댑터가 `published_at` · `published_precision` 을 제대로 안 채운다.
  - **afcstuff (x)** — 트윗 게시 시각을 `published_at` 에 갖고 있으나 `published_precision` 을 `time` 으로 안 붙임 → 표시가 날짜만.
  - **goal** — 실제 발행 시각 대신 수집 시각을 `published_at` 에 저장 (precision None) → 실제 시각 미포착.
- 표시 계층 (트랙 A `gossip_when` · 상세 발행 칸) 은 `precision == 'time'` 일 때만 시각을 병기하도록 이미 만들어 둠 → 어댑터가 precision 을 맞추면 자동 반영.
- 어댑터 수정 후 **재수집** 필요 (기존 저장 행은 안 바뀜) — fmkorea 2h · 429 규칙 · X 쿠키 1회 소모 주의.

- [ ] **Step 1:** 두 어댑터의 published_at · precision 저장 지점 확인 · X 트윗 시각 파싱 정합성 점검.
- [ ] **Step 2:** afcstuff precision=time 표기 · goal 실제 발행 시각 파싱 (없으면 precision None 유지 — 없는 시각 지어내지 않음).
- [ ] **Step 3:** 재수집 후 화면에서 시각 병기 확인 (afcstuff 예: 9:43 PM = 21:43 KST).
- [ ] **Step 4:** Commit — `fix(adapters): afcstuff · goal 발행 시각 precision 정정`.

## Task B5: 제목만 영어로 폴백 — 재번역 큐 (2026-07-23 발견 · §12.1)

**Files:** `src/bullet_in/enrich.py` · (재번역)

- `7341690b` (goal) 처럼 **본문 · 요약은 한국어인데 title_ko 가 영어 원문** 인 행이 있다.
제목 번역이 환각 게이트에 걸려 원문으로 폴백된 것 (재번역 큐 §12.1 실사례).
- `title_ko` 가 NULL 이 아니라 영어라 '번역 대기' 배지도 안 뜬다 (`title_pending` 은 NULL 만 감지) → 영어 제목이 아무 표시 없이 노출.
- **범위 결정** — 게이트가 제목을 거부할 때 원문으로 굳히지 말고 NULL 로 두어 재번역 큐에 넣을지 · 재시도 전략을 brainstorming 에서 정한다.
- 표시 계층 보완 (영어 title_ko 를 '번역 대기' 로 감지) 은 트랙 A 옵션 — 근본은 여기 (재번역).

- [ ] **Step 1:** 영어로 폴백된 title_ko 행 수집 (한글 0 · Latin 제목) · 게이트 거부 경위 확인.
- [ ] **Step 2:** 제목 재번역 · 게이트 폴백 처리 조정 (원문 굳히기 대신 재시도 큐).
- [ ] **Step 3:** 재번역 후 한국어 제목 · 배지 확인.
- [ ] **Step 4:** Commit — `fix(enrich): 게이트 거부 제목 재번역 큐 — 영어 폴백 방지`.

## Task B6: 통합 검증 · PR

- [ ] **Step 1:** 전체 테스트 통과 · 재분류/백필/재수집 분포 검증.
- [ ] **Step 2:** 라이브 (VM) 반영 후 화면에서 다섯 항목 (공신력 값 · 단계 정확도 · 무관 기사 · 발행 시각 · 제목 번역) 해소 확인.
- [ ] **Step 3:** push · PR (7섹션 · humanize · 머지는 사용자).

## Self-Review — 항목 커버리지

리뷰 1 → B1 · 리뷰 2-5 → B2 · 리뷰 5 → B3 · afcstuff · goal 시각 → B4 · 제목 영어 폴백 → B5.
표시 항목 (2-1~2-4 · 3 · 4 · 6 · 7 · 8 · 9) 은 트랙 A (완료 · 머지됨) 로 제외.
