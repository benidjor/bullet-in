# 소스 확장 구현 계획 — goal 복구 + guardian · skysports 등재

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** goal 을 HtmlAdapter 로 전환 복구하고 guardian ( Open Platform API ) · skysports ( HtmlAdapter ) 를 이적 키워드 필터와 함께 신규 등재한다.

**Architecture:** guardian_api.py 만 소폭 확장 ( q → tag · bodyText · thumbnail · 제목 필터 ) 하고, goal · skysports 는 sources.yaml config 만으로 등재한다 ( spec §3 접근안 A ).
셀렉터 4종은 계획 단계에서 httpx UA 로 라이브 확정했다 ( 2026-07-15 02:20 ~ 02:30 KST 실측 ).

**Tech Stack:** Python 3.11 · httpx + BeautifulSoup · respx ( 테스트 모킹 ) · pytest.

**Spec:** `docs/superpowers/specs/2026-07-15-source-expansion-design.md`

## Global Constraints

- 작업 위치: worktree `.claude/worktrees/source-expansion` 안에서만 — 메인 체크아웃 ( SLO-1 세션 점유 ) 파일 수정 금지.
- README.md 수정 금지 ( SLO-1 트랙 충돌 ) — 소스 표 갱신은 후속 ( spec §8 ).
- fmkorea 접근 ( fetch · 검색 ) 금지 — SLO-1 벤치 rate-limit 창 오염 방지.
- 03:00 ~ 03:15 KST 대량 라이브 fetch 자제 ( 벤치 3회차 창 ).
- GUARDIAN_API_KEY 는 시크릿 — `.env` 에만 두고 커밋 · 테스트 픽스처 · 문서에 넣지 않는다.
- 커밋: `<type>(<scope>): 한국어 제목` + 도입 1 ~ 2문장 + 명사형 불릿 ( 컨벤션 §1.1 ) + 실제 작업 모델 트레일러 ( §1.3 ).
- git 신원: `benidjor <94089198+benidjor@users.noreply.github.com>`.
- PR 코드 diff ≤ 200 LOC 목표 — 초과 시 spec §8 분할 기준 적용.
- 테스트 실행: `uv run pytest -q` ( 통합 테스트는 DB 없으면 자동 skip ).

## 라이브 확정 셀렉터 ( 2026-07-15 실측 요약 )

| 대상 | 셀렉터 | 실측 |
|---|---|---|
| goal 목록 | `a[href^='/en/news/']:not([aria-label]), a[href^='/en/lists/']:not([aria-label])` | 26건 유니크, 이미지 앵커 중복 0 |
| goal 본문 | `article` | /en/lists/ 3,407자 · /en/news/ 2,959자 ( 해시 클래스 회피 ) |
| skysports 목록 | `h3.sdc-site-tile__headline a[href*='/football/news/']` | 18건 유니크, 네비 혼입 0 ( 비스코프 시 22건 중 4건 혼입 ) |
| skysports 본문 | `div.sdc-article-body` | 3,063자 |
| guardian API | `tag=football/arsenal` + `show-fields=trailText,bodyText,thumbnail` | 아스날 태그만 반환 · bodyText · thumbnail 실재 |

---

### Task 1: GuardianAdapter 확장 ( tag 스코프 · 필드 확장 · 제목 필터 )

**Files:**
- Modify: `src/bullet_in/adapters/guardian_api.py` ( 전체 교체 수준 — 현재 26줄 )
- Test: `tests/test_guardian_adapter.py` ( 기존 1개 테스트도 신규 시그니처로 갱신 )

**Interfaces:**
- Consumes: `bullet_in.models.RawItem` ( 기존 ).
- Produces: `GuardianAdapter(source_id: str, api_key: str, tag: str = "football/arsenal", title_contains: str | list[str] | None = None)`.
  `fetch() -> list[RawItem]`, raw_payload 키 = `title · published · summary · body · image_url`.
  `self.params` ( dict ) · `self.title_keywords` ( list[str] | None ) 속성은 Task 2 factory 테스트가 참조.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_guardian_adapter.py` 를 아래 내용으로 교체.

```python
import asyncio, respx, httpx
from bullet_in.adapters.guardian_api import GuardianAdapter

def _resp(results):
    return httpx.Response(200, json={"response": {"results": results}})

@respx.mock
def test_guardian_adapter_maps_results():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal sign X", "webUrl": "https://g.test/1",
         "webPublicationDate": "2026-05-27T09:00:00Z",
         "fields": {"trailText": "deal done", "bodyText": "full body text",
                    "thumbnail": "https://media.test/t.jpg"}}]))
    a = GuardianAdapter(source_id="guardian", api_key="k")
    items = asyncio.run(a.fetch())
    assert items[0].url == "https://g.test/1"
    assert items[0].source_type == "api"
    p = items[0].raw_payload
    assert p["title"] == "Arsenal sign X"
    assert p["published"] == "2026-05-27T09:00:00Z"
    assert p["summary"] == "deal done"
    assert p["body"] == "full body text"
    assert p["image_url"] == "https://media.test/t.jpg"

@respx.mock
def test_guardian_adapter_requests_tag_and_fields():
    route = respx.get("https://content.guardianapis.com/search").mock(
        return_value=_resp([]))
    a = GuardianAdapter(source_id="guardian", api_key="k", tag="football/arsenal")
    asyncio.run(a.fetch())
    q = route.calls.last.request.url.params
    assert q["tag"] == "football/arsenal"
    assert q["show-fields"] == "trailText,bodyText,thumbnail"
    assert q["page-size"] == "20"

@respx.mock
def test_guardian_adapter_title_filter_blocks_nonmatch():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal SIGN X", "webUrl": "https://g.test/1", "fields": {}},
        {"webTitle": "Match report: dull draw", "webUrl": "https://g.test/2",
         "fields": {}}]))
    a = GuardianAdapter(source_id="guardian", api_key="k",
                        title_contains=["sign", "transfer"])
    items = asyncio.run(a.fetch())
    assert [i.url for i in items] == ["https://g.test/1"]

@respx.mock
def test_guardian_adapter_title_filter_accepts_str():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Transfer latest", "webUrl": "https://g.test/1", "fields": {}}]))
    a = GuardianAdapter(source_id="guardian", api_key="k", title_contains="transfer")
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_guardian_adapter_missing_fields_defaults():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal sign X", "webUrl": "https://g.test/1"}]))
    a = GuardianAdapter(source_id="guardian", api_key="k")
    p = asyncio.run(a.fetch())[0].raw_payload
    assert p["summary"] == ""
    assert p["body"] == ""
    assert p["image_url"] is None
```

기대값 손 재계산: 필터 `["sign", "transfer"]` 에 대해 `"Arsenal SIGN X".lower()` 는 "sign" 포함 → 통과, `"Match report: dull draw".lower()` 는 둘 다 미포함 → 차단.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_guardian_adapter.py -v`
Expected: FAIL 5건 — 매핑 · 필터 · 결손 테스트는 `KeyError: 'body'` 류 ( 구 payload 에 body · image_url 없음 ), tag 테스트는 `TypeError: unexpected keyword argument 'tag'`.

- [ ] **Step 3: 최소 구현** — `src/bullet_in/adapters/guardian_api.py` 전체를 아래로 교체.

```python
from __future__ import annotations
from datetime import datetime, timezone
import httpx
from bullet_in.models import RawItem

class GuardianAdapter:
    source_type = "api"
    BASE = "https://content.guardianapis.com/search"
    def __init__(self, source_id: str, api_key: str, tag: str = "football/arsenal",
                 title_contains: str | list[str] | None = None):
        self.source_id = source_id
        # q= 전문검색은 타 구단 기사 혼입 → tag 스코프 (spec §5.1)
        self.params = {"tag": tag, "api-key": api_key,
                       "show-fields": "trailText,bodyText,thumbnail",
                       "order-by": "newest", "page-size": 20}
        if title_contains is None:
            self.title_keywords: list[str] | None = None
        elif isinstance(title_contains, str):
            self.title_keywords = [title_contains.lower()]
        else:
            self.title_keywords = [k.lower() for k in title_contains]
    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(self.BASE, params=self.params)
            r.raise_for_status()
            results = r.json()["response"]["results"]
        now = datetime.now(timezone.utc)
        out = []
        for x in results:
            title = x["webTitle"]
            if self.title_keywords and not any(
                    k in title.lower() for k in self.title_keywords):
                continue
            f = x.get("fields", {})
            out.append(RawItem(source_id=self.source_id, source_type="api",
                               url=x["webUrl"], fetched_at=now,
                               raw_payload={"title": title,
                                            "published": x.get("webPublicationDate"),
                                            "summary": f.get("trailText", ""),
                                            "body": f.get("bodyText", ""),
                                            "image_url": f.get("thumbnail")}))
        return out
```

제목 필터 시맨틱은 `html.py` 의 HtmlAdapter 와 동일 ( 소문자 부분일치 · str | list 수용 ).

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_guardian_adapter.py -v`
Expected: PASS 5건.

- [ ] **Step 5: 전체 회귀 확인**

Run: `uv run pytest -q`
Expected: 전부 PASS.
주의: 구 factory 는 `c.get("query", "Arsenal")` 를 위치 인자로 넘겨 신 시그니처의 tag 자리에 들어가므로 생성 자체는 성공한다 ( 의미 불일치는 Task 2 배선 갱신으로 해소 — 이 시점에 guardian 소스는 미등재라 런타임 영향 없음 ).

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/adapters/guardian_api.py tests/test_guardian_adapter.py
git commit -m "$(cat <<'EOF'
feat(adapters): GuardianAdapter tag 스코프 · bodyText · 제목 필터 확장

q= 전문검색의 타 구단 기사 혼입을 tag 스코프로 제거하고 상세 페이지 데이터 계약을 채운다.

- 파라미터: q · section → tag, show-fields 에 bodyText · thumbnail, page-size 20
- payload: summary · body · image_url 추가 — pipeline 소비 계약 정렬
- 제목 필터: HtmlAdapter 동일 시맨틱 (소문자 부분일치, str | list 수용)

Refs: docs/superpowers/specs/2026-07-15-source-expansion-design.md §5

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

### Task 2: factory 배선 · 키 누락 격리

**Files:**
- Modify: `src/bullet_in/adapters/factory.py` ( guardian_api 분기 · import )
- Test: `tests/test_adapter_factory.py` ( 기존 guardian 테스트 갱신 + 2개 추가 )

**Interfaces:**
- Consumes: Task 1 의 `GuardianAdapter(source_id, api_key, tag, title_contains)` · `self.params` · `self.title_keywords`.
- Produces: `build_adapters(cfg)` 가 GUARDIAN_API_KEY 부재 시 guardian 소스만 건너뛰고 WARNING 로깅 ( 예외 없음 ).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_adapter_factory.py` 의 `test_factory_builds_enabled_adapters` 를 갱신하고 2개 테스트를 추가.

```python
def test_factory_builds_enabled_adapters(monkeypatch):
    monkeypatch.setenv("GUARDIAN_API_KEY", "k")
    cfg = {"sources": [
        {"source_id": "guardian", "adapter": "guardian_api", "enabled": True,
         "config": {"tag": "football/arsenal", "title_contains": ["sign"]}},
        {"source_id": "off", "adapter": "rss", "enabled": False, "config": {"feed_url": "x"}},
    ]}
    adapters = build_adapters(cfg)
    assert [a.source_id for a in adapters] == ["guardian"]

def test_factory_passes_tag_and_title_contains_to_guardian(monkeypatch):
    monkeypatch.setenv("GUARDIAN_API_KEY", "k")
    cfg = {"sources": [{"source_id": "guardian", "adapter": "guardian_api",
            "enabled": True,
            "config": {"tag": "football/arsenal", "title_contains": ["sign"]}}]}
    a = build_adapters(cfg)[0]
    assert a.params["tag"] == "football/arsenal"
    assert a.title_keywords == ["sign"]

def test_factory_skips_guardian_without_key(monkeypatch, caplog):
    monkeypatch.delenv("GUARDIAN_API_KEY", raising=False)
    cfg = {"sources": [
        {"source_id": "guardian", "adapter": "guardian_api", "enabled": True,
         "config": {"tag": "football/arsenal"}},
        {"source_id": "feed", "adapter": "rss", "enabled": True,
         "config": {"feed_url": "x"}},
    ]}
    with caplog.at_level("WARNING"):
        adapters = build_adapters(cfg)
    assert [a.source_id for a in adapters] == ["feed"]
    assert "GUARDIAN_API_KEY" in caplog.text
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_adapter_factory.py -v`
Expected: 신규 2건 FAIL ( 키 누락 → KeyError · tag 미배선 ), 기존 fmkorea · html 테스트는 PASS 유지.

- [ ] **Step 3: 최소 구현** — `factory.py` 상단에 logging 을 추가하고 guardian_api 분기를 교체.

```python
# 상단 import 에 추가
import logging
log = logging.getLogger(__name__)
```

```python
        elif kind == "guardian_api":
            key = os.environ.get("GUARDIAN_API_KEY")
            if not key:
                log.warning("GUARDIAN_API_KEY 미설정 — %s 소스 스킵 (다음 사이클 재시도)", sid)
                continue
            out.append(GuardianAdapter(sid, key,
                                       tag=c.get("tag", "football/arsenal"),
                                       title_contains=c.get("title_contains")))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_adapter_factory.py tests/test_guardian_adapter.py -v`
Expected: 전부 PASS.

- [ ] **Step 5: 전체 회귀 확인**

Run: `uv run pytest -q`
Expected: 전부 PASS ( Task 1 Step 5 의 허용 FAIL 이 여기서 해소 ).

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/adapters/factory.py tests/test_adapter_factory.py
git commit -m "$(cat <<'EOF'
feat(adapters): factory guardian 배선 · 키 누락 시 소스 스킵 격리

GUARDIAN_API_KEY 부재가 build 단계 KeyError 로 전체 사이클을 죽이던 것을 소스 단위 격리로 바꾼다.

- 배선: config 의 tag · title_contains 를 GuardianAdapter 에 전달
- 키 누락: 해당 소스만 skip + WARNING (fmkorea 429 격리 패턴, 다음 사이클 재시도)

Refs: docs/superpowers/specs/2026-07-15-source-expansion-design.md §5.3

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

### Task 3: sources.yaml 3종 등재

**Files:**
- Modify: `config/sources.yaml` ( goal 항목 교체 · guardian + skysports 추가 )

**Interfaces:**
- Consumes: Task 2 의 factory 배선 ( adapter: guardian_api 가 tag · title_contains 를 읽음 ).
- Produces: enabled 소스 목록에 goal · guardian · skysports 포함 — Task 4 라이브 검증이 이 config 를 그대로 사용.

- [ ] **Step 1: goal 항목 교체** — 기존 goal 블록 ( `adapter: playwright` · `enabled: false` ) 을 아래로 교체.

```yaml
  - source_id: goal
    display_name: Goal.com
    tier: 2
    medium: newspaper
    adapter: html
    config:
      # 2026-07 팀 슬러그 갱신 · 정적 서빙 확인 → playwright 에서 전환 (spec §4.1)
      list_url: "https://www.goal.com/en/team/arsenal/news/4dsgumo7d4zupm2ugsvm4zm4d"
      item_selector: "a[href^='/en/news/']:not([aria-label]), a[href^='/en/lists/']:not([aria-label])"
      base_url: "https://www.goal.com"
      title_contains: ["transfer", "sign", "signed", "signing", "deal", "loan", "bid", "fee", "medical", "agree", "agreed", "join", "joins", "target", "linked", "links", "contract", "swap", "move", "talks"]
      body_selector: "article"
    enabled: true
```

- [ ] **Step 2: guardian · skysports 추가** — fmkorea 항목 앞에 삽입.

```yaml
  - source_id: guardian
    display_name: The Guardian
    tier: 1.5
    medium: newspaper
    adapter: guardian_api
    config:
      tag: "football/arsenal"
      title_contains: ["transfer", "sign", "signed", "signing", "deal", "loan", "bid", "fee", "medical", "agree", "agreed", "join", "joins", "target", "linked", "links", "contract", "swap", "move", "talks"]
    enabled: true
  - source_id: skysports
    display_name: Sky Sports
    tier: 1.5
    medium: newspaper
    adapter: html
    config:
      # 네비게이션 /football/news/ 혼입 배제 — 타일 헤드라인 스코프 (spec §4.3)
      list_url: "https://www.skysports.com/arsenal"
      item_selector: "h3.sdc-site-tile__headline a[href*='/football/news/']"
      base_url: "https://www.skysports.com"
      title_contains: ["transfer", "sign", "signed", "signing", "deal", "loan", "bid", "fee", "medical", "agree", "agreed", "join", "joins", "target", "linked", "links", "contract", "swap", "move", "talks"]
      body_selector: "div.sdc-article-body"
    enabled: true
```

- [ ] **Step 3: build 스모크 확인** — 실제 config 로 어댑터가 전부 생성되는지 검증 ( 더미 키 사용, 네트워크 미접근 ).

```bash
GUARDIAN_API_KEY=dummy uv run python -c "
import yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open('config/sources.yaml'))
ids = [a.source_id for a in build_adapters(cfg)]
print(ids)
assert {'goal', 'guardian', 'skysports'} <= set(ids), ids"
```

Expected: `['arsenal_official', 'bbc_sport', 'bbc_gossip', 'goal', 'football_london', 'guardian', 'skysports', 'x_afcstuff', 'fmkorea']` 출력, assert 통과.

- [ ] **Step 4: 전체 회귀 확인**

Run: `uv run pytest -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add config/sources.yaml
git commit -m "$(cat <<'EOF'
feat(config): goal html 전환 복구 · guardian · skysports 신규 등재

계획 단계 라이브 확정 셀렉터로 3종을 등재하고 이적 키워드 필터를 일관 적용한다.

- goal: 신규 팀 슬러그 + :not([aria-label]) 셀렉터, playwright → html 전환
- guardian: tag=football/arsenal · tier 1.5, guardian_api 어댑터 첫 등재
- skysports: 타일 헤드라인 스코프로 네비 혼입 배제 · tier 1.5

Refs: docs/superpowers/specs/2026-07-15-source-expansion-design.md §4

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

### Task 4: 라이브 검증 · 최종 리뷰 · PR ( 컨트롤러 직접 )

**Files:**
- 수정 없음 ( 검증 실패 시에만 config 셀렉터 보정 후 재커밋 ).

**Interfaces:**
- Consumes: Task 3 까지의 전체 브랜치.
- Produces: 라이브 검증 결과 ( PR 본문 기재 ) · squash PR.

- [ ] **Step 1: 시간 창 확인** — `date` 로 03:00 ~ 03:15 KST 벤치 창 밖인지 확인, 창 안이면 대기.

- [ ] **Step 2: 키 주입** — worktree 루트 `.env` 에 GUARDIAN_API_KEY 한 줄 추가 ( 사용자 발급분, 커밋 금지 대상 — `.gitignore` 로 이미 제외 확인 ) 후 `set -a; source .env; set +a`.

- [ ] **Step 3: 어댑터 단독 라이브 fetch ( CLAUDE.md 함정 게이트 )** — fmkorea · x_afcstuff 는 실행하지 않는다.

```bash
uv run python -c "
import asyncio, yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open('config/sources.yaml'))
targets = {'goal', 'guardian', 'skysports'}
for a in build_adapters(cfg):
    if a.source_id not in targets:
        continue
    items = asyncio.run(a.fetch())
    bodies = [len(i.raw_payload.get('body') or '') for i in items]
    imgs = sum(1 for i in items if i.raw_payload.get('image_url'))
    print(a.source_id, 'items:', len(items), 'body_lens:', bodies[:5], 'imgs:', imgs)
    for i in items[:3]:
        print('  -', i.raw_payload['title'][:60], '|', i.url[:70])"
```

수용 기준 ( spec §7 ):
- 3종 모두 예외 없이 완료 · 이적 필터 통과 항목의 제목이 실제 이적 뉴스.
- goal · skysports 본문 길이 ≥ 500자, guardian body · thumbnail 채워짐.
- skysports 항목에 네비 링크 ( 멤버십 Q&A 등 비기사 ) 0건.
- 이적 필터로 0건인 소스는 `title_contains` 를 일시 제거한 스크립트로 셀렉터 자체 ( 링크 15건 안팎 ) 를 확인 후 정상 판정.

- [ ] **Step 4: 검증 실패 시 보정** — 셀렉터 불일치면 config 만 수정해 Step 3 재실행 · 재커밋, goal 이 비정적 응답이면 spec §6 에 따라 goal 만 트랙에서 분리하고 사용자에게 보고.

- [ ] **Step 5: 최종 whole-branch 리뷰** — superpowers:requesting-code-review 로 Fable 5 리뷰 ( spec 대비 완전성 · 컨벤션 ).

- [ ] **Step 6: verification-before-completion** — `uv run pytest -q` 전부 PASS + Step 3 수용 기준 재확인 후에만 완료 선언.

- [ ] **Step 7: PR** — 브랜치를 `feat/source-expansion` 으로 개명 · push, origin/main 리베이스 확인 ( SLO-1 PR 선머지 대비 ), 코드 diff LOC 확인 ( ≤ 200 목표 · 초과 시 spec §8 분할 ), PR 본문은 템플릿 주석 세칙 대조 · 라이브 검증 결과 기재 · Claude 서명 금지, squash merge 전제.

```bash
git branch -m worktree-source-expansion feat/source-expansion
git push -u origin feat/source-expansion
gh pr create --title "feat(sources): goal 복구 · guardian · skysports 신규 등재" --body-file /tmp/pr-body.md
```

---

## 모델 배정 ( 2026-07-13 확정 규칙 )

| Task | 구현 | 태스크 리뷰 |
|---|---|---|
| 1 GuardianAdapter | Haiku ( 코드 전문 ) | Sonnet |
| 2 factory | Haiku ( 코드 전문 ) | Sonnet |
| 3 sources.yaml | Haiku ( 코드 전문 ) | Sonnet |
| 4 라이브 검증 · PR | 컨트롤러 ( Fable 5 ) 직접 | — |

최종 whole-branch 리뷰: Fable 5.
커밋 트레일러: 설계 `Claude Fable 5 (설계)` + 구현 모델 병기 ( §1.3 ), Task 4 커밋 발생 시 Fable 5 단독 한 줄.
