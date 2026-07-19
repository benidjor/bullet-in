import asyncio, json
import httpx, respx
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter

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
