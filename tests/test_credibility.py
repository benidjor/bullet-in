import pytest
from pathlib import Path
from datetime import datetime, timezone
from bullet_in.credibility import load_registry, resolve_tier
from bullet_in.models import RawItem

REG = Path(__file__).parent.parent / "config" / "credibility.yaml"

def test_load_registry_maps_aliases_lowercased():
    r = load_registry(REG)
    assert r.journalists["@david_ornstein"] == 1.0
    assert r.journalists["온스테인"] == 1.0
    assert r.outlets["디 애슬레틱"] == 1.0
    assert r.outlets["데일리 메일"] == 3.0

def test_load_registry_rejects_duplicate_alias(tmp_path):
    p = tmp_path / "dup.yaml"
    p.write_text(
        "journalists:\n"
        '  - {name: A, tier: 1, aliases: ["dup"]}\n'
        '  - {name: B, tier: 2, aliases: ["dup"]}\n'
        "outlets: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate alias"):
        load_registry(p)

def _item(source_id, payload):
    return RawItem(source_id=source_id, source_type="x", url="u",
                   fetched_at=datetime.now(timezone.utc), raw_payload=payload)

def test_resolve_fixed_source_returns_static_tier():
    sources = {"bbc_sport": {"tier": 1}}
    it = _item("bbc_sport", {"title": "Saka"})
    assert resolve_tier(it, sources, registry=None) == 1.0

def test_resolve_x_mentions_picks_highest_credibility():
    r = load_registry(REG)
    sources = {"x_afcstuff": {"credibility": "x_mentions"}}
    it = _item("x_afcstuff", {"text": "Per @David_Ornstein and @FabrizioRomano, deal close"})
    assert resolve_tier(it, sources, r) == 1.0  # min(1, 1.5)

def test_resolve_x_mentions_drops_when_no_journalist():
    r = load_registry(REG)
    sources = {"x_afcstuff": {"credibility": "x_mentions"}}
    it = _item("x_afcstuff", {"text": "huge news coming soon @nobody_here"})
    assert resolve_tier(it, sources, r) is None

def test_resolve_fmkorea_journalist_beats_outlet():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[데일리 메일] 루머", "body": "온스테인에 따르면 사실이다"})
    assert resolve_tier(it, sources, r) == 1.0  # 기자(1) > 매체 데일리메일(3)

def test_resolve_fmkorea_outlet_bracket():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[디 애슬레틱] 사카 재계약", "body": "내용"})
    assert resolve_tier(it, sources, r) == 1.0

def test_resolve_fmkorea_fallback_tier_four():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[무명 블로그] 카더라", "body": "출처 불명"})
    assert resolve_tier(it, sources, r) == 4.0
