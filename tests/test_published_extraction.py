from datetime import datetime, timezone
from bullet_in.adapters.meta import extract_published_at

LD_TOP = ('<script type="application/ld+json">'
          '{"@type":"NewsArticle","datePublished":"2026-07-19T14:30:00+01:00"}'
          '</script>')
LD_GRAPH = ('<script type="application/ld+json">'
            '{"@graph":[{"@type":"WebPage"},'
            '{"@type":"NewsArticle","datePublished":"2026-07-19T09:15:00Z"}]}'
            '</script>')
LD_BROKEN = '<script type="application/ld+json">{broken json</script>'
META_TAG = ('<meta property="article:published_time" '
            'content="2026-07-19T07:40:00+00:00">')
TIME_TAG = '<time datetime="2026-07-18T22:00:00Z">yesterday</time>'

def test_jsonld_top_level_normalizes_to_utc():
    dt, prec = extract_published_at(f"<html><head>{LD_TOP}</head></html>")
    assert dt == datetime(2026, 7, 19, 13, 30, tzinfo=timezone.utc)  # +01:00 → UTC
    assert prec == "time"

def test_jsonld_graph_nested():
    dt, prec = extract_published_at(f"<html>{LD_GRAPH}</html>")
    assert dt == datetime(2026, 7, 19, 9, 15, tzinfo=timezone.utc)
    assert prec == "time"

def test_meta_tag_fallback_when_no_jsonld():
    dt, prec = extract_published_at(f"<html><head>{META_TAG}</head></html>")
    assert dt == datetime(2026, 7, 19, 7, 40, tzinfo=timezone.utc)

def test_time_tag_last_fallback():
    dt, _ = extract_published_at(f"<html><body>{TIME_TAG}</body></html>")
    assert dt == datetime(2026, 7, 18, 22, 0, tzinfo=timezone.utc)

def test_day_only_string_gives_day_precision_utc_midnight():
    html = ('<script type="application/ld+json">'
            '{"datePublished":"2026-07-19"}</script>')
    dt, prec = extract_published_at(html)
    assert dt == datetime(2026, 7, 19, tzinfo=timezone.utc)
    assert prec == "day"

def test_broken_jsonld_skipped_meta_used():
    dt, _ = extract_published_at(f"<html>{LD_BROKEN}{META_TAG}</html>")
    assert dt == datetime(2026, 7, 19, 7, 40, tzinfo=timezone.utc)

def test_none_when_nothing_found():
    assert extract_published_at("<html><body><p>hi</p></body></html>") is None
