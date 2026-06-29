import asyncio, respx, httpx
from bullet_in.adapters.fmkorea import FmkoreaAdapter, parse_bracket

LIST = '''
<a class="title" href="/1">[디 애슬레틱] 아스날 사카 재계약 임박</a>
<a class="title" href="/2">[BBC] 첼시 이적 소식</a>
<a class="title" href="/3">[BBC - 사미 목벨] Arsenal target identified</a>
'''
BODY1 = ('<div class="xe_content">온스테인에 따르면 사카가 재계약한다.'
         ' https://www.nytimes.com/athletic/123/saka/</div>')
BODY3 = ('<div class="xe_content">Arsenal scout report.'
         ' https://www.bbc.com/sport/football/x</div>')
BBC_ART = ('<html><body><article>'
           '<p>Arsenal scout seen at the stadium.</p>'
           '</article></body></html>')

@respx.mock
def test_fmkorea_filters_by_keyword_and_fetches_body():
    respx.get("https://fm.test/football_news").mock(
        return_value=httpx.Response(200, text=LIST))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=BODY1))
    respx.get("https://fm.test/3").mock(return_value=httpx.Response(200, text=BODY3))
    respx.get("https://www.bbc.com/sport/football/x").mock(
        return_value=httpx.Response(200, text=BBC_ART))
    # Athletic original — _fetch_og_image 호출용 (paywalled; og:image 없어도 무방)
    respx.get("https://www.nytimes.com/athletic/123/saka/").mock(
        return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날", "Arsenal"],
                       base_url="https://fm.test", body_selector=".xe_content")
    items = asyncio.run(a.fetch())
    urls = {i.url for i in items}
    # [BBC] 첼시 글 제외; 원문 URL 로 치환됨
    assert urls == {
        "https://www.nytimes.com/athletic/123/saka/",
        "https://www.bbc.com/sport/football/x",
    }
    one = next(i for i in items if "athletic" in i.url)
    assert one.raw_payload["title"].startswith("[디 애슬레틱]")
    assert "온스테인" in one.raw_payload["body"]   # paywalled → fmkorea 번역본 유지
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

from bullet_in.adapters.fmkorea import _extract_original_url

BLOCKED = (
    '<div class="xe_content"><p>유벤투스가 루쿠미를 원한다.</p><p></p>'
    '<p>https://m.gianlucadimarzio.com/calciomercato/juve-lucumi-493366</p></div>'
    '<!--AfterDocument(1,2)--></article>'
    '<strong>[퍼가기가 금지된 글입니다 - 캡처 방지 위해 글 열람 사용자 '
    '아이디/아이피가 자동으로 표기됩니다]</strong>'
)
NORMAL = '<div class="xe_content"><p>일반 글 본문.</p></div>'

def test_extract_original_url_from_plaintext_body():
    assert _extract_original_url(BLOCKED, ".xe_content") == \
        "https://m.gianlucadimarzio.com/calciomercato/juve-lucumi-493366"

def test_extract_original_url_none_when_no_external_link():
    assert _extract_original_url(NORMAL, ".xe_content") is None

def test_extract_original_url_prefers_trailing_plaintext_over_author_anchor():
    # 실측 post 10007542458: 본문에 기자 프로필 앵커 + 끝에 평문 기사 URL
    html = ('<div class="xe_content">'
            '<p>By <a href="https://www.nytimes.com/athletic/author/david-ornstein/">'
            'David Ornstein</a> 앤더슨 결장.</p>'
            '<p>https://www.nytimes.com/athletic/7398614/2026/06/26/england-anderson/</p>'
            '</div>')
    assert _extract_original_url(html, ".xe_content") == \
        "https://www.nytimes.com/athletic/7398614/2026/06/26/england-anderson/"

def test_extract_original_url_uses_anchor_when_no_plaintext():
    html = ('<div class="xe_content"><p>출처: '
            '<a href="https://www.bbc.com/sport/football/articles/abc">BBC</a></p></div>')
    assert _extract_original_url(html, ".xe_content") == \
        "https://www.bbc.com/sport/football/articles/abc"

@respx.mock
def test_fetch_returns_empty_on_list_429(caplog):
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(429))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"],
                       base_url="https://fm.test", body_selector=".xe_content")
    with caplog.at_level("WARNING"):
        assert asyncio.run(a.fetch()) == []
    assert any("429" in r.message for r in caplog.records)

def test_parse_bracket_outlet_and_journalist():
    assert parse_bracket("[BBC - 사미 목벨] 토트넘, 페르난데스 영입 추진") == ("BBC", "사미 목벨", False)

def test_parse_bracket_normalizes_korean_outlet():
    assert parse_bracket("[디 애슬레틱 - 온스테인] 앤더슨 결장") == ("The Athletic", "온스테인", False)

def test_parse_bracket_exclusive_flag():
    assert parse_bracket("[디 애슬레틱-독점] 디오망데 PSG 선택") == ("The Athletic", None, True)

def test_parse_bracket_outlet_only():
    assert parse_bracket("[공홈] 요케레스 영입 완료") == ("공홈", None, False)

def test_parse_bracket_no_bracket():
    assert parse_bracket("Arsenal target identified") == (None, None, False)

@respx.mock
def test_fmkorea_paywalled_keeps_korean_body_and_outlet():
    list_html = '<a class="title" href="/1">[디 애슬레틱 - 온스테인] 아스날 수비수 보강</a>'
    body = ('<div class="xe_content"><p>아스날이 센터백을 원한다.</p>'
            '<p>https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/</p></div>')
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=body))
    # Athletic original — _fetch_og_image 호출용
    respx.get("https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/").mock(
        return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"], base_url="https://fm.test")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/"
    assert it.raw_payload["outlet"] == "The Athletic"
    assert it.raw_payload["journalist"] == "온스테인"
    assert it.raw_payload["lang"] == "ko"
    assert "센터백" in it.raw_payload["body"]   # 디 애슬레틱: fmkorea 번역본 유지

@respx.mock
def test_fmkorea_free_outlet_fetches_original_english_body():
    list_html = '<a class="title" href="/1">[BBC - 사미 목벨] 아스날 요케레스 영입</a>'
    body = ('<div class="xe_content"><p>아스날이 요케레스를 영입한다.</p>'
            '<p>https://www.bbc.com/sport/football/articles/gyo</p></div>')
    original = ('<html><head><meta property="og:image" content="https://img.bbc/g.jpg"></head>'
                '<body><article><p>Arsenal have signed Gyokeres.</p>'
                '<p>The fee is 60m.</p></article></body></html>')
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=body))
    respx.get("https://www.bbc.com/sport/football/articles/gyo").mock(
        return_value=httpx.Response(200, text=original))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"], base_url="https://fm.test")
    it = asyncio.run(a.fetch())[0]
    assert it.url == "https://www.bbc.com/sport/football/articles/gyo"
    assert it.raw_payload["outlet"] == "BBC"
    assert it.raw_payload["lang"] == "en"
    assert "Arsenal have signed Gyokeres." in it.raw_payload["body"]   # 원문 영어 본문
    assert it.raw_payload["image_url"] == "https://img.bbc/g.jpg"

@respx.mock
def test_fmkorea_skips_when_no_original_url(caplog):
    list_html = '<a class="title" href="/1">[BBC] 아스날 소식</a>'
    body = '<div class="xe_content"><p>출처 링크 없는 본문.</p></div>'
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=body))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"], base_url="https://fm.test")
    with caplog.at_level("WARNING"):
        items = asyncio.run(a.fetch())
    assert items == []
    assert any("원문" in r.message or "skip" in r.message.lower() for r in caplog.records)
