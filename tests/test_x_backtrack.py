from bullet_in.adapters.x_backtrack import extract_entities

def test_extract_entities_multiword():
    assert "Jeremy Monga" in extract_entities("Man City working to sign Jeremy Monga")

def test_extract_entities_keeps_accent():
    ents = extract_entities("Arsenal hope to sign Bruno Guimarães this summer")
    assert "Bruno Guimarães" in ents

def test_extract_entities_skips_single_word():
    assert extract_entities("Arsenal are active") == []
