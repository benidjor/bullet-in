from bullet_in.enrich import enrich_rows

class FakeMessages:
    def create(self, **kw):
        class R: pass
        r = R(); r.content = [type("B", (), {"text": '{"title_ko":"제목","summary_ko":"요약"}'})()]
        return r
class FakeClient:
    def __init__(self): self.messages = FakeMessages()

def test_enrich_translates_missing_rows():
    rows = [{"content_hash": "h1", "title_original": "Title", "body_excerpt": "Body"}]
    out = enrich_rows(rows, client=FakeClient(), model="claude-haiku-4-5")
    assert out["h1"] == ("제목", "요약")

def test_enrich_skips_when_no_rows():
    assert enrich_rows([], client=FakeClient(), model="claude-haiku-4-5") == {}
