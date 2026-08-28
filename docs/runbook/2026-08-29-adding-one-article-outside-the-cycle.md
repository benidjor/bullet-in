# 기사 한 건만 회차 밖에서 넣고 화면까지 올리는 절차 (2026-08-29)

수집 규칙이 놓친 기사 하나를 손으로 넣어야 할 때의 절차다.
2026-08-29 에 구단 공식 영입 발표 (이고르 타이욘) 가 태그 조건에 걸려 안 들어온 자리에서 썼다.

**규칙을 고치는 것과 한 건을 넣는 것은 다른 일이다.**
규칙은 창 후보 전량에 대 보고 바뀌는 것을 전수로 읽어야 하는데, 그 사이에도 화면에는 그 소식이 있어야 한다.
이 절차는 **규칙을 안 건드리고** 한 건만 정상 경로에 태운다.

## 1. 왜 `INSERT` 로 끝내면 안 되나

기사 한 행은 여러 곳에서 재료를 받는다.

- 본문 · 이미지 · 저자는 어댑터가 소스별로 다르게 뽑는다
- 공신력 등급은 매체 · 기자 사전에서 나온다
- 중복 판정은 `content_hash` 와 정규화된 URL 두 축이다

**손으로 `INSERT` 하면 이 셋이 다 빈다.**
그래서 어댑터가 만드는 것과 **같은 모양** (`RawItem`) 을 만들어 정상 경로에 넣는다.

## 2. 어댑터와 같은 모양으로 만든다

어댑터의 `fetch()` 안에서 그 기사 하나에 해당하는 부분만 떼어 쓴다.
**함수를 옮겨 적지 말고 import 한다** — 옮겨 적으면 어댑터가 바뀔 때 조용히 갈라진다.

```python
from bullet_in.adapters.arsenal_api import ARTICLE_QUERY, GRAPHQL_URL, _accept, _body_payload
from bullet_in.canonical import canonical_url, content_hash
from bullet_in.pipeline import to_articles

payload = {"title": art["title"], "published": art["publicationDate"],
           "published_precision": "time", "accept_path": _accept(art) or "title",
           **_body_payload(art["articleBody"])}
item = RawItem(source_id="arsenal_official", source_type="api",
               url=URL, fetched_at=now, raw_payload=payload)
item.content_hash = content_hash(payload["title"], canonical_url(URL))
arts, stats = to_articles([item], sources, seen=mart.seen_map(), registry=registry)
mart.upsert(arts)
RawStore(mongo).insert_many([item])      # 원본도 정상 경로와 같이 남긴다
```

**채택 경로 (`accept_path`) 를 올려 잡지 않는다.**
단계 규칙이 태그 채택분에만 `official` 을 고정하므로, 어댑터가 `None` 을 낸 것을 `tag` 로 적으면 규칙 밖의 값을 손으로 만드는 셈이다.
`title` 로 두면 모델 판정을 받은 뒤 `promote_official` 이 정상적으로 올린다 (실제로 `done` → `official` 로 올라갔다).

## 3. 그 한 건만 번역 · 분류한다

정기 회차를 기다리면 최대 세 시간이다.
대상을 `content_hash` 하나로 좁혀 `run.py` 의 해당 구간과 같은 함수를 부른다.

```python
missing = [r for r in mart.rows_missing_translation() if r["content_hash"] == TARGET]
generatable, title_only = partition_generatable(missing)
rewrite_rows, translate_rows = partition_by_body_level(generatable)
# enrich_rows · rewrite_rows_guarded · title_only_rows → finalize_translation → set_translation
# roster.normalize_pairs → roster.record_article_players
# transfer_stage.rule_stage → classify_stage_rows → promote_official → set_stage
```

**단계 분류를 빠뜨리면 렌더가 멈춘다** — 런북 §3 의 스니펫에 `stage` 빈 행 가드가 있고, 빈 행이 있으면 그 자리에서 중단된다.

## 4. 재렌더 · 배포

```bash
ssh <호스트> 'bash -lc "cd ~/bullet-in && set -a && source .env && set +a && \
  uv run python -c \"import os;from sqlalchemy import create_engine;\
from bullet_in.confirm_player import _render;_render(create_engine(os.environ[\\\"MARIADB_URL\\\"]))\" \
  && ./infra/deploy-site.sh"'
```

재렌더는 `confirm_player._render` 를 쓴다 — `run.py` 서빙 경로와 1:1 로 유지되는 유일한 자리다 (런북 스니펫은 낡은 적이 있다).

## 5. 확인은 배포본이 아니라 값으로 한다

**렌더된 HTML 을 훑어 확인하지 말 것.**
이 회차에 실제로 밟았다 — 해시 근처 블록을 잘라 단추 글자를 읽었더니 세 건 중 하나가 **이웃 블록의 단추**를 집었다 (「스톤스」 자리에 「돈체프」).

대신 이렇게 본다.

```bash
curl -sL "<배포본>/article/<hash>.html" | grep -o '<h1[^>]*>[^<]*'   # 그 기사 하나
curl -sL "<배포본>/index.html" | grep -c "<찾는 문자열>"               # 노출 여부
```

묶음 · 단계처럼 계산이 들어간 값은 **제품 함수를 직접 돌려** 본다 (`cluster_events` · `protagonist`).

## 6. 같은 절차를 쓴 다른 일

이 회차에서 세 번 썼고 형태가 조금씩 달랐다.

| 무엇 | 어디까지 했나 |
| --- | --- |
| 기사 한 건 삽입 | §2 → §3 → §4 |
| 표기 정정 (기사 3건 · 네 필드) | DB 문자열 치환 → §4 (번역 불필요) |
| 선수 확정 | `confirm_player` 가 §3 · §4 를 알아서 함 (`--dry-run` 으로 재번역 대상 0 확인 후) |

**공통 규율은 「마른 실행으로 대상을 먼저 세고 돌린다」** 다.
선수 확정은 `--dry-run` 이 「등장 기사 3 · 재번역 대상 0」 을 먼저 보여 줘 Gemini 호출 0회로 끝났다.

## 7. 참조

- 재생성 · 배포 — `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` §6.1
- 렌더 절차 정본 — `docs/runbook/2026-08-28-rendering-the-home-page-before-you-deploy-it.md`
- 이 회차가 놓친 규칙 — 안건 `2α` 공홈아카데미태그
