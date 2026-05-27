from bullet_in.serve.render import render_page

def test_render_escapes_scraped_html():
    arts = [{"title_original": "A & B <script>x</script>", "title_ko": None,
             "summary_ko": "", "url": "u1", "source_id": "s", "tier": 2,
             "confidence_score": 0.5}]
    html = render_page(arts)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html

def test_render_orders_by_confidence_desc_and_shows_korean_title():
    arts = [
        {"title_original": "Low", "title_ko": None, "summary_ko": "", "url": "u1",
         "source_id": "football_london", "tier": 4, "confidence_score": 0.0},
        {"title_original": "High", "title_ko": "높음", "summary_ko": "요약", "url": "u2",
         "source_id": "arsenal_official", "tier": 0, "confidence_score": 1.0},
    ]
    html = render_page(arts)
    assert html.index("높음") < html.index("Low")
    assert "원문" in html
