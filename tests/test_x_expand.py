import asyncio
import logging

from bullet_in.adapters.x_playwright import (EXPAND_LEN_HINT, expand_truncated,
                                             needs_expansion)


def test_needs_expansion_only_at_the_cap():
    assert needs_expansion("가" * EXPAND_LEN_HINT) is True
    assert needs_expansion("가" * (EXPAND_LEN_HINT - 1)) is False
    assert needs_expansion(None) is False
    assert needs_expansion("") is False


class _Page:
    """status 페이지 흉내 — status_id 별로 돌려줄 전문을 미리 받는다."""

    def __init__(self, full_by_url, fail_urls):
        self.full_by_url, self.fail_urls = full_by_url, fail_urls
        self.url = None
        self.closed = False

    async def goto(self, url, **kw):
        self.url = url
        if url in self.fail_urls:
            raise RuntimeError("타임아웃")

    async def wait_for_selector(self, sel, **kw):
        return None

    async def eval_on_selector(self, sel, js):
        return self.full_by_url.get(self.url, "")

    async def close(self):
        self.closed = True


class _Ctx:
    def __init__(self, full_by_url, fail_urls=()):
        self.full_by_url, self.fail_urls = full_by_url, set(fail_urls)
        self.pages = []

    async def new_page(self):
        p = _Page(self.full_by_url, self.fail_urls)
        self.pages.append(p)
        return p


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_expand_replaces_the_truncated_text_with_the_full_one():
    short = "A" * EXPAND_LEN_HINT
    full = short + " and the rest of the tweet that the timeline hid."
    raw = [{"status_id": "1", "text": short},
           {"status_id": "2", "text": "짧은 트윗"}]     # 임계 미만 — 안 건드린다
    ctx = _Ctx({"https://x.com/afcstuff/status/1": full})
    grown = _run(expand_truncated(ctx, raw, "afcstuff", logging.getLogger(__name__)))
    assert grown == 1
    assert raw[0]["text"] == full
    assert raw[1]["text"] == "짧은 트윗"
    assert len(ctx.pages) == 1                        # 임계 넘는 것만 페이지를 연다
    assert all(p.closed for p in ctx.pages)           # 열었으면 닫는다


def test_expand_keeps_the_timeline_text_when_the_status_page_fails():
    short = "B" * EXPAND_LEN_HINT
    raw = [{"status_id": "9", "text": short}]
    ctx = _Ctx({}, fail_urls=["https://x.com/afcstuff/status/9"])
    grown = _run(expand_truncated(ctx, raw, "afcstuff", logging.getLogger(__name__)))
    assert grown == 0
    assert raw[0]["text"] == short                    # 실패해도 지금 값을 잃지 않는다
    assert all(p.closed for p in ctx.pages)


def test_expand_does_not_shrink_when_the_status_page_is_shorter():
    short = "C" * EXPAND_LEN_HINT
    raw = [{"status_id": "3", "text": short}]
    ctx = _Ctx({"https://x.com/afcstuff/status/3": "짧아진 값"})
    grown = _run(expand_truncated(ctx, raw, "afcstuff", logging.getLogger(__name__)))
    assert grown == 0
    assert raw[0]["text"] == short


def test_expand_warns_only_when_the_text_still_looks_cut(caplog):
    # 이 경고가 이 경로의 유일한 관측 장치다 — 조용히 깨지면 잘린 원문이 다시 흐른다.
    raw = [{"status_id": "4", "text": "D" * EXPAND_LEN_HINT + " “열린 인용"}]
    ctx = _Ctx({})                      # 펼치기가 아무것도 못 준다
    with caplog.at_level(logging.WARNING):
        _run(expand_truncated(ctx, raw, "afcstuff", logging.getLogger("x")))
    assert any("끊겨 보임" in r.getMessage() for r in caplog.records)


def test_expand_stays_quiet_for_a_long_but_complete_tweet(caplog):
    # 임계 이상의 대부분은 원래 안 잘린 트윗이다 — 여기서 경고하면 회차마다 떠서
    # 아무도 안 본다 (라이브 검증에서 임계 이상 2건 중 1건이 정상 트윗이었다).
    raw = [{"status_id": "5", "text": "E" * EXPAND_LEN_HINT + " 정상 종료."}]
    ctx = _Ctx({})
    with caplog.at_level(logging.WARNING):
        _run(expand_truncated(ctx, raw, "afcstuff", logging.getLogger("x")))
    assert not [r for r in caplog.records if "끊겨 보임" in r.getMessage()]


def test_expand_respects_the_cap():
    raw = [{"status_id": str(i), "text": "E" * EXPAND_LEN_HINT} for i in range(15)]
    ctx = _Ctx({})
    _run(expand_truncated(ctx, raw, "afcstuff", logging.getLogger(__name__), cap=3))
    assert len(ctx.pages) == 3
