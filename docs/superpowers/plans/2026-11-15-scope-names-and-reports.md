# 수집 범위 넓히기 (이름 표기 · 낱말 · 경기 리포트 · 프리뷰) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2주 수집 검토에서 놓친 것으로 판정한 제목 15건과 경기 리포트 · 프리뷰를 받도록 수집 범위 판정을 넓힌다.

**Architecture:** `scope.ScopeRule` 에 발음 기호를 무시한 이름 대조 · 새 낱말 · 「Report:」 · 「Preview:」 머리말 · 「성만 쓴 이름은 본문의 전체 이름으로 확인」 을 더한다.
어댑터 셋은 판정할 때 손에 있는 글 (BBC 피드 요약 · Arsenal.com 본문 · Guardian · Sky 상세 페이지 본문) 을 문맥으로 넘긴다.
Guardian 경기 리포트는 제목에 표지가 없어 주소 (`-match-report`) 로 가린다.

**Tech Stack:** Python 3.11 · httpx · respx · feedparser · BeautifulSoup · pytest

**Spec:** 별도 설계 문서 없음 · 결정은 2026-11-15 세션의 사용자 결정 (아래 「결정」 절) 과 실측이다 · 검토 원자료는 세션 메모리 `review-2w-2026-11-15`

## 배경

2026-10-11 18:00 ~ 11-15 00:00 UTC (273 실행) 동안 수집 범위 판정이 버린 제목은 중복 제외 295건이다.
세션이 제목을 모두 읽어 15건을 「받았어야 할 글」 로 판정했고, 대부분 이름이 있는데도 놓친 제목이었다.

| 놓친 까닭 | 건수 | 예 |
| --- | --- | --- |
| 성만으로는 안 받는 이름 (`scope_name_full_only`) | 8 | 「Rice relishing title race 'anxiety' after win at Liverpool」 · 「Tuchel defends White after more Wembley boos」 |
| 애칭 · 이름만 씀 | 3 | 「Big Gabi enjoys latest clean sheet」 · 「In Focus: Ezri excels in win over Hull City」 |
| 발음 기호 (명단은 `Gyokeres`) | 1 | 「Viktor Gyökeres the difference as Arsenal claim nervy win against Slavia Prague」 |
| 이름 없는 팀 소식 | 2 | 「Team news: Six changes made for Slavia Prague showdown」 · 「Timber hits 100 Arsenal appearances」 |
| 이적 낱말이 키워드에 없음 | 2 | 「Arsenal monitor Leverkusen striker Kofane」 · 「Bournemouth will consider Scott sale…」 |

(「Timber hits 100…」 은 성만 쓴 이름이기도 해 두 줄에 걸친다 · 합계 15)

경기 리포트 · 프리뷰는 같은 기간 버린 제목 중 Arsenal.com 리포트 9 · 프리뷰 9 · Guardian 리포트 3 · BBC 리포트 1 이다.

## 결정 (2026-11-15 사용자)

| 항목 | 결정 |
| --- | --- |
| 발음 기호 | 무시하고 이름을 대조한다 |
| 애칭 · 이름 | `Gabi` · `Ezri` 를 이름 갈래에 더한다 |
| 이적 낱말 | `sale` · `monitor` 를 더한다 |
| 팀 소식 낱말 | `appearances` · `Team news` 를 더한다 |
| 성만 쓴 이름 다섯 (White · Rice · Jesus · Timber · Salmon) | 요약 · 본문에 전체 이름이 있으면 받는다 (사용자 제안 「문맥에 아스날」 을 세션이 「전체 이름」 으로 바꿔 제안 · 소스가 모두 아스날 전용이라 「Arsenal」 로는 안 갈린다 · 2026-11-17 사용자 승인) |
| 경기 리포트 · 프리뷰 | 받는다 (선택 (c)) |
| 라이브 블로그 | 넣지 않아도 된다 (지금처럼 둔다) |

## 작업 원칙 (Karpathy 4원칙 · CLAUDE.md 「행동 가이드라인」)

구현 · 리뷰 서브에이전트는 CLAUDE.md 의 4원칙을 지킨다.
특히 아래 둘은 이 계획에서 리뷰가 Important 로 다룬다.

- **요청 밖 변경 금지** — 작업의 Files 목록 밖 파일을 고치거나, 리뷰의 Minor 를 근거로 설계에 없는 동작을 더하지 않는다. 넣을 만하면 보고만 하고 사용자가 정한다.
- **근거 없는 단정 금지** — 보고 · 커밋 · 주석의 숫자와 사실은 실행한 명령이나 읽은 파일에 닿아야 한다. 닿지 않으면 「추정」 이라고 쓴다.

## 가정과 확인

| 가정 | 확인 방법 · 결과 |
| --- | --- |
| 새 규칙 전부를 버린 제목 295건에 대면 놓침 후보 15건이 모두 들어온다 | 세션 스크립트 (제목만 · 성만 쓴 6건은 「문맥 필요」 로 셈) · 후보 9건은 제목만으로 · 6건은 문맥 확인 뒤 |
| 새 규칙이 「아님」 제목을 끌어오지 않는다 | 같은 대 보기에서 「아님」 인데 걸리는 10건은 모두 Arsenal.com 영상 · 옛 꼭지 · `_accept` 가 범위 판정보다 먼저 `EXCLUDE_TAGS` 로 거른다 (`arsenal_api.py` `_accept`) · 태그는 기록에 없어 10건 모두 그 태그인지는 추정 |
| 성만 쓴 Ben White 기사는 본문에 「Ben White」 가 있다 | 운영 DB 저장 글 중 제목에 성만 있는 글 White 6 · Rice 9 · Timber 2 · Jesus 11 · 본문에 전체 이름이 없는 글은 모두 다른 사람 · 다른 뜻 (「White flag」 · 「Gibbs-White」 · 「Jesus de Miguel」) · 2026-11-15 BBC 피드 요약 「England manager Thomas Tuchel defended Ben White…」 |
| 판정 순간 BBC 는 요약 · Arsenal.com 은 본문 · Guardian · Sky 는 제목만 갖고 있다 | `rss.py` 루프의 `e.get("summary")` · `arsenal_api.py` `GetArticle` 의 `articleBody` · `html.py` 는 받기로 정한 뒤에 `fetch_article_detail` |
| Guardian · Sky 는 상세 페이지 본문을 이미 받는다 | `sources.yaml` 두 소스 모두 `body_selector` 가 있다 · 성만 쓴 제목만 판정 전에 한 번 받고 그 결과를 다시 쓴다 |
| Guardian 경기 리포트는 주소가 `-match-report` 로 끝나고 라이브 블로그는 `/football/live/` 아래다 | 2026-11-15 Guardian 아스날 목록 한 번 받음 · 「…/slavia-prague-arsenal-champions-league-match-report」 · 「/football/live/2026/nov/01/liverpool-v-arsenal-premier-league-live」 |
| Arsenal.com 리포트 · 프리뷰는 제목이 「Report:」 · 「Preview:」 로 시작한다 | 버린 제목 18건 모두 (「Report: Liverpool 0-1 Arsenal」 · 「Preview: Arsenal v Hull City」 등) |
| 이적 키워드 목록은 수집 범위 소스만 쓴다 | `sources.yaml` `*transfer_kw` 를 쓰는 곳 = bbc_sport · guardian · skysports · goal (`collect: false`) · football_london (`enabled: false`) · `factory.scope_rules` |
| 깔때기 `passed_by` 의 갈래 이름을 읽는 코드가 없다 | `grep passed_by src/bullet_in` = `scope.py` 뿐 · 실행 기록에 남기만 한다 |
| 기존 측정 시험 (`test_press_titles_measured_on_2026_10_06`) 의 숫자가 안 바뀐다 | 픽스처 84 제목에 새 낱말 · 머리말 0건 · 발음 기호 제목은 「Arsène Wenger」 둘 (명단 밖) |
| 번역이 주당 7건 안팎 는다 | 34일에 후보 15 + Arsenal.com 18 + Guardian 리포트 약 3 · 실제 증가는 그 기간의 경기 수에 따른다 (추정) |

## 더 단순한 꼴과 버린 이유

| 더 단순한 꼴 | 버린 이유 |
| --- | --- |
| 「Rice」 · 「White」 를 성만으로도 받는다 | 「Toure recalls winning the league at White Hart Lane」 이 들어온다 · 이 설정이 막으려던 바로 그 꼴 |
| 본문에 「Arsenal」 이 있으면 성만 쓴 제목을 받는다 | 네 소스가 모두 아스날 전용 페이지라 본문에 거의 늘 「Arsenal」 이 있다 · White Hart Lane 글도 통과 |
| 성만 쓴 제목이면 Guardian · Sky 상세 페이지를 늘 받는다 | 규칙상 그렇게 한다 · 다만 받은 결과를 버리지 않고 적재에 다시 써서 같은 글을 두 번 받지 않는다 |
| 경기 리포트를 점수 꼴 (`Arsenal 1-0 Hull`) 로 가린다 | 라이브 블로그 제목도 점수 꼴이고 (「Liverpool 0-1 Arsenal: Premier League – as it happened」) BBC 리포트 「Substitutes steal the show…」 는 점수가 없다 |
| BBC 리포트도 받는다 | 제목 · 주소에 표지가 없다 · 34일에 1건이라 이번에는 둔다 |
| 별칭을 명단 (players) 에 칸으로 만든다 | 별칭 칸이 없어 `scope_name_extras` 에 둔 것이 지금 방식이다 (`sources.yaml` 주석) · 두 개를 더하는 데 스키마를 바꿀 까닭이 없다 |

## Global Constraints

- 파이썬은 워크트리의 3.11 가상환경으로 돌린다 (`uv venv --python 3.11 --project .` 뒤 `uv run --project . --extra dev pytest`)
- 전체 테스트 기준 = 1,971 통과 · 89 skip (DB 없이 · `5c37a6f` · 2026-11-15)
- 판정 갈래 순서 = `keyword` → `extra` → `name` → `team` → `report` → `fullname` (처음 맞은 하나) · Guardian 주소 규칙은 어댑터에서 `report` 로 센다
- 발음 기호 무시 = `unicodedata.normalize("NFKD", s)` 에서 결합 문자를 빼고 `Ø` → `O` · `ø` → `o` · 이름 갈래와 전체 이름 확인에만 쓴다 · 대소문자 구분은 그대로
- 전체 이름 확인은 낱말 단위 (`\b…\b`) · 문맥이 없거나 비면 확인하지 않는다
- 새 설정 키 = Guardian `config.scope_url_contains: ["-match-report"]` · 그 밖의 소스에는 두지 않는다
- 시험에서 외부 사이트에 접속하지 않는다 (`respx` 모킹)

## Review Focus

- **하이픈이 붙은 성** — 「Gibbs-White」 는 `\bWhite\b` 에 걸리지만 본문에 「Ben White」 가 없으면 버린다 (Task 1 시험)
- **상세 페이지를 못 받음** — 성만 쓴 제목의 본문을 못 받으면 (HTTP 오류 · 빈 본문) 버리고 수집은 계속한다 (Task 2 시험)
- **같은 글을 두 번 받지 않음** — 판정 때 받은 상세 페이지를 적재에 다시 쓴다 (Task 2 시험 · 요청 수 1)
- **라이브 블로그** — 주소 규칙이 `/football/live/` 글을 받지 않는다 (Task 2 시험)
- **제목의 「Report」 가 머리말이 아닐 때** — 「Match report on…」 처럼 머리말이 아닌 곳의 낱말은 받지 않는다 (Task 1 시험)

## 알고 두는 한계 (고치지 않음)

- **BBC 경기 리포트는 여전히 놓친다** — 34일에 1건 (「Substitutes steal the show as Arsenal score three against Lille」)
- **Sky 리포트 꼴은 모른다** — 같은 기간 Sky 가 버린 리포트가 없어 주소 꼴을 재지 못했다
- **Guardian 라이브 블로그 · 이름 있는 라이브 제목** — 지금처럼 이름이 있으면 받고 없으면 버린다 (사용자 결정 「넣지 않아도 된다」)
- **「Gabi」 가 다른 사람일 수 있다** — 표본에는 없었다
- **번역 요금** — 주당 7건 안팎 늘 것으로 보인다 (추정)

---

### Task 1: 판정 규칙 넓히기

**Files:**
- Modify: `src/bullet_in/scope.py` (`EXTRA_WORDS` · 접기 함수 · `ScopeRule` · 독스트링)
- Modify: `config/sources.yaml` (`transfer_keywords` 에 `sale` · `monitor` · `scope_name_extras` 에 `Gabi` · `Ezri`)
- Test: `tests/test_scope.py`

**Interfaces:**
- Produces: `ScopeRule(keywords=(), names=(), confirm: Mapping[str, str] | None = None)` · `ScopeRule.confirm: dict[str, str]` (성 → 전체 이름) · `ScopeRule.match(title: str, context: str | None = None) -> str | None` (갈래 `keyword` · `extra` · `name` · `team` · `report` · `fullname`) · `ScopeRule.needs_context(title: str) -> bool` (제목에 `confirm` 의 성이 낱말로 있으면 참)

- [ ] **Step 1: 실패하는 시험을 쓴다** (파일 끝에 추가)

```python
def test_names_ignore_diacritics():
    rule = ScopeRule([], {"Viktor Gyokeres", "Gyokeres", "Ødegaard"})
    assert rule.match("Viktor Gyökeres the difference as Arsenal claim nervy win") == "name"
    assert rule.match("Odegaard assists for Norway") == "name"
    assert rule.match("gyökeres") is None                            # 대소문자 구분은 그대로


def test_new_extra_words():
    rule = ScopeRule([], set())
    assert rule.match("Timber hits 100 Arsenal appearances against Forest") == "extra"
    assert rule.match("Team news: Six changes made for Slavia Prague showdown") == "extra"
    assert rule.match("Teams newsletter") is None


def test_report_and_preview_prefix():
    rule = ScopeRule([], set())
    assert rule.match("Report: Liverpool 0-1 Arsenal") == "report"
    assert rule.match("Preview: Arsenal v Hull City") == "report"
    assert rule.match("Match report on Arsenal") is None


def test_surname_only_title_is_confirmed_by_full_name_in_context():
    rule = ScopeRule([], scope_names([("Ben White", "White"), ("Declan Rice", "Rice")],
                                     full_only=["White", "Rice"]),
                     confirm={"White": "Ben White", "Rice": "Declan Rice"})
    t = "Tuchel defends White after more Wembley boos"
    assert rule.needs_context(t)
    assert rule.match(t) is None
    assert rule.match(t, context="England manager Thomas Tuchel defended Ben White.") == "fullname"
    assert rule.match("Toure recalls winning the league at White Hart Lane",
                      context="Kolo Toure on Arsenal at White Hart Lane") is None
    assert rule.match("PSG could rival Arsenal for Gibbs-White",
                      context="Nottingham Forest's Morgan Gibbs-White") is None
    assert rule.match("Rice relishing title race", context="") is None
    assert not rule.needs_context("Arsenal back at Highbury")


def test_config_covers_new_transfer_words_and_aliases():
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    assert {"sale", "monitor"} <= set(cfg["transfer_keywords"])
    assert {"Gabi", "Ezri"} <= set(cfg["scope_name_extras"])
    rule = ScopeRule(cfg["transfer_keywords"], set(cfg["scope_name_extras"]))
    assert rule.match("Arsenal monitor Leverkusen striker Kofane") == "keyword"
    assert rule.match("Big Gabi enjoys latest clean sheet") == "name"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project . --extra dev pytest tests/test_scope.py -q`
Expected: 새 시험 5개 FAIL · 기존 시험 PASS

- [ ] **Step 3: 구현한다**

- `EXTRA_WORDS` 에 `"appearances"` · `"Team news"` 를 더한다.
- 접기 함수 `_fold(s: str) -> str` (Global Constraints 의 규칙) 를 두고, 이름 정규식은 접은 이름으로 만들고 접은 제목에 대조한다.
- 「Report:」 · 「Preview:」 머리말 정규식 `^(?:Report|Preview):` 을 두고 `team` 다음 갈래 `report` 로 센다.
- `confirm` 은 성마다 `\b성\b` 정규식을 미리 만든다 · `needs_context` 는 접은 제목에 그중 하나가 있으면 참 · `match` 는 앞 갈래가 모두 빗나가고 문맥이 있고 제목에 있는 성의 전체 이름이 접은 문맥에 낱말로 있으면 `fullname`.
- `sources.yaml` 두 줄을 고치고, `scope_name_extras` 주석에 「Gabi · Ezri = 2주 수집 검토 (2026-11-15)」 를 덧붙인다.
- 모듈 독스트링의 갈래 설명에 `report` · `fullname` 을 더한다.

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project . --extra dev pytest tests/test_scope.py -q`
Expected: 모두 PASS (`test_press_titles_measured_on_2026_10_06` 숫자 그대로)

- [ ] **Step 5: 커밋한다**

```bash
git -C . add src/bullet_in/scope.py config/sources.yaml tests/test_scope.py
git -C . commit -m "<type>(collect): …"   # 컨벤션 §1 · 본문 · Refs · 트레일러
```

### Task 2: 어댑터가 문맥과 주소 규칙을 쓰게 하기

**Files:**
- Modify: `src/bullet_in/adapters/factory.py` (`scope_rules` 가 `confirm` 지도를 만듦 · `html` 갈래에 `scope_url_contains` 전달)
- Modify: `src/bullet_in/adapters/rss.py` (판정에 피드 요약을 문맥으로)
- Modify: `src/bullet_in/adapters/arsenal_api.py` (`_accept` 가 본문을 문맥으로)
- Modify: `src/bullet_in/adapters/html.py` (주소 규칙 · 성만 쓴 제목은 상세 페이지를 먼저 받아 판정 · 받은 결과 재사용)
- Modify: `config/sources.yaml` (Guardian `scope_url_contains: ["-match-report"]`)
- Test: `tests/test_adapter_factory.py` · `tests/test_rss_adapter.py` · `tests/test_arsenal_api_adapter.py` · `tests/test_html_adapter.py`

**Interfaces:**
- Consumes: `ScopeRule.match(title, context=None)` · `ScopeRule.needs_context(title)` · `ScopeRule.confirm` (Task 1)
- Produces: `scope_rules(cfg, roster)` 의 두 규칙 모두 `confirm = {성: 전체 이름}` (명단 중 성이 `scope_name_full_only` 에 든 사람) · `HtmlAdapter(..., scope_url_contains: Sequence[str] = ())` · `HtmlAdapter.scope_url_contains: tuple[str, ...]`

- [ ] **Step 1: 실패하는 시험을 쓴다**

`tests/test_adapter_factory.py`:

```python
def test_factory_builds_confirm_map_and_guardian_url_rule():
    cfg = {"scope_name_full_only": ["White"],
           "sources": [{"source_id": "guardian", "adapter": "html",
                        "config": {"list_url": "https://g.test", "item_selector": "a",
                                   "title_scope": True,
                                   "scope_url_contains": ["-match-report"]}}]}
    [a] = build_adapters(cfg, scope_roster=[("Ben White", "White"), ("Bukayo Saka", "Saka")])
    assert a.scope_url_contains == ("-match-report",)
    assert a.scope.confirm == {"White": "Ben White"}


def test_real_config_sets_url_rule_only_for_guardian():
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    rules = {s["source_id"]: s.get("config", {}).get("scope_url_contains") for s in cfg["sources"]}
    assert rules["guardian"] == ["-match-report"]
    assert [k for k, v in rules.items() if v] == ["guardian"]
```

`tests/test_rss_adapter.py`:

```python
from bullet_in.scope import ScopeRule

@respx.mock
def test_rss_confirms_surname_title_from_summary():
    items = ("<item><title>Tuchel defends White after more Wembley boos</title>"
             "<link>https://b.test/1</link>"
             "<description>England manager Thomas Tuchel defended Ben White.</description></item>"
             "<item><title>PSG could rival Arsenal for Gibbs-White</title>"
             "<link>https://b.test/2</link>"
             "<description>Morgan Gibbs-White is wanted.</description></item>")
    respx.get(FEED).mock(return_value=httpx.Response(200, content=_mini(items)))
    a = RssAdapter("bbc_sport", FEED, scope=ScopeRule([], set(), confirm={"White": "Ben White"}))
    out = asyncio.run(a.fetch())
    assert [i.url for i in out] == ["https://b.test/1"]
    assert a.funnel["passed_by"] == {"fullname": 1}
    assert a.funnel["dropped"] == ["PSG could rival Arsenal for Gibbs-White"]
```

`tests/test_arsenal_api_adapter.py` (기존 `_sitemap` · `_sitemap_entry` · `_gql_article` · `_mock_backend` 사용):

```python
@respx.mock
def test_scope_confirms_surname_from_body_and_takes_report_prefix():
    from bullet_in.scope import ScopeRule
    _mock_backend(_sitemap([_sitemap_entry("rice-aRICE0000001"),
                            _sitemap_entry("report-aREPT0000001"),
                            _sitemap_entry("rice-aRICE0000002")]), {
        "aRICE0000001": _gql_article("Rice – ‘This togetherness is unmatched’", ["Men", "News"],
                                     body_texts=("Declan Rice spoke after the win.",)),
        "aREPT0000001": _gql_article("Report: Liverpool 0-1 Arsenal", ["Men", "News"]),
        "aRICE0000002": _gql_article("Rice prices at the Emirates kiosk", ["Men", "News"],
                                     body_texts=("Food prices.",))})
    a = ArsenalApiAdapter("arsenal_official", window_hours=24 * 365,
                          scope=ScopeRule((), set(), confirm={"Rice": "Declan Rice"}))
    items = asyncio.run(a.fetch())
    assert [i.url.rsplit("-", 1)[1] for i in items] == ["aRICE0000001", "aREPT0000001", "aRICE0000002"]
```

(세 번째는 「Emirates」 팀 낱말로 받는다 · 전체 이름 확인이 다른 갈래를 막지 않는다는 확인)

`tests/test_html_adapter.py`:

```python
from bullet_in.scope import ScopeRule

LIST_G = ('<a class="t" href="/a" aria-label="‘We had to dig in’ … says Rice">x</a>'
          '<a class="t" href="/b" aria-label="Rice prices soar">y</a>'
          '<a class="t" href="/c" aria-label="Rice back in training">z</a>')

@respx.mock
def test_html_confirms_surname_title_from_detail_body_once():
    respx.get("https://g.test/arsenal").mock(return_value=httpx.Response(200, text=LIST_G))
    ra = respx.get("https://g.test/a").mock(return_value=httpx.Response(
        200, text='<div class="body">Declan Rice said the team dug in.</div>'))
    respx.get("https://g.test/b").mock(return_value=httpx.Response(
        200, text='<div class="body">Rice prices soar.</div>'))
    respx.get("https://g.test/c").mock(return_value=httpx.Response(503))
    a = HtmlAdapter("guardian", "https://g.test/arsenal", "a.t", "https://g.test",
                    body_selector="div.body", title_attr="aria-label",
                    scope=ScopeRule([], set(), confirm={"Rice": "Declan Rice"}))
    out = asyncio.run(a.fetch())
    assert [i.url for i in out] == ["https://g.test/a"]
    assert ra.call_count == 1
    assert out[0].raw_payload["body"].startswith("Declan Rice")
    assert a.funnel["passed_by"] == {"fullname": 1}
    assert sorted(a.funnel["dropped"]) == ["Rice back in training", "Rice prices soar"]
    assert a.funnel["passed"] == 1


@respx.mock
def test_html_url_rule_takes_match_report_but_not_live_blog():
    lst = ('<a class="t" href="/football/2026/oct/27/fleetwood-arsenal-match-report" '
           'aria-label="Fantastic Fleetwood seal shootout success">x</a>'
           '<a class="t" href="/football/live/2026/nov/01/liverpool-v-arsenal-live" '
           'aria-label="Liverpool 0-1 Arsenal – as it happened">y</a>')
    respx.get("https://g.test/arsenal").mock(return_value=httpx.Response(200, text=lst))
    respx.get("https://g.test/football/2026/oct/27/fleetwood-arsenal-match-report").mock(
        return_value=httpx.Response(200, text='<div class="body">Report.</div>'))
    a = HtmlAdapter("guardian", "https://g.test/arsenal", "a.t", "https://g.test",
                    body_selector="div.body", title_attr="aria-label",
                    scope=ScopeRule([], set()), scope_url_contains=["-match-report"])
    out = asyncio.run(a.fetch())
    assert [i.url.rsplit("/", 1)[1] for i in out] == ["fleetwood-arsenal-match-report"]
    assert a.funnel["passed_by"] == {"report": 1}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project . --extra dev pytest tests/test_adapter_factory.py tests/test_rss_adapter.py tests/test_arsenal_api_adapter.py tests/test_html_adapter.py -q`
Expected: 새 시험 6개 FAIL · 기존 시험 PASS

- [ ] **Step 3: 구현한다**

- `factory.scope_rules` — 명단에서 성이 `scope_name_full_only` 에 든 사람으로 `confirm = {sur: full}` 을 만들어 두 규칙 모두에 넘긴다 · `html` 갈래에 `scope_url_contains=c.get("scope_url_contains") or ()` 를 넘긴다.
- `rss.py` — `self.scope.match(title, context=e.get("summary") or "")`.
- `arsenal_api._accept` — `scope.match(title, context=_body_payload(article.get("articleBody") or [])["body"])`.
- `html.py` — 생성자에 `scope_url_contains` (튜플로 저장) · 루프에서 `scope.match(title)` 이 비면 주소에 패턴이 있으면 `report` · 그래도 비고 `needs_context(title)` 이고 `body_selector` 가 있으면 기록을 미루고 보류 목록에 둔다 · 루프 뒤 보류마다 `fetch_article_detail` 로 받은 본문으로 `match(title, context=body)` 를 다시 불러 `record` · 받으면 그 상세 결과를 붙여 두고 적재 단계에서 다시 받지 않는다 · `funnel["passed"]` 는 실제로 받은 수.
- `sources.yaml` Guardian `config` 에 `scope_url_contains: ["-match-report"]   # 경기 리포트 (2주 수집 검토 2026-11-15 · 제목에 표지 없음)`.

- [ ] **Step 4: 통과와 전체 시험을 확인한다**

Run: `uv run --project . --extra dev pytest -q`
Expected: 1,982 통과 · 89 skip (기준 1,971 + 새 시험 11)

- [ ] **Step 5: 커밋한다**

```bash
git -C . add src/bullet_in/adapters/factory.py src/bullet_in/adapters/rss.py src/bullet_in/adapters/arsenal_api.py src/bullet_in/adapters/html.py config/sources.yaml tests/test_adapter_factory.py tests/test_rss_adapter.py tests/test_arsenal_api_adapter.py tests/test_html_adapter.py
git -C . commit -m "<type>(collect): …"   # 컨벤션 §1 · 본문 · Refs · 트레일러
```

### Task 3: 배포 확인 (머지 뒤 · 세션이 한다)

**Files:**
- 바꾸는 파일 없음 · 확인 대상 `pipeline_runs.fetch_detail` (`funnels.<소스>.passed_by` 의 `report` · `fullname`) · 갈래 이름의 출처 `src/bullet_in/scope.py`

- [ ] **Step 1: 머지 뒤 첫 실행이 새 커밋을 내려받았는지 본다** — VM `git log --oneline -1` · judge 「반영 완료」
- [ ] **Step 2: 다음 경기 뒤 실행에서 Arsenal.com 「Report:」 · 「Preview:」 가 `passed_by.scope` 로 들어오는지 · Guardian 리포트가 `report` 로 들어오는지 본다**
- [ ] **Step 3: 일주일 뒤 버린 제목을 다시 읽어 새 오탐이 있는지 본다** (`funnels.<소스>.dropped` 와 받은 제목)
