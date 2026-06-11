from pathlib import Path
from bullet_in.credibility import load_registry

REG = Path("config/credibility.yaml")

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
    try:
        load_registry(p)
        assert False, "expected ValueError"
    except ValueError:
        pass
