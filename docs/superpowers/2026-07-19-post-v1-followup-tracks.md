# v1 이후 후속 트랙 백로그 — 2026-07-19 라이브 점검 반영

- 날짜: 2026-07-19
- 성격: v1 완성 (#58) · 기자 후속 트랙 ② (#60 · #61) 이후 남은 작업의 SoT.
  사용자 라이브 점검 (트랙 ② 종료 직후 8항목) 의 삼분류 결과와 확정 결정을 담는다.
- 선행 SoT: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` (v1 완성 선언으로 종결).
- 우선순위: 트랙 간 순서는 착수 세션에서 결정한다.

## 0. 확정 결정 기록 (2026-07-19)

- **영입 · 방출 기사 모두 수집 = 유지 확정.**
  트로사르 베식타스행 (방출) 수집이 예 — 아스날 관련 이적 전반이 제품 범위.
- **bbc_gossip 본문 전체 수집 · 번역 = 진행 확정** (트랙 ② "썸네일만" 결정 번복, §4 참조).
- **football.london 처리 = 삭제 + 신규 차단** (트랙 ② 에서 실행 완료 — 여기 기록만).

## 1. 트랙 ③ — X · 품질 (기존 예정 + 이번 점검 편입)

기존 예정 항목:

- 백트래킹 `domains` 에 talksport.com 누락 → @JacobsBen 원문 미승격 (원인 확정).
- @SamiMokbel_BBC 미승격 원인 미특정 → 라이브 1회 진단 필요.
- X 항목 outlet 칩이 "afcstuff (aggregator)" → 기자 소속 (The Athletic 등) 으로 표기하는 설계.
- 제목 환각 검출기 (원문에 없는 '펠레그리니' 생성 실사례).
- glossary: 요케레스 (쿄케레스 2 · 요케레스 6 혼재).
- 개행 없는 400자 초과 본문 15건 문단화.

이번 점검 (2026-07-19) 편입:

- glossary: Tzolis → **촐리스** (요케레스와 같은 몫으로 처리).
- @sr_collings 인용 트윗 원문 미승격 진단 (링크 카드 부재 vs 매칭 실패)
→ @SamiMokbel_BBC 진단과 같은 방법론.
- 참고: 기자 tier 자체는 이미 정확 적용 (@David_Ornstein tier 1 · @sr_collings tier 3 실측)
— 문제는 표기 (칩) 와 승격 (원문 브릿지) 축.

## 2. 트랙 ④ (신규) — 레지스트리 · 표기 정비 묶음

소형 chore 트랙 — #45 · #51 선례 (credibility 3곳 정합: credibility.yaml · OUTLET_MAP · README 표).
런북 `docs/runbook/2026-07-15-credibility-registry-ops.md` 절차 준수.

확정 지시 (2026-07-19):

- **Simon Collings 소속 교정**: 현재 Evening Standard 로 등재 (실측 확인)
→ **The Sun** 으로 수정 (X 프로필 근거).
- **David Ornstein alias 추가**: `데이비드온스테인` (붙여쓰기) 이 alias 에 없어 facet 미매칭 (DB 실측 2건)
→ alias 추가로 흡수.
- **L'Équipe**: 현재 outlets tier 2 → **tier 3** 으로 조정.
- **The Times**: 현재 outlets tier 3 → **tier 2** 로 조정 + alias `타임즈` 추가 (현재 `타임스` 만 있음).
- **기자 신규 등재**: Luke Edwards (The Telegraph, @LukeEdwardsTele, 한글 `루크 에드워즈`) · Sacha Tavolieri (Sky Sports, 한글 `타볼리에리`)
— 한글 표기 저장분은 영어 정식명으로 정규화.
- **fmkorea OUTLET_MAP 추가**: `DM` → Daily Mail · `비사커` → BeSoccer (둘 다 현재 미등재 실측).
- **조직명 journalist 처리**: 미등재 기자 목록에 'BBC' · 'Sky Sports' · 'The Guardian' 등 조직명 노출.
  지시 = 언론사가 확실한 조직 바이라인은 **해당 언론사 기자보다 0.5 낮은 tier** 부여.
  ⚠️ tier 산정 규칙 변경이라 단순 등재보다 큼 — 착수 시 설계 확인 질문 후 진행
  (예: journalist 필드 정규화 vs facet 표기 vs tier 규칙 중 어디를 바꿀지).

## 3. 트랙 ⑤ (신규) — 영입 단계 분류 개편

brainstorming → spec 필요 (규모 있음 — enum · 프롬프트 · 규칙 · 전건 재분류).

확정 지시 (2026-07-19):

- **'이적 합의' 단계 신설** — 협상 중과 합의를 분리하는 것이 목적.
  예시 (분류 기대): 이적 확정 기사 `cb0894b7…` · 영입 합의 기사 `b8055b5b…`
→ 둘 다 '이적 합의' 태그.
- **오피셜 = arsenal.com (공홈) 이적 기사 한정** — 현재 LLM 판정만으로 오피셜 부여
→ 소스 조건 규칙 결합 필요.
- **전체 개편 + 매핑 검증** — 개편 후 현재 기사 · 태그 매핑 전건 점검.
- 전건 재분류 절차는 기존 런북 참조: `docs/runbook/2026-06-30-transfer-stage-classification-ops.md`
  (`transfer_stage` NULL 복원 후 재실행 = 멱등 경로 준비돼 있음).
- 배경 지식: 단계 분류 입력 = 제목 + 1줄 요약 (Gemini 배치 분류 `classify_stage_rows`), 미허용값 other 강등.
  gossip 이 루머/기타로 갈리는 것은 소스가 아닌 기사별 판정 (기타 = 이적 무관) — 버그 아님.

## 4. 트랙 ⑥ (신규) — bbc_gossip 본문 전체 수집 · 번역

트랙 ② 의 "썸네일만 (본문 미수집)" 결정을 **번복** (사용자 확정 2026-07-19).

- 사유: 부분 (제목 기반) 번역만 있어 상세 페이지에 아스날 무관 가십 항목만 덩그러니 노출되는 문제.
  라운드업 전문이 있어야 아스날 관련 맥락이 온전히 전달된다.
- 구현 골자: bbc_gossip config 에 `body_selector: article` 추가 (풀 수집 경로 활성)
→ `thumbnail_only` 는 body_selector 우선 규칙에 따라 자연 무력화 (트랙 ② 설계가 이 전환을 이미 지원).
- 기존 45건 본문 백필: 재fetch 경로 필요 (본문은 backfill_image 범위 밖 — 신규 또는 확장).
- 비용: tier 4 가십 라운드업 (장문 · 타 구단 다수 포함) 전문 번역이 매 회차 발생 — 유료 Tier 1 이라 절대액은 작음.
- 부수 효과: 요약 품질 상승으로 단계 분류 (트랙 ⑤) 입력도 개선.

## 5. 별도 대기 (기존)

- SP2 라우팅 1/2순위 비율 재측정 (월드컵 종료됨).
- 아스날 링크 선수 워치리스트 (fmkorea 2h 차단 창 실측치 반영 필수).
- 교차 corroboration 스코어링 (Stretch — 내용 기반 중복 · 신뢰 가중, 2026-07-19 질의로 별도 트랙 재확인).
