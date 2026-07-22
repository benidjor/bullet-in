# 서빙 UI 개편 리뷰 반영 계획 (트랙 A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (또는 subagent-driven-development) 로 태스크 단위로 실행한다.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR #121 (서빙 UI 개편) 에 대한 사용자 리뷰 피드백을 머지 전에 이 브랜치에서 반영한다.

**Architecture:** 표시 계층 (`src/bullet_in/serve/`) 만 고친다.
분류 · 공신력 · 수집은 트랙 B (별도 세션 · 머지 후) 소관이라 건드리지 않는다.

**Tech Stack:** Python 3.11 · Jinja2 · 바닐라 CSS/JS · pytest.

## Global Constraints

- 브랜치는 `feat/serve-ui-redesign` 를 이어서 쓴다 (PR #121, 미머지). 새 브랜치를 파지 않는다.
- 표시 계층만 수정 — `config/` · `enrich.py` · `adapters/` · `transfer_stage.py` 무수정.
- 소유권 경계 (스펙1 §15) 를 유지한다 — `gossip_itemize` · `bbc_gossip` 분기 · `serving_mode` · `excerpt-note` 판정 로직 무수정.
- 강조 3색 · 반경 0–2px · 이모지 없음 · 내부 Tier 문자열 노출 금지 (스펙1 §4 · §7.1).
- 검증 데이터 = 로컬 `bulletin_mock` (VM 256행), 렌더 전용 패스 (`docs/runbook/2026-07-19-enrich-only-pass.md` §4), 프리뷰 localhost:8749.
- F안 목업 = localhost:8642 `/f/index.html` (9-1 · 9-2 대조 기준).
- 테스트 기준선 = 538 passed · 1 skipped.

## File Structure

| 파일 | 책임 |
|---|---|
| `src/bullet_in/serve/render.py` | 상세 발행 시각 뷰모델 · 클러스터 인바운드 가드 · 관련 보도 정렬 |
| `src/bullet_in/serve/templates/detail.html.j2` | 메타 그리드 · 기자 칸 · 발행 시각 |
| `src/bullet_in/serve/templates/index.html.j2` | 카드 헤드라인 · 배지 배치 · 가십 더보기 · 주 단위 더보기 |
| `src/bullet_in/serve/static/style.css` | 메타 그리드 정렬 · 요약 음영 · 배지 크기 · 가십 가독성 · 사이드바 크기 · 밴드 |
| `src/bullet_in/serve/static/app.js` | 가십 더보기 · 주 단위 더보기 토글 |
| `tests/test_serve_redesign.py` | 인바운드 가드 · 정렬 단위 테스트 |

---

## Task A1: 상세 메타 그리드 — 가운데 정렬 · 기자 괄호 제거 (2-1 · 2-3)

**Files:** `detail.html.j2` · `style.css`

- **2-1** — `.metagrid` 각 칸의 라벨 · 값을 가운데 정렬 (`text-align:center`) · 칸 구분 괘선 유지.
- **2-3** — 기자 칸은 언론사 칸이 따로 있으므로 괄호 소속을 항상 뺀다.
`a._byline` (이름 (언론사)) 대신 `a._journalist` (정규화 이름) 를 쓰거나, 표시용 이름만 내보낸다.

- [ ] **Step 1:** `detail.html.j2` 메타 그리드 기자 `<dd>` 를 `a._journalist` (또는 이름만) 으로 · `style.css` `.metagrid` 가운데 정렬.
- [ ] **Step 2:** 렌더 후 `cc2c7b58` 상세에서 값 중앙 · 기자 괄호 없음 확인.
- [ ] **Step 3:** Commit — `fix(serve): 상세 메타 그리드 가운데 정렬 · 기자 칸 괄호 제거`.

## Task A2: 상세 발행 시각 (KST) (2-2)

**Files:** `render.py` · `detail.html.j2`

- 상세는 현재 `a._date` (날짜만) 를 쓴다.
`published_precision` 이 `time` 이면 KST 날짜 + `HH:MM` 을, `day` 이거나 없으면 날짜만 보여 준다 (스펙1 §12 — 없는 시각을 지어내지 않는다).

- [ ] **Step 1:** 실패 테스트 — `_decorate` 가 `_datetime` (time 정밀도 → `2026-07-14 22:37`, day → `2026-07-14`) 를 채우는지.
- [ ] **Step 2:** 구현 — `to_kst` 로 변환한 날짜 + 시각 문자열.
- [ ] **Step 3:** 상세 발행 칸을 `a._datetime` 으로 · `1a6444ec` (time 정밀도) 에서 시각까지 뜨는지 확인.
- [ ] **Step 4:** Commit — `feat(serve): 상세 발행 시각 KST 병기 (time 정밀도)`.

## Task A3: 핵심 요약 음영 (2-4)

**Files:** `style.css`

- `.summary` 에 배경 (`var(--sunk)`) · 안쪽 여백을 넣어 본문과 구분 · 붉은 상단 괘선은 유지.

- [ ] **Step 1:** `.summary` 배경 · 패딩 추가 · 라이트 · 다크 대비 확인.
- [ ] **Step 2:** Commit — `fix(serve): 핵심 요약 칸 음영으로 구분 강화`.

## Task A4: 카드 헤드라인 vs 단계 · dest 배지 정렬 (3)

**Files:** `index.html.j2` · `style.css`

- 현재 배지 (`협상 중` · `개인 합의` · dest 칩) 가 헤드라인과 인라인이라 크기 · 위치가 어긋난다.
- F안 (8642) 의 카드 배지 배치를 기준으로 배지를 제목 위 별도 줄로 올리거나 크기 · 정렬을 맞춘다.
결정 전 8642 카드와 대조한다.

- [ ] **Step 1:** 8642 `/f/index.html` 카드 배지 배치 확인 후 `.htitle` 구조 · CSS 조정 (배지 별도 줄 또는 크기 상향).
- [ ] **Step 2:** 라이트 · 다크에서 한눈에 읽히는지 확인.
- [ ] **Step 3:** Commit — `fix(serve): 카드 단계 · 결말 배지 배치 정리`.

## Task A5: 클러스터 인바운드 오탐 (4 · 8)

**Files:** `render.py` · `tests/test_serve_redesign.py`

- `1a6444ec` "뉴캐슬 주장 기마랑이스, 아스날 이적 의사 구단에 전달" 이 결말 · "뉴캐슬행 관련" 갈래로 오판된다.
제목이 아스날로 시작 안 함 + 첫 절에 뉴캐슬 → `_is_other_club_report` 가 참을 낸다.
그러나 뉴캐슬은 선수의 현 소속이고 제목이 "아스날 이적 의사" 라 아스날로 **오는** 사건이다.
- **가드:** 제목에 아스날 인바운드 신호 (`아스날 이적` · `아스날 합류` · `아스날행` · `아스날 이적 의사` · `아스날로`) 가 있으면 `_is_other_club_report` 가 None 을 낸다.
이 가드는 결말 카드 · 관점 갈래 · dest 칩에 함께 걸린다.

- [ ] **Step 1:** 실패 테스트 — `_is_other_club_report({"title_ko":"뉴캐슬 주장 기마랑이스, 아스날 이적 의사..."}, "기마랑이스", CLUBS)` 가 None · 실제 다른 구단행 (`첼시, 로저스 영입 합의`) 은 여전히 구단명 반환.
- [ ] **Step 2:** 실패 확인 후 `_is_other_club_report` 앞에 인바운드 신호 가드 추가.
- [ ] **Step 3:** 통과 확인 + 전체 스위트 · `1a6444ec` 재렌더에서 dest 칩 · 뉴캐슬행 갈래 사라졌는지 확인.
- [ ] **Step 4:** Commit — `fix(serve): 클러스터 인바운드 오탐 차단 — 아스날 이적 의사 제외`.

## Task A6: 관련 보도 시간순 안정화 (9)

**Files:** `render.py` · `tests/test_serve_redesign.py`

- "아스날 쪽 보도" 갈래가 시간순으로 안 선다.
발행 시각이 없는 소스가 수집 시각으로 폴백해 같은 시각으로 뭉치기 때문 (스펙2 §6.1 이 예견).
- 정렬 키를 `_sort_ts` (published 우선 · day 보간 · fetched 폴백) 로 통일하고, 표시에서 날짜가 대표와 다르면 날짜를 병기하는 규칙 (스펙2 §4.1) 이 실제로 걸리는지 확인한다.
- 근본 (발행 시각 부재) 은 수집 한계라 표시 계층에서는 정렬 안정화까지만 한다.

- [ ] **Step 1:** `related_reports` 정렬이 `_sort_ts` 기준인지 점검 · 필요 시 보정 테스트 추가.
- [ ] **Step 2:** `1a6444ec` 클러스터 관련 보도에서 시간순 확인 (동시각 뭉침은 날짜 병기로 구분).
- [ ] **Step 3:** Commit — `fix(serve): 관련 보도 정렬 키 통일 — 발행 시각 폴백 안정화`.

## Task A7: 히어로 · 주요소식 F안 정렬 (9-1)

**Files:** `index.html.j2` · `style.css`

- 밴드 (리드 + 주요 4) 배치 · 비율 · 정렬을 F안 (8642) 기준으로 맞춘다.
- 로직 (톱스토리 선정) 은 스펙2 §5 를 따르되, **시각 배치**만 F안과 대조해 이탈을 바로잡는다.

- [ ] **Step 1:** 8642 `/f/index.html` 밴드와 현재 밴드를 나란히 대조 · 차이 목록화.
- [ ] **Step 2:** 템플릿 · CSS 로 비율 · 여백 · 정렬 조정.
- [ ] **Step 3:** Commit — `fix(serve): 톱스토리 밴드 배치를 F안 목업 기준으로 정렬`.

## Task A8: 사이드바 필터 크기 F안 (9-2)

**Files:** `style.css`

- 좌측 필터 폭 · 글자 크기 · 여백이 F안과 다르다.
`--side` · `.side` · `.opt` 크기를 8642 기준으로 맞춘다.

- [ ] **Step 1:** 8642 사이드바와 대조 후 CSS 조정.
- [ ] **Step 2:** 폭 990 · 390 에서 붕괴 없는지 확인.
- [ ] **Step 3:** Commit — `fix(serve): 사이드바 필터 크기를 F안 목업 기준으로 조정`.

## Task A9: 가십 가독성 · 더보기 · 시간 (6-1 · 6-2 · 6-3)

**Files:** `index.html.j2` · `style.css` · `app.js`

- **6-1** — 3열이 빽빽하다 (실데이터 88묶음). 열 간격 · 행 여백 · 항목 높이를 키워 가독성을 올린다.
초기 노출 건수를 제한하는 것과 병행한다 (아래 6-2).
- **6-2** — 가십에 더보기 버튼을 둔다.
초기 N묶음만 노출하고 버튼으로 나머지를 편다 (사이드바 facet 더보기와 같은 패턴).
- **6-3** — 가십은 발행 시각이 없어 수집 시각만 있다 (BBC 가십 등).
시각만으로는 순서를 알기 어려우니 날짜를 병기하거나, 수집 시각임을 드러낸다.
근본 (발행 시각 부재) 은 수집 한계.

- [ ] **Step 1:** `.gossiplist` 여백 · 열 간격 조정 (6-1).
- [ ] **Step 2:** 가십 초기 N묶음 + 더보기 버튼 (`index.html.j2` 초기 슬라이스 · `app.js` 토글) (6-2).
- [ ] **Step 3:** 가십 카드 시각을 날짜 병기 또는 수집 시각 표시로 (6-3).
- [ ] **Step 4:** 프리뷰에서 가독성 · 더보기 · 시각 확인.
- [ ] **Step 5:** Commit — `fix(serve): 가십 구역 가독성 · 더보기 · 시각 표시 개선`.

## Task A10: 최신 소식 주 단위 더보기 (7)

**Files:** `index.html.j2` · `app.js` (F안 대조 후 확정)

- 스펙 2건에는 최신 소식 더보기가 없다 (사이드바 facet 더보기뿐).
- **먼저 F안 (8642) 에 주 단위 더보기가 있는지 확인한다.**
있으면 그 형태로 구현 · 없으면 사용자에게 도입 여부를 확인한다 (범위 밖 신규일 수 있음).
- 구현 시 = 최신 N일 (또는 이번 주) 만 초기 노출 · 버튼으로 이전 주 날짜 그룹을 편다.

- [ ] **Step 1:** 8642 최신 소식에 주 단위 더보기 존재 여부 확인 · 없으면 사용자 확인 후 진행.
- [ ] **Step 2:** 초기 노출 범위 + 더보기 토글 구현.
- [ ] **Step 3:** Commit — `feat(serve): 최신 소식 주 단위 더보기` (도입 확정 시).

## Task A11: 재검증 · PR #121 갱신

- [ ] **Step 1:** 전체 테스트 — `uv run pytest -q` · 기준선 538 + 신규 통과.
- [ ] **Step 2:** VM `bulletin_mock` 재렌더 · 폭 990 · 390 × 라이트 · 다크 인덱스 · 상세 · 가십 확인.
- [ ] **Step 3:** 리뷰 항목별 (2 · 3 · 4 · 6 · 7 · 8 · 9) 실화면 해소 확인.
- [ ] **Step 4:** push · PR #121 본문에 반영 요약 추가 (머지는 사용자).

## Self-Review — 항목 커버리지

2-1 → A1 · 2-2 → A2 · 2-3 → A1 · 2-4 → A3 · 3 → A4 · 4 → A5 · 6-1 → A9 · 6-2 → A9 · 6-3 → A9 · 7 → A10 · 8 → A5 · 9 → A6 · 9-1 → A7 · 9-2 → A8.
분류 항목 (1 · 2-5 · 5) 은 트랙 B (별도 플랜) 로 제외.
