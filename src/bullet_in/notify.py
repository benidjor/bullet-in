from __future__ import annotations
import logging, os
import httpx

logger = logging.getLogger(__name__)

COLOR_ANOMALY = 0xF2A600
COLOR_FAILURE = 0xE01E5A


def send_alert(title: str, description: str, *, color: int,
               fields: list[dict] | None = None) -> None:
    embed: dict = {"title": title, "description": description, "color": color}
    if fields:
        embed["fields"] = fields
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        logger.warning("알림 (webhook 미설정): %s — %s", title, description)
        return
    try:
        resp = httpx.post(url, json={"embeds": [embed]}, timeout=10)
        if resp.status_code >= 300:
            logger.warning("알림 발송 실패 (status %s): %s", resp.status_code, title)
    except httpx.HTTPError as e:
        logger.warning("알림 발송 오류: %s (%s)", title, e)
