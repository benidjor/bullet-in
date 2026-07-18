# 기자 후속 트랙 ② 수집 · 소스 — bbc_gossip 썸네일 · football.london Tom Canton 제한 설계

- 날짜: 2026-07-19
- 상태: 사용자 승인 (대화 합의 반영)
- 선행: 기자 중심 트랙 (PR #54) · facet tier 정렬 (PR #56) · v1 완성 (PR #58)

## 1. 배경 · 목표

v1 완성 후 기자 후속 트랙 ② 는 수집 소스 두 곳의 품질 문제를 정리한다.

- bbc_gossip 카드 45건 전부가 썸네일 없이 PHOTO 플레이스홀더로 노출된다.
  원인은 body_selector 부재로 상세 페이지를 방문하지 않아 og:image 를 추출할 기회가 없는 것 (기사에는 og:image 존재 확인됨).
- football.london 은 아스날 전담 Tom Canton 외 기자 기사가 220건 중 157건을 차지해 mart 전체 (358건) 의 44% 를 낮은 신뢰도 기사로 채운다.
  원래 지시 (2026-07-16) 는 "Tom Canton 만 허용 · 나머지 DB 삭제 · 신규 필터 차단"이며, 이전 세션의 "서빙 숨기기" 발언과의 충돌은 이번 세션에서 원래 지시대로 재확정했다.

## 2. 스코프

포함:

- bbc_gossip 경량 상세 방문 (og:image 만 추출) + 기존 45건 image_url 백필.
- football.london 신규 수집분 Tom Canton 외 차단 (pipeline drop) + 기존 157건 DB 삭제.
- 머지 후 라이브 반영과 README 캡처 재촬영 (측정 런북 §6) 연결.

제외 (별도 트랙):

- X · 품질 항목 (talksport 누락 · @SamiMokbel_BBC 미승격 · 제목 환각 검출 · 요케레스 glossary · 400자 문단화)
→ 기자 후속 트랙 ③.
- 링크 선수 워치리스트 · 교차 corroboration 스코어링 (이번 세션 질의로 범위 밖 재확인).
- bbc_gossip 본문 수집 · 번역 (사용자 결정: 썸네일만 — tier 4 가십 라운드업 전문 번역 비용 회피).

## 3. 설계

### 3.1. football.london — journalist_allowlist (pipeline drop)

저자는 상세 페이지를 열어야 알 수 있어 목록 단계 필터가 불가하다.
따라서 수집 요청은 그대로 발생하고, journalist 확정 직후 pipeline 에서 걸러낸다.

- config: `sources.yaml` 의 football_london 항목에 소스 최상위 필드 `journalist_allowlist: ["Tom Canton"]` 추가.
  `journalist_label` 과 같은 층위라 `load_sources` 결과로 pipeline 에 자연 전달된다.
- drop 위치: `to_articles` 에서 `select_journalist` 직후 · `resolve_tier` 이전.
  allowlist 가 지정된 소스에서 journalist 가 allowlist 에 없으면 (None 포함) 그 항목을 버린다.
  여자팀 필터 (`_is_womens_football`) 와 같은 pipeline 단계 drop 선례를 따른다.
- 공저 처리: `select_journalist` 가 등재 기자를 우선 선정하므로 공저 목록에 Tom Canton 이 포함되면 Canton 이 대표로 뽑혀 생존한다.
  별도 매칭 규칙을 만들지 않는다 (규칙 이중화 방지).
- journalist None 처리: 상세 fetch 실패 · 저자 부재 항목은 Canton 확인이 불가하므로 drop.
  seen 에 남지 않아 다음 회차에 자연 재시도된다.
- 관측: `to_articles` 반환 stats 에 `author_drop_count` 추가 (`women_count` 선례).
- 어댑터는 무변경 — 정책은 pipeline, 수집은 어댑터라는 기존 경계 유지.

### 3.2. football.london — 기존 데이터 삭제

- 대상: `DELETE FROM articles WHERE source_id='football_london' AND (journalist IS NULL OR journalist <> 'Tom Canton')`.
- 실측 (2026-07-19): 220건 중 Tom Canton 63건 잔존 · 157건 삭제 · journalist NULL 0건 (NULL 가드는 안전장치).
- 시점: 코드 머지 후 같은 세션.
  삭제만 먼저 하면 다음 회차에 목록 페이지 잔존 기사가 재수집돼 되살아나므로 필터 배포가 선행돼야 한다.
- MongoDB raw 는 무접촉 (raw 계층은 원본 보존 원칙, BBC 정리 선례와 동일).
- 절차는 정리 런북으로 이 PR 에 포함하고, 실행 기록은 후속 docs PR 에 남긴다 (PR #20 선례).

### 3.3. bbc_gossip — thumbnail_only 경량 상세 방문

- `HtmlAdapter` 에 `thumbnail_only: bool = False` 파라미터 추가.
  `body_selector` 가 없고 이 플래그가 켜져 있으면 상세를 방문해 `extract_og_image` 결과만 `payload["image_url"]` 에 싣는다.
  본문 · 인라인 이미지 · 저자는 추출하지 않는다
  → Gemini 번역 비용 무변경 · `journalist_label` (BBC Gossip) 동작 유지.
- 우선순위: `body_selector` 가 있으면 기존 풀 수집 경로 그대로, `thumbnail_only` 는 무시된다.
- 실패 처리: 상세 fetch 실패 시 image_url 미설정으로 제목만 적재 (기존 body 실패 처리와 같은 결).
  이미 적재된 행은 pipeline 의 duplicate 판정으로 적재를 건너뛰어 갱신되지 않으므로, 놓친 이미지는 백필 (§3.4) 몫이다.
- factory: `thumbnail_only=c.get("thumbnail_only", False)` 전달 1줄.
- config: bbc_gossip 의 config 에 `thumbnail_only: true` 추가.

### 3.4. 기존 45건 image_url 백필

- 신규 모듈 `src/bullet_in/backfill_image.py` — `backfill_journalist.py` 패턴 (모듈 CLI · `--dry-run` · `--limit` · 요청 간격 1.5s · 멱등).
- 대상 산출: `sources.yaml` 에서 `thumbnail_only` 소스를 도출해 `image_url IS NULL AND source_id IN (...)` 행만 재fetch.
  현재 대상 = bbc_gossip 45건.
- 갱신: `extract_og_image` 결과가 있으면 `image_url` UPDATE, 부재 · fetch 실패면 NULL 유지 (재실행 가능).
- BBC 는 fmkorea 2h 규칙 대상이 아니다.

## 4. 테스트

- adapter: thumbnail_only 모킹 fetch — image_url 만 채워지고 body · images · authors 미설정, body_selector 공존 시 풀 수집 우선.
- factory: thumbnail_only 키 전달.
- pipeline: allowlist 5케이스 — 비허용 기자 drop · Tom Canton 생존 · 공저 (Canton 포함) 생존 · journalist None drop · allowlist 미지정 소스 무영향 + `author_drop_count` 집계.
- backfill_image: 대상 선정 · UPDATE 값 산출 로직 단위 테스트 (재fetch 는 모킹).
- 라이브 (머지 전): bbc_gossip 어댑터 단독 `fetch()` 로 og:image 실수집 확인 (셀렉터 드리프트는 모킹 테스트가 못 잡음).
  football.london 은 이미 수집 중인 소스라 pipeline 단위 테스트로 충분.

## 5. 라이브 반영 절차 (머지 후, 순서 고정)

1. 백필 실행
→ bbc_gossip 45건 image_url 채움.
2. football.london 157건 DELETE (정리 런북).
3. 전체 사이클 1회 실행 (fmkorea 마지막 fetch 대비 2h 경과 확인 후)
→ 필터 · 썸네일 동작 실증 + 사이트 재생성.
4. README 캡처 재촬영 (측정 런북 §6 규격 · 스크립트) + README 반영
→ 후속 docs PR 로 트랙 마무리 (캡처는 머지 후에만 라이브에 반영되므로 코드 PR 에 묶지 않는다).

## 6. 완료 기준

- bbc_gossip: 신규 수집분 image_url 채움 + 기존 45건 백필 (og:image 보유 건) — 인덱스 카드에서 PHOTO 플레이스홀더 해소.
- football.london: DB 에 Tom Canton 63건만 잔존, 이후 사이클에서 타 기자 기사 재유입 0건 (`author_drop_count` 로 관측).
- 테스트 전건 통과 (기존 378 passed 기준 + 신규).
- 캡처 2장 재촬영 · README 반영 (후속 docs PR).
