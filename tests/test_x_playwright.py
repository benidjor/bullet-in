from datetime import datetime, timezone
from bullet_in.adapters.x_playwright import parse_afcstuff_tweets, _accumulate_tweets, XPlaywrightAdapter

NOW = datetime(2026, 7, 1, 3, 30, tzinfo=timezone.utc)

def _rt(**kw):
    base = {"text": "", "created_at": "2026-07-01T03:18:00.000Z",
            "status_id": "111", "image_url": None}
    base.update(kw); return base

def test_keeps_only_cited_tweets():
    rts = [
        _rt(text="Arsenal eye Barcola. [ @SamiMokbel_BBC ]", status_id="1"),
        _rt(text="GOAL!! France 3-0", status_id="2"),   # 무인용 → drop
    ]
    items = parse_afcstuff_tweets("x_afcstuff", "afcstuff", rts, NOW)
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://x.com/afcstuff/status/1"
    assert it.source_type == "x"
    assert it.raw_payload["journalist"] == "@SamiMokbel_BBC"
    assert it.raw_payload["handles"] == ["@SamiMokbel_BBC"]
    assert it.raw_payload["text"].startswith("Arsenal eye")

def test_multi_handle_primary_is_last():
    rts = [_rt(text="News [ @David_Ornstein ] via [ @SamiMokbel_BBC ]", status_id="9")]
    items = parse_afcstuff_tweets("x_afcstuff", "afcstuff", rts, NOW)
    assert items[0].raw_payload["handles"] == ["@David_Ornstein", "@SamiMokbel_BBC"]
    assert items[0].raw_payload["journalist"] == "@SamiMokbel_BBC"

def test_passes_image_and_created_at():
    rts = [_rt(text="x [ @gunnerblog ]", image_url="https://img/x.jpg",
               created_at="2026-07-01T02:00:00.000Z")]
    it = parse_afcstuff_tweets("x_afcstuff", "afcstuff", rts, NOW)[0]
    assert it.raw_payload["image_url"] == "https://img/x.jpg"
    assert it.raw_payload["created_at"] == "2026-07-01T02:00:00.000Z"


def test_accumulate_dedupes_overlapping_snapshots():
    acc: dict[str, dict] = {}
    _accumulate_tweets(acc, [_rt(status_id="1"), _rt(status_id="2"), _rt(status_id="3")])
    _accumulate_tweets(acc, [_rt(status_id="2"), _rt(status_id="3"), _rt(status_id="4")])
    assert list(acc.keys()) == ["1", "2", "3", "4"]

def test_accumulate_retains_tweets_dropped_by_virtualization():
    # DOM 가상화: 두 번째 스냅샷에서 1~3이 화면 밖으로 밀려 사라져도 누적 유지돼야 한다.
    acc: dict[str, dict] = {}
    _accumulate_tweets(acc, [_rt(status_id="1"), _rt(status_id="2"), _rt(status_id="3")])
    _accumulate_tweets(acc, [_rt(status_id="4"), _rt(status_id="5"), _rt(status_id="6")])
    assert list(acc.keys()) == ["1", "2", "3", "4", "5", "6"]

def test_accumulate_skips_missing_status_id():
    acc: dict[str, dict] = {}
    _accumulate_tweets(acc, [_rt(status_id=""), _rt(status_id="7")])
    assert list(acc.keys()) == ["7"]


from bullet_in.adapters.x_playwright import parse_self_tweets

def test_self_source_keeps_uncited_afc_tweet():
    # 온스테인 본인 트윗: 인용([ @handle ]) 없음 — afcstuff 경로라면 버려질 형태 (spec §5.2)
    rts = [_rt(text="🚨 EXCL: Arsenal agree £60m deal for X #AFC", status_id="21")]
    items = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://x.com/David_Ornstein/status/21"
    assert it.source_type == "x"
    assert it.raw_payload["journalist"] == "@David_Ornstein"
    assert it.raw_payload["text"].startswith("🚨 EXCL")

def test_self_source_drops_tweets_without_afc_tag():
    # 관련성 필터 (spec §5.4): #AFC 없는 타 클럽 · 유사 태그(#AFCB 본머스 · #AFCON)는 드롭
    rts = [
        _rt(text="Chelsea close in on midfielder #CFC", status_id="22"),
        _rt(text="Bournemouth complete signing #AFCB", status_id="23"),
        _rt(text="AFCON squads announced #AFCON", status_id="24"),
    ]
    assert parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW) == []

def test_self_source_matches_afc_tag_mid_text():
    rts = [_rt(text="Arsenal + Sporting agree Gyokeres fee. #AFC latest on @TheAthleticFC", status_id="25")]
    items = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)
    assert len(items) == 1

def test_self_source_passes_image_and_created_at():
    rts = [_rt(text="Team news #AFC", image_url="https://img/o.jpg",
               created_at="2026-07-01T02:00:00.000Z", status_id="26")]
    it = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)[0]
    assert it.raw_payload["image_url"] == "https://img/o.jpg"
    assert it.raw_payload["created_at"] == "2026-07-01T02:00:00.000Z"

def test_self_source_drops_retweet_by_author_mismatch():
    # 리트윗 가드 (A안): status 링크 작성자가 계정 주인이 아니면 #AFC 가 있어도 드롭
    # — 리트윗은 원작자 status URL 이 잡히므로 author 세그먼트로 판별된다
    rts = [_rt(text="Arsenal have agreed a deal #AFC", status_id="27",
               author="SamiMokbel_BBC")]
    assert parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW) == []

def test_self_source_keeps_own_author_case_insensitive():
    rts = [_rt(text="Arsenal latest #AFC", status_id="28", author="david_ornstein")]
    assert len(parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)) == 1

def test_self_source_missing_author_passes_through():
    # DOM 이 author 를 못 뽑은 경우 (빈 문자열) 는 가드를 통과시킨다 — 실 DOM 에선 항상 존재
    rts = [_rt(text="Arsenal latest #AFC", status_id="29", author="")]
    assert len(parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)) == 1


def test_adapter_parse_tweets_self_source_branch():
    a = XPlaywrightAdapter("x_ornstein", "David_Ornstein", self_source=True)
    rts = [_rt(text="Deal done #AFC", status_id="31"),
           _rt(text="News [ @SamiMokbel_BBC ]", status_id="32")]  # 인용은 있으나 #AFC 없음 → 드롭
    items = a._parse_tweets(rts, NOW)
    assert [i.raw_payload["journalist"] for i in items] == ["@David_Ornstein"]
    assert items[0].url == "https://x.com/David_Ornstein/status/31"

def test_adapter_parse_tweets_default_afcstuff_branch():
    # 회귀 가드: 기본값(self_source 미지정)은 기존 "인용만" 경로 그대로 (spec §5.2)
    a = XPlaywrightAdapter("x_afcstuff", "afcstuff")
    rts = [_rt(text="Deal done #AFC", status_id="31"),
           _rt(text="News [ @SamiMokbel_BBC ]", status_id="32")]
    items = a._parse_tweets(rts, NOW)
    assert [i.raw_payload["journalist"] for i in items] == ["@SamiMokbel_BBC"]

def test_self_source_passes_card_href():
    rts = [_rt(text="Exclusive #AFC", status_id="41", card_href="https://t.co/abc")]
    it = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)[0]
    assert it.raw_payload["card_href"] == "https://t.co/abc"

def test_self_source_card_absent_is_none():
    rts = [_rt(text="News #AFC", status_id="42")]
    it = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)[0]
    assert it.raw_payload["card_href"] is None


import asyncio
import logging as _logging
from bullet_in.adapters import x_playwright


def _self_items(card):
    rts = [_rt(text="News #AFC", status_id="51", card_href=card)]
    return x_playwright.parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)

def _fake_resolver(final_url):
    async def fake(client, url):
        return (final_url, "ignored body", None, None, [])
    return fake

def test_resolve_card_rewrites_url_and_keeps_tweet_url(monkeypatch):
    monkeypatch.setattr("bullet_in.adapters.x_backtrack.resolve_and_fetch",
                        _fake_resolver("https://www.nytimes.com/athletic/12345/"))
    out = asyncio.run(x_playwright.resolve_card_urls(
        _self_items("https://t.co/abc"), _logging.getLogger("t")))
    assert out[0].url == "https://www.nytimes.com/athletic/12345/"
    assert out[0].raw_payload["tweet_url"] == "https://x.com/David_Ornstein/status/51"
    assert "body" not in out[0].raw_payload   # 스텁 유지 — 완전체가 되면 가드의 승격 경로가 뒤집힌다
    assert "title" not in out[0].raw_payload
    assert "image" not in out[0].raw_payload
    assert "images" not in out[0].raw_payload

def test_resolve_card_failure_keeps_tweet_url(monkeypatch):
    monkeypatch.setattr("bullet_in.adapters.x_backtrack.resolve_and_fetch",
                        _fake_resolver(None))
    out = asyncio.run(x_playwright.resolve_card_urls(
        _self_items("https://t.co/abc"), _logging.getLogger("t")))
    assert out[0].url == "https://x.com/David_Ornstein/status/51"
    assert "tweet_url" not in out[0].raw_payload

def test_resolve_card_tweet_domain_falls_back(monkeypatch):
    # 카드가 다른 트윗 (인용) 을 가리키면 기사 아님 — 현행 트윗 URL 유지 (spec §6)
    monkeypatch.setattr("bullet_in.adapters.x_backtrack.resolve_and_fetch",
                        _fake_resolver("https://x.com/other/status/99"))
    out = asyncio.run(x_playwright.resolve_card_urls(
        _self_items("https://t.co/abc"), _logging.getLogger("t")))
    assert out[0].url == "https://x.com/David_Ornstein/status/51"

def test_resolve_card_tco_domain_falls_back(monkeypatch):
    # 리다이렉트가 끝까지 안 풀려 t.co 로 남으면 기사 아님 — 트윗 URL 유지 (spec §6)
    monkeypatch.setattr("bullet_in.adapters.x_backtrack.resolve_and_fetch",
                        _fake_resolver("https://t.co/xyz"))
    out = asyncio.run(x_playwright.resolve_card_urls(
        _self_items("https://t.co/abc"), _logging.getLogger("t")))
    assert out[0].url == "https://x.com/David_Ornstein/status/51"

def test_resolve_card_no_targets_skips_network(monkeypatch):
    # card 없는 배치는 클라이언트 생성 전에 반환 — 외부 접촉 0회 (httpx.AsyncClient 생성 자체가 없어야 함)
    class _BoomClient:
        def __init__(self, *a, **kw):
            raise AssertionError("card 없는 배치는 httpx.AsyncClient 를 만들면 안 된다")
    monkeypatch.setattr("httpx.AsyncClient", _BoomClient)
    out = asyncio.run(x_playwright.resolve_card_urls(
        _self_items(""), _logging.getLogger("t")))
    assert out[0].url == "https://x.com/David_Ornstein/status/51"

def test_resolve_card_exception_isolated_keeps_batch(monkeypatch):
    # 카드 하나의 파싱 예외가 배치 전체를 죽이지 않아야 한다 (소스 격리)
    rts = [
        _rt(text="News #AFC", status_id="61", card_href="https://t.co/bad"),
        _rt(text="More #AFC", status_id="62", card_href="https://t.co/good"),
    ]
    items = x_playwright.parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)

    async def flaky(client, url):
        if url == "https://t.co/bad":
            raise ValueError("malformed html")
        return ("https://www.nytimes.com/athletic/999/", "ignored body", None, None, [])

    monkeypatch.setattr("bullet_in.adapters.x_backtrack.resolve_and_fetch", flaky)
    out = asyncio.run(x_playwright.resolve_card_urls(items, _logging.getLogger("t")))
    assert out[0].url == "https://x.com/David_Ornstein/status/61"
    assert "tweet_url" not in out[0].raw_payload
    assert out[1].url == "https://www.nytimes.com/athletic/999/"
    assert out[1].raw_payload["tweet_url"] == "https://x.com/David_Ornstein/status/62"


# --- 콜론형 인용 회수 (2026-07-30 실측) ---
# afcstuff 는 인용을 대괄호로만 쓰지 않는다. 아래는 라이브 타임라인 30건에서 그대로
# 옮긴 형태다 — 멘션이 줄 단위로 서고 콜론이 따르거나, 이름 뒤 괄호에 핸들이 온다.
# 이 4건이 버려지고 있었다 (통과 8/30 → 12/30).
LIVE_COLON_CITED = [
    (' \n@MatteMoretto\n: “Ethan Nwaneri is the type of profile that interest AC Milan.”',
     "@MatteMoretto"),
    (' \n@JacobsBen\n: “I think Arsenal have grown in optimism over a deal for Bruno Guimarães.”',
     "@JacobsBen"),
    (' \n@Rodra10_97\n: “There has been no meeting between Vinicius & Real Madrid yet.”',
     "@Rodra10_97"),
    ('Bruno Andrade (\n@ESPNBrasil\n): “Speaking to someone involved in the deal…”',
     "@ESPNBrasil"),
]

# 인용 주체가 없어 제외가 맞는 형태 — 회수 대상이 아니다 (같은 30건에서 발췌)
LIVE_UNCITED = [
    'Mikel Arteta: “This has to be the start & it has to be the standard.”',
    'Happy Birthday to Arsenal owner Stan Kroenke, who turns 79 today!',
    'Ben White in Arsenal training today.',
    'Bukayo Saka on Instagram, showing off his new look.',
    'Talks between Vinicius Junior & Real Madrid over a new contract will resume.',
    'Reminder: Arsenal’s 2026 pre-season fixtures, which begin on Saturday.',
]


def test_keeps_colon_form_citation():
    """멘션 + 콜론 형태도 인용으로 인정해야 한다 (2026-07-30 실측 4건 유실)."""
    for i, (text, who) in enumerate(LIVE_COLON_CITED):
        items = parse_afcstuff_tweets("x_afcstuff", "afcstuff",
                                      [_rt(text=text, status_id=str(i))], NOW)
        assert len(items) == 1, f"버려짐: {text[:50]!r}"
        assert items[0].raw_payload["journalist"] == who


def test_still_drops_uncited_tweets():
    """인용 주체 없는 트윗은 그대로 제외 — 기자 tier 를 매길 근거가 없다."""
    for i, text in enumerate(LIVE_UNCITED):
        items = parse_afcstuff_tweets("x_afcstuff", "afcstuff",
                                      [_rt(text=text, status_id=str(i))], NOW)
        assert items == [], f"통과하면 안 됨: {text[:50]!r}"


def test_bracket_citation_wins_over_colon_form():
    """대괄호 인용이 있으면 그것을 쓴다 — 기존 동작 무변경 보장."""
    text = 'Report [ @David_Ornstein ] — quoting Mikel Arteta: “we are ready”'
    it = parse_afcstuff_tweets("x_afcstuff", "afcstuff",
                               [_rt(text=text, status_id="7")], NOW)[0]
    assert it.raw_payload["journalist"] == "@David_Ornstein"
