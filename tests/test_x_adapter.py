from datetime import datetime, timezone
from bullet_in.adapters.x_twikit import tweets_to_items

class FakeTweet:
    def __init__(self, id, text, created_at):
        self.id, self.text, self.created_at = id, text, created_at

def test_tweets_to_items_maps_fields():
    tw = [FakeTweet("1", "Rice rice baby", datetime(2026,5,27,tzinfo=timezone.utc))]
    items = tweets_to_items("x_handofarsnal", "handofarsnal", tw)
    assert items[0].url == "https://x.com/handofarsnal/status/1"
    assert items[0].raw_payload["text"] == "Rice rice baby"
    assert items[0].source_type == "x"
