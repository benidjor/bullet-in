from __future__ import annotations
import socket
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

GAP_HOURS = 3.0
STATE_PATH = Path.home() / ".bullet-in" / "fmkorea_last_contact"

def should_supplement(last_contact: datetime | None, now: datetime,
                      gap_hours: float = GAP_HOURS) -> bool:
    """fmkorea 마지막 접촉에서 gap_hours 이상 지났으면 보충 수집.
    기록이 없으면 True. now · last_contact 는 같은 시계 (UTC) 여야 한다."""
    if last_contact is None:
        return True
    return now - last_contact >= timedelta(hours=gap_hours)

def read_last_contact(path: Path) -> datetime | None:
    """접촉 스탬프 파일 (ISO 8601) 을 읽는다. 없거나 못 읽으면 None."""
    try:
        return datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError):
        return None

def write_last_contact(path: Path, now: datetime) -> None:
    """접촉 시각 스탬프 — 신규 0건이어도 접촉했으면 기록한다 (가드 fail-open 방지)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(now.isoformat())

def tunnel_alive(proxy_url: str, timeout: float = 3.0) -> bool:
    """SOCKS 터널 포트 연결성 확인 — fmkorea 접촉 없이 TCP connect 만 시도."""
    u = urlparse(proxy_url)
    try:
        with socket.create_connection((u.hostname, u.port), timeout=timeout):
            return True
    except OSError:
        return False
