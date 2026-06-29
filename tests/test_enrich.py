from bullet_in.enrich import enrich_rows

class FakeModels:
    def generate_content(self, **kw):
        class R: pass
        r = R(); r.text = '{"title_ko":"제목","summary_ko":"요약","summary3_ko":["①","②","③"],"body_ko":"본문"}'
        return r
class FakeClient:
    def __init__(self): self.models = FakeModels()

def test_enrich_translates_missing_rows():
    rows = [{"content_hash": "h1", "title_original": "Title", "body_excerpt": "Body"}]
    out = enrich_rows(rows, client=FakeClient(), model="gemini-2.5-flash-lite")
    assert out["h1"]["title_ko"] == "제목" and out["h1"]["summary_ko"] == "요약"

def test_enrich_skips_when_no_rows():
    assert enrich_rows([], client=FakeClient(), model="gemini-2.5-flash-lite") == {}

def test_enrich_handles_code_fenced_json():
    class M:
        def generate_content(self, **kw):
            class R: pass
            r = R(); r.text = '```json\n{"title_ko":"제","summary_ko":"요","summary3_ko":["a","b","c"],"body_ko":"b"}\n```'
            return r
    class C:
        def __init__(self): self.models = M()
    out = enrich_rows([{"content_hash":"h","title_original":"T","body_excerpt":""}], C(), "gemini-2.5-flash-lite")
    assert out["h"]["title_ko"] == "제" and out["h"]["summary_ko"] == "요"

def test_enrich_skips_bad_row_without_aborting_batch():
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            r.text = "garbage no json" if self.n == 1 else '{"title_ko":"제","summary_ko":"요","summary3_ko":["a","b","c"],"body_ko":"b"}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash":"bad","title_original":"A","body_excerpt":""},
            {"content_hash":"ok","title_original":"B","body_excerpt":""}]
    out = enrich_rows(rows, C(), "gemini-2.5-flash-lite")
    assert "bad" not in out and out["ok"]["title_ko"] == "제" and out["ok"]["summary_ko"] == "요"

from bullet_in.enrich import partition_translation_rows

def test_partition_splits_ko_and_en_by_source_lang():
    rows = [
        {"content_hash": "k", "source_id": "fmkorea", "title_original": "한글", "body_excerpt": "본문"},
        {"content_hash": "e", "source_id": "bbc_sport", "title_original": "Eng", "body_excerpt": "b"},
    ]
    sources = {"fmkorea": {"lang": "ko"}, "bbc_sport": {"tier": 1}}
    ko, en = partition_translation_rows(rows, sources)
    assert [r["content_hash"] for r in ko] == ["k"]
    assert [r["content_hash"] for r in en] == ["e"]

from bullet_in.enrich import summarize_ko_rows

import logging

class _RateLimit(Exception):
    code = 429

def test_enrich_stops_and_logs_on_rate_limit(caplog):
    # 429를 만나면 그 회차는 즉시 중단하고 남은 행은 호출하지 않는다(다음 사이클 누적).
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            raise _RateLimit("429 RESOURCE_EXHAUSTED")
    class C:
        def __init__(self): self.models = M()
    c = C()
    rows = [{"content_hash":"a","title_original":"A","body_excerpt":""},
            {"content_hash":"b","title_original":"B","body_excerpt":""}]
    with caplog.at_level(logging.WARNING):
        out = enrich_rows(rows, c, "m")
    assert out == {}
    assert c.models.n == 1  # 둘째 행은 호출조차 안 함
    assert any("429" in r.message or "rate limit" in r.message.lower()
               for r in caplog.records)

def test_summarize_ko_rows_stops_and_logs_on_rate_limit(caplog):
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            raise _RateLimit("429")
    class C:
        def __init__(self): self.models = M()
    c = C()
    rows = [{"content_hash":"a","title_original":"A","body_excerpt":""},
            {"content_hash":"b","title_original":"B","body_excerpt":""}]
    with caplog.at_level(logging.WARNING):
        out = summarize_ko_rows(rows, c, "m")
    assert out == {}
    assert c.models.n == 1
    assert any("429" in r.message or "rate limit" in r.message.lower()
               for r in caplog.records)

def test_summarize_ko_rows_returns_korean_summary():
    class M:
        def generate_content(self, **kw):
            class R: pass
            r = R(); r.text = '{"summary_ko":"사카 재계약 임박"}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "h", "title_original": "사카 재계약", "body_excerpt": "본문"}]
    out = summarize_ko_rows(rows, C(), "gemini-2.5-flash-lite")
    assert out == {"h": "사카 재계약 임박"}

def test_summarize_ko_rows_skips_bad_row_without_aborting_batch():
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            r.text = "garbage no json" if self.n == 1 else '{"summary_ko":"요약"}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "bad", "title_original": "A", "body_excerpt": ""},
            {"content_hash": "ok", "title_original": "B", "body_excerpt": ""}]
    out = summarize_ko_rows(rows, C(), "gemini-2.5-flash-lite")
    assert "bad" not in out and out["ok"] == "요약"

import json as _json
from bullet_in.enrich import partition_by_paywall

class FullModels:
    def __init__(self, payload): self._p = payload; self.n = 0
    def generate_content(self, **kw):
        self.n += 1
        class R: pass
        r = R(); r.text = _json.dumps(self._p, ensure_ascii=False); return r
class FullClient:
    def __init__(self, payload): self.models = FullModels(payload)

def test_enrich_returns_four_fields():
    payload = {"title_ko": "아스날, 요케레스 영입", "summary_ko": "6천만에 영입",
               "summary3_ko": ["발표", "이적료 6천만", "5년 계약"], "body_ko": "전체 본문"}
    rows = [{"content_hash": "h1", "title_original": "Arsenal sign", "body_source": "Body"}]
    out = enrich_rows(rows, FullClient(payload), "m")
    assert out["h1"]["title_ko"] == "아스날, 요케레스 영입"
    assert out["h1"]["summary_ko"] == "6천만에 영입"
    assert out["h1"]["summary3_ko"] == "발표\n이적료 6천만\n5년 계약"  # 배열 → \n join
    assert out["h1"]["body_ko"] == "전체 본문"

def test_enrich_skips_row_missing_keys():
    payload = {"title_ko": "제목"}  # 키 부족
    out = enrich_rows([{"content_hash": "h", "title_original": "T", "body_source": ""}],
                      FullClient(payload), "m")
    assert "h" not in out

def test_enrich_paraphrase_mode_uses_paraphrase_prompt():
    payload = {"title_ko": "T", "summary_ko": "S", "summary3_ko": ["a", "b", "c"], "body_ko": "B"}
    client = FullClient(payload)
    rows = [{"content_hash": "h", "title_original": "[디 애슬레틱] 제목", "body_source": "한국어 본문"}]
    out = enrich_rows(rows, client, "m", mode="paraphrase")
    assert out["h"]["body_ko"] == "B"  # 정상 처리됨 (프롬프트 분기는 PROMPT 상수 사용)

def test_partition_by_paywall_splits_by_outlet():
    rows = [{"content_hash": "a", "outlet": "The Athletic"},
            {"content_hash": "b", "outlet": "BBC"}]
    para, trans = partition_by_paywall(rows)
    assert [r["content_hash"] for r in para] == ["a"]
    assert [r["content_hash"] for r in trans] == ["b"]
