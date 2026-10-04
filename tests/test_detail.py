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
