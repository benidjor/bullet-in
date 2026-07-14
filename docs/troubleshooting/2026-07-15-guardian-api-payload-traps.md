# guardian Open Platform API 함정 3종 — q 전문검색 혼입 · trailText 인라인 HTML · 미수집 스킵 SLO-5 사각 (2026-07-15)

소스 확장 트랙 (PR #41) 에서 guardian 을 API 경로로 등재하며 라이브 실측 · 최종 리뷰로 발견한 함정 모음.
공통 교훈: **API 소스도 HTML 스크랩과 똑같이 "모킹이 못 잡는" 응답 특성이 있다** — 어댑터 단독 `fetch()` 라이브 검증 게이트는 API 소스에도 필수.

## 1. 함정 ①: q= 는 전문 검색 — 타 구단 기사가 섞인다

- **증상** — `q=Arsenal` 응답에 맨유 매각 기사 · 월드컵 라이브블로그 혼입 (2026-07-15 실측).
- **원인** — `q` 파라미터는 관련도 기반 **전문 (full-text) 검색**: 본문에 Arsenal 이 한 번만 스쳐도 잡힌다.
  기존 잔존 코드 (`guardian_api.py` 초기 버전) 가 이 방식이었다.
- **해결** — `tag=football/arsenal` 스코프: HTML 페이지 `/football/arsenal` 과 동일한 태그 축이라 아스날 태깅 기사만 반환.
- **일반화** — 팀 · 주제 스코프가 필요한 소스는 검색 파라미터가 아니라 **분류 체계 (tag · section)** 를 먼저 찾을 것.

## 2. 함정 ②: trailText 에 인라인 HTML — autoescape 가 리터럴로 노출

- **증상** — `trailText` 값에 `<strong>…</strong>` 마크업 포함 (실측: "Football Daily" 류 기사).
  이 값이 `body_excerpt` 로 흘러 카드에 렌더되면 Jinja autoescape 가 태그를 이스케이프해 **`<strong>` 이 글자 그대로 보인다**.
- **왜 못 잡았나** — 단위 테스트 픽스처는 깨끗한 텍스트라 통과, 라이브 검증 1차도 길이 · 썸네일만 봤다.
  최종 whole-branch 리뷰의 "필드 내용" 지적 → 실측 재확인으로 발견.
- **해결** — 어댑터에서 제거: `BeautifulSoup(trailText, "html.parser").get_text(" ", strip=True)` (PR #41 `9f9b3ba`, 회귀 테스트 포함).
- **계열** — `2026-06-29-jinja-autoescape-css-context-injection.md` 와 같은 뿌리: autoescape 는 만능이 아니고, **컨텍스트 (CSS url · 리터럴 노출) 별로 입력 위생이 따로 필요**.

## 3. 함정 ③: 키 부재로 스킵된 소스는 SLO-5 알림 사각

- **증상** — GUARDIAN_API_KEY 미설정이면 factory 가 소스를 skip + WARNING 하는데, 이 상태가 **영구 지속돼도 알림이 없다**.
- **원인** — SLO-5 워터마크는 `MAX(fetched_at) FROM articles GROUP BY source_id` 기반: **한 번도 적재된 적 없는 소스는 행 자체가 없어** `evaluate_freshness` 가 stale 판정을 못 한다.
  최소 1회 적재 후의 키 소실은 48h 임계로 정상 포착 — 사각은 "처음부터 없던 소스" 한정.
- **미묘한 변형** — 워터마크 기준은 *적재*이지 *fetch 시도*가 아니다: fetch 는 성공했지만 키워드 필터로 전건 탈락이 이어지는 소스도 워터마크가 안 생긴다.
- **해결 (운영 보완)** — 배포 체크로 커버: Airflow 환경에 키 존재 확인 + 첫 운영 회차 `source_counts` 에 guardian 등장 확인.
  절차는 런북 `2026-07-15-source-expansion-ops.md` §3.
- **일반화** — "신규 소스 추가" 는 SLO-5 가 지켜주지 못하는 유일한 구간 (첫 적재 전) 을 지난다 — 첫 회차 확인은 알림이 아니라 **사람의 배포 체크** 몫.

## 4. 관련

- spec: `docs/superpowers/specs/2026-07-15-source-expansion-design.md` §5 · §6 (함정 ③ 은 최종 리뷰 지적으로 §6 정정).
- 계열 문서: `2026-06-12-live-source-selector-drift.md` (모킹이 못 잡는 소스 특성 — HTML 판), `2026-07-13-fmkorea-search-endpoint-traps.md` (검색 파라미터 의미론 함정 — 커뮤니티 판).
