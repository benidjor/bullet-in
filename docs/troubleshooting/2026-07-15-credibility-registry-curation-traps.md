# credibility 레지스트리 큐레이션 함정 3종 — alias 경로 비대칭 · 동일인 중복 tier · 일반 단어 성씨 오탐 (2026-07-15)

소스 확장 후속 정리 (PR #45) 에서 기자 등재 · tier 재조정을 처리하며 드러난 레지스트리 관리 함정 모음.
공통 교훈: **credibility.yaml 의 alias 는 "이름 목록" 이 아니라 매칭 경로별 키** — alias 의 형태가 곧 그 항목이 작동하는 범위를 결정한다.

## 1. 함정 ①: @핸들 없는 기자는 X 인용 경로에서 존재하지 않는다

- **증상** — Collings · Jacob · Di Marzio · de Roché 는 레지스트리에 등재돼 있는데도 afcstuff 인용에서 기자 매칭이 0.
  SP2-a 라이브 (2026-07-03) 에서 `[@sr_collings]` 인용 (콜링스 본인 핸들) 이 기자 tier 3 대신 아웃렛 폴백 (The Sun · tier 4) 으로 처리된 실증 기록이 있다.
- **원인** — 매칭 경로가 alias 형태별로 갈린다.
  `x_mentions` 경로는 트윗 텍스트에서 `@핸들`만 정규식으로 추출해 레지스트리 키와 대조 (`credibility.py:39-40`) — `@` 없는 alias 는 이 경로에서 죽은 데이터다.
  fmkorea 경로는 제목 · 본문 부분 문자열 대조라 한글 표기 · 영문 성씨가 작동한다.
  등재가 목적별 · 시점별로 이뤄져 (PR #5 = fmkorea 바이라인 세트 · SP1 = X 인용 정합화) 핸들 공백이 조용히 누적됐다.
- **왜 못 잡았나** — 매칭 실패는 에러가 아니라 폴백 (아웃렛 → fallback 4) 으로 흡수돼 로그 · 알림에 안 걸린다.
  tier 가 "좀 낮게" 나올 뿐 파이프라인은 정상이라, 레지스트리를 사람이 훑기 전까지 안 보인다.
- **해결** — PR #45 핸들 백필 4건: @sr_collings · @DiMarzio · @ArtdeRoche · @garyjacob.
- **예방** — 신규 등재는 alias 3종 세트 (핸들 · 한글 표기 · 영문 이름) 를 기본값으로.
  절차는 런북 `2026-07-15-credibility-registry-ops.md` §2.

## 2. 함정 ②: 동일인 중복 항목 — 인용 핸들에 따라 tier 가 갈린다

- **증상** — gunnerblog (tier 2) 와 James McNicholas (tier 1.5) 가 동일인 (gunnerblog = McNicholas 의 개인 채널명).
  afcstuff 가 `[@_JamesMcNicholas]` 로 인용하면 1.5, `[@gunnerblog]` 로 인용하면 2 — 같은 사람의 발언이 인용 표기에 따라 다른 공신력을 받는다.
- **원인** — 항목 추가가 관찰 시점별로 이뤄져 동일인 검증 단계가 없었고, 채널명과 본명이 달라 중복이 눈에 띄지 않았다.
- **해결** — McNicholas 항목으로 통합: @gunnerblog 를 alias 로 흡수 · tier 1.5 통일 · 단독 항목 삭제 (PR #45).
- **예방** — 신규 핸들 · 채널명 등재 전 "기존 항목의 인물인가" 를 확인.
  개인 채널명 계정은 독립 항목이 아니라 본명 항목의 alias 로 넣는다.

## 3. 함정 ③: 일반 단어 성씨는 fmkorea 부분 문자열 오탐원

- **증상 (등재 설계 중 예방)** — Sam Dean 등재 시 성씨 "Dean" 을 alias 로 넣으면 fmkorea 본문에서 무관한 매칭이 발생할 수 있다.
  "dean" 은 심판 Mike Dean · DeAndre 류 선수명 등 축구 텍스트 빈출 문자열이고, 매칭되면 그 글 전체가 tier 3 을 받는다.
- **원인** — fmkorea 경로는 소문자 부분 문자열 대조 (`credibility.py:52-57`): alias 가 짧고 흔할수록 오탐 확률이 커진다.
  기존 Matt Law 항목이 성씨 없이 핸들만 등재된 것도 같은 계열이다 ("law" 는 일반 영단어).
- **해결** — Sam Dean 은 성씨 단독을 배제하고 풀네임 "Sam Dean" + 한글 "샘 딘" + 핸들로 등재.
- **일반화** — 성씨가 일반 영단어거나 축구계 빈출 인명이면 풀네임 · 한글 표기 · 핸들만 쓴다.
  fmkorea 오탐은 tier 상향 방향이라 (무관 글이 기자 tier 획득) 하향 오류보다 서빙 정렬 왜곡이 크다.

## 4. 관련

- 런북: `2026-07-15-credibility-registry-ops.md` (등재 체크리스트 · tier 재조정 절차).
- 계열 문서: `2026-07-03-sp2-backtrack-tier-routing-traps.md` (같은 라우팅 계층의 승격 항목 tier 함정), `2026-07-13-fmkorea-search-endpoint-traps.md` (부분 문자열 매칭 의미론 — 검색 파라미터 판).
