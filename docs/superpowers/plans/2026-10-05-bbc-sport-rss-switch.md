# BBC Sport RSS 전환 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BBC Sport 수집을 아스날 팀 페이지 (HTML) 에서 아스날 RSS 로 옮겨 SLO-5 끊김을 해소한다.

**Architecture:** RSS 어댑터를 httpx 로 받기 · 키워드 필터 · 목록 지문 · 수집 단계 기록 · 상세 받기로 키운다.
상세 받기는 HTML 어댑터에서 함수로 떼어 두 어댑터가 함께 쓴다.
SLO-5 응답 판정 · 화면 · 알림이 rss 수집 단계 기록을 읽게 하고, 설정 한 블록으로 전환한다.

**Tech Stack:** Python 3.11 · httpx · feedparser · BeautifulSoup · respx (테스트) · pytest

**Spec:** `docs/superpowers/specs/2026-10-05-bbc-sport-rss-switch-design.md`

## Global Constraints

- 파이썬은 워크트리의 3.11 가상환경으로 돌린다 (`.venv/bin/python -m pytest`) · 전체 테스트는 워크트리에서 돌리고 수집 수를 먼저 본다 (기준 1,870)
- 피드 · 상세 요청의 User-Agent 는 `bullet-in/0.1` · 시간 제한 20초 · `follow_redirects=True` (HTML 어댑터와 같음)
- 수집 단계 기록 키는 `entries` · `deduped` · `passed` · `list_sig` (설계 §2.1)
- 새 무응답 사유 이름은 `no_entries` (설계 §3.1)
- `bbc_sport` 의 목록 상한은 `list_unchanged_cap_hours: 240` (설계 §3.2)
- 주소 규칙에 더하는 추적 인자는 `at_medium` · `at_campaign` 두 이름뿐 (설계 §2.5)
- 키워드는 지금의 `transfer_keywords` 그대로 (`title_contains: *transfer_kw`)
- 커밋은 `benidjor <94089198+benidjor@users.noreply.github.com>` 신원 · 컨벤션 `docs/conventions/2026-06-11-commit-pr-convention.md` · 트레일러 `Co-authored-by: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`
- 문서 (`docs/` · README) 는 컨벤션 §2.2 서식 · `docs/` 는 서술형 · 「급사」 · 「계수기」 라는 말은 쓰지 않는다

## Review Focus

- **피드가 200 인데 XML 이 아닌 경우 (오류 안내 HTML 등)** — 예외 없이 항목 0개로 끝나고 SLO-5 가 `no_entries` 로 본다 (작업 3 · 4 의 테스트)
- **피드 항목에 제목이나 링크가 없는 경우** — 링크가 없으면 건너뛰고, 제목이 없으면 중복 제거 단계까지만 센다 (작업 3 의 테스트)
- **같은 링크가 피드에 두 번 나오는 경우** — 한 번만 남긴다 (작업 3 의 테스트)
- **상세 페이지가 HTTP 오류인 경우** — 제목과 피드 발행 시각은 남기고 본문만 비운다 (작업 3 의 테스트)
- **키워드에 걸리는 항목이 하나도 없는 경우** — 목록 지문은 여전히 모든 항목으로 만든다 (작업 3 의 테스트)

---

### Task 1: 상세 받기 함수를 HTML 어댑터에서 떼어 내기

**Files:**
- Create: `src/bullet_in/adapters/detail.py`
- Modify: `src/bullet_in/adapters/html.py:33-94`
- Test: `tests/test_detail.py`

**Interfaces:**
- Produces: `async def fetch_article_detail(client: httpx.AsyncClient, url: str, body_selector: str) -> dict` — 반환 키 `body` (항상) · `image_url` · `images` · `authors` · 있으면 `published` (ISO 문자열) · `published_precision` (`"time"` 또는 `"day"`) · HTTP 오류면 `{"body": ""}` 만

- [ ] **Step 1: 실패 테스트 쓰기** — `tests/test_detail.py`

```python
import asyncio, respx, httpx
from bullet_in.adapters.detail import fetch_article_detail

DETAIL = ('<html><head><meta property="og:image" content="https://img.test/g.jpg">'
          '<meta property="article:published_time" content="2026-09-22T11:48:23+00:00">'
          '</head><body><article><p>Arteta has agreed a new deal.</p></article></body></html>')


async def _run(url, selector):
    async with httpx.AsyncClient() as c:
        return await fetch_article_detail(c, url, selector)


@respx.mock
def test_fetch_article_detail_extracts_body_image_and_published():
    respx.get("https://a.test/x").mock(return_value=httpx.Response(200, text=DETAIL))
    got = asyncio.run(_run("https://a.test/x", "article"))
    assert got["body"] == "Arteta has agreed a new deal."
    assert got["image_url"] == "https://img.test/g.jpg"
    assert got["published"] == "2026-09-22T11:48:23+00:00"
    assert got["published_precision"] == "time"
    assert "authors" in got and "images" in got


@respx.mock
def test_fetch_article_detail_http_error_returns_empty_body_only():
    respx.get("https://a.test/x").mock(return_value=httpx.Response(500))
    assert asyncio.run(_run("https://a.test/x", "article")) == {"body": ""}
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_detail.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.adapters.detail'`

- [ ] **Step 3: 함수 만들기** — `src/bullet_in/adapters/detail.py`

```python
"""기사 상세 페이지에서 본문 · 이미지 · 저자 · 발행 시각을 뽑는다.

HTML 어댑터와 RSS 어댑터가 함께 쓴다 (설계 2026-10-05 §2.4).
BBC Sport 가 RSS 로 옮겨도 본문과 저자를 HTML 시절과 같은 코드로 읽어야
전담 기자 (Mokbel) 의 등급 승격이 그대로 유지된다."""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from bullet_in.adapters.meta import (extract_authors, extract_body_images,
                                     extract_og_image, extract_published_at)


async def fetch_article_detail(client: httpx.AsyncClient, url: str,
                               body_selector: str) -> dict:
    """상세 페이지 한 장 → payload 에 더할 값. HTTP 오류면 본문만 비운다 (다음 회차 재시도)."""
    try:
        rb = await client.get(url)
        rb.raise_for_status()
    except httpx.HTTPError:
        return {"body": ""}
    el = BeautifulSoup(rb.text, "html.parser").select_one(body_selector)
    out = {"body": el.get_text(" ", strip=True) if el else "",
           "image_url": extract_og_image(rb.text),
           "images": extract_body_images(rb.text, body_selector, base_url=url),
           "authors": extract_authors(rb.text)}
    pub = extract_published_at(rb.text)
    if pub:
        out["published"] = pub[0].isoformat()
        out["published_precision"] = pub[1]
    return out
```

- [ ] **Step 4: HTML 어댑터가 이 함수를 쓰게 바꾸기** — `src/bullet_in/adapters/html.py`

`fetch()` 첫 줄의 지역 import 를 썸네일 경로가 쓰는 둘만 남기고, 파일 머리에 `detail` 을 들인다.

```python
from bullet_in.adapters.detail import fetch_article_detail
```

```python
        from bullet_in.adapters.meta import extract_og_image, extract_published_at
```

`if self.body_selector:` 블록 (지금 80 ~ 94행) 전체를 아래 한 줄로 바꾼다.

```python
                if self.body_selector:
                    payload.update(await fetch_article_detail(c, url, self.body_selector))
```

- [ ] **Step 5: 새 테스트와 HTML 어댑터 기존 테스트 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_detail.py tests/test_html_adapter.py`
Expected: 전부 PASS (기존 HTML 테스트가 하나도 바뀌지 않은 채 통과해야 동작 불변)

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/adapters/detail.py src/bullet_in/adapters/html.py tests/test_detail.py
git commit -m "refactor(adapters): 기사 상세 받기를 함수로 떼어 HTML · RSS 어댑터가 함께 쓰게 함"
```

---

### Task 2: 주소 규칙에 BBC RSS 추적 인자

**Files:**
- Modify: `src/bullet_in/canonical.py:5-6`
- Test: `tests/test_canonical.py`

**Interfaces:**
- Produces: `canonical_url` 가 `at_medium` · `at_campaign` 으로 시작하는 쿼리 인자를 지운다

- [ ] **Step 1: 실패 테스트 쓰기** — `tests/test_canonical.py` 끝에 더한다

```python
def test_canonical_strips_bbc_rss_tracking_and_folds_host():
    # BBC 아스날 RSS 의 link 그대로 (2026-10-04 실측) — 팀 페이지 시절 저장 주소와 같은 키가 돼야 한다
    rss = canonical_url("https://www.bbc.co.uk/sport/football/articles/ckd68e40ze3jo"
                        "?at_medium=RSS&at_campaign=rss")
    assert rss == "https://www.bbc.com/sport/football/articles/ckd68e40ze3jo"


def test_canonical_keeps_other_params_starting_with_at():
    # 두 이름만 지운다 — 다른 사이트의 정상 인자는 남긴다 (설계 §2.5)
    assert canonical_url("https://x.test/a?at=1&atlas=2") == "https://x.test/a?at=1&atlas=2"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_canonical.py -k "bbc_rss or starting_with_at"`
Expected: 첫 테스트 FAIL (`?at_campaign=rss&at_medium=RSS` 가 남음) · 둘째는 PASS

- [ ] **Step 3: 추적 인자 목록에 두 이름 더하기** — `src/bullet_in/canonical.py`

```python
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "smid", "source",
                      "unlocked_article_code",
                      # BBC 아스날 RSS 의 link 에 붙는다 (설계 2026-10-05 §2.5 · 저장 주소 0건이라 기존 해시 불변)
                      "at_medium", "at_campaign")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_canonical.py`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/canonical.py tests/test_canonical.py
git commit -m "fix(canonical): BBC RSS 추적 인자 at_medium · at_campaign 을 주소 키에서 제거"
```

---

### Task 3: RSS 어댑터 확장

**Files:**
- Modify: `src/bullet_in/adapters/rss.py` (전체 교체)
- Modify: `src/bullet_in/adapters/factory.py:24-25`
- Test: `tests/test_rss_adapter.py` (전체 교체) · `tests/test_adapter_factory.py`
- Fixture (계획과 함께 커밋됨): `tests/fixtures/bbc_arsenal_feed.xml` — 2026-10-04 15:55 UTC 실제 BBC 피드의 항목 셋 (`ckd68e40ze3jo` Arteta deal · `cvgy802y2n9o` Ramsdale · `crp3k23nkl8go` Dowman loan)

**Interfaces:**
- Consumes: `fetch_article_detail` (Task 1) · `bullet_in.quality.list_signature(urls) -> str` · `bullet_in.adapters.meta._parse_published(raw) -> tuple[datetime, str] | None`
- Produces: `RssAdapter(source_id: str, feed_url: str, title_contains: str | list[str] | None = None, body_selector: str | None = None)` · `fetch()` 뒤 `self.funnel == {"entries": int, "deduped": int, "passed": int, "list_sig": str}` (예외면 `{}`) · `RawItem.raw_payload` 키 `title` · `summary` · 있으면 `published` · `published_precision` · `body_selector` 가 있으면 Task 1 의 키

- [ ] **Step 1: 실패 테스트 쓰기** — `tests/test_rss_adapter.py` 전체를 바꾼다

```python
import asyncio
from pathlib import Path

import httpx
import pytest
import respx

from bullet_in.adapters.rss import RssAdapter
from bullet_in.quality import list_signature

FIX = Path(__file__).parent / "fixtures"
FEED = "https://feeds.test/arsenal/rss.xml"
BBC = (FIX / "bbc_arsenal_feed.xml").read_bytes()
DEAL = ("https://www.bbc.co.uk/sport/football/articles/ckd68e40ze3jo"
        "?at_medium=RSS&at_campaign=rss")
RAMSDALE = ("https://www.bbc.co.uk/sport/football/articles/cvgy802y2n9o"
            "?at_medium=RSS&at_campaign=rss")
LOAN = ("https://www.bbc.co.uk/sport/football/articles/crp3k23nkl8go"
        "?at_medium=RSS&at_campaign=rss")
KW = ["deal", "loan", "agree"]


def _mini(items: str) -> bytes:
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'.encode()


@respx.mock
def test_rss_adapter_parses_items():
    # 종전 테스트 (공식 소스 피드 픽스처) — 받기를 httpx 로 옮긴 뒤에도 같은 값
    respx.get(FEED).mock(return_value=httpx.Response(
        200, content=(FIX / "sample_feed.xml").read_bytes()))
    items = asyncio.run(RssAdapter(source_id="arsenal_official", feed_url=FEED).fetch())
    assert len(items) == 1
    assert items[0].raw_payload["title"] == "Arteta on win"
    assert items[0].url == "https://www.arsenal.com/news/arteta-win"
    assert items[0].source_type == "rss"


@respx.mock
def test_rss_filters_by_keyword_and_records_funnel():
    respx.get(FEED).mock(return_value=httpx.Response(200, content=BBC))
    a = RssAdapter("bbc_sport", FEED, title_contains=KW)
    items = asyncio.run(a.fetch())
    assert [it.raw_payload["title"] for it in items] == [
        "Arteta agrees new deal with champions Arsenal",
        "Arsenal open to Dowman loan in right circumstances"]
    assert [it.url for it in items] == [DEAL, LOAN]       # 주소 정규화는 파이프라인 몫
    assert a.funnel == {"entries": 3, "deduped": 3, "passed": 2,
                        "list_sig": list_signature([DEAL, RAMSDALE, LOAN])}


@respx.mock
def test_rss_list_signature_covers_items_the_keywords_drop():
    respx.get(FEED).mock(return_value=httpx.Response(200, content=BBC))
    a = RssAdapter("bbc_sport", FEED, title_contains=["nothing-matches"])
    assert asyncio.run(a.fetch()) == []
    assert a.funnel["passed"] == 0
    assert a.funnel["list_sig"] == list_signature([DEAL, RAMSDALE, LOAN])


@respx.mock
def test_rss_carries_feed_published_time():
    respx.get(FEED).mock(return_value=httpx.Response(200, content=BBC))
    items = asyncio.run(RssAdapter("bbc_sport", FEED, title_contains=KW).fetch())
    assert items[0].raw_payload["published"] == "2026-09-22T11:48:23+00:00"
    assert items[0].raw_payload["published_precision"] == "time"


@respx.mock
def test_rss_fetches_article_body_when_selector_set():
    respx.get(FEED).mock(return_value=httpx.Response(200, content=BBC))
    respx.get(DEAL).mock(return_value=httpx.Response(
        200, text='<html><head><meta property="og:image" content="https://img.test/a.jpg">'
                  '</head><body><article><p>Arteta has agreed a new deal.</p></article></body></html>'))
    respx.get(LOAN).mock(return_value=httpx.Response(500))
    items = asyncio.run(RssAdapter("bbc_sport", FEED, title_contains=KW,
                                   body_selector="article").fetch())
    assert items[0].raw_payload["body"] == "Arteta has agreed a new deal."
    assert items[0].raw_payload["image_url"] == "https://img.test/a.jpg"
    # 상세 실패 — 제목 · 피드 발행 시각은 남고 본문만 빈다
    assert items[1].raw_payload["body"] == ""
    assert items[1].raw_payload["title"] == "Arsenal open to Dowman loan in right circumstances"
    assert items[1].raw_payload["published"] == "2026-09-18T21:30:38+00:00"


@respx.mock
def test_rss_http_error_raises_and_leaves_no_funnel():
    respx.get(FEED).mock(return_value=httpx.Response(503))
    a = RssAdapter("bbc_sport", FEED, title_contains=KW)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(a.fetch())
    assert a.funnel == {}


@respx.mock
def test_rss_non_xml_page_yields_zero_entries():
    # 200 인데 피드가 아닌 페이지 — 예외 없이 0개, SLO-5 가 no_entries 로 본다
    respx.get(FEED).mock(return_value=httpx.Response(200, text="<html><body>Moved</body></html>"))
    a = RssAdapter("bbc_sport", FEED, title_contains=KW)
    assert asyncio.run(a.fetch()) == []
    assert a.funnel == {"entries": 0, "deduped": 0, "passed": 0, "list_sig": ""}


@respx.mock
def test_rss_skips_missing_link_dedups_and_counts_untitled():
    feed = _mini("<item><title>No link deal</title></item>"
                 "<item><title>Twice deal</title><link>https://a.test/1</link></item>"
                 "<item><title>Twice deal</title><link>https://a.test/1</link></item>"
                 "<item><link>https://a.test/2</link></item>")
    respx.get(FEED).mock(return_value=httpx.Response(200, content=feed))
    a = RssAdapter("bbc_sport", FEED, title_contains=["deal"])
    items = asyncio.run(a.fetch())
    assert [it.url for it in items] == ["https://a.test/1"]
    assert a.funnel["entries"] == 4
    assert a.funnel["deduped"] == 2          # 링크 없는 항목은 빠지고 같은 링크는 한 번
    assert a.funnel["passed"] == 1           # 제목 없는 항목은 키워드에 못 닿는다
    assert a.funnel["list_sig"] == list_signature(["https://a.test/1", "https://a.test/2"])
```

`tests/test_adapter_factory.py` 끝에 더한다.

```python
def test_rss_adapter_gets_keywords_and_body_selector():
    cfg = {"sources": [{"source_id": "bbc_sport", "adapter": "rss",
                        "config": {"feed_url": "https://feeds.test/a.xml",
                                   "title_contains": ["deal"], "body_selector": "article"}}]}
    a = build_adapters(cfg)[0]
    assert (a.feed_url, a.title_keywords, a.body_selector) == \
        ("https://feeds.test/a.xml", ["deal"], "article")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_rss_adapter.py tests/test_adapter_factory.py`
Expected: FAIL — `TypeError: RssAdapter.__init__() got an unexpected keyword argument 'title_contains'` 등 · `test_rss_adapter_parses_items` 도 respx 가 가로채지 못해 실패할 수 있음 (지금은 feedparser 가 직접 받음)

- [ ] **Step 3: 어댑터 교체** — `src/bullet_in/adapters/rss.py` 전체

```python
"""RSS 피드 어댑터 (설계 2026-10-05 §2).

피드는 httpx 로 받는다 — feedparser 가 주소를 직접 받으면 HTTP 오류에도 예외 없이
빈 목록을 돌려줘, 피드가 죽은 것과 새 글이 없는 것이 구별되지 않는다 (§2.2)."""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser
import httpx

from bullet_in.adapters.detail import fetch_article_detail
from bullet_in.adapters.meta import _parse_published
from bullet_in.models import RawItem
from bullet_in.quality import list_signature


class RssAdapter:
    source_type = "rss"

    def __init__(self, source_id: str, feed_url: str,
                 title_contains: str | list[str] | None = None,
                 body_selector: str | None = None):
        self.source_id = source_id
        self.feed_url = feed_url
        self.body_selector = body_selector
        # 수집 단계 기록 — SLO-5 응답 판정 (quality.responded) 이 읽는다 (§3.1).
        self.funnel: dict = {}
        if title_contains is None:
            self.title_keywords: list[str] | None = None
        elif isinstance(title_contains, str):
            self.title_keywords = [title_contains.lower()]
        else:
            self.title_keywords = [k.lower() for k in title_contains]

    async def fetch(self) -> list[RawItem]:
        self.funnel = {}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": "bullet-in/0.1"}) as c:
            r = await c.get(self.feed_url)
            r.raise_for_status()
            entries = feedparser.parse(r.content).entries
            now, matched, seen = datetime.now(timezone.utc), [], []
            funnel = {"entries": len(entries), "deduped": 0, "passed": 0}
            for e in entries:
                url = (e.get("link") or "").strip()
                if not url or url in seen:
                    continue
                seen.append(url)
                funnel["deduped"] += 1
                title = (e.get("title") or "").strip()
                if not title:
                    continue
                if self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
                funnel["passed"] += 1
                matched.append((title, url, e))
            # 목록 지문 — 키워드 필터 앞의 링크 묶음 (HTML 어댑터와 같은 규칙 · §2.3)
            funnel["list_sig"] = list_signature(seen)
            self.funnel = funnel
            out = []
            for title, url, e in matched:
                payload = {"title": title, "summary": e.get("summary", "")}
                pub = _parse_published(e.get("published") or "")
                if pub:
                    payload["published"] = pub[0].isoformat()
                    payload["published_precision"] = pub[1]
                if self.body_selector:
                    # 상세 페이지의 발행 시각이 있으면 그 값이 피드 값을 덮는다 (§2.1)
                    payload.update(await fetch_article_detail(c, url, self.body_selector))
                out.append(RawItem(source_id=self.source_id, source_type="rss",
                                   url=url, fetched_at=now, raw_payload=payload))
        return out
```

- [ ] **Step 4: 공장 함수가 설정을 넘기게** — `src/bullet_in/adapters/factory.py`

```python
        if kind == "rss":
            out.append(RssAdapter(sid, c["feed_url"],
                                  title_contains=c.get("title_contains"),
                                  body_selector=c.get("body_selector")))
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_rss_adapter.py tests/test_adapter_factory.py tests/test_detail.py`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/adapters/rss.py src/bullet_in/adapters/factory.py tests/test_rss_adapter.py tests/test_adapter_factory.py
git commit -m "feat(adapters): RSS 어댑터에 httpx 받기 · 키워드 필터 · 목록 지문 · 수집 단계 기록 · 상세 받기"
```

---

### Task 4: SLO-5 응답 판정의 rss 분기

**Files:**
- Modify: `src/bullet_in/quality.py:81-120` (`responded`)
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: Task 3 의 수집 단계 기록 키
- Produces: `responded("rss", funnel, errored)` 가 `(False, "no_entries")` 를 돌려줄 수 있다

- [ ] **Step 1: 실패 테스트 쓰기** — `tests/test_quality.py` 의 `responded` 테스트들 뒤에 더한다

```python
def test_responded_rss_needs_entries_and_signature():
    ok = {"entries": 24, "deduped": 24, "passed": 5, "list_sig": "abc"}
    assert responded("rss", ok, errored=False) == (True, "")
    assert responded("rss", {**ok, "passed": 0}, errored=False) == (True, "")   # 키워드 0 은 조용함의 몫
    assert responded("rss", {"entries": 0, "deduped": 0, "passed": 0, "list_sig": ""},
                     errored=False) == (False, "no_entries")
    assert responded("rss", {**ok, "list_sig": ""}, errored=False) == (False, "no_record")
    assert responded("rss", ok, errored=True) == (False, "error")
    assert responded("rss", None, errored=False) == (False, "no_record")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_quality.py -k rss_needs_entries`
Expected: FAIL — 항목 0개 경우가 `(True, '')` 로 떨어짐

- [ ] **Step 3: 분기 넣기** — `src/bullet_in/quality.py` 의 `responded` 에서 fmkorea 분기 뒤, 마지막 `return True, ""` 앞

```python
    if adapter == "rss":
        # 피드가 200 이어도 피드가 아닌 페이지면 항목이 0개다 (설계 2026-10-05 §3.1)
        if int(funnel.get("entries", 0)) == 0:
            return False, "no_entries"
        # 수집 단계 기록이 없으면 목록 서명을 얻지 못했다 (스펙 2026-10-02 §2.2.4)
        if not funnel.get("list_sig"):
            return False, "no_record"
        return True, ""
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_quality.py`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/quality.py tests/test_quality.py
git commit -m "feat(slo5): RSS 소스의 응답 판정 — 피드 항목 0개는 무응답 no_entries"
```

---

### Task 5: 화면과 알림이 rss 수집 단계를 읽게

**Files:**
- Modify: `src/bullet_in/serve/ops_view.py` (`_stage_text`)
- Modify: `src/bullet_in/notify.py` (`broken_reason_text` · `_funnel_lines`)
- Test: `tests/test_ops_view.py` · `tests/test_notify.py`

**Interfaces:**
- Consumes: Task 3 의 기록 키 · Task 4 의 사유 `no_entries`

- [ ] **Step 1: 실패 테스트 쓰기**

`tests/test_ops_view.py` 끝에 더한다.

```python
def test_stage_text_reads_rss_funnel():
    from bullet_in.serve.ops_view import _stage_text
    assert _stage_text({"entries": 24, "deduped": 24, "passed": 5, "list_sig": "x"}) == \
        "피드 항목 24 · 키워드 5"
```

`tests/test_notify.py` 끝에 더한다 (`_broken_rec` 는 같은 파일에 이미 있다).

```python
def test_broken_reason_no_entries():
    _, r = _broken_rec("no_entries")
    assert notify.broken_reason_text(r, {"entries": 0}, None) == "피드 항목 0개 · 2회 연속"


def test_funnel_lines_rss_three_stages():
    assert notify._funnel_lines({"entries": 24, "deduped": 24, "passed": 5, "list_sig": "x"}) == \
        ["수집 단계 기록: 피드 항목 24 → URL 24 → 키워드 5"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_ops_view.py tests/test_notify.py -k "rss or no_entries"`
Expected: FAIL — 화면 칸이 「기사 링크 24 · 제목 확인 0」 · 사유 문장이 「수집 단계 기록 없음 …」 · 수집 단계가 HTML 네 단계

- [ ] **Step 3: 화면 칸** — `src/bullet_in/serve/ops_view.py` 의 `_stage_text` 에서 `"deduped" in f` 검사 **앞**에

```python
    if "entries" in f:
        return f"피드 항목 {f.get('entries', 0)} · 키워드 {f.get('passed', 0)}"
```

- [ ] **Step 4: 알림 문장 둘** — `src/bullet_in/notify.py`

`broken_reason_text` 의 `no_links` 분기 바로 뒤에

```python
    if r.reason == "no_entries":
        return f"피드 항목 0개 · {n}회 연속"
```

`_funnel_lines` 의 `"keywords" in funnel` 분기 바로 뒤에

```python
    if "entries" in funnel:
        return [f"수집 단계 기록: 피드 항목 {funnel.get('entries', 0)} "
                f"→ URL {funnel.get('deduped', 0)} → 키워드 {funnel.get('passed', 0)}"]
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_ops_view.py tests/test_notify.py`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/serve/ops_view.py src/bullet_in/notify.py tests/test_ops_view.py tests/test_notify.py
git commit -m "feat(slo5): 수집 현황 화면 · 끊김 알림이 RSS 수집 단계 기록을 읽음"
```

---

### Task 6: 설정 전환 · 문서 · 라이브 검증

**Files:**
- Modify: `config/sources.yaml` (`bbc_sport` 블록)
- Modify: `README.md` (`collect` 행 · §3.4 BBC Sport 행)
- Modify: `docs/superpowers/specs/2026-10-02-slo5-broken-source-signal-design.md` (§9.2 소스별 상한)
- Modify: `docs/runbook/2026-08-20-freshness-threshold-recalibration.md` (§8.2 상한 표)
- Test: `tests/test_freshness_config.py`

- [ ] **Step 1: 실패 테스트 쓰기** — `tests/test_freshness_config.py` 끝에 더한다

```python
def test_bbc_sport_reads_the_arsenal_rss():
    """팀 페이지가 피드 모양으로 바뀌어 RSS 로 옮겼다 (설계 2026-10-05).

    RSS 는 조용한 주에 135시간 넘게 그대로라 전역 상한 48h 로는 거짓 끊김이 난다."""
    s = _sources()["bbc_sport"]
    assert s["adapter"] == "rss"
    assert s["config"]["feed_url"] == "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml"
    assert s["config"]["body_selector"] == "article"
    assert "transfer" in s["config"]["title_contains"]
    assert s["list_unchanged_cap_hours"] == 240
    assert "list_url" not in s["config"] and "item_selector" not in s["config"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_freshness_config.py`
Expected: FAIL — `adapter` 가 `html`

- [ ] **Step 3: 설정 바꾸기** — `config/sources.yaml` 의 `bbc_sport` 블록 전체

```yaml
  - source_id: bbc_sport
    display_name: BBC Sport
    serving: full      # 상세 페이지 서빙 범위 (spec §2.3 개정 2026-07-20) — 전 소스 전문 서빙
    tier: 1.5   # 비전담 기준선 — 전담 (Mokbel) 은 min 가드로 기자 tier 1 승격
    outlet: BBC
    medium: newspaper
    adapter: rss   # 2026-10-05 팀 페이지 (피드 모양 · 제목 확인 1/5) 에서 아스날 RSS 로 (설계 2026-10-05)
    config:
      feed_url: "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml"
      title_contains: *transfer_kw
      body_selector: "article"
    freshness_hours: 96    # 공백 95% 75h (21일 실측) — 48h 는 정상 소스를 회차의 22% 에서 stale 로 찍었다
    # RSS 항목 사이 최장 공백 135.2h (09-10 ~ 10-03) · A매치 휴식기 미포함이라 넉넉히 · 휴식기 뒤 재측정 (설계 §3.2 · §5)
    list_unchanged_cap_hours: 240
    enabled: true
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_freshness_config.py`
Expected: 전부 PASS

- [ ] **Step 5: 문서 넷 고치기**

README `collect` 행 (79행 부근) — 「수집 소스 8종을 어댑터 4종으로」 → 「수집 소스 8종을 어댑터 5종으로」.

README §3.4 수집 소스 표의 BBC Sport 행을 아래로 바꾼다.

```markdown
| BBC Sport | 1.5 | rss | 아스날 RSS (2026-10 팀 페이지에서 전환) · 비전담 기준선: 전담 기자 (Mokbel) 는 tier 1 로 상향 |
```

SLO-5 재설계 스펙 §9.2 의 소스별 상한 목록에 한 줄을 더한다 (그 절의 기존 서식을 따른다).

```markdown
- **BBC Sport 240시간 (2026-10-05 추가)** — 아스날 RSS 로 옮기며 둔 상한 · 근거와 재측정 시점은 `2026-10-05-bbc-sport-rss-switch-design.md` §3.2 · §5
```

신선도 임계 런북 §8.2 표의 `list_unchanged_cap_hours` 행을 고친다.

```markdown
| `list_unchanged_cap_hours: 288` · `240` · `240` | `config/sources.yaml` (Sky Sports · Ornstein · BBC Sport 항목) | 그 소스만 상한을 12일 · 10일 · 10일로 |
```

`docs/` 아래 두 파일은 저장할 때 서식 훅이 검사한다.
README 는 훅 대상이 아니라 손으로 `python3 .claude/hooks/check-doc-format.py README.md` 를 돌려 위반이 늘지 않았는지 본다.

- [ ] **Step 6: 전체 테스트**

Run: `cd <워크트리> && .venv/bin/python -m pytest --co -q | tail -1 && .venv/bin/python -m pytest -q`
Expected: 수집 1,870 + 이 계획이 더한 수 (Task 1 = 2 · Task 2 = 2 · Task 3 = 7 + 공장 1 (종전 1개는 교체) · Task 4 = 1 · Task 5 = 3 · Task 6 = 1 → 1,887) · 전부 PASS

- [ ] **Step 7: 머지 전 라이브 검증 (한 번만 접속 · 출력은 파일로)**

```bash
cd <워크트리> && .venv/bin/python - <<'EOF' 2>&1 | tee /tmp/bbc_rss_live.out
import asyncio, yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open("config/sources.yaml"))
cfg["sources"] = [s for s in cfg["sources"] if s["source_id"] == "bbc_sport"]
a = build_adapters(cfg)[0]
items = asyncio.run(a.fetch())
print("funnel", {k: v for k, v in a.funnel.items() if k != "list_sig"}, "sig", bool(a.funnel.get("list_sig")))
for it in items:
    p = it.raw_payload
    print(p["title"][:60], "| body", len(p.get("body", "")), "| authors", p.get("authors"),
          "| published", p.get("published"), p.get("published_precision"))
EOF
```

Expected: `entries` 20 이상 · `passed` 1 이상 · 통과한 항목마다 본문 길이 0 초과 · 발행 시각 있음 · 저자는 기사마다 다를 수 있음 (Mokbel 기사면 그 이름)

- [ ] **Step 8: 커밋**

```bash
git add config/sources.yaml tests/test_freshness_config.py README.md docs/superpowers/specs/2026-10-02-slo5-broken-source-signal-design.md docs/runbook/2026-08-20-freshness-threshold-recalibration.md
git commit -m "feat(sources): BBC Sport 를 아스날 RSS 로 전환 · 목록 상한 240시간"
```

## 범위 밖으로 둔 것

- README §3.4 표의 The Guardian 행은 `guardian_api` 로 적혀 있지만 설정은 `html` 어댑터다 · 이 계획에서는 고치지 않고 사용자에게 보고한다
- `backfill_journalist.py` 는 `adapter == "html"` 인 소스만 다시 받는 일회성 스크립트라 전환 뒤 `bbc_sport` 가 대상에서 빠진다 · 과거 행 소급용이라 그대로 둔다
- `run.adapter_funnels` 의 docstring 이 「rss · x_playwright 는 발견 단계가 달라」 라고 적고 있다 · 둘 다 이제 기록을 남기지만 동작과 무관한 주석이라 그대로 둔다
