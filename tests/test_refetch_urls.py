from datetime import datetime, timezone
from bullet_in.refetch_urls import build_item

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)

HTML = """<html><head>
<meta property="og:title" content="Arsenal complete Tzolis signing">
<meta property="og:image" content="https://img.test/t.jpg">
</head><body><article>Full body text here.</article></body></html>"""

def test_build_item_shapes_payload_like_html_adapter():
    # 정기 수집 (html 어댑터 상세 경로) 과 동형 payload — 가드의 same-source 갱신 경로로 통과
    it = build_item("bbc_sport", "https://www.bbc.com/sport/x", HTML, "article", NOW)
    assert it.source_type == "html"
    assert it.raw_payload["title"] == "Arsenal complete Tzolis signing"
    assert it.raw_payload["body"] == "Full body text here."
    assert it.raw_payload["image_url"] == "https://img.test/t.jpg"
    assert it.raw_payload["authors"] == []

def test_build_item_returns_none_without_title():
    # 제목 추출 실패 시 덮어쓰지 않는다 — 불완전 복원 방지
    assert build_item("bbc_sport", "https://x.test/a", "<html></html>", "article", NOW) is None

def test_build_item_without_body_selector_keeps_empty_body():
    it = build_item("bbc_sport", "https://x.test/a", HTML, None, NOW)
    assert it.raw_payload["body"] == ""
