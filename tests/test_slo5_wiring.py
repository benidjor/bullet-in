from datetime import datetime
from bullet_in.run import FetchSummary, source_responses

SOURCES = {"bbc_sport": {"adapter": "html"}, "x_ornstein": {"adapter": "x_playwright"},
           "fmkorea": {"adapter": "fmkorea"}, "arsenal_official": {"adapter": "arsenal_api"}}


def _fetched(errors=None, funnels=None):
    return FetchSummary(run_id="r1", started_at_utc=datetime(2026, 10, 2), fetch_sec=1.0,
                        source_counts={}, candidate_counts={}, new_count=0, dup_count=0,
                        blocked_count=0, errors=errors or {}, funnels=funnels or {},
                        success_rate=1.0)


def test_source_responses_reads_errors_and_funnels_per_adapter():
    f = _fetched(errors={"x_ornstein": "Timeout 20000ms"},
                 funnels={"bbc_sport": {"deduped": 7, "titled": 1, "list_sig": "s1"},
                          "fmkorea": {"keywords": 3, "searched": 2, "listed": 40, "list_sig": "s2"}})
    got = source_responses(SOURCES, f)
    assert got["bbc_sport"] == (False, "title_ratio")
    assert got["x_ornstein"] == (False, "error")
    assert got["fmkorea"] == (True, "")
    assert got["arsenal_official"] == (False, "no_record")
