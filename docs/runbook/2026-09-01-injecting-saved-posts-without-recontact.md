# 이미 받아 둔 페이지로 fmkorea 글을 회차 밖에서 넣는 절차 (2026-09-01)

수집이 놓친 fmkorea 글을 손으로 넣어야 하는데 **그 사이트에 다시 접촉할 수 없을 때** 쓴다.
2026-09-01 에 이적시장 마감일 글 다섯 건을 이 방법으로 넣었고, fmkorea 재접촉은 **0회**였다.

기사 한 건을 정상 경로에 태우는 일반 절차는 `docs/runbook/2026-08-29-adding-one-article-outside-the-cycle.md` 에 있다.
이 문서는 그 절차에 **재접촉을 0으로 만드는 부분**만 더한다.

## 1. 왜 재접촉을 피하나

fmkorea 는 짧은 시간에 요청을 몰아 쓰면 430 을 준다
— 다만 몰아 쓰지 않아도 정기 회차의 19.1% 는 430 을 맞는다.
그리고 **이 저장소의 수집은 맥을 프록시로 삼아 나간다** (`FMKOREA_PROXY=socks5://127.0.0.1:1080` 역터널).

**즉 조사나 보수 작업의 접촉이 운영 회차와 같은 회선을 쓴다.**
2026-09-01 에 조사로 아홉 번 접촉해 430 을 받았고, 그 상태에서 페이지를 새로 받아 넣으려 했다면 실패했을 것이다.

이미 페이지를 받아 둔 상태라면 그것으로 끝낼 수 있다.

## 2. 준비 — 페이지를 파일로 갖고 있을 것

조사 단계에서 글 페이지를 받았다면 그대로 쓴다.

```bash
curl -sS -m 25 -A "Mozilla/5.0 bullet-in/0.1" "https://www.fmkorea.com/<글번호>" -o post-<글번호>.html
```

**받는 김에 파일로 남긴다** — 나중에 다시 받으려다 430 을 부르는 것이 흔한 실패다.

VM 으로 옮긴다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'mkdir -p /tmp/fmk-inject'
scp -i ~/.ssh/seoulnow_deploy post-*.html ubuntu@155.248.164.17:/tmp/fmk-inject/
```

## 3. fmkorea 요청만 파일로 답하는 transport

어댑터의 `_process` 는 글 페이지와 원문 기사를 모두 받아 온다.
**fmkorea 쪽만 가로채고 원문은 실제로 받는다** — 원문은 다른 사이트라 접촉 예산과 무관하다.

```python
class LocalFmkorea(httpx.AsyncHTTPTransport):
    """fmkorea 요청만 보유 파일로 답한다 — 없는 주소면 조용히 나가지 않고 멈춘다."""
    def __init__(self, files: dict[str, str]):
        super().__init__()
        self.files = files

    async def handle_async_request(self, request):
        u = str(request.url)
        if "fmkorea.com" in u:
            srl = u.rstrip("/").rsplit("/", 1)[-1]
            if srl not in self.files:
                raise RuntimeError(f"보유하지 않은 fmkorea 주소 — 접촉 차단: {u}")
            return httpx.Response(200, content=Path(self.files[srl]).read_bytes(),
                                  request=request)
        return await super().handle_async_request(request)
```

**없는 주소에서 예외를 던지는 것이 요점이다.**
그냥 통과시키면 의도치 않은 접촉이 조용히 나간다.

어댑터에서 부를 것은 `fetch()` 가 아니라 `_process()` 다
— `fetch()` 안의 `_discover()` 가 검색 페이지를 받으러 나가기 때문이다.

```python
a = FmkoreaAdapter(source_id="fmkorea", search_url=src["search_url"], search_keywords=[],
                   base_url=src["base_url"], body_selector=src["body_selector"],
                   relevance_terms=src["relevance_terms"],
                   player_names=pstore.confirmed_ko_names())
async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 bullet-in/0.1"},
                             transport=LocalFmkorea(files)) as c:
    raw = await a._process(c, matched)     # matched = [(제목, fmkorea 글 주소), ...]
```

## 4. dry-run 으로 대상을 먼저 센다

`--apply` 없이 한 번 돌려 `to_articles` 까지만 확인한다.

```
=== 적재 전 대조 (seen_map) ===
  291741f9e2f7 · 기존여부=False · [AS] 훌리안 알바레스의 현실, 결국 남을 운명
  ...
=== to_articles ===
  살아남은 행 5건 · drop 집계 {'dup_count': 0, 'blocked_count': 0, ...}
  dfc9c01e7065 tier=1.0 outlet=The Athletic jrn=David Ornstein
```

**이미 적재된 글은 빼라.**
다시 upsert 하면 원문 제목이 조금만 달라져도 `content_hash` 가 갈린다
(`docs/troubleshooting/2026-08-31-the-upsert-rewrote-the-hash-and-cut-the-links.md`).
선수 귀속은 `move_hash_refs` 가 따라가지만 번역 네 필드는 NULL 로 밀려 다시 만들고,
해시로 짓는 상세 페이지 주소도 함께 바뀐다.
2026-09-01 에는 여섯 건 중 한 건이 이미 있어 다섯 건만 넣었다.

## 5. 번역 · 분류는 대상만 좁혀서 돌린다

`rows_missing_translation()` 과 `rows_missing_stage()` 는 **전체**를 돌려준다.
그대로 쓰면 다른 대기 행까지 처리해 Gemini 호출이 늘고 예상 밖 변경이 생긴다.

```python
target = set(hashes)
missing = [r for r in mart.rows_missing_translation() if r["content_hash"] in target]
```

단계 분류도 같은 방식으로 좁힌다.
끝나고 **단계 빈 행이 0인지 확인한다** — 빈 행은 카드로 서지 못하고 화면에서 빠진다.

## 6. 재렌더 · 배포 · 확인

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd /home/ubuntu/bullet-in && set -a && source .env && set +a && \
   /home/ubuntu/.local/bin/uv run python -c "
import os
from sqlalchemy import create_engine
from bullet_in.confirm_player import _render
_render(create_engine(os.environ[\"MARIADB_URL\"]))
" && ./infra/deploy-site.sh'
```

확인은 배포본에 직접 요청해 응답 값으로 한다.

```bash
curl -sL -o /dev/null -w "%{http_code}\n" "https://bullet-in.pages.dev/article/<hash>.html"
curl -sL "https://bullet-in.pages.dev/" | grep -c "<hash>"
```

## 7. 밟은 함정 넷

- **`uv` 는 절대 경로로 부른다** — VM 의 로그인 셸이 아니면 `PATH` 에 없다 (`/home/ubuntu/.local/bin/uv`).
- **글 번호로 적재 여부를 판정하지 마라** — 저장되는 `url` 은 원문 주소다
(`docs/troubleshooting/2026-09-01-one-question-three-layers.md` §2).
- **heredoc 안 파이썬 코드에서 문자열 밖에 ASCII 밖 기호를 두지 마라** — `★` 하나에 `SyntaxError: invalid character` 가 났다.
- **재작성 재큐는 정상이다** — 게이트가 잔존을 잡으면 `title_ko` 를 비워 다음 회차에 다시 만든다.
그 글은 원 제목으로 화면에 나오며 회차가 지나면 채워진다.

## 8. 참조

- 일반 절차 — `docs/runbook/2026-08-29-adding-one-article-outside-the-cycle.md`
- 라이브 접촉 판단 — `docs/troubleshooting/2026-08-03-fmkorea-430-not-explained-by-our-requests.md`
- VM 수동 작업 — `docs/runbook/2026-07-20-vm-cohost-bootstrap.md`
