# 문서가 지시한 관측 지표에 싱크가 없음 — author_drop_count 사례

- 날짜: 2026-07-19
- 관련: 트랙 ② (PR #60) · `docs/troubleshooting/2026-07-13-alert-exception-swallow-gap.md` 등과 같은 "계층 간 대조" 실패 클래스

## 1. 증상

spec §6 과 정리 런북이 "`author_drop_count` 로 재유입을 관측한다" 고 지시하는데, 코드에는 그 지표의 싱크 (로그 · 저장) 가 없었다.

- `to_articles` 는 stats dict 에 `author_drop_count` 를 반환하지만, run.py 는 이 키를 로그로도 pipeline_runs 로도 내보내지 않았다.
- 운영자가 런북 절차를 그대로 실행하면 관측 단계에서 막힌다 — 지표는 존재하나 볼 방법이 없다.

## 2. 왜 태스크 리뷰를 통과했나

- 태스크 단위 리뷰 3회는 전건 통과 — 각 태스크 범위 안에서는 결함이 없었다 (stats 반환은 spec 대로, 런북 문장도 자체로는 자연스러움).
- 결함은 **문서 (관측 지시) ↔ 코드 (싱크 부재) 의 계층 간 계약**에 있어, whole-branch 리뷰의 계층 대조에서만 드러났다.
- 같은 실패 클래스 선례: PR #38 의 clock-mixing · sparse-source-counts (단위 테스트 · 태스크 리뷰 통과 후 계층 대조에서만 발견).

## 3. 갭의 뿌리

- 선례 계승: `women_count` 도 동일하게 stats 반환만 있고 싱크가 없었다.
  "women_count 선례를 따른다" 는 설계가 **선례의 갭까지 계승**한 것 — 선례 준수와 선례 결함 계승은 다른 문제다.

## 4. 해결

- run.py 의 `to_articles` 직후 drop 집계 INFO 로그 1줄 (중복 · 여자팀 · 기자 allowlist)
→ `author_drop_count` 와 `women_count` 가 함께 싱크 확보 (커밋 `c7f6c5e`, squash `59d098f`).

## 5. 잔여 함정 — INFO 는 기본 레벨에서 안 보인다

- run.py 는 기본 로깅 레벨이 WARNING 이라 INFO 로그가 표준 출력에 안 잡힌다 (tone 백필 런북 §의 기지 함정과 동일).
- 따라서 운영 검증은 **DB 불변량 병행**이 실전 경로:
  football.london 잔존 전건 `journalist='Tom Canton'` 확인 (사이클 후 재유입 0 = 필터 실동작).
  실제 트랙 ② 라이브 검증도 이 경로로 수행했다 (정리 런북 §7).

## 6. 예방

- 문서에 "X 로 관측 · 확인한다" 를 쓸 때마다 **X 의 싱크 (출력 경로 + 로그 레벨) 를 코드에서 확인**한다.
- whole-branch 리뷰 디스패치에 계층 간 대조 (문서의 지시 ↔ 코드의 출력) 를 명시 항목으로 넣는다 — 이번 발견 경로.
