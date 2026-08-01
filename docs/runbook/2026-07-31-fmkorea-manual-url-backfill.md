# fmkorea 본문 수동 주소 회수 (2026-07-31)

검색 백필이 못 닿는 fmkorea 글을 사람이 브라우저로 찾아 주소를 넘겨 채우는 절차다.
2026-07-31 에 본문 빈 행 23건을 이 절차로 하루 안에 정리했다
— 21건 회수 (fetch 21회 · 실패 0) + 사용자 판단으로 2건 삭제.
같은 규모를 검색 배치로 했다면 요청 약 4배에 며칠이 걸렸을 일이다.

## 1. 언제 이 절차를 쓰나

- `--by-title` 검색 배치가 미적중을 낼 때다.
검색은 키워드당 최근 20건만 돌려주므로 오래된 글은 어떤 검색어로도 안 나온다.
- 배치 1 실측 (2026-07-31 11:15): 대상 5건 중 미적중 3건이 검색 13회를 소모했고,
검색 17회를 쓴 뒤의 본문 fetch (18~19번째 요청) 가 430 으로 막혀 채움이 0건이었다.
- 미적중 행은 대상 정렬 (`published_at DESC`) 의 상위 슬롯을 계속 점거한다.
`--exclude-hashes` 로 빼거나 (2회 연속 미적중 확정 후), 이 절차로 주소를 직접 공급한다.

## 2. 절차

### 2.1. 대상 집계와 목록 전달

```sql
SELECT LEFT(content_hash,8), published_at, title_original, url
FROM articles
WHERE source_id='fmkorea' AND COALESCE(body_source,'')=''
ORDER BY published_at DESC;
```

- 해시 8자 · 제목 · 저장된 원문 주소를 표로 만들어 사용자에게 전달한다.
- 건수는 실행 직전에 다시 센다 — 새 행이 수시로 들어온다 (실측 22 → 23).

### 2.2. 사람이 주소를 찾는다

- fmkorea 검색창에 제목 일부를 넣어 글을 찾고, **검색 결과 주소를 그대로 복사**하면 된다.
`search.php?…document_srl=NNN…` 의 `document_srl` 이 글 번호이고 CLI 가 정규화한다.
- 주소가 중간에 잘려도 `document_srl` 파라미터만 살아 있으면 쓸 수 있다 (실측 1건).

### 2.3. 주소 파일 작성과 실행

```
# /tmp/post-urls-runN.txt — "<해시 접두사 8자 이상> <주소>" · # 주석 허용
3146dc6a https://www.fmkorea.com/10152481709
98deadf5 https://www.fmkorea.com/10115335099
```

```bash
set -a; source .env; set +a
uv run python -m bullet_in.backfill_fmkorea_body \
  --post-urls-file /tmp/post-urls-runN.txt --force 2>&1 | tee /tmp/bf-manual-runN.log
```

- 요청 수 = 글 수 (fetch 만 한다). 버스트 상한 (약 18요청 · 아래 §3) 아래로 파일을 나눈다
— 실측은 12건 + 9건 두 번, 회차 사이 슬롯에 하나씩.
- `--force` 는 3h 접촉 간격 가드 우회 — 단회 실행에 필수, 연속 사용 금지.
- `--limit N` 을 함께 주면 파일 앞 N 건만 fetch 한다 (버스트 분할용).

### 2.4. 검증

- 실행 요약: `대상 N · 일치 N · 채움 N · 실패 0` 과 로그의 430 카운트 0 을 확인한다.
- DB: 채운 행의 `body_source` 길이 · `body_level=1` · 번역 4필드 NULL (재번역 대기) 을 확인한다.
- 본문 내용 표본 대조를 1~2건 한다 — 주소를 사람이 옮겨 적었으므로 잘못된 글이 들어갈 수 있다.
- 다음 정기 회차가 재번역 · 배포한다 (회차 종료 후 `curl -sL` 로 상세 페이지 확인 · `-L` 필수).

### 2.5. 회수하지 않을 행의 정리

- 오래돼 가치가 없는 행은 사용자 확정을 받아 `DELETE` 한다 (실측 2건 · 6월 이전).
- Mongo raw 는 남으므로 완전 소실이 아니다.
- 목록 반영은 다음 회차 재렌더가 한다 — 첫 화면 · all.html 에서 부재를 확인한다.

## 3. 접촉 예산 실측 갱신 (2026-07-31)

- 예산은 직전 누적 접촉량 (약 16분 창) 기준이라는 07-30 모델이 재확인됐다.
수동 채움 12 fetch 의 30분 뒤 정기 회차가 19요청을 전부 200 으로 통과했다.
- 검색 배치의 실패 지점도 같은 모델과 일치한다 — 검색 17회 직후의 fetch 2회가 430.
- 판단 기준은 여전히 "직전 회차 검색이 200 이었는가" 다
— 접촉 0회 (journalctl) 로 먼저 본다.

## 4. 참고

- 접촉 예산 · 검색 도달 범위 진단: `docs/troubleshooting/2026-07-30-fmkorea-contact-budget-and-search-reach.md`
- 검색 배치 규율: `docs/runbook/2026-07-25-fmkorea-backfill-paging.md`
- CLI 옵션 도입: #162 (`--by-title`) · #177 (`--exclude-hashes` · `--post-urls-file`)
