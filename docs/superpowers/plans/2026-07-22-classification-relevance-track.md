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
- 세 항목이 하나의 PR 로 묶일지 (관련성 + 등재 + 분류 정확도) 는 brainstorming 에서 결정한다.

---

## Task B1: Ben Jacobs 공신력 등재 (리뷰 1)

**Files:** `config/credibility.yaml` · (재분류 스크립트)

- 현재 Ben Jacobs 는 미등재다 — 등록된 건 다른 사람 "Gary Jacob" (tier 3 · The Times).
`@JacobsBen` 은 talkSPORT 항목 주석에만 있고 기자 미등재라 아웃렛 폴백 경로다.
- **결정 필요** — Ben Jacobs 를 어느 아웃렛 · 어느 tier 로 등재할지 (사용자 요청 = tier 2).
Ben Jacobs 는 특정 매체 전속이 아니라 여러 매체 · 소셜에 걸쳐 활동하므로 아웃렛 매핑을 사용자와 확정한다.

- [ ] **Step 1:** `config/credibility.yaml` `journalists` 에 Ben Jacobs 등재 (tier 2 · 별칭 `@JacobsBen` · 한글 표기 포함) · 부분 문자열 충돌 점검.
- [ ] **Step 2:** 기존 Ben Jacobs 기사 재분류 (해당 행 `tier` 재계산) — 재분류 대상 · 절차는 런북 참조.
- [ ] **Step 3:** 화면에서 Ben Jacobs 기사 tier 2 표시 확인.
- [ ] **Step 4:** Commit — `chore(credibility): Ben Jacobs 기자 등재 — tier 2`.

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

## Task B4: 통합 검증 · PR

- [ ] **Step 1:** 전체 테스트 통과 · 재분류/백필 분포 검증.
- [ ] **Step 2:** 라이브 (VM) 반영 후 화면에서 세 항목 (Ben Jacobs tier · 단계 정확도 · 무관 기사) 해소 확인.
- [ ] **Step 3:** push · PR (7섹션 · humanize · 머지는 사용자).

## Self-Review — 항목 커버리지

리뷰 1 → B1 · 리뷰 2-5 → B2 · 리뷰 5 → B3.
표시 항목 (2-1~2-4 · 3 · 4 · 6 · 7 · 8 · 9) 은 트랙 A (별도 플랜) 로 제외.
