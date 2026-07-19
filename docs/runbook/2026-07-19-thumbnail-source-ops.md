# thumbnail_only 소스 운영 런북 — 적용 · 드리프트 진단 · 백필 · 풀 수집 전환

- 날짜: 2026-07-19
- 대상: `thumbnail_only` 경량 상세 방문 소스 (현재 bbc_gossip 1곳)
- 관련: spec `docs/superpowers/specs/2026-07-19-source-curation-design.md` §3.3 · §3.4

## 1. 동작 요약

- config 에 `body_selector` 없이 `thumbnail_only: true` 만 있으면 상세 페이지를 방문해 **og:image 만** `image_url` 로 싣는다.
  본문 · 인라인 이미지 · 저자는 추출하지 않는다
→ Gemini 번역 비용 무변경 · `journalist_label` 통칭 유지.
- `body_selector` 가 있으면 풀 수집 경로가 우선이고 `thumbnail_only` 는 무시된다 (어댑터 분기 순서).
- 상세 fetch 실패 시 제목만 적재 (image_url 키 없음)
— 이미 적재된 행은 duplicate 판정으로 갱신되지 않으므로 놓친 이미지는 백필 (§3) 몫.

## 2. 신규 소스 적용 절차

1. `config/sources.yaml` 해당 소스 config 에 `thumbnail_only: true` 추가.
2. 머지 전 어댑터 단독 `fetch()` 라이브 검증 — 수집 건수와 image_url 채움 비율 확인 (모킹 테스트는 셀렉터 · og:image 드리프트를 못 잡음).
   실측 기준 (bbc_gossip, 2026-07-19): 25건 중 25건 채움.

## 3. 기존 행 백필

```bash
set -a; source .env; set +a
uv run python -m bullet_in.backfill_image --limit 5 --dry-run   # 검증
uv run python -m bullet_in.backfill_image                        # 본실행
```

- 대상 = config 의 `thumbnail_only` 소스 전체의 `image_url IS NULL` 행 — 멱등이라 재실행 안전.
- 대상 도출이 config 기반이라 fmkorea 등 2h 규칙 소스가 섞일 수 없는 구조.
- 실측 (2026-07-19): bbc_gossip 45건 중 성공 45 · 실패 0.
- 함정: `extract_og_image` 에 자체 예외 가드가 없어 병리적 HTML 이 예외를 던지면 그 회차가 중단될 수 있다 (html.parser 가 관대해 저확률).
→ 중단돼도 멱등이라 재실행으로 회복.

## 4. 드리프트 진단

증상별로 원인이 다르다.

- **신규 행의 image_url NULL 증가 · 카드 플레이스홀더 복귀**
→ 상세 페이지 og:image 태그 변경 의심. 어댑터 단독 fetch 로 채움 비율 재확인.
- **수집 자체가 0건**
→ 목록 셀렉터 드리프트 (별개 증상 클래스). `docs/troubleshooting/2026-06-12-live-source-selector-drift.md` 참조.

## 5. 풀 수집 전환 (트랙 ⑥ 예정 경로)

- 전환은 config 에 `body_selector` 추가만으로 완료 — 우선 규칙에 따라 `thumbnail_only` 는 남아 있어도 무시된다 (혼동 방지를 위해 제거 권장).
- 전환 후 신규 수집분부터 본문 · 인라인 이미지 · 저자가 채워지고 번역 비용이 발생한다.
- 기존 행의 **본문** 백필은 backfill_image 범위 밖 (image_url 만 다룸)
→ 별도 백필 경로가 필요하다 (트랙 ⑥ 설계 항목, 백로그 SoT §4).
