"""수집 현황 화면의 뷰모델 — 절 열이 목업 v2.8 의 id 로 나오고 값이 손 재계산과 맞는지.

픽스처는 작게 잡았다. 기대값은 전부 주석의 셈으로 따라갈 수 있다.
"""
from datetime import datetime

from bullet_in.dbt_gate import GateTally, TestOutcome
from bullet_in.serve.ops_view import NO_GATE, UNNAMED, build_ops_view

NOW = datetime(2026, 9, 5, 0, 10)                                  # UTC


def _run(rid, t, new, dup, err=0, dur=100.0, fetch=60.0, counts=None, sr=1.0):
    return {"run_id": rid, "started_at": t, "duration_sec": dur, "fetch_duration_sec": fetch,
            "source_counts": counts or {}, "new_count": new, "dup_count": dup,
            "error_count": err, "success_rate": sr}


RUNS = [_run("r0", datetime(2026, 8, 27, 0, 0), 10, 0, counts={"bbc_sport": 10}),          # 주 08/24
        _run("r1", datetime(2026, 9, 3, 0, 0), 4, 40, counts={"bbc_sport": 3, "fmkorea": 1}),
        _run("r2", datetime(2026, 9, 3, 3, 0), 2, 38, err=1, dur=300.0, sr=0.9, counts={"fmkorea": 2}),
        _run("r3", datetime(2026, 9, 4, 0, 0), 6, 54, dur=120.0, fetch=None, counts={"bbc_sport": 6})]
T = datetime(2026, 9, 4, 0, 2)
FRESH = [{"run_id": "r1", "checked_at": datetime(2026, 9, 3, 0, 2), "source_id": "bbc_sport",
          "last_fetched_at": datetime(2026, 9, 2, 20, 0), "age_hours": 4.0, "threshold_hours": 96.0, "stale": 0},
         {"run_id": "r3", "checked_at": T, "source_id": "bbc_sport",
          "last_fetched_at": datetime(2026, 9, 3, 20, 0), "age_hours": 4.0, "threshold_hours": 96.0, "stale": 0},
         {"run_id": "r3", "checked_at": T, "source_id": "fmkorea",
          "last_fetched_at": datetime(2026, 9, 2, 18, 0), "age_hours": 30.0, "threshold_hours": 24.0, "stale": 1},
         {"run_id": "r3", "checked_at": T, "source_id": "never",
          "last_fetched_at": None, "age_hours": None, "threshold_hours": 48.0, "stale": 0}]
LATENCY = [("bbc_sport", 1.0), ("bbc_sport", 3.0), ("bbc_sport", 100.0), ("fmkorea", 20.0)]
MIX = [{"yw": 202636, "tier": 4.0, "stage": "rumour", "n": 6, "n_byline": 3},        # 주 08/31
       {"yw": 202636, "tier": 1.0, "stage": "official", "n": 4, "n_byline": 4},
       {"yw": 202635, "tier": 2.0, "stage": None, "n": 5, "n_byline": 0}]            # 주 08/24 · 단계 없음 → 기타
SUBJECTS = [{"player_id": 1, "ko_name": "기마랑이스", "category": "squad", "n": 149},
            {"player_id": 2, "ko_name": "알바레스", "category": "external", "n": 103},
            {"player_id": 3, "ko_name": None, "category": "external", "n": 60},
            {"player_id": 4, "ko_name": "", "category": "external", "n": 45}]
GATE = GateTally(generated_at="2026-09-04T21:03:00.000000Z", unique_total=5, unique_failed=[],
                 not_null_total=10, not_null_failed=[TestOutcome("not_null_stg_articles_transfer_stage", 2)])
SNAPSHOT = {"runs_all": RUNS, "freshness": FRESH, "latency": LATENCY, "weekly_mix": MIX,
            "player_subjects": SUBJECTS, "articles_total": 200,
            "high_retention": [{"content_hash": "a" * 64, "outlet": "The Athletic", "retention": 0.934}]}
EMPTY = {"runs_all": [], "freshness": [], "latency": [], "weekly_mix": [], "player_subjects": [],
         "articles_total": 0, "high_retention": []}
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"}, "fmkorea": {"display_name": "fmkorea"},
           "dead": {"display_name": "Dead"}}
UNMATCHED = [{"date": "2026-09-03", "source": "bbc_sport", "title": "추출 실패 기사"}]
IDS = ["sec-slo", "sec-ingestion-volume", "sec-source-coverage", "sec-throughput", "sec-run-duration",
       "sec-ingestion-latency", "sec-coverage-by-player", "sec-credibility-mix-stage-mix",
       "sec-source-freshness", "sec-review-tables"]


def _view(snapshot=SNAPSHOT, gate=GATE, anomaly=0):
    return build_ops_view(snapshot, SOURCES, anomaly, NOW, gate=gate, unmatched=UNMATCHED)


def _flat(view):
    return [s for item in view["sections"] for s in (item["pair"] if "pair" in item else [item])]


def _sec(view, id_):
    return next(s for s in _flat(view) if s["id"] == id_)


def test_절_열이_목업의_id_순서로_나온다():
    view = _view()
    assert [s["id"] for s in _flat(view)] == IDS
    assert all(not s["missing"] for s in _flat(view))          # 수집 현황에는 빈 구간이 없다 (스펙 §4)
    assert view["generated_at"] == "2026-09-05 00:10 UTC"


def test_타일_여섯은_최근_30회에서_만든다():
    tiles = {t["label"]: t for t in _view()["tiles"]}
    assert len(tiles) == 6
    assert tiles["신규 · 최근 회차"]["value"] == "6" and tiles["신규 · 최근 회차"]["sub"] == "09-04 00:00 UTC"
    assert tiles["Dedup Rate · 4회"]["value"] == "86%"          # 132 / (22 + 132) = 85.7
    assert tiles["Success Rate · 4회"]["value"] == "97.5%"      # (1 + 1 + .9 + 1) / 4
    assert tiles["Run Duration p50 · 4회"]["value"] == "120초"  # [100, 100, 120, 300] 의 p50
    assert tiles["Run Duration p50 · 4회"]["sub"] == "fetch 60초"
    assert tiles["Stale Sources"]["value"] == "1"
    assert tiles["Runs · 12주"]["value"] == "4"                 # 06-12 에서 09-05 = 86일 = 12주
    assert tiles["Runs · 12주"]["sub"] == "에러 회차 1 · 기대 8/일"


def test_slo_여섯_행의_값과_상태():
    rows = {r["slo_id"]: r for r in _view()["slo"]}
    assert list(rows) == ["SLO-1", "SLO-2", "SLO-3", "SLO-4", "SLO-5", "SLO-6"]
    assert rows["SLO-1"]["value"] == "56.5%↓" and rows["SLO-1"]["status"] == "ok"
    assert rows["SLO-2"]["value"] == "97.5%" and rows["SLO-2"]["status"] == "bad"      # 목표 99%
    assert rows["SLO-3"]["value"] == "0%" and rows["SLO-3"]["status"] == "ok"
    assert rows["SLO-3"]["how"] == "dbt unique 테스트 5종 통과 · 게이트 09-04 21:03 UTC"
    assert rows["SLO-4"]["value"] == "99.0%" and rows["SLO-4"]["status"] == "ok"       # 1 − 2 / 200
    assert "10종 가운데 1종 결측 2행" in rows["SLO-4"]["how"]
    assert rows["SLO-5"]["value"] == "1" and rows["SLO-5"]["status"] == "bad"
    assert rows["SLO-6"]["value"] == "0" and rows["SLO-6"]["status"] == "ok"
    body = str(_sec(_view(), "sec-slo")["body"])
    assert body.count("<tr>") == 7 and "✕ 미달" in body           # 머리 1 + 행 6


def test_게이트_결과가_없으면_3_4_는_참고_행이다():
    rows = {r["slo_id"]: r for r in _view(gate=None)["slo"]}
    assert rows["SLO-3"]["value"] == NO_GATE and rows["SLO-3"]["status"] == "info"
    assert rows["SLO-4"]["value"] == NO_GATE and rows["SLO-4"]["status"] == "info"


def test_unique_실패는_중복_적재율로_바뀐다():
    gate = GateTally(generated_at="", unique_total=5, unique_failed=[TestOutcome("unique_stg_articles_url", 3)],
                     not_null_total=10, not_null_failed=[])
    rows = {r["slo_id"]: r for r in _view(gate=gate)["slo"]}
    assert rows["SLO-3"]["value"] == "1.50%" and rows["SLO-3"]["status"] == "bad"     # 3 / 200
    assert rows["SLO-4"]["value"] == "100.0%"


def test_수집량_표는_회차가_있는_날만_적는다():
    body = str(_sec(_view(), "sec-ingestion-volume")["body"])
    assert body.count("<tr><td>2026-") == 3
    # 09-03: 신규 4 + 2 · 중복 40 + 38 · 회차 2 · 에러 1 · p50 of [100, 300] = 300
    assert "<tr><td>2026-09-03</td><td>6</td><td>78</td><td>2</td><td>1</td><td>300</td></tr>" in body
    assert "기대 8" in body and ">Airflow<" in body               # 기준선과 전환 표시


def test_소스_커버리지는_회차_기록의_소스별_건수를_주로_묶는다():
    body = str(_sec(_view(), "sec-source-coverage")["body"])
    assert "BBC Sport · 08/31\n9건" in body                      # 3 + 6
    assert "fmkorea · 08/31\n3건" in body                        # 1 + 2
    assert "BBC Sport · 08/24\n10건" in body
    assert "Dead · 08/31\n0건" in body                           # 설정에만 있는 소스도 행이 있다
    cats = [c for c in ("BBC Sport", "fmkorea", "Dead") if f">{c}<" in body]
    assert body.index(">BBC Sport<") < body.index(">fmkorea<") < body.index(">Dead<")   # 합 내림차순


def test_처리량은_주별_합과_중복률이다():
    s = _sec(_view(), "sec-throughput")
    body = str(s["body"])
    assert "08/31\n12건 · 신규" in body and "08/24\n10건 · 신규" in body
    assert "08/31\n92% · Dedup Rate" in body                     # 132 / 144
    assert s["insights"][0] == ("12주 합은 신규 22건 · 중복 차단 132건이다.", ["중복이 신규의 6배다."])


def test_소요_절은_밴드_에러_표시_주별_구성을_그린다():
    s = _sec(_view(), "sec-run-duration")
    body = str(s["body"])
    assert body.count('class="fail"') == 1 and "09/03\n에러 회차 1회" in body
    assert 'class="band s1"' in body
    # 주 08/31: fetch (60 + 60 + 0) / 3 = 40 · 나머지 ((100−60) + (300−60) + 120) / 3 = 133.33
    assert "08/31\n40초 · 수집 (fetch)\n133.33초 · 번역 · 게이트 · 배포" in body
    assert s["insights"][0][0] == "지난 4회 p50 은 120초이고 fetch 가 60초다."
    assert s["insights"][1][0] == "1,000초를 넘긴 회차는 0회다."


def test_지연은_소스별_p50_p95_를_p50_순으로_로그_축에_그린다():
    s = _sec(_view(), "sec-ingestion-latency")
    body = str(s["body"])
    assert "BBC Sport\np50 3.0h · p95 100.0h\n기사 3건" in body
    assert body.index(">BBC Sport<") < body.index(">fmkorea<")
    assert s["insights"][1][0] == "회차 간격 (3시간) 안에 드는 소스는 1곳이다."


def test_선수_축은_주체만_세고_이름_없는_후보는_한_줄로_모은다():
    s = _sec(_view(), "sec-coverage-by-player")
    body = str(s["body"])
    assert "기마랑이스\n149건" in body and "알바레스\n103건" in body
    assert f"{UNNAMED}\n105건" in body                            # 60 + 45
    assert 'class="bar s1"' in body and 'class="bar s2"' in body and "dimbar dim" in body
    assert "357건만 세고" in " ".join(s["question"])              # 149 + 103 + 60 + 45


def test_구성_비율은_숫자를_적은_히트맵이고_빈_단계는_기타다():
    s = _sec(_view(), "sec-credibility-mix-stage-mix")
    body = str(s["body"])
    assert "4 타블로이드 · 08/31\n60%" in body and "1 최상 · 08/31\n40%" in body
    assert "루머 · 08/31\n60%" in body and "공식 · 완료 · 08/31\n40%" in body
    assert "기타 · 08/24\n100%" in body
    assert "08/31\n70% · 식별률" in body                          # 7 / 10
    assert s["insights"] == [("등급 4 비중이 가장 높은 주는 08/31 (60%) 다.", []),
                             ("기자 식별률은 0% 에서 70% 사이다.", [])]


def test_신선도_표는_임계_대비_비율_순이고_미터를_그린다():
    s = _sec(_view(), "sec-source-freshness")
    body = str(s["body"])
    assert body.index(">fmkorea<") < body.index(">BBC Sport<") < body.index(">never<")   # 1.25 · 0.04 · 0
    assert "✕ 초과" in body and 'class="fill bad"' in body
    assert "30.0h / 24h" in body and "이력 없음" in body
    assert s["insights"][0] == ("임계는 소스마다 다르다 (24h 에서 96h).", [])
    assert s["insights"][1] == ("임계를 넘은 소스는 fmkorea 다.", [])


def test_확인_대상_절은_두_표를_그대로_둔다():
    body = str(_sec(_view(), "sec-review-tables")["body"])
    assert f'href="article/{"a" * 64}.html">aaaaaaaa<' in body and ">0.93<" in body
    assert "추출 실패 기사" in body
    assert "재작성 잔존율 확인 대상 (1건)" in body and "선수 추출 누락 (1건)" in body


def test_빈_스냅샷이면_타일이_없고_절은_전부_그려진다():
    view = build_ops_view(EMPTY, SOURCES, 0, NOW, gate=None, unmatched=None)
    assert view["tiles"] == []
    assert [s["id"] for s in _flat(view)] == IDS
    rows = {r["slo_id"]: r for r in view["slo"]}
    assert rows["SLO-2"]["status"] == "info" and rows["SLO-5"]["status"] == "info"
    assert "아직 없다" in str(_sec(view, "sec-ingestion-latency")["body"])


def test_개요는_기사_총수와_기간을_적는다():
    ov = dict((lab, (txt, subs)) for lab, txt, subs in _view()["overview"])
    assert ov["기간"][0] == "2026-06-12 첫 라이브 실행부터 12주 (86일)."
    assert ("articles", "기사 200건 · 등급 · 이적 단계 · 발행 시각.") in ov["데이터 원천"][1]


def test_설명문은_문장마다_줄을_가른다():
    for s in _flat(_view()):
        assert len(s["question"]) >= 1 and all(q.endswith(".") for q in s["question"])


def test_회차_수_인사이트는_오늘을_빼고_회차가_있던_날만_센다():
    snap = dict(SNAPSHOT, runs_all=RUNS + [_run("r4", datetime(2026, 9, 5, 0, 5), 1, 9)])   # 오늘 · 회차 1
    s = _sec(build_ops_view(snap, SOURCES, 0, NOW, gate=GATE, unmatched=UNMATCHED), "sec-ingestion-volume")
    assert s["insights"][1] == ("회차가 있던 날 가운데 8회에 못 미친 날은 3일이다 (오늘 제외).", [])  # 08-27 · 09-03 · 09-04


def test_소요_선은_회차가_있던_날만_그린다():
    body = str(_sec(_view(), "sec-run-duration")["body"])
    line = body[:body.index("주별 회차당")]                    # 첫 figure (p50 선) 만
    assert line.count('class="hit"') == 3                      # 08/27 · 09/03 · 09/04
    assert "06/12" not in line


def test_등급이_없는_행은_등급_비율의_분모에서_빠진다():
    mix = [{"yw": 202636, "tier": 4.0, "stage": "rumour", "n": 6, "n_byline": 3},
           {"yw": 202636, "tier": None, "stage": "other", "n": 4, "n_byline": 0}]
    s = _sec(build_ops_view(dict(SNAPSHOT, weekly_mix=mix), SOURCES, 0, NOW, gate=GATE, unmatched=UNMATCHED),
             "sec-credibility-mix-stage-mix")
    body = str(s["body"])
    assert "4 타블로이드 · 08/31\n100%" in body               # 등급 분모 6 (None 제외)
    assert "기타 · 08/31\n40%" in body                        # 단계 분모 10 (전체)
    assert "08/31\n30% · 식별률" in body                       # 3 / 10
    assert s["insights"][0] == ("등급 4 비중이 가장 높은 주는 08/31 (100%) 다.", [])
