# run.py 의 INFO 로그가 운영 journal 에 전혀 남지 않음 (basicConfig 미호출)

arsenal 퍼널 로그 (PR #128) 가 VM journal 에 안 보이는 문제를 조사한 기록이다 (2026-07-25 · 읽기 전용 조사).
원인은 arsenal 쪽이 아니었다.
파이프라인 엔트리포인트 전체에서 로깅 설정이 빠져 있었다.
**미해결 — 수정은 별도 소형 PR 로 남겨 둔다** (이 문서가 착수 입력).

## 1. 증상

- PR #128 이 추가한 arsenal 수집 퍼널 로그 (`arsenal_api.py:123-124` · `창 후보 %d · Men %d · accept %d`) 가
  VM journal 에 한 번도 나타나지 않음.
- 코드 경로상 이 로그는 조건 없이 매 회차 실행된다 — "조건 미충족"으로는 설명되지 않음.

## 2. 원인

- systemd 가 실행하는 엔트리포인트 `src/bullet_in/run.py` 가 생성 시점부터
  `logging.basicConfig()` 를 한 번도 호출하지 않았다.
- root logger 의 유효 레벨이 Python 기본값 WARNING 에 머물러,
  INFO 로그는 핸들러에 닿기 전 `isEnabledFor()` 단계에서 걸러진다.
- journald 캡처 경로의 문제가 아니다 — 로그가 "안 닿는" 게 아니라 애초에 "안 찍힌다".

## 3. 근거

- 백필 · 보충 스크립트들은 각자 `__main__` 에서 `basicConfig` 를 호출한다 — `run.py` 만 예외.
- journal 실측: 같은 프로세스의 다른 INFO 라인 (`드롭 집계` · `말투 백필`) 도 전무한 반면,
  WARNING 라인 (`재번역 큐 요약` · fmkorea 430) 은 매 회차 정상 출현.
- 회차 요약의 `errors: {}` 가 매 회차 비어 있어 어댑터 예외로 로그가 끊긴 것도 아니다.

## 4. 영향 범위

- arsenal 퍼널만이 아니라 `run.py` 경유의 **모든 INFO 진단 로그가 운영에서 소실 중**이다
  (수집 드롭 집계 · 보충 흡수 현황 등). PR #128 이전부터 있던 전역 문제다.
- WARNING 이상은 정상 기록되므로 장애 감지에는 공백이 없다 — 소실되는 것은 진단 · 관측 정보다.

## 5. 남은 조치 (착수 입력)

- `run.py` 진입부에 `logging.basicConfig(level=logging.INFO, format=...)` 추가 (다른 스크립트와 관례 통일)
  — 소형 PR 1건, 코드 한두 줄.
- 반영 후 확인 두 가지: ① arsenal 퍼널 로그가 journal 에 나타나는지
  ② arsenal_official 실수집 건수 (그동안 로그가 없어 실측하지 못했던 값).
- INFO 개방 시 회차당 로그량이 늘어난다 — journal 용량은 시스템 rotate 가 흡수하므로 따로 조치할 필요는 없다고 판단.

## 6. 참고

- 발단: PR #128 (arsenal sitemap 전환 · 커버리지 알림) — `docs/runbook/2026-07-24-source-coverage-audit.md`
- 엔트리포인트: `src/bullet_in/run.py` · systemd 유닛 `infra/systemd/bullet-in.service`
