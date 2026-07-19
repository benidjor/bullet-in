import asyncio, respx, httpx
from bullet_in.adapters.fmkorea import FmkoreaAdapter, parse_bracket, _post_url_from_href

SEARCH_KW1 = ('<a class="hx" href="/index.php?document_srl=111">[BBC] 아스날 A</a>'
              '<a class="replyNum" href="/index.php?document_srl=111#c">3</a>'
              '<a class="hx" href="/index.php?document_srl=222">[디 애슬레틱] 아스날 B</a>')
SEARCH_KW2 = ('<a class="hx" href="/index.php?document_srl=222">[디 애슬레틱] 아스날 B</a>'
              '<a class="hx" href="/index.php?document_srl=333">[더 선] 아스날 C</a>')
FREE_BODY = ('<div class="xe_content"><p>아스날 본문.</p>'
             '<p>https://ex.test/a</p></div>')
PAY_BODY = ('<div class="xe_content"><p>아스날 본문.</p>'
            '<p>https://www.nytimes.com/athletic/9/b</p></div>')
FREE_ART = '<html><body><article><p>Arsenal news.</p></article></body></html>'

@respx.mock
def test_fmkorea_search_union_dedup():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=SEARCH_KW1))
    respx.get("https://fm.test/s?t=title_content&kw=kw2").mock(return_value=httpx.Response(200, text=SEARCH_KW2))
    respx.get("https://www.fmkorea.com/111").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://www.fmkorea.com/222").mock(return_value=httpx.Response(200, text=PAY_BODY))
    respx.get("https://www.fmkorea.com/333").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"},
                                        {"keyword": "kw2", "target": "title_content"}],
                       base_url="https://www.fmkorea.com")
    items = asyncio.run(a.fetch())
    assert len(items) == 3
    pay = next(i for i in items if "athletic" in i.url)
    assert pay.raw_payload["outlet"] == "The Athletic"
    assert pay.raw_payload["lang"] == "ko"

@respx.mock
def test_fmkorea_search_respects_max_posts():
    html = ('<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
            '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>'
            '<a class="hx" href="/index.php?document_srl=3">[BBC] 아스날 3</a>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=html))
    for n in (1, 2, 3):
        respx.get(f"https://www.fmkorea.com/{n}").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com", max_posts=2)
    assert len(asyncio.run(a.fetch())) == 2

@respx.mock
def test_fmkorea_search_429_skips_keyword_continues(caplog):
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(429))
    respx.get("https://fm.test/s?t=title_content&kw=kw2").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=9">[BBC] 아스날</a>'))
    respx.get("https://www.fmkorea.com/9").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"},
                                        {"keyword": "kw2", "target": "title_content"}],
                       base_url="https://www.fmkorea.com")
    with caplog.at_level("WARNING"):
        items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert any("429" in r.message for r in caplog.records)

@respx.mock
def test_fmkorea_round_robin_represents_all_keywords():
    # kw1 이 결과를 많이 내도, max_posts 안에서 kw2 도 대표돼야 한다 (앞 키워드 독식 금지)
    kw1_html = "".join(f'<a class="hx" href="/index.php?document_srl=10{n}">[BBC] 아스날 A{n}</a>' for n in range(5))
    kw2_html = "".join(f'<a class="hx" href="/index.php?document_srl=20{n}">[BBC] 아스날 B{n}</a>' for n in range(5))
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=kw1_html))
    respx.get("https://fm.test/s?t=title_content&kw=kw2").mock(return_value=httpx.Response(200, text=kw2_html))
    import re as _re
    def body_for(srl):
        return (f'<div class="xe_content"><p>아스날 본문.</p>'
                f'<p>https://ex.test/{srl}</p></div>')
    for m in _re.finditer(r"document_srl=(\d+)", kw1_html + kw2_html):
        srl = m.group(1)
        respx.get(f"https://www.fmkorea.com/{srl}").mock(return_value=httpx.Response(200, text=body_for(srl)))
        respx.get(f"https://ex.test/{srl}").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"},
                                        {"keyword": "kw2", "target": "title_content"}],
                       base_url="https://www.fmkorea.com", max_posts=4)
    urls = {i.url for i in asyncio.run(a.fetch())}
    # 총 4건, kw1(10x)·kw2(20x) 양쪽이 대표돼야 함
    assert len(urls) == 4
    assert any("/10" in u for u in urls) and any("/20" in u for u in urls)

@respx.mock
def test_fmkorea_non_429_error_skips_keyword_continues(caplog):
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(403))
    respx.get("https://fm.test/s?t=title_content&kw=kw2").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=9">[BBC] 아스날</a>'))
    respx.get("https://www.fmkorea.com/9").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"},
                                        {"keyword": "kw2", "target": "title_content"}],
                       base_url="https://www.fmkorea.com")
    with caplog.at_level("WARNING"):
        items = asyncio.run(a.fetch())
    assert len(items) == 1  # kw1 403 스킵, kw2 수집 보존
    assert any("403" in r.message for r in caplog.records)

@respx.mock
def test_fmkorea_skips_post_when_body_fetch_fails():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 속보</a>'))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(500))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
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

def test_parse_bracket_outlet_and_journalist():
    assert parse_bracket("[BBC - 사미 목벨] 토트넘, 페르난데스 영입 추진") == ("BBC", "사미 목벨", False)

def test_parse_bracket_normalizes_korean_outlet():
    assert parse_bracket("[디 애슬레틱 - 온스테인] 앤더슨 결장") == ("The Athletic", "온스테인", False)

def test_parse_bracket_exclusive_flag():
    assert parse_bracket("[디 애슬레틱-독점] 디오망데 PSG 선택") == ("The Athletic", None, True)

def test_parse_bracket_outlet_only():
    assert parse_bracket("[텔레그래프] 요케레스 영입 완료") == ("The Telegraph", None, False)

def test_parse_bracket_official_prefix_not_mapped():
    # 공홈 말머리 매핑 제거 (2026-07-19) — 아스날 공홈은 직수집(arsenal_api)이 커버,
    # 타 구단 공홈 오귀속(tier 0) 차단. drop 은 _process 몫 (아래 어댑터 테스트).
    assert parse_bracket("[공홈] 요케레스 영입 완료") == ("공홈", None, False)

def test_parse_bracket_no_bracket():
    assert parse_bracket("Arsenal target identified") == (None, None, False)

@respx.mock
def test_fmkorea_paywalled_keeps_korean_body_and_outlet():
    search_html = '<a class="hx" href="/index.php?document_srl=1">[디 애슬레틱 - 온스테인] 아스날 수비수 보강</a>'
    body = ('<div class="xe_content"><p>아스날이 센터백을 원한다.</p>'
            '<p>https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/</p></div>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=search_html))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=body))
    respx.get("https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/").mock(
        return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/"
    assert it.raw_payload["outlet"] == "The Athletic"
    assert it.raw_payload["journalist"] == "온스테인"
    assert it.raw_payload["lang"] == "ko"
    assert "센터백" in it.raw_payload["body"]

@respx.mock
def test_fmkorea_free_outlet_fetches_original_english_body():
    search_html = '<a class="hx" href="/index.php?document_srl=1">[BBC - 사미 목벨] 아스날 요케레스 영입</a>'
    body = ('<div class="xe_content"><p>아스날이 요케레스를 영입한다.</p>'
            '<p>https://www.bbc.com/sport/football/articles/gyo</p></div>')
    original = ('<html><head><meta property="og:image" content="https://img.bbc/g.jpg"></head>'
                '<body><article><p>Arsenal have signed Gyokeres.</p>'
                '<p>The fee is 60m.</p></article></body></html>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=search_html))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=body))
    respx.get("https://www.bbc.com/sport/football/articles/gyo").mock(
        return_value=httpx.Response(200, text=original))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    it = asyncio.run(a.fetch())[0]
    assert it.url == "https://www.bbc.com/sport/football/articles/gyo"
    assert it.raw_payload["outlet"] == "BBC"
    assert it.raw_payload["lang"] == "en"
    assert "Arsenal have signed Gyokeres." in it.raw_payload["body"]   # 원문 영어 본문
    assert it.raw_payload["image_url"] == "https://img.bbc/g.jpg"

@respx.mock
def test_fmkorea_skips_when_no_original_url(caplog):
    search_html = '<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 소식</a>'
    body = '<div class="xe_content"><p>출처 링크 없는 본문.</p></div>'
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=search_html))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=body))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    with caplog.at_level("WARNING"):
        items = asyncio.run(a.fetch())
    assert items == []
    assert any("원문" in r.message or "skip" in r.message.lower() for r in caplog.records)

def test_parse_bracket_athletic_rae_variant():
    # '디 애슬래틱'(래) 변종도 The Athletic 으로 정규화
    assert parse_bracket("[디 애슬래틱] 아스날 0-2 맨시티")[0] == "The Athletic"

def test_parse_bracket_athletic_english_literal():
    assert parse_bracket("[The Athletic] 아스날 재계약")[0] == "The Athletic"

def test_post_url_from_document_srl_query():
    href = "/index.php?mid=football_news&document_srl=10035196191&search_keyword=x&page=1"
    assert _post_url_from_href(href, "https://www.fmkorea.com") == \
        "https://www.fmkorea.com/10035196191"

def test_post_url_from_clean_path():
    assert _post_url_from_href("/10035196191", "https://www.fmkorea.com") == \
        "https://www.fmkorea.com/10035196191"

def test_post_url_none_when_no_srl():
    assert _post_url_from_href("/index.php?mid=football_news&act=dispBoard",
                               "https://www.fmkorea.com") is None

FREE_ART_IMG = ('<html><body><article><p>Arsenal news.</p>'
                '<img src="https://art.test/1.jpg"></article></body></html>')
PAY_BODY_IMG = ('<div class="xe_content"><p>아스날 본문.</p>'
                '<img src="https://fmimg.test/p.jpg">'
                '<p>https://www.nytimes.com/athletic/9/b</p></div>')

@respx.mock
def test_fmkorea_free_path_collects_original_article_images():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날</a>'))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART_IMG))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["images"] == ["https://art.test/1.jpg"]

@respx.mock
def test_fmkorea_paywalled_path_collects_post_images():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=2">[디 애슬레틱] 아스날</a>'))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(200, text=PAY_BODY_IMG))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(
        return_value=httpx.Response(200, text="<html></html>"))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["images"] == ["https://fmimg.test/p.jpg"]

@respx.mock
def test_fmkorea_drops_official_prefix_posts():
    # [공홈]·[아스날 공홈]·[맨유 공홈] 전부 drop — 아스날 공홈은 직수집 경로가 커버, 타 구단은 범위 밖
    html = ('<a class="hx" href="/index.php?document_srl=1">[공홈] 아스날, 멜리에 영입</a>'
            '<a class="hx" href="/index.php?document_srl=2">[맨유 공홈] 산투스 영입</a>'
            '<a class="hx" href="/index.php?document_srl=3">[BBC] 아스날 이적 소식</a>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=html))
    for n in (1, 2, 3):
        respx.get(f"https://www.fmkorea.com/{n}").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    items = asyncio.run(a.fetch())
    assert [i.raw_payload["outlet"] for i in items] == ["BBC"]
