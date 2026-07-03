from datetime import datetime, timezone, timedelta
from bullet_in.adapters.x_backtrack import extract_entities, match_original_tweet, outlet_for_domain, is_paywalled, load_backtrack_config

def test_extract_entities_multiword():
    assert "Jeremy Monga" in extract_entities("Man City working to sign Jeremy Monga")

def test_extract_entities_keeps_accent():
    ents = extract_entities("Arsenal hope to sign Bruno Guimarães this summer")
    assert "Bruno Guimarães" in ents

def test_extract_entities_skips_single_word():
    assert extract_entities("Arsenal are active") == []

_AF = datetime(2026, 7, 2, 21, 0, tzinfo=timezone.utc)

def _jt(text, minutes_before):
    return {"text": text, "created_at": (_AF - timedelta(minutes=minutes_before)).isoformat()}

def test_matcher_picks_highest_overlap_in_window():
    tweets = [
        _jt("Man City working to complete signing of Leicester winger Jeremy Monga proposed fee", 13),
        _jt("Man City pushing hard to sign Jeremy Monga from Leicester", 108),
    ]
    af = "Manchester City are working to complete a deal for Jeremy Monga fee region Leicester winger"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is tweets[0]

def test_matcher_none_below_threshold():
    tweets = [_jt("Newcastle eye Felix Nmecha midfielder shortlist", 20)]
    af = "Arsenal monitoring William Saliba fitness back problem"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is None

def test_matcher_excludes_later_tweets():
    tweets = [_jt("Arsenal agree Bruno Guimaraes deal Newcastle package worth", -30)]
    af = "Arsenal agree Bruno Guimaraes deal Newcastle package worth"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is None

def test_matcher_handles_naive_created_at():
    # tz 없는 created_at도 UTC로 간주해 비교 크래시 없이 매칭
    tweets = [{"text": "Arsenal sign Bruno Guimaraes Newcastle package worth",
               "created_at": "2026-07-02T20:30:00"}]
    af = "Arsenal sign Bruno Guimaraes Newcastle package worth"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is tweets[0]

_DOMAINS = {"bbc.co.uk": "BBC", "thesun.co.uk": "The Sun"}

def test_outlet_for_domain_exact_and_subdomain():
    assert outlet_for_domain("https://www.bbc.co.uk/sport/x", _DOMAINS) == "BBC"
    assert outlet_for_domain("https://thesun.co.uk/a", _DOMAINS) == "The Sun"

def test_outlet_for_domain_unknown():
    assert outlet_for_domain("https://example.com/a", _DOMAINS) is None

def test_outlet_for_domain_real_subdomain():
    assert outlet_for_domain("https://sport.bbc.co.uk/x", _DOMAINS) == "BBC"

def test_is_paywalled_athletic():
    assert is_paywalled("https://www.nytimes.com/athletic/123/") is True
    assert is_paywalled("https://theathletic.com/123/") is True
    assert is_paywalled("https://www.bbc.co.uk/x") is False

def test_is_paywalled_no_false_positive():
    assert is_paywalled("https://www.nytimes.com/athletics-fanzone/x") is False
    assert is_paywalled("https://t.co/x?u=theathletic.com") is False

def test_load_backtrack_config():
    cfg = load_backtrack_config("config/backtrack.yaml")
    assert cfg["domains"]["bbc.co.uk"] == "BBC"
    assert cfg["params"]["overlap_min"] == 4
