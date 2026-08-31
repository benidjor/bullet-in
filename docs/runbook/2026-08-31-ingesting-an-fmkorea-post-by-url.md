# fmkorea 글을 주소로 직접 적재하는 절차 (2026-08-31)

검색어에 안 걸려 아예 들어오지 않은 글을 사람이 주소로 넘겨 새로 적재한다.
2026-08-31 에 Mundo Deportivo 전재 두 건을 이 절차로 채웠다 (fetch 4회 · 차단 0).

## 1. 이 절차와 본문 회수 절차의 차이

**`2026-07-31-fmkorea-manual-url-backfill.md` 와 대상이 다르다.**

| | 본문 회수 (07-31) | 새 글 적재 (이 문서) |
| --- | --- | --- |
| 기사 행 | **이미 있다** (본문만 비었다) | **없다** |
| 도구 | `backfill_fmkorea_body --post-urls-file` | 어댑터의 `_process` 직접 호출 |
| 넘기는 것 | 해시 + 주소 | **제목 + 주소** |

행이 없는데 본문 회수 도구를 쓰면 대상이 0건으로 나온다.

## 2. 언제 쓰나

- 정기 회차 검색어 (`아스날` 제목 검색 등) 에 안 걸리는 글일 때.
  방출 기사처럼 **제목의 주어가 아스날이 아닌 소식**이 여기 해당한다.
- 워치리스트 배치의 수확 상한에 밀려 계속 안 들어오는 글일 때.
- **원인 진단이 먼저다** — 왜 안 걸렸는지 모르면 같은 글이 계속 새어 나간다.

## 3. 접촉 예산 확인

라이브 접촉이므로 회차와 겹치지 않는 슬롯에서 돈다.

```bash
ssh <호스트> 'journalctl -u bullet-in --since "-3 hours" --no-pager | grep -iE "fmkorea|430" | tail -8'
ssh <호스트> 'cat ~/.bullet-in/fmkorea_last_contact'
```

- 마지막 접촉이 **30분 이상 지났고** 그 회차가 200 이었으면 안전하다.
- 요청 수 = 글 수 × 2 내외다 (글 fetch + 원문 fetch).
- 정기 회차는 KST 00 · 03 · … · 21 시다.

## 4. 스크립트

**검색 단계 (`_discover`) 만 건너뛰고 나머지는 정기 회차와 같은 함수를 쓴다.**
말머리 파싱 · 원문 회수 · 저자 추출 · 이미지 · 무관 글 필터가 그대로 걸린다.
규칙을 여기에 다시 적으면 회차와 갈린다.

```python
from bullet_in.collect_fmkorea import build_fmkorea_adapter, persist

# 제목은 말머리 파싱 입력이라 `[MD]` 를 포함한 원문 그대로여야 한다
TARGETS = [("[MD] 가브리엘 제주스, 월요일에 바르셀로나 도착 후 메디컬 테스트 예정",
            "https://www.fmkorea.com/10278862489")]

adapter = build_fmkorea_adapter(cfg, os.environ.get("FMKOREA_PROXY"))
adapter.relevance_terms = src["config"].get("relevance_terms") or []
adapter.player_names = PlayerStore(engine).confirmed_ko_names()
async with adapter._client() as c:
    raw = await adapter._process(c, TARGETS)
persist(raw, mart)
```

- **제목을 정확히 옮긴다** — 말머리가 빠지면 매체가 `None` 이 되어 그 글이 스킵된다.
- **한 번만 돌린다** — 출력 확인 목적의 재실행은 접촉을 두 배로 쓴다 (`tee` 로 남긴다).
- 무관 글 필터를 주입하지 않으면 회차와 기준이 갈린다.

## 5. 번역 · 분류 · 선수 귀속

적재는 원자료와 mart 까지만 한다.
나머지는 따로 돌린다.

1. **번역 · 분류** — `2026-07-19-enrich-only-pass.md` §3.
   **§2 의 잔존 확인을 §3 직전에 다시 돌린다** (그 사이 회차가 끼면 승인 없는 호출이 나간다).
2. **선수 귀속** — 이 경로는 `article_players` 를 안 만든다.
   `backfill_article_players` 가 맞는 도구인데 **오래된 순으로 처리해 특정 건만 겨냥할 수 없다.**
   대상 전체 수를 세어 보이고 승인을 받는다.
   `reextract_article_players` 는 **이미 귀속이 있는 행만** 다시 뽑으므로 여기서는 아무 일도 안 한다.
3. **렌더 · 배포** — `confirm_player._render(engine)` 뒤 `./infra/deploy-site.sh`.

## 6. 검증

```bash
curl -sSL -A "Mozilla/5.0" "https://bullet-in.pages.dev/all.html" -o /tmp/all.html
grep -c "<해시 앞 8자>" /tmp/all.html
```

- 저장값이 아니라 **배포본**에서 확인한다.
- 첫 화면에 안 보여도 정상일 수 있다 — 사건 묶음에 접히기 때문이다
  (`serve/render.py` 의 `promote_recent` · 같은 날 대표 카드가 있으면 안 꺼낸다).

## 7. 참고

- 본문 회수 절차 = `docs/runbook/2026-07-31-fmkorea-manual-url-backfill.md`.
- 접촉 예산 = `docs/troubleshooting/2026-07-30-fmkorea-contact-budget-and-search-reach.md`.
- 배치 운영 = `docs/runbook/2026-08-01-watchlist-batch-ops.md`.
