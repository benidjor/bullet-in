# fmkorea [공홈] 말머리 오귀속 — 상대 표기의 절대 매핑 · 구/신 URL dedup 사각

- 날짜: 2026-07-19 (백로그 SoT §6 항목 처리 중, PR #70)
- 증상 소스: fmkorea (발견 소스) × arsenal_official (직수집)
- 관련: 복구 선행 `docs/troubleshooting/2026-07-19-unofficial-graphql-api-probe-traps.md` (PR #68)

## 1. 증상

- 맨유 · 맨시티 공홈 발표 글이 **outlet=Arsenal.com · tier 0 · team=arsenal · stage=agreed** 로
  적재돼 아스날 이적 합의 필터에 노출됐다 (실측 2건: e68eb3f2 · d1f34b86).
- 조사 중 부수 발견: fmkorea 경유 아스날 공홈 글 2건이 직수집 (#68) 과 **같은 기사인데 2행씩**
  존재했다 (Meslier 영입 · 트로사르 합의) — dedup 이 잡지 못한 중복.

## 2. 원인 1 — 말머리가 담지 않는 정보를 매핑이 가정

- fmkorea 의 `[공홈]` 말머리는 "**글 주제 구단의** 공홈" 이라는 상대 표기다
→ 이용자는 타 구단 공홈 발표에도 같은 말머리를 쓴다.
- OUTLET_MAP 은 이를 Arsenal.com 절대 매핑으로 처리해, 표기에 없는 정보 (어느 구단인지) 를
  아스날로 가정했다 — tier 0 최상 등급이라 오귀속 비용이 가장 큰 지점에서 틀렸다.
- 검증축은 이미 있었다: 어댑터가 추출하는 **원문 URL 도메인** (mancity.com · manutd.com) 이
  정체를 말해 주고 있었으나 매핑이 참조하지 않았다.

## 3. 원인 2 — 사이트 개편이 URL dedup 의 가정을 깬다

- dedup 은 canonical URL (+ 제목 기반 content_hash) 로 "같은 기사 = 같은 URL" 을 가정한다.
- 공홈 개편으로 기사 URL 형식이 바뀌자 같은 기사가 두 형식으로 유통됐다:
  fmkorea 글의 원문 링크 = 구 형식 (`/news/illan-meslier-signs-arsenal`),
  직수집 = 신 형식 (`/news/illan-meslier-signs-for-arsenal-aSP1T2x5SP7c`).
- 제목도 fmkorea (한국어) 와 직수집 (영어) 이 달라 content_hash 도 불일치
→ 두 dedup 축이 모두 통과해 같은 기사가 2행 적재됐다.
- 일반화: **개편된 사이트를 직수집으로 복구하면, 그 도메인의 구 URL 을 실어 나르던
  발견 소스와의 중복이 새로 생긴다** — 복구 자체가 만든 사각이다.

## 4. 해결 (PR #70, 사용자 확정)

- `[공홈]` 말머리 전체 drop — 아스날 공홈은 직수집이 더 빠르고 official 규칙 태깅까지 커버,
  타 구단 공홈은 제품 범위 밖 (도메인 검증 유지안은 중복 이원화 잔존으로 기각).
- 매핑의 생산 · 소비 양쪽 제거 — OUTLET_MAP 항목 + credibility.yaml 한글 alias
  (alias 만 남기면 잠재 tier 0 부여 경로가 남는다, 런북 §2.7).
- 기존 5건 DELETE (오귀속 2 · 중복 2 · 인터뷰 1) + 재렌더, mongo raw 보존.

## 5. 예방

- **관례 표기 → 정체성 매핑 점검**: 커뮤니티 말머리처럼 이용자 관례에 기대는 표기를
  절대 정체성 (특정 매체 · 구단) 으로 매핑할 때는, 표기가 그 정체성을 실제로 담는지 묻고
  이미 추출 중인 검증축 (원문 URL 도메인) 과 대조할 수 있는지 먼저 본다.
- **소스 복구 시 중복 대조**: 개편 사이트를 직수집으로 복구할 때는 타 소스가 그 도메인
  기사를 적재 중인지 확인한다 — 이번 건은 오귀속 조사가 우연히 발견했다.

```sql
-- 복구 도메인의 소스별 적재 현황 — 직수집 외 소스가 나오면 구/신 URL 중복 후보
SELECT source_id, COUNT(*) FROM articles
WHERE url LIKE '%arsenal.com%' GROUP BY source_id;
```

## 6. 관련

- 레지스트리 제거 체크리스트: `docs/runbook/2026-07-15-credibility-registry-ops.md` §2.7
- 발견 소스 원문 승격 설계: `docs/runbook/2026-07-13-fmkorea-search-adapter-ops.md`
