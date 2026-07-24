# fmkorea 1-B 정기 복구 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fmkorea 수집을 맥 경유 프록시로 복구하고, 맥이 켜질 때 밀린 글을 자동 보충 수집한다.

**Architecture:** fmkorea 어댑터가 프록시 (환경변수 `FMKOREA_PROXY`) 를 타면 발신 IP 가 맥 (주거) 이 된다.
정기 회차는 맥이 켜져 있을 때 터널을 타고, 맥 깨어남 시 보충 수집 스크립트가 마지막 접촉 3시간 초과분만 채운다.
보충 수집은 적재까지만 하고 번역 · 렌더는 다음 정기 회차가 흡수한다.

**Tech Stack:** Python 3.11 · httpx 0.28 (`proxy=`) · SQLAlchemy · pytest · respx · autossh · macOS launchd.

## Global Constraints

- httpx 0.28 은 `proxy=` 인자만 받는다 (`proxies=` 없음 · 0.28 에서 제거).
- 한국어 문자열 (로그 · 주석) 은 구현 시 그대로 유지한다 (Sonnet 전담 · Haiku 오염 방지).
- `proxy` 미지정 시 현행 동작 (직접 접속) 을 유지한다 — 로컬 개발 · 다른 소스 무영향.
- 보충 수집은 번역 · 렌더를 하지 않는다 (행 추가 백필의 수렴 패스 규칙 · 번역 전 상태 노출 방지).
- 중복 가드 기준 시각은 "마지막 접촉" 이다 — VM 접촉 스탬프 파일과 fmkorea `MAX(fetched_at)` (DB) 중 최신값 · 임계 3시간 · UTC 비교.
  DB 워터마크는 신규 행이 적재될 때만 전진하므로, 단독으로 쓰면 새 글 없는 시간대에 15분마다 재접촉하는 구멍 (fail-open) 이 생긴다.
- httpx 의 socks5 프록시는 `socksio` 패키지가 필요하다.
  현재는 twikit 의 transitive 의존으로만 설치돼 있어, pyproject 에 `httpx[socks]` 로 명시한다 (twikit 제거 시 조용히 깨지는 것 방지).
- 커밋은 컨벤션 §1.1 (본문 도입 + 불릿) · §1.3 (co-author 트레일러) 를 따른다.
  아래 각 Task 의 커밋 블록은 제목만 표기한 것이다.

---

### Task 1: fmkorea 어댑터 proxy 주입

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py` (`__init__` · `fetch`)
- Modify: `src/bullet_in/adapters/factory.py` (fmkorea 분기)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: 없음 (기존 `FmkoreaAdapter`).
- Produces: `FmkoreaAdapter(..., proxy: str | None = None)` — `proxy` 를 저장하고 `fetch` 의 `httpx.AsyncClient` 에 `proxy=` 로 전달. `factory.build_adapters` 가 `os.environ.get("FMKOREA_PROXY")` 를 넘김.

- [ ] **Step 1: proxy 저장 · 전달 실패 테스트 작성**

`tests/test_fmkorea_adapter.py` 끝에 추가:

```python
import httpx as _httpx
from bullet_in.adapters.fmkorea import FmkoreaAdapter as _FA

def test_fmkorea_adapter_stores_proxy():
    a = _FA(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
            search_keywords=[], proxy="socks5://127.0.0.1:1080")
    assert a.proxy == "socks5://127.0.0.1:1080"

def test_fmkorea_adapter_proxy_defaults_none():
    a = _FA(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
            search_keywords=[])
    assert a.proxy is None

@respx.mock
def test_fmkorea_fetch_passes_proxy_to_client(monkeypatch):
    seen = {}
    orig = _httpx.AsyncClient
    def spy(*args, **kwargs):
        seen["proxy"] = kwargs.get("proxy")
        return orig(*args, **kwargs)
    monkeypatch.setattr(_httpx, "AsyncClient", spy)
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=""))
    a = _FA(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
            search_keywords=[{"keyword": "kw1", "target": "title"}],
            base_url="https://www.fmkorea.com", proxy="socks5://127.0.0.1:1080")
    asyncio.run(a.fetch())
    assert seen["proxy"] == "socks5://127.0.0.1:1080"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k "proxy" -v`
Expected: FAIL (`TypeError: __init__() got an unexpected keyword argument 'proxy'`).

- [ ] **Step 3: 어댑터에 proxy 추가**

`src/bullet_in/adapters/fmkorea.py` `__init__` 시그니처와 본문 수정:

```python
    def __init__(self, source_id: str, search_url: str, search_keywords: list[dict],
                 item_selector: str = "a.hx",
                 base_url: str = "https://www.fmkorea.com",
                 body_selector: str = ".xe_content", max_posts: int = 15,
                 proxy: str | None = None):
        self.source_id = source_id
        self.search_url = search_url            # {keyword} · {target} 자리표시 포함
        self.search_keywords = search_keywords
        self.item_selector = item_selector
        self.base_url = base_url
        self.body_selector = body_selector
        self.max_posts = max_posts
        self.proxy = proxy
```

`fetch` 의 `AsyncClient` 생성에 `proxy` 전달:

```python
    async def fetch(self) -> list[RawItem]:
        headers = {"User-Agent": "Mozilla/5.0 bullet-in/0.1"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers=headers, proxy=self.proxy) as c:
            matched = await self._discover(c)
            return await self._process(c, matched)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k "proxy" -v`
Expected: PASS (3건).

- [ ] **Step 5: factory 가 환경변수를 전달하도록 수정**

`src/bullet_in/adapters/factory.py` 상단에 `import os` 는 이미 있음. fmkorea 분기 수정:

```python
        elif kind == "fmkorea":
            out.append(FmkoreaAdapter(
                sid, c["search_url"], c["search_keywords"],
                item_selector=c.get("item_selector", "a.hx"),
                base_url=c.get("base_url", "https://www.fmkorea.com"),
                body_selector=c.get("body_selector", ".xe_content"),
                max_posts=c.get("max_posts", 15),
                proxy=os.environ.get("FMKOREA_PROXY")))
```

- [ ] **Step 6: httpx socks extra 명시**

`pyproject.toml` 의 `"httpx>=0.27",` 를 `"httpx[socks]>=0.27",` 로 변경 후 `uv sync --extra dev`.
socksio 는 이미 venv 에 있으므로 (twikit transitive) lock 은 extra 표기만 바뀐다.

- [ ] **Step 7: 전체 fmkorea 테스트 회귀 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: PASS (기존 + 신규 전부). proxy 미지정 기존 테스트가 그대로 통과 (기본값 None).

- [ ] **Step 8: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py src/bullet_in/adapters/factory.py tests/test_fmkorea_adapter.py pyproject.toml uv.lock
git commit -m "feat(collect): fmkorea 어댑터 proxy 주입 (FMKOREA_PROXY 환경변수)"
```

---

### Task 2: 보충 수집 가드 (접촉 스탬프 · 터널 체크)

**Files:**
- Create: `src/bullet_in/collect_fmkorea.py`
- Test: `tests/test_collect_fmkorea.py`

**Interfaces:**
- Consumes: 없음.
- Produces: `should_supplement(last_contact: datetime | None, now: datetime, gap_hours: float = 3.0) -> bool`
  · `read_last_contact(path: Path) -> datetime | None` / `write_last_contact(path: Path, now: datetime) -> None` (접촉 스탬프 파일 · ISO 8601)
  · `tunnel_alive(proxy_url: str, timeout: float = 3.0) -> bool` (SOCKS 포트 TCP 연결성만 확인 · fmkorea 접촉 없음).

- [ ] **Step 1: 가드 · 스탬프 · 터널 체크 테스트 작성**

`tests/test_collect_fmkorea.py` 생성:

```python
import socket
from datetime import datetime, timedelta, timezone
from bullet_in.collect_fmkorea import (should_supplement, read_last_contact,
                                       write_last_contact, tunnel_alive)

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

def test_supplement_when_no_record():
    assert should_supplement(None, _NOW) is True

def test_skip_when_within_gap():
    assert should_supplement(_NOW - timedelta(hours=2), _NOW) is False

def test_supplement_when_gap_exceeded():
    assert should_supplement(_NOW - timedelta(hours=4), _NOW) is True

def test_supplement_at_exact_gap():
    assert should_supplement(_NOW - timedelta(hours=3), _NOW) is True

def test_last_contact_roundtrip(tmp_path):
    p = tmp_path / "state" / "fmkorea_last_contact"
    write_last_contact(p, _NOW)          # 부모 디렉토리 자동 생성
    assert read_last_contact(p) == _NOW

def test_read_last_contact_missing(tmp_path):
    assert read_last_contact(tmp_path / "absent") is None

def test_read_last_contact_corrupt(tmp_path):
    p = tmp_path / "stamp"
    p.write_text("not-a-date")
    assert read_last_contact(p) is None

def test_tunnel_alive_when_port_listening():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert tunnel_alive(f"socks5://127.0.0.1:{port}") is True
    finally:
        srv.close()

def test_tunnel_dead_when_port_closed():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()                          # 닫힌 포트 = 터널 없음
    assert tunnel_alive(f"socks5://127.0.0.1:{port}", timeout=0.5) is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_collect_fmkorea.py -v`
Expected: FAIL (`ModuleNotFoundError: bullet_in.collect_fmkorea`).

- [ ] **Step 3: 가드 · 스탬프 · 터널 체크 구현**

`src/bullet_in/collect_fmkorea.py` 생성:

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_collect_fmkorea.py -v`
Expected: PASS (9건).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/collect_fmkorea.py tests/test_collect_fmkorea.py
git commit -m "feat(collect): fmkorea 보충 가드 — 접촉 스탬프 · 터널 체크 (3h)"
```

---

### Task 3: 보충 수집 스크립트 (fmkorea 만 fetch · 적재)

**Files:**
- Modify: `src/bullet_in/collect_fmkorea.py` (`build_fmkorea_adapter` · `main` 추가)
- Test: `tests/test_collect_fmkorea.py`

**Interfaces:**
- Consumes: `should_supplement` · `read_last_contact` · `write_last_contact` · `tunnel_alive` (Task 2) · `FmkoreaAdapter(proxy=...)` (Task 1) · `to_articles` · `MartStore` · `RawStore`.
- Produces: `build_fmkorea_adapter(cfg: dict, proxy: str | None) -> FmkoreaAdapter` · `async main(force: bool = False)` — enabled · 터널 · 가드 통과 시 fetch → 적재 (번역 · 렌더 없음).

- [ ] **Step 1: 어댑터 빌더 테스트 작성**

`tests/test_collect_fmkorea.py` 에 추가:

```python
from bullet_in.collect_fmkorea import build_fmkorea_adapter

_CFG = {"sources": [
    {"source_id": "bbc_sport", "adapter": "html", "config": {}},
    {"source_id": "fmkorea", "adapter": "fmkorea", "config": {
        "search_url": "https://fm.test/s?t={target}&kw={keyword}",
        "search_keywords": [{"keyword": "아스날", "target": "title"}],
        "max_posts": 15}}]}

def test_build_fmkorea_adapter_reads_config_and_proxy():
    a = build_fmkorea_adapter(_CFG, "socks5://127.0.0.1:1080")
    assert a.source_id == "fmkorea"
    assert a.proxy == "socks5://127.0.0.1:1080"
    assert a.max_posts == 15
    assert a.search_keywords == [{"keyword": "아스날", "target": "title"}]

def test_build_fmkorea_adapter_none_proxy():
    a = build_fmkorea_adapter(_CFG, None)
    assert a.proxy is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_collect_fmkorea.py -k "build" -v`
Expected: FAIL (`ImportError: cannot import name 'build_fmkorea_adapter'`).

- [ ] **Step 3: 빌더 · main 구현**

`src/bullet_in/collect_fmkorea.py` 에 추가 (상단 import 도 함께):

```python
import argparse, asyncio, logging, os
from pathlib import Path
import yaml
from sqlalchemy import create_engine
from pymongo import MongoClient
from bullet_in.adapters.fmkorea import FmkoreaAdapter
from bullet_in.canonical import content_hash, canonical_url
from bullet_in.pipeline import to_articles
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry
from bullet_in.storage.mongo import RawStore
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)


def build_fmkorea_adapter(cfg: dict, proxy: str | None) -> FmkoreaAdapter:
    """config 에서 fmkorea 소스 블록을 읽어 어댑터를 만든다 (factory 와 동일 인자)."""
    s = next(x for x in cfg["sources"] if x["source_id"] == "fmkorea")
    c = s["config"]
    return FmkoreaAdapter(
        "fmkorea", c["search_url"], c["search_keywords"],
        item_selector=c.get("item_selector", "a.hx"),
        base_url=c.get("base_url", "https://www.fmkorea.com"),
        body_selector=c.get("body_selector", ".xe_content"),
        max_posts=c.get("max_posts", 15), proxy=proxy)


async def main(force: bool = False) -> None:
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    src = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")
    if not src.get("enabled", True):
        log.info("fmkorea 비활성 (enabled: false) — 보충 수집 스킵")
        return
    proxy = os.environ.get("FMKOREA_PROXY")
    if proxy and not tunnel_alive(proxy):
        log.info("fmkorea 터널 미접속 — 보충 수집 스킵 (스탬프 없음 · 다음 주기 재시도)")
        return

    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()

    now = mart.db_now()
    marks = [t for t in (read_last_contact(STATE_PATH),
                         mart.source_watermarks().get("fmkorea")) if t]
    last = max(marks) if marks else None
    if not force and not should_supplement(last, now):
        log.info("fmkorea 보충 수집 스킵 — 마지막 접촉 %s (3h 이내)", last)
        return

    adapter = build_fmkorea_adapter(cfg, proxy)
    raw = await adapter.fetch()
    write_last_contact(STATE_PATH, now)  # 신규 0 이어도 접촉 스탬프 (15분 재접촉 방지)
    if not raw:
        log.info("fmkorea 보충 수집 — 신규 0 (새 글 없음 · 전부 스킵)")
        return

    for it in raw:
        it.content_hash = content_hash(
            it.raw_payload.get("title") or "", canonical_url(it.url))
    mongo = MongoClient(os.environ["MONGO_URI"])[os.environ.get("MONGO_DB", "bulletin")]
    RawStore(mongo).insert_many(raw)

    arts, stats = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
    n = mart.upsert(arts)
    # 번역 · 분류 · 렌더는 하지 않는다 — 다음 정기 회차가 흡수 (번역 전 상태 노출 방지)
    log.info("fmkorea 보충 수집 완료 — 적재 %d · 중복 %d (번역 · 렌더는 다음 정기 회차)",
             n, stats["dup_count"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="중복 가드 무시하고 즉시 수집")
    asyncio.run(main(ap.parse_args().force))
```

- [ ] **Step 4: 빌더 테스트 통과 확인**

Run: `uv run pytest tests/test_collect_fmkorea.py -v`
Expected: PASS (Task 2 4건 + 빌더 2건).

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `uv run pytest -q`
Expected: 기존 통과 수 + 신규, 실패 0 (통합 테스트는 DB 없으면 skip).

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/collect_fmkorea.py tests/test_collect_fmkorea.py
git commit -m "feat(collect): fmkorea 보충 수집 스크립트 (가드 · fetch · 적재)"
```

---

### Task 4: 터널 · launchd · VM 트리거 · 런북

**Files:**
- Create: `infra/mac-fmkorea-relay/com.bulletin.fmkorea-tunnel.plist` (autossh 상주)
- Create: `infra/mac-fmkorea-relay/com.bulletin.fmkorea-supplement.plist` (깨어남 보충 트리거)
- Create: `infra/mac-fmkorea-relay/supplement.sh` (터널 위 VM 원격 실행)
- Create: `docs/runbook/2026-07-25-fmkorea-mac-relay-setup.md`

**Interfaces:**
- Consumes: `collect_fmkorea.main` (Task 3) · `FMKOREA_PROXY` 환경변수.
- Produces: 인프라 설정 · 라이브 검증 절차 (코드 단위 테스트 없음 · 라이브 검증 기반).

- [ ] **Step 1: 역SSH 터널 plist 작성**

`infra/mac-fmkorea-relay/com.bulletin.fmkorea-tunnel.plist` — autossh 로 VM 에 동적 SOCKS 역포워딩을 상주.
`<포트>` 는 VM 에서 쓸 로컬 포트 (예: 1080) · 키 · 호스트는 런북 기준.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.bulletin.fmkorea-tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/autossh</string>
    <string>-M</string><string>0</string>
    <string>-N</string>
    <string>-o</string><string>ServerAliveInterval=30</string>
    <string>-o</string><string>ServerAliveCountMax=3</string>
    <string>-o</string><string>ExitOnForwardFailure=yes</string>
    <string>-i</string><string>/Users/aryijq/.ssh/seoulnow_deploy</string>
    <string>-R</string><string>1080</string>
    <string>ubuntu@155.248.164.17</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>/tmp/fmkorea-tunnel.err</string>
</dict>
</plist>
```

- [ ] **Step 2: VM 원격 실행 스크립트 작성**

`infra/mac-fmkorea-relay/supplement.sh` — 터널이 붙은 VM 에서 보충 수집을 1회 실행.
`.env` 로드 (프로젝트는 dotenv 미사용 · 셸 export 필요) 후 `FMKOREA_PROXY` 를 로컬 포워딩 포트로 지정.
원격 명령은 반드시 **하나의 인자로 인용**한다
— `ssh host bash -lc '멀티라인'` 처럼 나눠 넘기면 ssh 가 인자를 공백으로 이어붙여, 원격 셸이 첫 줄만 `bash -c "cd"` 로 실행하고 나머지 줄은 홈 디렉토리에서 기본 셸로 실행해 `.env` 로드가 깨진다.

```bash
#!/usr/bin/env bash
set -euo pipefail
ssh -i /Users/aryijq/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && set -a && source .env && set +a && export FMKOREA_PROXY=socks5://127.0.0.1:1080 && uv run python -m bullet_in.collect_fmkorea"'
```

- [ ] **Step 3: 깨어남 보충 트리거 plist 작성**

`infra/mac-fmkorea-relay/com.bulletin.fmkorea-supplement.plist` — 맥 깨어남 · 주기 도래 시 `supplement.sh` 실행.
`StartInterval` 은 자주 깨어도 스크립트 내부 가드 (3h) 가 접촉을 제한하므로 낮게 (예: 900초) 둬도 안전.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.bulletin.fmkorea-supplement</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/aryijq/Documents/01_DE_project/bullet-in/infra/mac-fmkorea-relay/supplement.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardErrorPath</key><string>/tmp/fmkorea-supplement.err</string>
  <key>StandardOutPath</key><string>/tmp/fmkorea-supplement.out</string>
</dict>
</plist>
```

- [ ] **Step 4: VM 에 프록시 환경변수 등록**

VM `/home/ubuntu/bullet-in/.env` 에 정기 회차용 `FMKOREA_PROXY` 를 추가한다.
서비스는 `EnvironmentFile=/home/ubuntu/bullet-in/.env` 로 이를 로드하므로 (실측 확인 2026-07-25), 정기 회차도 프록시를 탄다.
맥이 꺼져 터널이 없으면 프록시 연결이 실패해 `httpx.HTTPError` 가 나고, `_discover` 의 키워드 스킵 강등 (기존 동작) 으로 안전하게 degrade 한다.

```bash
# VM: /home/ubuntu/bullet-in/.env
FMKOREA_PROXY=socks5://127.0.0.1:1080
```

- [ ] **Step 5: 런북 작성 · 라이브 검증**

`docs/runbook/2026-07-25-fmkorea-mac-relay-setup.md` 에 설치 · 검증 · 롤백 절차를 적는다.
런북에는 VM 측 배포 (git pull · uv sync) 와 `supplement.sh` 실행 권한 부여도 포함한다.
라이브 검증 (§2.2 서식 · 접촉 예산 2h 준수):

```bash
# 0. VM 코드 배포 (httpx[socks] 반영 의존 동기화)
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && git pull && uv sync"'
# supplement.sh 실행 권한 (launchd 가 직접 실행)
chmod +x infra/mac-fmkorea-relay/supplement.sh
# 1. autossh 설치 · 터널 로드
brew install autossh
launchctl load infra/mac-fmkorea-relay/com.bulletin.fmkorea-tunnel.plist
# 2. VM 에서 터널 · 프록시 경유 fmkorea 200 확인 (직전 접촉 2h 후 1회)
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "curl -s -o /dev/null -w '%{http_code}\n' --socks5-hostname 127.0.0.1:1080 \
   'https://www.fmkorea.com/search.php?mid=football_news&search_target=title&search_keyword=%EC%95%84%EC%8A%A4%EB%82%A0'"
# 기대: 200 (직접 접속이면 430)
# 3. 보충 수집 1회 (force 로 가드 우회 · 적재 · 렌더 없음 확인)
launchctl load infra/mac-fmkorea-relay/com.bulletin.fmkorea-supplement.plist
```

- **검증 성공 기준** — VM 프록시 경유 fmkorea 가 200 · 보충 수집 로그에 "적재 N" · DB fmkorea `MAX(fetched_at)` 갱신.
  라이브 검증은 로컬 직접 접속으로 갈음하지 않는다 (발신 IP 가 다름).

- [ ] **Step 6: 커밋**

```bash
git add infra/mac-fmkorea-relay/ docs/runbook/2026-07-25-fmkorea-mac-relay-setup.md
git commit -m "feat(infra): fmkorea 맥 릴레이 터널 · 보충 수집 launchd · 런북"
```

---

## Self-Review

- **Spec coverage** — §4.1 터널 (Task 4) · §4.2 proxy 주입 (Task 1, 환경변수로 조정) · §4.3 정기 회차 강등 (Task 1 기본값 None · 기존 스킵 유지) · §4.4 보충 수집 · 가드 (Task 2 · 3) · 수렴 패스 규칙 (Task 3 번역 · 렌더 제외). 전 항목 커버.
- **spec 과의 차이** — proxy 를 sources.yaml 대신 환경변수 `FMKOREA_PROXY` 로 읽는다 (배포 환경 분리 · 시크릿 · 로컬 무영향). 사용자 통보 후 확정.
- **정기 회차 프록시 (확정)** — VM systemd 가 `EnvironmentFile` 로 `.env` 를 로드함을 실측 확인. `.env` 에 `FMKOREA_PROXY` 설정 시 정기 회차도 프록시를 타고, 맥 꺼짐 시 연결 실패 → 키워드 스킵으로 degrade.
- **테스트 한계** — proxy 는 respx 가 우회하므로 spy 로 전달만 검증한다. 실제 프록시 통과는 라이브 (Task 4 Step 5) 로만 확인 가능.
- **가드 재설계 (2026-07-25 재검토 반영)** — DB 워터마크 단독 가드는 새 글 없는 시간대에 전진하지 않아 15분마다 재접촉하는 fail-open 이었다.
  접촉 스탬프 파일 (신규 0건이어도 기록) + 터널 선체크 (미접속 시 스탬프 없이 종료) 로 접촉을 3시간당 1회로 제한한다.
- **잔여 리스크 (허용)** — 정기 회차의 fmkorea 접촉은 스탬프에 잡히지 않는다.
  새 글이 없는 시간대에는 정기 접촉 후 2시간 안에 보충 접촉이 드물게 겹칠 수 있다 (빈도 3시간당 최대 1회 · 주거 IP 기준 허용 수준).
- **재검토 반영 (기타)** — supplement.sh ssh 원격 명령 단일 인자 인용 (분해 시 `.env` 로드 깨짐) · pyproject `httpx[socks]` 명시 (twikit transitive 의존 탈피) · 보충 스크립트 `enabled: false` 존중 (spec §11 롤백 정합) · 런북에 VM 배포 절차 포함.

## 다음 PR

- PR 2 (온스테인 X 직접 수집) · PR 3 (fmkorea 소급 백필) 은 이 PR 머지 후 각각 별도 계획.
- SoT: `docs/superpowers/specs/2026-07-25-fmkorea-recovery-ornstein-x-design.md`.
