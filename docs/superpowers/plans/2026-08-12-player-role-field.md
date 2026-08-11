# 선수 귀속 역할 필드 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 선수 페이지가 보여줄 기사를 `article_players.stage` 가 아니라 새 필드 `article_players.role` 로 고르게 한다.

**Architecture:** 저장 계층에 역할 컬럼과 어휘 상수를 두고 (`storage/players.py` 가 그 표의 소유자), 추출 결과를 받는 경로 (`roster.normalize_pairs` → `PlayerStore.link_article`) 가 값을 실어 나르며, 서빙 (`serve/render.build_player_entries`) 이 목록 선별 조건으로 쓴다.
값을 만드는 프롬프트 문안은 이 작업 범위 밖이라 (병렬 세션 소유) 배포 시점에는 전 행이 미기입이고, 미기입은 주역으로 읽어 현행 화면을 그대로 유지한다.

**Tech Stack:** Python 3.11 · SQLAlchemy Core (`text()` 원시 SQL) · MariaDB · pytest · Jinja2.

## Global Constraints

- 스펙 정본은 `docs/superpowers/specs/2026-08-12-player-role-field-design.md` 다.
아래에서 "스펙 §N" 은 이 문서를 가리킨다.
- 역할 값은 `subject` · `mention` 두 가지다 (스펙 §3.1).
- 미기입 (NULL) 과 어휘 밖 값은 **주역**으로 읽는다 (스펙 §3.2).
- 목록 필터는 `role != mention` 으로 **대체**한다 — `stage != other` 를 함께 걸지 않는다 (스펙 §3.3).
- **`src/bullet_in/enrich.py` 를 수정하지 않는다.** 추출 프롬프트 문안은 병렬 세션 소유다 (스펙 §5).
- **`players` 테이블을 쓰지 않는다** (읽기만).
- 커밋 규약은 `docs/conventions/2026-06-11-commit-pr-convention.md` 를 따른다.
제목은 `<type>(<scope>): 한국어 제목`, 본문은 도입 1~2문장 + 명사형 불릿, 마지막에 `Refs:` 와 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- 작업 위치는 worktree `.claude/worktrees/feat-player-role-field` (브랜치 `feat/player-role-field`) 다.
모든 명령은 이 디렉터리에서 실행한다.
- 테스트 실행은 `uv run pytest` 다.
통합 테스트 (`tests/integration/`) 는 로컬 MariaDB 가 떠 있어야 돈다 (`docker compose up -d`).

## File Structure

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `src/bullet_in/storage/schema.sql` | 스키마 정본 | `article_players.role` 컬럼 추가 |
| `src/bullet_in/storage/players.py` | `players` · `article_players` 저장소 · **역할 어휘의 단일 출처** | 상수 3개 추가 · `link_article` 인자 추가 · `page_player_links` SELECT 확장 |
| `src/bullet_in/roster.py` | 추출 쌍 → 저장 반영 | `normalize_role()` 추가 · `normalize_pairs` 가 역할 실음 · `link_article` 호출에 역할 전달 |
| `src/bullet_in/serve/render.py` | 서빙 렌더 | `load_page_players` 가 역할 실음 · `build_player_entries` 필터 교체 |
| `tests/test_roster.py` | 추출 쌍 정규화 단위 테스트 | 역할 정규화 테스트 1건 추가 |
| `tests/integration/test_player_store.py` | 저장소 통합 테스트 | 역할 저장 · 조회 테스트 2건 추가 |
| `tests/test_serve_players.py` | 선수 페이지 단위 테스트 | 3건 갱신 · 3건 추가 |

역할 어휘를 `storage/players.py` 에 두는 이유는 그 모듈이 `article_players` 표의 소유자이고, 쓰는 쪽 (`roster`) 과 읽는 쪽 (`serve/render`) 이 모두 이미 그 모듈을 참조하기 때문이다.
`transfer_stage.py` 에 두지 않는다 — 그 모듈은 이적 단계 어휘의 단일 출처이고, 병렬 세션이 단계를 손대면 충돌 지점이 된다.

---

### Task 1: 역할 어휘와 정규화

추출이 낸 역할 문자열을 검증해 저장 가능한 값으로 바꾼다.
DB 없이 도는 단위 테스트만 있다.

**Files:**
- Modify: `src/bullet_in/storage/players.py` (상수 블록 · `_PAGE_WHERE` 아래)
- Modify: `src/bullet_in/roster.py` (import · `normalize_role` 신설 · `normalize_pairs` 반환값)
- Test: `tests/test_roster.py`

**Interfaces:**
- Produces: `bullet_in.storage.players.SUBJECT` (= `"subject"`) · `MENTION` (= `"mention"`) · `ROLES` (`frozenset[str]`)
- Produces: `bullet_in.roster.normalize_role(raw) -> str | None` — 어휘 밖 · 비문자열은 `None`
- Produces: `normalize_pairs()` 반환 항목에 `"role"` 키가 생긴다 (`{"full_name", "ko", "stage", "role"}`)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_roster.py` 맨 아래에 붙인다.

```python
def test_normalize_pairs_normalizes_role_and_drops_unknown():
    # 어휘 밖 · 미기입은 None — 서빙이 주역으로 읽어 화면을 지우지 않는다 (스펙 §3.2)
    raw = [{"full_name": "Christos Tzolis", "ko": "촐리스", "stage": "interest",
            "role": " Subject "},
           {"full_name": "Morgan Rogers", "ko": "로저스", "stage": "other",
            "role": "mention"},
           {"full_name": "Ben White", "ko": "화이트", "stage": "other",
            "role": "배경"},
           {"full_name": "Bukayo Saka", "ko": "사카", "stage": "other"}]
    assert [p["role"] for p in normalize_pairs(raw)] == [
        "subject", "mention", None, None]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_roster.py::test_normalize_pairs_normalizes_role_and_drops_unknown -v`
Expected: FAIL — `KeyError: 'role'`

- [ ] **Step 3: 어휘 상수를 넣는다**

`src/bullet_in/storage/players.py` 의 `_PAGE_WHERE` 정의 바로 아래에 붙인다.

```python
# 귀속 역할 어휘 (역할 필드 스펙 2026-08-12 §3.1) — article_players.role 의 단일 출처.
# "이 기사의 주인공인가" 를 묻는 축이고, stage 는 "어느 단계인가" 만 맡는다.
# 두 질문을 stage 하나로 답하던 동안 화면 귀속 807건 중 331건이 남의 기사였다.
SUBJECT = "subject"
MENTION = "mention"
ROLES = frozenset({SUBJECT, MENTION})
```

- [ ] **Step 4: 정규화 함수를 넣는다**

`src/bullet_in/roster.py` 의 import 를 고친다.

```python
from bullet_in.storage.players import PlayerStore, ROLES
```

`_HANGUL_RE` 정의 아래, `normalize_pairs` 위에 함수를 넣는다.

```python
def normalize_role(raw) -> str | None:
    """추출이 낸 역할 값 정규화 — 어휘 밖은 미기입 (None) 으로 떨어뜨린다.

    미기입은 서빙에서 주역으로 읽히므로 (스펙 §3.2), 모델이 값을 빠뜨리거나
    모르는 낱말을 내도 기사가 화면에서 사라지지 않는 쪽으로 넘어진다."""
    if not isinstance(raw, str):
        return None
    v = raw.strip().lower()
    return v if v in ROLES else None
```

`normalize_pairs` 의 마지막 append 를 고친다.

```python
        out.append({"full_name": fn, "ko": ko, "stage": stage,
                    "role": normalize_role(item.get("role"))})
```

- [ ] **Step 5: 통과를 확인한다**

Run: `uv run pytest tests/test_roster.py -v`
Expected: PASS (기존 테스트 포함 전부)

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/storage/players.py src/bullet_in/roster.py tests/test_roster.py
git commit -F - <<'EOF'
feat(roster): 추출 쌍에 귀속 역할 값 정규화 추가

선수 페이지가 보여줄 기사를 단계가 아니라 역할로 고르기 위한 첫 조각이다.
값을 만드는 프롬프트 문안은 이 변경 범위 밖이라 저장 경로만 먼저 연다.

- 역할 어휘 상수 신설: article_players 표를 소유한 저장소 모듈에 두어 쓰는 쪽과
  읽는 쪽이 같은 값을 참조
- 어휘 밖 · 비문자열 · 미기입은 전부 미기입으로 떨어뜨림 — 서빙이 주역으로
  읽으므로 모델이 값을 빠뜨려도 기사가 화면에서 사라지지 않음

Refs: docs/superpowers/specs/2026-08-12-player-role-field-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: 스키마 · 저장 · 조회

컬럼을 만들고, 저장 경로가 값을 쓰고, 서빙 조회가 값을 돌려주게 한다.

**Files:**
- Modify: `src/bullet_in/storage/schema.sql:63-68` (article_players 블록 다음 줄)
- Modify: `src/bullet_in/storage/players.py:80-88` (`link_article`) · `:172-178` (`page_player_links`)
- Modify: `src/bullet_in/roster.py:91` (`link_article` 호출)
- Test: `tests/integration/test_player_store.py`

**Interfaces:**
- Consumes: Task 1 의 `normalize_pairs()` 반환 항목의 `"role"` 키
- Produces: `PlayerStore.link_article(content_hash: str, player_id: int, stage: str | None, role: str | None = None) -> None`
- Produces: `PlayerStore.page_player_links()` 항목이 `{"player_id", "content_hash", "stage", "role"}` 를 갖는다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/integration/test_player_store.py` 의 `test_page_player_links_shares_the_same_predicate` 바로 아래에 붙인다.
`_add_player` 는 같은 파일에 이미 있는 헬퍼다.

```python
def test_link_article_stores_role_and_page_links_return_it(engine):
    store = PlayerStore(engine)
    keep = _add_player(engine, full_name="Role Target", surname="RoleTarget",
                       ko_name="역할대상", category="external", status="confirmed",
                       transfer_status="in_link")
    h = "d" * 64
    store.link_article(h, keep, "other", "mention")
    store.link_article(h, keep, "interest", "subject")   # 재추출 — 역할도 갱신된다
    with engine.connect() as c:
        assert c.execute(text(
            "SELECT stage, role FROM article_players WHERE content_hash=:h"),
            {"h": h}).all() == [("interest", "subject")]
    assert [l["role"] for l in store.page_player_links()
            if l["content_hash"] == h] == ["subject"]


def test_link_article_leaves_role_null_when_not_given(engine):
    # 기존 호출자 (백필 · 재추출 모듈) 는 역할을 넘기지 않는다 — 미기입으로 남아야 한다
    store = PlayerStore(engine)
    keep = _add_player(engine, full_name="No Role", surname="NoRole",
                       ko_name="역할없음", category="external", status="confirmed",
                       transfer_status="in_link")
    store.link_article("e" * 64, keep, "interest")
    with engine.connect() as c:
        assert c.execute(text(
            "SELECT role FROM article_players WHERE content_hash=:h"),
            {"h": "e" * 64}).scalar_one() is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/integration/test_player_store.py -k role -v`
Expected: FAIL — `link_article() takes 4 positional arguments but 5 were given`

DB 가 없어 skip 되면 `docker compose up -d` 를 먼저 실행한다.

- [ ] **Step 3: 컬럼을 추가한다**

`src/bullet_in/storage/schema.sql` 의 `article_players` 블록이 끝나는 줄 (`PRIMARY KEY (content_hash, player_id));`) 바로 다음에 붙인다.

```sql
ALTER TABLE article_players ADD COLUMN IF NOT EXISTS role VARCHAR(16);
```

- [ ] **Step 4: 저장 · 조회를 고친다**

`src/bullet_in/storage/players.py` 의 `link_article` 을 통째로 바꾼다.

```python
    def link_article(self, content_hash: str, player_id: int,
                     stage: str | None, role: str | None = None) -> None:
        """추출 쌍 저장 — 재추출 시 단계 · 역할 · 시각만 갱신하는 멱등 upsert.
        역할을 넘기지 않는 호출자 (백필 · 재추출 모듈) 는 미기입으로 남긴다."""
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO article_players "
                "(content_hash,player_id,stage,role,extracted_at) "
                "VALUES (:h,:p,:s,:r,:now) ON DUPLICATE KEY UPDATE "
                "stage=VALUES(stage), role=VALUES(role), "
                "extracted_at=VALUES(extracted_at)"),
                {"h": content_hash, "p": player_id, "s": stage, "r": role,
                 "now": _utcnow()})
```

같은 파일의 `page_player_links` 안 SELECT 문자열을 바꾼다.

```python
                "SELECT ap.player_id, ap.content_hash, ap.stage, ap.role "
```

`src/bullet_in/roster.py` 의 `record_article_players` 안 호출을 바꾼다.

```python
        store.link_article(content_hash, pid, p["stage"], p.get("role"))
```

- [ ] **Step 5: 통과를 확인한다**

Run: `uv run pytest tests/integration/test_player_store.py -v`
Expected: PASS (기존 테스트 포함 전부 — `link_article` 의 역할 인자는 기본값이 있어 옛 호출이 그대로 돈다)

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/storage/schema.sql src/bullet_in/storage/players.py \
        src/bullet_in/roster.py tests/integration/test_player_store.py
git commit -F - <<'EOF'
feat(storage): 귀속 역할 컬럼 신설 · 저장 · 조회 경로 배선

역할 값을 담을 자리를 만들고 저장 경로와 서빙 조회를 잇는다. 스키마는 정기 회차의
멱등 적용 경로를 그대로 타므로 수동 반영이 필요 없다.

- article_players 에 role 컬럼 추가 (기존 컬럼 추가와 같은 ALTER ... IF NOT EXISTS)
- 저장은 멱등 upsert 에 역할을 포함 — 재추출 시 단계와 함께 갱신
- 역할 인자에 기본값을 두어 값을 넘기지 않는 백필 · 재추출 모듈은 그대로 동작
- 선수 페이지 조회가 역할을 함께 반환

Refs: docs/superpowers/specs/2026-08-12-player-role-field-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: 서빙 필터 교체

선수 페이지의 기사 선별 조건을 단계에서 역할로 바꾼다.
화면 동작이 바뀌는 유일한 작업이다.

**Files:**
- Modify: `src/bullet_in/serve/render.py:14` (import) · `:995-999` (`load_page_players`) · `:1004-1023` (`build_player_entries` 의 docstring · `paired` 조건)
- Test: `tests/test_serve_players.py`

**Interfaces:**
- Consumes: Task 2 의 `page_player_links()` 항목의 `"role"` 키 · `bullet_in.storage.players.MENTION`
- Produces: `build_player_entries()` 의 선별 기준이 `role != MENTION` 이 된다 (반환 구조는 그대로)

- [ ] **Step 1: 기존 테스트 3건을 새 전제로 고친다**

`tests/test_serve_players.py` 에서 아래 셋을 바꾼다.
셋 다 "단계가 `other` 면 빠진다" 를 전제로 쓰여 있어 그대로 두면 새 규칙과 모순된다.

첫째, `test_build_player_entries_header_count_matches_article_list` 의 `links` 목록에서 `h3` 항목에 역할을 붙인다.

```python
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": None},
                        {"content_hash": "h3", "stage": "other",
                         "role": "mention"}])]
```

둘째, `test_build_player_entries_excludes_other_from_list_and_count` 를 이름과 내용 모두 바꾼다.

```python
def test_build_player_entries_excludes_mention_from_list_and_count():
    # 머리 건수와 목록 수가 어긋나면 안 되므로 둘 다 같은 집합에서 나와야 한다.
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)},
            {"content_hash": "h2", "published_at": datetime(2026, 8, 2)},
            {"content_hash": "h3", "published_at": datetime(2026, 8, 3)}]
    players = [{"id": 1, "full_name": "Christos Tzolis", "surname": "Tzolis",
                "ko_full_name": None, "ko_name": "촐리스",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest",
                           "role": "subject"},
                          {"content_hash": "h2", "stage": "agreed",
                           "role": "mention"},
                          {"content_hash": "h3", "stage": "agreed",
                           "role": "subject"}]}]
    entry = build_player_entries(rows, players)[0]
    assert entry["count"] == 2
    assert len(entry["articles"]) == 2
    assert [a["content_hash"] for a in entry["articles"]] == ["h3", "h1"]
```

셋째, `test_build_player_entries_drops_player_whose_articles_are_all_other` 를 바꾼다.

```python
def test_build_player_entries_drops_player_whose_links_are_all_mention():
    # 남의 기사에 이름만 스친 선수 — 색인이 부풀지 않게 페이지를 만들지 않는다.
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)},
            {"content_hash": "h2", "published_at": datetime(2026, 8, 2)}]
    players = [{"id": 1, "full_name": "Martin Zubimendi", "surname": "Zubimendi",
                "ko_full_name": None, "ko_name": "수비멘디",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "agreed",
                           "role": "mention"},
                          {"content_hash": "h2", "stage": "done",
                           "role": "mention"}]}]
    assert build_player_entries(rows, players) == []
```

- [ ] **Step 2: 새 테스트 3건을 쓴다**

`tests/test_serve_players.py` 의 `test_build_player_entries_excludes_mention_from_list_and_count` 바로 아래에 붙인다.
`_art` · `_player` 는 같은 파일에 이미 있는 헬퍼다.

```python
def test_build_player_entries_keeps_links_with_no_role():
    # 역할이 채워지기 전 · 모델이 빠뜨렸을 때 지금 화면이 유지되는지 (스펙 §3.2)
    arts = [_art("h1", 1, "interest"), _art("h2", 2, "other")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "interest"},
                        {"content_hash": "h2", "stage": "other"}])]
    [e] = build_player_entries(arts, players)
    assert e["count"] == 2


def test_build_player_entries_keeps_subject_other_without_ladder_row():
    # 경쟁 구단 접근 · 잔류 협상 — 주역인데 아스날 축에 담을 단계가 없는 기사 (스펙 §2.3)
    arts = [_art("h1", 1, "interest"), _art("h2", 2, "other")]
    players = [_player(1, "Kepa", "케파", "out_link",
                       [{"content_hash": "h1", "stage": "interest",
                         "role": "subject"},
                        {"content_hash": "h2", "stage": "other",
                         "role": "subject"}])]
    [e] = build_player_entries(arts, players)
    assert [a["content_hash"] for a in e["articles"]] == ["h2", "h1"]
    assert [l["stage"] for l in e["ladder"]] == ["interest"]   # other 는 줄이 없다
    assert e["stage"] == "interest"                            # 현재 상태도 안 바뀐다


def test_player_chips_skip_mention_links():
    # 기사 카드의 선수 칩도 같은 목록에서 나오므로 잡음 칩이 함께 사라진다 (스펙 §4)
    arts = [_art("h1", 1, "agreed")]
    players = [_player(1, "Rogers", "로저스", "other_club",
                       [{"content_hash": "h1", "stage": "agreed",
                         "role": "mention"}]),
               _player(2, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed",
                         "role": "subject"}])]
    chips = player_chips(build_player_entries(arts, players))
    assert [c["name"] for c in chips["h1"]] == ["촐리스"]
```

- [ ] **Step 3: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -v`
Expected: FAIL — 새 테스트 3건과 갱신한 3건이 떨어진다 (아직 필터가 단계 기준이다)

- [ ] **Step 4: 필터를 바꾼다**

`src/bullet_in/serve/render.py` 의 import 블록에 한 줄을 더한다 (`from bullet_in.enrich import ...` 아래).

```python
from bullet_in.storage.players import MENTION
```

`load_page_players` 안의 링크 조립을 바꾼다.

```python
        links.setdefault(l["player_id"], []).append(
            {"content_hash": l["content_hash"], "stage": l["stage"],
             "role": l["role"]})
```

`build_player_entries` 의 docstring 첫 문단 두 줄을 바꾼다.
기존 문장은 "기사 목록은 단계가 other 인 귀속을 뺀 나머지다." 로 시작하는 세 줄이다.

```python
    """선수별 기사 목록 · 진행 단계 사다리 · 현재 단계 (스펙 §5).

    기사 목록은 역할이 언급인 귀속을 뺀 나머지다 (역할 필드 스펙 §3.3).
    단계로 고르던 것을 역할로 바꾼 것인데, 단계는 "이 기사가 그 선수에 대해
    보도하는 진행 단계" 라 "이 기사의 주인공인가" 와 다른 질문이고, 그 대가로
    화면 귀속 807건 중 331건이 남의 기사였다 (2026-08-12 실측).
    역할이 미기입이면 주역으로 읽는다 — 값이 채워지기 전에는 지금 화면이 그대로다.
    머리 건수도 같은 집합에서 나오므로 "머리 = 목록" 등식은 그대로다 (스펙 §5.3).
    서빙 목록에 없는 기사는 링크에서 빠지고, 그 결과 남는 기사가 0건인 선수는
    빈 페이지가 되지 않도록 결과에서 제외한다."""
```

같은 함수의 `paired` 조립 조건을 바꾼다.

```python
        paired = [(by_hash[l["content_hash"]], l["stage"]) for l in p["links"]
                  if l["content_hash"] in by_hash and l.get("role") != MENTION]
```

- [ ] **Step 5: 통과를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -v`
Expected: PASS

- [ ] **Step 6: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 전건 통과 (직전 기준 1016건 · 신규분 포함)

떨어지는 것이 있으면 그 테스트가 "단계 `other` 면 화면에서 빠진다" 를 전제로 쓰였는지 먼저 확인한다.

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_players.py
git commit -F - <<'EOF'
feat(serve): 선수 페이지의 기사 선별을 단계에서 역할로 교체

한 필드가 "이 기사의 주인공인가" 와 "어느 단계인가" 두 질문에 답하고 있어 양쪽 다
새고 있었다. 선별은 역할이 맡고 단계는 사다리와 배지에만 쓰도록 나눈다.

- 목록 · 건수 · 선수 칩의 기준을 역할로 교체: 남의 기사가 선수 페이지에 쌓이던
  귀속 331건이 빠지고, 담을 단계가 없어 묻혀 있던 소식 21건이 살아남
- 단계 조건을 함께 걸지 않음: 지금 화면의 잡음은 전부 단계값을 가진 채 통과한
  것들이라 2차 조건으로서 작동하지 않았음
- 역할 미기입은 주역으로 해석 — 값이 채워지기 전까지 화면은 그대로 유지
- 회귀 테스트 3건 추가 · 단계 기준을 전제하던 기존 테스트 3건 갱신

Refs: docs/superpowers/specs/2026-08-12-player-role-field-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: 머지 전 화면 검증

값이 아직 없으므로 운영 사본에 역할을 모의로 채워 새 규칙의 화면을 사람이 직접 본다.
런북 `docs/runbook/2026-08-11-premerge-screen-check-with-prod-copy.md` 의 절차다.
코드 변경은 없고 산출물은 확인 결과다.

**Files:**
- Create: 없음 (스크래치패드에서만 작업)
- Modify: 없음

**Interfaces:**
- Consumes: Task 3 까지의 코드 전부

- [ ] **Step 1: 운영 사본을 세션 전용 DB 로 뜬다**

이미 `bulletin_role` 이 있으면 건너뛴다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'docker exec bullet-in-mariadb-1 mariadb-dump -uroot -pbulletin bulletin articles article_players players' \
  > prod_role.sql
docker exec bullet-in-mariadb-1 mariadb -uroot -pbulletin \
  -e "DROP DATABASE IF EXISTS bulletin_role; CREATE DATABASE bulletin_role CHARACTER SET utf8mb4;"
docker exec -i bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin_role < prod_role.sql
```

- [ ] **Step 2: 사본에 컬럼을 만들고 역할을 모의로 채운다**

근사 기준은 제목의 한글 이름 대조다.
**이 근사는 정답이 아니다** — 제목에 이름이 있는데도 언급인 행이 6건, 이름이 없는데 본인 기사인 행이 표본 48건 중 1건 있었다 (스펙 §6.2).
따라서 이 화면으로 판정하는 것은 표시 규칙이지 어느 기사가 걸러질지가 아니다.

```bash
docker exec bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin_role -e "
ALTER TABLE article_players ADD COLUMN IF NOT EXISTS role VARCHAR(16);
UPDATE article_players ap
  JOIN players p ON p.id = ap.player_id
  JOIN articles a ON a.content_hash = ap.content_hash
SET ap.role = CASE
  WHEN p.ko_name IS NOT NULL
   AND LOCATE(p.ko_name, COALESCE(a.title_ko, a.title_original)) > 0
  THEN 'subject' ELSE 'mention' END;"
```

- [ ] **Step 3: 숫자를 먼저 대조한다**

```bash
docker exec bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin_role -e "
SELECT SUM(ap.stage <> 'other') AS old_total,
       SUM(ap.role = 'subject') AS new_total
  FROM article_players ap JOIN players p ON p.id = ap.player_id
 WHERE p.category IN ('squad','external') AND p.transfer_status <> 'none'
   AND p.status <> 'candidate';
SELECT p.ko_name, SUM(ap.stage <> 'other') AS old_n, SUM(ap.role = 'subject') AS new_n
  FROM article_players ap JOIN players p ON p.id = ap.player_id
 WHERE p.category IN ('squad','external') AND p.transfer_status <> 'none'
   AND p.status <> 'candidate'
 GROUP BY p.id HAVING old_n <> new_n ORDER BY (old_n - new_n) DESC;"
```

기대값은 옛 규칙 807 · 새 규칙 476 근처다 (모의값이라 정확히 일치하지 않아도 된다).
**페이지가 사라지는 선수** (새 규칙 0) 와 **새로 생기는 선수** (옛 0 · 새 1 이상) 를 목록으로 적어 둔다.

- [ ] **Step 4: 로컬에 렌더한다**

`docs/runbook/2026-07-19-enrich-only-pass.md` §4 의 스니펫을 그대로 쓴다.
출력 위치만 `site_role` 로 바꾼다.

```bash
set -a; source .env; set +a
MARIADB_URL="mysql+pymysql://root:bulletin@localhost:3306/bulletin_role" \
uv run python - <<'EOF'
import os, yaml
from sqlalchemy import create_engine, text
from bullet_in.run import SERVING_SELECT_SQL, LINKED_HASHES_SQL, serving_rows
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry, journalist_directory, outlet_directory
from bullet_in.serve.render import write_site
from bullet_in.storage.players import PlayerStore

engine = create_engine(os.environ["MARIADB_URL"])
with engine.connect() as c:
    rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
    linked = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())
blank = sum(1 for r in rows if not r["transfer_stage"])
assert blank == 0, f"stage 빈 행 {blank} — 중간 상태"
cfg = yaml.safe_load(open("config/sources.yaml", encoding="utf-8"))
fm_cfg = next(s for s in cfg["sources"] if s.get("adapter") == "fmkorea")
rows, hidden = serving_rows(rows,
    relevance_terms=fm_cfg.get("config", {}).get("relevance_terms", []),
    player_names=PlayerStore(engine).confirmed_ko_names(),
    linked=linked)
print(f"무관 글 서빙 제외 {hidden}건")
write_site(rows, load_sources("config/sources.yaml"), "site_role",
           directory=journalist_directory("config/credibility.yaml"),
           registry=load_registry("config/credibility.yaml"),
           outlet_dir=outlet_directory("config/credibility.yaml"))
print("site_role 재생성:", len(rows), "행")
EOF
```

- [ ] **Step 5: 사람이 직접 본다**

```bash
cd site_role && python3 -m http.server 8899 --bind 127.0.0.1
```

확인할 페이지는 여섯이다.

- 잡음이 컸던 곳 — `player/tzolis-*.html` (촐리스) · `player/konsa-*.html` (콘사) · `player/meslier-*.html` (멜리에)
슬러그는 `players.html` 에서 확인한다.
- 신호가 올라올 곳 — 수비멘디 · 완-비사카 · 마르티넬리

보는 것은 셋이다.

- 남의 기사가 목록에서 사라졌는가.
- 단계 없는 기사가 배지 없이 목록에 뜨는가 (사다리에는 줄이 없어야 한다).
- 머리 건수와 목록 길이가 같은가.

검토가 끝나면 서버를 내리고 `site_role` 을 지운다.

- [ ] **Step 6: 결과를 스펙에 적는다**

`docs/superpowers/specs/2026-08-12-player-role-field-design.md` 에 `## 8. 머지 전 화면 검증 결과` 를 더한다.
옛 규칙 · 새 규칙 건수, 사라진 선수와 새로 생긴 선수 목록, 눈으로 본 것에서 이상이 있었는지를 적는다.

```bash
git add docs/superpowers/specs/2026-08-12-player-role-field-design.md
git commit -F - <<'EOF'
docs(spec): 역할 필드 머지 전 화면 검증 결과 기록

운영 사본에 역할을 모의로 채워 새 규칙의 화면을 배포 전에 확인한 결과다.

- 옛 규칙과 새 규칙의 목록 건수 대조 · 페이지가 사라지거나 새로 생기는 선수 목록
- 잡음이 컸던 선수 페이지 셋과 신호가 올라오는 선수 페이지 셋의 눈검수 결과

Refs: docs/runbook/2026-08-11-premerge-screen-check-with-prod-copy.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## 이후 (계획 밖)

PR 생성 · 머지 · VM 반영 · 배포 · 배포 후 무변화 확인은 계획이 끝난 뒤 세션이 진행한다.
추출 프롬프트 개정 세션에 요구를 고지하는 것도 그때 한다 — 넘기는 것은 스펙 §5 (요구 · 경계 표본 3건 · 명확 사례 1건 · 오분류 27건 · 소급 572건을 그쪽 적용 회차에 묶는 근거) 다.
머지는 사용자가 직접 한다 (`gh pr merge` 금지).
배포 후 판정 기준은 **무변화 확인**이다 — 역할이 비어 있으므로 페이지가 지금과 같아야 하고, 달라지면 미기입 해석이 잘못된 것이다 (스펙 §5.3).
