from datetime import datetime, timezone
from bullet_in.adapters.x_playwright import parse_afcstuff_tweets

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
