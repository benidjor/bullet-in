from __future__ import annotations
import os
from datetime import datetime, timezone
from bullet_in.models import RawItem

def tweets_to_items(source_id: str, handle: str, tweets) -> list[RawItem]:
    now = datetime.now(timezone.utc)
    out = []
    for t in tweets:
        out.append(RawItem(
            source_id=source_id, source_type="x",
            url=f"https://x.com/{handle}/status/{t.id}", fetched_at=now,
            raw_payload={"text": t.text,
                         "created_at": str(getattr(t, "created_at", ""))}))
    return out

class XAdapter:
    source_type = "x"
    def __init__(self, source_id: str, handle: str, max_tweets: int = 20):
        self.source_id, self.handle, self.max_tweets = source_id, handle, max_tweets
    async def fetch(self) -> list[RawItem]:
        from twikit import Client
        client = Client("en-US")
        cookies = "x_cookies.json"
        if os.path.exists(cookies):
            client.load_cookies(cookies)
        else:
            await client.login(auth_info_1=os.environ["X_USERNAME"],
                               auth_info_2=os.environ["X_EMAIL"],
                               password=os.environ["X_PASSWORD"])
            client.save_cookies(cookies)
        user = await client.get_user_by_screen_name(self.handle)
        tweets = await user.get_tweets("Tweets", count=self.max_tweets)
        return tweets_to_items(self.source_id, self.handle, tweets)
