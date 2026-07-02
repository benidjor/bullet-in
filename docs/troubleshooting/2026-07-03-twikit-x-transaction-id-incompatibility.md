# twikit ↔ 현재 X 비호환 — client-transaction-id 생성 실패 (2026-07-03)

`x_twikit` 어댑터가 현재 X와 호환되지 않아 afcstuff 수집이 불가능했던 문제와, Playwright 우회로의 진단 · 해결 기록.

## 증상

- twikit (`get_user_by_screen_name` 등 첫 GraphQL 호출)이 `Exception: Couldn't get KEY_BYTE indices`로 죽는다.
- 쿠키 (`auth_token` · `ct0`)는 유효하고 네트워크도 정상인데 실패한다.

## 진단 (비직관적 — 여기서 헤맴)

twikit은 요청마다 `x-client-transaction-id` 헤더를 붙여야 하고, 이 값을 x.com 홈 HTML에서 `ondemand.s` 청크 참조를 찾아 그 JS를 받아 KEY_BYTE indices를 계산해 만든다.
확인 결과:
- 쿠키 로드 정상 · x.com 홈 283KB 정상 응답 · `twitter-site-verification` meta 존재.
- 그러나 twikit의 `ON_DEMAND_FILE_REGEX` (`"ondemand.s":"<hash>"`)가 홈 HTML에서 매칭 실패
  → indices 빈 값 → 위 예외.
- 실제 홈 HTML엔 `NNNN:"ondemand.countries-*"` 식 webpack manifest만 있고 `ondemand.s` 청크 참조가 없다. X가 리소스 구조를 바꿨다.

즉 "쿠키 · 네트워크가 멀쩡한데 죽는다"라 네트워크 · 인증을 의심하기 쉽지만, 실패 지점은 **요청 서명값 계산**이다.

## 근본 원인

- twikit 2.3.3이 PyPI 최신이나 2025-02 이후 릴리스가 없다
  → 그 뒤 X 프런트엔드 변경을 못 따라간다.
- 단순 regex 패치로 안 된다 — 찾을 리소스 (`ondemand.s`) 자체가 사라져 transaction-id 알고리즘 재역설계가 필요하고, X가 계속 바꾸는 움직이는 표적이다.

## 해결

- **Playwright (실브라우저)로 우회.** 실제 브라우저가 자기 요청을 직접 서명하므로 transaction-id 문제가 원천적으로 사라진다.
- 쿠키 (`auth_token` · `ct0`)를 브라우저 컨텍스트에 주입
  → `x.com/<handle>` 로드 → DOM 스크레이프.
- 구현: `src/bullet_in/adapters/x_playwright.py` (SP1, PR #24). `x_twikit` 어댑터 · 테스트 제거.

## 재발 방지 · 참고

- twikit (또는 유사 unofficial 클라이언트)로 재시도하지 말 것 — 대개 같은 transaction-id 문제를 각자 쫓는 중이다.
- 공식 X API는 무료 티어로 타임라인 읽기가 사실상 불가하다.
- 운영 절차 (쿠키 획득 · 갱신 · 라이브 검증)는 런북 `docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md`.
