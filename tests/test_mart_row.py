import json
from datetime import datetime
from bullet_in.models import Article
from bullet_in.storage.mariadb import _article_row

def _article(**kw):
    base = dict(content_hash="h1", url="https://x/1", source_id="s",
                title_original="T", published_at=datetime(2026, 7, 15, 10, 0))
    base.update(kw)
    return Article(**base)

def test_article_row_serializes_images_json():
    row = _article_row(_article(images=["https://a/1.jpg", "https://a/2.jpg"]))
    assert json.loads(row["images_json"]) == ["https://a/1.jpg", "https://a/2.jpg"]
    assert "images" not in row  # SQL 파라미터에 미지의 키 금지

def test_article_row_empty_images_is_null():
    assert _article_row(_article())["images_json"] is None
