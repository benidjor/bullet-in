import asyncio, json
import httpx, respx
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter, GRAPHQL_URL, SITEMAP_URL
from datetime import datetime, timezone
from bullet_in.adapters.arsenal_api import _sitemap_candidates, _glide_id

def _sitemap_entry(slug, lastmod="2026-07-23T12:10:38.401Z"):
    return (f"<url><loc>https://www.arsenal.com/news/{slug}</loc>"
            f"<lastmod>{lastmod}</lastmod></url>")

def _sitemap(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(entries) + "</urlset>")

def _gql_article(title, taxonomies, article_type="News",
                 published="2026-07-23T12:10:38.401Z", body_texts=("본문",)):
    blocks = [{"type": "HEADER", "image": "https://assets.arsenal.com/h.webp",
               "author": "Arsenal Media"}]
    blocks += [{"type": "TEXT", "innerText": t} for t in body_texts]
    return {"title": title, "publicationDate": published,
            "taxonomies": taxonomies, "articleType": article_type,
            "articleBody": blocks}

def _mock_backend(sitemap_xml, articles_by_gid, article_status=200):
    """sitemap GET + GetArticle POST 모킹. articles_by_gid: glideId → 응답 (None = data null)."""
    respx.get(SITEMAP_URL).mock(return_value=httpx.Response(200, text=sitemap_xml))
    def responder(request):
        gid = json.loads(request.content)["variables"]["glideId"]
        if article_status != 200:
            return httpx.Response(article_status)
        return httpx.Response(200, json={"data": {"getArticle":
                                                  articles_by_gid.get(gid)}})
    return respx.post(GRAPHQL_URL).mock(side_effect=responder)

FIXED_NOW_ENTRIES = [_sitemap_entry("christos-tzolis-signs-for-arsenal-axDM85b0dBUW")]

@respx.mock
def test_accept_maps_payload_with_time_precision():
    _mock_backend(_sitemap(FIXED_NOW_ENTRIES), {
        "axDM85b0dBUW": _gql_article(
            "Christos Tzolis signs for Arsenal",
            ["Men", "News", "Transfer news"],
            body_texts=("Tzolis has signed.", "Welcome."))})
    items = asyncio.run(ArsenalApiAdapter("arsenal_official", window_hours=24 * 365).fetch())
    assert len(items) == 1
    p = items[0].raw_payload
    assert items[0].url.endswith("-axDM85b0dBUW")
    assert p["title"] == "Christos Tzolis signs for Arsenal"
    assert p["published"] == "2026-07-23T12:10:38.401Z"
    assert p["published_precision"] == "time"
    assert p["body"] == "Tzolis has signed.\n\nWelcome."
    assert p["image_url"] == "https://assets.arsenal.com/h.webp"
    assert p["authors"] == ["Arsenal Media"]

@respx.mock
def test_taxonomy_filter_rules_via_getarticle():
    entries = [_sitemap_entry(f"a-{g}") for g in
               ["aOK1ok1ok1ok", "aOK2ok2ok2ok", "aNO1no1no1no",
                "aNO2no2no2no", "aNO3no3no3no", "aNO4no4no4no"]]
    _mock_backend(_sitemap(entries), {
        "aOK1ok1ok1ok": _gql_article("Terms agreed", ["Transfer news", "Men", "News"]),
        "aOK2ok2ok2ok": _gql_article("Men renewal", ["Contract news", "Men", "News"]),
        "aNO1no1no1no": _gql_article("Academy pro", ["Contract news", "Academy", "News"]),
        "aNO2no2no2no": _gql_article("Women signing", ["Transfer news", "Women", "News"]),
        "aNO3no3no3no": _gql_article("Match report", ["Men", "News"]),
        "aNO4no4no4no": _gql_article("Transfer video", ["Transfer news", "Men", "Video"],
                                     article_type="Video")})
    adapter = ArsenalApiAdapter("arsenal_official", window_hours=24 * 365)
    items = asyncio.run(adapter.fetch())
    assert [i.raw_payload["title"] for i in items] == ["Terms agreed", "Men renewal"]
    assert adapter.coverage == {"candidates": 6, "men_tagged": 4, "accepted": 2}

@respx.mock
def test_getarticle_null_is_isolated_and_others_survive(caplog):
    entries = [_sitemap_entry("good-aOK1ok1ok1ok"), _sitemap_entry("gone-aNO1no1no1no")]
    _mock_backend(_sitemap(entries), {
        "aOK1ok1ok1ok": _gql_article("Terms agreed", ["Transfer news", "Men", "News"])})
    with caplog.at_level("WARNING"):
        items = asyncio.run(
            ArsenalApiAdapter("arsenal_official", window_hours=24 * 365).fetch())
    assert [i.raw_payload["title"] for i in items] == ["Terms agreed"]
    assert any("GetArticle 응답 없음" in r.message for r in caplog.records)

@respx.mock
def test_getarticle_http_error_is_isolated(caplog):
    _mock_backend(_sitemap(FIXED_NOW_ENTRIES), {}, article_status=500)
    with caplog.at_level("WARNING"):
        items = asyncio.run(
            ArsenalApiAdapter("arsenal_official", window_hours=24 * 365).fetch())
    assert items == []
    assert any("GetArticle 실패" in r.message for r in caplog.records)

@respx.mock
def test_sitemap_failure_propagates():
    respx.get(SITEMAP_URL).mock(return_value=httpx.Response(503))
    import pytest
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(ArsenalApiAdapter("arsenal_official").fetch())

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.arsenal.com/news/christos-tzolis-signs-for-arsenal-axDM85b0dBUW</loc><lastmod>2026-07-23T12:10:38.401Z</lastmod></url>
  <url><loc>https://www.arsenal.com/gallery/christos-tzolis.-in-arsenal-colours.-af95S4s4Avgu</loc><lastmod>2026-07-23T12:41:00.000Z</lastmod></url>
  <url><loc>https://www.arsenal.com/news/old-article-aOLD11111111</loc><lastmod>2026-07-01T09:00:00.000Z</lastmod></url>
  <url><loc>https://www.arsenal.com/news/broken-lastmod-aBRK22222222</loc><lastmod>not-a-date</lastmod></url>
</urlset>"""

def test_sitemap_candidates_window_and_news_filter():
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    urls = _sitemap_candidates(SITEMAP_XML, now, 48)
    # /news/ 경로 + 48h 창 안 + lastmod 파싱 실패 제외 → Tzolis 1건
    assert urls == ["https://www.arsenal.com/news/"
                    "christos-tzolis-signs-for-arsenal-axDM85b0dBUW"]

def test_sitemap_candidates_wide_window_keeps_order():
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    urls = _sitemap_candidates(SITEMAP_XML, now, 24 * 60)
    assert [u.rsplit("-", 1)[1] for u in urls] == ["axDM85b0dBUW", "aOLD11111111"]

def test_glide_id_extraction():
    assert _glide_id("https://www.arsenal.com/news/"
                     "christos-tzolis-signs-for-arsenal-axDM85b0dBUW") == "axDM85b0dBUW"
    assert _glide_id("https://www.arsenal.com/news/no-token") is None
