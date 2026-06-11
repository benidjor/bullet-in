from bullet_in.adapters.factory import build_adapters

def test_factory_builds_enabled_adapters(monkeypatch):
    monkeypatch.setenv("GUARDIAN_API_KEY", "k")
    cfg = {"sources": [
        {"source_id": "guardian", "adapter": "guardian_api", "enabled": True,
         "config": {"query": "Arsenal", "section": "football"}},
        {"source_id": "off", "adapter": "rss", "enabled": False, "config": {"feed_url": "x"}},
    ]}
    adapters = build_adapters(cfg)
    assert [a.source_id for a in adapters] == ["guardian"]

def test_factory_builds_fmkorea_adapter():
    cfg = {"sources": [
        {"source_id": "fmkorea", "adapter": "fmkorea", "enabled": True,
         "config": {"list_url": "https://fm.test/football_news",
                    "item_selector": "a.title", "keywords": ["아스날", "Arsenal"]}},
    ]}
    adapters = build_adapters(cfg)
    assert adapters[0].source_id == "fmkorea"
    assert adapters[0].keywords == ["아스날", "Arsenal"]
