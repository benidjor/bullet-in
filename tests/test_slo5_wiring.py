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


def test_source_responses_marks_all_430_fmkorea_as_blocked():
    f = _fetched(funnels={"fmkorea": {"keywords": 5, "searched": 0, "listed": 0,
                                      "codes": {"430": 5}, "list_sig": ""}})
    assert source_responses(SOURCES, f)["fmkorea"] == (False, "blocked")


def test_blocked_miss_runs_reads_the_per_source_setting():
    from bullet_in.run import blocked_miss_runs
    assert blocked_miss_runs({"fmkorea": {"blocked_miss_runs": 8}, "bbc_sport": {}}) == {"fmkorea": 8}


def test_live_config_gives_fmkorea_eight_runs():
    from bullet_in.run import blocked_miss_runs
    from bullet_in.score import load_sources
    assert blocked_miss_runs(load_sources("config/sources.yaml")) == {"fmkorea": 8}


def test_list_unchanged_caps_reads_the_per_source_setting():
    from bullet_in.run import list_unchanged_caps
    assert list_unchanged_caps({"skysports": {"list_unchanged_cap_hours": 288},
                                "guardian": {}}) == {"skysports": 288.0}


def test_live_config_caps_sky_and_ornstein_only():
    from bullet_in.run import list_unchanged_caps
    from bullet_in.score import load_sources
    assert list_unchanged_caps(load_sources("config/sources.yaml")) == \
        {"skysports": 288.0, "x_ornstein": 240.0}
