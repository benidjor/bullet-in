import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from bullet_in.adapters.x_playwright import (XPageError, backtrack_cached,
                                             load_x_cache, save_x_cache,
                                             wait_for_tweets)
from bullet_in.models import RawItem

_NOW = datetime(2026, 11, 15, 9, tzinfo=timezone.utc)
_NOW2 = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def _tweet(sid):
    return RawItem(source_id="x_afcstuff", source_type="x",
                   url=f"https://x.com/afcstuff/status/{sid}", fetched_at=_NOW,
                   raw_payload={"text": "t", "created_at": None,
                                "journalist": "@SamiMokbel_BBC",
                                "handles": ["@SamiMokbel_BBC"], "image_url": None})


def _promoted(it):
    return RawItem(source_id=it.source_id, source_type="html",
                   url="https://www.bbc.com/a", fetched_at=it.fetched_at,
                   raw_payload={"title": "T", "body": "B", "outlet": "BBC"})


def test_second_run_reuses_promotion_and_opens_no_timeline():
    calls = []

    async def scrape(fresh):
        calls.append(len(fresh))
        return {"samimokbel_bbc": []}, set()

    async def promote(fresh, tl):
        return [_promoted(it) for it in fresh]

    outcomes = {}
    first = asyncio.run(backtrack_cached([_tweet("1")], outcomes, _NOW, scrape, promote))
    second = asyncio.run(backtrack_cached([_tweet("1")], outcomes, _NOW2, scrape, promote))
    assert calls == [1]
    assert [i.url for i in second] == [i.url for i in first] == ["https://www.bbc.com/a"]
    assert second[0].raw_payload == first[0].raw_payload and second[0].fetched_at == _NOW2
    assert second[0].source_type == "html"


def test_failed_timeline_is_not_remembered():
    async def scrape(fresh):
        return {}, {"samimokbel_bbc"}

    async def promote(fresh, tl):
        return list(fresh)

    outcomes = {}
    asyncio.run(backtrack_cached([_tweet("1")], outcomes, _NOW, scrape, promote))
    assert outcomes == {}


def test_in_place_paywall_promotion_is_still_keyed_by_tweet_url():
    calls = []

    async def scrape(fresh):
        calls.append(len(fresh))
        return {}, set()

    async def promote(fresh, tl):      # backtrack_promote 의 유료 기사 경로처럼 제자리 변경
        for it in fresh:
            it.raw_payload["tweet_url"] = it.url
            it.url = "https://www.theathletic.com/a"
        return list(fresh)

    outcomes = {}
    first = asyncio.run(backtrack_cached([_tweet("1")], outcomes, _NOW, scrape, promote))
    second = asyncio.run(backtrack_cached([_tweet("1")], outcomes, _NOW2, scrape, promote))
    assert calls == [1]
    assert list(outcomes) == ["https://x.com/afcstuff/status/1"]
    assert [i.url for i in first] == [i.url for i in second] == ["https://www.theathletic.com/a"]
    assert second[0].raw_payload["tweet_url"] == "https://x.com/afcstuff/status/1"


def test_mixed_batch_keeps_input_order():
    async def scrape(fresh):
        return {}, set()

    async def promote(fresh, tl):
        return [_promoted(it) for it in fresh]

    outcomes = {}
    asyncio.run(backtrack_cached([_tweet("2")], outcomes, _NOW, scrape, promote))
    out = asyncio.run(backtrack_cached([_tweet("1"), _tweet("2"), _tweet("3")],
                                       outcomes, _NOW2, scrape, promote))
    assert [i.source_type for i in out] == ["html", "html", "html"]
    assert set(outcomes) == {f"https://x.com/afcstuff/status/{i}" for i in "123"}


def test_save_keeps_only_what_this_run_saw_and_round_trips(tmp_path):
    p = tmp_path / "c.json"
    cache = {"expanded": {"1": "a", "9": "old"},
             "outcomes": {"u1": {"url": "u1"}, "u9": {}}}
    save_x_cache(str(p), cache, {"1"}, {"u1"})
    assert load_x_cache(str(p)) == {"expanded": {"1": "a"}, "outcomes": {"u1": {"url": "u1"}}}


def test_broken_or_missing_cache_starts_empty(tmp_path, caplog):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    empty = {"expanded": {}, "outcomes": {}}
    assert load_x_cache(None) == load_x_cache(str(tmp_path / "none.json")) == empty
    assert load_x_cache(str(bad)) == empty and "못 읽음" in caplog.text


def test_save_to_none_path_does_nothing():
    save_x_cache(None, {"expanded": {}, "outcomes": {}}, set(), set())


def test_save_with_non_json_value_warns_and_leaves_no_file(tmp_path, caplog):
    p = tmp_path / "c.json"
    cache = {"expanded": {"1": datetime(2026, 11, 15)}, "outcomes": {}}
    save_x_cache(str(p), cache, {"1"}, set())
    assert "못 씀" in caplog.text
    assert list(tmp_path.iterdir()) == []


def test_live_x_sources_have_cache_paths():
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    paths = {s["source_id"]: s["config"].get("cache_path") for s in cfg["sources"]
             if s["source_id"].startswith("x_")}
    assert paths == {"x_afcstuff": "state/x_cache_afcstuff.json",
                     "x_ornstein": "state/x_cache_ornstein.json"}


class _Page:
    url = "https://x.com/account/access"

    def __init__(self, title="Locked account", title_fails=False):
        self._t, self._f = title, title_fails

    async def wait_for_selector(self, sel, timeout):
        raise TimeoutError("Timeout 20000ms exceeded.\nCall log: ...")

    async def title(self):
        if self._f:
            raise RuntimeError("closed")
        return self._t


def test_timeout_carries_url_and_title():
    with pytest.raises(XPageError) as e:
        asyncio.run(wait_for_tweets(_Page()))
    msg = str(e.value)
    assert "url=https://x.com/account/access" in msg and "title='Locked account'" in msg
    assert "Call log" not in msg and isinstance(e.value.__cause__, TimeoutError)


def test_title_failure_still_raises_the_timeout():
    with pytest.raises(XPageError) as e:
        asyncio.run(wait_for_tweets(_Page(title_fails=True)))
    assert "title=?" in str(e.value)
