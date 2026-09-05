"""수집 현황 화면 — 템플릿이 공통 뼈대를 상속하고 게이트 파일을 읽어 그리는지."""
import json
from datetime import datetime

from bullet_in.serve.ops_view import build_ops_view
from bullet_in.serve.render import render_ops, write_ops

NOW = datetime(2026, 9, 5, 0, 10)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"}}
SNAPSHOT = {"runs_all": [{"run_id": "r1", "started_at": datetime(2026, 9, 4, 0, 0), "duration_sec": 80.0,
                          "fetch_duration_sec": 10.0, "source_counts": {"bbc_sport": 4}, "new_count": 4,
                          "dup_count": 2, "error_count": 0, "success_rate": 1.0}],
            "freshness": [{"run_id": "r1", "checked_at": datetime(2026, 9, 4, 0, 2), "source_id": "bbc_sport",
                           "last_fetched_at": datetime(2026, 9, 3, 22, 0), "age_hours": 2.1,
                           "threshold_hours": 96.0, "stale": 0}],
            "latency": [("bbc_sport", 2.0)], "weekly_mix": [], "player_subjects": [],
            "articles_total": 10, "high_retention": []}
EMPTY = {"runs_all": [], "freshness": [], "latency": [], "weekly_mix": [], "player_subjects": [],
         "articles_total": 0, "high_retention": []}


def _html(snapshot=SNAPSHOT):
    return render_ops(build_ops_view(snapshot, SOURCES, 0, NOW))


def test_수집_현황_탭이_선택되고_행동_지표로_가는_링크가_있다():
    html = _html()
    assert 'href="ops.html" aria-current="page">수집 현황' in html
    assert 'href="behavior.html">행동 지표' in html
    assert "<title>bullet-in 수집 현황</title>" in html


def test_절_열이_id_와_svg_로_렌더된다():
    html = _html()
    assert html.count('class="sec"') == 10
    for id_ in ("sec-slo", "sec-ingestion-volume", "sec-source-freshness", "sec-review-tables"):
        assert f'id="{id_}"' in html
    assert html.count("<svg") >= 10
    assert "2026-09-05 00:10 UTC" in html


def test_검색엔진에_안_실린다():
    # 운영 뷰는 공개 화면에서 링크하지 않고 색인도 막는다 (2026-08-23 공개 준비). 접근 차단이 아니다.
    assert '<meta name="robots" content="noindex,nofollow">' in _html()


def test_툴팁_목차_js_가_공통_뼈대에서_온다():
    html = _html()
    assert "<script" in html and 'id="tip"' in html and 'id="toc"' in html
    assert "app.js" not in html                                   # 사이트 JS 는 안 싣는다 (스펙 §3.3)


def test_write_ops_는_게이트_파일을_읽어_slo_3_4_를_채운다(tmp_path):
    gate = tmp_path / "run_results.json"
    gate.write_text(json.dumps({"metadata": {"generated_at": "2026-09-04T21:03:00Z"}, "results": [
        {"unique_id": "test.bullet_in.unique_stg_articles_url.a", "status": "pass", "failures": 0},
        {"unique_id": "test.bullet_in.unique_stg_articles_content_hash.b", "status": "pass", "failures": 0},
        {"unique_id": "test.bullet_in.not_null_stg_articles_url.c", "status": "pass", "failures": 0}]}))
    write_ops(SNAPSHOT, SOURCES, tmp_path, anomaly_count=0, now=NOW, gate_path=gate)
    html = (tmp_path / "ops.html").read_text(encoding="utf-8")
    assert "dbt unique 테스트 2종 통과 · 게이트 09-04 21:03 UTC" in html
    assert "dbt not_null 테스트 1종 통과 · 같은 게이트" in html


def test_write_ops_는_게이트_파일이_없어도_그린다(tmp_path):
    write_ops(SNAPSHOT, SOURCES, tmp_path, anomaly_count=0, now=NOW, gate_path=tmp_path / "missing.json")
    html = (tmp_path / "ops.html").read_text(encoding="utf-8")
    assert "게이트 결과 없음" in html and "bullet-in 수집 현황" in html


def test_빈_스냅샷도_페이지가_나온다():
    html = _html(EMPTY)
    assert html.count('class="sec"') == 10 and "회차 이력이 아직 없다" in html
