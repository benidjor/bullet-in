# 선수 페이지 화면 개선 구현 계획

> **구현자에게**: 이 계획은 `superpowers:subagent-driven-development` 로 태스크 단위 실행한다.
> 단계는 체크박스 (`- [ ]`) 로 표시돼 있다.

**목표**: 선수 색인 · 선수 페이지에서 이름 · 그룹 · 배지 · 기사 목록 네 가지를 사용자 확정안대로 고쳐, 화면만 보고도 영입인지 방출인지 · 지금 어느 그룹인지 알 수 있게 한다.

**접근**: 데이터 한 겹 (`players.ko_full_name` 컬럼 신설 · 1회 적재) 과 서빙 한 겹 (`serve/render.py` · 템플릿 · `style.css`) 으로 나눈다.
분류 계열 (`article_players.stage` · `players.transfer_status`) 은 값을 읽기만 하고 쓰지 않는다.
기존 8개 이적 축 값 · slug 규칙 · 타임라인 전이 규칙은 그대로 둔다.

**스택**: Python 3.11 · SQLAlchemy · Jinja2 · pytest · MariaDB 11.

## 전역 제약

- 필드 소유권은 서빙 계열 (`src/bullet_in/serve/` · 템플릿 · `static/`) + `players.ko_full_name` 신설분이다.
- `players.ko_name` · `players.ko_candidate` · `players.transfer_status` 는 읽기만 한다.
- `article_players.stage` 값을 고치지 않는다.
- 타임라인의 단계 오르내림 (역행 표시) 규칙을 건드리지 않는다.
- 기사 단위 분류 (`enrich.py` · 추출 프롬프트) 를 건드리지 않는다.
- 지난 창 영입 (요케레스 · 에제 등) 을 여기서 처리하지 않는다.
- slug 규칙 (`player_slug`) 을 바꾸지 않는다.
- `PlayerStore.serving_names()` · `gate_name_map()` 은 건드리지 않는다.
- 문서는 한국어 · 컨벤션 §2.2 서식으로 쓴다.
- 커밋 메시지는 `<type>(<scope>): 한국어 제목` + 도입 1~2문장 + 명사형 불릿 + `Refs:` + co-author 트레일러.

## 작업 위치 · git 규율 (필독)

- 워크트리 절대 경로
— `/Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish`
- 브랜치
— `feat/player-page-polish` (base `b2431d7`)
- **모든 git 명령에 `-C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish` 를 붙인다.**
- 매 태스크 시작 시 `git -C <워크트리> rev-parse --abbrev-ref HEAD` 로 브랜치가 `feat/player-page-polish` 인지 자기검증한다.
- **`git reset` 을 실행하지 마라.**
- **`git rebase` 를 실행하지 마라.**
- **`git checkout <다른 브랜치>` 를 실행하지 마라.**
- 커밋은 반드시 워크트리 안에서만 한다.

## 파일 구조

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `src/bullet_in/storage/schema.sql` | `players.ko_full_name` 컬럼 정의 | 수정 |
| `src/bullet_in/backfill_ko_full_name.py` | 한글 풀네임 1회 적재 · 승인 표기 표 | 신설 |
| `tests/test_backfill_ko_full_name.py` | 적재 규칙 순수 함수 테스트 | 신설 |
| `src/bullet_in/storage/players.py` | `page_players()` 가 `ko_full_name` 을 함께 싣는다 | 수정 |
| `src/bullet_in/serve/render.py` | 표시 이름 폴백 · `other` 귀속 제외 · 그룹 4분할 | 수정 |
| `src/bullet_in/serve/templates/players.html.j2` | 모든 그룹에 접기 · 펼치기 버튼 | 수정 |
| `src/bullet_in/serve/static/style.css` | 배지 색을 영입 · 방출 계열로 분리 | 수정 |
| `tests/test_serve_players.py` | 위 전부의 회귀 테스트 | 수정 |
| `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` | §4.1 · §5.3 개정 | 수정 |

---

### Task 1: `players.ko_full_name` 컬럼 신설 · 적재 규칙

**파일**
- 수정: `src/bullet_in/storage/schema.sql:46-60` (players 테이블 뒤)
- 생성: `src/bullet_in/backfill_ko_full_name.py`
- 테스트: `tests/test_backfill_ko_full_name.py`

**인터페이스**
- 제공: `resolve(full_name: str, ko_name: str | None, ko_candidate: str | None) -> str | None`
— 적재할 한글 풀네임. 정할 수 없으면 `None` 이고, 그 경우 표시는 Task 2 의 폴백으로 떨어진다.
- 제공: `APPROVED: dict[str, str]` — `full_name` 을 키로 하는 사용자 승인 표기 23건.

**왜 규칙 + 예외 표인가**
`ko_candidate` 는 자동 발굴이 넣은 값이라 어떤 행은 풀네임 (`크리스티안 뇌르고르`) 이고 어떤 행은 성만 (`마르틴`) 이다.
길이 비교 규칙 하나로 27건이 자동으로 맞고, 규칙이 틀리는 두 건 (`Kyran Thompson` · `Jon Martin`) 과 사용자가 새로 승인한 22건만 표로 못 박는다.

- [ ] **1단계: 컬럼을 스키마에 추가한다**

`src/bullet_in/storage/schema.sql` 의 `article_players` 생성문 **앞** (players 생성문 바로 뒤) 에 한 줄 넣는다.
기존 `articles` 컬럼 추가와 같은 멱등 형식이다.

```sql
ALTER TABLE players ADD COLUMN IF NOT EXISTS ko_full_name VARCHAR(60);
```

- [ ] **2단계: 실패하는 테스트를 쓴다**

`tests/test_backfill_ko_full_name.py` 를 새로 만든다.

```python
"""ko_full_name 적재 규칙 — 승인 표기 우선 · 나머지는 ko_candidate 길이 규칙."""
from bullet_in.backfill_ko_full_name import APPROVED, resolve


def test_approved_table_wins_over_candidate():
    # 승인 표기가 있으면 ko_candidate 가 무엇이든 그 값을 쓴다.
    assert resolve("Bradley Barcola", "바르콜라", "바르콜라") == "브래들리 바르콜라"


def test_longer_candidate_is_adopted():
    assert resolve("Christian Norgaard", "뇌르고르", "크리스티안 뇌르고르") == "크리스티안 뇌르고르"


def test_shorter_candidate_is_skipped():
    # ko_name 이 이미 풀네임이고 후보가 성만인 경우 — Jon Martin.
    assert resolve("Jon Martin", "욘 마르틴", "마르틴") is None


def test_equal_candidate_is_skipped():
    assert resolve("Nico Williams", "니코 윌리암스", "니코 윌리암스") is None


def test_missing_ko_name_takes_candidate():
    # ko_name 이 비어 있으면 화면이 영문으로 떨어지므로 후보를 그대로 쓴다.
    assert resolve("Aladji Bamba", None, "알라지 밤바") == "알라지 밤바"


def test_kyran_thompson_keeps_user_confirmed_spelling():
    # 후보 (카이런 톰슨) 가 더 길지만 사용자 확정 값은 ko_name 쪽이다.
    assert resolve("Kyran Thompson", "키란 톰슨", "카이런 톰슨") == "키란 톰슨"


def test_no_candidate_returns_none():
    assert resolve("Ezri Konsa2", "콘사2", None) is None


def test_approved_table_has_23_entries():
    assert len(APPROVED) == 23
```

- [ ] **3단계: 테스트가 실패하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_backfill_ko_full_name.py -q
```
기대: `ModuleNotFoundError: No module named 'bullet_in.backfill_ko_full_name'` 로 전건 실패.

- [ ] **4단계: 적재 모듈을 구현한다**

`src/bullet_in/backfill_ko_full_name.py` 를 새로 만든다.

```python
"""선수 한글 풀네임 1회 적재 — players.ko_full_name.

표시용 컬럼이라 ko_name · ko_candidate 는 건드리지 않는다.
값을 정할 수 없는 행은 비워 두고, 화면이 ko_name → full_name 으로 떨어진다.
"""
from __future__ import annotations
import argparse
import os
from sqlalchemy import create_engine, text

# 사용자 승인 표기 (2026-08-03) — ko_candidate 규칙으로는 나오지 않는 값만 담는다.
# 앞의 22건은 새로 승인받은 표기, 마지막 Kyran Thompson 은 규칙이 후보를 고르는 것을
# 막기 위한 예외다 (ko_name 쪽이 사용자 확정 값).
APPROVED: dict[str, str] = {
    "Anthony Gordon": "앤서니 고든",
    "Axel Donczew": "악셀 돈체프",
    "Bradley Barcola": "브래들리 바르콜라",
    "Bruno Guimaraes": "브루노 기마랑이스",
    "Charles Sagoe Jr": "찰스 세이고 주니어",
    "Christos Tzolis": "크리스토스 촐리스",
    "Eberechi Eze": "에베레치 에제",
    "Eli Junior Kroupi": "엘리 주니오르 크루피",
    "Elliot Anderson": "엘리엇 앤더슨",
    "Ezri Konsa": "에즈리 콘사",
    "Illan Meslier": "일란 멜리에",
    "Jacobo Ramon": "하코보 라몬",
    "Jakub Kiwior": "야쿠프 키비오르",
    "Julian Alvarez": "훌리안 알바레스",
    "Leandro Trossard": "레안드로 트로사르",
    "Marcus Rashford": "마커스 래시포드",
    "Morgan Rogers": "모건 로저스",
    "Noni Madueke": "노니 마두에케",
    "Ollie Watkins": "올리 왓킨스",
    "Piero Hincapie": "피에로 인카피에",
    "Sandro Tonali": "산드로 토날리",
    "Viktor Gyokeres": "빅토르 요케레스",
    "Kyran Thompson": "키란 톰슨",
}


def resolve(full_name: str, ko_name: str | None,
            ko_candidate: str | None) -> str | None:
    """적재할 한글 풀네임. 정할 수 없으면 None.

    승인 표기가 최우선이고, 그 다음은 ko_name 보다 긴 ko_candidate 다.
    길이 조건이 없으면 성만 담긴 후보 (Jon Martin 의 '마르틴') 가 풀네임을 밀어낸다.
    """
    if full_name in APPROVED:
        return APPROVED[full_name]
    if not ko_candidate:
        return None
    if ko_name is None:
        return ko_candidate
    return ko_candidate if len(ko_candidate) > len(ko_name) else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(
            "SELECT id, full_name, ko_name, ko_candidate, ko_full_name "
            "FROM players")).mappings().all()]
    updates = []
    for r in rows:
        value = resolve(r["full_name"], r["ko_name"], r["ko_candidate"])
        if value and value != r["ko_full_name"]:
            updates.append({"id": r["id"], "v": value})
    print(f"대상 {len(rows)}행 · 적재 {len(updates)}행")
    if args.dry_run:
        for u in updates[:10]:
            print(" ", u)
        return
    if updates:
        with engine.begin() as c:
            c.execute(text("UPDATE players SET ko_full_name=:v WHERE id=:id"),
                      updates)
    print("적재 완료")


if __name__ == "__main__":
    main()
```

- [ ] **5단계: 테스트가 통과하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_backfill_ko_full_name.py -q
```
기대: 8 passed.

- [ ] **6단계: 커밋한다**

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish rev-parse --abbrev-ref HEAD
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish add src/bullet_in/storage/schema.sql src/bullet_in/backfill_ko_full_name.py tests/test_backfill_ko_full_name.py
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish commit -F - <<'MSG'
feat(players): 한글 풀네임 컬럼 신설 · 1회 적재 모듈 추가

선수 화면이 성만 보여 주고 있어 동명이인과 낯선 선수를 구분하기 어렵다.
표시 전용 컬럼을 따로 두고, 이름 판정의 원천인 ko_name · ko_candidate 는 건드리지 않는다.

- 스키마: players.ko_full_name 컬럼 (VARCHAR(60) · 멱등 ALTER)
- 적재 규칙: 사용자 승인 표기 23건 우선 · 나머지는 ko_name 보다 긴 ko_candidate
- 예외 처리: 성만 담긴 후보 (Jon Martin) · 후보가 더 길어도 확정값이 따로 있는 경우 (Kyran Thompson)
- 테스트: 규칙 순수 함수 8건

Refs: #144
MSG
```

---

### Task 2: 표시 이름 폴백 — `ko_full_name` → `ko_name` → `full_name`

**파일**
- 수정: `src/bullet_in/storage/players.py:129-137` (`page_players`)
- 수정: `src/bullet_in/serve/render.py:992-993` (`build_player_entries` 의 `name`)
- 테스트: `tests/test_serve_players.py`

**인터페이스**
- 사용: Task 1 의 `players.ko_full_name` 컬럼.
- 제공: `page_players()` 반환 dict 에 `ko_full_name` 키가 추가된다.
`build_player_entries` 결과의 `name` 이 한글 풀네임이 된다.
이 `name` 은 선수 색인 · 선수 페이지 머리 · 상세 페이지 칩 (`player_chips`) 세 곳이 함께 쓴다.

- [ ] **1단계: 실패하는 테스트를 쓴다**

`tests/test_serve_players.py` 끝에 붙인다.
기존 `test_build_player_entries_falls_back_to_full_name` 은 그대로 둔다 — 폴백 마지막 칸을 지키는 테스트다.

```python
def test_build_player_entries_prefers_ko_full_name():
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)}]
    players = [{"id": 1, "full_name": "Christos Tzolis", "surname": "Tzolis",
                "ko_full_name": "크리스토스 촐리스", "ko_name": "촐리스",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest"}]}]
    assert render.build_player_entries(rows, players)[0]["name"] == "크리스토스 촐리스"


def test_build_player_entries_falls_back_to_ko_name():
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)}]
    players = [{"id": 1, "full_name": "Christos Tzolis", "surname": "Tzolis",
                "ko_full_name": None, "ko_name": "촐리스",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest"}]}]
    assert render.build_player_entries(rows, players)[0]["name"] == "촐리스"
```

- [ ] **2단계: 테스트가 실패하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_serve_players.py -q -k "prefers_ko_full_name or falls_back_to_ko_name"
```
기대: `test_build_player_entries_prefers_ko_full_name` 이 `'촐리스' != '크리스토스 촐리스'` 로 실패.

- [ ] **3단계: 최소 구현을 넣는다**

`src/bullet_in/serve/render.py` 의 `build_player_entries` 에서 `name` 줄 하나만 바꾼다.

```python
                    "name": (p.get("ko_full_name") or p.get("ko_name")
                             or p["full_name"]),
```

`src/bullet_in/storage/players.py` 의 `page_players` SELECT 에 컬럼을 넣는다.

```python
                "SELECT id, full_name, surname, ko_name, ko_full_name, "
                "transfer_status "
```

- [ ] **4단계: 테스트가 통과하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_serve_players.py -q
```
기대: 전건 통과.

- [ ] **5단계: 커밋한다**

```bash
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish rev-parse --abbrev-ref HEAD
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish add src/bullet_in/serve/render.py src/bullet_in/storage/players.py tests/test_serve_players.py
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish commit -F - <<'MSG'
feat(serve): 선수 표시 이름을 한글 풀네임 우선으로 바꿈

색인 · 선수 페이지 머리 · 상세 칩이 모두 같은 이름을 쓰므로 한 곳에서만 폴백을 정한다.
값이 없는 선수도 화면이 깨지지 않도록 두 칸을 더 둔다.

- 폴백 순서: ko_full_name → ko_name → full_name
- 조회: page_players 가 ko_full_name 을 함께 싣도록 SELECT 확장
- 테스트: 풀네임 우선 · ko_name 폴백 2건

Refs: #144
MSG
```

---

### Task 3: 기사 목록에서 `stage` 가 `other` 인 귀속 제외

**파일**
- 수정: `src/bullet_in/serve/render.py:968-1000` (`build_player_entries`)
- 수정: `tests/test_serve_players.py:137-143` (`test_build_player_entries_has_no_stage_when_all_other`)
- 수정: `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` (§5.3)

**인터페이스**
- 사용: Task 2 의 `build_player_entries`.
- 제공: 기사 목록 · 머리 건수 (`count`) · 색인 대상이 모두 `other` 를 뺀 집합으로 좁아진다.
색인 대상은 56명에서 50명으로 줄고, 남는 기사가 0건이 된 6명은 기존 `if not paired: continue` 가 알아서 떨어뜨린다.

**실측 근거 (다시 재지 말 것)**
- 대상 선수 56명 · 귀속 `stage` 분포는 `interest` 299 · `other` 155 · `agreed` 121 · `rumour` 81 · `negotiating` 59 · `medical` 12 · `personal_terms` 7 · `official` 6.
- `stage` 가 `NULL` 인 귀속은 0건이다.
따라서 `other` 만 빼면 되고 `NULL` 처리를 따로 넣을 필요가 없다.
- `other` 를 뺀 뒤 남는 선수는 정확히 50명이다.

- [ ] **1단계: 기존 테스트를 새 기대값으로 고친다**

`tests/test_serve_players.py` 의 `test_build_player_entries_has_no_stage_when_all_other` 를 아래로 교체한다.
이름과 기대값이 함께 바뀐다 — 기사가 전부 `other` 인 선수는 이제 항목 자체가 없다.

```python
def test_build_player_entries_drops_player_whose_articles_are_all_other():
    # 이적 얘기가 없는데 이름만 스친 선수 — 색인 56명이 50명으로 줄어든 근거다.
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)},
            {"content_hash": "h2", "published_at": datetime(2026, 8, 2)}]
    players = [{"id": 1, "full_name": "Martin Zubimendi", "surname": "Zubimendi",
                "ko_full_name": None, "ko_name": "수비멘디",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "other"},
                          {"content_hash": "h2", "stage": "other"}]}]
    assert render.build_player_entries(rows, players) == []
```

- [ ] **2단계: 추가로 실패하는 테스트를 쓴다**

같은 파일 끝에 붙인다.

```python
def test_build_player_entries_excludes_other_from_list_and_count():
    # 머리 건수와 목록 수가 어긋나면 안 되므로 둘 다 같은 집합에서 나와야 한다.
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)},
            {"content_hash": "h2", "published_at": datetime(2026, 8, 2)},
            {"content_hash": "h3", "published_at": datetime(2026, 8, 3)}]
    players = [{"id": 1, "full_name": "Christos Tzolis", "surname": "Tzolis",
                "ko_full_name": None, "ko_name": "촐리스",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest"},
                          {"content_hash": "h2", "stage": "other"},
                          {"content_hash": "h3", "stage": "agreed"}]}]
    entry = render.build_player_entries(rows, players)[0]
    assert entry["count"] == 2
    assert len(entry["articles"]) == 2
    assert [a["content_hash"] for a in entry["articles"]] == ["h3", "h1"]
```

- [ ] **3단계: 테스트가 실패하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_serve_players.py -q -k "all_other or excludes_other"
```
기대: 두 건 모두 실패 (`count` 가 3 · 항목이 1건 반환).

- [ ] **4단계: 최소 구현을 넣는다**

`build_player_entries` 의 `paired` 를 만드는 곳에 조건 하나를 더한다.

```python
        paired = [(by_hash[l["content_hash"]], l["stage"]) for l in p["links"]
                  if l["content_hash"] in by_hash and l["stage"] != _stage.OTHER]
```

같은 함수의 docstring 에서 "기사 목록은 귀속 전량이다 — 단계 없는 기사도 포함한다." 문단을 아래로 바꾼다.

```python
    """선수별 기사 목록 · 전이 타임라인 · 현재 단계 (스펙 §5).

    기사 목록은 단계가 other 인 귀속을 뺀 나머지다.
    이름만 스친 기사가 그 선수의 이적 기사인 것처럼 쌓이던 것을 막기 위한 것이며,
    머리 건수도 같은 집합에서 나오므로 "머리 = 목록" 등식은 그대로다 (스펙 §5.3).
    서빙 목록에 없는 기사는 링크에서 빠지고, 그 결과 남는 기사가 0건인 선수는
    빈 페이지가 되지 않도록 결과에서 제외한다."""
```

`_stage` 는 이미 `render.py` 상단에서 import 돼 있다 — 확인만 하고 새로 넣지 마라.

- [ ] **5단계: 테스트가 통과하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_serve_players.py -q
```
기대: 전건 통과.

- [ ] **6단계: 스펙 §5.3 을 개정한다**

`docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` 의 §5.3 첫 두 줄을 아래로 바꾼다.
나머지 문단 (필터 사이드바 관련) 은 건드리지 않는다.

```markdown
### 5.3. 기사 목록

단계가 `other` 인 귀속을 뺀 기사를 최신순 평면 카드로 놓는다.
이름만 스친 기사가 그 선수의 이적 기사처럼 쌓이던 것을 막는 것이며, 2026-08-03 사용자 검토에서 나온 변경이다.
머리의 건수도 같은 집합에서 세므로 머리와 목록이 어긋나지 않는다.
```

- [ ] **7단계: 커밋한다**

```bash
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish rev-parse --abbrev-ref HEAD
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish add src/bullet_in/serve/render.py tests/test_serve_players.py docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish commit -F - <<'MSG'
feat(serve): 선수 기사 목록에서 단계 없는 귀속 제외

이름만 스친 기사가 그 선수의 이적 기사처럼 쌓여, 이적 얘기가 전혀 없는 선수에게도 페이지가 생겼다.
머리 건수와 목록을 같은 집합에서 뽑아 둘이 어긋나지 않게 유지한다.

- 제외 대상: article_players.stage 가 other 인 귀속
- 색인 축소: 대상 선수 56명 → 50명 (남는 기사 0건인 6명 자동 탈락)
- 실측: NULL 단계 귀속 0건이라 other 조건 하나로 충분
- 스펙 §5.3 개정 · 회귀 테스트 2건

Refs: #144
MSG
```

---

### Task 4: 그룹 4분할 · 라벨 변경 · 전 그룹 접기 · 펼치기

**파일**
- 수정: `src/bullet_in/serve/render.py:922-931` (`TRANSFER_GROUPS` · `_TRANSFER_GROUP_OF`)
- 수정: `src/bullet_in/serve/templates/players.html.j2:8`
- 수정: `tests/test_serve_players.py:31-45` · `:174-187` · `:284-292`
- 수정: `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` (§4.1)

**인터페이스**
- 사용: Task 3 의 `build_player_entries` 결과.
- 제공: `TRANSFER_GROUPS` 가 4묶음이 된다
— `("진행 중", False)` · `("이적 확정", False)` · `("이적 무산", True)` · `("타 클럽행", True)`.
`transfer_group()` 이 반환하는 그룹명이 바뀐다.

**빈 그룹은 안 그린다**
템플릿의 `{% if g.members %}` 가 이미 빈 그룹을 걸러 낸다.
`link_dropped` 가 현재 0건이라 `이적 무산` 그룹은 당분간 화면에 나오지 않는다 — 정상이다.

- [ ] **1단계: 실패하는 테스트를 쓴다**

`tests/test_serve_players.py` 의 기존 두 테스트를 아래로 교체한다.

```python
def test_transfer_group_splits_eight_values_without_gap():
    assert render.transfer_group("in_link") == "진행 중"
    assert render.transfer_group("out_link") == "진행 중"
    assert render.transfer_group("in_done") == "이적 확정"
    assert render.transfer_group("out_done") == "이적 확정"
    assert render.transfer_group("loan_in") == "이적 확정"
    assert render.transfer_group("loan_out") == "이적 확정"
    assert render.transfer_group("link_dropped") == "이적 무산"
    assert render.transfer_group("other_club") == "타 클럽행"
    assert render.transfer_group("none") == ""


def test_transfer_groups_order_and_collapse_flag():
    assert render.TRANSFER_GROUPS == [
        ("진행 중", False), ("이적 확정", False),
        ("이적 무산", True), ("타 클럽행", True)]
```

같은 파일의 `test_render_players_folded_group_has_plfold_button` 을 아래로 교체한다.

```python
def test_render_players_every_group_has_a_fold_button():
    # 접힌 그룹만 버튼이 있으면 펼쳐진 그룹은 접을 수 없고, 접힌 그룹은 비어 보인다.
    entries = [
        {"name": "촐리스", "slug": "tzolis", "transfer_status": "in_link",
         "stage": "interest", "count": 3, "last_ts": datetime(2026, 8, 2)},
        {"name": "모건 로저스", "slug": "rogers", "transfer_status": "other_club",
         "stage": "agreed", "count": 5, "last_ts": datetime(2026, 8, 1)},
    ]
    html = render.render_players(entries, datetime(2026, 8, 3))
    assert html.count('class="plfold"') == 2
    assert ">접기<" in html
    assert ">펼치기<" in html
```

- [ ] **2단계: 테스트가 실패하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_serve_players.py -q -k "transfer_group or transfer_groups or fold_button"
```
기대: 세 건 모두 실패 (그룹명이 `성사` · `무산과 종료` · 버튼이 1개).

- [ ] **3단계: 그룹 정의를 바꾼다**

`src/bullet_in/serve/render.py` 의 두 상수를 아래로 교체한다.
주석의 "3그룹" 표현도 함께 고친다.

```python
# 색인 4그룹 (스펙 §4.1) — (그룹명, 기본 접힘).
# 무산 · 타 클럽행은 되짚기용이라 접어 두고, 접기 · 펼치기는 네 그룹 모두에 둔다.
TRANSFER_GROUPS: list[tuple[str, bool]] = [
    ("진행 중", False), ("이적 확정", False),
    ("이적 무산", True), ("타 클럽행", True),
]

_TRANSFER_GROUP_OF: dict[str, str] = {
    "in_link": "진행 중", "out_link": "진행 중",
    "in_done": "이적 확정", "out_done": "이적 확정",
    "loan_in": "이적 확정", "loan_out": "이적 확정",
    "link_dropped": "이적 무산", "other_club": "타 클럽행",
}
```

`transfer_group` 의 docstring 도 한 줄 고친다.

```python
    """색인 그룹명. 여덟 값이 4그룹으로 빠짐없이 갈린다."""
```

- [ ] **4단계: 템플릿에서 버튼을 항상 그린다**

`src/bullet_in/serve/templates/players.html.j2` 의 8번째 줄을 아래로 바꾼다.

```jinja
    <button class="plfold" type="button">{{ '펼치기' if g.collapsed else '접기' }}</button>
```

`app.js` 는 이미 `.plgrp .plfold` 를 모두 잡아 토글하므로 손대지 않는다.

- [ ] **5단계: 테스트가 통과하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_serve_players.py -q
```
기대: 전건 통과.

- [ ] **6단계: 스펙 §4.1 을 개정한다**

`docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` 의 §4.1 을 아래로 바꾼다.

```markdown
### 4.1. 4그룹

| 그룹 | 포함 값 | 기본 상태 |
| --- | --- | --- |
| 진행 중 | `in_link` · `out_link` | 펼침 |
| 이적 확정 | `in_done` · `out_done` · `loan_in` · `loan_out` | 펼침 |
| 이적 무산 | `link_dropped` | 접힘 |
| 타 클럽행 | `other_club` | 접힘 |

무산 · 타 클럽행은 되짚기용이라 접어 둔다.
접기 · 펼치기 버튼은 네 그룹 모두에 둔다.
접힌 그룹에만 버튼이 있으면 그 그룹이 비어 있는 것으로 읽힌다 — 2026-08-03 사용자 검토에서 실제로 그렇게 읽혔다.
빈 그룹은 그리지 않으므로 `link_dropped` 가 0건인 동안 이적 무산 그룹은 화면에 나오지 않는다.
```

- [ ] **7단계: 커밋한다**

```bash
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish rev-parse --abbrev-ref HEAD
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish add src/bullet_in/serve/render.py src/bullet_in/serve/templates/players.html.j2 tests/test_serve_players.py docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish commit -F - <<'MSG'
feat(serve): 선수 색인 그룹을 넷으로 나누고 모든 그룹을 접을 수 있게 함

무산과 종료를 한 묶음으로 두니 이적이 틀어진 선수와 다른 팀으로 간 선수가 섞여 보였다.
접힌 그룹에만 버튼이 있어 그 그룹이 비어 있는 것으로 읽히던 문제도 함께 고친다.

- 그룹 분할: 무산과 종료 → 이적 무산 (link_dropped) · 타 클럽행 (other_club)
- 라벨 변경: 성사 → 이적 확정
- 접기 버튼: 네 그룹 모두에 표시 · 초기 문구는 접힘 상태를 따라감
- 스펙 §4.1 개정 · 회귀 테스트 3건

Refs: #144
MSG
```

---

### Task 5: 배지 색을 영입 계열 · 방출 계열로 분리

**파일**
- 수정: `src/bullet_in/serve/static/style.css:315-332`
- 테스트: `tests/test_serve_players.py:277-283`

**인터페이스**
- 사용: `transfer_badge()` 가 내보내는 여덟 클래스 (`t-inlink` · `t-outlink` · `t-indone` · `t-outdone` · `t-loanin` · `t-loanout` · `t-dropped` · `t-otherclub`).
클래스 이름과 배지 문구는 바꾸지 않는다 — 바뀌는 것은 색 배정뿐이다.

**무엇이 왜 바뀌나**
지금은 색이 단계를 나른다 — 링크는 둘 다 빨강, 완료는 둘 다 초록이고, 영입인지 방출인지는 실선 · 파선 차이로만 구분된다.
이것을 뒤집어 색이 계열을 나르게 한다.

| | 영입 계열 | 방출 계열 | 무산 · 종료 |
| --- | --- | --- | --- |
| 색 | `--red` | `--green` | `--mut` |
| 링크 | `t-inlink` 파선 | `t-outlink` 파선 | `t-dropped` 실선 |
| 완료 | `t-indone` 실선 | `t-outdone` 실선 | `t-otherclub` 파선 |
| 임대 | `t-loanin` 점선 | `t-loanout` 점선 | |

`--yellow` 는 배지에서 빠진다 — 이 변경이 만든 고아이므로 배지 규칙에서만 걷어 내고, 토큰 자체는 `.stage.yellow` 가 계속 쓰므로 남긴다.

**대비 실측 (계산 완료 · 다시 재지 말 것)**

WCAG 2.1 상대 휘도 공식으로 배경 `--paper` 대비를 계산한 값이다.

| 토큰 | 라이트 | 다크 | 판정 |
| --- | --- | --- | --- |
| `--red` | 5.03:1 | 5.80:1 | 통과 |
| `--green` | 5.14:1 | 8.93:1 | 통과 |
| `--mut` | 5.20:1 | 6.98:1 | 통과 |

세 색 모두 라이트 · 다크 양쪽에서 4.5:1 을 넘는다.
흰 글자 채움 배경은 쓰지 않는다 — 다크에서 흰 글자 대비가 빨강 3.23:1 · 초록 2.10:1 로 무너진다.

- [ ] **1단계: 실패하는 테스트를 쓴다**

`tests/test_serve_players.py` 의 `test_style_css_defines_all_eight_transfer_badge_classes` 는 그대로 두고 아래를 덧붙인다.

```python
def test_transfer_badge_color_splits_in_and_out():
    # 색이 계열을 나른다 — 영입 3종은 red, 방출 3종은 green.
    css = (Path("src/bullet_in/serve/static/style.css")
           .read_text(encoding="utf-8"))
    for cls in ("t-inlink", "t-indone", "t-loanin"):
        line = next(l for l in css.splitlines() if l.startswith(f".{cls}{{"))
        assert "var(--red)" in line and "var(--green)" not in line
    for cls in ("t-outlink", "t-outdone", "t-loanout"):
        line = next(l for l in css.splitlines() if l.startswith(f".{cls}{{"))
        assert "var(--green)" in line and "var(--red)" not in line


def test_transfer_badge_never_uses_white_fill():
    # 다크 토큰은 흰 글자와 대비가 무너진다 (red 3.23:1 · green 2.10:1).
    css = (Path("src/bullet_in/serve/static/style.css")
           .read_text(encoding="utf-8"))
    for cls in ("t-inlink", "t-indone", "t-loanin",
                "t-outlink", "t-outdone", "t-loanout"):
        line = next(l for l in css.splitlines() if l.startswith(f".{cls}{{"))
        assert "background" not in line
```

`Path` 가 그 테스트 파일에 이미 import 돼 있는지 확인하고, 없으면 파일 상단에 `from pathlib import Path` 를 더한다.

- [ ] **2단계: 테스트가 실패하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_serve_players.py -q -k "color_splits or white_fill"
```
기대: `test_transfer_badge_color_splits_in_and_out` 이 실패 (`t-indone` 이 green · `t-outlink` 가 red · `t-loanin` 이 yellow 혼합).

- [ ] **3단계: CSS 를 바꾼다**

`src/bullet_in/serve/static/style.css` 의 이적 축 배지 주석 블록과 여덟 규칙을 아래로 교체한다.
`.tbadge` 자체 (글자 크기 · 여백 · 라운드) 는 건드리지 않는다.

```css
/* 이적 축 배지 — 색이 계열 (영입 red · 방출 green · 무산과 종료 mut) 을 나르고,
   테두리가 단계 (링크 파선 · 완료 실선 · 임대 점선) 를 나른다.
   흰 글자 채움 배경은 쓰지 않는다 — 다크 토큰은 흰 글자와 대비가 무너진다
   (red 3.23:1 · green 2.10:1 · WCAG AA 미달).
   텍스트 색만 쓰며 paper 대비는 계산으로 확인했다 — 라이트/다크 순으로
   red 5.03/5.80 · green 5.14/8.93 · mut 5.20/6.98 로 전부 4.5:1 이상이다. */
.tbadge{display:inline-flex;align-items:center;font-size:11px;font-weight:700;
  padding:1px 6px;border-radius:2px;letter-spacing:.01em;margin:0 6px 4px 0}
.t-inlink{color:var(--red);border:1px dashed var(--red)}
.t-indone{color:var(--red);border:1px solid var(--red)}
.t-loanin{color:var(--red);border:1px dotted var(--red)}
.t-outlink{color:var(--green);border:1px dashed var(--green)}
.t-outdone{color:var(--green);border:1px solid var(--green)}
.t-loanout{color:var(--green);border:1px dotted var(--green)}
.t-dropped{color:var(--mut);border:1px solid var(--hair)}
.t-otherclub{color:var(--mut);border:1px dashed var(--hair)}
```

- [ ] **4단계: 테스트가 통과하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest tests/test_serve_players.py -q
```
기대: 전건 통과.

- [ ] **5단계: 전체 테스트를 돌린다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish
uv run pytest -q
```
기대: 실패 0건 (통합 테스트는 DB 없으면 skip).

- [ ] **6단계: 커밋한다**

```bash
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish rev-parse --abbrev-ref HEAD
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish add src/bullet_in/serve/static/style.css tests/test_serve_players.py
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/feat-player-page-polish commit -F - <<'MSG'
feat(serve): 이적 축 배지 색을 영입 · 방출 계열로 분리

색이 링크인지 완료인지를 나르고 있어, 영입과 방출이 같은 색으로 보였다.
색과 테두리의 역할을 맞바꿔 한눈에 방향을 읽을 수 있게 한다.

- 색 배정: 영입 계열 red · 방출 계열 green · 무산과 종료 mut
- 테두리: 링크 파선 · 완료 실선 · 임대 점선
- 대비 확인: 라이트/다크 paper 대비 red 5.03/5.80 · green 5.14/8.93 · mut 5.20/6.98
- 흰 글자 채움 배제 유지 (다크에서 red 3.23:1 · green 2.10:1 로 미달)
- 테스트: 계열별 색 배정 · 채움 배경 금지 2건

Refs: #144
MSG
```

---

## 배포 · 검증 (머지 후 · 세션이 직접 수행)

태스크가 아니라 사람이 순서대로 밟는 절차다.

1. 사용자가 PR 을 직접 머지한다.
2. VM 에서 `git pull` 한다 (런북 `2026-07-20-vm-cohost-bootstrap.md` §6.1).
3. 스키마를 먼저 반영한다.
`ko_full_name` 컬럼을 만드는 `ensure_schema()` 는 정기 회차 안에서만 돌기 때문에, 회차를 기다리지 않고 백필 · 재렌더를 하려면 이 단계가 앞에 와야 한다.
컬럼 없이 백필을 돌리면 `Unknown column 'ko_full_name'` 으로 죽는다.

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine
from bullet_in.storage.mariadb import MartStore
MartStore(create_engine(os.environ["MARIADB_URL"])).ensure_schema()
print("스키마 반영 완료")
EOF
```

4. `uv run python -m bullet_in.backfill_ko_full_name --dry-run` 으로 적재 대상 건수를 먼저 본다.
5. `--dry-run` 없이 실행해 `ko_full_name` 을 적재한다.
6. 배포 게이트를 확인한다
— `transfer_stage` NULL 0건 (런북 `2026-07-19-enrich-only-pass.md` §4).
7. 런북 §4 의 재렌더 스니펫으로 사이트를 다시 만든다.
그 스니펫도 `ensure_schema()` 를 부르지 않으므로 3번을 건너뛰면 여기서 같은 오류가 난다.
8. 라이브에서 확인한다
— 색인이 50명 · 그룹 4개 (이적 무산은 0건이라 안 보임) · 네 그룹 모두 접기 버튼 · 한글 풀네임 표시 · 죽은 칩 링크 0건.
9. 다음 정기 회차 (약 3시간 간격) 가 정상으로 도는지 본다.

## 자기 점검

- 사용자 확정 6건이 모두 태스크에 들어갔다
— 1번 Task 1 · 2 / 2번 Task 4 / 3번 Task 5 / 4번 Task 4 / 5번 Task 4 / 6번 Task 3.
- 하지 말 것 3건은 어느 태스크에서도 건드리지 않는다 (타임라인 · 기사 단위 분류 · 지난 창 영입).
- 타입 일관성
— `resolve()` 반환은 `str | None`, `page_players()` 의 `ko_full_name` 도 `str | None`, `build_player_entries` 의 폴백이 `None` 을 받아 넘긴다.
- `TRANSFER_GROUPS` 의 그룹명과 `_TRANSFER_GROUP_OF` 의 값이 같은 네 문자열을 쓴다.
