"""이적시장 창 일정 — 서빙 (상단 바 타이머) 과 수집 (X 수집 시각 판정) 이 함께 쓴다."""
from __future__ import annotations

from datetime import datetime

# 이적시장 창 — 상단 바 타이머의 단일 원천 (2026-08-28 사용자 요청).
#
# 시각은 **현지 (런던) 기준을 오프셋까지 적어 절대 시각으로** 둔다. 「9월 1일 23시」
# 한 줄만 적으면 읽는 쪽 시간대에 따라 여덟 시간이 어긋난다 — 여름은 BST (+01:00),
# 겨울은 GMT (Z) 라 오프셋도 창마다 다르다.
# 계산 (지금이 어느 구간인가 · 얼마 남았나) 은 app.js 가 한다 — 렌더는 세 시간에 한
# 번이라 서버가 계산해 박으면 그사이에 낡는다. 여기는 재료만 둔다.
#
# **목록이 끝나면 타이머는 사라진다** — 다음 시즌 일정은 확정되면 여기에 더한다.
# 여름 개장일 (6월 1일) 은 프리미어리그 통상값을 쓴 가정이다 (사용자가 준 것은 마감
# 시각 셋뿐) — 2027 여름이 오기 전에 확인해서 고친다.
TRANSFER_WINDOWS: list[dict] = [
    {"name": "여름", "open": "2026-06-01T00:00:00+01:00",
     "close": "2026-09-01T23:00:00+01:00"},
    {"name": "겨울", "open": "2027-01-01T00:00:00+00:00",
     "close": "2027-02-01T23:00:00+00:00"},
]


def in_transfer_window(now: datetime) -> bool:
    """`now` (시간대가 있는 값) 가 어느 창 안인가 — open 이상 · close 미만."""
    return any(
        datetime.fromisoformat(w["open"]) <= now < datetime.fromisoformat(w["close"])
        for w in TRANSFER_WINDOWS
    )
