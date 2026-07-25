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
