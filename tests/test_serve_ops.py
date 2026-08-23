from datetime import datetime
from bullet_in.serve.render import build_ops_view, render_ops, write_ops

NOW = datetime(2026, 7, 14, 9, 12, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"}}


def _snapshot():
    return {"runs": [{"run_id": "r1", "started_at": NOW, "duration_sec": 80.0,
                      "fetch_duration_sec": 10.0,
                      "source_counts": {"bbc_sport": 4}, "new_count": 4,
                      "dup_count": 2, "error_count": 0, "success_rate": 1.0}],
            "freshness": [{"run_id": "r1", "checked_at": NOW,
                           "source_id": "bbc_sport", "last_fetched_at": NOW,
                           "age_hours": 2.1, "threshold_hours": 48.0, "stale": 0}],
            "tier_counts": {2.0: 4}, "pending": {}}


def test_render_ops_contains_tiles_sections_and_labels():
    html = render_ops(build_ops_view(_snapshot(), SOURCES, 0, NOW))
    assert "수집 끊긴 소스" in html and "번역 · 분류 대기" in html
    for title in ("회차별 수집량", "소스별 신선도", "소스별 수집량",
                  "Tier 분포", "SLO 롤업"):
        assert title in html
    assert "2026-07-14 09:12 UTC" in html
    assert "<script" not in html                     # JS 금지 계약
    assert "polyline" in html                        # 스파크라인 존재


def test_render_ops_cold_start_survives():
    empty = {"runs": [], "freshness": [], "tier_counts": {}, "pending": {}}
    html = render_ops(build_ops_view(empty, SOURCES, 0, NOW))
    assert "이력 없음" in html and "—" in html


def test_write_ops_creates_file(tmp_path):
    write_ops(_snapshot(), SOURCES, tmp_path, anomaly_count=0, now=NOW)
    out = tmp_path / "ops.html"
    assert out.exists() and "bullet-in 수집 현황" in out.read_text(encoding="utf-8")


def test_build_ops_view_fetch_duration_row():
    view = build_ops_view(_snapshot(), SOURCES, 0, NOW)
    row = next(s for s in view["slo"] if s["slo_id"] == "fetch_duration")
    # 10.0 하나의 평균 = 10.0 → "10s" (손 재계산)
    assert row["value"] == "10s" and row["status"] == "info"
    assert row["definition"] == "최근 30회 평균 fetch 시간"


def test_build_ops_view_fetch_duration_all_null_shows_dash():
    snap = _snapshot()
    snap["runs"][0]["fetch_duration_sec"] = None      # 기존 13회 이력 = NULL 계약
    view = build_ops_view(snap, SOURCES, 0, NOW)
    row = next(s for s in view["slo"] if s["slo_id"] == "fetch_duration")
    assert row["value"] == "—"


def test_render_ops_stale_badge_renders():
    snap = _snapshot()
    snap["freshness"][0]["stale"] = 1                 # PR #39 이월 ③ — 미검증 경로
    html = render_ops(build_ops_view(snap, SOURCES, 0, NOW))
    assert "✕ 초과" in html and "b-stale" in html


def test_ops_view_lists_high_retention_rows():
    from bullet_in.serve.render import build_ops_view
    snap = {"runs": [], "freshness": [], "tier_counts": {}, "pending": {},
            "high_retention": [{"content_hash": "a" * 64, "outlet": "The Athletic",
                                "retention": 0.934}]}
    view = build_ops_view(snap, {}, anomaly_count=0,
                          now=datetime(2026, 7, 30, 12, 0, 0))
    assert view["high_retention_count"] == 1
    row = view["high_retention"][0]
    assert row["retention"] == "0.93"
    assert row["href"].endswith(f"article/{'a' * 64}.html")


def test_ops_page_is_kept_out_of_search_results():
    # 운영 뷰는 공개 화면에서 링크하지 않고 색인도 막는다 (2026-08-23 공개 준비).
    # 배포에는 그대로 올라가므로 주소를 아는 사람은 볼 수 있다 — 접근 차단이 아니다.
    html = render_ops(build_ops_view(_snapshot(), SOURCES, anomaly_count=0, now=NOW))
    assert '<meta name="robots" content="noindex,nofollow">' in html
