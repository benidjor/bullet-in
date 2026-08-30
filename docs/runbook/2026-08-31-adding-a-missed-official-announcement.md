# 공홈이 놓친 영입 발표를 넣고 선수 페이지까지 올리는 절차 (2026-08-31)

안건 2α (공홈 아카데미 태그) 로 수집이 놓친 구단 공식 발표를 손으로 넣을 때의 순서다.
2026-08-31 에 두 건 (하비브 오군네예 · 제임스 스캔론) 을 이 순서로 넣었다.

기존 절차 (`2026-08-29-adding-one-article-outside-the-cycle.md`) 는 **기사 한 건을 화면에 올리는 것**까지만 다룬다.
이 문서는 거기서 이어지는 두 가지를 더한다
— **선수 페이지에 붙이는 귀속**과 **명단 표기와 화면 표기를 맞추는 일**이다.

## 1. 왜 안 들어왔는지부터 확인한다

`arsenal_api._accept` 가 `Men` 태그를 필수로 두는데 구단이 유스 발표에는 `Academy` 를 붙인다.
추측하지 말고 GetArticle 로 실제 태그를 받아 본다.

```python
from bullet_in.adapters.arsenal_api import (ARTICLE_QUERY, GRAPHQL_URL, _accept,
                                            _glide_id)
r = await c.post(GRAPHQL_URL, json={
    "operationName": "GetArticle", "query": ARTICLE_QUERY,
    "variables": {"articleId": "", "glideId": _glide_id(url), "glidePath": ""}})
art = r.json()["data"]["getArticle"]
print(art["articleType"], art["taxonomies"], _accept(art))
```

2026-08-31 두 건의 실제 값이다.

```
News · ['Academy', 'Arsenal U21', 'Transfer news', 'News', …] · _accept None
```

**이적 태그도 있고 제목 조건도 통과하는데 `Men` 앞에서 잘린다.**

**관측 장치도 같은 조건 안에 있다** — 어댑터의 `men_news_rejects` 는 `Men` 이 있는 기사만 기록해서, `Academy` 로 잘린 기사는 저널에도 안 남는다.
그래서 이 고장은 사람이 공홈을 보고 「왜 이게 없지」 할 때만 드러난다.

## 2. 삽입 · 번역 · 분류

`2026-08-29-adding-one-article-outside-the-cycle.md` §2 · §3 을 그대로 따른다.
번역 · 분류는 손으로 옮겨 적지 말고 **enrich 전용 패스** (`2026-07-19-enrich-only-pass.md` §3) 를 쓴다.

**분류 블록에 `promote_official` 이 있어야 한다.**
채택 경로가 `title` 인 공홈 기사는 모델이 낸 `done` 에서 이 함수가 `official` 로 올린다.
빠뜨리면 오피셜 배지가 안 붙는다 (그 스니펫의 누락을 2026-08-31 에 정정했다).

넣은 뒤 값으로 확인한다.

```
단계 official · 방향 in · tier 0.0
```

## 3. 선수 페이지 귀속 — 별도 작업이다

**enrich 전용 패스는 `article_players` 를 만들지 않는다.**
회차 경로는 번역 직후 같은 블록에서 귀속을 저장하는데 그 패스에는 그 단계가 없고, 한 번 번역된 행은 `title_ko IS NULL` 조건에서 빠져 **다음 회차가 다시 만지지 않는다.**

귀속이 없으면 그 기사는 홈 · 전체 기사에는 보이지만 **선수 페이지에는 안 붙는다.**

채우는 도구는 `backfill_article_players` 다 (`reextract_article_players` 는 이미 귀속이 있는 기사가 대상이라 반대다).

```bash
uv run python -m bullet_in.backfill_article_players --dry-run   # 대상 수를 먼저 센다
uv run python -m bullet_in.backfill_article_players
```

**대상을 좁힐 수 없다.**
도구가 「연결 없는 기사 전건」 을 대상으로 잡아 우리 몇 건만 고를 수 없다.
2026-08-31 에는 우리 2행을 넣으려고 28행을 돌렸다 (나머지 26행은 예전부터 비어 있던 것).

- **비용을 먼저 세어 보이고 승인을 받는다** — 전건이 Gemini 호출이다.
- **남의 구단 기사는 귀속 0명으로 끝난다** — 28행 중 실제로 연결이 생긴 것은 4행이고, 나머지는 우리 명단 선수가 안 나온다.
그래도 `state` 에 기록돼 다음에 재과금되지 않는다.
- **state 를 손으로 채워 대상을 좁히지 않는다** — 「처리 완료」 를 거짓으로 적는 셈이라, 나중에 「왜 이것들만 귀속이 없지」 를 다시 파야 한다.

확인은 값으로 한다.

```
선수 하비브 오군네예 · 역할 subject · 단계 official
선수 제임스 스캔론   · 역할 subject · 단계 official
```

## 4. 표기가 갈리는지 본다

선수를 새로 확정하면 **명단 표기와 번역 표기가 갈릴 수 있다.**
2026-08-31 에 명단을 「제임스 스캔론」 으로 확정했는데 번역이 전건 「스캔런」 으로 나왔다.

**확정 명령의 재검사는 이것을 안 잡는다.**
`confirm_player` 가 도는 `recheck_titles` 는 「원문에 없는 이름이 번역에 있다」 (환각) 를 보지, 표기가 낡았는지는 안 본다.
그래서 dry-run 이 「재번역 대상 0」 을 내도 표기는 갈린 채로 남는다.

인명 게이트가 대신 신호를 준다 — 공식 발표 기사에서 `인명 누락:Scanlon` 경고가 떴다.

고치는 절차는 `2026-08-29-spelling-dictionary-expansion.md` 다.
사전 등재 → 머지 → 소급 순서를 지킨다 (사전을 먼저 배포해 두는 것이 해시 변동에 대한 유일한 일반 방어).

## 5. 전체 순서 한눈에

```
① GetArticle 로 태그 확인          — 왜 안 들어왔나
② RawItem 삽입                     — 어댑터 함수 import · accept_path 는 올려 잡지 않는다
③ enrich 전용 패스                 — 번역 · 분류 · promote_official 포함
④ backfill_article_players         — 선수 페이지 귀속 · 대상 수를 세어 보이고 승인
⑤ 표기 확인 · 필요하면 사전 · 소급  — 명단 값과 화면 표기를 맞춘다
⑥ 재렌더 · 배포 · 값으로 확인       — confirm_player._render 후 deploy-site.sh
```

## 6. 참조

- 기사 한 건 삽입 — `docs/runbook/2026-08-29-adding-one-article-outside-the-cycle.md`
- 번역 · 분류 수렴 — `docs/runbook/2026-07-19-enrich-only-pass.md` §3
- 표기 사전 · 소급 — `docs/runbook/2026-08-29-spelling-dictionary-expansion.md`
- 선수 확정 · 명단 전이 — `docs/runbook/2026-07-31-player-roster-ops.md` §3 · §5 · §6
- 이 고장의 안건 — `2α` 공홈아카데미태그 (착수 보류)
