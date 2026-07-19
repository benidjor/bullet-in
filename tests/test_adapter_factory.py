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

def test_factory_builds_arsenal_api_with_pages():
    from bullet_in.adapters.arsenal_api import ArsenalApiAdapter
    cfg = {"sources": [{"source_id": "arsenal_official", "adapter": "arsenal_api",
                        "enabled": True, "config": {"pages": 2}}]}
    a = build_adapters(cfg)[0]
    assert isinstance(a, ArsenalApiAdapter) and a.pages == 2
