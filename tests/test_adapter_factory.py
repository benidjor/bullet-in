from bullet_in.adapters.factory import build_adapters

def test_factory_builds_enabled_adapters(monkeypatch):
    monkeypatch.setenv("GUARDIAN_API_KEY", "k")
    cfg = {"sources": [
        {"source_id": "guardian", "adapter": "guardian_api", "enabled": True,
         "config": {"tag": "football/arsenal", "title_contains": ["sign"]}},
        {"source_id": "off", "adapter": "rss", "enabled": False, "config": {"feed_url": "x"}},
    ]}
    adapters = build_adapters(cfg)
    assert [a.source_id for a in adapters] == ["guardian"]

def test_factory_passes_tag_and_title_contains_to_guardian(monkeypatch):
    monkeypatch.setenv("GUARDIAN_API_KEY", "k")
    cfg = {"sources": [{"source_id": "guardian", "adapter": "guardian_api",
            "enabled": True,
            "config": {"tag": "football/arsenal", "title_contains": ["sign"]}}]}
    a = build_adapters(cfg)[0]
    assert a.params["tag"] == "football/arsenal"
    assert a.title_keywords == ["sign"]

def test_factory_skips_guardian_without_key(monkeypatch, caplog):
    monkeypatch.delenv("GUARDIAN_API_KEY", raising=False)
    cfg = {"sources": [
        {"source_id": "guardian", "adapter": "guardian_api", "enabled": True,
         "config": {"tag": "football/arsenal"}},
        {"source_id": "feed", "adapter": "rss", "enabled": True,
         "config": {"feed_url": "x"}},
    ]}
    with caplog.at_level("WARNING"):
        adapters = build_adapters(cfg)
    assert [a.source_id for a in adapters] == ["feed"]
    assert "GUARDIAN_API_KEY" in caplog.text

def test_factory_builds_fmkorea_adapter():
    cfg = {"sources": [
        {"source_id": "fmkorea", "adapter": "fmkorea", "enabled": True,
         "config": {"search_url": "https://fm.test/s?t={target}&kw={keyword}",
                    "search_keywords": [{"keyword": "아스날", "target": "title"},
                                        {"keyword": "온스테인", "target": "title_content"}],
                    "item_selector": "a.hx"}},
    ]}
    adapters = build_adapters(cfg)
    assert adapters[0].source_id == "fmkorea"
    assert adapters[0].search_keywords == [{"keyword": "아스날", "target": "title"},
                                           {"keyword": "온스테인", "target": "title_content"}]

def test_factory_passes_body_selector_to_html():
    from bullet_in.adapters.html import HtmlAdapter
    cfg = {"sources": [{"source_id": "bbc_sport", "adapter": "html", "enabled": True,
            "config": {"list_url": "https://b.test", "item_selector": "a.card",
                       "body_selector": ".article-body"}}]}
    a = build_adapters(cfg)[0]
    assert isinstance(a, HtmlAdapter) and a.body_selector == ".article-body"

def test_factory_passes_title_selector_to_html():
    from bullet_in.adapters.html import HtmlAdapter
    cfg = {"sources": [{"source_id": "bbc_sport", "adapter": "html", "enabled": True,
            "config": {"list_url": "https://b.test",
                       "item_selector": "[data-testid='main-content'] a",
                       "title_selector": "span[class*='LinkPostHeadline']"}}]}
    a = build_adapters(cfg)[0]
    assert isinstance(a, HtmlAdapter) and a.title_selector == "span[class*='LinkPostHeadline']"

def test_factory_passes_thumbnail_only_to_html():
    from bullet_in.adapters.html import HtmlAdapter
    cfg = {"sources": [{"source_id": "bbc_gossip", "adapter": "html",
                        "config": {"list_url": "https://x", "item_selector": "a",
                                   "thumbnail_only": True}}]}
    a = build_adapters(cfg)[0]
    assert isinstance(a, HtmlAdapter) and a.thumbnail_only is True

def test_factory_builds_arsenal_api_default_window():
    from bullet_in.adapters.arsenal_api import ArsenalApiAdapter, WINDOW_HOURS
    cfg = {"sources": [{"source_id": "arsenal_official", "adapter": "arsenal_api",
                        "enabled": True, "config": {}}]}
    a = build_adapters(cfg)[0]
    assert isinstance(a, ArsenalApiAdapter) and a.window_hours == WINDOW_HOURS

def test_factory_passes_self_source_to_x_playwright():
    cfg = {"sources": [{"source_id": "x_ornstein", "adapter": "x_playwright", "enabled": True,
                        "config": {"handle": "David_Ornstein", "self_source": True}}]}
    a = build_adapters(cfg)[0]
    assert a.self_source is True

def test_factory_x_playwright_defaults_to_cited_path():
    cfg = {"sources": [{"source_id": "x_afcstuff", "adapter": "x_playwright", "enabled": True,
                        "config": {"handle": "afcstuff"}}]}
    a = build_adapters(cfg)[0]
    assert a.self_source is False

def _fmkorea_cfg(extra_config=None):
    return {"sources": [
        {"source_id": "fmkorea", "adapter": "fmkorea", "enabled": True,
         "config": {"search_url": "https://fm.test/s?t={target}&kw={keyword}",
                    "search_keywords": [{"keyword": "아스날", "target": "title"}],
                    **(extra_config or {})}}]}

def test_factory_injects_fmkorea_relevance_filter():
    cfg = _fmkorea_cfg({"relevance_terms": ["아스날", "아스널", "arsenal"]})
    a = build_adapters(cfg, fmkorea_player_names={"디오망데"})[0]
    assert a.relevance_terms == ["아스날", "아스널", "arsenal"]
    assert a.player_names == {"디오망데"}

def test_factory_fmkorea_no_filter_by_default():
    # relevance_terms 없는 config + player_names 미전달 = 필터 없음 (기존 동작)
    a = build_adapters(_fmkorea_cfg())[0]
    assert a.relevance_terms == [] and a.player_names == set()

def test_live_config_has_relevance_terms_triple():
    # 재발 방지 규칙 (트러블슈팅 2026-08-01 §4): 구단명 판정은 3종 동시
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    c = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")["config"]
    assert set(c["relevance_terms"]) == {"아스날", "아스널", "arsenal"}


def test_factory_skips_sources_marked_not_to_collect():
    # 수집만 멈추고 표시 설정은 남긴다 — enabled 를 끄면 언론사 이름 · 공신력 ·
    # 본문 서빙 범위가 함께 사라져 이미 적재된 기사가 깨진다.
    cfg = {"sources": [
        {"source_id": "keep", "adapter": "rss", "config": {"feed_url": "a"}},
        {"source_id": "stopped", "adapter": "rss", "collect": False,
         "config": {"feed_url": "b"}}]}
    assert [a.source_id for a in build_adapters(cfg)] == ["keep"]


def test_sources_marked_not_to_collect_stay_in_the_display_config():
    # load_sources 는 collect 를 안 본다 — 그래서 저장된 기사의 표시가 유지된다
    from bullet_in.score import load_sources
    import tempfile, pathlib, yaml
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d, "s.yaml")
        p.write_text(yaml.safe_dump({"sources": [
            {"source_id": "stopped", "adapter": "rss", "collect": False,
             "outlet": "Goal.com", "serving": "full", "tier": 4}]}))
        assert "stopped" in load_sources(p)
