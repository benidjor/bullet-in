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

from bullet_in.adapters.fmkorea import _is_repost_blocked, _extract_original_url

BLOCKED = (
    '<div class="xe_content"><p>유벤투스가 루쿠미를 원한다.</p><p></p>'
    '<p>https://m.gianlucadimarzio.com/calciomercato/juve-lucumi-493366</p></div>'
    '<!--AfterDocument(1,2)--></article>'
    '<strong>[퍼가기가 금지된 글입니다 - 캡처 방지 위해 글 열람 사용자 '
    '아이디/아이피가 자동으로 표기됩니다]</strong>'
)
NORMAL = '<div class="xe_content"><p>일반 글 본문.</p></div>'

def test_is_repost_blocked_detects_marker():
    assert _is_repost_blocked(BLOCKED) is True
    assert _is_repost_blocked(NORMAL) is False

def test_extract_original_url_from_plaintext_body():
    assert _extract_original_url(BLOCKED, ".xe_content") == \
        "https://m.gianlucadimarzio.com/calciomercato/juve-lucumi-493366"

def test_extract_original_url_none_when_no_external_link():
    assert _extract_original_url(NORMAL, ".xe_content") is None

from bullet_in.adapters.fmkorea import _fetch_og_description

OG_HTML = (
    '<html><head>'
    '<meta property="og:title" content="La Juventus vuole Lucum&iacute;">'
    '<meta property="og:description" content="I bianconeri vogliono il '
    'difensore colombiano del Bologna.">'
    '</head><body></body></html>'
)
META_ONLY = ('<html><head><meta name="description" content="Solo meta desc.">'
             '</head></html>')

@respx.mock
def test_fetch_og_description_prefers_og():
    respx.get("https://orig.test/a").mock(return_value=httpx.Response(200, text=OG_HTML))
    async def run():
        async with httpx.AsyncClient() as c:
            return await _fetch_og_description(c, "https://orig.test/a")
    assert asyncio.run(run()) == "I bianconeri vogliono il difensore colombiano del Bologna."

@respx.mock
def test_fetch_og_description_falls_back_to_meta():
    respx.get("https://orig.test/b").mock(return_value=httpx.Response(200, text=META_ONLY))
    async def run():
        async with httpx.AsyncClient() as c:
            return await _fetch_og_description(c, "https://orig.test/b")
    assert asyncio.run(run()) == "Solo meta desc."

@respx.mock
def test_fetch_og_description_none_on_http_error():
    respx.get("https://orig.test/c").mock(return_value=httpx.Response(404))
    async def run():
        async with httpx.AsyncClient() as c:
            return await _fetch_og_description(c, "https://orig.test/c")
    assert asyncio.run(run()) is None
