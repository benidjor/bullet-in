# thumbnail_only 소스 운영 런북 — 적용 · 드리프트 진단 · 백필 · 풀 수집 전환

- 날짜: 2026-07-19
- 대상: `thumbnail_only` 경량 상세 방문 소스 (bbc_gossip 은 트랙 ⑥ 에서 풀 수집 전환 완료 — §5, 현재 해당 소스 없음)
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

## 5. 풀 수집 전환 (트랙 ⑥ 에서 실행 — bbc_gossip 선례)

1. config 전환 — `body_selector` 추가 · `thumbnail_only` 제거 (우선 규칙상 남아 있어도 무시되나 혼동 방지).
2. 머지 전 어댑터 단독 `fetch()` 라이브 검증 — 실측 (2026-07-19): 25건 전부 body (2.2k~7.4k자) · og:image · 인라인 이미지 채움.
3. 기존 행 본문 백필 — 재fetch 로 body_source · images_json 을 채우고 `title_ko` 를 NULL 로 되돌려 재번역을 트리거한다 (transfer_stage 전건 재분류와 같은 멱등 패턴 · stage 는 보존).

```bash
uv run python -m bullet_in.backfill_body --source bbc_gossip --limit 3 --dry-run   # 검증
uv run python -m bullet_in.backfill_body --source bbc_gossip                        # 본실행
```

- 대상 소스는 `--source` 명시 필수 — config 파생으로 뽑으면 body 빈 행을 가진 football.london (재수집 금지) · fmkorea (2h 규칙) 가 섞일 수 있다.
- 백필 후 enrich 전용 패스 (`2026-07-19-enrich-only-pass.md` §3~§4) 로 수렴 · 사이트 재생성.
- 실측 (2026-07-19): 백필 45/45 성공 · enrich 2패스 수렴 (파싱 실패 2건 재시도 성공) · 잔존 0.
- **라운드업 발췌 함정**: "아스날 뉴스 번역" 프레이밍 탓에 모델이 타 구단 항목을 발췌 삭제할 수 있다
→ TRANSLATE_PROMPT 의 라운드업 발췌 금지 규칙으로 해소 (실측 구단 보존 8행 중 3행 누락 → 1행).
  잔존 1행 (전 구단 일정 목록 기사) 은 동일 입력 프로브 2회 재현 = 구조적 한계로 수용 (아스날 항목은 온전).
