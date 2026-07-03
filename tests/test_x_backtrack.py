import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from bullet_in.models import RawItem
from bullet_in.adapters.x_backtrack import extract_entities, match_original_tweet, outlet_for_domain, is_paywalled, load_backtrack_config, resolve_and_fetch, promote_cited_item, backtrack_promote

def test_extract_entities_multiword():
    assert "Jeremy Monga" in extract_entities("Man City working to sign Jeremy Monga")

def test_extract_entities_keeps_accent():
    ents = extract_entities("Arsenal hope to sign Bruno Guimarães this summer")
    assert "Bruno Guimarães" in ents

def test_extract_entities_skips_single_word():
    assert extract_entities("Arsenal are active") == []

_AF = datetime(2026, 7, 2, 21, 0, tzinfo=timezone.utc)

def _jt(text, minutes_before):
    return {"text": text, "created_at": (_AF - timedelta(minutes=minutes_before)).isoformat()}

def test_matcher_picks_highest_overlap_in_window():
    tweets = [
        _jt("Man City working to complete signing of Leicester winger Jeremy Monga proposed fee", 13),
        _jt("Man City pushing hard to sign Jeremy Monga from Leicester", 108),
    ]
    af = "Manchester City are working to complete a deal for Jeremy Monga fee region Leicester winger"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is tweets[0]

def test_matcher_none_below_threshold():
    tweets = [_jt("Newcastle eye Felix Nmecha midfielder shortlist", 20)]
    af = "Arsenal monitoring William Saliba fitness back problem"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is None

def test_matcher_excludes_later_tweets():
    tweets = [_jt("Arsenal agree Bruno Guimaraes deal Newcastle package worth", -30)]
    af = "Arsenal agree Bruno Guimaraes deal Newcastle package worth"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is None

def test_matcher_handles_naive_created_at():
    # tz 없는 created_at도 UTC로 간주해 비교 크래시 없이 매칭
    tweets = [{"text": "Arsenal sign Bruno Guimaraes Newcastle package worth",
               "created_at": "2026-07-02T20:30:00"}]
    af = "Arsenal sign Bruno Guimaraes Newcastle package worth"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is tweets[0]

_DOMAINS = {"bbc.co.uk": "BBC", "thesun.co.uk": "The Sun"}

def test_outlet_for_domain_exact_and_subdomain():
    assert outlet_for_domain("https://www.bbc.co.uk/sport/x", _DOMAINS) == "BBC"
    assert outlet_for_domain("https://thesun.co.uk/a", _DOMAINS) == "The Sun"

def test_outlet_for_domain_unknown():
    assert outlet_for_domain("https://example.com/a", _DOMAINS) is None

def test_outlet_for_domain_real_subdomain():
    assert outlet_for_domain("https://sport.bbc.co.uk/x", _DOMAINS) == "BBC"

def test_is_paywalled_athletic():
    assert is_paywalled("https://www.nytimes.com/athletic/123/") is True
    assert is_paywalled("https://theathletic.com/123/") is True
    assert is_paywalled("https://www.bbc.co.uk/x") is False

def test_is_paywalled_no_false_positive():
    assert is_paywalled("https://www.nytimes.com/athletics-fanzone/x") is False
    assert is_paywalled("https://t.co/x?u=theathletic.com") is False

def test_load_backtrack_config():
    cfg = load_backtrack_config("config/backtrack.yaml")
    assert cfg["domains"]["bbc.co.uk"] == "BBC"
    assert cfg["params"]["overlap_min"] == 4

def test_resolve_and_fetch_follows_redirect():
    def handler(request):
        if request.url.host == "t.co":
            return httpx.Response(301, headers={"location": "https://www.bbc.co.uk/sport/article"})
        return httpx.Response(200, headers={"content-type": "text/html"},
                              html='<meta property="og:title" content="Head"><article><p>Body text here.</p></article>')
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as c:
            return await resolve_and_fetch(c, "https://t.co/abc")
    url, body, title, _img = asyncio.run(run())
    assert url == "https://www.bbc.co.uk/sport/article"
    assert "Body text" in body
    assert title == "Head"

def test_resolve_and_fetch_returns_empty_on_http_error():
    def handler(request):
        return httpx.Response(500)
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as c:
            return await resolve_and_fetch(c, "https://t.co/bad")
    assert asyncio.run(run()) == (None, "", None, None)

def test_promote_builds_html_item():
    it = RawItem(source_id="x_afcstuff", source_type="x",
                 url="https://x.com/afcstuff/status/1",
                 fetched_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                 raw_payload={"text": "Arsenal sign X [ @gunnerblog ]",
                              "journalist": "@gunnerblog",
                              "created_at": "2026-07-02T20:00:00Z"})
    p = promote_cited_item(it, "https://arseblog.com/a", "arseblog", "Arsenal sign X", "Body.", "https://img")
    assert p.url == "https://arseblog.com/a"
    assert p.source_type == "html"
    assert p.raw_payload["outlet"] == "arseblog"
    assert p.raw_payload["lang"] == "en"
    assert p.raw_payload["journalist"] == "@gunnerblog"
    assert p.raw_payload["title"] == "Arsenal sign X"
    assert p.raw_payload["body"] == "Body."

def test_promote_title_falls_back_to_tweet_text():
    it = RawItem(source_id="x_afcstuff", source_type="x", url="https://x.com/a/status/1",
                 fetched_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                 raw_payload={"text": "Tweet headline", "journalist": "@x"})
    p = promote_cited_item(it, "https://bbc.co.uk/a", "BBC", None, "B", None)
    assert p.raw_payload["title"] == "Tweet headline"

def _cited(handle, text, created):
    return RawItem(source_id="x_afcstuff", source_type="x",
                   url="https://x.com/afcstuff/status/9", fetched_at=datetime(2026,7,3,tzinfo=timezone.utc),
                   raw_payload={"text": text, "journalist": handle, "created_at": created})

_CFG = {"params": {"window_min": 180, "overlap_min": 4}, "domains": {"bbc.co.uk": "BBC"}}

def test_backtrack_keeps_item_when_no_timeline():
    # 기자 타임라인 없음 → 2순위 그대로
    it = _cited("@gunnerblog", "Arsenal sign X", "2026-07-02T20:00:00Z")
    out = asyncio.run(backtrack_promote([it], {}, _CFG))
    assert out[0] is it

def test_backtrack_keeps_item_when_matched_tweet_has_no_card():
    # 정책 Y : 매칭돼도 카드 없으면 승격 안 함
    it = _cited("@gunnerblog", "Arsenal sign Bruno Guimaraes Newcastle package worth", "2026-07-02T20:00:00Z")
    timelines = {"gunnerblog": [{"text": "Arsenal sign Bruno Guimaraes Newcastle package worth",
                                 "created_at": "2026-07-02T19:30:00Z", "card_href": ""}]}
    out = asyncio.run(backtrack_promote([it], timelines, _CFG))
    assert out[0] is it

def test_backtrack_degrades_item_on_unexpected_error():
    # timeline에 잘못된(None) 항목 → 내부 예외 → 그 인용만 2순위 강등, 크래시 없음
    it = _cited("@gunnerblog", "Arsenal sign Bruno Guimaraes Newcastle package worth", "2026-07-02T20:00:00Z")
    out = asyncio.run(backtrack_promote([it], {"gunnerblog": [None]}, _CFG))
    assert out[0] is it
