# 홈 시간순 목록 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 홈이 그날 들어온 기사를 빠짐없이 시간순으로 세우고, 같은 소식은 대표 카드 안에 줄로 접어 보여 준다.

**Architecture:** 사건 묶음의 키에 KST 날짜와 표시 단계를 더해 하루 안에서만 묶는다.
접힘이 안 생기므로 접힌 것을 꺼내던 장치 (`promote_recent` 계열) 와 관련 보도 갈래가 통째로 없어진다.
대표는 공신력을 앞세우도록 정렬 축 순서를 바꾼다.

**Tech Stack:** Python 3.11 · Jinja2 템플릿 · 바닐라 JS (`app.js`) · pytest

**Spec:** `docs/superpowers/specs/2026-09-02-home-chronological-design.md`

## Global Constraints

- **테스트** — `uv run --project <워크트리> pytest -q` 가 전량 통과해야 한다 (착수 시점 1517 passed · 1 skipped)
- **파이썬 실행** — 반드시 `uv run --project <워크트리 절대경로>` 로 고정한다
- **커밋** — `<type>(<scope>): 한국어 제목` + 본문 (도입 1 ~ 2문장 + 명사형 불릿) + `Refs:` + 트레일러
   → 트레일러는 `Co-authored-by: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **문서 서식** — `docs/` 아래 `.md` 는 `→` 와 `—` 가 줄 시작에만 오고 한 줄이 한 문장이다
   → 저장 시 `.claude/hooks/check-doc-format.py` 가 자동 검사한다
- **안 건드리는 것** — 1면 (히어로 · 주요 소식) · 가십 절 · 선수 페이지 · 전체 기사 페이지 · 상세 페이지 · 사이드바 계수
- **`config/club_map.yaml` 은 지우지 않는다** — `run.py` 의 번역 · 재작성 경로가 따로 읽는다

---

## 파일 구조

| 파일 | 이 계획에서의 책임 |
| --- | --- |
| `src/bullet_in/serve/render.py` | 묶음 키 · 대표 선정 · 블록 조립 · 죽은 코드 제거 |
| `src/bullet_in/serve/templates/index.html.j2` | 카드 안의 줄과 기준 라벨 마크업 |
| `src/bullet_in/serve/templates/_cards.html.j2` | 줄 하나를 그리는 매크로 |
| `src/bullet_in/serve/static/style.css` | 줄 · 라벨 스타일 |
| `src/bullet_in/serve/static/app.js` | 관련 보도 토글 제거 · 필터가 줄을 다루는 방식 |
| `tests/test_serve_redesign.py` | 묶음 키 · 대표 선정 · 줄 정렬 단위 테스트 |
| `tests/test_serve_render.py` | 템플릿이 줄과 라벨을 그리는지 |

---

### Task 1: 묶음 키에 날짜와 표시 단계를 더한다

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`cluster_events`)
- Test: `tests/test_serve_redesign.py`

**Interfaces:**
- Consumes: `protagonist(title, players)` · `_group_ts(row)` · `to_kst(dt)` · `_STAGE_GROUP_OF`
- Produces: `cluster_events(articles, players) -> list[dict]` · 각 항목이
   `{"key": str|None, "day": date|None, "stage_group": str|None, "articles": list[dict]}`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_serve_redesign.py` 의 `cluster_events` 테스트 뒤에 넣는다.

```python
def _staged(h, day, stage, title, hour=12):
    return _row(content_hash=h, transfer_stage=stage, title_ko=title,
                published_at=datetime(2026, 7, day, hour, 0),
                fetched_at=datetime(2026, 7, day, hour, 0))


def test_cluster_events_splits_by_day():
    # 하루 안에서만 묶는다 — 어제 기사와 오늘 기사는 같은 선수라도 다른 카드다
    a = _staged("a", 20, "interest", "아스날, 로저스 영입 검토")
    b = _staged("b", 21, "interest", "아스날, 로저스 영입 추진")
    out = R.cluster_events([b, a], ["로저스"])
    assert len(out) == 2
    assert {len(c["articles"]) for c in out} == {1, 1}


def test_cluster_events_splits_by_display_stage():
    # 같은 날 같은 선수라도 화면 배지가 다르면 다른 카드다
    a = _staged("a", 20, "interest", "아스날, 로저스 영입 검토", hour=1)
    b = _staged("b", 20, "agreed", "아스날, 로저스 영입 합의", hour=2)
    out = R.cluster_events([b, a], ["로저스"])
    assert len(out) == 2


def test_cluster_events_folds_medical_into_agreed():
    # 표시 묶음으로 묶으므로 메디컬과 이적 합의는 한 카드다 (배지가 같다)
    a = _staged("a", 20, "agreed", "아스날, 로저스 영입 합의", hour=1)
    b = _staged("b", 20, "medical", "로저스, 메디컬 테스트", hour=2)
    out = R.cluster_events([b, a], ["로저스"])
    assert len(out) == 1
    assert out[0]["stage_group"] == "이적 합의"


def test_cluster_events_keeps_unstaged_articles_single():
    # 단계가 기타 · 빈 값이면 묶지 않는다 (카드에서 기본 숨김인 값이다)
    a = _staged("a", 20, "other", "아스날, 로저스 관련 보도", hour=1)
    b = _staged("b", 20, "other", "아스날, 로저스 다른 보도", hour=2)
    out = R.cluster_events([b, a], ["로저스"])
    assert len(out) == 2
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> pytest tests/test_serve_redesign.py -k cluster_events -q`
Expected: FAIL — `test_cluster_events_splits_by_day` 가 `assert 1 == 2` 로 떨어진다 (지금은 날짜 무관으로 한 묶음).

- [ ] **Step 3: 최소 구현**

`cluster_events` 를 통째로 바꾼다.

```python
def cluster_events(articles: list[dict], players: list[str]) -> list[dict]:
    """같은 날 · 같은 선수 · 같은 표시 단계 기사를 한 묶음으로 (2026-09-02 개정).

    그전에는 선수 이름 하나로만 묶고 날짜 경계가 없었다. 그러면 6월 기사와 오늘
    기사가 한 묶음이 되고, 카드는 대표 하나만 서서 그날 들어온 것이 화면에서
    사라진다 (실측 2026-08-28 — 기사 16건에 카드 1장 · 날짜 그룹이 아예 없는 날도
    나흘 있었다).

    단계는 표시 묶음 (_STAGE_GROUP_OF) 을 쓴다 — 화면에 같은 배지가 붙은 것끼리
    묶여야 카드 안이 한 이야기로 읽힌다. 메디컬은 이적 합의로, 개인 합의는
    제안 · 협상으로 접힌다.

    묶지 않는 것은 셋이다 — 주인공을 못 찾은 기사 · 기준 시각이 없는 기사 ·
    단계가 기타이거나 빈 기사. 셋 다 낱개 카드가 된다.

    입력 등장 순서를 보존한다 (호출부가 최신순으로 정렬해 전달)."""
    groups: dict = {}
    order: list = []
    singles: list = []
    for a in articles:
        name = protagonist(a.get("title_ko") or a.get("title_original") or "", players)
        ts = _group_ts(a)
        stage_group = _STAGE_GROUP_OF.get(a.get("transfer_stage") or "")
        if name is None or ts is None or stage_group is None:
            singles.append({"key": name, "day": to_kst(ts).date() if ts else None,
                            "stage_group": stage_group, "articles": [a]})
            continue
        key = (to_kst(ts).date(), name, stage_group)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(a)
    return [{"key": k[1], "day": k[0], "stage_group": k[2], "articles": groups[k]}
            for k in order] + singles
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> pytest tests/test_serve_redesign.py -k cluster_events -q`
Expected: PASS

전체도 돌린다 — 여기서 깨지는 것이 있으면 다음 태스크가 고칠 자리를 알려 주는 것이다.

Run: `uv run --project <워크트리> pytest -q`
Expected: `cluster_events` 를 쓰는 다른 테스트가 몇 개 깨질 수 있다 · **어떤 것이 왜 깨졌는지 적어 두고 넘어간다** (Task 3 에서 함께 고친다).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_redesign.py
git commit -F <메시지 파일>
```

메시지:

```
feat(serve): 사건 묶음을 하루 · 선수 · 표시 단계로 가른다

묶음에 날짜 경계가 없어 옛 기사와 오늘 기사가 한 카드로 합쳐졌다.
그래서 그날 들어온 기사가 대표 하나만 남기고 화면에서 사라졌다.

- **묶음 키** — (KST 날짜, 주인공 선수, 표시 단계 묶음)
- **표시 단계를 쓰는 이유** — 화면에 같은 배지가 붙은 것끼리 묶여야 카드 안이
  한 이야기로 읽힌다 · 메디컬은 이적 합의로 접힌다
- **묶지 않는 셋** — 주인공 미상 · 기준 시각 없음 · 단계가 기타이거나 빈 값
- **테스트 4종** — 날짜로 가름 · 단계로 가름 · 메디컬 접기 · 기타 단계 단독

Refs: docs/superpowers/specs/2026-09-02-home-chronological-design.md
```

---

### Task 2: 대표 선정에서 공신력을 넷째 축으로 올린다

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`pick_representative`)
- Test: `tests/test_serve_redesign.py`

**Interfaces:**
- Consumes: `_arsenal_subject_rank(a)` · `_has_body(a)` · `_sort_ts(row)` · `_LEAD_STAGE_RANK`
- Produces: `pick_representative(articles) -> dict | None` — 시그니처는 그대로다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

기존 `test_pick_representative_*` 뒤에 넣는다.

```python
def test_pick_representative_prefers_credibility_over_recency():
    # 같은 날 같은 단계면 늦게 들어온 낮은 등급보다 공신력이 앞선다 (2026-09-02)
    late_mid = _row(content_hash="late", tier=2.0, body_ko="본문", body_level=1,
                    title_ko="아스날, 포파나 영입 검토",
                    published_at=datetime(2026, 7, 20, 7, 0),
                    fetched_at=datetime(2026, 7, 20, 7, 0))
    early_top = _row(content_hash="early", tier=1.0, body_ko="본문", body_level=1,
                     title_ko="아스날, 포파나 영입 제안받아",
                     published_at=datetime(2026, 7, 20, 1, 38),
                     fetched_at=datetime(2026, 7, 20, 1, 38))
    assert R.pick_representative([late_mid, early_top]) is early_top


def test_pick_representative_recency_still_breaks_a_credibility_tie():
    # 공신력이 같으면 늦은 기사가 이긴다 (기존 성질 유지)
    early = _row(content_hash="e", tier=1.0, body_ko="본문", body_level=1,
                 title_ko="아스날, 포파나 영입 검토",
                 published_at=datetime(2026, 7, 20, 1, 0),
                 fetched_at=datetime(2026, 7, 20, 1, 0))
    late = _row(content_hash="l", tier=1.0, body_ko="본문", body_level=1,
                title_ko="아스날, 포파나 영입 추진",
                published_at=datetime(2026, 7, 20, 9, 0),
                fetched_at=datetime(2026, 7, 20, 9, 0))
    assert R.pick_representative([early, late]) is late
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> pytest tests/test_serve_redesign.py -k pick_representative -q`
Expected: `test_pick_representative_prefers_credibility_over_recency` 만 FAIL
(`assert <late> is <early>`) · 나머지 셋은 PASS.

- [ ] **Step 3: 최소 구현**

`pick_representative` 의 `key` 함수와 독스트링을 바꾼다.

```python
def pick_representative(articles: list[dict]) -> dict | None:
    """묶음 대표 — 구단 공식 → 최하 제외 → 아스날 주어 → 공신력 → 본문 → 최신 → 단계.

    2026-09-02 에 공신력을 넷째로 올렸다. 그전에는 날짜와 시각이 공신력보다 앞이라
    사실상 「가장 최신」 이 대표였다. 그렇게 둔 근거는 「옛 기사가 본문을 갖고 있다고
    최신 소식을 밀어내던 것」 인데, 묶음이 하루 안에서만 만들어지면서 한 묶음의
    기사가 모두 같은 날이 되어 그 위험이 사라졌다.

    날짜 축도 같은 이유로 뺐다 — 비교할 것이 없다.
    이 함수를 부르는 곳은 render_index 하나다 (선수 페이지 사다리는 _rep_key 를 쓴다)."""
    if not articles:
        return None
    has_higher = any(a.get("tier") is not None and float(a["tier"]) < 4.0 for a in articles)

    def key(a):
        tier = a.get("tier")
        tv = float(tier) if tier is not None else 99.0
        official = 1 if tv == 0.0 else 0
        not_lowest = 0 if (has_higher and tv >= 4.0) else 1
        return (official, not_lowest, _arsenal_subject_rank(a), -tv,
                _has_body(a), _sort_ts(a)[0],
                _LEAD_STAGE_RANK.get(a.get("transfer_stage") or "", 0))

    return max(articles, key=key)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> pytest tests/test_serve_redesign.py -k pick_representative -q`
Expected: PASS (4종)

- [ ] **Step 5: 커밋**

```
feat(serve): 묶음 대표에서 공신력을 최신보다 앞에 둔다

대표 정렬 축이 여덟 개인데 공신력이 일곱째라 사실상 가장 최신이 대표였다.
같은 소식을 여러 매체가 보도하면 늦게 들어온 낮은 등급이 카드의 얼굴이 됐다.

- **축 순서** — 구단 공식 · 최하 제외 · 아스날 주어 · 공신력 · 본문 · 최신 · 단계
- **날짜 축 제거** — 묶음이 하루 안에서만 만들어져 한 묶음이 모두 같은 날이다
- **최신을 앞세우던 근거 소멸** — 옛 기사가 최신을 밀어내던 자리가 없어졌다
- **테스트 2종** — 공신력이 최신을 이김 · 공신력 동률이면 최신이 이김

Refs: docs/superpowers/specs/2026-09-02-home-chronological-design.md
```

---

### Task 3: 블록을 대표와 줄로 조립한다

**Files:**
- Modify: `src/bullet_in/serve/render.py:1180-1215` (`render_index` 의 블록 조립)
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: `cluster_events` (Task 1) · `pick_representative` (Task 2) · `_sort_ts`
- Produces: 블록 dict 가 `{"rep", "same", "key", "stage_group", "count", "_articles", "story"}` 를 갖는다
   → `same` 은 대표를 뺀 나머지 기사 리스트 (시각 내림차순)
   → `rel_count` · `branches` · `ending` 키는 더 이상 만들지 않는다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_serve_render.py` 에 넣는다.
이 태스크의 검증은 **접는 버튼이 사라지는 것**이다 — 줄을 그리는 일은 Task 4 가 맡는다.
템플릿의 관련 보도 버튼은 `{% if b.rel_count %}` 안에 있어서, 블록이 그 키를 안 만들면 그려지지 않는다.

```python
def test_home_no_longer_folds_reports_behind_a_button():
    """같은 소식을 버튼 뒤에 접지 않는다 (2026-09-02).

    블록이 rel_count 를 안 만들면 템플릿의 관련 보도 버튼이 그려지지 않는다."""
    rows = [
        _row(content_hash="top", tier=1.0, transfer_stage="interest", body_level=1,
             title_ko="아스날, 말릭 포파나 영입 제안받아", body_ko="아스날 본문",
             published_at=datetime(2026, 6, 29, 1, 38),
             fetched_at=datetime(2026, 6, 29, 1, 38)),
        _row(content_hash="mid", tier=2.0, transfer_stage="interest", body_level=1,
             title_ko="아스날, 말릭 포파나 영입 검토", body_ko="아스날 본문",
             published_at=datetime(2026, 6, 29, 7, 0),
             fetched_at=datetime(2026, 6, 29, 7, 0)),
    ]
    html = render_index(rows, SOURCES, NOW)
    assert "reltoggle" not in html              # 접는 버튼이 없다
    assert 'data-hash="top"' in html            # 공신력 최상이 대표로 선다
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> pytest tests/test_serve_render.py -k no_longer_folds -q`
Expected: FAIL — `assert "reltoggle" not in html` (지금은 블록이 `rel_count` 를 만들어 버튼이 그려진다).

- [ ] **Step 3: 블록 조립을 바꾼다**

`render_index` 안에서 `clusters = ...` 부터 `blocks.extend(lifted)` 까지를 아래로 바꾼다.

```python
    clusters = cluster_events([a for a in rest if not is_lowest(a)], players)
    blocks = []
    for c in clusters:
        rep = pick_representative(c["articles"])
        # 대표를 뺀 나머지가 카드 안의 줄이 된다 (2026-09-02). 접지 않으므로 버튼이
        # 없고, 그날 들어온 기사는 카드나 줄 어느 한쪽에 반드시 한 번 나온다.
        same = [a for a in c["articles"] if a["content_hash"] != rep["content_hash"]]
        same.sort(key=_sort_ts, reverse=True)
        blocks.append({"rep": rep, "same": same, "key": c["key"],
                       "stage_group": c.get("stage_group"),
                       "count": len(c["articles"]), "_articles": list(c["articles"])})
```

이어지는 `for b in blocks: b.setdefault("story", None) ...` 블록은 조건을 단순히 한다.

```python
    for b in blocks:
        b["story"] = None if b.get("band_dup") else (stories or {}).get(b.get("key"))
```

`band_dup` 숨김 카드를 넣는 자리도 새 키에 맞춘다.

```python
    for a in ordered:
        if a["content_hash"] in top_hashes:
            blocks.append({"rep": a, "same": [], "count": 1, "_articles": [a],
                           "band_dup": True, "key": None, "stage_group": None})
```

`pick_empty_day_gossip` 이 만드는 블록도 같은 키로 맞춘다.

```python
        blocks.extend(
            {"rep": a, "same": [], "count": 1, "_articles": [a],
             "promoted": True, "lowsolo": True, "stage_group": None,
             "key": protagonist(a.get("title_ko") or a.get("title_original") or "",
                                players)}
            for a in picked)
```

**`recent_days` · `promote_recent` 호출 두 줄과 `lifted` 를 지운다.**
함수 정의 자체는 Task 6 에서 지운다.

`_same_day_reports` 는 그대로 둔다.
`_articles` 를 세는데 하루 단위 묶음에서는 그것이 곧 「카드 + 줄」 이라 스펙 §3.2 의 셈법과 이미 맞는다.

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> pytest tests/test_serve_render.py -k no_longer_folds -q`
Expected: PASS

Run: `uv run --project <워크트리> pytest -q`
Expected: 승격 · 관련 보도 · 결말 카드를 검사하던 테스트가 여럿 FAIL 한다
— **Task 6 에서 함께 지운다** · 이 시점의 실패 목록을 적어 둔다.

- [ ] **Step 5: 커밋**

```
feat(serve): 블록을 대표와 같은 소식 줄로 조립한다

같은 날 · 같은 선수 · 같은 단계 기사를 한 블록에 담고, 대표를 뺀 나머지를
줄로 쓸 수 있게 담아 둔다. 접는 버튼이 만들어지지 않는다.

- **블록 키** — rep · same (시각 내림차순) · key · stage_group · count
- **없앤 키** — rel_count · branches · ending · 그에 걸려 있던 관련 보도 버튼
- **꺼내기 호출 제거** — promote_recent · recent_days (정의는 Task 6 에서 지운다)
- **보도 건수** — _same_day_reports 가 세는 _articles 가 곧 카드와 줄의 합이다

Refs: docs/superpowers/specs/2026-09-02-home-chronological-design.md
```

---

### Task 4: 카드 안에 줄과 기준 라벨을 그린다

**Files:**
- Modify: `src/bullet_in/serve/templates/_cards.html.j2` (줄 매크로 추가)
- Modify: `src/bullet_in/serve/templates/index.html.j2` (블록 안 마크업)
- Modify: `src/bullet_in/serve/static/style.css`
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: 블록 dict 의 `same` · `key` · `stage_group` (Task 3)
- Produces: `.sameline` 앵커와 `.keyline` 라벨 마크업 · `sameline(a)` 매크로

- [ ] **Step 0: 실패하는 테스트를 쓴다**

```python
def test_home_draws_same_news_as_lines_with_a_key_label():
    """같은 소식은 대표 카드 안에 줄로 그려지고, 무엇으로 묶었는지가 함께 적힌다."""
    rows = [
        _row(content_hash="top", tier=1.0, transfer_stage="interest", body_level=1,
             title_ko="아스날, 말릭 포파나 영입 제안받아", body_ko="아스날 본문",
             published_at=datetime(2026, 6, 29, 1, 38),
             fetched_at=datetime(2026, 6, 29, 1, 38)),
        _row(content_hash="mid", tier=2.0, transfer_stage="interest", body_level=1,
             title_ko="아스날, 말릭 포파나 영입 검토", body_ko="아스날 본문",
             published_at=datetime(2026, 6, 29, 7, 0),
             fetched_at=datetime(2026, 6, 29, 7, 0)),
    ]
    html = render_index(rows, SOURCES, NOW)
    assert 'class="sameline"' in html                 # 나머지가 줄로 그려진다
    assert "아스날, 말릭 포파나 영입 검토" in html         # 줄 제목이 화면에 있다
    assert "보도 2건" in html                          # 건수는 대표를 포함한다


def test_home_omits_the_key_label_on_a_card_that_stands_alone():
    """혼자 선 카드에는 기준 라벨을 안 붙인다 — 설명할 것이 없다."""
    rows = [_row(content_hash="solo", tier=1.0, transfer_stage="interest", body_level=1,
                 title_ko="아스날, 말릭 포파나 영입 검토", body_ko="아스날 본문",
                 published_at=datetime(2026, 6, 29, 1, 38),
                 fetched_at=datetime(2026, 6, 29, 1, 38))]
    html = render_index(rows, SOURCES, NOW)
    assert 'data-hash="solo"' in html
    assert 'class="keyline"' not in html
```

Run: `uv run --project <워크트리> pytest tests/test_serve_render.py -k "same_news_as_lines or stands_alone" -q`
Expected: 첫 테스트 FAIL (`class="sameline"` 이 없다) · 둘째는 PASS (검사가 헛돌지 않는지 확인하는 쪽)

- [ ] **Step 1: 줄 매크로를 만든다**

`_cards.html.j2` 의 `relitem` 매크로를 지우고 그 자리에 넣는다.
필터가 읽는 `data-*` 는 `relitem` 이 갖고 있던 것을 그대로 옮긴다.

```jinja
{% macro sameline(a) %}<a class="sameline" href="{{ root }}article/{{ a.content_hash }}.html"
   data-hash="{{ a.content_hash }}" data-stage="{{ a._stage }}" data-dir="{{ a._dir }}"
   data-tier="{{ a._tier_key }}" data-outlet="{{ a._outlet }}"
   data-journalist="{{ a._journalist }}" data-published="{{ a._published_iso }}"
   data-confidence="{{ a.confidence_score or 0 }}"
   data-text="{{ (a._title ~ ' ' ~ (a.summary_ko or '')) | lower }}"><span class="sm">{{ a._outlet | replace(' (aggregator)', '') }}</span><span class="st">{{ a._title }}</span><span class="sw">{{ a._time }}</span></a>{% endmacro %}
```

- [ ] **Step 2: 홈 템플릿의 블록 안을 바꾼다**

`index.html.j2` 의 `{% from ... import stage_badge, card, relitem %}` 를
`{% from "_cards.html.j2" import stage_badge, card, sameline %}` 로 바꾸고,
`.block` 안의 `blocknav` · `reltoggle` · `related` 를 아래로 대체한다.

```jinja
  <div class="block {{ b.rep._grade }}{{ ' lowsolo' if b.lowsolo }}"{% if b.band_dup %} style="display:none"{% endif %}>
    {{ card(b.rep, thumb=True, cls='dupcard' if b.band_dup else '', hidden=b.band_dup) }}
    {# 같은 날 · 같은 선수 · 같은 단계 보도를 줄로 붙인다 (2026-09-02). 접지 않으므로
       버튼이 없다 — 그날 들어온 기사는 카드나 줄 어느 한쪽에 반드시 한 번 나온다.
       기준 라벨은 줄이 있을 때만 붙는다 · 혼자 선 카드는 지금처럼 깨끗하다. #}
    {% if b.same %}
    <div class="same">
      <div class="keyline"><span class="key">{{ b.key }}{% if b.stage_group %} · {{ b.stage_group }}{% endif %}</span><span class="keyn">보도 {{ b.same|length + 1 }}건</span></div>
      {% for a in b.same %}{{ sameline(a) }}{% endfor %}
    </div>
    {% endif %}
    {% if b.story %}
    <div class="blocknav"><a class="storylink" href="player/{{ b.story.slug }}.html">{{ b.key }} 더보기 · 기사 {{ b.story.count }}건</a></div>
    {% endif %}
  </div>
```

- [ ] **Step 3: 스타일을 더한다**

`style.css` 의 `.reltoggle` · `.related` · `.branchlabel` · `.relitem` 규칙을 지우고 그 자리에 넣는다.

```css
/* 같은 소식 줄 (2026-09-02) — 언론사가 왼쪽 끝에 세로로 맞고 시각은 대표 카드의
   시각과 같은 오른쪽 끝에 온다. 접지 않으므로 토글이 없다. */
.same{margin:5px 12px 2px;padding-top:5px;border-top:1px dotted var(--hair);
  display:flex;flex-direction:column;gap:1px}
.keyline{display:flex;align-items:baseline;gap:8px;font-size:10.5px;
  letter-spacing:.04em;margin-bottom:3px}
.keyline .key{font-weight:700;color:var(--mut)}
.keyline .keyn{margin-left:auto;color:var(--dim);font-variant-numeric:tabular-nums}
.sameline{display:flex;align-items:baseline;gap:8px;font-size:11.5px;
  color:var(--mut);line-height:1.8;min-width:0}
.sameline:hover .st{color:var(--ink)}
.sameline .sm{flex:0 0 84px;font-weight:700;color:var(--ink);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sameline .st{flex:1 1 auto;min-width:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sameline .sw{flex:0 0 auto;font-variant-numeric:tabular-nums;color:var(--dim)}
@media (max-width:720px){.sameline .sm{flex-basis:72px}}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> pytest tests/test_serve_render.py -k "same_news_as_lines or stands_alone" -q`
Expected: PASS (2종)

Run: `uv run --project <워크트리> pytest -q`
Expected: Task 3 에서 적어 둔 실패 목록이 그대로다 — **여기서 새로 늘어나면 안 된다.**
늘었으면 템플릿이 옛 키를 아직 읽고 있는 것이니 그 자리를 먼저 본다.

- [ ] **Step 5: 커밋**

```
feat(serve): 같은 소식을 대표 카드 안의 줄로 그린다

관련 보도를 버튼 뒤에 접어 두던 자리를 카드 안의 줄로 바꿨다.
누르지 않아도 그날 들어온 보도가 전부 화면에 있다.

- **줄 형식** — 언론사가 왼쪽 끝 · 제목 가운데 · 시각은 대표 카드와 같은 오른쪽 끝
- **기준 라벨** — 줄이 있을 때만 붙는다 · 선수 이름 · 단계 · 보도 건수
- **필터용 data 속성** — 옛 관련 보도 항목이 갖던 것을 그대로 옮겼다
- **블록 조립** — 대표를 뺀 나머지를 시각 내림차순으로 담는다

Refs: docs/superpowers/specs/2026-09-02-home-chronological-design.md
```

---

### Task 5: 필터와 계측이 새 줄을 읽게 한다

**Files:**
- Modify: `src/bullet_in/serve/static/app.js`

**Interfaces:**
- Consumes: `.sameline` 앵커의 `data-*` (Task 4)
- Produces: 없음 (브라우저 동작만 바뀐다)

- [ ] **Step 1: 클릭 계측 셀렉터를 고친다**

`app.js:51` 의 셀렉터에서 `a.relitem` 을 `a.sameline` 으로 바꾼다.

```javascript
  const card = e.target.closest?.('a.item, a.sameline, a.mitem, a.pcard, a.tltitle');
```

- [ ] **Step 2: 관련 보도 토글 코드를 지운다**

`relTrim` · `relUntrim` · 갈래를 찾는 함수와 `.reltoggle` 리스너 (대략 `app.js:225-295`) 를 통째로 지운다.
접는 장치가 없어졌으므로 이 코드가 붙을 자리가 없다.

- [ ] **Step 3: 필터가 줄을 다루게 바꾼다**

`app.js:516-552` 의 블록 순회를 아래로 바꾼다.

```javascript
  for (const bl of document.querySelectorAll('.block')) {
    if (bl.querySelector('.dupcard')) continue;
    const cards = [...bl.querySelectorAll('.item')];
    const lines = [...bl.querySelectorAll('.sameline')];
    const lineHits = active ? lines.filter(r => match(r.dataset)) : [];
    const blockHit = cards.some(c => selfHit.get(c)) || lineHits.length > 0;
    shown += cards.filter(c => selfHit.get(c)).length + lineHits.length;
    for (const c of cards) {
      c.style.display = (active ? blockHit : selfHit.get(c)) ? '' : 'none';
      c.classList.toggle('ctxdim', active && blockHit && !selfHit.get(c));
    }
    // 줄은 늘 펴져 있다 — 조건이 걸리면 안 맞는 줄만 감춘다
    for (const r of lines) {
      r.style.display = (!active || lineHits.includes(r)) ? '' : 'none';
    }
    const same = bl.querySelector('.same');
    if (same) same.style.display = (!active || lineHits.length) ? '' : 'none';
  }
```

- [ ] **Step 4: 브라우저로 확인한다**

Task 7 의 렌더 절차로 화면을 띄우고 셋을 눌러 본다.

- 사이드바에서 매체 하나를 고른다 → 안 맞는 줄이 사라지고 맞는 줄만 남는다
- 조건을 지운다 → 줄이 모두 돌아온다
- 줄을 클릭한다 → 그 기사 상세로 간다

- [ ] **Step 5: 커밋**

```
feat(serve): 필터와 계측이 카드 안의 줄을 읽게 한다

관련 보도를 접던 토글이 없어져 그 자리에 붙어 있던 스크립트도 함께 걷어냈다.

- **계측 셀렉터** — a.relitem 을 a.sameline 으로
- **필터** — 조건이 걸리면 안 맞는 줄만 감춘다 · 펴고 접는 처리가 없어졌다
- **삭제** — relTrim · relUntrim · 갈래 탐색 · reltoggle 리스너

Refs: docs/superpowers/specs/2026-09-02-home-chronological-design.md
```

---

### Task 6: 쓰이지 않게 된 코드를 지운다

**Files:**
- Modify: `src/bullet_in/serve/render.py`
- Modify: `tests/test_serve_redesign.py` · `tests/test_serve_render.py`

**Interfaces:**
- Consumes: 없음
- Produces: 없음 (삭제만 한다)

- [ ] **Step 1: 지울 것을 먼저 센다**

지우기 전에 부르는 곳이 정말 없는지 확인한다.

```bash
grep -rn "promote_recent\|recent_days\|_promotable\|_advances_past\|_ladder_rank" src/ | grep -v "^src/bullet_in/serve/render.py:.*def "
grep -rn "related_reports\|branch_views\|ending_card" src/
grep -rn "_is_other_club_report\|club_in_title\|_first_clause\|load_clubs\|_ARSENAL_INBOUND" src/
```

Expected: `render.py` 안의 정의 줄만 나오고 호출부가 없다.
**하나라도 호출부가 남아 있으면 지우지 말고 그 자리를 먼저 본다.**

- [ ] **Step 2: 함수와 상수를 지운다**

`render.py` 에서 아래를 지운다.

- `promote_recent` · `recent_days` · `_promotable` · `PROMOTE_DAYS` · `PROMOTE_PER_PLAYER_DAY`
- `_advances_past` · `_ladder_rank`
- `related_reports` · `branch_views` · `ending_card`
- `_is_other_club_report` · `club_in_title` · `_first_clause` · `_ARSENAL_INBOUND` · `load_clubs`
- `_same_day_reports` 는 **남긴다** · 다만 독스트링에서 「묶음은 날짜 경계가 없어」 를 지운다

`_stage` 임포트가 `_ladder_rank` 때문에만 있었는지 확인하고, 다른 곳에서 쓰면 남긴다.

- [ ] **Step 3: 죽은 테스트를 지운다**

이름으로 찾아 지운다.

```bash
grep -n "def test_.*promote_recent\|def test_.*ending_card\|def test_.*related_reports\|def test_.*branch_views\|def test_.*_is_other_club_report\|def test_.*recent_days" tests/test_serve_redesign.py tests/test_serve_render.py
```

찾은 테스트를 지운다.
**Task 4 Step 4 에서 적어 둔 실패 목록과 대조한다** — 목록에 있는데 여기서 안 걸린 것이 있으면 이름이 다른 것이니 하나씩 본다.

- [ ] **Step 4: 전량 통과를 확인한다**

Run: `uv run --project <워크트리> pytest -q`
Expected: PASS · skip 1 · **실패 0**

- [ ] **Step 5: 커밋**

```
refactor(serve): 접힘이 없어져 쓰이지 않게 된 코드를 걷어낸다

카드가 그날 기사를 다 세우게 되면서 접는 장치와 꺼내는 장치가 함께 필요 없어졌다.

- **꺼내기** — promote_recent · recent_days · _promotable · 상수 둘
- **같은 날 가드 예외** — _advances_past · _ladder_rank
- **관련 보도** — related_reports · branch_views · ending_card
- **딸려 고아가 된 것** — _is_other_club_report · club_in_title · _first_clause ·
  load_clubs · _ARSENAL_INBOUND
- **남긴 것** — config/club_map.yaml (run.py 의 번역 · 재작성이 따로 읽는다)

Refs: docs/superpowers/specs/2026-09-02-home-chronological-design.md
```

---

### Task 7: 운영 데이터로 재고 화면을 눈으로 본다

**Files:**
- Create: `<스크래치패드>/home_diff.py` (저장소에 넣지 않는다)

**Interfaces:**
- Consumes: 앞 여섯 태스크의 결과 전부
- Produces: 검증 결과 · PR 본문에 넣을 수치

- [ ] **Step 1: 터널을 연다**

포트는 이 세션에서 안 쓴 번호로 고른다.

```bash
ssh -i ~/.ssh/seoulnow_deploy -f -N -L 13351:127.0.0.1:3306 ubuntu@155.248.164.17
nc -z 127.0.0.1 13351 && echo "터널 열림"
```

- [ ] **Step 2: 스냅샷을 파일에 고정하고 렌더한다**

런북 `docs/runbook/2026-08-28-rendering-the-home-page-before-you-deploy-it.md` §3 의 인자 구성을 그대로 쓴다.
**행과 기준 시각을 pickle 로 고정한다** — 워치리스트 회차가 3시간마다 행을 더해 두 실행의 대상이 달라진다.
`.env` 는 셸에서 소싱하지 말고 파이썬 안에서 읽어 포트만 바꿔 끼운다.
런북 스니펫의 `assert blank == 0` 을 반드시 넣는다.

- [ ] **Step 3: 날짜별로 센다**

렌더된 `index.html` 과 `all.html` 을 날짜 그룹별로 대조한다.

- 홈의 카드 수 + 줄 수
- 전체 기사 페이지의 그날 기사 수
- 둘이 같아야 한다

**세는 조건 셋을 모두 본다** — 카드의 `display:none` · 블록의 `display:none` · 날짜 그룹의 `latestcut`.
한 층만 보면 늘 더 크게 센다.

- [ ] **Step 4: 기대값과 대 본다**

| 확인할 것 | 기대 |
| --- | --- |
| 9월 1일 카드 | 11장 |
| 9월 1일 카드 + 줄 | 19건 |
| 8월 28일 카드 + 줄 | 그날 기사 16건 |
| 홈에 없던 나흘 | 8월 23 · 24 · 25 · 27일에 날짜 그룹이 생긴다 |
| 어디에도 없는 기사 | 0건 |

**수가 안 맞으면 스펙 §8 의 손계산부터 다시 본다.**
기대값과 결과가 같은 코드에서 나오면 검증이 아니다.

- [ ] **Step 5: 화면을 눈으로 본다**

로컬 http 서버를 띄우고 브라우저로 연다.

- 카드가 시각 내림차순으로 서는가
- 줄의 언론사가 왼쪽 끝에 세로로 맞는가
- 줄의 시각이 대표 카드의 시각과 같은 오른쪽 끝에 오는가
- 기준 라벨이 줄 있는 카드에만 붙는가
- 줄이 많은 카드가 옆 카드보다 지나치게 길어지지 않는가

- [ ] **Step 6: 터널과 서버를 닫는다**

```bash
pkill -f "13351:127.0.0.1:3306"
pkill -f "http.server <포트>"
```

---

## 마치고 나서

- **PR 본문** — 7섹션 한국어 구조 · 게시 전 `.claude/tools/check-pr-format.py --body <파일> --title "<제목>"`
- **문체 점검** — PR 본문은 게시 전에 humanize-korean 을 한 번 통과시킨다
   → 변경 금지 목록에 명사형 종결 · 라벨 불릿 · 수치 · 경로 · 코드 블록을 넣는다
- **머지는 사용자가 한다** — push 와 PR 생성까지만 한다
- **머지 뒤** — VM 반영 · 재렌더 · 배포 · 확인까지 묻지 말고 끝낸다
   → 배포 전에 `systemctl show bullet-in.service -p ActiveState --value` 로 회차 중인지 본다
