import asyncio, respx, httpx
from bullet_in.adapters.fmkorea import FmkoreaAdapter

LIST = '''
<a class="title" href="/1">[디 애슬레틱] 아스날 사카 재계약 임박</a>
<a class="title" href="/2">[BBC] 첼시 이적 소식</a>
<a class="title" href="/3">Arsenal target identified</a>
'''
BODY1 = '<div class="xe_content">온스테인에 따르면 사카가 재계약한다.</div>'
BODY3 = '<div class="xe_content">Arsenal scout report.</div>'

@respx.mock
def test_fmkorea_filters_by_keyword_and_fetches_body():
    respx.get("https://fm.test/football_news").mock(
        return_value=httpx.Response(200, text=LIST))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=BODY1))
    respx.get("https://fm.test/3").mock(return_value=httpx.Response(200, text=BODY3))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날", "Arsenal"],
                       base_url="https://fm.test", body_selector=".xe_content")
    items = asyncio.run(a.fetch())
    urls = {i.url for i in items}
    assert urls == {"https://fm.test/1", "https://fm.test/3"}  # [BBC] 첼시 글 제외
    one = next(i for i in items if i.url == "https://fm.test/1")
    assert one.raw_payload["title"].startswith("[디 애슬레틱]")
    assert "온스테인" in one.raw_payload["body"]
    assert one.raw_payload["lang"] == "ko"
    assert one.source_type == "html"

@respx.mock
def test_fmkorea_skips_post_when_body_fetch_fails():
    respx.get("https://fm.test/football_news").mock(
        return_value=httpx.Response(200, text='<a class="title" href="/1">아스날 속보</a>'))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(500))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"],
                       base_url="https://fm.test", body_selector=".xe_content")
    assert asyncio.run(a.fetch()) == []
