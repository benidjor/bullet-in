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
FREE_ART = ('<html><body><article><p>Arsenal have secured a significant victory in ongoing transfer '
            'negotiations this summer. The club management completed the acquisition of a key midfielder '
            'who brings valuable experience and technical skills to strengthen the squad. This strategic '
            'signing reinforces Arsenal position in the Premier League competition. The player brings '
            'international experience having played for multiple top clubs across Europe and other leagues. '
            'The announcement was made during a comprehensive press conference where the coaching staff '
            'expressed satisfaction with the completed transfer. Fans have reacted positively to this news '
            'on social media platforms.</p></article></body></html>')

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

def test_parse_bracket_dandok_is_exclusive_marker_not_journalist():
    # 표식 어휘 드리프트 실사례 (2026-07-26): "[디 애슬레틱-단독]" 의 "단독" 이
    # 기자명으로 오파싱돼 기자 = "단독" 으로 서빙됨 (8651f026)
    assert parse_bracket("[디 애슬레틱-단독]아스날, 비니시우스 주니오르 영입 검토") == \
        ("The Athletic", None, True)

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
                '<body><article><p>Arsenal have signed Gyokeres following successful negotiations with his previous club. '
                'The fee is reported to be sixty million pounds sterling which makes it a significant investment. '
                'The Swedish striker brings valuable experience from European football. '
                'He is expected to strengthen the team significantly in the coming season. '
                'The deal was finalized after weeks of intensive discussions. '
                'The player has already begun training with the squad.</p></article></body></html>')
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
    assert "Arsenal have signed Gyokeres" in it.raw_payload["body"]   # 원문 영어 본문
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

FREE_ART_IMG = ('<html><body><article><p>Arsenal news and updates about the team performance. '
                'The club has made significant signings to strengthen the squad. '
                'These acquisitions represent a strong commitment to competition. '
                'The coaching staff expressed enthusiasm about the new roster. '
                'Fans anticipate an exciting season ahead with these additions.</p>'
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

from bullet_in.adapters.fmkorea import _is_repost_blocked

# 실측 DOM (2026-07-19, post 9940576222): 표식 strong 은 .rd_body 직하위 · 본문(.xe_content) 밖
_BLOCK_STRONG = ('<strong>[퍼가기가 금지된 글입니다 - 캡처 방지 위해 글 열람 사용자 '
                 '아이디/아이피가 자동으로 표기됩니다]</strong>')

def _post_html(body_inner: str, blocked: bool = False) -> str:
    return ('<div class="rd_body clear">'
            + (_BLOCK_STRONG if blocked else "")
            + f'<article><div class="xe_content">{body_inner}</div></article>'
            '</div>')

def test_is_repost_blocked_detects_marker_outside_body():
    html = _post_html('<p>번역 본문.</p>', blocked=True)
    assert _is_repost_blocked(html) is True

def test_is_repost_blocked_false_on_normal_post():
    html = _post_html('<p>일반 글 본문.</p>')
    assert _is_repost_blocked(html) is False

def test_is_repost_blocked_false_when_phrase_quoted_inside_body():
    # 본문이 표식 문구를 인용해도 (xe_content 내부) 오탐하지 않는다
    html = _post_html('<p><strong>퍼가기가 금지된 글입니다</strong> 라는 표식이 붙는다.</p>')
    assert _is_repost_blocked(html) is False

BLOCKED_PAY_POST = _post_html(
    '<p>아스날이 센터백을 원한다.</p>'
    '<img src="https://fmimg.test/p.jpg">'
    '<p>https://www.nytimes.com/athletic/9/b</p>', blocked=True)

@respx.mock
def test_fmkorea_blocked_paywalled_keeps_post_body(caplog):
    # E안: 퍼가기 금지 + 페이월 → 게시글 본문 채택 · 게시글 이미지 제외
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=2">[디 애슬레틱 - 온스테인] 아스날 수비수 보강</a>'))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(200, text=BLOCKED_PAY_POST))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(
        200, text='<html><head><meta property="og:image" content="https://img.nyt/a.jpg"></head></html>'))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    with caplog.at_level("INFO"):
        items = asyncio.run(a.fetch())
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://www.nytimes.com/athletic/9/b"
    assert "아스날이 센터백을 원한다." in it.raw_payload["body"]  # fmkorea 게시글 본문 채택
    assert it.raw_payload["images"] == []          # 게시글 이미지 제외
    assert it.raw_payload["body_level"] == 1       # 게시글 본문
    assert it.raw_payload["image_url"] == "https://img.nyt/a.jpg"   # og 이미지는 원문에서
    assert it.raw_payload["outlet"] == "The Athletic"
    assert it.raw_payload["journalist"] == "온스테인"
    assert it.raw_payload["lang"] == "ko"
    assert any("퍼가기" in r.message for r in caplog.records)

@respx.mock
def test_fmkorea_blocked_free_outlet_keeps_original_body():
    # 퍼가기 금지 + 무료 → 현행 무료 분기 그대로 (원문 en 본문, fmkorea 본문 원래 미복제)
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날</a>'))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(
        200, text=_post_html('<p>아스날 본문.</p><p>https://ex.test/a</p>', blocked=True)))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    it = asyncio.run(a.fetch())[0]
    assert it.raw_payload["lang"] == "en"
    assert "Arsenal have secured a significant victory" in it.raw_payload["body"]

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

from datetime import datetime, timezone
from bullet_in.adapters.fmkorea import _post_published

RD_HD = ('<div class="rd_hd"><div class="board clear">'
         '<span class="date m_no">2026.06.11 10:04</span></div></div>')

def test_post_published_parses_kst_to_utc():
    html = f'<html><body>{RD_HD}</body></html>'
    assert _post_published(html) == datetime(2026, 6, 11, 1, 4, tzinfo=timezone.utc)

def test_post_published_none_when_absent():
    assert _post_published("<html><body></body></html>") is None

@respx.mock
def test_fmkorea_free_path_uses_original_published():
    art = ('<html><head><script type="application/ld+json">'
           '{"datePublished":"2026-07-19T08:00:00Z"}</script></head>'
           '<body><article><p>Arsenal news and updates. The team continues to show strong performance. '
           'Recent signings have made a significant impact on the squad dynamics. '
           'The coaching staff remains optimistic about the season. '
           'Fans have expressed positive reactions to the current form. '
           'The next match is scheduled for this weekend.</p></article></body></html>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날</a>'))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(
        200, text=f'{RD_HD}<div class="xe_content"><p>본문.</p><p>https://ex.test/a</p></div>'))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=art))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    it = asyncio.run(a.fetch())[0]
    assert it.raw_payload["published"] == "2026-07-19T08:00:00+00:00"
    assert it.raw_payload["published_precision"] == "time"

@respx.mock
def test_fmkorea_paywalled_path_uses_post_time():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=2">[디 애슬레틱] 아스날</a>'))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(
        200, text=f'{RD_HD}<div class="xe_content"><p>본문.</p>'
                  '<p>https://www.nytimes.com/athletic/9/b</p></div>'))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(
        return_value=httpx.Response(200, text="<html></html>"))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    it = asyncio.run(a.fetch())[0]
    # KST 2026.06.11 10:04 → UTC 01:04
    assert it.raw_payload["published"] == "2026-06-11T01:04:00+00:00"
    assert it.raw_payload["published_precision"] == "time"

import httpx as _httpx
from bullet_in.adapters.fmkorea import FmkoreaAdapter as _FA

def test_fmkorea_adapter_stores_proxy():
    a = _FA(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
            search_keywords=[], proxy="socks5://127.0.0.1:1080")
    assert a.proxy == "socks5://127.0.0.1:1080"

def test_fmkorea_adapter_proxy_defaults_none():
    a = _FA(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
            search_keywords=[])
    assert a.proxy is None

@respx.mock
def test_fmkorea_fetch_passes_proxy_to_client(monkeypatch):
    seen = {}
    orig = _httpx.AsyncClient
    def spy(*args, **kwargs):
        seen["proxy"] = kwargs.get("proxy")
        return orig(*args, **kwargs)
    monkeypatch.setattr(_httpx, "AsyncClient", spy)
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=""))
    a = _FA(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
            search_keywords=[{"keyword": "kw1", "target": "title"}],
            base_url="https://www.fmkorea.com", proxy="socks5://127.0.0.1:1080")
    asyncio.run(a.fetch())
    assert seen["proxy"] == "socks5://127.0.0.1:1080"

@respx.mock
def test_fmkorea_discovers_across_pages():
    p1 = '<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
    p2 = '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>'
    respx.get("https://fm.test/s?t=title&kw=kw1&p=1").mock(return_value=httpx.Response(200, text=p1))
    respx.get("https://fm.test/s?t=title&kw=kw1&p=2").mock(return_value=httpx.Response(200, text=p2))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}&p={page}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com", pages=2)
    found = asyncio.run(a.discover())
    assert [t for t, _ in found] == ["[BBC] 아스날 1", "[BBC] 아스날 2"]


@respx.mock
def test_fmkorea_single_page_by_default():
    p1 = '<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
    route = respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        return_value=httpx.Response(200, text=p1))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    found = asyncio.run(a.discover())
    assert route.call_count == 1
    assert len(found) == 1


@respx.mock
def test_fmkorea_page_error_keeps_earlier_pages_and_next_keyword(caplog):
    p1 = '<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
    p2 = '<a class="hx" href="/index.php?document_srl=9">[BBC] 아스날 9</a>'
    respx.get("https://fm.test/s?t=title&kw=kw1&p=1").mock(return_value=httpx.Response(200, text=p1))
    respx.get("https://fm.test/s?t=title&kw=kw1&p=2").mock(return_value=httpx.Response(429))
    respx.get("https://fm.test/s?t=title&kw=kw2&p=1").mock(return_value=httpx.Response(200, text=p2))
    respx.get("https://fm.test/s?t=title&kw=kw2&p=2").mock(return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}&p={page}",
                       search_keywords=[{"keyword": "kw1", "target": "title"},
                                        {"keyword": "kw2", "target": "title"}],
                       base_url="https://www.fmkorea.com", pages=2)
    found = asyncio.run(a.discover())
    titles = {t for t, _ in found}
    assert titles == {"[BBC] 아스날 1", "[BBC] 아스날 9"}
    assert "429" in caplog.text


@respx.mock
def test_fmkorea_excludes_known_titles_without_fetching():
    html = ('<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
            '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=html))
    known = respx.get("https://www.fmkorea.com/1").mock(
        return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com",
                       exclude_titles={"[BBC] 아스날 1"})
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert known.call_count == 0          # 이미 있는 글은 접촉하지 않는다


@respx.mock
def test_fmkorea_exclusion_frees_max_posts_slots():
    html = ('<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
            '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>'
            '<a class="hx" href="/index.php?document_srl=3">[BBC] 아스날 3</a>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=html))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com", max_posts=2,
                       exclude_titles={"[BBC] 아스날 1"})
    found = asyncio.run(a.discover())
    assert [t for t, _ in found] == ["[BBC] 아스날 2", "[BBC] 아스날 3"]


@respx.mock
def test_fmkorea_sleeps_between_requests(monkeypatch):
    slept = []
    async def fake_sleep(sec):
        slept.append(sec)
    monkeypatch.setattr("bullet_in.adapters.fmkorea.asyncio.sleep", fake_sleep)
    p1 = '<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
    p2 = '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>'
    respx.get("https://fm.test/s?t=title&kw=kw1&p=1").mock(return_value=httpx.Response(200, text=p1))
    respx.get("https://fm.test/s?t=title&kw=kw1&p=2").mock(return_value=httpx.Response(200, text=p2))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}&p={page}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com", pages=2, request_gap_sec=1.5)
    asyncio.run(a.fetch())
    # 검색 2페이지 사이 1회 + 글 2건 사이 1회
    assert slept == [1.5, 1.5]


@respx.mock
def test_fmkorea_no_sleep_when_gap_zero(monkeypatch):
    slept = []
    async def fake_sleep(sec):
        slept.append(sec)
    monkeypatch.setattr("bullet_in.adapters.fmkorea.asyncio.sleep", fake_sleep)
    html = ('<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
            '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=html))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    asyncio.run(a.fetch())
    assert slept == []


# --- 바이라인 처리 (순수 함수 둘 · 호출 순서 무관) ---
# 시험 사례는 실측에서 뽑았다 (bulletin_mock 2026-07-27 사본 · fmkorea 본문 98건).

from bullet_in.adapters.fmkorea import strip_publish_datetime, extract_body_journalist


def test_strip_publish_datetime_removes_byline_date_and_time():
    body = "By David Ornstein June 19, 2026 3:19 am 리버풀이 RB 라이프치히와 협상 중이다."
    assert strip_publish_datetime(body) == "By David Ornstein 리버풀이 RB 라이프치히와 협상 중이다."


def test_strip_publish_datetime_removes_updated_time_form():
    body = ("By James McNicholas and Art de Roché July 3, 2026 Updated 2:46 am "
            "아스날이 파스칼 드 마샬크를 선임했다.")
    assert strip_publish_datetime(body) == (
        "By James McNicholas and Art de Roché 아스날이 파스칼 드 마샬크를 선임했다.")


def test_strip_publish_datetime_keeps_journalist_name():
    # 기자명을 지우면 fmkorea tier 가 본문 스캔을 잃는다 (합의 2026-07-29)
    body = "By Art de Roché May 18, 2026 1:20 pm 미켈 아르테타 감독은 팬들과의 관계를 강조해왔다."
    out = strip_publish_datetime(body)
    assert "Art de Roché" in out
    assert "May 18, 2026" not in out and "1:20 pm" not in out


def test_strip_publish_datetime_keeps_quoted_tweet_timestamp():
    # 실측 7c2a0a1e — 200자 밖 인용 트윗 작성 시각 3건이 전부 여기 있었다
    lead = "아스날의 2014년 여름을 돌아본다. " * 12          # 200자 넘기기
    body = lead + "— UEFA Champions League (@ChampionsLeague) March 4, 2019 벵거 시절."
    assert strip_publish_datetime(body) == body


def test_strip_publish_datetime_keeps_korean_date_notation():
    body = "디 애슬레틱은 지난 6월 24일, 브라힘 디아스가 아스날행을 원한다고 보도했다."
    assert strip_publish_datetime(body) == body


def test_strip_publish_datetime_keeps_year_inside_sentence():
    body = "2030년까지 계약이 남아 있는 디오망데는 이번 여름 이적을 고려하지 않는다."
    assert strip_publish_datetime(body) == body


def test_strip_publish_datetime_keeps_article_years_after_byline():
    body = "By Art de Roché 미켈 아르테타 감독은 2019 년 12 월 지휘봉을 잡았다."
    assert strip_publish_datetime(body) == body


def test_extract_body_journalist_reads_leading_byline():
    body = "By David Ornstein June 19, 2026 3:19 am 리버풀이 협상 중이다."
    assert extract_body_journalist(body) == "David Ornstein"


def test_extract_body_journalist_takes_first_of_coauthors():
    # journalist 컬럼은 단일 문자열 — 대표 1명 (공저자 다중 귀속은 별도 트랙)
    body = "By James McNicholas and Art de Roché July 3, 2026 Updated 2:46 am 아스날이"
    assert extract_body_journalist(body) == "James McNicholas"


def test_extract_body_journalist_reads_byline_after_caption():
    # 실측 19건 중 11건은 게시글 캡션 뒤에 바이라인이 온다 (본문 첫 글자 아님)
    body = ("훌리안 알바레스(왼쪽)와 엘리 주니오르 크루피 By Art de Roché July 17, 2026 "
            "1:16 pm 작년 이맘때 센터포워드는 아스날의 고민거리였다.")
    assert extract_body_journalist(body) == "Art de Roché"


def test_extract_body_journalist_stops_at_line_break():
    # 실측 3건 (데일리 메일) — 개행 뒤 'Published' 가 이름에 붙으면 안 된다
    body = "By SIMON JONES\n\nPublished: 17:30 GMT, 20 July 2026 아스날이"
    assert extract_body_journalist(body) == "SIMON JONES"


def test_extract_body_journalist_returns_none_without_byline():
    assert extract_body_journalist("아스날이 비니시우스 주니오르 영입을 추진한다.") is None


def test_extract_body_journalist_does_not_change_body():
    # 추출 전용 — 본문 변경은 strip_publish_datetime 의 일 (순서 무관 계약)
    body = "By David Ornstein June 19, 2026 3:19 am 본문."
    extract_body_journalist(body)
    assert body == "By David Ornstein June 19, 2026 3:19 am 본문."


# --- 본문 출처 등급 명시 · 바이라인 적용 (어댑터) ---

PAY_BYLINE_BODY = (
    '<div class="xe_content"><p>비니시우스는 레알에서 8시즌 활약했다 '
    'By David Ornstein June 19, 2026 3:19 am 아스날이 영입을 추진한다.</p>'
    '<p>https://www.nytimes.com/athletic/9/b</p></div>')


def _one_post(post_html: str, title: str = "[디 애슬레틱] 아스날 소식"):
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text=f'<a class="hx" href="/index.php?document_srl=1">{title}</a>'))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=post_html))
    return FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                          search_keywords=[{"keyword": "kw1", "target": "title"}],
                          base_url="https://www.fmkorea.com")


@respx.mock
def test_fmkorea_declares_post_body_level_on_paywalled_path():
    # 페이월 경로가 채택하는 재료는 게시글 본문 (_body_text) → 등급 1
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(200, text=""))
    items = asyncio.run(_one_post(PAY_BODY).fetch())
    assert items[0].raw_payload["body_level"] == 1


@respx.mock
def test_fmkorea_declares_outlet_body_level_on_free_path():
    # 원문 URL 에서 받은 본문 (extract_article_body) → 등급 2
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    items = asyncio.run(_one_post(FREE_BODY, title="[BBC] 아스날 소식").fetch())
    assert items[0].raw_payload["body_level"] == 2


@respx.mock
def test_fmkorea_keeps_original_url_when_falling_back_to_post_body():
    # 게시글 본문을 채택해도 (등급 1) url 은 원문 기사 URL 로 남겨 둔다 — 등급 2 로
    # 올려 줄 재수집 경로가 계속 열려 있어야 한다 (스펙 §4.1 · §4.7 사다리)
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(500))
    items = asyncio.run(_one_post(FREE_BODY, title="[BBC] 아스날 소식").fetch())
    assert items[0].url == "https://ex.test/a"
    assert items[0].raw_payload["body_level"] == 1


@respx.mock
def test_fmkorea_declares_post_level_when_repost_blocked():
    respx.get("https://www.nytimes.com/athletic/9/b").mock(
        return_value=httpx.Response(200, text=""))
    items = asyncio.run(_one_post(BLOCKED_PAY_POST).fetch())
    assert "아스날이 센터백을 원한다." in items[0].raw_payload["body"]  # 게시글 본문 채택
    assert items[0].raw_payload["body_level"] == 1  # 게시글 본문


@respx.mock
def test_fmkorea_strips_publish_datetime_from_collected_body():
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(200, text=""))
    body = asyncio.run(_one_post(PAY_BYLINE_BODY).fetch())[0].raw_payload["body"]
    assert "June 19, 2026" not in body and "3:19 am" not in body
    assert "By David Ornstein" in body


@respx.mock
def test_fmkorea_fills_journalist_from_body_when_bracket_has_none():
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(200, text=""))
    items = asyncio.run(_one_post(PAY_BYLINE_BODY).fetch())
    assert items[0].raw_payload["journalist"] == "David Ornstein"


@respx.mock
def test_fmkorea_keeps_bracket_journalist_over_body_byline():
    # 말머리 값 우선 — 본문 추출값은 비어 있을 때만 채운다
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(200, text=""))
    items = asyncio.run(_one_post(PAY_BYLINE_BODY, title="[디 애슬레틱 - 온스테인] 아스날").fetch())
    assert items[0].raw_payload["journalist"] == "온스테인"


@respx.mock
def test_fmkorea_falls_back_to_post_body_when_original_fetch_fails():
    # 원문 재수집은 26건 중 1건만 성공했다 (스펙 §6.2) — 게시글 본문을 재료로 채택
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(403))
    items = asyncio.run(_one_post(FREE_BODY, title="[텔레그래프] 아스날 소식").fetch())
    assert items[0].raw_payload["body"] == "아스날 본문. https://ex.test/a"
    assert items[0].raw_payload["body_level"] == 1
    assert items[0].raw_payload["lang"] == "ko"


@respx.mock
def test_fmkorea_fallback_uses_post_body_when_repost_blocked():
    # 폴백: 원문 접속 실패 → 게시글 본문 채택 · 이미지 제외
    blocked = BLOCKED_PAY_POST.replace("https://www.nytimes.com/athletic/9/b",
                                       "https://ex.test/a")
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(403))
    items = asyncio.run(_one_post(blocked, title="[텔레그래프] 아스날 소식").fetch())
    assert "아스날이 센터백을 원한다." in items[0].raw_payload["body"]  # 게시글 본문 채택
    assert items[0].raw_payload["body_level"] == 1  # 게시글 본문
    assert items[0].raw_payload["images"] == []  # 이미지 제외


# --- 키워드별 제목 필수어 (아르테타 인터뷰 유입 · 2026-07-30 사용자 지시) ---

def _search_adapter(results_html: str, keywords: list[dict]):
    respx.get(url__startswith="https://fm.test/s").mock(
        return_value=httpx.Response(200, text=results_html))
    return FmkoreaAdapter(source_id="fmkorea",
                          search_url="https://fm.test/s?t={target}&kw={keyword}",
                          search_keywords=keywords,
                          base_url="https://www.fmkorea.com")


_TWO_HITS = (
    '<a class="hx" href="/index.php?document_srl=11">[디 애슬레틱] 아르테타 이적 시장 인터뷰</a>'
    '<a class="hx" href="/index.php?document_srl=12">[디 애슬레틱] 첼시 이적 시장 정리</a>')


@respx.mock
def test_fmkorea_title_must_contain_filters_candidates():
    """title_content 검색은 본문만 걸려도 잡히므로 제목 필수어로 좁힌다.
    아르테타 인터뷰는 제목에 '아르테타' 가 있고, 무관한 글은 없다."""
    a = _search_adapter(_TWO_HITS, [{"keyword": "아르테타 이적 시장",
                                     "target": "title_content",
                                     "title_must_contain": "아르테타"}])
    found = asyncio.run(a.discover())
    assert [t for t, _ in found] == ["[디 애슬레틱] 아르테타 이적 시장 인터뷰"]


@respx.mock
def test_fmkorea_title_must_contain_ignores_spacing():
    # fmkorea 게시자는 띄어쓰기를 붙여 쓴다 ('중인아스날') — 공백 무시 비교가 필요하다
    html = ('<a class="hx" href="/index.php?document_srl=21">'
            '[텔레그래프]아르테타의 이적 시장 발언</a>')
    a = _search_adapter(html, [{"keyword": "아르 테타", "target": "title_content",
                                "title_must_contain": "아르 테타"}])
    assert len(asyncio.run(a.discover())) == 1


@respx.mock
def test_fmkorea_keyword_without_title_must_contain_is_unfiltered():
    # 기존 키워드는 계약이 바뀌지 않는다
    a = _search_adapter(_TWO_HITS, [{"keyword": "아스날", "target": "title"}])
    assert len(asyncio.run(a.discover())) == 2


def test_sources_yaml_has_arteta_keyword_with_title_guard():
    """아르테타 인터뷰가 '아스날' 키워드에 안 걸려 유실됐다 (2026-07-30 실측).
    제목 필수어를 함께 두지 않으면 본문만 스친 무관한 글이 대량 유입된다."""
    import yaml as _yaml
    from pathlib import Path as _Path
    data = _yaml.safe_load((_Path(__file__).parent.parent / "config" / "sources.yaml")
                           .read_text(encoding="utf-8"))
    fm = next(s for s in data["sources"] if s["source_id"] == "fmkorea")
    kws = fm["config"]["search_keywords"]
    arteta = next(k for k in kws if "아르테타" in k["keyword"])
    assert arteta["target"] == "title_content"
    assert arteta["title_must_contain"] == "아르테타"


# ---- 무관 글 필터 (스펙 2026-08-01 §3.2) ----

UNRELATED_SEARCH = ('<a class="hx" href="/index.php?document_srl=71">'
                    '[BBC] 유벤투스 새 감독 발표</a>')
UNRELATED_POST = ('<div class="xe_content"><p>유벤투스 소식.</p>'
                  '<p>https://ex.test/u</p></div>')
UNRELATED_ART = '<html><body><article><p>Juventus news only.</p></article></body></html>'

def _filter_adapter(**kw):
    return FmkoreaAdapter(
        source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
        search_keywords=[{"keyword": "kw1", "target": "title"}],
        base_url="https://www.fmkorea.com", **kw)

def _mock_single_post(search_html, post_html, art_html, art_url="https://ex.test/u"):
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        return_value=httpx.Response(200, text=search_html))
    respx.get("https://www.fmkorea.com/71").mock(
        return_value=httpx.Response(200, text=post_html))
    respx.get(art_url).mock(return_value=httpx.Response(200, text=art_html))

@respx.mock
def test_filter_off_when_not_injected():
    # 인자 미주입 = 필터 없음 — 백필 등 기존 호출부 회귀 가드
    _mock_single_post(UNRELATED_SEARCH, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter()
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_filter_passes_club_term_in_title():
    search = ('<a class="hx" href="/index.php?document_srl=71">'
              '[BBC] 아스날, 유벤투스와 협상</a>')
    _mock_single_post(search, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter(relevance_terms=["아스날", "아스널", "arsenal"])
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_filter_passes_club_term_in_body_only():
    # 제목엔 구단명 없음 · 언론사 본문에 Arsenal — 대소문자 무시 (_squash)
    art = ('<html><body><article><p>Talks with Arsenal continue to develop as the club explores '
           'new opportunities for strengthening the squad. Multiple discussions are underway. '
           'The negotiations involve significant financial commitments from the board. '
           'Arsenal management has demonstrated serious intent in the transfer window. '
           'Recent progress suggests positive developments are imminent.</p></article></body></html>')
    _mock_single_post(UNRELATED_SEARCH, UNRELATED_POST, art)
    a = _filter_adapter(relevance_terms=["아스날", "아스널", "arsenal"])
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_filter_passes_player_name_in_title():
    search = ('<a class="hx" href="/index.php?document_srl=71">'
              '[BBC] 디오망데, PSG 와 협상</a>')
    _mock_single_post(search, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter(relevance_terms=["아스날", "아스널", "arsenal"],
                        player_names={"디오망데"})
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_filter_drops_unrelated_and_counts(caplog):
    _mock_single_post(UNRELATED_SEARCH, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter(relevance_terms=["아스날", "아스널", "arsenal"],
                        player_names={"디오망데"})
    with caplog.at_level("INFO"):
        items = asyncio.run(a.fetch())
    assert items == []
    assert a.relevance_dropped == 1
    assert any("무관 글" in r.message for r in caplog.records)

@respx.mock
def test_filter_squash_matching_variant_spacing():
    # 변형 표기 붙여쓰기 ("아스널이") 도 공백 무시 비교로 잡는다
    search = ('<a class="hx" href="/index.php?document_srl=71">'
              '[BBC] 아 스널이 원하는 선수</a>')
    _mock_single_post(search, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter(relevance_terms=["아스널"])
    assert len(asyncio.run(a.fetch())) == 1

# ---- 검색 실패 카운터 (스펙 §6 — 커서 유지 판단 입력) ----

@respx.mock
def test_search_failures_counted_on_429():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(429))
    a = _filter_adapter()
    assert asyncio.run(a.fetch()) == []
    assert a.search_failures == 1

@respx.mock
def test_search_failures_zero_on_success():
    _mock_single_post(UNRELATED_SEARCH, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter()
    asyncio.run(a.fetch())
    assert a.search_failures == 0

BLOCKED_PAY_BODY = ('<div class="rd_body"><strong>퍼가기가 금지된 글입니다</strong>'
                    '<div class="xe_content"><p>아스날이 영입에 근접했다.</p>'
                    '<p><img src="/p.jpg"></p>'
                    '<p>https://www.nytimes.com/athletic/9/b</p></div></div>')


@respx.mock
def test_blocked_paywalled_post_keeps_body_without_images():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        return_value=httpx.Response(200, text=(
            '<a class="hx" href="/index.php?document_srl=222">'
            '[디 애슬레틱] 아스날 B</a>')))
    respx.get("https://www.fmkorea.com/222").mock(
        return_value=httpx.Response(200, text=BLOCKED_PAY_BODY))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(
        return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    item = asyncio.run(a.fetch())[0]
    assert "아스날이 영입에 근접했다." in item.raw_payload["body"]
    assert item.raw_payload["body_level"] == 1
    assert item.raw_payload["images"] == []


ERROR_PAGE = ('<html><body><article><p>Friday 24 July 2026 23:47, UK</p>'
              '<p>Sorry, this blog is currently unavailable. '
              'Please try again later.</p></article></body></html>')


@respx.mock
def test_origin_error_page_falls_back_to_post_body():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        return_value=httpx.Response(200, text=(
            '<a class="hx" href="/index.php?document_srl=111">[BBC] 아스날 A</a>')))
    respx.get("https://www.fmkorea.com/111").mock(
        return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(
        return_value=httpx.Response(200, text=ERROR_PAGE))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    item = asyncio.run(a.fetch())[0]
    assert item.raw_payload["body_level"] == 1
    assert item.raw_payload["lang"] == "ko"
    assert "아스날 본문." in item.raw_payload["body"]
    assert "unavailable" not in item.raw_payload["body"]


def test_origin_body_usable_boundary():
    from bullet_in.adapters.fmkorea import origin_body_usable
    assert not origin_body_usable("Sorry, this blog is currently unavailable.")
    assert not origin_body_usable("  " + "가" * 199 + "  ")
    assert origin_body_usable("가" * 200)


@respx.mock
def test_fmkorea_search_failure_codes_count_status():
    """상태 코드별로 집계된다 — 알림이 원인 추정 없이 사실을 적기 위한 재료."""
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(430))
    respx.get("https://fm.test/s?t=title_content&kw=kw2").mock(
        return_value=httpx.Response(403))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"},
                                        {"keyword": "kw2", "target": "title_content"}],
                       base_url="https://www.fmkorea.com")
    asyncio.run(a.fetch())
    assert a.search_failures == 2
    assert dict(a.search_failure_codes) == {430: 1, 403: 1}


@respx.mock
def test_fmkorea_search_failure_codes_count_connection_error():
    """연결 오류는 상태 코드가 없으므로 error 키로 집계된다."""
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        side_effect=httpx.ConnectError("boom"))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    asyncio.run(a.fetch())
    assert a.search_failures == 1
    assert dict(a.search_failure_codes) == {"error": 1}


@respx.mock
def test_fmkorea_search_failure_codes_reset_between_fetches():
    """fetch 재진입 시 계수가 초기화된다 (search_failures 와 같은 규칙)."""
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(430))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    asyncio.run(a.fetch())
    assert dict(a.search_failure_codes) == {430: 1}
    asyncio.run(a.fetch())
    assert dict(a.search_failure_codes) == {430: 1}   # 누적되지 않는다


# --- 본문 바이라인의 저자 전원 (공저 다중 귀속 스펙 §2.2 ②) ---

from bullet_in.adapters.fmkorea import extract_body_authors


def test_extract_body_authors_returns_both_coauthors():
    # 트랙 발단 기사 8651f026 — 온스테인 단독 · McNicholas 단독 둘 다 도달해야 한다
    body = "By David Ornstein and James McNicholas 아스날이 협상 중이다."
    assert extract_body_authors(body) == ["David Ornstein", "James McNicholas"]


def test_extract_body_authors_returns_three_on_comma_list():
    body = "By Will Magee, Niall McVeigh and Billy Munday 아스날이"
    assert extract_body_authors(body) == ["Will Magee", "Niall McVeigh", "Billy Munday"]


def test_extract_body_authors_drops_job_title_entry():
    # 실측 3건 — 두 번째 자리가 사람이 아니라 직함이다
    body = "By KIERAN GILL, MAIL SPORT REPORTER 아스날이"
    assert extract_body_authors(body) == ["KIERAN GILL"]


def test_extract_body_authors_stops_at_abbreviated_month():
    # 운영 6건 — 축약형 월이 이름 토큰으로 통과해 'David Ornstein Aug' 로 저장됐다
    body = "By David Ornstein Aug. 2, 2026 아스날이"
    assert extract_body_authors(body) == ["David Ornstein"]


def test_extract_body_authors_keeps_name_starting_like_a_month():
    # 함정 — 축약형을 접두로 막으면 Mario 가 Mar + io 로 걸려 이름이 통째로 사라진다
    body = "By Mario Cortegana Aug 3, 2026 아스날이"
    assert extract_body_authors(body) == ["Mario Cortegana"]


def test_extract_body_authors_returns_empty_without_byline():
    assert extract_body_authors("아스날이 비니시우스 영입을 추진한다.") == []


def test_extract_body_journalist_is_first_of_extracted_authors():
    body = "By David Ornstein and James McNicholas 아스날이"
    assert extract_body_journalist(body) == "David Ornstein"


PAY_COAUTHOR_BODY = (
    '<div class="xe_content"><p>비니시우스는 레알에서 8시즌 활약했다 '
    'By David Ornstein and James McNicholas June 19, 2026 3:19 am 아스날이 영입을 추진한다.</p>'
    '<p>https://www.nytimes.com/athletic/9/b</p></div>')


@respx.mock
def test_fmkorea_carries_all_body_authors():
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(200, text=""))
    items = asyncio.run(_one_post(PAY_COAUTHOR_BODY).fetch())
    assert items[0].raw_payload["authors"] == ["David Ornstein", "James McNicholas"]
    assert items[0].raw_payload["journalist"] == "David Ornstein"


@respx.mock
def test_fmkorea_bracket_journalist_leads_the_author_list():
    # 말머리 값이 대표라는 기존 규칙을 유지하되 공저자는 목록에 남긴다
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(200, text=""))
    items = asyncio.run(_one_post(PAY_COAUTHOR_BODY, title="[디 애슬레틱 - 온스테인] 아스날").fetch())
    assert items[0].raw_payload["journalist"] == "온스테인"
    assert items[0].raw_payload["authors"] == [
        "온스테인", "David Ornstein", "James McNicholas"]
