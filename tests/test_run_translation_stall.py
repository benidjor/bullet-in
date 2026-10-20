"""번역 멈춤 알림의 배선 — 번역 대기 행에서 알림 페이로드까지 (안건 3α)."""
from datetime import datetime, timedelta

from bullet_in import notify
from bullet_in.run import translation_stall_payload

NOW = datetime(2026, 10, 20, 12, 0)
RID = "scheduled__2026-10-20T12:00:00+00:00"


def _wait(h, hours):
    return {"content_hash": h, "source_id": "fmkorea", "title_original": h,
            "url": f"https://x.test/{h}", "fetched_at": NOW - timedelta(hours=hours)}


def test_no_payload_while_every_wait_is_within_the_threshold():
    assert translation_stall_payload([_wait("a", 3), _wait("b", 6)], NOW, run_id=RID) is None
    assert translation_stall_payload([], NOW, run_id=RID) is None


def test_payload_lists_the_stale_rows_and_counts_every_wait():
    p = translation_stall_payload([_wait("a", 3), _wait("b", 12), _wait("c", 30)], NOW,
                                  run_id=RID)
    assert p["channel"] == notify.CHANNEL_INCIDENT
    assert "2건" in p["title"]
    body = next(f["value"] for f in p["fields"] if f["name"] == "8.5시간 넘게 기다리는 기사")
    assert body.index("- c ·") < body.index("- b ·")      # 오래 기다린 것부터
    assert "- a ·" not in body
    assert next(f["value"] for f in p["fields"] if f["name"] == "번역 대기 전체") == "3건"
