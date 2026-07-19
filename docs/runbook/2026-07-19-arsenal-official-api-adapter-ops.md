# arsenal_official GraphQL API 어댑터 운영

- 날짜: 2026-07-19 (복구 PR #68 라이브 실행 기준)
- 대상: `src/bullet_in/adapters/arsenal_api.py` (source_id `arsenal_official`)
- 설계 근거: `docs/superpowers/specs/2026-07-19-arsenal-official-api-recovery-design.md`
- 발굴 함정: `docs/troubleshooting/2026-07-19-unofficial-graphql-api-probe-traps.md`

## 1. 평시 구성

- 비공식 GraphQL API `https://afc-prd.graph.arsenal.com/graphql` 를 httpx 로 직접 호출한다
  (인증 불요 · `bullet-in/0.1` UA — 2026-07-19 실측).
- 필터 · 쿼리 전문의 SoT 는 어댑터 코드다 — 이 런북은 절차만 다루고 규칙을 미러하지 않는다
  (스니펫 드리프트 예방: `docs/troubleshooting/2026-07-19-runbook-snippet-logic-drift.md`).
- config 는 `pages` 하나만 노출한다 (평시 2 — 페이지당 50건 · 최신순, 최근 100건 커버).
- 수집 기사는 전건 규칙 경로로 `transfer_stage = official` 태깅된다.
  재계약 기사가 official 배지를 받는 것은 **의도된 동작**이다
  — 근거는 분류 런북 알려진 한계 (`docs/runbook/2026-06-30-transfer-stage-classification-ops.md`).

## 2. 라이브 단독 fetch 검증 (어댑터 · config 변경 시 머지 전 필수)

단위 테스트는 모킹이라 API 계약 변화를 못 잡는다 — 셀렉터 드리프트 함정과 같은 원칙.

```bash
uv run python - <<'EOF'
import asyncio
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter
items = asyncio.run(ArsenalApiAdapter("arsenal_official", pages=8).fetch())
print(f"수집 {len(items)}건")
for it in items:
    p = it.raw_payload
    print(f"- {p['published'][:10]} | {p['title'][:60]} | body {len(p.get('body') or '')}자")
EOF
```

판독:

- 이적창 기간인데 0건이면 §3 실패 모드를 순서대로 점검한다 (비이적창 0건은 정상일 수 있음).
- 수집건의 body 가 전부 0자면 본문 쿼리 (`GetArticle`) 축만 깨진 것 — 목록 축과 분리 진단.

## 3. 실패 모드 3종 (드러나는 방식이 서로 다름)

### 3.1 쿼리 필드 드리프트 — 에러로 드러남

- API 가 쿼리의 필드를 없애면 validation 에러 → `fetch()` 예외 → 회차 에러 카운트 · 알림 경로.
- 대응: 사이트에서 신규 번들을 받아 쿼리 전문을 재추출해 어댑터 상수를 갱신한다
  (절차는 발굴 함정 문서 §1).

### 3.2 taxonomy 명칭 · 부여 정책 변경 — 조용한 0건

- 채택 조건이 참조하는 taxonomy 명칭 (예: "Transfer news") 이 바뀌면 필터가 전건 걸러
  **에러 없이 0건**이 된다 — 평시 0건 소스 감시 사각과 같은 형태
  (`docs/troubleshooting/2026-07-19-silent-zero-collection-blindspot.md`).
- 대응: 이적창 기간에 §2 단독 프로브를 정기 점검에 포함하고,
  0건이면 무필터 목록 (어댑터 `_accept` 우회) 으로 최근 기사들의 `taxonomies` 실값을 눈으로 대조한다.
- 목록 응답 자체가 null 이면 어댑터가 "목록 응답 비어 있음" WARNING 을 남긴다
  — 인자 계약 드리프트 의심 (조용한 null 함정, 발굴 함정 문서 §2).

### 3.3 인증 도입 · 엔드포인트 폐쇄 — 4xx 로 드러남

- 401 · 403 · 429 류가 지속되면 비공식 API 접근이 막힌 것.
- 대응: 헤더 요구 (Origin · Referer) 재실측부터 시도하고, 막혔으면 Playwright 갈래 재검토
  (spec 의 기각 대안 — goal 복구 선례 규모로 회귀).

## 4. 소급 (백필) 절차 — 2026-07-19 여름 이적창 실행 기록

과거 기사 소급은 전용 모듈 없이 어댑터 단독 실행으로 한다.

- **run.py 종단 실행을 쓰지 않는 이유**
→ 전 소스를 fetch 해 fmkorea 2h 규칙 등 타 소스 접촉 제약과 충돌한다.
- 절차: 어댑터를 `pages` 상향으로 단독 fetch → 컷오프 날짜로 필터 → 표준 적재 경로
  (content_hash → RawStore → to_articles → upsert → rule 태깅) 를 스크립트로 1회 통과.
  실행 스크립트 원형은 PR #68 검증 절 참조.
- 멱등: mart 의 URL UNIQUE · content_hash dedup 으로 재실행 안전.
  번역 (title_ko NULL) 은 하루 4회 정규 스케줄이 누적 처리 — 백필에서 enrich 를 돌리지 않는다.
- 실행 기록 (2026-07-19): `pages=30` (약 1,500건 목록 = 5/23 도달) · 컷오프 6/1
→ 5건 적재 · 전건 official · tier 0
  (트로사르 방출 · 합의 · Meslier · Kiwior · Hincapie — 방출 2건은 구 'sign' 필터 누락분).
- 페이지 깊이 감: 50건 × 1페이지 ≈ 2~3일 (시즌 중 체감치) — 컷오프 날짜 도달 여부는
  마지막 페이지 기사의 `publicationDate` 로 확인한다.

## 5. 롤백

- 어댑터 · config 는 `git revert` 로 원복 (구 html 셀렉터 경로는 사이트 개편으로 이미 무효
  — revert 는 수집 중단과 같다).
- 백필 적재분은 실제 공홈 기사라 정합 — 제거 불요.
  제거가 필요하면 `DELETE FROM articles WHERE source_id='arsenal_official'` 후
  raw (mongo) 는 보존해도 무해하다 (mart 재적재 시 dedup).
