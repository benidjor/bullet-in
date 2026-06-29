# 트러블슈팅 로그

인시던트가 발생할 때마다 파일 1개씩 추가한다: `YYYY-MM-DD-<슬러그>.md`.

각 문서 구조:
- **증상 (Symptom)** — 무엇이 어떻게 잘못 보였는지
- **원인 (Cause)** — 근본 원인
- **해결 (Fix)** — 실제로 한 조치
- **예방 (Prevention)** — 재발 방지책 / 추가한 테스트 · 가드

발생 가능성이 높아 미리 대비하는 시드 항목:
- X (twikit) 안티봇 · 로그인 세션 만료
- Playwright 셀렉터 드리프트 (대상 사이트 DOM 변경)
- dedup 충돌 (같은 기사 다른 URL, canonicalization 누락)
- dbt-duckdb의 MariaDB attach (mysql_scanner) 연결 이슈
- Airflow 2→3 provider 호환성
