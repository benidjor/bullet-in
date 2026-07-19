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
    assert out["h1"]["title_ko"] == "제목"
    assert out["h1"]["summary_ko"] == "요약"
    assert out["h1"]["summary3_ko"] == "①\n②\n③"
    assert out["h1"]["body_ko"] == "본문"

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
    assert out["h"]["title_ko"] == "제"
    assert out["h"]["summary_ko"] == "요"
    assert out["h"]["summary3_ko"] == "a\nb\nc"
    assert out["h"]["body_ko"] == "b"

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
    assert "bad" not in out
    assert out["ok"]["title_ko"] == "제"
    assert out["ok"]["summary_ko"] == "요"
    assert out["ok"]["summary3_ko"] == "a\nb\nc"
    assert out["ok"]["body_ko"] == "b"

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
    assert out["h"]["body_ko"] == "B"  # 정상 처리됨

def test_partition_by_paywall_splits_by_outlet():
    rows = [{"content_hash": "a", "outlet": "The Athletic"},
            {"content_hash": "b", "outlet": "BBC"}]
    para, trans = partition_by_paywall(rows)
    assert [r["content_hash"] for r in para] == ["a"]
    assert [r["content_hash"] for r in trans] == ["b"]

from bullet_in.enrich import classify_stage_rows


class _StageModels:
    def __init__(self, text, exc=None):
        self._t = text; self._exc = exc; self.n = 0
    def generate_content(self, **kw):
        self.n += 1
        if self._exc:
            raise self._exc
        class R: pass
        r = R(); r.text = self._t; return r


class _StageClient:
    def __init__(self, text, exc=None): self.models = _StageModels(text, exc)


def test_classify_returns_hash_to_stage():
    payload = ('[{"content_hash":"a","stage":"negotiating"},'
               '{"content_hash":"b","stage":"agreed"}]')
    rows = [{"content_hash": "a", "title_original": "Arsenal in talks", "summary_ko": "협상"},
            {"content_hash": "b", "title_original": "Arsenal confirm", "summary_ko": "발표"}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"a": "negotiating", "b": "agreed"}


def test_classify_demotes_invalid_stage_to_other():
    payload = '[{"content_hash":"a","stage":"bogus"}]'
    out = classify_stage_rows([{"content_hash": "a", "title_original": "T", "summary_ko": ""}],
                              _StageClient(payload), "m")
    assert out == {"a": "other"}


def test_classify_demotes_official_to_agreed():
    """프롬프트에 없어도 모델이 official을 뱉으면 agreed로 강등 (spec §4.3 불변량)."""
    payload = '[{"content_hash":"h1","stage":"official"}]'
    rows = [{"content_hash": "h1", "title_original": "t", "summary_ko": "s"}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"h1": "agreed"}


def test_classify_omits_missing_hashes():
    payload = '[{"content_hash":"a","stage":"rumour"}]'   # b 누락
    rows = [{"content_hash": "a", "title_original": "A", "summary_ko": ""},
            {"content_hash": "b", "title_original": "B", "summary_ko": ""}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"a": "rumour"}   # b는 NULL 유지 (다음 사이클 재시도)


def test_classify_skips_unparseable_batch():
    out = classify_stage_rows([{"content_hash": "a", "title_original": "A", "summary_ko": ""}],
                              _StageClient("not json"), "m")
    assert out == {}


def test_classify_batches_by_size():
    payload = '[{"content_hash":"a","stage":"rumour"}]'
    client = _StageClient(payload)
    rows = [{"content_hash": f"h{i}", "title_original": "T", "summary_ko": ""} for i in range(5)]
    classify_stage_rows(rows, client, "m", batch_size=2)
    assert client.models.n == 3   # 5건 → 2+2+1 = 3 배치


def test_classify_stops_on_rate_limit():
    class _RL(Exception):
        code = 429
    client = _StageClient("", exc=_RL("429"))
    rows = [{"content_hash": f"h{i}", "title_original": "T", "summary_ko": ""} for i in range(5)]
    out = classify_stage_rows(rows, client, "m", batch_size=2)
    assert out == {}
    assert client.models.n == 1   # 첫 배치에서 중단


def test_stage_prompt_lists_llm_stages_and_excludes_official():
    """STAGE_PROMPT는 LLM 분류 대상 enum 전부를 포함하되 official은 제외한다.
    official은 공홈 소스 규칙 전용 (spec §4.1) — 프롬프트에 등장하면 규칙 분리가 깨진 것."""
    from bullet_in import transfer_stage as ts
    from bullet_in.enrich import STAGE_PROMPT
    for enum in sorted(ts.VALID_STAGES - {"official"}):
        assert enum in STAGE_PROMPT, f"STAGE_PROMPT가 {enum} 단계를 누락 — transfer_stage와 동기화 필요"
    assert "official" not in STAGE_PROMPT

from bullet_in.enrich import resummarize_rows

def test_resummarize_returns_summary_fields_only():
    class M:
        def generate_content(self, **kw):
            class R: pass
            r = R(); r.text = '{"summary_ko":"확정했다.","summary3_ko":["a","b","c"]}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "h", "title_original": "T",
             "title_ko": "제목", "body_ko": "본문"}]
    out = resummarize_rows(rows, C(), "gemini-2.5-flash-lite")
    assert out["h"] == {"summary_ko": "확정했다.", "summary3_ko": "a\nb\nc"}

def test_resummarize_stops_and_logs_on_rate_limit(caplog):
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            raise _RateLimit("429")
    class C:
        def __init__(self): self.models = M()
    c = C()
    rows = [{"content_hash": "a", "title_original": "A", "body_ko": "b"},
            {"content_hash": "b", "title_original": "B", "body_ko": "b"}]
    with caplog.at_level(logging.WARNING):
        out = resummarize_rows(rows, c, "m")
    assert out == {}
    assert c.models.n == 1
    assert any("429" in r.message or "rate limit" in r.message.lower()
               for r in caplog.records)

def test_resummarize_skips_unparseable_row_without_aborting():
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            r.text = "garbage" if self.n == 1 else '{"summary_ko":"됐다.","summary3_ko":["a","b","c"]}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "bad", "title_original": "A", "body_ko": "b"},
            {"content_hash": "ok", "title_original": "B", "body_ko": "b"}]
    out = resummarize_rows(rows, C(), "gemini-2.5-flash-lite")
    assert "bad" not in out
    assert out["ok"]["summary_ko"] == "됐다."

def test_all_prompts_carry_polite_ban_example():
    # 존댓말 금지 대비 예시가 프롬프트에서 빠지면 회귀 — 4종 모두 검사
    from bullet_in.enrich import (SUMMARY_PROMPT, TRANSLATE_PROMPT,
                                  PARAPHRASE_PROMPT, RESUMMARY_PROMPT)
    for p in (SUMMARY_PROMPT, TRANSLATE_PROMPT, PARAPHRASE_PROMPT, RESUMMARY_PROMPT):
        assert "했습니다" in p and "했다" in p

def test_resummarize_skips_empty_or_null_summary():
    # 빈/비문자열 summary_ko가 기존 요약을 덮어쓰지 않도록 행 단위 스킵 (M2 가드)
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            r.text = ('{"summary_ko":"","summary3_ko":["a","b","c"]}' if self.n == 1
                      else '{"summary_ko":null,"summary3_ko":["a","b","c"]}')
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "empty", "title_original": "A", "body_ko": "b"},
            {"content_hash": "null", "title_original": "B", "body_ko": "b"}]
    out = resummarize_rows(rows, C(), "gemini-2.5-flash-lite")
    assert out == {}

def test_body_prompts_carry_plain_style_boilerplate_and_markdown_rules():
    # body_ko 평어체 대비 예시 · 인용문 예외 · 무관 문구 제외 · 경량 마크다운 지시가
    # 프롬프트에서 빠지면 회귀 — 번역 · 패러프레이즈 2종 모두 검사
    from bullet_in.enrich import TRANSLATE_PROMPT, PARAPHRASE_PROMPT
    for p in (TRANSLATE_PROMPT, PARAPHRASE_PROMPT):
        assert "갖고 있습니다" in p and "갖고 있다" in p
        assert "인용문" in p
        assert "무관한 문구" in p
        assert "###" in p and "**" in p and "> " in p

def test_body_prompts_instruct_paragraph_breaks():
    # 추출 평문화로 원문 문단이 소실되므로 번역이 2~4문장 문단으로 재구성해야 함
    from bullet_in.enrich import TRANSLATE_PROMPT, PARAPHRASE_PROMPT
    for p in (TRANSLATE_PROMPT, PARAPHRASE_PROMPT):
        assert "2~4문장" in p and "줄바꿈" in p

def test_apply_glossary_replaces_all_ko_fields():
    from bullet_in.enrich import apply_glossary
    mapping = {"메슬리에": "멜리에", "스캇": "스콧"}
    parsed = {"title_ko": "메슬리에 영입 임박", "summary_ko": "알렉스 스캇 관심.",
              "summary3_ko": "메슬리에가 온다.\n스캇도 온다.", "body_ko": "메슬리에는 골키퍼다."}
    out = apply_glossary(parsed, mapping)
    assert out["title_ko"] == "멜리에 영입 임박"
    assert out["summary_ko"] == "알렉스 스콧 관심."
    assert out["summary3_ko"] == "멜리에가 온다.\n스콧도 온다."
    assert out["body_ko"] == "멜리에는 골키퍼다."

def test_apply_glossary_ignores_missing_fields_and_empty_mapping():
    from bullet_in.enrich import apply_glossary
    parsed = {"title_ko": "제목", "summary_ko": None}
    assert apply_glossary(parsed, {}) == parsed
    assert apply_glossary(parsed, {"스캇": "스콧"})["summary_ko"] is None

def test_paragraphize_splits_long_block_at_sentence_ends():
    from bullet_in.enrich import paragraphize
    sent = "아스날이 여름 이적 시장에서 미드필더 보강을 위해 여러 후보를 검토하고 있는 것으로 알려졌다."  # 약 50자
    block = " ".join([sent] * 12)  # 600자 초과 단일 블록
    out = paragraphize(block)
    lines = out.split("\n")
    assert len(lines) >= 2
    assert all(len(l) <= 400 for l in lines)
    # 내용 보존: 공백 정규화 후 동일
    assert " ".join(out.split()) == " ".join(block.split())

def test_paragraphize_keeps_short_blocks_and_markdown():
    from bullet_in.enrich import paragraphize
    long_quote = "> " + "인용문이다. " * 60  # 400자 초과 인용 블록
    header = "### " + "소제목이다. " * 60   # 400자 초과 소제목 블록
    text = "짧은 문단이다.\n" + long_quote + "\n" + header
    assert paragraphize(text) == text

def test_paragraphize_does_not_split_on_decimal_point():
    from bullet_in.enrich import paragraphize
    sent = "이적료는 총 2.5천만 파운드에 이르는 것으로 전해졌으며 협상은 막바지 단계다."
    block = " ".join([sent] * 12)
    out = paragraphize(block)
    assert not any(l.rstrip().endswith("2.") for l in out.split("\n"))

def test_paragraphize_passthrough_none_empty_and_unsplittable():
    from bullet_in.enrich import paragraphize
    assert paragraphize(None) is None
    assert paragraphize("") == ""
    one_sentence = "가" * 500 + "."  # 문장 경계 없는 500자
    assert paragraphize(one_sentence) == one_sentence

def test_detect_title_hallucination_flags_name_absent_from_source():
    from bullet_in.enrich import detect_title_hallucination
    name_map = {"펠레그리니": "Pellegrini", "촐리스": "Tzolis"}
    # 실사례 (id 365): 원문에 없는 펠레그리니가 제목에 생성
    title_ko = "아스날, 펠레그리니 영입 위해 펠레그리니 포함 제안 검토"
    src = "Arsenal weigh player-plus-cash offer for Christos Tzolis. Arsenal are ..."
    assert detect_title_hallucination(title_ko, src, name_map) == ["펠레그리니"]

def test_detect_title_hallucination_passes_when_source_has_name():
    from bullet_in.enrich import detect_title_hallucination
    name_map = {"요케레스": "Gyokeres", "트로사르": "Trossard"}
    # 원문 diacritics (Gyökeres) 도 정규화 후 매치돼야 함
    title_ko = "요케레스, 아스날 이적 임박"
    src = "Viktor Gyökeres is close to joining Arsenal."
    assert detect_title_hallucination(title_ko, src, name_map) == []

def test_detect_title_hallucination_passes_korean_source():
    from bullet_in.enrich import detect_title_hallucination
    name_map = {"펠레그리니": "Pellegrini"}
    # 한국어 원문 (fmkorea paraphrase 경로): 한글 표기가 원문에 있으면 통과
    title_ko = "펠레그리니, 아스날행 루머"
    src = "[오피셜] 펠레그리니 아스날 이적 협상 중이라고 함"
    assert detect_title_hallucination(title_ko, src, name_map) == []

def test_detect_title_hallucination_empty_inputs():
    from bullet_in.enrich import detect_title_hallucination
    assert detect_title_hallucination(None, "src", {"a": "b"}) == []
    assert detect_title_hallucination("제목", "src", {}) == []

def test_detect_roundup_omission_flags_missing_attribution_item():
    from bullet_in.enrich import detect_roundup_omission
    src = ("A move. (Teamtalk) , external B move. (Sky Sports) , external "
           "C move. (Guardian) , external")
    ko = "A 이적. (Teamtalk)\nC 이적. (Guardian)"
    assert detect_roundup_omission(src, ko) == ["Sky Sports"]

def test_detect_roundup_omission_passes_when_all_kept_and_non_roundup():
    from bullet_in.enrich import detect_roundup_omission
    src = "A move. (Teamtalk) , external B move. (Sky Sports) , external"
    ko = "A 이적. (Teamtalk)\nB 이적. (Sky Sports)"
    assert detect_roundup_omission(src, ko) == []
    # 비 라운드업 (', external' 표지 없음) — 일반 괄호 (£50.9m) 는 무시
    assert detect_roundup_omission("fee of 60m euros (£50.9m).", "번역문") == []
    assert detect_roundup_omission(None, None) == []

def test_detect_roundup_omission_strips_attribution_suffix():
    from bullet_in.enrich import detect_roundup_omission
    src = "A move. (Corriere dello Sport - in Italian) , external"
    ko = "A 이적. (Corriere dello Sport)"
    assert detect_roundup_omission(src, ko) == []

def test_detect_roundup_omission_counts_duplicate_outlets():
    from bullet_in.enrich import detect_roundup_omission
    src = "A. (Sky Sports) , external B. (Sky Sports) , external"
    ko = "A. (Sky Sports)"   # 같은 출처 단신 2건 중 1건 누락
    assert detect_roundup_omission(src, ko) == ["Sky Sports"]

def test_detect_roundup_omission_normalizes_attribution_variants():
    from bullet_in.enrich import detect_roundup_omission
    src = ("A. (L'Equipe, in French) , external "
           "B. (Corriere dello Sport via Football Italia) , external "
           "C. (Football Insider) , external")
    ko = "A. (L'Equipe)\nB. (Corriere dello Sport)\nC. (Football Insider)"
    assert detect_roundup_omission(src, ko) == []

def test_detect_title_mistranslation_flags_missing_registered_name():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"촐리스": "Tzolis"}
    # 실사례 (id 385): 원문 제목의 Tzolis 가 번역 제목에서 '조르제' 로 창작
    out = detect_title_mistranslation(
        "아스날, 클럽 브뤼허 공격수 조르제 영입 근접",
        "Arsenal close in on £34m deal for Club Brugge forward Christos Tzolis",
        name_map)
    assert out == ["인명 누락:Tzolis"]

def test_detect_title_mistranslation_word_boundary_avoids_price_rice():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"라이스": "Rice"}
    # 'price' 안의 'rice' 는 단어 경계 밖 — 오탐 금지
    assert detect_title_mistranslation(
        "아스날, 이적료 책정", "Arsenal told asking price for star", name_map) == []

def test_detect_title_mistranslation_flags_unfounded_loan():
    from bullet_in.enrich import detect_title_mistranslation
    # 실사례 (id 392): permanent deal → '임대 이적 확정'
    out = detect_title_mistranslation(
        "트로사르, 베식타스 임대 이적 확정",
        "Trossard leaves Arsenal for Besiktas in permanent deal", {})
    assert out == ["임대 무근거"]
    # 원문에 loan 있으면 통과
    assert detect_title_mistranslation(
        "선수, 임대 이적", "Player joins on loan", {}) == []
    # 한국어 원문 (fmkorea) 에 '임대' 있으면 통과
    assert detect_title_mistranslation(
        "선수, 임대 이적", "[오피셜] 선수 임대 이적 확정", {}) == []

def test_detect_title_mistranslation_passes_variant_spelling_same_person():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"래시포드": "Rashford", "라시포드": "Rashford"}
    # 같은 인물의 다른 등재 표기가 제목에 있으면 통과
    assert detect_title_mistranslation(
        "라시포드, 아스날행?", "Rashford to Arsenal?", name_map) == []

def test_detect_title_mistranslation_empty_inputs():
    from bullet_in.enrich import detect_title_mistranslation
    assert detect_title_mistranslation(None, "t", {"a": "B"}) == []
    assert detect_title_mistranslation("제목", None, {"a": "B"}) == []

def test_detect_title_mistranslation_passes_partial_name_condensation():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"아르테타": "Arteta", "로저스": "Rogers"}
    # 다절 제목 (트윗 · 리스트클) 의 축약 — 매핑 인명 일부라도 유지되면 통과
    assert detect_title_mistranslation(
        "아스날, 로저스 영입 경쟁서 첼시에 밀려",
        "talkSPORT understands that Mikel Arteta met Morgan Rogers for talks",
        name_map) == []

def test_detect_club_injection_flags_unfounded_club():
    from bullet_in.enrich import detect_club_injection
    club_map = {"미들즈브러": ["Middlesbrough", "Boro"],
                "아스톤 빌라": ["Aston Villa", "Villa"]}
    # 실사례 (9956234a): 원문은 Aston Villa 소속 명시, 번역이 학습 지식 (전 소속) 주입
    parsed = {"title_ko": "아스날, 3000만 파운드 미들즈브러 FW 영입 임박",
              "summary_ko": None,
              "summary3_ko": "미들즈브러의 모건 로저스가 링크됐다.",
              "body_ko": "아스톤 빌라가 로저스의 몸값을 책정했다."}
    src = "Aston Villa, who reportedly value Rogers at £130m. Arsenal are keen."
    assert detect_club_injection(parsed, src, club_map) == ["미들즈브러"]

def test_detect_club_injection_passes_on_english_alias():
    from bullet_in.enrich import detect_club_injection
    club_map = {"미들즈브러": ["Middlesbrough", "Boro"]}
    # 원문이 통칭 (Boro) 으로만 표기해도 근거로 인정 — 별칭 누락 = 오탐 방지
    parsed = {"title_ko": "미들즈브러, 유망주 영입 완료", "summary_ko": None,
              "summary3_ko": None, "body_ko": None}
    src = "Boro have completed the signing of the youngster."
    assert detect_club_injection(parsed, src, club_map) == []

def test_detect_club_injection_passes_folded_diacritics_alias():
    from bullet_in.enrich import detect_club_injection
    club_map = {"베식타스": ["Besiktas"]}
    # 원문 분음부호 표기 (Beşiktaş) 도 fold 후 매치 (기존 Gyökeres 테스트와 동일 계열)
    parsed = {"title_ko": "트로사르, 베식타스 이적", "summary_ko": None,
              "summary3_ko": None, "body_ko": None}
    src = "Trossard joins Beşiktaş for £15.3m."
    assert detect_club_injection(parsed, src, club_map) == []

def test_detect_club_injection_passes_korean_source():
    from bullet_in.enrich import detect_club_injection
    club_map = {"미들즈브러": ["Middlesbrough", "Boro"]}
    # ko 경로 (fmkorea): 원문 자체가 한국어 — 한글 표기 근거로 통과 (오탐 실측 cc2c7b58 재현 회귀)
    parsed = {"title_ko": None, "summary_ko": None, "summary3_ko": None,
              "body_ko": "미들즈브러 시절부터 주목받던 로저스가 빌라에서 성장했다."}
    src = "[해외축구] 미들즈브러 출신 로저스, 아스톤 빌라에서 폼 절정이라고 함"
    assert detect_club_injection(parsed, src, club_map) == []

def test_detect_club_injection_leading_hangul_guard():
    from bullet_in.enrich import detect_club_injection
    club_map = {"리즈": ["Leeds"]}
    # 선행 문자 한글이면 불인정: '시리즈' 는 '리즈' 매치 아님 (등장 · 근거 양쪽)
    parsed = {"title_ko": None, "summary_ko": None, "summary3_ko": None,
              "body_ko": "이번 시리즈 경기에서 아스날이 승리했다."}
    assert detect_club_injection(parsed, "Arsenal win again.", club_map) == []
    # 조사 결합 (직후 한글) 은 정상 검출 유지: '리즈가' → 원문에 Leeds 없음 → 검출
    parsed2 = {"title_ko": None, "summary_ko": None, "summary3_ko": None,
               "body_ko": "리즈가 영입 경쟁에 뛰어들었다."}
    assert detect_club_injection(parsed2, "Arsenal win again.", club_map) == ["리즈"]
    # 근거 대조에도 같은 가드: 원문의 '시리즈' 는 '리즈' 의 근거가 아님
    assert detect_club_injection(parsed2, "월드컵 시리즈 특집 기사", club_map) == ["리즈"]

def test_detect_club_injection_empty_inputs():
    from bullet_in.enrich import detect_club_injection
    club_map = {"미들즈브러": ["Middlesbrough"]}
    assert detect_club_injection({}, "src", club_map) == []
    assert detect_club_injection({"title_ko": None, "body_ko": None}, "src", club_map) == []
    assert detect_club_injection({"title_ko": "미들즈브러 소식"}, "src", {}) == []
