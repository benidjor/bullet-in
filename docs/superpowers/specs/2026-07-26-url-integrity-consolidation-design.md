# URL 정합 통합 설계 (완전체 보호 · 스텁 업그레이드)

2026-07-26 브레인스토밍 확정본.
수집 라인 트랙 1/3 — fmkorea 의 원문 URL 저장 설계와 upsert 덮어쓰기가 충돌하는 결함을 고치고, 온스테인 트윗을 원문 기사와 같은 행으로 합류시킨다.
사용자 확정 사항 (완전체 보호 · 스텁 업그레이드 · 업그레이드 시 전면 채택 · BBC 단건 재수집) 을 단일 근거로 담는다.

## 1. 배경 · 증상

- fmkorea 어댑터는 퍼온 글을 원문 기사 URL 로 저장한다 (발견 소스 설계 의도).
- 기존 원문 행과 URL UNIQUE 가 충돌하면 `dedup.classify` 가 hash 불일치를 "changed" (revision+1) 로 판정하고, `MartStore.upsert` 의 ON DUPLICATE KEY UPDATE 가 제목 · 기자 · tier 를 덮어쓴다.
- 실제 피해: `bbc_sport` 행 3건이 fmkorea 한국어 제목으로 교체됨 (revision 2 · journalist NULL · 영문 원제 소실 · 07-25 백필 배치).
- 역방향도 성립한다 (원 소스 재수집이 fmkorea 흔적을 되덮음)
— 플립플롭 가능.

## 2. 추가 발견 — 배치 내 정렬도 사실상 무력

- `pipeline.py` 의 fmkorea 후순위 정렬은 first-seen 을 원문 소스로 만들려는 장치지만, 뒤에 온 fmkorea 항목이 "changed" 판정을 받으면 결과 목록에 같이 실려 upsert 에서 뒤가 앞을 덮는다.
- fmkorea 제목은 한국어라 hash 가 항상 다르므로, 같은 배치 안에서도 보호는 제목이 완전히 같은 경우 (실제로는 없음) 에만 동작해 왔다.
- 이번 가드는 cross-run 과 배치 내를 같은 규칙으로 막는다.
정렬은 유지한다
— 배치 내에서 양쪽이 모두 완전체일 때 "먼저 본 쪽 보호" 의 승자를 원문 소스로 만드는 역할이 새로 생긴다.

## 3. 확정 정책 (2026-07-26 사용자 · 재논의 금지)

- 같은 URL 로 새 아이템 도착 시: 기존 행에 body_source 있으면 (완전체) 보호 · 새 아이템 버림.
- 기존 행에 body_source 없으면 (스텁), 새 아이템이 body_source 를 가질 때만 업그레이드 (교체 · 정보 증가 방향).
- 같은 소스의 정당한 기사 갱신 (revision 원 목적) 은 유지
— 소스 동일 여부 × 완전체 여부의 2축 규칙.
- 업그레이드 시 귀속은 새 아이템 전면 채택 (source_id 포함)
— 행이 "처음부터 새 소스가 수집한 것" 과 동일해져 serve · enrich 의 source_id 분기가 그대로 맞는다.
- 완전체 판정 = `body_source` 가 NULL 아니고 빈 문자열 아님 (페이월 헤드라인-온리는 스텁).

## 4. 판정 매트릭스 — `dedup.classify` 확장

seen 맵 값을 `(hash, revision)` → `(hash, revision, source_id, has_body)` 로 확장하고, classify 가 새 아이템의 `(source_id, has_body)` 를 받아 판정한다.

| 상황 | 판정 | 처리 |
|---|---|---|
| URL 미존재 | `new` (rev 1) | 현행 |
| 같은 소스 · hash 동일 | `duplicate` | 현행 (드롭 · dup 집계) |
| 같은 소스 · hash 상이 | `changed` (rev+1) | 현행 (정당한 갱신) |
| 다른 소스 · 기존 완전체 | `blocked` | 드롭 · blocked 집계 (BBC 사례 차단) |
| 다른 소스 · 기존 스텁 · 새 아이템 완전체 | `upgrade` (rev+1) | 교체 허용 |
| 다른 소스 · 둘 다 스텁 | `blocked` | 드롭 (first-seen 승리) |

- `upgrade` 는 downstream 에서 `changed` 와 동일하게 처리한다.
content_hash 가 바뀌므로 upsert 의 IF 절이 번역 4필드를 자동 리셋해 재번역 큐로 들어간다 (의도된 동작).
- pipeline 은 `blocked` 를 드롭하고 `blocked_count` 로 집계한다 (journal 로그 노출).
- 배치 내 갱신: 항목을 결과에 실을 때 local_seen 에 `(hash, rev, source_id, has_body)` 를 기록해 같은 배치의 후속 충돌에도 같은 규칙이 적용되게 한다.

## 5. 구현 지점

- `MartStore.seen_map()`: SELECT 에 `source_id` 와 body_source 보유 여부를 추가해 4-튜플을 반환한다.
- `dedup.classify`: 시그니처 확장 + §4 매트릭스.
호출처는 `pipeline.to_articles` 하나뿐이다.
- `pipeline.to_articles`: 새 아이템의 has_body (`raw_payload["body"]` 비어있지 않음) 산출 · blocked 드롭 · 집계 · local_seen 4-튜플 갱신.
- `MartStore.upsert`: ON DUPLICATE 절에 `source_id=VALUES(source_id)` 한 줄 추가.
같은 소스 갱신에는 같은 값이라 무해하고, cross-source 로 upsert 에 도달하는 경우는 `upgrade` 뿐이므로 (blocked 는 pipeline 에서 이미 드롭) 교체가 곧 전면 채택이 된다.
- 모든 적재 경로 (run.py 정기 · collect_fmkorea 보충 · backfill_fmkorea 소급) 가 `to_articles` 를 통과하므로 한 곳 수정으로 전 경로가 보호된다.

## 6. 온스테인 단일 상세 — X 카드 링크 추출

- 목적: x_ornstein 행의 키를 트윗 URL 이 아닌 원문 기사 URL 로 만들어, fmkorea 전문 도착 시 같은 행에서 승격되게 한다 (상세 페이지 1개
— 온스테인 X spec (2026-07-25) §7 의 "행 2개 유지" 결정 기각).
- `_TWEET_JS` 에 `card.wrapper` href 캡처를 추가한다 (`_JOURN_JS` 의 기존 패턴 재사용).
afcstuff 인용 경로도 같은 JS 를 쓰지만 해당 파서는 새 필드를 무시하므로 무해하다.
- `fetch()` 에서 `self_source` 항목 중 card_href 있는 트윗만 t.co 리졸브를 수행한다.
`x_backtrack.resolve_and_fetch` 재사용 · final_url 만 사용 · 본문 미저장 (확정).
- 성공 시 `RawItem.url` = 원문 기사 URL, payload 에 `tweet_url` 보존 (mongo raw 추적용).
- 폴백: 리졸브 실패 시, 또는 결과가 x.com · twitter.com 도메인이면 (인용 트윗 카드
— 기사 아님) 현행 트윗 URL + 인명 묶음을 유지한다.
- 접촉 예산: 카드 트윗당 GET 1회 (실측 회차당 통과 ~4건이라 소량).
- 귀결: 스텁 상태의 서빙 링크가 원문 기사 (The Athletic 등 페이월 포함) 로 향한다.
키 = url 컬럼 = 링크이므로 정책의 자연 귀결이다.

## 7. BBC 오염 3행 복구 — 단건 재수집 CLI

- 대상: bbc.com/sport/football/articles/ `c77yg781lr8o` (기마랑이스) · `cvge7wen5g9o` (멜리에) · `c235lr80ekko` (촐리스).
- 세 기사는 BBC 정기 수집 창 (RSS 최신분) 밖이라 자연 수렴이 불가능하다.
- `src/bullet_in/refetch_urls.py` (신규 소형 CLI): `--url` 반복 인자 + `--source-id` 로 대상 지정
→ html 메타 추출 (meta.extract_* · backfill_journalist 의 저자 추출 재사용)
→ RawItem 생성
→ `to_articles` (같은 소스 갱신이라 가드 통과)
→ `upsert` (rev+1 · 번역 리셋).
- 실행 순서: 가드 머지 · VM 반영 후에만 실행한다.
복구
→ enrich-only 패스로 번역 수렴 (docs/runbook/2026-07-19-enrich-only-pass.md)
→ 재렌더 · 검증 (행 추가 백필은 렌더 전 수렴 패스 필수 교훈 적용).
- VM 원격 실행은 예방책 적용: uv PATH 고정 · 산출물 grep 게이트를 배포 앞에 · `docker exec -i` 는 heredoc 한정 (docs/troubleshooting/2026-07-26-remote-render-silent-pitfalls.md).

## 8. 테스트 (TDD)

- classify 단위: §4 매트릭스 6분기 전부.
- pipeline cross-run: seen 에 완전체 존재
→ fmkorea 새 아이템 드롭 + blocked 집계.
- pipeline 배치 내: EN 완전체 + fmkorea 완전체 같은 URL
→ EN 승리 (정렬 + 가드 결합).
- 스텁 업그레이드: 온스테인 스텁 seen
→ fmkorea 완전체 통과 · rev+1.
- 동일 소스 갱신: 제목 바뀐 재수집이 계속 "changed" 로 통과.
- upsert: upgrade 행의 source_id 교체 (mart 행 단위).
- x_playwright: 카드 캡처 파싱 · 리졸브 성공 시 url 교체 · 실패 · x.com 도메인 폴백 (모킹).
- refetch CLI: 추출
→ RawItem
→ upsert 경로 단위.

## 9. PR 분할 · 순서

- PR-1: 가드 (classify · pipeline · upsert) + refetch CLI.
독립 머지 가능하고, 이것만으로 오염 재생산이 차단된다.
- PR-2: 온스테인 카드 리졸브 (x_playwright).
가드에 의존하지 않지만, 승격이 의미 있으려면 가드 선행이 안전하므로 순차.
- 이후: 머지 (사용자 직접)
→ VM 최신 main pull
→ BBC 3행 복구 실행
→ enrich 수렴
→ 재렌더 · 검증.

## 10. 병렬 조건 · 제약

- UI 세션 (PR-2 선수 트랙 · 워크트리 serve-filter-fix) 병렬 중
— serve/ · templates · name_map.yaml 수정 금지 (이 설계는 무접촉) · sources.yaml 변경 없음.
- PR 은 착수 시 최신 origin/main 분기 · 머지 직후 상대 세션에 한 줄 공유.
- 가드 머지 전까지 fmkorea 백필 · 보충 임의 실행 금지 (오염 재생산).
- 라이브 접촉 명령은 tee 필수 · 출력 확인 목적 재실행 금지.
