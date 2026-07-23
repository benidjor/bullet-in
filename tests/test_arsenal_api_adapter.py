import asyncio, json
import httpx, respx
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter
from datetime import datetime, timezone
from bullet_in.adapters.arsenal_api import _sitemap_candidates, _glide_id

GQL = "https://afc-prd.graph.arsenal.com/graphql"

def _article(title, path, taxonomies, article_type="News", glide_id="g1",
             published="2026-07-15T17:00:09.176Z"):
    return {"articleId": "1", "glideId": glide_id, "title": title, "path": path,
            "publicationDate": published, "taxonomies": taxonomies,
            "articleType": article_type}

def _body_blocks(texts, image="https://assets.arsenal.com/h.webp",
                 author="Arsenal Media"):
    blocks = [{"type": "HEADER", "image": image, "author": author}]
    blocks += [{"type": "TEXT", "innerText": t, "html": f"<p>{t}</p>"} for t in texts]
    blocks.append({"type": "PROMOTEDARTICLE", "title": "more"})
    return blocks

def _mock_graphql(articles, bodies=None, body_status=200):
    """operationName 으로 목록/본문 응답 분기. bodies: glideId → blocks."""
    def responder(request):
        payload = json.loads(request.content)
        if payload["operationName"] == "GetArticlesByTaxonomy":
            return httpx.Response(200, json={"data": {"getArticlesByTaxonomy": {
                "total": len(articles), "articles": articles}}})
        gid = payload["variables"]["glideId"]
        if body_status != 200:
            return httpx.Response(body_status)
        return httpx.Response(200, json={"data": {"getArticle": {
            "articleBody": (bodies or {}).get(gid, [])}}})
    return respx.post(GQL).mock(side_effect=responder)

@respx.mock
def test_departure_official_passes_and_maps_payload():
    _mock_graphql(
        [_article("Leandro Trossard joins Besiktas",
                  "/news/leandro-trossard-joins-besiktas-a2RJl0E1RyLJ",
                  ["Transfer news", "Men", "News"], glide_id="a2RJl0E1RyLJ")],
        bodies={"a2RJl0E1RyLJ": _body_blocks(
            ["Trossard has joined Besiktas.", "Everyone at Arsenal thanks Leo."])})
    items = asyncio.run(ArsenalApiAdapter("arsenal_official").fetch())
    assert len(items) == 1
    it = items[0]
    assert it.source_type == "api"
    assert it.url == ("https://www.arsenal.com/news/"
                      "leandro-trossard-joins-besiktas-a2RJl0E1RyLJ")
    p = it.raw_payload
    assert p["title"] == "Leandro Trossard joins Besiktas"
    assert p["published"] == "2026-07-15T17:00:09.176Z"
    assert p["body"] == "Trossard has joined Besiktas.\n\nEveryone at Arsenal thanks Leo."
    assert p["image_url"] == "https://assets.arsenal.com/h.webp"
    assert p["authors"] == ["Arsenal Media"]

@respx.mock
def test_taxonomy_filter_rules():
    _mock_graphql([
        _article("Terms agreed with Besiktas", "/news/terms",
                 ["Transfer news", "Men", "News"], glide_id="ok1"),
        _article("Men renewal", "/news/renewal",
                 ["Contract news", "Men", "News"], glide_id="ok2"),
        _article("Academy first pro contract", "/news/academy",
                 ["Contract news", "Academy", "News"], glide_id="no1"),
        _article("Women signing", "/news/women",
                 ["Transfer news", "Women", "News"], glide_id="no2"),
        _article("Match report", "/news/report",
                 ["Men", "News"], glide_id="no3"),
        _article("Transfer video", "/video/clip",
                 ["Transfer news", "Men", "Video"],
                 article_type="Video", glide_id="no4"),
    ], bodies={"ok1": _body_blocks(["a"]), "ok2": _body_blocks(["b"])})
    items = asyncio.run(ArsenalApiAdapter("arsenal_official").fetch())
    assert [i.raw_payload["title"] for i in items] == ["Terms agreed with Besiktas",
                                                       "Men renewal"]

@respx.mock
def test_pages_config_paginates():
    route = _mock_graphql([])
    asyncio.run(ArsenalApiAdapter("arsenal_official", pages=3).fetch())
    pages = [json.loads(c.request.content)["variables"]["pageNumber"]
             for c in route.calls]
    assert pages == [1, 2, 3]

@respx.mock
def test_body_fetch_failure_keeps_title_only():
    _mock_graphql(
        [_article("Trossard joins Besiktas", "/news/t",
                  ["Transfer news", "Men", "News"], glide_id="g1")],
        body_status=500)
    items = asyncio.run(ArsenalApiAdapter("arsenal_official").fetch())
    assert len(items) == 1
    assert items[0].raw_payload["body"] == ""

@respx.mock
def test_null_list_response_returns_empty():
    respx.post(GQL).mock(return_value=httpx.Response(
        200, json={"data": {"getArticlesByTaxonomy": None}}))
    assert asyncio.run(ArsenalApiAdapter("arsenal_official").fetch()) == []

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
