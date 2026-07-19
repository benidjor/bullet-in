# football.london Tom Canton 정리 런북 — 타 기자 기존 기사 삭제

- 날짜: 2026-07-19
- 관련: spec `docs/superpowers/specs/2026-07-19-source-curation-design.md` §3.2 · 선례 `docs/runbook/2026-06-30-bbc-collection-cleanup.md`

## 1. 배경

football.london 은 아스날 전담 Tom Canton 외 기자 기사가 220건 중 157건 (mart 전체의 44%) 을 차지해 낮은 신뢰도 기사로 피드를 채웠다.
처리 방침은 "Tom Canton 만 허용 · 나머지 DB 삭제 · 신규 필터 차단" — 이전 세션의 "서빙 숨기기" 발언과 충돌했으나 트랙 ② 착수 시 사용자 재확인으로 원래 지시가 확정됐다.
신규 차단은 pipeline 의 `journalist_allowlist` drop (spec §3.1) 이 담당하고, 이 런북은 기존 데이터 삭제만 다룬다.

## 2. 전제 (필수)

- **`journalist_allowlist` 필터가 머지 · 배포된 뒤에만 실행한다.**
  삭제만 먼저 하면 다음 회차에 목록 페이지 잔존 기사가 재수집돼 되살아난다 (필터가 있어야 drop 으로 차단).
- MariaDB `articles` 만 대상 — MongoDB raw 는 무접촉 (원본 보존 원칙, BBC 정리 선례와 동일).
- 삭제는 비가역 — 사전 확인 쿼리의 건수가 기대값과 크게 다르면 중단하고 원인을 파악한다.

## 3. 사전 확인

```sql
SELECT journalist, COUNT(*) FROM articles
WHERE source_id='football_london' GROUP BY journalist ORDER BY 2 DESC;

SELECT COUNT(*) FROM articles
WHERE source_id='football_london'
  AND (journalist IS NULL OR journalist <> 'Tom Canton');
```

- 실측 기대값 (2026-07-19 기준): 전체 220건 · Tom Canton 63건 · 삭제 대상 157건 · journalist NULL 0건.
  NULL 가드는 안전장치 — 이후 회차에서 NULL 이 생겼어도 Canton 확인 불가라 삭제 대상이 맞다.

## 4. 삭제 실행

```sql
DELETE FROM articles
WHERE source_id='football_london'
  AND (journalist IS NULL OR journalist <> 'Tom Canton');
```

## 5. 사후 검증

```sql
-- 남은 행 전건이 Tom Canton 인지 (기대: Canton 행만, 이외 0)
SELECT journalist, COUNT(*) FROM articles
WHERE source_id='football_london' GROUP BY journalist;
```

- 다음 사이클 1회 실행 후 로그 · stats 의 `author_drop_count` 로 타 기자 재유입이 drop 되는지 관측한다 (기대: 재유입 적재 0).
- 사이트 재생성은 별도 조치 불필요 — 다음 `run.py` 사이클이 mart 를 다시 읽어 렌더한다.

## 6. 함정

- **dedup seen 과의 상호작용**: 삭제된 행은 `seen_map()` 에서 사라져 다음 회차에 신규로 재수집을 시도한다.
  allowlist 필터가 그 시점에 drop 하므로 부활하지 않는다 — 이것이 §2 의 순서 (필터 선배포) 가 필수인 이유다.
- **enrich 산출물 동반 소실**: 삭제 행의 번역 · 요약 · 분류도 함께 사라진다.
  의도된 결과 — Canton 외 기사는 제품에서 제외가 방침이라 재생성 비용이 없다.

## 7. 실행 기록 (2026-07-19, PR #60 머지 직후)

- 순서 준수: 필터 머지 (squash `59d098f`) 확인 후 실행.
- 백필 선행: bbc_gossip image_url 45건 중 성공 45 · 실패 0.
- 사전 확인: 삭제 대상 157 · Canton 잔존 63 · NULL 0
→ §3 기대값과 전건 일치, 삭제 실행.
- 사후 검증: football_london 잔존 = Tom Canton 63건만, mart 전체 358 → 201건.
- 재유입 검증: 직후 전체 사이클 1회 (fmkorea 2h 창 준수, 마지막 접촉 +2h 경과 후 실행)
→ 신규 적재 0 · 에러 0 · football_london 63건 유지 = allowlist drop 실동작 확인.
- 캡처 재촬영: 측정 런북 §6 절차로 인덱스 · 상세 갱신 (gossip 썸네일 반영 · 플레이스홀더 해소).
