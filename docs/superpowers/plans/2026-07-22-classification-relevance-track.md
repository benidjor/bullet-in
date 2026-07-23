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

## PR 구조 (2026-07-23 brainstorming 확정)

다섯 항목을 재처리 성격에 따라 세 PR 로 나눈다 (같은 성격끼리 스냅샷 · 백필 · 리뷰 공유, 위험 다른 것 분리).

- **PR-A = B1 + B2 + B5** — 재분류 · 재번역 백필, 재수집 없음.
스냅샷 1 회.
먼저 착수 (작은 성과 선반영).
- **PR-B = B4** — 어댑터 precision 수정 + 재수집.
X 쿠키 소모 준비됐을 때.
- **PR-C = B3** — 관련성 신규 설계.
자체 brainstorm → spec → SDD 를 PR-C 착수 시점에 별도로 돌린다 (지금 미리 파면 구현까지 텀이 길어 컨텍스트가 흐려짐).

브레인스토밍도 PR 단위로 순차 진행한다.
B3 판별 위치는 PR-C 브레인스토밍에서 다룬다.

---

## Task B1: 공신력 등재 · 값 정정 (리뷰 1 · 2026-07-23 사용자 정정)

**Files:** `config/credibility.yaml` · (재분류 스크립트)

- 사용자가 두 인물을 착각했음이 확인됨 → **Ben Jacobs → tier 3 · Gary Jacob → tier 2** 로 확정 (원래 계획은 Ben → 2 였음).
  - **Gary Jacob** (`@garyjacob` · The Times) — 현재 tier 3.
소속 The Times outlet 이 tier 2 라 기자가 아웃렛보다 낮은 역전 → **tier 2 로 상향** (값 수정).
  - **Ben Jacobs** (`@JacobsBen`) — 현재 미등재 (`@JacobsBen` 은 talkSPORT 주석에만 · 아웃렛 폴백으로 tier 4 로 떨어짐) → **tier 3 로 신규 등재**.

**Ben Jacobs 등재 · outlet 결정 (2026-07-23 확정)**:

- 등재 = `{name: Ben Jacobs, tier: 3, outlet: talkSPORT, aliases: ["@JacobsBen", "벤 제이콥스"]}`.
- outlet 은 프로필 · 기고처 (`talksport.com/author/ben-jacobs`) 기준 **talkSPORT**.
- **"Ben 작성 · 공동작성 = tier 3" 은 config 만으로 충족** — x_mentions 모드가 **핸들 매칭을 outlet 폴백보다 먼저** 본다 (`credibility.py:71-77`).
`[ @JacobsBen ]` 인용 → tier 3, talkSPORT 인데 Ben 인용 아님 → outlet 폴백 tier 4 (정상).
별도 tier 코드 변경 없음.
  - 한계 (범위 밖) : afcstuff 가 `@JacobsBen` 을 인용하지 않고 Ben 기사만 링크한 경우, 파이프라인이 저자를 모르고 outlet 폴백 tier 4 로 간다.
바이라인 대조 (`extract_authors`) 는 별도 기능이라 B1 범위 밖 (YAGNI).

- [ ] **Step 1:** `config/credibility.yaml` — Gary Jacob tier 3 → 2 수정 · Ben Jacobs 위 entry 등재 · 부분 문자열 충돌 점검.
Gary 별칭 `"jacob"` 이 fmkorea 부분 문자열 모드에서 `"jacobs"` 텍스트를 오매치할 수 있어 (`credibility.py:87` `a in text`) 점검한다 (`docs/troubleshooting/2026-07-22-glossary-substring-traps.md`).
- [ ] **Step 2:** 두 기자의 기존 기사 재분류 (해당 행 `tier` 재계산) — 재분류 대상 · 절차는 런북 참조.
- [ ] **Step 3:** 화면에서 Gary Jacob tier 2 · Ben Jacobs tier 3 표시 확인.
- [ ] **Step 4:** Commit — `chore(credibility): Gary Jacob tier 2 상향 · Ben Jacobs tier 3 등재`.

## Task B2: 영입 단계 분류 정확도 — 구두 합의 (리뷰 2-5)

**Files:** `src/bullet_in/enrich.py` (STAGE_PROMPT) · (재분류)

- `cc2c7b58` "첼시, 모건 로저스 영입 **구두 합의**" 가 `negotiating` 으로 저장됐다.
"구두 합의" 는 `agreed` (이적 합의) 에 가깝다 — 분류 프롬프트가 "합의 도달" 신호를 협상 중으로 떨어뜨린다.
- `agreed` enum 은 이미 존재한다 (`transfer_stage.py:11` · 총 8 단계) — 새 값 추가가 아니라 프롬프트 경계 명확화 문제다.

**실측 (bulletin_mock 256 행) · 방식 확정 (2026-07-23)**:

- "합의 도달" 신호가 negotiating · rumour 로 흩어져 떨어짐 — `cc2c7b58` (구두 합의) · `2f556abe` (verbal agreement) · `b2a4b681` (원칙적 합의) · `5e35e51a2` (on verge of signing) · rumour `aeb2d493b5` · `28ae255921` (agree).
`agreed` 로 올바르게 분류된 행 (Arsenal agree £34m 등) 은 정상.
- **(B2-1) 프롬프트 = agreed · negotiating 두 줄에 인라인 명확화** (별도 임계표현 목록보다 간결 · 수술적).
  - `negotiating` : `… 협상 중 (아직 합의 전 — '합의 도달'이면 agreed)`
  - `agreed` : `… 딜 확정/임박 (구두 합의 · 원칙적 합의 · verbal agreement · agreement in principle · 'on verge of signing' 포함 · 타 매체 공식 발표 보도 포함)`
- **(B2-2) 재분류 = 타깃** — `agreed` · `official` 아래 단계 (negotiating · interest · rumour · other) 중 **합의 도달 키워드** (구두 합의 · 원칙적 합의 · verbal agreement · agreement in principle · agree · reached an agreement · on verge) 매칭 행만 `transfer_stage` 를 NULL 로 되돌리고 `classify_stage_rows` 재실행.
전건 재분류는 LLM 변동성으로 이미 맞은 행까지 뒤섞을 위험 + Gemini 비용 큼.
- 프롬프트를 고쳐도 기존 행은 그대로라 재분류가 필요하다 (트리거 `transfer_stage IS NULL` 복원 후 재실행 · 런북 `2026-06-30-transfer-stage-classification-ops.md`).

**재분류 실측 정정 (2026-07-23 · 중요)**:

- 키워드 후보 4 행 중 3 행이 **비아스날 딜** 이었다 — `cc2c7b58` (첼시 ← 모건 로저스) · `b2a4b681` (뉴캐슬 ← 만잠비) · `2f556abe` (첼시 ← 모건 로저스 중복).
플랜의 대표 사례 `cc2c7b58` 은 B2 (단계) 가 아니라 **B3 (관련성) 케이스** 였다 (아스날 무관 기사가 team=arsenal 로 저장).
- 현재 택소노미는 **아스날 중심** ("아스날 FC 관련 이적 진행 단계") 이라, 첼시 딜을 agreed 로 달면 "아스날이 합의" 로 오독된다.
딜 자체는 agreed 가 맞지만 아스날 관점 단계엔 안 맞는다.
- **B2 스코프 = 진짜 아스날 딜의 합의 단계만** 고친다 — 실측에서 유효 사례는 `5e35e51a2` (아스날 촐리스 영입 임박 → agreed) 뿐.
비아스날 행은 B2 가 건드리지 않고 (재분류가 관련성을 불안정하게 침범 · `2f556abe` → interest 오분류 관측) **B3 에서 team 으로 처리**.
- 타깃 재분류 candidate 는 키워드만으로 비아스날을 못 거른다 — 재분류 결과 중 비아스날 행은 원 stage 로 롤백하고 아스날 딜만 반영한다.

- [ ] **Step 1:** 합의 도달 키워드로 후보 행 정확 카운트 (mock 기준 대략 6 ~ 10 행) · 재분류 대상 확정.
- [ ] **Step 2:** STAGE_PROMPT 인라인 명확화 + enum 동기화 가드 테스트 유지.
- [ ] **Step 3:** 대상 행만 NULL 복원 · `classify_stage_rows` 재실행 · 분포 검증 · 사례 재확인.
- [ ] **Step 4:** Commit — `fix(enrich): 구두 합의류를 이적 합의로 분류 — 단계 프롬프트 보강`.

## Task B3: 아스날 무관 기사 관련성 필터 (리뷰 5 · 스펙 §16.3)

**Files:** `src/bullet_in/adapters/fmkorea.py` 또는 분류 계층 · (백필 정리)

- fmkorea 게시판에 타 구단 소식도 올라오는데 관련성 판별이 없어 `team=arsenal` 로 저장돼 그대로 실린다.
실사례 = 노팅엄 포레스트 크사버 슐라거 영입 기사.
- **가장 큰 설계 결정이라 brainstorming → spec 이 선행돼야 한다** — 관련성을 수집 시 필터할지 (제목 아스날 키워드 강화) · enrich 분류로 뺄지 (아스날 관련 여부 판정) · 서빙에서 숨길지 (표시 토글, PR #22 선례).
- 스펙 §16.3 이 "수집 · 분류 계층 문제" 로 명시 — 표시 계층 우회는 임시책일 뿐.

**딜 중심 stage + team 설계 입력 (2026-07-23 B2 발견 · 다팀 로드맵 정합)**:

- 현재 세 개념이 "전부 아스날 중심" 으로 뭉쳐 있다 — 이걸 분리해야 다팀 (첼시 · 맨시티 등 향후 추가 계획) 으로 확장된다.
  - **stage** = 딜 진행 정도 (매입 구단 기준 · 객관) — 지금은 "아스날의 단계" 로 아스날 중심.
  - **team** = 누구의 딜 (매입 구단) — 지금 전부 arsenal 하드코딩 (이 버그가 B3).
  - **serving** = 어느 피드에 노출 — 지금 arsenal-only 필터.
- 이 모델에서 `cc2c7b58` = {team: chelsea, stage: agreed} — stage 는 "딜 합의됨" (객관), team 이 "첼시 딜" 임을 말하고, 서빙이 "아스날 피드엔 안 보임" 을 결정.
첼시 · 맨시티 추가 시 그대로 재사용.
- B3 spec 은 관련성 판별 위치뿐 아니라 **team 을 실제 매입 구단으로 검출할지 (딜 중심 stage 전환)** 도 함께 결정한다.
단, 딜 중심 전환은 stage 프롬프트의 아스날 중심 프레이밍을 바꾸는 큰 변경이라 다팀 착수와 묶일 수 있다.

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
제목 번역이 환각 게이트에 재차 걸려 원문으로 굳혀진 것 (`enrich.py:297` — retry 재발 시 `title_original` 폴백이 종착 상태).
- `title_ko` 가 NULL 이 아니라 영어라 '번역 대기' 배지도 안 뜬다 (`title_pending` 은 NULL 만 감지 · `render.py:133`) → 영어 제목이 아무 표시 없이 노출.

**방식 확정 (2026-07-23) — 방안 1 (NULL 재큐)**:

- **`enrich.py:297` 영어 고정 → `title_ko = None`** (한 줄 · 스키마 무변경).
`rows_missing_translation` 이 `WHERE title_ko IS NULL` 이라 (`mariadb.py:79`) 다음 사이클에 자동 재선별 → 재번역.
NULL 이라 `title_pending` 이 자동으로 '번역 대기' 배지를 띄운다 (표시 계층 Track A 보완 불필요).
- 화면 : title_ko 가 NULL 이면 `_title` 이 title_original (영어) 로 폴백 표시 (`render.py:717`) + '번역 대기' 배지.
매 사이클 (6 시간 · 하루 4 회) 자동 재시도 → 게이트 통과하는 한국어가 나오면 교체.
- **기존 영어 폴백 행 백필** : `title_ko` 에 한글 0 (Latin only) 인 행을 NULL 로 되돌려 재번역 큐 재진입 (mock 1 건 · VM 엔 몇 건 더 가능).

**결정적 오탐 진단 결과 (2026-07-23 · 실 Gemini 재번역 5 회)**:

- `7341690b` 의 좋은 번역 ("아스날 · 첼시 · 맨유 노리는 알렉스 스콧, 리버풀 영입전 가세") 이 **`인명 누락:Arteta` 게이트에 결정적으로 걸림** (1 ~ 3 회 FLAGGED · 5 회는 Arteta 억지 삽입한 어색한 제목으로만 PASS).
원제 "With Arteta's Backing…" 의 Arteta 는 부차적 프레이밍인데 `detect_title_mistranslation` 이 원제 인명 전부를 요구해 **좋은 제목을 오탐 거부**한다.
- 즉 뿌리는 폴백 방식이 아니라 **NAME_MISSING 게이트가 부차 인명에 과하게 엄격** 한 것 → 방안 1 로는 이 부류가 대개 배지로 남거나 어쩌다 어색한 제목으로 풀린다.
- **게이트 오탐 수정은 별도 후속 트랙** (환각 게이트는 전 소스 공유 로직이라 blast radius 큼 · 자체 TDD 필요) — 아래 '후속 트랙 백로그' 참조.
방안 1 이 그 사이 증상을 정직하게 (배지 + 자동 재시도) 처리하므로 급하지 않다.

**관측 — 로그 ① ② 추가 (Discord 는 후속으로 보류)**:

- ① WARNING 로그 상태 구분 : `1차 큐` / `재시도 잔존 (재큐)` / `해소`.
- ② enrich 패스 끝에 사이클 요약 한 줄 : `재번역 큐 요약 : 신규 X · 잔존 Y · 해소 Z (남은 NULL N)`.
- 관측 = pull (로컬 stderr · VM `journalctl -u bullet-in | grep`) + 기존 `ops.html` '번역 대기' KPI (완성품 · 재사용).
- Discord push 는 게이트 오탐 미수정 상태에선 결정적 오탐 행이 매 사이클 재실패해 스팸 → 후속 트랙 (게이트 수정 후) 으로 보류.

- [ ] **Step 1:** 영어로 폴백된 title_ko 행 백필 대상 확정 (한글 0 · Latin 제목).
- [ ] **Step 2:** `enrich.py:297` 영어 고정 → NULL 재큐 (방안 1) · 로그 ① ② 추가 · TDD.
- [ ] **Step 3:** 기존 영어 폴백 행 NULL 백필 → 재번역 큐 재진입 확인 · 배지 확인.
- [ ] **Step 4:** Commit — `fix(enrich): 게이트 거부 제목 재번역 큐 — 영어 폴백 방지`.

## Task B6: 통합 검증 · PR

- [ ] **Step 1:** 전체 테스트 통과 · 재분류/백필/재수집 분포 검증.
- [ ] **Step 2:** 라이브 (VM) 반영 후 화면에서 다섯 항목 (공신력 값 · 단계 정확도 · 무관 기사 · 발행 시각 · 제목 번역) 해소 확인.
- [ ] **Step 3:** push · PR (7섹션 · humanize · 머지는 사용자).

## 후속 트랙 백로그 (2026-07-23 발견 · 트랙 B 밖)

B5 진단에서 새로 드러난 별도 트랙 — 착수 시점은 사용자 결정 (권장 = 트랙 B 이후).

- **제목 게이트 오탐 완화 + 재번역 escalation 알림** (하나로 묶음) :
  - **NAME_MISSING 게이트 오탐 수정** (핵심 지렛대) — `detect_title_mistranslation` 이 부차 인명 (프레이밍) 까지 요구해 좋은 제목을 거부한다 (`7341690b` 실증).
전 소스 공유 게이트라 blast radius 큼 → 자체 brainstorm → spec → SDD.
  - **Discord push** — 게이트 수정으로 큐가 평소 비게 된 뒤라야 스팸이 아니라 진짜 신호가 된다.
  - **재시도 → 소진 시 escalation 알림 설계** (사용자 제안) — 한 사이클 안에서 N 회 재시도 후 다 실패면 알림 (사이클 간 상태 저장 불필요).
게이트 수정 후엔 진짜 실패에만 발송.
  - **사이클 내 즉시 재시도** 는 게이트 수정 후 실제 대기가 남는지 보고 판단 (투기적 선구현 금지 · YAGNI).

## Self-Review — 항목 커버리지

리뷰 1 → B1 · 리뷰 2-5 → B2 · 리뷰 5 → B3 · afcstuff · goal 시각 → B4 · 제목 영어 폴백 → B5.
표시 항목 (2-1~2-4 · 3 · 4 · 6 · 7 · 8 · 9) 은 트랙 A (완료 · 머지됨) 로 제외.
PR 구조 (A = B1+B2+B5 · B = B4 · C = B3) 는 상단 'PR 구조' 참조.
