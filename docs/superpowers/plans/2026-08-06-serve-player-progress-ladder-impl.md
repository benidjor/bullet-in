# 선수 페이지 진행 단계 사다리 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스펙 `docs/superpowers/specs/2026-08-05-serve-player-progress-ladder-design.md` (PR #227) 의 다섯 변경을 별개 PR 두 개로 구현한다.

**Architecture:** 묶음 1 은 전이형 타임라인 (`stage_timeline`) 을 묶음별 대표 선정 (`stage_ladder`) 으로 바꾸고, 그 선행 작업으로 `SIDEBAR_STAGES` 순서를 화면 순서에 맞춘다.
묶음 2 는 템플릿 · 정적 자산만 건드린다 (제목 · `flatlist` · 10건 더보기).

**Tech Stack:** Python 3.11 · Jinja2 · 순수 CSS/JS (프레임워크 없음) · pytest.

## Global Constraints

- 결정을 다시 열지 않는다 — 스펙 §2 표가 전부 사용자 확정이다.
- 같은 단계 N건 = 그 묶음 전체 건수 (대표 포함) · 2건 이상일 때만 표시.
- 동률이면 오피셜 묶음만 늦은 기사 · 나머지 다섯 묶음은 이른 기사.
- 머리 · 색인 배지는 사다리 맨 윗줄이 아니라 시간축 최신 기사의 단계 (§6.2).
- 단계 값이 틀려 보여도 고치지 않는다 — 재추출 트랙 몫이며 §4.4 표에 그대로 반영돼 있다.
- 내부 tier 숫자는 화면에 내보내지 않는다 — 공신력은 `_reader_tier` 라벨로만.
- 새 CSS 클래스는 `.latest` 계열 (`latestcut` · `dg-extra` · `wcut`) 과 겹치지 않게 둔다.
- 브랜치는 `git fetch origin` 뒤 `origin/main` 에서 딴다 (로컬 main 금지).
- 서브에이전트의 모든 git 명령에 `-C <워크트리>` 를 박는다.
- 커밋 · PR 은 `docs/conventions/2026-06-11-commit-pr-convention.md` — 한국어 제목 · 명사형 불릿 · 실제 작업 모델 트레일러 · Claude 서명 금지.
- serve/ · 정적 자산 · 템플릿은 이 세션 소유다 — 병렬 세션 (알림 · 재추출) 파일은 건드리지 않는다.

## 파일 구조

| PR | 파일 | 책임 |
| --- | --- | --- |
| 1 | `src/bullet_in/transfer_stage.py` | `SIDEBAR_STAGES` 순서 정합 (§4.1) |
| 1 | `src/bullet_in/serve/render.py` | `stage_ladder()` 신설 · `stage_timeline()` 제거 · `build_player_entries` · `render_player` 연결 |
| 1 | `src/bullet_in/serve/templates/player.html.j2` | 노드 줄에 공신력 병기 · `같은 단계 N건` |
| 1 | `tests/test_transfer_stage.py` · `tests/test_serve_players.py` | 순서 테스트 갱신 · 전이 테스트 4개를 사다리 테스트로 대체 |
| 1 | `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` | 개정 표시 (§11) |
| 2 | `src/bullet_in/serve/templates/player.html.j2` | 제목 `진행 단계` · `flatlist` · `pl-extra` 마킹 · 더보기 버튼 |
| 2 | `src/bullet_in/serve/static/style.css` | `.block.pl-extra{display:none}` |
| 2 | `src/bullet_in/serve/static/app.js` | 10건 단위 더보기 · 접기 |
| 2 | `tests/test_serve_players.py` | 더보기 계약 · flatlist · 제목 테스트 |

두 PR 이 겹치는 파일은 `player.html.j2` 하나이고 줄이 겹치지 않는다 (스펙 §3).
PR 1 은 노드 반복 블록, PR 2 는 제목 문자열 · 목록 컨테이너 클래스 · 버튼 줄만 바꾼다.
**PR 1 에서는 구역 제목 `단계 흐름` 을 바꾸지 않는다** — 제목 변경은 묶음 2 소속이다.

---

## PR 1 — 진행 단계 사다리 + 순위 정합 (묶음 1)

브랜치 `feat/serve-progress-ladder` · 워크트리 `.claude/worktrees/feat-serve-progress-ladder`.

### Task 1: SIDEBAR_STAGES 순서 정합

**Files:**
- Modify: `src/bullet_in/transfer_stage.py:13-21`
- Test: `tests/test_transfer_stage.py:4-7`

**Interfaces:**
- Produces: `SIDEBAR_STAGES` 새 순서 (아래 목록 그대로).
집합 · 조회 소비처 (`_LABEL` · `_CSS` · `STAGE_ENUMS` · `VALID_STAGES`) 는 순서 무관이라 영향이 없다 (스펙 §7.1 전수 확인 완료).

- [ ] **Step 1: 순서 테스트를 새 순서로 갱신 (먼저 실패 확인)**

`tests/test_transfer_stage.py` 의 `test_sidebar_stages_order_and_count` 를 다음으로 교체한다.

```python
def test_sidebar_stages_order_and_count():
    # 진행 단계 순 (사다리 스펙 §4.1) — 화면 순서 (render._STAGE_DISPLAY_GROUPS) 가
    # 정답이고, medical 은 협상 중 묶음의 짝이라 negotiating 바로 뒤에 둔다.
    enums = [e for e, _, _ in ts.SIDEBAR_STAGES]
    assert enums == ["official", "agreed", "negotiating", "medical",
                     "personal_terms", "interest", "rumour"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_transfer_stage.py -q`
Expected: `test_sidebar_stages_order_and_count` FAIL (현행 순서는 medical 이 세 번째).

- [ ] **Step 3: SIDEBAR_STAGES 재정렬**

`src/bullet_in/transfer_stage.py` 의 목록을 스펙 §4.1 그대로 바꾼다.

```python
SIDEBAR_STAGES: list[tuple[str, str, str]] = [
    ("official", "오피셜", "s-off"),
    ("agreed", "이적 합의", "s-agree"),
    ("negotiating", "협상 중", "s-talk"),
    ("medical", "메디컬", "s-med"),
    ("personal_terms", "개인 합의", "s-personal"),
    ("interest", "관심", "s-interest"),
    ("rumour", "루머", "s-rum"),
]
```

바로 위 주석 블록의 마지막 문장 뒤에 한 줄을 덧붙인다 (기존 주석은 그대로 둔다).

```python
# 2026-08-06 사다리 스펙 §4.1 로 순서를 화면 묶음 순서에 정합했다 — 사다리가
# 이 순위를 처음으로 실제 동작 (진행 단계 정렬) 에 쓴다.
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_transfer_stage.py -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git -C <워크트리> add src/bullet_in/transfer_stage.py tests/test_transfer_stage.py
git -C <워크트리> commit  # feat(serve): SIDEBAR_STAGES 순서를 화면 묶음 순서에 정합
```

### Task 2: `stage_ladder()` 신설 · `stage_timeline()` 제거

**Files:**
- Modify: `src/bullet_in/serve/render.py:1008-1026` (`stage_timeline` 자리)
- Test: `tests/test_serve_players.py:62-89` (전이 테스트 4개 대체)

**Interfaces:**
- Consumes: `_STAGE_DISPLAY_GROUPS` (render.py:230) · `_stage.is_displayable`.
- Produces: `stage_ladder(entries: list[dict]) -> list[dict]`.
입력은 오래된 것부터 정렬된 `[{"row", "stage"}]` (row 는 `tier` 키를 가진 서빙 행).
출력은 `[{"row", "stage", "count"}]` · 오피셜이 앞.
Task 3 의 `build_player_entries` 와 Task 4 의 `render_player` 가 이 시그니처를 쓴다.

- [ ] **Step 1: 사다리 테스트 작성 (전이 테스트 4개 대체)**

`tests/test_serve_players.py` 에서 `test_stage_timeline_makes_node_only_when_stage_changes` · `test_stage_timeline_skips_other_and_blank` · `test_stage_timeline_keeps_regression_as_its_own_node` · `test_stage_timeline_is_empty_when_no_article_has_a_stage` 네 개와 `_row` 헬퍼를 지우고 다음으로 바꾼다.
import 줄의 `stage_timeline` 도 `stage_ladder` 로 바꾼다.

```python
def _row(day: int, h: str = "h1", tier=2):
    """사다리 판정용 최소 행 — stage_ladder 는 tier 와 입력 순서만 쓴다."""
    return {"content_hash": h, "tier": tier,
            "published_at": datetime(2026, 7, day, 12, 0)}


def test_stage_ladder_one_line_per_group_in_progress_order():
    entries = [{"row": _row(1, "h1"), "stage": "rumour"},
               {"row": _row(2, "h2"), "stage": "rumour"},
               {"row": _row(3, "h3"), "stage": "agreed"}]
    lines = stage_ladder(entries)
    assert [l["stage"] for l in lines] == ["agreed", "rumour"]   # 진행 단계 순 (위가 앞)
    assert [l["count"] for l in lines] == [1, 2]                 # 건수 = 묶음 전체 (대표 포함)


def test_stage_ladder_merges_negotiating_and_medical_into_one_line():
    entries = [{"row": _row(1, "h1", tier=4), "stage": "negotiating"},
               {"row": _row(2, "h2", tier=4), "stage": "medical"}]
    [line] = stage_ladder(entries)
    assert line["row"]["content_hash"] == "h1"   # 동률 → 이른 기사
    assert line["count"] == 2                    # 협상 중 한 줄로 합산


def test_stage_ladder_rep_is_highest_credibility_and_missing_tier_is_lowest():
    entries = [{"row": _row(1, "h1", tier=4), "stage": "agreed"},
               {"row": _row(2, "h2", tier=1), "stage": "agreed"},
               {"row": _row(3, "h3", tier=None), "stage": "agreed"}]
    [line] = stage_ladder(entries)
    assert line["row"]["content_hash"] == "h2"   # tier 작을수록 높음 · 미상 (None) 은 최하
    assert line["count"] == 3


def test_stage_ladder_tie_official_latest_others_earliest():
    # 공홈은 합의 때 · 확정 때 두 번 올린다 — 마지막 공지가 현재 상태다 (스펙 §4.2).
    entries = [{"row": _row(4, "ag1", tier=1), "stage": "agreed"},
               {"row": _row(14, "off1", tier=0), "stage": "official"},
               {"row": _row(14, "ag2", tier=1), "stage": "agreed"},
               {"row": _row(16, "off2", tier=0), "stage": "official"}]
    lines = stage_ladder(entries)
    assert lines[0]["row"]["content_hash"] == "off2"   # 오피셜 — 동률이면 늦은 기사
    assert lines[1]["row"]["content_hash"] == "ag1"    # 나머지 — 동률이면 이른 기사


def test_stage_ladder_skips_other_and_blank():
    entries = [{"row": _row(1, "h1"), "stage": "other"},
               {"row": _row(2, "h2"), "stage": None},
               {"row": _row(3, "h3"), "stage": "agreed"}]
    lines = stage_ladder(entries)
    assert [l["stage"] for l in lines] == ["agreed"]
    assert lines[0]["count"] == 1     # other · 빈 값은 줄도 건수도 만들지 않는다


def test_stage_ladder_is_empty_when_no_article_has_a_stage():
    assert stage_ladder([{"row": _row(1), "stage": "other"}]) == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_players.py -q`
Expected: ImportError (`stage_ladder` 미정의).

- [ ] **Step 3: stage_ladder 구현 · stage_timeline 제거**

`src/bullet_in/serve/render.py` 의 `stage_timeline` 함수 (1008-1026행) 를 다음으로 교체한다.

```python
_STAGE_GROUP_OF = {e: label for label, enums in _STAGE_DISPLAY_GROUPS for e in enums}


def stage_ladder(entries: list[dict]) -> list[dict]:
    """진행 단계 사다리 (사다리 스펙 §4.2) — 표시 묶음 6종마다 대표 기사 하나.

    입력은 오래된 것부터 정렬된 [{"row", "stage"}], 출력은 오피셜이 앞이다.
    대표는 공신력 높은 순 (tier 작을수록 높음 · 미상은 최하 — pick_representative
    의 99.0 선례) 이고, 동률이면 오피셜 묶음만 늦은 기사를 뽑는다 — 공홈은 합의
    때 · 확정 때 두 번 올리므로 마지막 공지가 현재 상태다. 나머지 다섯 묶음은
    이른 기사 (그 단계가 처음 보도된 시점). count 는 묶음 전체 건수 (대표 포함)
    라 머리 · 사이드바 건수와 셈법이 같다. other · 빈 값은 줄도 건수도 없다."""
    buckets: dict[str, list[dict]] = {}
    for e in entries:
        if not _stage.is_displayable(e.get("stage")):
            continue
        buckets.setdefault(_STAGE_GROUP_OF[e["stage"]], []).append(e)

    def cred(e):
        t = e["row"].get("tier")
        return float(t) if t is not None else 99.0

    out = []
    for label, _ in _STAGE_DISPLAY_GROUPS:
        b = buckets.get(label)
        if not b:
            continue
        # 오피셜은 마지막 공지가 현재 상태다 — 뒤집어 넣어 동률에서 늦은 기사가 이기게 한다.
        seq = list(reversed(b)) if label == "오피셜" else b
        rep = min(seq, key=cred)       # 안정 선택 — 동률이면 seq 순서상 첫 기사
        out.append({"row": rep["row"], "stage": rep["stage"], "count": len(b)})
    return out
```

`stage_timeline` 은 이 교체로 완전히 사라진다 (소비처는 `build_player_entries` 와 테스트뿐 — Task 3 에서 함께 전환).

- [ ] **Step 4: 사다리 테스트만 통과 확인**

Run: `uv run pytest tests/test_serve_players.py -q -k stage_ladder`
Expected: 6개 PASS.
`build_player_entries` 계열은 Task 3 전까지 `stage_timeline` 부재로 FAIL 상태여도 된다 — Task 3 과 같은 커밋 흐름 안에서 수렴한다.
단, Step 5 커밋 전에 Task 3 Step 3 까지 끝내 전체 그린을 만든 뒤 커밋해도 좋다 (구현자는 Task 2 · 3 을 한 커밋으로 합쳐도 된다).

- [ ] **Step 5: 커밋은 Task 3 완료 후 함께 한다**

`build_player_entries` 가 `stage_timeline` 을 부르는 중간 상태로 커밋하면 그 커밋이 깨진 트리가 된다.
Task 3 Step 4 의 전체 그린 후에 커밋한다.

### Task 3: build_player_entries 전환 — ladder 키 · 현재 단계 분리

**Files:**
- Modify: `src/bullet_in/serve/render.py:991-1004` (`build_player_entries` 몸통)
- Test: `tests/test_serve_players.py` (timeline 키를 쓰는 기존 테스트 2개 갱신 + §6.2 회귀 테스트 1개 신설)

**Interfaces:**
- Consumes: Task 2 의 `stage_ladder`.
- Produces: entry dict 의 `"ladder"` 키 (`stage_ladder` 출력 그대로) 와 `"stage"` 키 (시간축 최신 표시 단계 · 없으면 None).
`"timeline"` 키는 사라진다.
Task 4 의 `render_player` 가 `entry["ladder"]` 를 읽는다.

- [ ] **Step 1: 기존 테스트 갱신 + §6.2 회귀 테스트 작성**

`test_build_player_entries_header_count_matches_article_list` 의 마지막 단언을 바꾼다.

```python
    assert [l["stage"] for l in e["ladder"]] == ["rumour"]
```

`test_build_player_entries_current_stage_is_latest_node` 를 이름째 교체한다.

```python
def test_build_player_entries_current_stage_is_time_axis_latest():
    arts = [_art("h1", 1, "agreed"), _art("h2", 5, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed"},
                        {"content_hash": "h2", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] == "rumour"          # 역행이어도 시간축 최신값 (사다리 첫 줄 아님)
```

그 아래에 §6.2 회귀 방어를 신설한다.

```python
def test_build_player_entries_stage_ignores_ladder_top_official():
    # §6.2 회귀 방어 — 오피셜 기사가 섞여 있어도 머리 · 색인 배지는 시간축 최신
    # 단계다. 사다리 첫 줄 (오피셜) 을 그대로 읽으면 실측 다섯 명 전부 틀린다.
    arts = [_art("h1", 1, "official"), _art("h2", 5, "interest")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "official"},
                        {"content_hash": "h2", "stage": "interest"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] == "interest"
    assert e["ladder"][0]["stage"] == "official"   # 사다리 자체는 오피셜이 위
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_players.py -q -k build_player_entries`
Expected: FAIL (ladder 키 없음 · stage_timeline 부재).

- [ ] **Step 3: build_player_entries 전환**

`render.py` 의 몸통에서 timeline 세 줄을 다음으로 바꾼다 (독스트링의 "전이 타임라인" 문구도 "진행 단계 사다리" 로 맞춘다).

```python
        paired.sort(key=lambda t: _sort_ts(t[0]))          # 오래된 것부터 (사다리 입력)
        ladder = stage_ladder([{"row": r, "stage": s} for r, s in paired])
```

entry dict 는 다음으로 바꾼다.

```python
        out.append({**p,
                    "name": (p.get("ko_full_name") or p.get("ko_name")
                             or p["full_name"]),
                    "slug": slug,
                    "articles": [r for r, _ in reversed(paired)],
                    "ladder": ladder,
                    # 현재 단계는 시간축 최신값이다 (사다리 스펙 §6.2) — 사다리는
                    # 오피셜이 앞이라 첫 줄을 읽으면 뜻이 "가장 진행된 단계" 로 바뀐다.
                    "stage": next((s for _, s in reversed(paired)
                                   if _stage.is_displayable(s)), None),
                    "count": len(paired),
                    "last_ts": _sort_ts(paired[-1][0])[0]})
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `uv run pytest tests/test_serve_players.py tests/test_transfer_stage.py -q`
Expected: `render_player` 계열 (Task 4 대상) 만 FAIL, 나머지 PASS.
`render_player` 가 아직 `entry["timeline"]` 을 읽으므로 Task 4 까지 끝낸 뒤 커밋한다.

- [ ] **Step 5: 커밋은 Task 4 완료 후 함께 한다**

### Task 4: render_player · 템플릿 — 사다리 줄 (공신력 · 같은 단계 N건)

**Files:**
- Modify: `src/bullet_in/serve/render.py:1044-1063` (`render_player`)
- Modify: `src/bullet_in/serve/templates/player.html.j2:11-24`
- Test: `tests/test_serve_players.py` (`test_render_player_shows_timeline_and_full_list` 대체 + 단건 표시 테스트)

**Interfaces:**
- Consumes: Task 3 의 `entry["ladder"]`.
- Produces: 템플릿 컨텍스트 `nodes` = `[{"a": 장식된 행, "badge": display_stage 결과, "count": int}]`.

- [ ] **Step 1: 렌더 테스트 갱신**

`test_render_player_shows_timeline_and_full_list` 를 다음 둘로 교체한다.

```python
def test_render_player_ladder_line_has_count_and_credibility():
    arts = [_art("h1", 1, "rumour", "촐리스 관심"), _art("h2", 2, "rumour", "촐리스 재보도"),
            _art("h3", 3, None, "촐리스 단계 없음")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": "rumour"},
                        {"content_hash": "h3", "stage": None}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert "기사 3건" in html
    assert "같은 단계 2건" in html            # 묶음 전체 건수 (대표 포함)
    assert "이후 " not in html                 # 전이형 문구 잔존 방지
    assert "공신력 중" in html                 # tier 2 독자 라벨 — tlsrc 에 병기 (§4.3)
    assert "촐리스 단계 없음" in html          # 단계 없는 기사도 목록에


def test_render_player_ladder_hides_count_when_single():
    arts = [_art("h1", 1, "agreed", "촐리스 합의")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert "같은 단계" not in html             # 1건이면 건수 표시 없음 (§4.2)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_players.py -q -k render_player`
Expected: FAIL (`entry["timeline"]` KeyError).

- [ ] **Step 3: render_player · 템플릿 수정**

`render.py` 의 `render_player` 에서 nodes 생성과 독스트링을 바꾼다.

```python
def render_player(entry: dict, sources: dict, now: datetime,
                  directory: dict | None = None,
                  outlet_dir: dict | None = None) -> str:
    """선수 페이지 (스펙 §5) — 머리 · 진행 단계 사다리 · 귀속 기사 전량."""
```

```python
    nodes = [{"a": decorated[n["row"]["content_hash"]],
              "badge": display_stage(n["stage"]), "count": n["count"]}
             for n in entry["ladder"]]
```

`player.html.j2` 의 노드 반복 두 줄을 바꾼다 (구역 제목 `단계 흐름` 은 묶음 2 소속이라 여기서 안 바꾼다).

```html
    <span class="tlsrc">{{ n.a._outlet }}{% if n.a._reader_tier %} · {{ n.a._reader_tier }}{% endif %}</span>
    {% if n.count > 1 %}<span class="tlmore">같은 단계 {{ n.count }}건</span>{% endif %}
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `uv run pytest -q`
Expected: 전부 PASS (통합은 DB/Airflow 없으면 skip).

- [ ] **Step 5: Task 2 · 3 · 4 커밋**

```bash
git -C <워크트리> add src/bullet_in/serve/render.py src/bullet_in/serve/templates/player.html.j2 tests/test_serve_players.py
git -C <워크트리> commit  # feat(serve): 선수 페이지 전이 타임라인을 진행 단계 사다리로 교체
```

### Task 5: 기존 스펙 개정 표시 (§11)

**Files:**
- Modify: `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md`

- [ ] **Step 1: 개정 표시 삽입**

문서 첫머리 (제목 바로 아래) 에 개정 안내를 넣는다.

```markdown
> **개정 (2026-08-06)** — §5.1 의 현재 단계 계산 · §5.2 의 전이형 타임라인 · 단계 역행 조항은
> `docs/superpowers/specs/2026-08-05-serve-player-progress-ladder-design.md` (§4 · §6.2) 로 대체됐다.
> §2 확정 결정 요약 표의 `타임라인` · `단계 역행` 두 줄도 같은 취지로 낡았다.
```

§5.1 의 현재 단계 문장과 §5.2 의 전이형 설명 절 머리에도 각각 한 줄씩 단다.

```markdown
> 개정 (2026-08-06) — 사다리 스펙 §6.2 로 대체 (시간축 최신 기사의 단계 · 뜻은 그대로 · 계산 경로만 분리).
```

```markdown
> 개정 (2026-08-06) — 사다리 스펙 §4 로 대체 (표시 묶음별 대표 한 줄 · `같은 단계 N건` · 진행 단계 순 · 공신력 병기).
```

- [ ] **Step 2: 문서 형식 훅 통과 확인 후 커밋**

```bash
git -C <워크트리> add docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md
git -C <워크트리> commit  # docs(spec): 선수 페이지 재개 설계에 사다리 대체 개정 표시
```

### Task 6: bulletin_mock 렌더 실측 (§8.2) — 컨트롤러 직접 수행

**Files:**
- Create: 스크래치패드 `render_mock.py` (저장소 밖 · 커밋 안 함)

- [ ] **Step 1: 렌더 스크립트 작성**

`docs/runbook/2026-07-26-local-serve-render-verification.md` 의 스크립트를 기반으로 하되, 접속을 `bulletin_mock` 으로 바꾸고 run.py 의 `serving_rows` 필터를 재현한다 (fmkorea 무관 글 제외 — PR #225 이후 렌더 입력 경로).
제외 건수는 로그로 찍되 기대값을 고정하지 않는다 (08-06 실측 11건 · 변동 가능).

- [ ] **Step 2: 워크트리 코드로 렌더 후 §4.4 · §6.2 대조**

- 트로사르 페이지가 §4.4 표와 같은 5줄인지 — 날짜 · 언론사 · 건수까지.
오피셜 줄이 07-16 `이적 확정` · 건수 2, 이적 합의 07-14 BBC 13건, 협상 중 06-13 BBC Football Gossip 2건, 개인 합의 07-05 The Athletic 2건, 루머 07-14 afcstuff 2건, 합 21.
- 기마랑이스 5줄 · 알바레스 3줄 · 로저스 5줄 · 촐리스 5줄.
- 선수 색인 배지가 §6.2 표의 왼쪽 값 그대로인지 — 기마랑이스 관심 · 로저스 관심 · 알바레스 루머 · 트로사르 이적 합의 · 촐리스 이적 합의.
- 안 맞으면 데이터 탓이 아니라 구현이 틀린 것이다 — 단계 값은 이 세션 동안 고정이다.

### Task 7: PR 1 생성

- [ ] **Step 1: push · PR 본문 작성 (7섹션 · humanize fast 점검) · PR 생성**

머지 · VM 반영 · 첫 회차 확인까지가 한 묶음이라는 점을 본문에 적는다.
머지는 사용자가 직접 한다.

---

## PR 2 — 카드 높이 정렬 · 10개 더보기 · 제목 변경 (묶음 2)

브랜치 `feat/serve-player-page-polish` · 워크트리 `.claude/worktrees/feat-serve-player-page-polish`.
`git fetch origin` 뒤 `origin/main` 에서 딴다 — PR 1 브랜치에서 따지 않는다 (독립 머지 가능해야 함).

### Task 8: 제목 변경 + flatlist 부착

**Files:**
- Modify: `src/bullet_in/serve/templates/player.html.j2:12,26`
- Test: `tests/test_serve_players.py`

- [ ] **Step 1: 테스트 작성**

```python
def test_render_player_section_title_and_flatlist():
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert "진행 단계" in html and "단계 흐름" not in html   # 제목 (§5.3)
    assert 'class="daylist plist flatlist"' in html          # 행 높이 정렬 (§5.1)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_players.py -q -k section_title`
Expected: FAIL.

- [ ] **Step 3: 템플릿 두 줄 수정**

`player.html.j2` 12행 `<h2>단계 흐름</h2>` → `<h2>진행 단계</h2>`.
26행 `<div class="daylist plist">` → `<div class="daylist plist flatlist">`.

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `uv run pytest tests/test_serve_players.py -q`

```bash
git -C <워크트리> add src/bullet_in/serve/templates/player.html.j2 tests/test_serve_players.py
git -C <워크트리> commit  # feat(serve): 선수 페이지 제목을 진행 단계로 바꾸고 카드 행 높이 정렬
```

### Task 9: 기사 10건 단위 더보기

**Files:**
- Modify: `src/bullet_in/serve/templates/player.html.j2:26-28`
- Modify: `src/bullet_in/serve/static/style.css` (`.plfold` 규칙 근처)
- Modify: `src/bullet_in/serve/static/app.js` (파일 끝 `.plfold` 배선 다음)
- Test: `tests/test_serve_players.py`

**Interfaces:**
- Produces: DOM 계약 — 서버가 11번째 블록부터 `pl-extra` 클래스 · `id="plMore"` 버튼 (`.latestmore` 재사용).
`.latest` 계열 (`latestcut` · `dg-extra` · `wcut`) 과 겹치지 않는다.
선수 페이지엔 사이드바가 없어 `applyFilters()` 미배선 — 인라인 display 충돌 없음 (스펙 §7.2 · §7.3).

- [ ] **Step 1: 테스트 작성**

```python
def test_render_player_marks_extra_blocks_beyond_ten():
    arts = [_art(f"h{i}", min(i, 28), "rumour", f"기사 {i}") for i in range(1, 13)]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": f"h{i}", "stage": "rumour"}
                        for i in range(1, 13)])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert html.count("pl-extra") == 2                        # 11 · 12번째 블록만
    assert "기사 더보기 · 남은 2건" in html
    assert 'id="plMore"' in html and 'class="latestmore"' in html


def test_render_player_has_no_more_button_at_ten_or_less():
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert "pl-extra" not in html
    assert "plMore" not in html


# pytest 는 브라우저를 띄우지 않으므로 아래 단언은 세 파일이 같은 문자열 계약
# (pl-extra 클래스 · plMore id) 을 공유하는지만 고정한다 (.plfold 계약 테스트와
# 같은 방식) — 클릭 동작 자체는 실브라우저로만 검증된다.
def test_player_more_contract_shared_across_three_files():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    tpl = Path("src/bullet_in/serve/templates/player.html.j2").read_text(encoding="utf-8")
    assert "pl-extra" in js and "plMore" in js
    assert re.search(r"\.block\.pl-extra\s*\{[^}]*display\s*:\s*none", css), (
        ".block.pl-extra{display:none} 규칙이 없음 — 더보기 전에도 전량 노출되는 결함")
    assert "pl-extra" in tpl and 'id="plMore"' in tpl
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_players.py -q -k "more_button or more_contract or extra_blocks"`
Expected: FAIL.

- [ ] **Step 3: 템플릿 · CSS · JS 구현**

`player.html.j2` 목록 블록을 다음으로 바꾼다.

```html
<div class="daylist plist flatlist">
  {% for a in articles %}<div class="block{{ ' pl-extra' if loop.index > 10 }}">{{ card(a, thumb=True, when=a._kdate, show_all=True) }}</div>{% endfor %}
</div>
{% if articles|length > 10 %}<button class="latestmore" id="plMore" type="button">기사 더보기 · 남은 {{ articles|length - 10 }}건</button>{% endif %}
```

`style.css` 의 `.plfold` 규칙 근처에 한 줄을 더한다.

```css
.block.pl-extra{display:none}                   /* 선수 페이지 — 11번째부터 더보기 뒤로 */
```

`app.js` 끝의 `.plfold` 배선 다음에 더한다.

```js
// ── 선수 페이지 — 기사 10건 단위 더보기 · 접기 (사다리 스펙 §5.2) ────
// 서버가 11번째 블록부터 pl-extra 를 붙여 두고, 여기서는 노출 건수 shown 기준으로
// 매번 다시 계산한다. 선수 페이지엔 사이드바가 없어 applyFilters 가 배선되지
// 않으므로 (items.length && side) 인라인 display 와 부딪히지 않는다.
const plList = document.querySelector('.plist');
const plMore = document.getElementById('plMore');
if (plList && plMore) {
  const plBlocks = [...plList.querySelectorAll('.block')];
  const PL_INIT = 10;
  let plShown = PL_INIT;
  const plSync = () => {
    plBlocks.forEach((b, i) => b.classList.toggle('pl-extra', i >= plShown));
    const left = plBlocks.length - plShown;
    plMore.textContent = left > 0 ? `기사 더보기 · 남은 ${left}건` : '접기';
  };
  plMore.onclick = () => {
    if (plShown < plBlocks.length) { plShown += 10; }
    else {
      plShown = PL_INIT;
      plList.previousElementSibling?.scrollIntoView({ behavior: 'smooth', block: 'start' });  // 구역 머리 (sechead)
    }
    plSync();
  };
}
```

- [ ] **Step 4: 전체 테스트 통과 확인 후 커밋**

Run: `uv run pytest -q`

```bash
git -C <워크트리> add src/bullet_in/serve/templates/player.html.j2 src/bullet_in/serve/static/style.css src/bullet_in/serve/static/app.js tests/test_serve_players.py
git -C <워크트리> commit  # feat(serve): 선수 페이지 기사 목록에 10건 단위 더보기
```

### Task 10: bulletin_mock 렌더 실측 (묶음 2) — 컨트롤러 직접 수행

- [ ] **Step 1: 워크트리 코드로 렌더**

Task 6 의 스크립트를 이 워크트리에서 실행한다.

- [ ] **Step 2: 화면 확인**

- 구역 제목이 `진행 단계` 인지 (묶음 2 만 머지된 상태를 가정한 화면 — 내용이 전이형이어도 스펙 §5.3 이 허용).
- 기사 목록이 10건에서 끊기는지 (21건 트로사르 → 초기 10건 · 버튼 `기사 더보기 · 남은 11건`).
- 브라우저에서 더보기 → 20건 → 더보기 → 21건 (버튼 `접기`) → 접기 → 10건 복귀 · 구역 머리 스크롤.
- 카드 구분선이 행 단위로 맞는지 (flatlist).
- JS 콘솔 에러 0.

### Task 11: PR 2 생성

- [ ] **Step 1: push · PR 본문 (7섹션 · humanize fast) · PR 생성**

머지 · VM 반영 · 첫 회차 확인 한 묶음 문구 포함.
자산 (`style.css` · `app.js`) 변경이라 재렌더만으로 반영되지 않는다는 점 (스펙 §8.3) 도 적는다.

---

## 최종 전체 리뷰 (생략 금지)

두 PR 모두 태스크별 리뷰와 별개로, 브랜치 diff 전체를 스펙에 대조하는 최종 리뷰를 한 번씩 돌린다.
계획서 코드의 결함이 구현까지 살아남은 전례 (2026-08-03 · Critical 1 · Important 2) 가 근거다.

## 검증 기대값 (요약)

| 항목 | 기대값 |
| --- | --- |
| 트로사르 사다리 | 5줄 · 오피셜 07-16 이적 확정 (건수 2) · 건수 합 21 |
| 줄 수 | 기마랑이스 5 · 알바레스 3 · 로저스 5 · 촐리스 5 |
| 색인 배지 | 기마랑이스 관심 · 로저스 관심 · 알바레스 루머 · 트로사르 이적 합의 · 촐리스 이적 합의 (§6.2 왼쪽 값 그대로) |
| 단위 테스트 | `uv run pytest -q` 전부 PASS |
