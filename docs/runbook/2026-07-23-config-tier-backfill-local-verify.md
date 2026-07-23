# config · 프롬프트 변경의 로컬 재처리 · 검증 런북 (2026-07-23)

재수집이 필요 없는 변경 (credibility 값 · enrich 프롬프트 · 게이트) 을 머지 전 로컬 `bulletin_mock` 에 적용해 개편 UI 로 눈으로 확인하는 절차다.
트랙 B PR-A (B1 tier · B2 단계 · B5 제목) 검증에 쓴 흐름이며, 이후 config 기반 백필 · 트랙 B 잔여 PR 에 재사용한다.

## 전제

- 로컬 `bulletin_mock` — VM 복제본 (재렌더 런북 `2026-07-22-mockup-rerender-from-vm.md` 로 채움).
- 로컬 mongo `bulletin.raw_items` — tier 재계산 입력 (raw_payload).
- `GEMINI_API_KEY` — 재분류 · 재번역 (B2 · B5) 에 필요. tier 재계산 (B1) 은 순수 함수라 불필요.
- `set -a; source .env; set +a` 후 실행 (이 프로젝트는 dotenv 미사용).

## 1. 스냅샷 (필수 · 되돌릴 수 없음)

이 저장소 mariadb 컨테이너에는 `mysqldump` · `mariadb-dump` 가 없다.
articles 테이블을 Python 으로 읽어 pickle 로 뜬다.

```python
rows = [dict(r) for r in c.execute(text("SELECT * FROM articles")).mappings()]
pickle.dump(rows, open(snapshot_path, "wb"))
```

## 2. 재처리 (변경 성격별)

- **tier 재계산 (config 값 변경)** — old (git HEAD) vs new 레지스트리 델타만 update.
전건 재 resolve 는 과거 드리프트까지 건드리므로 금지 (`docs/troubleshooting/2026-07-23-tier-recompute-stale-drift.md`).
- **단계 재분류 (프롬프트 변경)** — 대상 행의 `transfer_stage` 를 NULL 로 되돌린 뒤 `classify_stage_rows` (Gemini) 재실행.
전건이 아니라 관련 키워드로 좁힌 후보만 (LLM 변동성 · 비용).
키워드 후보가 관련성 (다른 구단) 케이스를 끌어올 수 있으니, 재분류 결과를 확인하고 범위 밖 행은 원 stage 로 롤백한다.
- **제목 재번역 (게이트 폴백 변경)** — 영어 폴백 행 (title_ko 에 한글 0) 의 `title_ko` 를 NULL 로 백필.
`rows_missing_translation` 이 `title_ko IS NULL` 을 뽑으므로 다음 enrich 패스에 재선별된다.

## 3. 렌더 · 대조

`run.py` 의 `SERVING_SELECT_SQL` 로 SELECT 한 뒤 `write_site` 를 **스크래치패드로** 렌더한다 (실 `site/` 오염 방지).

```python
rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
write_site(rows, load_sources("config/sources.yaml"), out_dir,
           directory=journalist_directory("config/credibility.yaml"),
           registry=load_registry("config/credibility.yaml"),
           outlet_dir=outlet_directory("config/credibility.yaml"))
```

생성된 article 페이지를 grep 으로 확인한다.
함정 — 상세 메타의 공신력은 접두어를 뗀 `<dt>공신력</dt><dd>중</dd>` 형태다.
그냥 "공신력" 으로 grep 하면 사이드바 필터의 전체 라벨 (`공신력 최상` 등) 이 먼저 잡히니, `<dt>공신력</dt><dd>…</dd>` 패턴으로 그 행의 자기 tier 만 뽑는다.

## 4. 롤백

스냅샷 pickle 을 읽어 바뀐 컬럼을 원값으로 UPDATE 한다 (또는 mock 을 재렌더 런북으로 다시 채운다).

## 게이트 결정적 오탐 진단 (B5 류)

제목이 재번역 큐에서 안 풀릴 때, **같은 행을 여러 번 재번역해 게이트가 매번 같은 이유로 걸리는지** 본다.
매번 걸리면 결정적 오탐 (LLM 변동성으로 안 풀림) 이고, 가끔 통과하면 변동성 문제다.
PR-A 실측 — `7341690b` 의 좋은 번역이 원제의 부차 인명 (Arteta) 을 정당하게 생략했는데 `인명 누락` 게이트가 매번 거부했다 (결정적 오탐 · 별도 후속 트랙).

## 참고

- VM (운영) 재처리는 별개 — 재분류 운영 `docs/runbook/2026-06-30-transfer-stage-classification-ops.md` · enrich 전용 패스 `docs/runbook/2026-07-19-enrich-only-pass.md`.
- mock 채우기 · 재렌더: `docs/runbook/2026-07-22-mockup-rerender-from-vm.md`.
- tier 재계산 함정: `docs/troubleshooting/2026-07-23-tier-recompute-stale-drift.md`.
