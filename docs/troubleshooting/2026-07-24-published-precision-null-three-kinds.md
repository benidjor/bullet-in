# published_precision NULL 은 한 가지 문제가 아니다 — 세 부류 진단 (2026-07-24)

트랙 B PR-B (B4 발행 시각) 착수 전 전 소스 실태를 진단하다가, NULL 246행 (전체 294행 중) 이 서로 다른 세 부류임을 확인했다.
계획의 전제 ("goal 어댑터가 수집 시각을 저장") 는 낡아 있었다 — goal 은 2026-07 에 html 어댑터로 전환돼 이미 발행 시각을 정상 수집 중이었다.

## 세 부류

- **① 라벨 누락 (코드 버그 · 백필 가능)** — `published_at` 은 정확한데 (트윗 · API 의 발행 시각) `published_precision` 만 안 붙임.
x_afcstuff 62 · guardian 5 · arsenal_official 5 = 72행.
mongo raw_payload 에 원문 시각 (`created_at` · `published`) 이 남아 있어 **재수집 없이** precision 을 재도출할 수 있다.
- **② 레거시 폴백 (재수집 없이 복구 불가)** — 발행 시각 정확화 트랙 (2026-07-20 · PR #87 · #88) **이전** 수집분.
당시 어댑터가 시각을 안 뽑아 `published_at` 이 수집 시각으로 폴백됐고, raw 에도 시각이 없다.
html 5개 소스 (football_london 64 · bbc_gossip 45 · goal 16 · skysports 16 · bbc_sport 8) + fmkorea 25 = 174행.
저장된 URL 을 개별 재파싱하는 길만 있으나 404 · 페이지 시각 미노출로 수율이 불확실하다.
- **③ 원천 미제공 (정상)** — 페이지가 발행 시각을 아예 안 내주는 경우.
현재도 발생할 수 있고 설계상 정상이다 (없는 시각을 지어내지 않음).

## 진단법

**precision × fetched_at 경계 분석** — 소스별로 `time` 행과 NULL 행의 `fetched_at` 범위를 대조한다.

```sql
SELECT source_id,
       DATE(MIN(CASE WHEN published_precision='time' THEN fetched_at END)) AS time_min,
       DATE(MAX(CASE WHEN published_precision IS NULL THEN fetched_at END)) AS null_max
FROM articles GROUP BY source_id;
```

- 경계일 (여기선 2026-07-20) 을 사이에 두고 갈리면 NULL 은 레거시 (②) — 현행 어댑터는 정상이다.
- NULL 이 경계를 넘나들면 현행 코드 버그 (①) 다.
- 이어서 mongo raw_payload 의 `published` · `created_at` 유무로 백필 가능성을 판정한다 — ①이면 있고 ②면 없다.

## 파생 발견

이 진단 중 사용자의 "오피셜 기사가 왜 없나" 지적으로 arsenal_official 커버리지 기아를 발견했다.
표시 (시각 안 보임) 의심을 파면 데이터 부류 판정으로 환원되고, 그 과정에서 더 큰 결함이 드러날 수 있다.
상세: `docs/troubleshooting/2026-07-24-arsenal-official-filter-starvation.md`.

## 교훈

- 계획 문서의 결함 전제는 작성 시점 관찰이다.
착수 전 최신 수집분 (경계 이후 `fetched_at`) 으로 어댑터의 **현재** 동작을 재검증할 것 — 스펙 · 머지 PR 먼저 확인 관례의 데이터 판.
- "precision NULL = 전부 같은 문제" 로 묶으면 백필 가능한 72행과 불가능한 174행을 같은 처방 (전면 재수집 등) 으로 오판하게 된다.
부류를 먼저 가르면 ①은 저비용 백필, ②는 투자 판단, ③은 무대응으로 처방이 갈린다.

## 참고

- 발행 시각 정확화 트랙 spec: `docs/superpowers/specs/2026-07-20-published-at-accuracy-design.md`
- 관련 계획 (B4 정정): `docs/superpowers/plans/2026-07-22-classification-relevance-track.md`
- precision 해석 규칙: `src/bullet_in/adapters/meta.py` `_parse_published`
