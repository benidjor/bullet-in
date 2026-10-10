# 비수기 수집 범위 확대 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 언론사 세 소스 (BBC Sport · Sky Sports · The Guardian) 와 공식 소스 (Arsenal.com) 가 이적 기사에 더해 선수 · 팀 소식과 경기 평점을 받게 하고, 홈 대표 자리는 「이적 우선」 으로 고른다.

**Architecture:** 판정은 새 모듈 `bullet_in/scope.py` 한 곳에 둔다 (갈래 넷 · 처음 맞은 갈래를 돌려줌).
`build_adapters` 가 명단 이름으로 판정 규칙 둘 (언론사용 · 공식 소스용) 을 만들어, 설정에 `title_scope: true` 가 있는 소스의 어댑터에 넘긴다.
어댑터는 받은 갈래 수 (`passed_by`) 와 버린 제목 (`dropped`) 을 기존 수집 단계 기록 (`funnel`) 에 남긴다.
공식 소스의 새 채택 경로 `scope` 는 이적 단계 규칙에서 「오피셜」 고정을 받지 않는다.

**Tech Stack:** Python 3.11 · httpx · feedparser · BeautifulSoup · respx (테스트) · pytest · MariaDB 11 (통합 테스트)

**Spec:** `docs/superpowers/specs/2026-10-07-offseason-collection-scope-design.md`

**Dry run:** 2026-10-07 에 이 계획서의 코드 블록을 워크트리에 그대로 적용해 전체 테스트를 돌렸고 (1,942 통과 · 1 skip · 새 테스트 28 = 작업 1 의 8 · 작업 2 의 11 · 작업 3 의 6 · 작업 4 의 3) 되돌렸다.
dry run 은 「도는가」 만 본다.
값이 맞는지는 작업 리뷰가 본다.

## 작업 원칙 (Karpathy 4원칙 · CLAUDE.md 「행동 가이드라인」)

구현 · 리뷰 서브에이전트는 CLAUDE.md 의 4원칙을 지킨다.
특히 아래 둘은 이 계획에서 리뷰가 Important 로 다룬다.

- **요청 밖 변경 금지** — 작업의 Files 목록 밖 파일을 고치거나, 리뷰의 Minor 를 근거로 설계에 없는 동작을 더하지 않는다. 넣을 만하면 보고만 하고 사용자가 정한다.
- **근거 없는 단정 금지** — 보고 · 커밋 · 주석의 숫자와 사실은 실행한 명령이나 읽은 파일에 닿아야 한다. 닿지 않으면 「추정」 이라고 쓴다.

## 가정과 확인

| 가정 | 확인 방법 · 결과 |
| --- | --- |
| 언론사 세 소스의 목록은 아스날 페이지다 | `config/sources.yaml` 의 `feed_url` · `list_url` (BBC 아스날 RSS · Sky `/arsenal` · Guardian `/football/arsenal`) · **대체로 맞음** · 2026-10-06 실측 목록에 리그 전반 글 (「10 talking points」 · 「November fixtures」) 이 섞여 있었다 |
| 명단 이름 재료는 41명 (1군 40 · 감독 1) | 운영 DB `players` 조회 2026-10-06 · 픽스처 `roster` 41쌍 |
| 판정 결과 (BBC 15 · Sky 7 · Guardian 9 · 공식 10) | 2026-10-06 실측 제목에 규칙을 돌린 값 · 작업 1 · 3 의 테스트가 고정 |
| 공식 소스 `title` 이 아닌 경로는 「오피셜」 로 고정된다 | `transfer_stage.rule_stage` 를 읽음 · 그래서 `scope` 를 고정에서 뺀다 (작업 3) |
| SLO-5 · SLO-6 에 영향이 없다 | `quality.responded` (키워드 통과 수를 안 봄) · `quality.volume_anomalies` 의 `min_baseline=3.0` 을 읽음 |
| 공식 소스 제외 태그 10개로 홍보성 글이 걸러진다 | 최근 7일 29건에서만 확인 · **표본 한정 · 추정** · 배포 뒤 `dropped` · `passed_by` 로 다시 본다 |
| 번역량이 하루 2 ~ 3건 는다 | **추정** · 목록이 덮는 기간이 소스마다 다르다 · 배포 뒤 소스별 새 기사 수로 잰다 |

## 더 단순한 꼴과 버린 이유

| 더 단순한 꼴 | 버린 이유 |
| --- | --- |
| 명단 없이 키워드 목록만 늘리기 | 늘어나는 기사의 대부분이 이름 갈래다 (실측 BBC 7 · Sky 4 · Guardian 6) · 이름은 낱말 목록으로 대신할 수 없다 |
| 공식 소스도 언론사와 같은 규칙 하나 | 「Raya talks …」 가 이적 키워드 (`talks`) 에 먼저 걸려 `scope` 로 받히지 않는다 · 규칙 둘이 필요하다 |
| 기록 (`passed_by` · `dropped`) 없이 배포 | 설계 §5 의 「LLM 보조가 필요한가」 를 잴 재료가 없어진다 · 사용자 결정 (2026-10-06) |

## Global Constraints

- 파이썬은 워크트리의 3.11 가상환경으로 돌린다 (`uv venv --python 3.11 --project .` 뒤 `uv run --project . --extra dev pytest`) · 전체 테스트는 워크트리 디렉터리에서 돌리고 수집 수를 먼저 본다 (기준 1,914 통과 + 1 skip · `origin/main` `78a6265`)
- 통합 테스트는 로컬 MariaDB (`docker compose up -d`) 가 있으면 돈다
- 갈래 이름은 `keyword` · `extra` · `name` · `team` (언론사) · 공식 소스 채택 경로는 `tag` · `title` · `scope` (설계 §2.1 · §3)
- 추가 낱말 `interest` · `ratings` · 팀 낱말 `Emirates` · `stadium` · `Pro Ref` · `referee` · `academy` · `injury` · `fitness` (설계 §2.1)
- 이적 키워드 갈래는 지금의 부분 일치 동작을 그대로 둔다 (`k in title.lower()`) · 나머지 셋은 낱말 단위 (`\b`) · 이름만 대소문자 구분
- 이름 재료 = `players` 의 `status='confirmed'` · `category IN ('squad','manager')` 의 `full_name` · `surname` + 설정 `scope_name_extras` (`Gabriel` · `Bruno` · `Ødegaard`) · `scope_name_full_only` (`White` · `Rice` · `Jesus` · `Timber` · `Salmon`) 은 성으로는 안 받고 전체 이름만 (설계 §2.2)
- 공식 소스 `scope` 경로 = 이름 · 추가 낱말 · 팀 낱말 가운데 하나 또는 `Internationals` 태그 · 제외 태그 10개 · 제외 제목 `Ask Me Anything` · 낱말 `AMA` · 이적 키워드 갈래는 쓰지 않는다 (설계 §3.2)
- `dropped` 는 소스당 최대 40개 · 제목당 120자 (설계 §5.1)
- 명단을 못 읽으면 이름 갈래만 빠지고 경고 로그 · 수집은 계속 (설계 §2.2)
- 커밋은 `benidjor <94089198+benidjor@users.noreply.github.com>` 신원 · 컨벤션 `docs/conventions/2026-06-11-commit-pr-convention.md` · 트레일러는 실행 방식이 정해지면 정한다
- 문서 (`docs/`) 는 컨벤션 §2.2 서식 · `docs/` 는 서술형 · README 는 존댓말 · 「급사」 · 「계수기」 금지 · 사용자가 읽는 새 문자열에 「회차」 대신 「실행」

## Review Focus

- **흔한 낱말과 겹치는 성이 소문자 일반 낱말 · 다른 고유명사로 나올 때** — 「rice」 · 「White Hart Lane」 은 받지 않고 「Declan Rice」 · 「Ben White」 는 받는다 (작업 1 의 `test_full_only_surnames_need_full_name`)
- **이름이 다른 낱말의 일부일 때** — 「Sakai」 는 `Saka` 로 잡히지 않는다 · 「Lewis-Skelly」 · 「Ødegaard」 처럼 하이픈 · 비ASCII 이름은 잡힌다 (작업 1 의 `test_names_match_whole_words_only`)
- **명단을 못 읽었을 때** — 예외가 수집을 멈추지 않고 이름 갈래만 빠진다 (작업 2 의 `test_scope_roster_or_none_logs_and_returns_none`)
- **공식 소스 기사가 이적 키워드 낱말을 담았을 때** — 「Raya talks all things goalkeeping with Seaman」 은 `talks` 가 아니라 이름으로 `scope` 경로가 된다 (작업 3 의 픽스처 테스트)
- **`scope` 경로 기사가 이적 완료로 판정될 때** — 「오피셜」 로 고정되지도, 올라가지도 않는다 (작업 3 의 `test_scope_path_is_never_official`)

## 알고 두는 한계 (고치지 않음)

- 수집 단계 칸과 알림의 「키워드 N」 라벨 (`ops_view._stage_text` · `notify._funnel_lines`) 은 이제 범위 통과 수를 뜻한다. 문구는 이 계획에서 바꾸지 않는다.
- 지금 키워드의 부분 일치 오탐 (`deal` → 「deal with」) 은 설계 §8 범위 밖이다.
- `publish` 와 `benchmark` 도 `build_adapters` 를 부르지만 수집을 하지 않거나 시간만 재므로 명단을 넘기지 않는다 (이름 갈래 없이 만들어진다).

---

### Task 1: 판정 모듈 `scope.py`

**Files:**
- Create: `src/bullet_in/scope.py`
- Test: `tests/test_scope.py`
- Use (이미 있음 · 계획 커밋에 포함): `tests/fixtures/scope_titles_2026-10-06.json` — 키 `roster` (`[full_name, surname]` 41쌍) · `press` (`bbc_sport` 24 · `skysports` 11 · `guardian` 20 제목) · `official` (29건 · `title` · `articleType` · `taxonomies`)

**Interfaces:**
- Produces: `scope_names(roster: Iterable[tuple[str, str]], extras: Iterable[str] = (), full_only: Iterable[str] = ()) -> set[str]`
- Produces: `class ScopeRule(keywords: Iterable[str] = (), names: Iterable[str] = ())` · 메서드 `match(title: str) -> str | None` (돌려주는 값 `"keyword"` · `"extra"` · `"name"` · `"team"` · `None`)
- Produces: `record(funnel: dict, title: str, reason: str | None) -> None` · 상수 `DROPPED_MAX = 40` · `DROPPED_CHARS = 120`

- [ ] **Step 1: 실패 테스트 쓰기** — `tests/test_scope.py`

```python
"""수집 범위 판정 — 갈래 넷과 2026-10-06 실측 제목 (설계 2026-10-07 §2)."""
import json
from pathlib import Path

import yaml

from bullet_in.scope import DROPPED_CHARS, DROPPED_MAX, ScopeRule, record, scope_names

FX = json.loads((Path(__file__).parent / "fixtures" / "scope_titles_2026-10-06.json").read_text())
KEYWORDS = yaml.safe_load(Path("config/sources.yaml").read_text())["transfer_keywords"]
EXTRAS = ["Gabriel", "Bruno", "Ødegaard"]
FULL_ONLY = ["White", "Rice", "Jesus", "Timber", "Salmon"]
NAMES = scope_names([tuple(r) for r in FX["roster"]], EXTRAS, FULL_ONLY)


def test_branches_in_order():
    rule = ScopeRule(["deal"], {"Saka"})
    assert rule.match("Arteta agrees new deal") == "keyword"
    assert rule.match("Saka signs a new deal") == "keyword"        # 처음 맞은 갈래 하나
    assert rule.match("Bournemouth to resist interest in Scott") == "extra"
    assert rule.match("Sunderland v Arsenal player ratings") == "extra"
    assert rule.match("Saka at the double for England") == "name"
    assert rule.match("Arsenal shelve plans for Emirates Stadium") == "team"
    assert rule.match("Arsenal demand meeting with Pro Ref") == "team"
    assert rule.match("Fans have their say!") is None


def test_full_only_surnames_need_full_name():
    rule = ScopeRule([], scope_names([("Declan Rice", "Rice"), ("Ben White", "White")],
                                     full_only=["Rice", "White"]))
    assert rule.match("Declan Rice scores again") == "name"
    assert rule.match("Ben White back in training") == "name"
    assert rule.match("Rice on target for England") is None
    assert rule.match("rice prices rise") is None
    assert rule.match("Spurs return to White Hart Lane") is None


def test_names_match_whole_words_only():
    rule = ScopeRule([], {"Saka", "Lewis-Skelly", "Ødegaard"})
    assert rule.match("Sakai joins Gamba Osaka") is None
    assert rule.match("Myles Lewis-Skelly nominated") == "name"
    assert rule.match("Ødegaard assists for Norway") == "name"
    assert rule.match("saka at the double") is None                 # 이름은 대소문자 구분


def test_extra_and_team_words_ignore_case():
    rule = ScopeRule([], set())
    assert rule.match("INJURY update") == "team"
    assert rule.match("Player Ratings") == "extra"
    assert rule.match("Interesting times") is None                  # 낱말 단위


def test_no_names_drops_only_the_name_branch():
    rule = ScopeRule(["deal"], set())
    assert rule.match("Saka at the double") is None
    assert rule.match("Arteta agrees new deal") == "keyword"


def test_scope_names_keeps_full_names_and_extras():
    names = scope_names([("Mikel Arteta", "Arteta"), ("Ben White", "White")],
                        extras=["Gabriel"], full_only=["White"])
    assert names == {"Mikel Arteta", "Arteta", "Ben White", "Gabriel"}


def test_record_counts_passed_and_caps_dropped():
    f = {}
    record(f, "a", "name")
    record(f, "b", "name")
    record(f, "c", "keyword")
    for i in range(DROPPED_MAX + 5):
        record(f, "x" * (DROPPED_CHARS + 30), None)
    assert f["passed_by"] == {"name": 2, "keyword": 1}
    assert len(f["dropped"]) == DROPPED_MAX
    assert all(len(t) == DROPPED_CHARS for t in f["dropped"])


def _split(titles, rule):
    out = {}
    for t in titles:
        r = rule.match(t)
        if r:
            out[r] = out.get(r, 0) + 1
    return out


def test_press_titles_measured_on_2026_10_06():
    """설계 §2.3 의 결과표를 그대로 고정한다."""
    rule = ScopeRule(KEYWORDS, NAMES)
    assert _split(FX["press"]["bbc_sport"], rule) == {"keyword": 5, "extra": 2, "name": 7, "team": 1}
    assert _split(FX["press"]["skysports"], rule) == {"keyword": 3, "name": 4}
    assert _split(FX["press"]["guardian"], rule) == {"keyword": 1, "name": 6, "team": 2}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_scope.py -q`
Expected: `ModuleNotFoundError: No module named 'bullet_in.scope'`

- [ ] **Step 3: 구현** — `src/bullet_in/scope.py`

```python
"""수집 범위 판정 — 이적 + 선수 · 팀 소식 + 경기 평점 (설계 2026-10-07 §2).

언론사 세 소스와 공식 소스가 같은 판정을 쓴다. 갈래는 위에서 아래 순서로 보고
처음 맞은 하나를 돌려준다 — 기록 (`passed_by`) 으로 넓힌 갈래가 무엇을 가져왔는지
재기 위해서다. 이적 키워드 갈래는 종전 필터와 같은 부분 일치를 그대로 둔다
(바꾸면 지금 받는 기사가 줄어 범위 확대와 섞인다 · 설계 §2.1)."""
from __future__ import annotations

import re
from collections.abc import Iterable

EXTRA_WORDS = ("interest", "ratings")
TEAM_WORDS = ("Emirates", "stadium", "Pro Ref", "referee", "academy", "injury", "fitness")
DROPPED_MAX = 40
DROPPED_CHARS = 120


def _words(words: Iterable[str], flags: int = 0) -> re.Pattern | None:
    ws = sorted(set(words), key=len, reverse=True)       # 긴 이름 먼저 (Mikel Arteta > Arteta)
    if not ws:
        return None
    return re.compile(r"\b(?:" + "|".join(map(re.escape, ws)) + r")\b", flags)


_EXTRA_RE = _words(EXTRA_WORDS, re.IGNORECASE)
_TEAM_RE = _words(TEAM_WORDS, re.IGNORECASE)


def scope_names(roster: Iterable[tuple[str, str]], extras: Iterable[str] = (),
                full_only: Iterable[str] = ()) -> set[str]:
    """명단 (full_name, surname) → 판정에 쓸 이름 집합 (설계 §2.2).

    full_only 에 든 성은 흔한 낱말과 겹쳐 (「White Hart Lane」) 성으로는 안 받고
    전체 이름만 남긴다."""
    skip = set(full_only)
    out = set(extras)
    for full, sur in roster:
        if full:
            out.add(full)
        if sur and sur not in skip:
            out.add(sur)
    return out


class ScopeRule:
    """제목이 받을 범위인가 — 이적 키워드 · 추가 낱말 · 명단 이름 · 팀 낱말."""

    def __init__(self, keywords: Iterable[str] = (), names: Iterable[str] = ()):
        self.keywords = tuple(k.lower() for k in keywords)
        self._name_re = _words(names)                     # 이름만 대소문자를 가린다

    def match(self, title: str) -> str | None:
        if any(k in title.lower() for k in self.keywords):
            return "keyword"
        if _EXTRA_RE.search(title):
            return "extra"
        if self._name_re is not None and self._name_re.search(title):
            return "name"
        if _TEAM_RE.search(title):
            return "team"
        return None


def record(funnel: dict, title: str, reason: str | None) -> None:
    """수집 단계 기록에 받은 갈래 수와 버린 제목을 남긴다 (설계 §5.1)."""
    if reason:
        by = funnel.setdefault("passed_by", {})
        by[reason] = by.get(reason, 0) + 1
        return
    dropped = funnel.setdefault("dropped", [])
    if len(dropped) < DROPPED_MAX:
        dropped.append(title[:DROPPED_CHARS])
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_scope.py -q`
Expected: 8 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/scope.py tests/test_scope.py tests/fixtures/scope_titles_2026-10-06.json
git commit -m "feat(collect): 수집 범위 판정 모듈 — 이적 키워드 · 추가 낱말 · 명단 이름 · 팀 낱말"
```

(픽스처가 계획 커밋에 이미 들어가 있으면 `git add` 목록에서 빠져도 된다.)

---

### Task 2: 언론사 세 소스 · 명단 연결 · 설정 · README

**Files:**
- Modify: `src/bullet_in/adapters/html.py` (`__init__` 에 `scope` · 필터 자리 · `funnel` 주석)
- Modify: `src/bullet_in/adapters/rss.py` (같은 두 자리)
- Modify: `src/bullet_in/adapters/factory.py` (`scope_roster` 인자 · 판정 규칙 둘 · html · rss 에 넘김)
- Modify: `src/bullet_in/storage/players.py` (`scope_roster` 메서드)
- Modify: `src/bullet_in/run.py` (`scope_roster_or_none` · `collect` 배선)
- Modify: `config/sources.yaml` (최상위 설정 두 줄 · 세 소스에 `title_scope: true`)
- Modify: `README.md` §3.4 (126행 문장)
- Test: `tests/test_html_adapter.py` · `tests/test_rss_adapter.py` · `tests/test_adapter_factory.py` · `tests/test_run_stages.py` · `tests/integration/test_player_store.py` (각각 끝에 더함)

**Interfaces:**
- Consumes: 작업 1 의 `ScopeRule` · `scope_names` · `record`
- Produces: `build_adapters(cfg: dict, fmkorea_player_names: set[str] | None = None, scope_roster: list[tuple[str, str]] | None = None) -> list`
- Produces: `factory.scope_rules(cfg: dict, roster) -> tuple[ScopeRule, ScopeRule]` — (언론사용 · 공식 소스용) · 작업 3 이 공식 소스용을 쓴다
- Produces: `HtmlAdapter(..., scope: ScopeRule | None = None)` · `RssAdapter(..., scope: ScopeRule | None = None)` · `funnel` 에 `passed_by` · `dropped`
- Produces: `PlayerStore.scope_roster() -> list[tuple[str, str]]` · `run.scope_roster_or_none(pstore) -> list[tuple[str, str]] | None`

- [ ] **Step 1: 실패 테스트 쓰기**

`tests/test_html_adapter.py` 끝에:

```python
from bullet_in.scope import ScopeRule


@respx.mock
def test_html_adapter_scope_records_passed_by_and_dropped():
    html = ('<a class="i" href="/1">Arteta agrees new deal</a>'
            '<a class="i" href="/2">Saka returns from injury</a>'
            '<a class="i" href="/3">Fans have their say</a>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter("x", "https://a.test/news", "a.i", scope=ScopeRule(["deal"], {"Saka"}))
    items = asyncio.run(a.fetch())
    assert [i.raw_payload["title"] for i in items] == ["Arteta agrees new deal",
                                                       "Saka returns from injury"]
    assert a.funnel["passed"] == 2
    assert a.funnel["passed_by"] == {"keyword": 1, "name": 1}
    assert a.funnel["dropped"] == ["Fans have their say"]


@respx.mock
def test_html_adapter_without_scope_keeps_keyword_filter():
    html = '<a class="i" href="/1">Arteta agrees new deal</a><a class="i" href="/2">Saka returns</a>'
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter("x", "https://a.test/news", "a.i", title_contains=["deal"])
    items = asyncio.run(a.fetch())
    assert [i.raw_payload["title"] for i in items] == ["Arteta agrees new deal"]
    assert "passed_by" not in a.funnel and "dropped" not in a.funnel
```

`tests/test_rss_adapter.py` 끝에:

```python
from bullet_in.scope import ScopeRule


@respx.mock
def test_rss_scope_records_passed_by_and_dropped():
    items = ("<item><title>Arteta agrees new deal</title><link>https://b.test/1</link></item>"
             "<item><title>Guimaraes and Raya crucial - player ratings</title>"
             "<link>https://b.test/2</link></item>"
             "<item><title>Is it a two-team title race?</title><link>https://b.test/3</link></item>")
    respx.get(FEED).mock(return_value=httpx.Response(200, content=_mini(items)))
    a = RssAdapter("bbc_sport", FEED, scope=ScopeRule(["deal"], {"Raya"}))
    out = asyncio.run(a.fetch())
    assert [i.raw_payload["title"] for i in out] == [
        "Arteta agrees new deal", "Guimaraes and Raya crucial - player ratings"]
    assert a.funnel["passed"] == 2
    assert a.funnel["passed_by"] == {"keyword": 1, "extra": 1}
    assert a.funnel["dropped"] == ["Is it a two-team title race?"]
```

`tests/test_adapter_factory.py` 끝에:

```python
from bullet_in.adapters.factory import scope_rules

ROSTER = [("Declan Rice", "Rice"), ("Bukayo Saka", "Saka")]


def _scope_cfg(title_scope: bool):
    conf = {"list_url": "https://a.test/l", "item_selector": "a", "title_contains": ["deal"]}
    if title_scope:
        conf["title_scope"] = True
    return {"transfer_keywords": ["deal"], "scope_name_extras": ["Gabriel"],
            "scope_name_full_only": ["Rice"],
            "sources": [{"source_id": "s", "adapter": "html", "config": conf}]}


def test_title_scope_source_gets_press_rule_with_roster_names():
    a = build_adapters(_scope_cfg(True), scope_roster=ROSTER)[0]
    assert a.scope.match("Saka at the double") == "name"
    assert a.scope.match("Gabriel heads in") == "name"
    assert a.scope.match("Declan Rice scores") == "name"
    assert a.scope.match("Rice scores") is None
    assert a.scope.match("Arteta agrees new deal") == "keyword"


def test_source_without_title_scope_keeps_keyword_filter():
    a = build_adapters(_scope_cfg(False), scope_roster=ROSTER)[0]
    assert a.scope is None
    assert a.title_keywords == ["deal"]


def test_scope_without_roster_drops_only_names():
    a = build_adapters(_scope_cfg(True))[0]
    assert a.scope.match("Saka at the double") is None
    assert a.scope.match("Arteta agrees new deal") == "keyword"


def test_scope_rules_official_rule_has_no_keywords():
    press, official = scope_rules(_scope_cfg(True), ROSTER)
    assert press.match("Saka talks a deal") == "keyword"
    assert official.match("Saka talks a deal") == "name"     # 이적 키워드 갈래 없음
    assert official.match("Arteta agrees new deal") is None


def test_sources_yaml_scope_settings():
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    assert cfg["scope_name_extras"] == ["Gabriel", "Bruno", "Ødegaard"]
    assert cfg["scope_name_full_only"] == ["White", "Rice", "Jesus", "Timber", "Salmon"]
    scoped = sorted(s["source_id"] for s in cfg["sources"]
                    if (s.get("config") or {}).get("title_scope"))
    assert scoped == ["bbc_sport", "guardian", "skysports"]
```

`tests/test_run_stages.py` 끝에:

```python
import logging

from bullet_in.run import scope_roster_or_none


class _Store:
    def __init__(self, rows=None, boom=False):
        self.rows, self.boom = rows or [], boom

    def scope_roster(self):
        if self.boom:
            raise RuntimeError("db down")
        return self.rows


def test_scope_roster_or_none_returns_rows():
    assert scope_roster_or_none(_Store([("Bukayo Saka", "Saka")])) == [("Bukayo Saka", "Saka")]


def test_scope_roster_or_none_logs_and_returns_none(caplog):
    with caplog.at_level(logging.WARNING):
        assert scope_roster_or_none(_Store(boom=True)) is None
    assert any("이름 갈래" in r.message for r in caplog.records)
```

`tests/integration/test_player_store.py` 끝에:

```python
def test_scope_roster_is_confirmed_squad_and_manager_only(engine):
    from datetime import datetime
    from sqlalchemy import text
    from bullet_in.storage.players import PlayerStore
    rows = [{"id": 9001, "fn": "Scope Squadman", "sn": "Squadman", "cat": "squad", "st": "confirmed"},
            {"id": 9002, "fn": "Scope Bossman", "sn": "Bossman", "cat": "manager", "st": "confirmed"},
            {"id": 9003, "fn": "Scope Outsider", "sn": "Outsider", "cat": "external", "st": "confirmed"},
            {"id": 9004, "fn": "Scope Prospect", "sn": "Prospect", "cat": "squad", "st": "candidate"}]
    with engine.begin() as c:
        c.execute(text("DELETE FROM players WHERE id BETWEEN 9001 AND 9004"))
        c.execute(text(
            "INSERT INTO players (id,full_name,surname,category,status,transfer_status,origin,added_at) "
            "VALUES (:id,:fn,:sn,:cat,:st,'none','seed',:at)"),
            [dict(r, at=datetime(2026, 10, 1)) for r in rows])
    try:
        got = PlayerStore(engine).scope_roster()
        assert ("Scope Squadman", "Squadman") in got and ("Scope Bossman", "Bossman") in got
        assert ("Scope Outsider", "Outsider") not in got and ("Scope Prospect", "Prospect") not in got
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM players WHERE id BETWEEN 9001 AND 9004"))
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_html_adapter.py tests/test_rss_adapter.py tests/test_adapter_factory.py tests/test_run_stages.py tests/integration/test_player_store.py -q`
Expected: 새 테스트가 `TypeError: ... unexpected keyword argument 'scope'` · `ImportError` (`scope_rules` · `scope_roster_or_none`) · `AttributeError` (`scope_roster`) · 설정 테스트 `KeyError` 로 FAIL

- [ ] **Step 3: 구현 — 어댑터 둘**

`src/bullet_in/adapters/html.py` 위쪽 import 에 더한다:

```python
from bullet_in.scope import ScopeRule, record
```

`__init__` 서명 끝에 `scope: ScopeRule | None = None` 를 더하고 (`title_attr` 뒤), 본문에 한 줄:

```python
        self.scope = scope   # 수집 범위 판정 (설계 2026-10-07 §2) — 있으면 키워드 필터를 대신한다
```

`self.funnel: dict[str, int] = {}` 를 `self.funnel: dict = {}` 로 바꾼다 (`passed_by` · `dropped` 가 정수가 아니다).

`fetch` 의 키워드 필터

```python
                self.funnel["titled"] += 1
                if self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
```

를 이렇게 바꾼다:

```python
                self.funnel["titled"] += 1
                if self.scope is not None:
                    reason = self.scope.match(title)
                    record(self.funnel, title, reason)
                    if reason is None:
                        continue
                elif self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
```

`src/bullet_in/adapters/rss.py` 도 같다.
import 에 `from bullet_in.scope import ScopeRule, record` 를 더하고, `__init__` 서명 끝 (`body_selector` 뒤) 에 `scope: ScopeRule | None = None`, 본문에 `self.scope = scope` (같은 주석).
`fetch` 의

```python
                if self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
```

를

```python
                if self.scope is not None:
                    reason = self.scope.match(title)
                    record(funnel, title, reason)
                    if reason is None:
                        continue
                elif self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
```

로 바꾼다 (RSS 는 지역 변수 `funnel` 에 쌓고 끝에서 `self.funnel = funnel` 로 옮긴다).

- [ ] **Step 4: 구현 — 공장 · 명단 · 배선**

`src/bullet_in/adapters/factory.py` import 에 `from bullet_in.scope import ScopeRule, scope_names` 를 더하고, `build_adapters` 앞에 함수를 둔다:

```python
def scope_rules(cfg: dict, roster) -> tuple[ScopeRule, ScopeRule]:
    """(언론사용, 공식 소스용) 수집 범위 판정 규칙 (설계 2026-10-07 §2 · §3.2).

    공식 소스는 이적 낱말을 이미 자기 경로 (`tag` · `title`) 로 보므로 키워드 갈래를
    빼고 이름 · 추가 낱말 · 팀 낱말만 쓴다. 명단이 없으면 이름 갈래만 빠진다."""
    names = (scope_names(roster, cfg.get("scope_name_extras") or (),
                         cfg.get("scope_name_full_only") or ()) if roster else set())
    return ScopeRule(cfg.get("transfer_keywords") or (), names), ScopeRule((), names)
```

`build_adapters` 서명을

```python
def build_adapters(cfg: dict, fmkorea_player_names: set[str] | None = None,
                   scope_roster: list[tuple[str, str]] | None = None) -> list:
    press_scope, official_scope = scope_rules(cfg, scope_roster)
    out = []
```

로 바꾸고 (`official_scope` 는 작업 3 이 쓴다 · 그 전까지 쓰이지 않는 변수로 남는다), rss · html 생성 호출에 인자 하나씩 더한다:

```python
            out.append(RssAdapter(sid, c["feed_url"],
                                  title_contains=c.get("title_contains"),
                                  body_selector=c.get("body_selector"),
                                  scope=press_scope if c.get("title_scope") else None))
```

```python
            out.append(HtmlAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url"),
                                   title_contains=c.get("title_contains"),
                                   body_selector=c.get("body_selector"),
                                   title_selector=c.get("title_selector"),
                                   thumbnail_only=c.get("thumbnail_only", False),
                                   title_attr=c.get("title_attr"),
                                   scope=press_scope if c.get("title_scope") else None))
```

`src/bullet_in/storage/players.py` 의 `confirmed_ko_names` 바로 뒤에:

```python
    def scope_roster(self) -> list[tuple[str, str]]:
        """수집 범위 판정의 이름 재료 (설계 2026-10-07 §2.2) — 확정 1군 선수 · 감독."""
        with self.engine.connect() as c:
            return [(r[0], r[1]) for r in c.execute(text(
                "SELECT full_name, surname FROM players WHERE status='confirmed' "
                "AND category IN ('squad','manager') ORDER BY id")).all()]
```

`src/bullet_in/run.py` 의 `adapter_funnels` 바로 앞에:

```python
def scope_roster_or_none(pstore) -> list[tuple[str, str]] | None:
    """수집 범위 판정의 명단 — 못 읽으면 이름 갈래만 빠지고 수집은 계속한다 (설계 2026-10-07 §2.2)."""
    try:
        return pstore.scope_roster()
    except Exception:
        logging.getLogger(__name__).warning(
            "명단을 못 읽어 수집 범위 판정에서 이름 갈래를 뺌 (수집은 계속)", exc_info=True)
        return None
```

`collect` 의

```python
    adapters = build_adapters(cfg, fmkorea_player_names=pstore.confirmed_ko_names())
```

를 (`collect` 안의 것만 · `publish` 의 같은 줄은 그대로)

```python
    adapters = build_adapters(cfg, fmkorea_player_names=pstore.confirmed_ko_names(),
                              scope_roster=scope_roster_or_none(pstore))
```

로 바꾼다.

- [ ] **Step 5: 구현 — 설정 · README**

`config/sources.yaml` 의 `transfer_keywords:` 줄 바로 아래에:

```yaml
# 수집 범위 판정의 이름 재료 (설계 2026-10-07 §2.2) — 명단 (players) 에 별칭 칸이 없어 여기에 둔다
scope_name_extras: ["Gabriel", "Bruno", "Ødegaard"]
# 성만으로는 인정하지 않는 이름 — 흔한 낱말 · 다른 고유명사와 겹친다 (「White Hart Lane」)
scope_name_full_only: ["White", "Rice", "Jesus", "Timber", "Salmon"]
```

`bbc_sport` · `skysports` · `guardian` 세 소스의 `config:` 안, `title_contains: *transfer_kw` 바로 아래에 한 줄씩:

```yaml
      title_scope: true   # 이적 + 선수 · 팀 소식 + 경기 평점 (설계 2026-10-07 §2)
```

`README.md` 126행

```
언론 5종은 공통 이적 키워드 필터를 공유합니다 (`config/sources.yaml`).
```

을

```
언론 5종은 공통 이적 키워드 필터를 공유합니다 (`config/sources.yaml`).
그중 수집 중인 3종 (BBC Sport · Sky Sports · The Guardian) 은 명단의 선수 · 감독 이름과 팀 낱말로 선수 · 팀 소식과 경기 평점까지 받습니다 (2026-10 개정).
```

로 바꾼다.

- [ ] **Step 6: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_html_adapter.py tests/test_rss_adapter.py tests/test_adapter_factory.py tests/test_run_stages.py tests/integration/test_player_store.py tests/test_scope.py -q`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/adapters/html.py src/bullet_in/adapters/rss.py src/bullet_in/adapters/factory.py \
        src/bullet_in/storage/players.py src/bullet_in/run.py config/sources.yaml README.md \
        tests/test_html_adapter.py tests/test_rss_adapter.py tests/test_adapter_factory.py \
        tests/test_run_stages.py tests/integration/test_player_store.py
git commit -m "feat(collect): 언론사 세 소스가 명단 이름과 팀 낱말로 선수 · 팀 소식까지 받음"
```

---

### Task 3: 공식 소스 `scope` 경로 · 이적 단계 규칙 · 개정 안내

**Files:**
- Modify: `src/bullet_in/adapters/arsenal_api.py` (import · 상수 셋 · `_accept` · `__init__` · `fetch` 의 기록)
- Modify: `src/bullet_in/adapters/factory.py` (`arsenal_api` 생성에 공식 소스용 규칙)
- Modify: `src/bullet_in/transfer_stage.py` (`rule_stage` 한 줄 · docstring)
- Modify: `config/sources.yaml` (`arsenal_official` 의 `config: {}` → `title_scope: true`)
- Modify: `docs/superpowers/specs/2026-08-12-arsenal-official-collection-revision-design.md` (끝에 §8 개정 안내)
- Modify: `README.md` 소스 표 Arsenal.com 행
- Test: `tests/test_arsenal_api_adapter.py` · `tests/test_transfer_stage.py` · `tests/test_adapter_factory.py` (끝에 더함 · 작업 2 의 설정 테스트 기대값 갱신)

**Interfaces:**
- Consumes: 작업 1 의 `ScopeRule` · `record` · 작업 2 의 `factory.scope_rules` 가 돌려주는 공식 소스용 규칙 (`official_scope`)
- Produces: `_accept(article: dict, scope: ScopeRule | None = None) -> str | None` (`"tag"` · `"title"` · `"scope"` · `None`) · `ArsenalApiAdapter(source_id, window_hours=WINDOW_HOURS, scope=None)` · `funnel` 에 `passed_by` (`tag` · `title` · `scope`) · `dropped` (1군 뉴스 중 비채택)

- [ ] **Step 1: 실패 테스트 쓰기**

`tests/test_arsenal_api_adapter.py` 끝에:

```python
# --- 수집 범위 확대 (설계 2026-10-07 §3) ---------------------------------------
from bullet_in.adapters.arsenal_api import _accept
from bullet_in.scope import ScopeRule, scope_names

SCOPE_FX = json.loads((Path(__file__).parent / "fixtures" / "scope_titles_2026-10-06.json").read_text())
OFFICIAL_RULE = ScopeRule((), scope_names([tuple(r) for r in SCOPE_FX["roster"]],
                                          ["Gabriel", "Bruno", "Ødegaard"],
                                          ["White", "Rice", "Jesus", "Timber", "Salmon"]))


def _art(title, tax, kind="News"):
    return {"title": title, "articleType": kind, "taxonomies": tax}


def test_official_titles_measured_on_2026_10_06():
    """설계 §3.4 — 1군 뉴스 29건 중 10건이 scope 경로로 채택된다."""
    got = [(a["title"], _accept(a, OFFICIAL_RULE)) for a in SCOPE_FX["official"]]
    accepted = [t for t, p in got if p]
    assert len(accepted) == 10
    assert {p for _, p in got if p} == {"scope"}
    assert "Raya talks all things goalkeeping with Seaman" in accepted      # talks 가 아니라 이름
    assert "Kai Havertz takes on Ask Me Anything" not in accepted
    assert "Mikel Merino stars in Colney Carpool!" not in accepted


def test_scope_path_needs_scope_rule_and_respects_exclusions():
    saka = _art("Saka at the double", ["Men", "News", "Internationals"])
    assert _accept(saka) is None                                   # 규칙이 없으면 종전 그대로
    assert _accept(saka, OFFICIAL_RULE) == "scope"
    assert _accept(_art("Gyokeres scores again", ["Men", "News", "Video"]), OFFICIAL_RULE) is None
    assert _accept(_art("William Saliba takes on AMA", ["Men", "News"]), OFFICIAL_RULE) is None
    assert _accept(_art("Scotland v Norway report", ["Men", "News", "Internationals"]),
                   OFFICIAL_RULE) == "scope"                       # 대표팀 태그만으로도
    assert _accept(_art("Saka at the double", ["Women", "News"]), OFFICIAL_RULE) is None


def test_tag_and_title_paths_win_over_scope():
    assert _accept(_art("Saka signs new deal", ["Men", "News", "Contract news"]),
                   OFFICIAL_RULE) == "tag"
    assert _accept(_art("Saka joins on loan", ["Men", "News"]), OFFICIAL_RULE) == "title"


@respx.mock
def test_fetch_records_passed_by_and_dropped_for_men_news():
    entries = [_sitemap_entry("saka-at-the-double-aSAKA0000001"),
               _sitemap_entry("ticket-information-aTICK0000001")]
    _mock_backend(_sitemap(entries), {
        "aSAKA0000001": _gql_article("Saka at the double", ["Men", "Internationals"]),
        "aTICK0000001": _gql_article("Disabled Supporters' Ticket Information", ["Men"])})
    a = ArsenalApiAdapter("arsenal_official", window_hours=24 * 365, scope=OFFICIAL_RULE)
    items = asyncio.run(a.fetch())
    assert [i.raw_payload["accept_path"] for i in items] == ["scope"]
    assert a.funnel["passed_by"] == {"scope": 1}
    assert a.funnel["dropped"] == ["Disabled Supporters' Ticket Information"]
    assert a.funnel["sitemap_attempts"] == 1                        # 사이트맵 기록은 그대로
```

파일 맨 위 import 에 `from pathlib import Path` 가 없으면 더한다.

`tests/test_transfer_stage.py` 끝에:

```python
def test_scope_path_is_never_official():
    """설계 2026-10-07 §3.3 — 대표팀 활약 기사에 오피셜이 붙지 않게."""
    assert ts.rule_stage("arsenal_official", "scope") == (None, None)
    assert ts.promote_official("done", "arsenal_official", "scope") == "done"
    assert ts.promote_official("done", "arsenal_official", "title") == "official"   # 종전 그대로
```

`tests/test_adapter_factory.py` 끝에:

```python
def test_official_source_gets_official_rule_when_title_scope():
    cfg = {"transfer_keywords": ["deal"], "sources": [
        {"source_id": "arsenal_official", "adapter": "arsenal_api", "config": {"title_scope": True}},
        {"source_id": "other_official", "adapter": "arsenal_api", "config": {}}]}
    on, off = build_adapters(cfg, scope_roster=[("Bukayo Saka", "Saka")])
    assert on.scope.match("Saka talks a deal") == "name"
    assert off.scope is None
```

같은 파일의 작업 2 테스트 `test_sources_yaml_scope_settings` 의 기대값을

```python
    assert scoped == ["arsenal_official", "bbc_sport", "guardian", "skysports"]
```

로 바꾼다.

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_arsenal_api_adapter.py tests/test_transfer_stage.py tests/test_adapter_factory.py -q`
Expected: 새 테스트가 `TypeError` (`_accept` 인자 · `scope`) · `AssertionError` (`rule_stage` 가 `("official", None)`) 로 FAIL

- [ ] **Step 3: 구현 — 어댑터**

`src/bullet_in/adapters/arsenal_api.py` import 에 더한다:

```python
from bullet_in.scope import ScopeRule, record
```

`ANY_TAXONOMIES = {...}` 바로 아래에:

```python
# 수집 범위 확대 (설계 2026-10-07 §3.2) — 1군 뉴스 중 이적 경로 밖의 선수 · 팀 소식.
# 제외는 사진 모음 · 영상 · 옛 경기 · 투표 · 다큐 · 선수 차 안 인터뷰 영상이고,
# 선수의 팬 질의응답 (AMA) 은 태그로 구별되지 않아 제목으로 거른다.
SCOPE_TAG = "Internationals"
EXCLUDE_TAGS = {"Compilation", "Photos", "Match gallery", "Video", "Full match",
                "From the vault", "Gamification", "Behind the Scenes", "3rd Party",
                "Colney Carpool"}
_EXCLUDE_TITLE_RE = re.compile(r"Ask Me Anything|\bAMA\b")
```

`_accept` 를 통째로 이렇게 바꾼다 (docstring 앞 두 단락은 지금 것을 그대로 두고 셋째 단락만 더한다):

```python
def _accept(article: dict, scope: ScopeRule | None = None) -> str | None:
    """채택 경로 — 'tag' (구단이 이적 태그를 붙임) · 'title' (제목 어휘) ·
    'scope' (선수 · 팀 소식) · None (비채택).

    구단이 이적 태그를 빠뜨린 발표가 실재해 (2026-08-05 뇌르고르) 제목 갈래를 둔다.
    두 경로를 구분해 두는 것은 단계 규칙이 태그 채택분에만 official 을 고정하기
    때문이다 (공홈 수집 개정 스펙 2026-08-12 §3.2 · §3.3).

    scope 는 규칙을 받았을 때만 본다 (설계 2026-10-07 §3.2) — 백필처럼 규칙 없이
    만든 어댑터는 종전 두 경로만 쓴다."""
    tax = set(article.get("taxonomies") or [])
    if article.get("articleType") != "News" or REQUIRED_TAXONOMY not in tax:
        return None
    if ANY_TAXONOMIES & tax:
        return "tag"
    title = article.get("title") or ""
    if TRANSFER_TITLE_RE.search(title):
        return "title"
    if scope is None or EXCLUDE_TAGS & tax or _EXCLUDE_TITLE_RE.search(title):
        return None
    if SCOPE_TAG in tax or scope.match(title):
        return "scope"
    return None
```

`ArsenalApiAdapter.__init__` 서명과 본문:

```python
    def __init__(self, source_id: str, window_hours: float = WINDOW_HOURS,
                 scope: ScopeRule | None = None):
        self.source_id = source_id
        self.window_hours = window_hours
        self.scope = scope   # 수집 범위 판정 (설계 2026-10-07 §3) — 없으면 종전 두 경로만
```

(나머지 속성 줄은 그대로.)

`fetch` 의

```python
                accept_path = _accept(art)
                if accept_path is None:
                    tax = art.get("taxonomies") or []
                    if art.get("articleType") == "News" and "Men" in tax:
                        self.men_news_rejects.append({
```

를

```python
                accept_path = _accept(art, self.scope)
                tax = art.get("taxonomies") or []
                if art.get("articleType") == "News" and "Men" in tax:
                    # 1군 뉴스만 기록한다 — 받은 경로 수와 버린 제목 (설계 2026-10-07 §5.1)
                    record(self.funnel, art.get("title") or "", accept_path)
                if accept_path is None:
                    if art.get("articleType") == "News" and "Men" in tax:
                        self.men_news_rejects.append({
```

로 바꾼다 (그 아래 `men_news_rejects` 딕셔너리 · `continue` 는 그대로).

- [ ] **Step 4: 구현 — 공장 · 단계 규칙 · 설정 · 문서**

`src/bullet_in/adapters/factory.py` 의

```python
        elif kind == "arsenal_api":
            out.append(ArsenalApiAdapter(sid))
```

를

```python
        elif kind == "arsenal_api":
            out.append(ArsenalApiAdapter(
                sid, scope=official_scope if c.get("title_scope") else None))
```

로 바꾼다.

`src/bullet_in/transfer_stage.py` `rule_stage` 의

```python
    if source_id == "arsenal_official":
        return (None, None) if accept_path == "title" else ("official", None)
```

를

```python
    if source_id == "arsenal_official":
        return (None, None) if accept_path in ("title", "scope") else ("official", None)
```

로 바꾸고, docstring 의 「고정에서 빠진 뒤 모델 판정을 받는 경로는 promote_official 이 잇는다.」 바로 앞에 한 줄을 더한다:

```
    'scope' (선수 · 팀 소식 · 설계 2026-10-07 §3.3) 도 고정하지 않는다 — 대표팀 활약 기사에
    오피셜이 붙지 않게. promote_official 은 'title' 에만 적용한다.
```

`config/sources.yaml` `arsenal_official` 의 `config: {}` 를

```yaml
    config:
      title_scope: true   # 1군 선수 · 팀 소식까지 (설계 2026-10-07 §3.2)
```

로 바꾼다.

`README.md` 소스 표의

```
| Arsenal.com | 0 | arsenal_api | 공식: 공홈 GraphQL API, taxonomy 필터 (이적 · 1군 재계약) |
```

를

```
| Arsenal.com | 0 | arsenal_api | 공식: 공홈 GraphQL API, taxonomy 필터 (이적 · 1군 재계약) · 2026-10 부터 1군 선수 · 팀 소식 (대표팀 · 수상 · 인터뷰) |
```

로 바꾼다.

`docs/superpowers/specs/2026-08-12-arsenal-official-collection-revision-design.md` 끝에 더한다:

```markdown

## 8. 2026-10-07 개정 안내 — 수집 범위 확대

1군 뉴스 가운데 이적 경로 (`tag` · `title`) 밖의 선수 · 팀 소식을 새 경로 `scope` 로 받는다.
`scope` 경로는 `rule_stage` 가 「오피셜」 로 고정하지 않고, `promote_official` 도 지금처럼 `title` 경로에만 적용한다.
조건과 제외 목록은 `docs/superpowers/specs/2026-10-07-offseason-collection-scope-design.md` §3 에 있다.
```

- [ ] **Step 5: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_arsenal_api_adapter.py tests/test_transfer_stage.py tests/test_adapter_factory.py tests/test_backfill_arsenal.py -q`
Expected: 전부 PASS
Run: `python3 .claude/hooks/check-doc-format.py docs/superpowers/specs/2026-08-12-arsenal-official-collection-revision-design.md`
Expected: 위반 없음

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/adapters/arsenal_api.py src/bullet_in/adapters/factory.py src/bullet_in/transfer_stage.py \
        config/sources.yaml README.md docs/superpowers/specs/2026-08-12-arsenal-official-collection-revision-design.md \
        tests/test_arsenal_api_adapter.py tests/test_transfer_stage.py tests/test_adapter_factory.py
git commit -m "feat(collect): 공식 소스가 1군 선수 · 팀 소식을 scope 경로로 받고 오피셜 고정에서 뺌"
```

---

### Task 4: 홈 대표 자리 「이적 우선」

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`top_story_key` 의 첫 원소)
- Test: `tests/test_serve_redesign.py` (끝에 더함)

**Interfaces:**
- Consumes: `transfer_stage.is_displayable(stage) -> bool` (이미 있음 · `other` · `None` 은 False)
- Produces: `top_story_key(row)` 의 첫 원소가 이적 단계 유무 (`pick_top_stories` 만 부른다)

- [ ] **Step 1: 실패 테스트 쓰기** — `tests/test_serve_redesign.py` 끝에

```python
def test_top_story_puts_transfer_first():
    """설계 2026-10-07 §4 — 이적 단계가 있는 기사가 대표 자리를 먼저 차지한다."""
    now = datetime(2026, 10, 7, 12, 0)
    injury = _row(content_hash="I", tier=0.0, title_ko="아스날, 사카 부상 복귀",
                  transfer_stage="other", published_at=datetime(2026, 10, 7, 9, 0),
                  fetched_at=datetime(2026, 10, 7, 9, 0))
    rumour = _row(content_hash="R", tier=1.5, title_ko="아스날, 요케레스 영입 관심",
                  transfer_stage="interest", published_at=datetime(2026, 10, 5, 9, 0),
                  fetched_at=datetime(2026, 10, 5, 9, 0))
    assert R.pick_top_stories([injury, rumour], now)["lead"]["content_hash"] == "R"


def test_top_story_fills_with_other_news_when_transfer_is_short():
    now = datetime(2026, 10, 7, 12, 0)
    rows = [_row(content_hash=f"O{h}", tier=0.0, transfer_stage="other",
                 published_at=datetime(2026, 10, 7, h), fetched_at=datetime(2026, 10, 7, h))
            for h in range(4)]
    rows.append(_row(content_hash="T", tier=1.5, transfer_stage="rumour",
                     published_at=datetime(2026, 10, 6), fetched_at=datetime(2026, 10, 6)))
    picks = R.pick_top_stories(rows, now)
    assert picks["lead"]["content_hash"] == "T"
    assert len(picks["mains"]) == 4                                  # 자리가 비지 않는다
    assert {m["content_hash"] for m in picks["mains"]} == {"O0", "O1", "O2", "O3"}


def test_top_story_unstaged_counts_as_other_news():
    now = datetime(2026, 10, 7, 12, 0)
    when = {"published_at": datetime(2026, 10, 6), "fetched_at": datetime(2026, 10, 6)}
    none_stage = _row(content_hash="N", tier=0.0, transfer_stage=None, **when)
    staged = _row(content_hash="S", tier=1.5, transfer_stage="negotiating", **when)
    assert R.pick_top_stories([none_stage, staged], now)["lead"]["content_hash"] == "S"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_serve_redesign.py -q`
Expected: 새 테스트 셋이 FAIL (지금은 공신력 0 인 「기타」 기사가 대표가 됨)

- [ ] **Step 3: 구현** — `src/bullet_in/serve/render.py` 의 `top_story_key`

```python
def top_story_key(row: dict) -> tuple:
    """정렬 키 (내림차순 = 우선). 이미지 유무는 신뢰도를 밀지 않게 최하위 (spec2 §5.1).

    맨 앞은 이적 단계 유무다 (설계 2026-10-07 §4 「이적 우선」) — 선수 · 팀 소식을 받기
    시작해도 이적 기사가 대표 자리를 먼저 차지하고, 모자라면 나머지가 채운다."""
    tier = row.get("tier")
    return (
        1 if _stage.is_displayable(row.get("transfer_stage")) else 0,
        1 if arsenal_subject(row) else 0,
        -float(tier) if tier is not None else -99.0,
        _LEAD_STAGE_RANK.get(row.get("transfer_stage") or "", 0),
        _sort_ts(row)[0],
        1 if row.get("image_url") else 0,
    )
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_serve_redesign.py tests/test_serve_render.py -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_redesign.py
git commit -m "feat(serve): 홈 대표 기사 · 주요 소식을 이적 우선으로 고름"
```

---

## 마무리 (컨트롤러가 직접)

- [ ] 전체 테스트 — 워크트리 디렉터리에서 `uv run --project . --extra dev pytest -q` · 기대 1,942 통과 + 1 skip (머리의 Dry run 줄 · `origin/main` 이 그사이 움직였으면 다시 잰다)
- [ ] 머지 전 라이브 확인 — 네 소스를 한 번씩 실제로 받아 `passed_by` · `dropped` 가 남는지 · 받은 수가 설계 §2.3 · §3.4 와 크게 어긋나지 않는지 (출력은 파일로 · 다시 돌리지 않는다)
- [ ] 최종 전체 리뷰 · PR (본문 humanize-korean fast 1회 → `check-pr-format.py` → 통과에 묶어 push · PR 생성)
- [ ] 머지 · 배포는 2026-10-07 18:00 KST 실행 뒤
- [ ] 배포 뒤 확인 (설계 §9.3) — 첫 실행 기록 · 첫 주 소스별 새 기사 수와 「오피셜」 오표기 · 2주 뒤 `dropped` 판단
