# 같은 단계 값이 기사 · 선수 두 경로로 저장돼 갈렸다 (2026-08-03)

## 증상

공홈 (`arsenal_official`) 이 영입을 발표한 기사가 홈 화면에서는 오피셜 배지를 다는데, 같은 기사의 `article_players.stage` 에는 `agreed` 가 저장돼 있었다.

라이브 오작동 신고로 발견한 것이 아니다.
선수 페이지를 설계하면서 선수별 단계를 읽는 코드를 따라가다 발견했다.
선수별 단계를 화면에 쓰는 코드가 아직 없어서, 값이 갈려 있어도 겉으로 드러날 곳이 없었다.

선수 페이지의 타임라인은 단계가 **바뀐** 기사만 노드로 만든다 (스펙 §5).
이 상태로 그리면 발표 기사는 직전 기사와 값이 같아 노드조차 생기지 않는다.
배지 하나가 어긋나는 문제가 아니라 이적 완료 시점이 타임라인에서 통째로 빠지는 문제였다.

## 원인

단계라는 같은 개념이 두 경로로 따로 저장된다.

- **기사 단위** — `run.py` 의 분류 패스가 `transfer_stage.rule_stage(source_id)` 를 거쳐 `articles.transfer_stage` 에 넣는다.
공홈이면 LLM 을 부르지 않고 `official` 을 준다.
- **선수 단위** — enrich 의 추출 결과가 `roster.normalize_pairs()` 를 거쳐 `article_players.stage` 에 들어간다.
이 경로에는 공홈 규칙이 없었다.

두 번째 경로에는 오히려 값을 낮추는 코드가 있었다.
모델이 `official` 을 반환하면 무조건 `agreed` 로 강등하는 한 줄이다.
2026-07-19 오피셜 규칙 분리 때 넣은 방어다 — 공홈이 아닌 소스는 구조적으로 official 이 될 수 없으므로, 모델이 그렇게 답하면 낮춘다.
그런데 이 강등은 `source_id` 를 보지 않아서, 정작 official 이 맞는 공홈 기사까지 함께 낮췄다.

## 뒤이어 드러난 함정 — 스펙에 적은 조건이 실제로는 발동하지 않았다

스펙 §8.1 에는 조치가 "공홈이면 `official` 을 유지하고, 아니면 지금처럼 강등한다" 로 적혀 있었다.
구현에 들어가서야 이 규칙이 아무 일도 하지 않는다는 것이 드러났다.

추출 프롬프트가 stage 선택지를 `rumour · interest · negotiating · personal_terms · medical · agreed · other` 로 제시한다.
`official` 이 아예 선택지에 없다.
모델은 공홈 기사에서도 `official` 을 답하지 않으므로, "official 이면 유지" 는 발동할 일이 없는 조건이었다.

실제로 필요한 것은 유지가 아니라 **조건부 덮어쓰기**였다 — 공홈이면 모델이 뭐라고 답했든 `official` 로 덮는다.
기사 단위 경로와 소급 `UPDATE` 가 이미 조건 없이 덮고 있으므로, 여기서도 같은 규칙을 써야 소급으로 고친 행과 앞으로 쌓일 행이 갈리지 않는다.

## 왜 조용했나

두 경로 각각의 테스트는 통과하고 있었다.
두 값을 맞춰 보는 테스트가 없었을 뿐이다.

런북에는 기사 단위 불변량까지 있었다 (비공홈 official 은 0 이어야 한다).
그 SQL 이 보는 테이블은 `articles` 하나여서, 같은 규칙이 `article_players` 에서 깨진 것은 잡히지 않았다.

## 해결

- **#208** — `roster.normalize_pairs()` 가 `source_id` 를 받고, 공홈이면 `official` 로 덮어쓴다.
공홈 판정은 `rule_stage()` 를 재사용해 `arsenal_official` 문자열을 새로 박지 않았다.
정기 회차와 백필 두 호출부에 `source_id` 를 배선하고, 백필 대상 SQL 에 컬럼을 추가했다.
- **소급** — LLM 호출 없이 `UPDATE` 한 번이다 (스펙 §8.1).
계획서 `docs/superpowers/plans/2026-08-03-serve-player-pages-impl.md` Step 2 에 대상 6행으로 잡혀 있고, 이 글을 쓰는 시점에는 아직 실행 전이다.
- **런북** — 선수 단위 불변량 SQL 을 `docs/runbook/2026-06-30-transfer-stage-classification-ops.md` "오피셜 규칙 분리" 절에 추가했다.

## 예방

- **같은 개념을 두 테이블에 저장하면 규칙 출처를 한 곳에 둔다.** 양쪽이 `rule_stage()` 처럼 한 함수를 부르게 하고, 각자 문자열을 박지 않는다.
- **값을 낮추는 방어는 낮출 대상을 조건으로 적는다.** 조건 없는 강등은 방어하려던 비정상 입력뿐 아니라 정상 경로까지 함께 삼킨다.
이 사고는 방어 한 줄이 `source_id` 를 안 본 것이 전부였다.
- **모델이 낼 수 없는 값을 조건에 쓰지 않는다.** 프롬프트가 제시하는 선택지를 먼저 확인한다.
스펙에 규칙을 적을 때도 그 값이 실제로 나올 수 있는지 한 번 짚어야 한다.
- **불변량은 저장 경로마다 하나씩 둔다.** 규칙이 두 테이블에 걸쳐 있으면 점검 SQL 도 두 개여야 한다.

## 참조

- 설계: `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` §8.1
- 계획: `docs/superpowers/plans/2026-08-03-serve-player-pages-impl.md` Step 2
- 런북: `docs/runbook/2026-06-30-transfer-stage-classification-ops.md` "오피셜 규칙 분리"
- 오피셜 규칙 분리 배경: `docs/superpowers/specs/2026-07-19-transfer-stage-overhaul-design.md` §2 · §4
- 계획서 단계의 결함이 구현까지 살아남은 선례: `docs/troubleshooting/2026-07-14-plan-artifact-defect-propagation.md`
