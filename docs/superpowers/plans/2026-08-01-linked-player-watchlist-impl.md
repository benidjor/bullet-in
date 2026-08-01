# 링크 선수 워치리스트 정기 수집 · fmkorea 무관 글 필터 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 활성 이적축 선수 ko_name 로테이션 검색 배치 (하루 4회) 와, 구단 키워드 · 확정 선수명 기반 무관 글 필터를 구현한다.

**Architecture:** 전용 배치 모듈 `watchlist_fmkorea.py` 를 신설하고 collect_fmkorea 의 공용 부품 (어댑터 factory · persist · 가드) 을 재사용한다.
무관 글 필터는 `FmkoreaAdapter` 생성자 선택 인자 2개로 넣고, 정기 회차 (run.py) 와 워치리스트 배치 양쪽이 같은 인정 집합을 주입한다.
스펙 SoT 는 `docs/superpowers/specs/2026-08-01-linked-player-watchlist-design.md` (PR #187 머지 완료) 다.

**Tech Stack:** Python 3.11 · httpx + BeautifulSoup · SQLAlchemy · pytest + respx · systemd timer.

## Global Constraints

- 보수안으로 시작: 하루 4배치 · 배치당 검색 10명 + fetch 상한 5 (스펙 §2). 증량은 관찰 후 사용자 결정.
- `relevance_terms` 는 아스날 · 아스널 · arsenal 3종 동시 (트러블슈팅 `docs/troubleshooting/2026-08-01-club-name-variant-bypasses-string-checks.md` §4 재발 방지 규칙).
- `collect_fmkorea.py` 의 변경은 `build_fmkorea_adapter` 선택 인자 1개 (`search_keywords`) 추가뿐 (스펙 §3.4 · 수술적 변경).
- 배치는 Gemini 호출 없음 — 적재만 하고 enrich 는 다음 정기 회차 위임.
- 활성 링크 명단은 실행 시점 DB 조회 — 선수명 하드코딩 금지.
- 구단 키워드는 config (`config/sources.yaml`) 소유 — 코드에 구단명을 박지 않는다 (멀티 클럽 대비).
- 필터 인자 미주입 시 필터 없음 — 백필 · 보충 수집 등 기존 호출부 무영향 (스펙 §3.2).
- 브랜치 = `feat/watchlist-batch` (워크트리 격리 · superpowers:using-git-worktrees).
- 커밋: `<type>(<scope>): 한국어 제목` + 도입 1–2문장 + 명사형 불릿 + `Refs:` + co-author 트레일러 (컨벤션 §1.1 · §1.3).
- docs 산출물은 §2.2 서식 (`→` · `—` 줄 시작 · 한 줄 = 한 문장 · `·` + 여는 괄호 양옆 띄우기).
- 라이브 접촉 규율: 직전 회차 200 확인 → tee 필수 → 출력 확인 목적 재실행 금지.
- PR 머지는 사용자 직접 — 세션은 push + PR 생성까지.

## 파일 구조

- Modify `src/bullet_in/adapters/fmkorea.py`
— 무관 글 필터 (생성자 인자 2개 + `_relevant`) · 검색 실패 카운터 · 필터 탈락 카운터.
- Modify `config/sources.yaml`
— fmkorea 블록에 `relevance_terms` 3종.
- Modify `src/bullet_in/adapters/factory.py`
— `build_adapters` 에 `fmkorea_player_names` 선택 인자 · fmkorea 분기에서 필터 주입.
- Modify `src/bullet_in/storage/players.py`
— `confirmed_ko_names()` (필터 인정 집합) · `active_link_players()` (로테이션 명단) 추가.
- Modify `src/bullet_in/run.py`
— engine · mart · pstore 생성을 어댑터 빌드 앞으로 이동 + 필터 주입.
- Modify `src/bullet_in/collect_fmkorea.py`
— `build_fmkorea_adapter` 에 `search_keywords` 선택 인자 1개.
- Create `src/bullet_in/watchlist_fmkorea.py`
— 배치 진입점 (커서 · 슬라이스 · 키워드 생성 · 가드 · main · CLI).
- Create `infra/systemd/bullet-in-watchlist.service` · `bullet-in-watchlist.timer`.
- Create `docs/runbook/2026-08-01-watchlist-batch-ops.md`
— 배치 관측 · 커서 리셋 · 증량 절차.
- Test: `tests/test_fmkorea_adapter.py` · `tests/test_adapter_factory.py` · `tests/test_collect_fmkorea.py` · `tests/test_watchlist_fmkorea.py` (신규) · `tests/integration/test_player_store.py`.

## 설계 메모 (구현자가 알아야 할 결정)

- **필터 주입 경로가 두 갈래인 이유**: 정기 회차는 `factory.build_adapters` 가 어댑터를 만들므로 인자로 주입한다.
워치리스트 배치는 `build_fmkorea_adapter` 재사용이 스펙 (§3.1) 인데, 이 함수의 변경은 인자 1개로 묶여 있다 (§3.4).
따라서 배치는 어댑터 생성 후 공개 속성 (`adapter.relevance_terms` · `adapter.player_names`) 에 직접 대입한다.
생성자 인자와 같은 이름의 평범한 인스턴스 속성이라 동작 차이는 없다.
- **보충 수집 (collect_fmkorea.main) 은 필터를 받지 않는다**: 스펙 §3.2 가 주입 지점을 정기 회차 · 워치리스트 배치 양쪽으로 한정했다.
- **필터 판정은 `_squash` 비교** (공백 무시 · 소문자화): 게시자가 "아스날이" 처럼 붙여 쓰는 실측과 Arsenal 대문자 표기를 흡수한다.
- **커서 전진 규칙** (스펙 §6): 검색 실패 (`search_failures > 0`) 가 하나라도 있으면 커서를 전진하지 않고 같은 슬라이스를 다음 배치에 재시도한다.
성공한 검색의 수집분은 그대로 적재한다 (중복은 dedup 흡수).
- **접촉 스탬프는 collect_fmkorea 와 공유** (`~/.bullet-in/fmkorea_last_contact`): 보충 수집 · 백필의 예산 판단이 배치 접촉을 보게 한다 (스펙 §4.5).
- **dry-run 도 접촉 스탬프는 기록** (실접촉이므로) · 커서는 전진하지 않고 적재도 없다.

---

### Task 1: FmkoreaAdapter 무관 글 필터 + 검색 실패 카운터

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py`
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: 기존 `FmkoreaAdapter.__init__` · `_discover` · `_process` · `_squash`.
- Produces: 생성자 선택 인자 `relevance_terms: list[str] | None = None` · `player_names: set[str] | None = None`, 인스턴스 속성 `self.relevance_terms: list[str]` · `self.player_names: set[str]` · `self.search_failures: int` · `self.relevance_dropped: int`, 메서드 `_relevant(title: str, body: str) -> bool`.
Task 2 (factory 주입) 와 Task 6 (배치의 속성 대입 · 커서 판단) 이 이 이름들을 그대로 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_fmkorea_adapter.py` 끝에 추가한다.
기존 상수 (`FREE_ART` 등) 와 respx 패턴을 재사용한다.

```python
# ---- 무관 글 필터 (스펙 2026-08-01 §3.2) ----

UNRELATED_SEARCH = ('<a class="hx" href="/index.php?document_srl=71">'
                    '[BBC] 유벤투스 새 감독 발표</a>')
UNRELATED_POST = ('<div class="xe_content"><p>유벤투스 소식.</p>'
                  '<p>https://ex.test/u</p></div>')
UNRELATED_ART = '<html><body><article><p>Juventus news only.</p></article></body></html>'

def _filter_adapter(**kw):
    return FmkoreaAdapter(
        source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
        search_keywords=[{"keyword": "kw1", "target": "title"}],
        base_url="https://www.fmkorea.com", **kw)

def _mock_single_post(search_html, post_html, art_html, art_url="https://ex.test/u"):
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        return_value=httpx.Response(200, text=search_html))
    respx.get("https://www.fmkorea.com/71").mock(
        return_value=httpx.Response(200, text=post_html))
    respx.get(art_url).mock(return_value=httpx.Response(200, text=art_html))

@respx.mock
def test_filter_off_when_not_injected():
    # 인자 미주입 = 필터 없음 — 백필 등 기존 호출부 회귀 가드
    _mock_single_post(UNRELATED_SEARCH, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter()
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_filter_passes_club_term_in_title():
    search = ('<a class="hx" href="/index.php?document_srl=71">'
              '[BBC] 아스날, 유벤투스와 협상</a>')
    _mock_single_post(search, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter(relevance_terms=["아스날", "아스널", "arsenal"])
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_filter_passes_club_term_in_body_only():
    # 제목엔 구단명 없음 · 언론사 본문에 Arsenal — 대소문자 무시 (_squash)
    art = '<html><body><article><p>Talks with Arsenal continue.</p></article></body></html>'
    _mock_single_post(UNRELATED_SEARCH, UNRELATED_POST, art)
    a = _filter_adapter(relevance_terms=["아스날", "아스널", "arsenal"])
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_filter_passes_player_name_in_title():
    search = ('<a class="hx" href="/index.php?document_srl=71">'
              '[BBC] 디오망데, PSG 와 협상</a>')
    _mock_single_post(search, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter(relevance_terms=["아스날", "아스널", "arsenal"],
                        player_names={"디오망데"})
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_filter_drops_unrelated_and_counts(caplog):
    _mock_single_post(UNRELATED_SEARCH, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter(relevance_terms=["아스날", "아스널", "arsenal"],
                        player_names={"디오망데"})
    with caplog.at_level("INFO"):
        items = asyncio.run(a.fetch())
    assert items == []
    assert a.relevance_dropped == 1
    assert any("무관 글" in r.message for r in caplog.records)

@respx.mock
def test_filter_squash_matching_variant_spacing():
    # 변형 표기 붙여쓰기 ("아스널이") 도 공백 무시 비교로 잡는다
    search = ('<a class="hx" href="/index.php?document_srl=71">'
              '[BBC] 아 스널이 원하는 선수</a>')
    _mock_single_post(search, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter(relevance_terms=["아스널"])
    assert len(asyncio.run(a.fetch())) == 1

# ---- 검색 실패 카운터 (스펙 §6 — 커서 유지 판단 입력) ----

@respx.mock
def test_search_failures_counted_on_429():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(429))
    a = _filter_adapter()
    assert asyncio.run(a.fetch()) == []
    assert a.search_failures == 1

@respx.mock
def test_search_failures_zero_on_success():
    _mock_single_post(UNRELATED_SEARCH, UNRELATED_POST, UNRELATED_ART)
    a = _filter_adapter()
    asyncio.run(a.fetch())
    assert a.search_failures == 0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -q -k "filter or search_failures"`
Expected: FAIL — `TypeError: unexpected keyword argument 'relevance_terms'` 등.

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/fmkorea.py` 수정 3곳.

생성자 시그니처 끝에 인자 2개 추가 + 속성 초기화:

```python
    def __init__(self, source_id: str, search_url: str, search_keywords: list[dict],
                 item_selector: str = "a.hx",
                 base_url: str = "https://www.fmkorea.com",
                 body_selector: str = ".xe_content", max_posts: int = 15,
                 proxy: str | None = None, pages: int = 1,
                 request_gap_sec: float = 0.0,
                 exclude_titles: set[str] | None = None,
                 relevance_terms: list[str] | None = None,
                 player_names: set[str] | None = None):
        ...  # 기존 대입 유지
        self.relevance_terms = relevance_terms or []
        self.player_names = player_names or set()
        self.search_failures = 0      # 이번 fetch 에서 실패한 키워드 검색 수
        self.relevance_dropped = 0    # 무관 글 필터 탈락 수
```

`_relevant` 메서드 추가 (`_process` 위):

```python
    def _relevant(self, title: str, body: str) -> bool:
        """무관 글 필터 (스펙 §3.2) — 구단 키워드 (제목 · 본문) 또는 선수명 (제목) 포함 시 통과.
        인정 집합 미주입이면 필터 없음 — 백필 등 기존 호출부 무영향."""
        if not self.relevance_terms and not self.player_names:
            return True
        t, b = _squash(title), _squash(body)
        if any(_squash(k) in t or _squash(k) in b for k in self.relevance_terms):
            return True
        return any(_squash(n) in t for n in self.player_names)
```

`_discover` 첫 줄에 카운터 리셋, 두 except 분기 (HTTPStatusError · HTTPError) 의 `break` 직전에 `self.search_failures += 1` 추가:

```python
    async def _discover(self, c: httpx.AsyncClient) -> list[tuple[str, str]]:
        self.search_failures = 0
        ...
                except httpx.HTTPStatusError as e:
                    self.search_failures += 1
                    ...  # 기존 로깅 유지
                    break
                except httpx.HTTPError as e:
                    self.search_failures += 1
                    ...  # 기존 로깅 유지
                    break
```

`_process` 의 `body = strip_publish_datetime(body)` 직후 (journalist 추출 앞) 에 판정 삽입:

```python
            body = strip_publish_datetime(body)
            if not self._relevant(title, body):
                self.relevance_dropped += 1
                log.info("fmkorea 무관 글 필터 탈락 — title=%s url=%s", title, url)
                continue
```

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `uv run pytest tests/test_fmkorea_adapter.py -q`
Expected: 전부 PASS (기존 테스트는 필터 미주입이라 무변경 통과).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit  # feat(adapters): fmkorea 무관 글 필터 · 검색 실패 카운터
```

---

### Task 2: config relevance_terms + factory 주입

**Files:**
- Modify: `config/sources.yaml` (fmkorea config 블록)
- Modify: `src/bullet_in/adapters/factory.py`
- Test: `tests/test_adapter_factory.py`

**Interfaces:**
- Consumes: Task 1 의 `FmkoreaAdapter(relevance_terms=..., player_names=...)`.
- Produces: `build_adapters(cfg: dict, fmkorea_player_names: set[str] | None = None) -> list`.
config 키 `relevance_terms` (fmkorea config 블록). Task 3 (run.py) 과 Task 6 (배치) 이 이 키를 읽는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_adapter_factory.py` 에 추가:

```python
def _fmkorea_cfg(extra_config=None):
    return {"sources": [
        {"source_id": "fmkorea", "adapter": "fmkorea", "enabled": True,
         "config": {"search_url": "https://fm.test/s?t={target}&kw={keyword}",
                    "search_keywords": [{"keyword": "아스날", "target": "title"}],
                    **(extra_config or {})}}]}

def test_factory_injects_fmkorea_relevance_filter():
    cfg = _fmkorea_cfg({"relevance_terms": ["아스날", "아스널", "arsenal"]})
    a = build_adapters(cfg, fmkorea_player_names={"디오망데"})[0]
    assert a.relevance_terms == ["아스날", "아스널", "arsenal"]
    assert a.player_names == {"디오망데"}

def test_factory_fmkorea_no_filter_by_default():
    # relevance_terms 없는 config + player_names 미전달 = 필터 없음 (기존 동작)
    a = build_adapters(_fmkorea_cfg())[0]
    assert a.relevance_terms == [] and a.player_names == set()

def test_live_config_has_relevance_terms_triple():
    # 재발 방지 규칙 (트러블슈팅 2026-08-01 §4): 구단명 판정은 3종 동시
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    c = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")["config"]
    assert set(c["relevance_terms"]) == {"아스날", "아스널", "arsenal"}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_adapter_factory.py -q`
Expected: 신규 3건 FAIL.

- [ ] **Step 3: 최소 구현**

`config/sources.yaml` 의 fmkorea `config:` 블록 (max_posts 아래) 에 한 줄:

```yaml
      max_posts: 15
      # 무관 글 필터 인정 구단 키워드 — 변형 표기 3종 동시 (트러블슈팅 2026-08-01 §4)
      relevance_terms: ["아스날", "아스널", "arsenal"]
```

`src/bullet_in/adapters/factory.py`:

```python
def build_adapters(cfg: dict, fmkorea_player_names: set[str] | None = None) -> list:
    ...
        elif kind == "fmkorea":
            out.append(FmkoreaAdapter(
                sid, c["search_url"], c["search_keywords"],
                item_selector=c.get("item_selector", "a.hx"),
                base_url=c.get("base_url", "https://www.fmkorea.com"),
                body_selector=c.get("body_selector", ".xe_content"),
                max_posts=c.get("max_posts", 15),
                proxy=os.environ.get("FMKOREA_PROXY"),
                relevance_terms=c.get("relevance_terms"),
                player_names=fmkorea_player_names))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_adapter_factory.py tests/test_serving_config.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add config/sources.yaml src/bullet_in/adapters/factory.py tests/test_adapter_factory.py
git commit  # feat(config): fmkorea relevance_terms 3종 + factory 필터 주입
```

---

### Task 3: PlayerStore 조회 2종 + run.py 주입

**Files:**
- Modify: `src/bullet_in/storage/players.py`
- Modify: `src/bullet_in/run.py:56` 부근 · `run.py:84-86` · `run.py:111`
- Test: `tests/integration/test_player_store.py`

**Interfaces:**
- Consumes: Task 2 의 `build_adapters(cfg, fmkorea_player_names=...)`.
- Produces: `PlayerStore.confirmed_ko_names() -> set[str]` · `PlayerStore.active_link_players() -> list[tuple[int, str]]` (id 오름차순 · `(id, ko_name)`).
Task 6 (배치) 이 두 메서드를 그대로 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/integration/test_player_store.py` 에 추가 (DB 없으면 기존 관례대로 skip 된다):

```python
def test_confirmed_ko_names_excludes_archived_and_candidate(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    with engine.begin() as c:
        c.execute(text("UPDATE players SET status='archived' WHERE full_name='Leandro Trossard'"))
        c.execute(text(
            "INSERT INTO players (full_name,surname,ko_candidate,category,status,"
            "transfer_status,origin,added_at) VALUES "
            "('New Guy','Guy','뉴가이','external','candidate','in_link','extracted',NOW())"))
    names = store.confirmed_ko_names()
    assert "트로사르" not in names        # archived 제외 (필터 인정 집합은 confirmed 전체)
    assert "뉴가이" not in names          # 후보 미공급
    assert "사카" in names

def test_active_link_players_only_links_ordered_by_id(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    with engine.begin() as c:
        c.execute(text("UPDATE players SET transfer_status='in_link' WHERE full_name='Bukayo Saka'"))
        c.execute(text("UPDATE players SET transfer_status='out_link' WHERE full_name='William Saliba'"))
    rows = store.active_link_players()
    assert [n for _, n in rows] == ["사카", "살리바"]   # seed 순서 = id 순
    assert [pid for pid, _ in rows] == sorted(pid for pid, _ in rows)

def test_active_link_players_excludes_archived_link(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    with engine.begin() as c:
        c.execute(text("UPDATE players SET transfer_status='in_link', status='archived' "
                       "WHERE full_name='Bukayo Saka'"))
    assert store.active_link_players() == []
```

- [ ] **Step 2: 실패 확인**

Run: `docker compose up -d && uv run pytest tests/integration/test_player_store.py -q`
Expected: 신규 3건 FAIL (`AttributeError: confirmed_ko_names`).
DB 를 못 띄우는 환경이면 skip 확인 후 Step 4 에서 CI 대신 로컬 DB 로 검증한다.

- [ ] **Step 3: 최소 구현**

`src/bullet_in/storage/players.py` 에 메서드 2개:

```python
    def confirmed_ko_names(self) -> set[str]:
        """무관 글 필터 인정 집합 (워치리스트 스펙 §3.2) — confirmed 전체 (스쿼드 포함)."""
        with self.engine.connect() as c:
            return {r[0] for r in c.execute(text(
                "SELECT ko_name FROM players WHERE status='confirmed' "
                "AND ko_name IS NOT NULL")).all()}

    def active_link_players(self) -> list[tuple[int, str]]:
        """워치리스트 로테이션 명단 (스펙 §3.1) — 활성 이적축 · id 순."""
        with self.engine.connect() as c:
            return [(r[0], r[1]) for r in c.execute(text(
                "SELECT id, ko_name FROM players WHERE status='confirmed' "
                "AND transfer_status IN ('in_link','out_link') "
                "AND ko_name IS NOT NULL ORDER BY id")).all()]
```

`src/bullet_in/run.py`: 어댑터 빌드 (56행) 앞으로 engine 블록을 이동하고 주입한다.
84–86행의 engine · mart 생성과 111행의 `pstore = PlayerStore(engine)` 는 삭제 (위로 이동했으므로).

```python
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    pstore = PlayerStore(engine)
    # fmkorea 무관 글 필터 인정 집합 주입 (워치리스트 스펙 §3.2) — 배치와 동일 집합
    adapters = build_adapters(cfg, fmkorea_player_names=pstore.confirmed_ko_names())
```

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `uv run pytest -q`
Expected: PASS (통합은 DB 없으면 skip).
run.py 이동 회귀는 `uv run pytest tests/test_dag_import.py -q` 로 임포트 손상 여부까지 확인.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/storage/players.py src/bullet_in/run.py tests/integration/test_player_store.py
git commit  # feat(run): 정기 회차에 fmkorea 무관 글 필터 주입 + PlayerStore 조회 2종
```

---

### Task 4: build_fmkorea_adapter search_keywords 인자

**Files:**
- Modify: `src/bullet_in/collect_fmkorea.py:54-69`
- Test: `tests/test_collect_fmkorea.py`

**Interfaces:**
- Consumes: 기존 `build_fmkorea_adapter(cfg, proxy, *, pages, request_gap_sec, exclude_titles, max_posts)`.
- Produces: 키워드 전용 선택 인자가 추가된 `build_fmkorea_adapter(..., search_keywords: list[dict] | None = None)`.
생략 시 config 값 사용 (기존 동작 동일).
Task 6 (배치) 이 이 인자로 선수명 키워드를 넘긴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_collect_fmkorea.py` 에 추가:

```python
def test_build_fmkorea_adapter_search_keywords_override():
    kws = [{"keyword": "디오망데", "target": "title"}]
    a = build_fmkorea_adapter(_CFG, None, search_keywords=kws, max_posts=5)
    assert a.search_keywords == kws
    assert a.max_posts == 5

def test_build_fmkorea_adapter_search_keywords_default_is_config():
    a = build_fmkorea_adapter(_CFG, None)
    assert a.search_keywords == [{"keyword": "아스날", "target": "title"}]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_collect_fmkorea.py -q`
Expected: override 테스트 FAIL (`TypeError`).

- [ ] **Step 3: 최소 구현**

시그니처에 `search_keywords: list[dict] | None = None` 추가, 본문 한 줄 교체:

```python
def build_fmkorea_adapter(cfg: dict, proxy: str | None, *, pages: int = 1,
                          request_gap_sec: float = 0.0,
                          exclude_titles: set[str] | None = None,
                          max_posts: int | None = None,
                          search_keywords: list[dict] | None = None) -> FmkoreaAdapter:
    ...
    return FmkoreaAdapter(
        "fmkorea", c["search_url"],
        search_keywords if search_keywords is not None else c["search_keywords"],
        ...)  # 나머지 인자 기존 그대로
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_collect_fmkorea.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/collect_fmkorea.py tests/test_collect_fmkorea.py
git commit  # feat(collect): build_fmkorea_adapter 에 search_keywords 선택 인자
```

---

### Task 5: 워치리스트 순수 부품 — 커서 · 슬라이스 · 키워드

**Files:**
- Create: `src/bullet_in/watchlist_fmkorea.py` (순수 함수부만 — main 은 Task 6)
- Test: `tests/test_watchlist_fmkorea.py` (신규)

**Interfaces:**
- Consumes: 없음 (표준 라이브러리만).
- Produces: `CURSOR_PATH: Path` · `GAP_HOURS = 1.0` · `SLICE_SIZE = 10` · `MAX_POSTS = 5`,
`read_cursor(path: Path) -> int | None` · `write_cursor(path: Path, player_id: int) -> None`,
`next_slice(ids: list[int], cursor: int | None, size: int = SLICE_SIZE) -> list[int]`,
`build_keywords(names: list[str]) -> list[dict]`,
`next_cursor(slice_ids: list[int], search_failures: int) -> int | None`.
Task 6 의 main 이 전부 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_watchlist_fmkorea.py` 신규:

```python
from bullet_in.watchlist_fmkorea import (read_cursor, write_cursor, next_slice,
                                         build_keywords, next_cursor)

IDS = [10, 20, 30, 40, 50]

def test_next_slice_from_start_when_no_cursor():
    assert next_slice(IDS, None, size=3) == [10, 20, 30]

def test_next_slice_starts_after_cursor():
    assert next_slice(IDS, 20, size=2) == [30, 40]

def test_next_slice_wraps_around():
    assert next_slice(IDS, 40, size=3) == [50, 10, 20]

def test_next_slice_restarts_when_cursor_is_last():
    assert next_slice(IDS, 50, size=2) == [10, 20]

def test_next_slice_cursor_id_removed_uses_next_id():
    # 커서 25 가 명단에서 사라짐 → 그다음 id (30) 부터 (스펙 §6)
    assert next_slice(IDS, 25, size=2) == [30, 40]

def test_next_slice_small_roster_no_duplicates():
    assert next_slice([10, 20], 10, size=10) == [20, 10]

def test_next_slice_empty_roster():
    assert next_slice([], None) == []

def test_cursor_roundtrip(tmp_path):
    p = tmp_path / "state" / "watchlist_cursor"
    write_cursor(p, 42)                  # 부모 디렉토리 자동 생성
    assert read_cursor(p) == 42

def test_read_cursor_missing_or_corrupt(tmp_path):
    assert read_cursor(tmp_path / "absent") is None
    p = tmp_path / "cursor"
    p.write_text("not-a-number")
    assert read_cursor(p) is None

def test_build_keywords_title_target():
    assert build_keywords(["디오망데", "히메네스"]) == [
        {"keyword": "디오망데", "target": "title"},
        {"keyword": "히메네스", "target": "title"}]

def test_next_cursor_advances_to_slice_end():
    assert next_cursor([30, 40, 50], search_failures=0) == 50

def test_next_cursor_holds_on_search_failure():
    # 검색 실패 시 커서 유지 — 같은 슬라이스 재시도 (스펙 §6)
    assert next_cursor([30, 40, 50], search_failures=1) is None

def test_next_cursor_none_on_empty_slice():
    assert next_cursor([], search_failures=0) is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_watchlist_fmkorea.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: 최소 구현**

`src/bullet_in/watchlist_fmkorea.py` 신설:

```python
"""링크 선수 워치리스트 배치 — 활성 이적축 ko_name 로테이션 검색 (스펙 2026-08-01).

정기 회차와 분리된 전용 배치로, 적재까지만 하고 (Gemini 호출 없음)
번역 · 분류 · 렌더는 다음 정기 회차가 흡수한다.
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from pathlib import Path

import yaml
from sqlalchemy import create_engine

from bullet_in.collect_fmkorea import (STATE_PATH, build_fmkorea_adapter, persist,
                                       read_last_contact, should_supplement,
                                       tunnel_alive, write_last_contact)
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)

CURSOR_PATH = Path.home() / ".bullet-in" / "watchlist_cursor"
GAP_HOURS = 1.0      # 최근 접촉 60분 이내면 스킵 (스펙 §3.1)
SLICE_SIZE = 10      # 배치당 검색 인원 (보수안)
MAX_POSTS = 5        # 배치당 fetch 상한 (보수안)


def read_cursor(path: Path) -> int | None:
    """마지막 검색 선수 id — 없거나 손상이면 None (처음부터 재시작)."""
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def write_cursor(path: Path, player_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(player_id))


def next_slice(ids: list[int], cursor: int | None,
               size: int = SLICE_SIZE) -> list[int]:
    """커서 다음 id 부터 size 명 순환 슬라이스.
    커서 id 가 명단에서 사라졌으면 그다음 id 부터 · 명단이 size 이하면 전원 1회씩."""
    if not ids:
        return []
    start = 0
    if cursor is not None:
        start = next((i for i, pid in enumerate(ids) if pid > cursor), 0)
    return [ids[(start + k) % len(ids)] for k in range(min(size, len(ids)))]


def build_keywords(names: list[str]) -> list[dict]:
    """ko_name → fmkorea 제목 검색 키워드 (스펙 §3.1)."""
    return [{"keyword": n, "target": "title"} for n in names]


def next_cursor(slice_ids: list[int], search_failures: int) -> int | None:
    """전진할 커서 값 — 검색 실패가 있으면 None (같은 슬라이스 재시도 · 스펙 §6)."""
    if not slice_ids or search_failures:
        return None
    return slice_ids[-1]
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_watchlist_fmkorea.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/watchlist_fmkorea.py tests/test_watchlist_fmkorea.py
git commit  # feat(watchlist): 커서 · 슬라이스 · 키워드 순수 부품
```

---

### Task 6: 워치리스트 main + CLI

**Files:**
- Modify: `src/bullet_in/watchlist_fmkorea.py` (main · CLI 추가)
- Test: `tests/test_watchlist_fmkorea.py`

**Interfaces:**
- Consumes: Task 3 `PlayerStore.active_link_players()` · `confirmed_ko_names()`, Task 4 `build_fmkorea_adapter(search_keywords=...)`, Task 1 어댑터 속성 (`relevance_terms` · `player_names` · `search_failures` · `relevance_dropped`), Task 5 순수 부품, collect_fmkorea 의 `persist` · `tunnel_alive` · `should_supplement` · 스탬프 함수 · `STATE_PATH`.
- Produces: `async def main(dry_run: bool = False, force: bool = False) -> None` · `python -m bullet_in.watchlist_fmkorea [--dry-run] [--force]`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_watchlist_fmkorea.py` 에 추가.
main 의 분기 (성공 전진 · 실패 유지 · dry-run 무적재) 를 대역으로 검증한다:

```python
import asyncio
from datetime import datetime, timezone
from bullet_in import watchlist_fmkorea
from bullet_in.models import RawItem


class _FakeAdapter:
    def __init__(self, raw, search_failures=0):
        self._raw = raw
        self.search_failures = search_failures
        self.relevance_dropped = 0
        self.relevance_terms = []
        self.player_names = set()
    async def fetch(self):
        return self._raw

class _FakeMart:
    def __init__(self):
        pass
    def ensure_schema(self):
        pass
    def db_now(self):
        return datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    def source_watermarks(self):
        return {}

class _FakePStore:
    def __init__(self, players):
        self._players = players
    def active_link_players(self):
        return self._players
    def confirmed_ko_names(self):
        return {"디오망데"}


def _run_main(monkeypatch, tmp_path, *, adapter, players, dry_run=False,
              persisted=None):
    monkeypatch.setenv("MARIADB_URL", "fake://")
    monkeypatch.setattr(watchlist_fmkorea, "create_engine", lambda url: None)
    monkeypatch.setattr(watchlist_fmkorea, "MartStore", lambda e: _FakeMart())
    monkeypatch.setattr(watchlist_fmkorea, "PlayerStore", lambda e: _FakePStore(players))
    monkeypatch.setattr(watchlist_fmkorea, "build_fmkorea_adapter",
                        lambda cfg, proxy, **kw: adapter)
    monkeypatch.setattr(watchlist_fmkorea, "persist",
                        lambda raw, mart: (persisted or []).append(raw) or (len(raw), 0, 0))
    monkeypatch.setattr(watchlist_fmkorea, "STATE_PATH", tmp_path / "stamp")
    monkeypatch.setattr(watchlist_fmkorea, "CURSOR_PATH", tmp_path / "cursor")
    monkeypatch.delenv("FMKOREA_PROXY", raising=False)
    asyncio.run(watchlist_fmkorea.main(dry_run=dry_run, force=True))


_RAW = [RawItem(source_id="fmkorea", source_type="html", url="https://fm.test/1",
                fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                raw_payload={"title": "[BBC] 디오망데", "body": "b", "body_level": 1})]
_PLAYERS = [(10, "디오망데"), (20, "히메네스")]


def test_main_advances_cursor_on_success(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path, adapter=_FakeAdapter(_RAW), players=_PLAYERS)
    assert watchlist_fmkorea.read_cursor(tmp_path / "cursor") == 20
    assert (tmp_path / "stamp").exists()          # 접촉 스탬프 공유 기록

def test_main_holds_cursor_on_search_failure(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path,
              adapter=_FakeAdapter(_RAW, search_failures=1), players=_PLAYERS)
    assert watchlist_fmkorea.read_cursor(tmp_path / "cursor") is None

def test_main_dry_run_no_persist_no_cursor(monkeypatch, tmp_path):
    persisted = []
    _run_main(monkeypatch, tmp_path, adapter=_FakeAdapter(_RAW), players=_PLAYERS,
              dry_run=True, persisted=persisted)
    assert persisted == []                        # 적재 없음
    assert watchlist_fmkorea.read_cursor(tmp_path / "cursor") is None
    assert (tmp_path / "stamp").exists()          # 실접촉이므로 스탬프는 기록

def test_main_zero_active_links_exits_clean(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path, adapter=_FakeAdapter([]), players=[])
    assert not (tmp_path / "stamp").exists()      # 검색 0회 — 접촉 없음

def test_watchlist_guard_uses_60min_gap():
    # 가드 60분 (스펙 §3.1) — collect 의 should_supplement 를 GAP_HOURS 로 재사용
    from bullet_in.collect_fmkorea import should_supplement
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    from datetime import timedelta
    assert should_supplement(now - timedelta(minutes=30), now,
                             gap_hours=watchlist_fmkorea.GAP_HOURS) is False
    assert should_supplement(now - timedelta(minutes=61), now,
                             gap_hours=watchlist_fmkorea.GAP_HOURS) is True
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_watchlist_fmkorea.py -q`
Expected: 신규 main 테스트 FAIL (`AttributeError: main`).

- [ ] **Step 3: 최소 구현**

`watchlist_fmkorea.py` 에 main · CLI 추가:

```python
async def main(dry_run: bool = False, force: bool = False) -> None:
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    src = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")
    if not src.get("enabled", True):
        log.info("fmkorea 비활성 (enabled: false) — 워치리스트 배치 스킵")
        return
    proxy = os.environ.get("FMKOREA_PROXY")
    if proxy and not tunnel_alive(proxy):
        log.info("fmkorea 터널 미접속 — 워치리스트 배치 스킵 (커서 무전진 · 스탬프 무기록)")
        return

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    pstore = PlayerStore(engine)

    now = mart.db_now()
    marks = [t for t in (read_last_contact(STATE_PATH),
                         mart.source_watermarks().get("fmkorea")) if t]
    last = max(marks) if marks else None
    if not force and not should_supplement(last, now, gap_hours=GAP_HOURS):
        log.info("워치리스트 배치 스킵 — 마지막 fmkorea 접촉 %s (60분 이내)", last)
        return

    players = pstore.active_link_players()
    if not players:
        log.info("활성 링크 선수 0명 — 검색 없이 정상 종료 (시장 폐장 휴면)")
        return
    ids = [pid for pid, _ in players]
    names = dict(players)
    slice_ids = next_slice(ids, read_cursor(CURSOR_PATH))
    kws = build_keywords([names[pid] for pid in slice_ids])

    adapter = build_fmkorea_adapter(cfg, proxy, search_keywords=kws,
                                    max_posts=MAX_POSTS)
    # 무관 글 필터 주입 — 정기 회차 (run.py) 와 같은 인정 집합 (스펙 §3.2).
    # build_fmkorea_adapter 는 변경 범위가 인자 1개로 묶여 있어 (스펙 §3.4)
    # 생성 후 공개 속성에 대입한다.
    adapter.relevance_terms = src["config"].get("relevance_terms") or []
    adapter.player_names = pstore.confirmed_ko_names()

    raw = await adapter.fetch()
    write_last_contact(STATE_PATH, now)   # 신규 0건 · 전량 탈락도 접촉은 기록 (스펙 §6)

    if dry_run:
        log.info("[dry-run] 검색 %d명 · 필터 통과 %d · 탈락 %d · 검색 실패 %d — 적재 없음",
                 len(slice_ids), len(raw), adapter.relevance_dropped,
                 adapter.search_failures)
        for it in raw:
            log.info("[dry-run] 통과: %s", it.raw_payload.get("title"))
        return

    n = dup = blocked = 0
    if raw:
        n, dup, blocked = persist(raw, mart)
    cur = next_cursor(slice_ids, adapter.search_failures)
    if cur is not None:
        write_cursor(CURSOR_PATH, cur)
    log.info("워치리스트 배치 완료 — 검색 %d명 · 적재 %d · 동일 내용 생략 %d · "
             "기존 기사 유지 %d · 필터 탈락 %d · 검색 실패 %d · 커서 %s",
             len(slice_ids), n, dup, blocked, adapter.relevance_dropped,
             adapter.search_failures, cur if cur is not None else "유지")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="적재 없이 검색 · 필터 결과만 출력 (커서 무전진)")
    ap.add_argument("--force", action="store_true", help="최근 접촉 가드 무시")
    a = ap.parse_args()
    asyncio.run(main(dry_run=a.dry_run, force=a.force))
```

DB · Mongo 접속 실패는 잡지 않는다 — 예외 전파로 비정상 종료하면 systemd `OnFailure` 가 알림을 쏜다 (스펙 §6).

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `uv run pytest -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/watchlist_fmkorea.py tests/test_watchlist_fmkorea.py
git commit  # feat(watchlist): 배치 진입점 main · CLI (가드 · 필터 주입 · 커서 전진 규칙)
```

---

### Task 7: systemd 유닛 (타이머 · 서비스)

**Files:**
- Create: `infra/systemd/bullet-in-watchlist.timer`
- Create: `infra/systemd/bullet-in-watchlist.service`

**Interfaces:**
- Consumes: Task 6 의 `python -m bullet_in.watchlist_fmkorea` · 기존 `bullet-in-fail-notify.service`.
- Produces: VM 반영 시 `systemctl enable --now bullet-in-watchlist.timer` 로 켜는 유닛 2개.

- [ ] **Step 1: 유닛 파일 작성**

시각 산출: 정기 회차는 UTC 00/3:00 (KST 정시 3시간 간격).
+90분 오프셋 · 6시간 간격 4회 = UTC 04:30 · 10:30 · 16:30 · 22:30 = KST 13:30 · 19:30 · 01:30 · 07:30 (스펙 §3.5 일치).

`infra/systemd/bullet-in-watchlist.timer`:

```ini
[Unit]
Description=bullet-in watchlist batch 4x daily (regular +90min, KST 01:30/07:30/13:30/19:30)

[Timer]
OnCalendar=*-*-* 04/6:30:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

`infra/systemd/bullet-in-watchlist.service`:

```ini
[Unit]
Description=bullet-in watchlist batch (linked-player rotation search -> raw/mart)
Wants=docker.service network-online.target
After=docker.service network-online.target
OnFailure=bullet-in-fail-notify.service

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/bullet-in
EnvironmentFile=/home/ubuntu/bullet-in/.env
ExecStartPre=/usr/bin/docker compose up -d --wait
ExecStartPre=/bin/sleep 10
ExecStart=/home/ubuntu/.local/bin/uv run python -m bullet_in.watchlist_fmkorea
TimeoutStartSec=600
```

- [ ] **Step 2: 기존 유닛과 대조 검증**

Run: `diff <(grep -v "^Desc\|^Exec\|^OnCal\|^Timeout" infra/systemd/bullet-in.service) <(grep -v "^Desc\|^Exec\|^OnCal\|^Timeout" infra/systemd/bullet-in-watchlist.service)`
Expected: 차이 없음 (구조 동일 — Description · ExecStart · 시각 · 타임아웃만 다름).

- [ ] **Step 3: 커밋**

```bash
git add infra/systemd/bullet-in-watchlist.timer infra/systemd/bullet-in-watchlist.service
git commit  # feat(infra): 워치리스트 배치 systemd 타이머 (KST 01:30/07:30/13:30/19:30)
```

---

### Task 8: 운영 런북 신설

**Files:**
- Create: `docs/runbook/2026-08-01-watchlist-batch-ops.md`

**Interfaces:**
- Consumes: Task 6 의 CLI · 로그 문구 · 커서 경로, Task 7 의 유닛 이름.
- Produces: 배치 관측 · 커서 리셋 · 증량 절차 런북 (스펙 §8).

- [ ] **Step 1: 런북 작성**

§2.2 서식으로 작성한다 (PostToolUse 훅이 자동 검사).
필수 섹션과 담을 내용:

1. **개요** — 배치의 역할 (활성 이적축 로테이션 검색 · 적재만) · 스펙 참조.
2. **VM 최초 반영 절차** — `git pull` → `sudo cp infra/systemd/bullet-in-watchlist.* /etc/systemd/system/` → `sudo systemctl daemon-reload` → `sudo systemctl enable --now bullet-in-watchlist.timer` → `systemctl list-timers bullet-in-watchlist.timer` 확인.
3. **배치 관측** — `journalctl -u bullet-in-watchlist -n 50` 로 완료 로그 한 줄 해석 (검색 N 명 · 적재 · 동일 내용 생략 · 기존 기사 유지 · 필터 탈락 · 검색 실패 · 커서).
스킵 사유 3종 (터널 미접속 · 60분 가드 · 활성 링크 0명) 의 로그 문구.
Task 6 Step 3 의 실제 로그 문구를 그대로 옮긴다 (스니펫 드리프트 방지 — 문구는 코드가 SoT).
4. **관찰 3종** (스펙 §8) — ① 배치 430 비율 (`journalctl -u bullet-in-watchlist | grep 429`) ② 무관 글 비중 (필터 탈락 로그 집계) ③ 일순 주기 (커서 값이 최소 id 로 돌아오는 간격) — 각각 확인 명령 포함.
5. **커서 리셋** — 경로 `~/.bullet-in/watchlist_cursor`.
전체 재시작은 `rm`, 특정 지점부터는 `echo <player_id> >` 기록.
필요 시점: 명단 대개편 직후 · 슬라이스 반복 이상 관찰 시.
6. **증량 절차 (4회 → 8회)** — 관찰 3종 통과 + 사용자 결정 후: 타이머 `OnCalendar` 를 `*-*-* 01/3:30:00 UTC` 로 수정 (정기 회차 +90분 · 3시간 간격 8회) → repo 커밋 → VM `cp` · `daemon-reload` · `restart`.
7. **수동 실행 · dry-run** — `uv run python -m bullet_in.watchlist_fmkorea --dry-run --force 2>&1 | tee /tmp/watchlist-dryrun.log`.
접촉 규율 3줄 (직전 회차 200 확인 · tee 필수 · 재실행 금지) 포함.

- [ ] **Step 2: 서식 · 문체 점검**

훅 통과 확인 (저장 시 자동).
게시 전 humanize-korean (fast) 문체 점검 1회 — 명사형 불릿 · 수치 · 경로 · 코드 블록은 변경 금지 목록으로 명시.

- [ ] **Step 3: 커밋**

```bash
git add docs/runbook/2026-08-01-watchlist-batch-ops.md
git commit  # docs(runbook): 워치리스트 배치 관측 · 커서 리셋 · 증량 절차
```

---

### Task 9: 머지 전 라이브 검증 (컨트롤러 직접 수행)

**Files:** 없음 (검증만 — 산출 로그는 스크래치패드 tee 파일).

셀렉터 드리프트 함정 (모킹은 실검색을 못 잡음 · 스펙 §7) 때문에 머지 전에 라이브로 1회 확인한다.
접촉 규율: **직전 회차 200 확인 → tee 필수 → 출력 확인 목적 재실행 절대 금지**.
실행 경로 (프록시 · env) 는 `docs/runbook/2026-07-31-fmkorea-manual-url-backfill.md` 의 수동 회수와 동일하게 맞춘다.

- [ ] **Step 1: 직전 회차 접촉 상태 확인**

VM 에서 `journalctl -u bullet-in -n 200 | grep -i "fmkorea"` — 직전 정기 회차의 fmkorea 검색이 정상 (429 · 430 경고 없음 · 후보 계수 > 0) 인지 확인.
비정상이면 라이브 검증을 미루고 사용자에게 보고.

- [ ] **Step 2: 선수명 title 검색 1회 실측 (검색 요청 1건)**

활성 링크 선수 1명의 ko_name 으로 `discover()` 만 (본문 fetch 없음):

```bash
set -a; source .env; set +a
uv run python - <<'EOF' 2>&1 | tee "$SCRATCH/watchlist-live-discover.log"
import asyncio, os, yaml
from pathlib import Path
from bullet_in.collect_fmkorea import build_fmkorea_adapter
cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
a = build_fmkorea_adapter(cfg, os.environ.get("FMKOREA_PROXY"),
                          search_keywords=[{"keyword": "<활성 링크 ko_name 1명>",
                                            "target": "title"}])
print(asyncio.run(a.discover()))
EOF
```

확인 (tee 파일로만): 한글 키워드 URL 인코딩 정상 · 파싱 결과가 (제목, 글 URL) 튜플 목록 (0건이어도 예외 없이 반환이면 정상).

- [ ] **Step 3: dry-run 전체 배치 (검색 10 + fetch 최대 5)**

Step 2 에서 60분 이상 지난 깨끗한 창 (다음 정기 회차와 60분 이격) 에서:

```bash
uv run python -m bullet_in.watchlist_fmkorea --dry-run --force 2>&1 | tee "$SCRATCH/watchlist-dryrun.log"
```

확인 (tee 파일로만): 통과 표본이 실제 아스날 관련 · 링크 선수 글인지, 탈락 로그 표본이 실제 무관 글인지 눈검증.
검색 실패 카운트 0 인지 확인.

- [ ] **Step 4: 결과 기록**

통과 · 탈락 표본과 판정을 PR 본문 검증 섹션에 옮긴다 (수치는 근사치로 충분 — 재실행 금지).

---

### Task 10: PR 생성 (머지는 사용자 직접)

- [ ] **Step 1: 전체 테스트 + 최종 리뷰**

Run: `uv run pytest -q`
Expected: 전부 PASS.
superpowers:requesting-code-review 로 스펙 대비 최종 점검.

- [ ] **Step 2: push + PR**

PR 본문: 7섹션 한국어 · `--body-file` · Claude 서명 금지 · 라이브 검증 결과 (Task 9) 포함.
게시 전 humanize-korean (fast) 문체 점검 1회 (서식 §2.2 · 명사형 불릿 · 수치 · 경로 변경 금지 명시).

- [ ] **Step 3: 머지 후 절차 안내 (사용자 머지 대기)**

머지는 사용자 직접.
머지 후 한 묶음 (런북 §2): VM `git pull` → 유닛 `cp` · `daemon-reload` · `enable --now` → 첫 배치 journalctl 확인 (검색 10 · 적재 수 · 커서 전진) → 다음 정기 회차에서 번역 흡수 · 라벨 확인.
이후 관찰 3종 (런북 §4) → 8회 증량 판단은 사용자 결정.

---

## Self-Review 결과

- 스펙 §3.1 (배치 구성 전부) → Task 5 · 6. §3.2 (필터 · 양쪽 주입) → Task 1 · 2 · 3 · 6. §3.3 (config) → Task 2. §3.4 (factory 인자 1개) → Task 4. §3.5 (타이머) → Task 7. §6 (에러 경로: 터널 · 430 커서 유지 · 0명 · DB 실패 · 커서 손상) → Task 5 · 6 테스트. §7 (TDD 목록 + 라이브 검증) → 각 Task Step 1 + Task 9. §8 (런북 · 관찰) → Task 8 · 10.
- 스펙 §7 테스트 목록 대조: 커서 4종 (슬라이스 · 순환 · id 소실 · 파일 부재) ✓ · 키워드 생성 ✓ · 필터 (통과 3경로 · 탈락 · 미주입 회귀) ✓ · 가드 60분 ✓ · factory 인자 생략 시 기존 동작 ✓ · 검색 실패 시 커서 유지 ✓.
- 타입 · 이름 일관성: `relevance_terms` (list) · `player_names` (set) · `search_failures` (int) 를 Task 1 정의 → Task 2 · 6 소비로 통일.
`active_link_players` 는 `(id, ko_name)` 튜플 목록으로 Task 3 정의 → Task 6 `dict(players)` 소비 일치.
