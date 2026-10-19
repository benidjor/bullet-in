# 홈 「선수 · 팀 뉴스」 구역 · 「뉴스 종류」 필터 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 홈을 「이적 뉴스」 · 「선수 · 팀 뉴스」 두 구역으로 나누고, 사이드바의 「기타」 칸을 고르면 좁혀지는 「뉴스 종류」 필터로 바꾼다.

**Architecture:** 카드마다 구역 키 `_kind` (`transfer` · `team`) 를 단다 (`render._decorate` · 표시하는 이적 단계 유무).
`render_index` 가 사건 묶음을 대표 카드의 `_kind` 로 두 구역에 나누고, 구역마다 날짜 묶음 · 펼칠 날짜 셋 (`mark_day_cut`) · 오늘 건수를 만든다.
카드의 「기타 숨김」 은 가십에만 남긴다 (`hide_other`).
`app.js` 는 날짜 더보기를 구역마다 따로 달고 (`dayCuts`), 첫 화면 카드 상한 (`data-cap` · `capApply`) 과 「뉴스 종류」 필터 (`data-kind`) 를 더한다.

**Tech Stack:** Python 3.11 · Jinja2 · 바닐라 JS · pytest · Playwright 크로미움 (화면 시험)

**Spec:** `docs/superpowers/specs/2026-10-20-team-news-section-design.md` (#547)

**Dry run:** 2026-10-20 에 이 계획서의 패치를 `origin/main` `834cd1b` 워크트리에 그대로 적용해 전체 테스트를 돌렸다 (DB 없이 기준 1,902 통과 · 87 skip → 1,906 통과 · 87 skip · 새 시험 8 · 옛 정책 시험 4 를 바꿈).
같은 렌더를 크로미움으로 띄워 데스크톱 · 모바일 화면을 한 번 봤다 (시험 데이터 · 운영 데이터 확인은 마무리 단계).
같은 날 코드를 `origin/main` 으로 되돌리고 이 계획서의 패치 블록만 꺼내 `git apply` 로 적용해 같은 수 (1,906 통과 · 87 skip) 를 다시 확인했다.
dry run 은 「도는가」 만 본다.
값이 맞는지는 작업 리뷰가 본다.

## 작업 원칙 (Karpathy 4원칙 · CLAUDE.md 「행동 가이드라인」)

구현 · 리뷰 서브에이전트는 CLAUDE.md 의 4원칙을 지킨다.
특히 아래 둘은 이 계획에서 리뷰가 Important 로 다룬다.

- **요청 밖 변경 금지** — 작업의 Files 목록 밖 파일을 고치거나, 리뷰의 Minor 를 근거로 설계에 없는 동작을 더하지 않는다. 넣을 만하면 보고만 하고 사용자가 정한다.
- **근거 없는 단정 금지** — 보고 · 커밋 · 주석의 숫자와 사실은 실행한 명령이나 읽은 파일에 닿아야 한다. 닿지 않으면 「추정」 이라고 쓴다.

## 가정과 확인

| 가정 | 확인 방법 · 결과 |
| --- | --- |
| 사건 묶음은 단계를 섞지 않는다 | `render.cluster_events` 를 읽음 · 단계 묶음이 없는 기사는 낱개 카드 · 그래서 대표 카드의 `_kind` 로 묶음을 가를 수 있다 |
| 표시하는 단계 집합과 사이드바 단계 집합이 같다 | `transfer_stage.SIDEBAR_STAGES` 가 둘 다의 원천 (`_LABEL` · `stage_counts` 키) · 그래서 `kinds.team` = 지금의 `other` 건수 |
| 위쪽 띠는 공신력 상위 세 등급에서만 고른다 | `render._TOP_TIERS` = 0 · 1 · 1.5 · 화면 시험의 데이터를 2등급으로 둬 띠를 비운다 |
| 상세 페이지는 `facets` 없이 렌더될 수 있다 | `render_article` 의 빈 `facets` 폴백 · 사이드바가 `facets.kinds` 를 읽으므로 폴백에도 `kinds` 를 넣는다 (dry run 첫 실패) |
| 선수 페이지는 모든 귀속 기사를 보인다 | `player.html.j2` 가 `show_all=True` 를 넘겼다 · 숨김 기본값이 사라져 인자가 필요 없다 |
| `bi_filter_apply` 의 `has_other` 를 읽는 곳이 없다 | `src` · `dbt` · `tests` 를 검색해 `app.js` 한 곳뿐 · 창고 (`warehouse.py`) 는 이 기록의 개수와 `n_tier` · `n_journalist` 만 쓰고, 새 값 이름은 `union_by_name` 으로 칸을 늘려 받는다 (자세한 내용은 「알고 두는 한계」) |
| 크로미움으로 `app.js` 를 시험할 수 있다 | `tests/test_filter_autocheck.py` 와 같은 틀 · 로컬 맥에서 dry run 통과 |

## 더 단순한 꼴과 버린 이유

| 더 단순한 꼴 | 버린 이유 |
| --- | --- |
| 상한을 서버에서 박는다 (카드에 `capcut` 클래스) | 정렬 (최신순 · 신뢰도순 · 조회순) 을 바꾸면 앞의 6장이 바뀌는데 서버 표식은 따라가지 못한다 · `app.js` 가 정렬 뒤에 다시 센다 |
| 옛 `latestMore` 함수들을 두고 구역마다 복사 | 두 구역 · 전체 기사 세 목록이 같은 동작이라 하나 (`dayCuts`) 로 묶는 편이 짧다 |
| 「기타」 숨김을 가십에서도 푼다 | 가십 구역은 설계 범위 밖 · 바꾸면 최하 등급 「기타」 가 가십에 새로 나타난다 |
| `facets.other` 를 `kinds` 로 바꿔 지운다 | `tests/test_serve_layout.py` 세 곳이 `other` 를 본다 · 지우면 바뀐 줄이 요청에 닿지 않는다 · 둘을 함께 둔다 |

## Global Constraints

- 파이썬은 워크트리의 3.11 가상환경으로 돌린다 (`uv venv --python 3.11 --project .` 뒤 `uv run --project . --extra dev pytest`) · 워크트리에서 그냥 `uv run` 을 하면 3.14 가상환경이 생긴 일이 있다 (2026-10-20 dry run)
- 전체 테스트는 워크트리 디렉터리에서 돌린다 · 기준 1,902 통과 + 87 skip (DB 없이 · `834cd1b`)
- 구역 키는 `transfer` · `team` · 구역 이름은 「이적 뉴스」 · 「선수 · 팀 뉴스」 (설계 §1.3 · 「선수 · 팀 소식」 아님)
- 첫 화면 카드 상한은 6 (`data-cap="6"`) · 마무리 단계의 화면 확인에서 사용자와 확정한다
- 새 주소 키는 `kind` · 옛 `bucket=other` 는 `kind=team` 으로 읽는다
- 가십 구역 · 선수 페이지 · 기사 상세의 동작은 바꾸지 않는다

## Review Focus

- 날짜 셋을 셀 때 위쪽 띠 기사만 있는 날짜 (`all_dup`) 를 빼는가 (서버 `mark_day_cut` · `app.js` `real`)
- 필터를 걸면 상한이 풀리고, 필터를 풀면 상한이 다시 걸리는가 (`filtering` · `capOff` · `capApply`)
- 「영입 단계」 를 고르면 선수 · 팀 뉴스가 빠지는가 · 「뉴스 종류」 와 다른 필터가 AND 로 묶이는가
- 가십의 「기타」 카드가 필터를 걸지 않은 상태에서 숨은 채인가 (초기화 뒤 포함)

## 알고 두는 한계 (고치지 않음)

- **날짜 머리글 건수** — 「묶음 13개 · 보도 13건」 은 그날 전체이고 상한으로 6장만 보여도 그대로다 · 상한을 풀면 맞는다
- **단계 분류 오류** — 이적 이야기인데 단계가 빠진 기사는 선수 · 팀 뉴스로 간다 (설계 §6 · 안건 「단계분류개선」 에서 고친다)
- **필터 계측 값의 이름이 바뀐다** — 「필터 적용」 을 누르면 `app.js` 가 구글 애널리틱스 (GA4) 에 `bi_filter_apply` 기록을 보내고, 무엇을 골랐는지 값 몇 개를 함께 싣는다.
  그중 「기타」 칸을 켰는지를 뜻하던 `has_other` (1 · 0) 는 칸이 없어져 보낼 것이 없으므로, 「뉴스 종류」 칸을 몇 개 골랐는지를 뜻하는 `n_kind` 로 바꾼다.
  고른 축을 모아 적는 `axes` 값 안의 이름도 `other` 에서 `kind` 로 바뀐다.
  - **깨지는 곳이 없는 이유** — 행동 지표 창고 (`src/bullet_in/warehouse.py`) 가 이 기록에서 쓰는 것은 기록 개수 (316행) 와 `n_tier` · `n_journalist` (369행) 뿐이고 `has_other` 는 읽지 않는다.
    창고는 받은 값의 이름을 그대로 칸으로 펴고 (`flatten_rows` · 141행), 새 이름이 나오면 표에 칸을 자동으로 늘린다 (`union_by_name` · 186 · 892행).
    `src` · `dbt` · `tests` 를 검색해 `has_other` 는 `app.js` 한 곳뿐인 것을 확인했다 (2026-10-20).
  - **남는 일** — 배포 전 기록에는 `has_other`, 배포 뒤 기록에는 `n_kind` 가 남는다.
    필터 사용을 긴 기간으로 분석할 때는 배포일을 기준으로 두 이름을 나눠 읽어야 한다.

### Task 1: 서버 렌더 — 구역 · 날짜 셋 · 건수 · 사이드바

**Files:**
- `src/bullet_in/serve/render.py`
- `src/bullet_in/serve/templates/index.html.j2`
- `src/bullet_in/serve/templates/_cards.html.j2`
- `src/bullet_in/serve/templates/_layout.html.j2`
- `src/bullet_in/serve/templates/player.html.j2`
- `tests/test_serve_render.py`

- [ ] **Step 1: 시험을 먼저 바꾼다** — 옛 정책 시험 셋 (「기타」 숨김 둘 · 「기타」 칸) 을 새 규칙으로 바꾸고, 새 시험 다섯 (구역 배치 · 빈 구역 생략 · 가십 숨김 유지 · 날짜 셋 · 구역별 오늘 건수) 을 더한다. 사이드바 시험은 서버 템플릿을 보므로 이 작업에 둔다 (2026-10-20 구현 때 작업 2 에서 옮김). `test_section_is_named_news_and_counts_are_split` 의 머리글 기대값을 「이적 뉴스」 · 「오늘 1건」 으로, `test_linked_player_badge_and_its_exposure_exception_are_gone` 의 마지막 줄을 「숨지 않음」 으로 바꾼다.

```diff
diff --git a/tests/test_serve_render.py b/tests/test_serve_render.py
index 152014c..72bf45d 100644
--- a/tests/test_serve_render.py
+++ b/tests/test_serve_render.py
@@ -250,19 +250,56 @@ def test_detail_shows_stage_badge():
 
 import re as _re
 
-def test_index_hides_offmission_card_by_default():
+def _section(html, kind):
+    m = _re.search(r'<section class="sect" data-kind="%s">(.*?)</section>' % kind, html, _re.S)
+    return m.group(1) if m else ""
+
+
+def test_index_puts_other_card_in_team_section_and_shows_it():
+    # 설계 2026-10-20 §3.1 — 「기타」 는 숨기지 않고 선수 · 팀 뉴스 구역에 둔다 (#22 정책 폐기)
     tr = _row(content_hash="t", transfer_stage="rumour")
     ot = _row(content_hash="o", transfer_stage="other")
     html = render_index([tr, ot], SOURCES, NOW)
-    o_tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/o\.html"', html).group(0)
-    t_tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/t\.html"', html).group(0)
-    assert "display:none" in o_tag       # off-mission(other) 카드만 숨김
-    assert "display:none" not in t_tag   # 이적 카드(rumour)는 노출
-
-def test_index_still_hides_offmission_card_without_badge():
-    # 회귀 가드 — 배지 없는 기타 글은 그대로 숨김 (PR #22 정책 유지)
-    html = render_index([_row(content_hash="o2", transfer_stage="other")], SOURCES, NOW)
-    tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/o2\.html"', html).group(0)
+    o_tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/o\.html"[^>]*>', html).group(0)
+    assert "display:none" not in o_tag
+    assert 'data-kind="team"' in o_tag
+    assert 'href="article/o.html"' in _section(html, "team")
+    assert 'href="article/t.html"' in _section(html, "transfer")
+    assert 'href="article/o.html"' not in _section(html, "transfer")
+
+
+def test_mark_day_cut_counts_only_days_with_cards():
+    from bullet_in.serve.render import mark_day_cut
+    days = [{"all_dup": False}, {"all_dup": True}, {"all_dup": False},
+            {"all_dup": False}, {"all_dup": False}]
+    assert mark_day_cut(days) is True
+    # 위쪽 띠 기사만 있는 날짜 (all_dup) 는 펼칠 자리를 차지하지 않는다
+    assert [d["extra"] for d in days] == [False, False, False, False, True]
+    assert mark_day_cut([{"all_dup": False}] * 3) is False
+
+
+def test_each_section_counts_its_own_today():
+    t1 = _row(content_hash="t1", transfer_stage="rumour", published_at=datetime(2026, 6, 29, 9))
+    o1 = _row(content_hash="o1", transfer_stage="other", published_at=datetime(2026, 6, 29, 8))
+    o2 = _row(content_hash="o2", transfer_stage="other", published_at=datetime(2026, 6, 29, 7))
+    html = render_index([t1, o1, o2], SOURCES, NOW)
+    assert "오늘 1건" in _section(html, "transfer")
+    assert "오늘 2건" in _section(html, "team")
+
+
+def test_index_skips_a_section_with_no_cards():
+    html = render_index([_row(content_hash="t", transfer_stage="rumour")], SOURCES, NOW)
+    assert 'data-kind="transfer"' in html
+    assert '<section class="sect" data-kind="team">' not in html
+
+
+def test_gossip_still_hides_cards_without_a_stage():
+    # 가십 구역은 이 설계 범위 밖 — 배지 없는 최하 카드는 지금처럼 숨긴다 (hide_other)
+    hi = _row(content_hash="hi", tier=2.0, transfer_stage="agreed", transfer_direction="in",
+              title_ko="아스날, 사카 재계약 합의")
+    lo = _row(content_hash="lo", tier=4.0, transfer_stage="other", title_ko="아스날 훈련장 소식")
+    html = render_index([hi, lo], SOURCES, NOW)
+    tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/lo\.html"', html).group(0)
     assert "display:none" in tag
 
 
@@ -273,11 +310,16 @@ def test_app_js_has_no_badge_exemption_left():
     assert "d.ctx" not in js
 
 
-def test_sidebar_has_other_bucket_checkbox():
-    html = render_index([_row(transfer_stage="other")], SOURCES, NOW)
-    assert 'data-group="bucket"' in html
-    assert 'data-value="other"' in html
-    assert "기타" in html
+def test_sidebar_has_kind_filter_and_no_other_bucket():
+    # 설계 2026-10-20 §4 — 「기타」 칸 대신 「뉴스 종류」 · 영입 단계는 맨 아래
+    html = render_index([_row(content_hash="t", transfer_stage="rumour"),
+                         _row(content_hash="o", transfer_stage="other")], SOURCES, NOW)
+    assert 'data-group="bucket"' not in html
+    assert 'data-group="kind" data-value="transfer"> 이적 뉴스 <span class="ct">1</span>' in html
+    assert 'data-group="kind" data-value="team"> 선수 · 팀 뉴스 <span class="ct">1</span>' in html
+    order = [html.index(f'data-grp="{g}"') for g in ("kind", "tier", "outlet", "journalist", "stage")]
+    assert order == sorted(order)
+    assert "<h4>이적 뉴스 · 영입 단계</h4>" in html
 
 
 def test_app_js_has_other_bucket_toggle_contract():
@@ -939,7 +981,7 @@ def test_linked_player_badge_and_its_exposure_exception_are_gone():
     assert 'class="ctx"' not in html          # 배지 없음
     assert 'data-ctx' not in html             # 필터 표식도 없음
     tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/ob\.html"', html).group(0)
-    assert "display:none" in tag              # 기타라서 숨는다 (예외 없음)
+    assert "display:none" not in tag          # 「기타」 는 이제 선수 · 팀 뉴스 구역에 보인다 (설계 2026-10-20)
 
 
 from bullet_in.serve.render import filter_stage
@@ -1139,11 +1181,11 @@ def test_lowest_stays_in_gossip_when_the_day_already_has_a_card():
 
 
 def test_section_is_named_news_and_counts_are_split():
-    # 「최신 소식」 → 「최신 뉴스」 · 오늘 건수를 뉴스 · 가십으로 갈라 적는다
+    # 「최신 뉴스」 → 「이적 뉴스」 (설계 2026-10-20 §3.4) · 오늘 건수를 구역 · 가십으로 갈라 적는다
     low = _low(content_hash="lo", title_ko="아스날, 사카 이적설 부인")
     html = render_index([low], SOURCES, NOW)
-    assert "<h2>최신 뉴스</h2>" in html
-    assert "오늘 뉴스 1건" in html
+    assert "<h2>이적 뉴스</h2>" in html
+    assert "오늘 1건" in html
     # 오늘치가 전부 최신 뉴스로 올라가 가십 절에 0건이면 링크를 걸지 않는다 (c안)
     assert "gossipjump" not in html
 
```

- [ ] **Step 2: 실패를 확인한다** — `uv run --project . --extra dev pytest -q tests/test_serve_render.py` (새 · 바꾼 시험이 실패)

- [ ] **Step 3: 렌더를 고친다**

```diff
diff --git a/src/bullet_in/serve/render.py b/src/bullet_in/serve/render.py
index 829db7e..23941b8 100644
--- a/src/bullet_in/serve/render.py
+++ b/src/bullet_in/serve/render.py
@@ -141,6 +141,21 @@ def group_blocks_by_day(blocks: list[dict], now: datetime) -> list[dict]:
     return out
 
 
+def mark_day_cut(days: list[dict], n: int = 3) -> bool:
+    """첫 화면에 펼칠 날짜 n개를 정해 각 날짜에 extra 를 단다 (설계 2026-10-20 §3.2).
+
+    카드가 보이는 날짜만 센다 — 위쪽 띠 기사만 있는 날짜 (all_dup) 는 머리글도 카드도
+    숨으므로 펼칠 자리를 차지하지 않는다. 접힌 날짜가 하나라도 있으면 True."""
+    seen = 0
+    for d in days:
+        if d.get("all_dup"):
+            d["extra"] = seen >= n
+            continue
+        seen += 1
+        d["extra"] = seen > n
+    return seen > n
+
+
 def time_in_group(row: dict) -> str:
     """날짜 그룹 안 항목의 시각 표시 (spec1 §6.2 · §12). day 정밀도는 지어내지 않고 빈 문자열."""
     if row.get("published_precision") == "day":
@@ -826,6 +841,8 @@ def facet_counts(articles: list[dict], sources: dict, directory: dict | None = N
     return {"total": len(articles), "team": dict(teams),
             "tiers": tiers, "stage": stage_counts, "stage_groups": stage_groups,
             "other": other_count,
+            # 「뉴스 종류」 필터 건수 (설계 2026-10-20 §4.2) — 선수 · 팀 뉴스는 위 「기타」 와 같은 규칙
+            "kinds": {"transfer": len(articles) - other_count, "team": other_count},
             "outlets": _facet_rows(o_ctr, {}, o_tier),
             "journalists": _facet_rows(j_ctr, j_labels, j_tier,
                                        initial_min=INITIAL_MIN_COUNT, extra=j_extra)}
@@ -1008,6 +1025,8 @@ def _decorate(row: dict, sources: dict, now: datetime,
     # 단계 필터의 in · out 한정 (스펙 §8) 판정 키 — 카드 data-dir 로 나간다
     a["_dir"] = row.get("transfer_direction") or ""
     a["_stage_badge"] = _stage.is_displayable(st)
+    # 홈 구역 · 「뉴스 종류」 필터 키 (설계 2026-10-20 §3.1 · §4.4) — 표시하는 단계가 있으면 이적
+    a["_kind"] = "transfer" if a["_stage_badge"] else "team"
     a["_stage_label"] = _stage.label_for(st)
     a["_stage_class"] = _stage.css_for(st)
     entries = article_journalists(row, sources, directory, outlet_dir)
@@ -1101,8 +1120,6 @@ def render_index(articles: list[dict], sources: dict, now: datetime,
     def _is_today(a):
         ts = _group_ts(a)
         return ts is not None and to_kst(ts).date() == today
-    news_today = len({a["content_hash"] for a in
-                      [b["rep"] for b in blocks if b.get("rep")] + band if _is_today(a)})
     gossip_today = sum(1 for g in gossip if _is_today(g))
 
     # 카드마다 그 선수 페이지로 가는 줄을 단다 (2026-08-28 사용자 확정) — 카드 안의
@@ -1115,15 +1132,27 @@ def render_index(articles: list[dict], sources: dict, now: datetime,
         if a["content_hash"] in top_hashes:
             blocks.append({"rep": a, "same": [], "count": 1, "_articles": [a],
                            "band_dup": True, "key": None, "stage_group": None})
-    day_blocks = group_blocks_by_day(blocks, now)
+    # 두 구역으로 가른다 (설계 2026-10-20 §3.1) — 묶음은 단계를 섞지 않으므로 (cluster_events)
+    # 대표의 단계가 곧 묶음의 단계다. 머리글 「오늘 N건」 은 그 구역 카드 + 위쪽 띠 기사로 센다
+    # — 그전 「오늘 뉴스」 는 숨긴 「기타」 까지 셌다.
+    sections = []
+    for kind, title in (("transfer", "이적 뉴스"), ("team", "선수 · 팀 뉴스")):
+        mine = [b for b in blocks if b["rep"]["_kind"] == kind]
+        days = group_blocks_by_day(mine, now)
+        today_n = len({b["rep"]["content_hash"] for b in mine
+                       if not b.get("band_dup") and _is_today(b["rep"])}
+                      | {a["content_hash"] for a in band if a["_kind"] == kind and _is_today(a)})
+        sections.append({"kind": kind, "title": title, "days": days,
+                         "cut": mark_day_cut(days), "today": today_n,
+                         "hidden_days": sum(1 for d in days if d["extra"] and not d["all_dup"])})
 
     facets = facet_counts(articles, sources, directory=directory, registry=registry,
                           outlet_dir=outlet_dir)
     return _env().get_template("index.html.j2").render(
-        lead=top["lead"], mains=top["mains"], day_blocks=day_blocks,
+        lead=top["lead"], mains=top["mains"], sections=sections,
         gossip=gossip, gossip_hidden=gossip_hidden, gossip_days=GOSSIP_DAYS,
         gossip_shown=len(gossip) - gossip_hidden, gossip_total=len(gossip),
-        news_today=news_today, gossip_today=gossip_today,
+        gossip_today=gossip_today,
         facets=facets, active="home", root="",
         meta=page_meta("Bullet-in · 아스날 이적 뉴스", _SITE_DESC,
                        image=(top["lead"] or {}).get("image_url")))
@@ -1887,7 +1916,8 @@ def render_article(article: dict, neighbors: list[dict], current_hash: str,
     # facets=None이면 빈 구조로 폴백 (하위 호환 유지)
     if facets is None:
         facets = {"team": {}, "tiers": [], "total": 0, "stage": {}, "stage_groups": [],
-                  "other": 0, "outlets": {"initial": [], "stages": []},
+                  "other": 0, "kinds": {"transfer": 0, "team": 0},
+                  "outlets": {"initial": [], "stages": []},
                   "journalists": {"initial": [], "stages": []}}
     article = dict(article)
     paras = [p for p in (article.get("body_ko") or "").split("\n") if p.strip()]
```

- [ ] **Step 4: 템플릿을 고친다** — 홈 두 구역 · 카드의 `hide_other` · `data-kind` · 사이드바 순서 · 선수 페이지 인자

```diff
diff --git a/src/bullet_in/serve/templates/index.html.j2 b/src/bullet_in/serve/templates/index.html.j2
index d40c7a2..7eba794 100644
--- a/src/bullet_in/serve/templates/index.html.j2
+++ b/src/bullet_in/serve/templates/index.html.j2
@@ -33,15 +33,17 @@
 {% endblock %}
 
 {% block content %}
-{# 오늘 들어온 것을 절별로 갈라 적는다 (2026-08-30 사용자 확정) — 가십 절은 본문
-   아래쪽이라 스크롤을 내리기 전엔 오늘 소식이 들어왔는지 알 수 없었다.
-   건수는 「그 절에 실제로 놓인 오늘치」 다 (c안). 가십이 0건이면 줄을 걸지 않는다
-   — 링크가 보이면 반드시 갈 곳이 있어야 한다. #}
-<div class="sechead"><h2>최신 뉴스</h2><span class="secside"><span class="kst">오늘 뉴스 {{ news_today }}건{% if gossip_today %} · <a class="gossipjump" href="#gossip">가십 {{ gossip_today }}건</a>{% endif %} · 시각 KST 기준</span><a class="seclink" href="all.html">전체 기사 보기</a></span></div>
+{# 홈은 두 구역이다 (설계 2026-10-20 §3) — 위 「이적 뉴스」 · 아래 「선수 · 팀 뉴스」.
+   머리글 건수는 「그 구역에 실제로 놓인 오늘치」 다 (2026-08-30 c안을 구역마다).
+   가십 바로가기는 첫 구역 머리글에만 단다 — 가십이 0건이면 걸지 않는다. #}
+{% for s in sections if s.days %}
+<section class="sect" data-kind="{{ s.kind }}">
+<div class="sechead"><h2>{{ s.title }}</h2><span class="secside"><span class="kst">오늘 {{ s.today }}건{% if loop.first and gossip_today %} · <a class="gossipjump" href="#gossip">가십 {{ gossip_today }}건</a>{% endif %}{% if loop.first %} · 시각 KST 기준{% endif %}</span>{% if loop.first %}<a class="seclink" href="all.html">전체 기사 보기</a>{% endif %}</span></div>
 
-<div class="latest{{ ' latestcut' if day_blocks|length > 3 }}">
-{% for day in day_blocks %}
-<div class="daygroup{{ ' dg-extra' if loop.index > 3 }}" data-date="{{ day.date }}">
+{# 첫 화면 카드 상한은 app.js 가 건다 (data-cap · 정렬을 바꿔도 다시 센다). #}
+<div class="latest{{ ' latestcut' if s.cut }}" data-cap="6">
+{% for day in s.days %}
+<div class="daygroup{{ ' dg-extra' if day.extra }}" data-date="{{ day.date }}">
 <div class="daydiv"{% if day.all_dup %} style="display:none"{% endif %}><span class="d">{{ day.label }}</span><span class="c">묶음 {{ day.n }}개 · 보도 {{ day.reports }}건</span></div>
 <div class="daylist">
   {% for b in day.blocks %}
@@ -67,12 +69,15 @@
 </div>
 {% endfor %}
 </div>
-{% if day_blocks|length > 3 %}<button class="latestmore" id="latestMore" type="button">이전 날짜 더보기 · {{ day_blocks|length - 3 }}개 날짜</button>{% endif %}
+<button class="capmore" type="button" hidden></button>
+{% if s.cut %}<button class="latestmore" type="button">이전 날짜 더보기 · {{ s.hidden_days }}개 날짜</button>{% endif %}
+</section>
+{% endfor %}
 
 {% if gossip %}
 <div class="sechead gossiphead" id="gossip"><h2>가십</h2><span class="secside"><span class="kst">최근 {{ gossip_days }}일 {{ gossip_shown }}건 · 전체 {{ gossip_total }}건</span><a class="seclink" href="all.html">전체 기사 보기</a></span></div>
 <div class="gossiplist{{ ' weekcut' if gossip_hidden }}">
-  {% for a in gossip %}{{ card(a, when=a._gwhen, cls='gwk' if a._gwk else '', show_cred=False) }}{% endfor %}
+  {% for a in gossip %}{{ card(a, when=a._gwhen, cls='gwk' if a._gwk else '', show_cred=False, hide_other=True) }}{% endfor %}
 </div>
 {% if gossip_hidden %}<button class="gossipmore" id="gossipMore" type="button">이전 날짜 가십 더보기 · {{ gossip_hidden }}건</button>{% endif %}
 <p class="gossipnote">공신력 최하 보도는 사건 묶음과 상관없이 모두 여기에 모읍니다.</p>
```

```diff
diff --git a/src/bullet_in/serve/templates/_cards.html.j2 b/src/bullet_in/serve/templates/_cards.html.j2
index 4e73698..db41840 100644
--- a/src/bullet_in/serve/templates/_cards.html.j2
+++ b/src/bullet_in/serve/templates/_cards.html.j2
@@ -1,13 +1,11 @@
 {% macro stage_badge(s) %}{% if s %}<span class="stage {{ s.tone }}{{ ' filled' if s.filled }}">{{ s.label }}</span>{% endif %}{% endmacro %}
-{% macro card(a, when=None, cls='', show_cred=True, thumb=False, hidden=False, show_all=False) %}
+{% macro card(a, when=None, cls='', show_cred=True, thumb=False, hidden=False, hide_other=False) %}
 {% set show_thumb = thumb and a.image_url %}
-{# 기타 단계는 기본 숨김 (#22).
-   링크 선수 배지가 붙은 글을 예외로 노출하던 규칙은 2026-08-27 에 배지와 함께
-   걷어냈다 — 배지 없이 예외만 남기면 아스날과 무관한 글이 설명 없이 뜬다.
-   선수 페이지 (show_all) 는 귀속 기사 전량을 보여줘야 해서 이 기본 숨김을 끈다
-   — 머리 건수와 목록 수가 어긋나면 안 되기 때문 (선수 페이지 스펙 §5.3). #}
-<a class="item {{ a._grade }}{{ ' hasthumb' if show_thumb }}{{ ' ' ~ cls if cls }}"{% if hidden or (not show_all and not a._stage_disp) %} style="display:none"{% endif %} href="{{ root }}article/{{ a.content_hash }}.html"
-   data-hash="{{ a.content_hash }}" data-stage="{{ a._stage }}" data-dir="{{ a._dir }}" data-tier="{{ a._tier_key }}"
+{# 단계 배지가 없는 카드 (「기타」) 는 이제 기본으로 보인다 (설계 2026-10-20) — 홈은
+   「선수 · 팀 뉴스」 구역에, 전체 기사는 목록 그대로 둔다. 가십만 지금처럼 숨긴다
+   (hide_other) · 가십 구역은 이 설계의 범위 밖이다. #}
+<a class="item {{ a._grade }}{{ ' hasthumb' if show_thumb }}{{ ' ' ~ cls if cls }}"{% if hidden or (hide_other and not a._stage_disp) %} style="display:none"{% endif %} href="{{ root }}article/{{ a.content_hash }}.html"
+   data-hash="{{ a.content_hash }}" data-stage="{{ a._stage }}" data-kind="{{ a._kind }}" data-dir="{{ a._dir }}" data-tier="{{ a._tier_key }}"
    data-outlet="{{ a._outlet }}" data-journalist="{{ a._journalist }}"
    data-published="{{ a._published_iso }}" data-confidence="{{ a.confidence_score or 0 }}"
    data-text="{{ (a._title ~ ' ' ~ (a.summary_ko or '')) | lower }}">
@@ -22,7 +20,7 @@
 {# 같은 소식 줄 (2026-09-02) — 대표 카드 안에 한 줄씩 붙는다. 필터가 읽는 data-*
    는 옛 관련 보도 항목 (relitem) 이 갖던 것을 그대로 옮긴 것이다. #}
 {% macro sameline(a) %}<a class="sameline" href="{{ root }}article/{{ a.content_hash }}.html"
-   data-hash="{{ a.content_hash }}" data-stage="{{ a._stage }}" data-dir="{{ a._dir }}"
+   data-hash="{{ a.content_hash }}" data-stage="{{ a._stage }}" data-kind="{{ a._kind }}" data-dir="{{ a._dir }}"
    data-tier="{{ a._tier_key }}" data-outlet="{{ a._outlet }}"
    data-journalist="{{ a._journalist }}" data-published="{{ a._published_iso }}"
    data-confidence="{{ a.confidence_score or 0 }}"
```

```diff
diff --git a/src/bullet_in/serve/templates/_layout.html.j2 b/src/bullet_in/serve/templates/_layout.html.j2
index c8d675b..26d01d4 100644
--- a/src/bullet_in/serve/templates/_layout.html.j2
+++ b/src/bullet_in/serve/templates/_layout.html.j2
@@ -106,13 +106,13 @@ gtag('config','{{ ga_id }}');
     <h4>팀</h4>
     <label class="opt"><input type="checkbox" data-group="team" data-value="arsenal" checked> Arsenal <span class="ct">{{ facets.team.get('arsenal', 0) }}</span></label>
 
-    <div class="grp" data-grp="stage">
-      <button class="grphead" type="button"><h4>영입 단계</h4><span class="caret">▾</span></button>
+    {# 「뉴스 종류」 는 홈의 두 구역과 같은 축이다 (설계 2026-10-20 §4) — 옛 「기타」 칸을 대신하고,
+       고르면 좁혀지는 필터다. 공통 필터 (공신력 · 소스 · 기자) 가 그 아래, 「영입 단계」 는 맨 아래. #}
+    <div class="grp" data-grp="kind">
+      <button class="grphead" type="button"><h4>뉴스 종류</h4><span class="caret">▾</span></button>
       <div class="grpbody">
-      {% for sg in facets.stage_groups %}
-      <label class="opt"><input type="checkbox" data-group="stage" data-value="{{ sg.value }}"> {{ sg.label }} <span class="ct">{{ sg.count }}</span></label>
-      {% endfor %}
-      <label class="opt"><input type="checkbox" data-group="bucket" data-value="other"> 기타 <span class="ct">{{ facets.other or 0 }}</span></label>
+      <label class="opt"><input type="checkbox" data-group="kind" data-value="transfer"> 이적 뉴스 <span class="ct">{{ facets.kinds.transfer }}</span></label>
+      <label class="opt"><input type="checkbox" data-group="kind" data-value="team"> 선수 · 팀 뉴스 <span class="ct">{{ facets.kinds.team }}</span></label>
       </div>
     </div>
 
@@ -145,6 +145,15 @@ gtag('config','{{ ga_id }}');
       </div>
     </div>
 
+    <div class="grp" data-grp="stage">
+      <button class="grphead" type="button"><h4>이적 뉴스 · 영입 단계</h4><span class="caret">▾</span></button>
+      <div class="grpbody">
+      {% for sg in facets.stage_groups %}
+      <label class="opt"><input type="checkbox" data-group="stage" data-value="{{ sg.value }}"> {{ sg.label }} <span class="ct">{{ sg.count }}</span></label>
+      {% endfor %}
+      </div>
+    </div>
+
     {# 첫 화면에는 조건이 없다 — 「전체 표시」 라고만 쓰면 무엇이 전체인지 안 보여
        건수를 함께 적는다. 필터를 걸면 app.js 가 「조건 N개 · M건」 으로 바꾼다. #}
     <div class="fstatus" id="fstatus">조건 없음 · 전체 {{ facets.total }}건</div>
```

```diff
diff --git a/src/bullet_in/serve/templates/player.html.j2 b/src/bullet_in/serve/templates/player.html.j2
index 62a0fe7..1a3b519 100644
--- a/src/bullet_in/serve/templates/player.html.j2
+++ b/src/bullet_in/serve/templates/player.html.j2
@@ -25,7 +25,7 @@
 {% endif %}
 <div class="sechead"><h2>기사</h2><span class="kst">{{ e.count }}건</span></div>
 <div class="daylist plist flatlist">
-  {% for a in articles %}<div class="block{{ ' pl-extra' if loop.index > 10 }}">{{ card(a, thumb=True, when=a._kdate, show_all=True) }}</div>{% endfor %}
+  {% for a in articles %}<div class="block{{ ' pl-extra' if loop.index > 10 }}">{{ card(a, thumb=True, when=a._kdate) }}</div>{% endfor %}
 </div>
 {% if articles|length > 10 %}<button class="latestmore" id="plMore" type="button">기사 더보기 · 남은 {{ articles|length - 10 }}건</button>{% endif %}
 {% endblock %}
```

- [ ] **Step 5: 통과를 확인한다** — `uv run --project . --extra dev pytest -q tests/test_serve_render.py tests/test_serve_layout.py tests/test_serve_players.py tests/test_serve_mobile_layout.py`

- [ ] **Step 6: 커밋** — `feat(serve): 홈을 이적 뉴스 · 선수 · 팀 뉴스 두 구역으로 나누고 사이드바에 뉴스 종류 필터`

### Task 2: 화면 동작 — 구역별 더보기 · 첫 화면 상한 · 뉴스 종류 필터

**Files:**
- `src/bullet_in/serve/static/app.js`
- `src/bullet_in/serve/static/style.css`
- `tests/test_team_news_filter.py`
- `tests/test_serve_render.py`

- [ ] **Step 1: 시험을 먼저 쓴다** — 크로미움 시험 (새 파일) 과 `app.js` 계약 시험 (옛 「기타」 계약 둘을 하나로 바꿈)

```diff
diff --git a/tests/test_team_news_filter.py b/tests/test_team_news_filter.py
new file mode 100644
index 0000000..ffebdab
--- /dev/null
+++ b/tests/test_team_news_filter.py
@@ -0,0 +1,96 @@
+"""홈 두 구역 · 「뉴스 종류」 필터 · 첫 화면 상한을 실제 브라우저로 본다 (설계 2026-10-20 §4 · §9.1).
+
+렌더한 홈 · app.js · style.css 를 그대로 띄운다 — 구역 감춤과 상한은 CSS 와 JS 가 함께
+만드는 결과라 문자열 검사로는 못 잰다. 크로미움이 없는 기계에서는 건너뛴다.
+"""
+from datetime import datetime
+from pathlib import Path
+
+import pytest
+
+from bullet_in.serve.render import render_index
+
+STATIC = Path(__file__).resolve().parents[1] / "src" / "bullet_in" / "serve" / "static"
+NOW = datetime(2026, 6, 29, 12, 0, 0)
+SOURCES = {"bbc_sport": {"display_name": "BBC Sport", "serving": "full"}}
+
+
+def _row(h, stage, hour, direction="in"):
+    return dict(content_hash=h, url=f"https://x/{h}", source_id="bbc_sport",
+                title_original=h, title_ko=f"기사 {h}", summary_ko="요약", tier=2,
+                confidence_score=0.5, image_url=None, outlet=None, team="arsenal",
+                transfer_stage=stage, transfer_direction=direction,
+                published_at=datetime(2026, 6, 29, hour, 0, 0))
+
+
+# 모두 공신력 2등급이라 위쪽 띠 (상위 세 등급만 · render._TOP_TIERS) 는 비고,
+# 이적 13건 · 팀 3건이 그대로 두 구역에 놓인다 (같은 날 · 날짜 묶음 하나).
+ROWS = ([_row(f"t{i:02d}", "rumour", 11 - i % 10) for i in range(13)]
+        + [_row(f"o{i}", "other", 1 + i) for i in range(3)])
+
+JS = """async () => {
+  const wait = ms => new Promise(r => setTimeout(r, ms));
+  const vis = el => !!el && getComputedStyle(el).display !== 'none' && el.offsetParent !== null;
+  const sect = k => document.querySelector(`.sect[data-kind="${k}"]`);
+  const cards = k => [...sect(k).querySelectorAll('a.item:not(.dupcard)')].filter(vis).length;
+  const snap = () => ({ transfer: vis(sect('transfer')) ? cards('transfer') : 0,
+                        team: vis(sect('team')) ? cards('team') : 0 });
+  const out = {};
+  out.initial = snap();
+  const cap = sect('transfer').querySelector('.capmore');
+  out.capText = vis(cap) ? cap.textContent : null;
+  cap.click(); await wait(30);
+  out.afterCap = snap();
+  document.querySelector('input[data-group="kind"][data-value="transfer"]').click();
+  document.getElementById('applyBtn').click(); await wait(30);
+  out.kindTransfer = snap();
+  document.getElementById('resetBtn').click(); await wait(30);
+  document.querySelector('input[data-group="stage"][data-value="rumour"]').click();
+  document.getElementById('applyBtn').click(); await wait(30);
+  out.stageRumour = snap();
+  return out;
+}"""
+
+
+@pytest.fixture(scope="module")
+def browser():
+    pw = pytest.importorskip("playwright.sync_api")
+    try:
+        p = pw.sync_playwright().start()
+        b = p.chromium.launch()
+    except Exception as e:                                   # 크로미움 미설치 기계
+        pytest.skip(f"chromium 없음: {e}")
+    yield b
+    b.close()
+    p.stop()
+
+
+def _page(browser, tmp_path, query=""):
+    (tmp_path / "index.html").write_text(render_index(ROWS, SOURCES, NOW), encoding="utf-8")
+    for f in ("app.js", "style.css"):
+        (tmp_path / f).write_text((STATIC / f).read_text(encoding="utf-8"), encoding="utf-8")
+    page = browser.new_page()
+    page.goto((tmp_path / "index.html").as_uri() + query)
+    return page
+
+
+def test_두_구역과_상한과_뉴스_종류_필터(browser, tmp_path):
+    page = _page(browser, tmp_path)
+    r = page.evaluate(JS)
+    page.close()
+    assert r["initial"] == {"transfer": 6, "team": 3}             # 이적 구역은 6장에서 멈춘다
+    assert r["capText"] == "이적 뉴스 더보기 · 7건"
+    assert r["afterCap"] == {"transfer": 13, "team": 3}
+    assert r["kindTransfer"]["team"] == 0                         # 선수 · 팀 뉴스 구역째 감춤
+    assert r["kindTransfer"]["transfer"] > 0
+    assert r["stageRumour"]["team"] == 0                          # 단계를 고르면 단계 없는 기사는 빠진다
+
+
+def test_옛_기타_주소는_선수_팀_뉴스만_보인다(browser, tmp_path):
+    page = _page(browser, tmp_path, "?bucket=other")
+    r = page.evaluate("""() => ({
+      checked: document.querySelector('input[data-group="kind"][data-value="team"]').checked,
+      transfer: getComputedStyle(document.querySelector('.sect[data-kind="transfer"]')).display,
+      team: getComputedStyle(document.querySelector('.sect[data-kind="team"]')).display })""")
+    page.close()
+    assert r == {"checked": True, "transfer": "none", "team": "block"}
```

```diff
diff --git a/tests/test_serve_render.py b/tests/test_serve_render.py
index 72bf45d..9846f84 100644
--- a/tests/test_serve_render.py
+++ b/tests/test_serve_render.py
@@ -322,22 +322,12 @@ def test_sidebar_has_kind_filter_and_no_other_bucket():
     assert "<h4>이적 뉴스 · 영입 단계</h4>" in html
 
 
-def test_app_js_has_other_bucket_toggle_contract():
+def test_app_js_reads_kind_and_drops_the_other_bucket():
+    # 설계 2026-10-20 §4.2 · §4.3 — 「기타」 칸 · 「좁히면 기타도 연다」 예외를 걷고 뉴스 종류로 거른다
     js = (STATIC / "app.js").read_text(encoding="utf-8")
-    assert "bucket" in js              # '기타' 토글 셀렉터
-    assert "showOther" in js            # other 노출 분기
-
-
-def test_app_js_opens_other_when_narrowed_by_outlet_journalist_or_tier():
-    """사이드바 건수에는 기타 기사가 들어 있는데 기타 토글 말고는 열 수단이 없었다.
-
-    언론사 · 기자 · 공신력으로 좁히면 기타도 함께 열어야 건수와 목록이 맞는다
-    (사이드바 계수 설계 §5.1). 공신력 축이 이 예외에서 빠져 있어 사이드바 숫자와
-    필터 결과가 갈렸다 (2026-08-28 실측 — 「최상 94」 를 눌러도 91건).
-    """
-    js = (STATIC / "app.js").read_text(encoding="utf-8")
-    assert "const narrowed = srcActive || tiers.length > 0;" in js
-    assert "isOther ? (showOther || (narrowed && stageEnums.size === 0))" in js
+    assert "showOther" not in js and "narrowed" not in js
+    assert "const okKind = kinds.length === 0 || kinds.includes(d.kind);" in js
+    assert "p.getAll('bucket').includes('other')" in js      # 옛 주소는 선수 · 팀 뉴스로 읽는다
 
 
 def test_index_footer_does_not_link_to_ops_page():
```

- [ ] **Step 2: 실패를 확인한다** — `uv run --project . --extra dev pytest -q tests/test_team_news_filter.py tests/test_serve_render.py -k "kind or 구역 or 주소"`

- [ ] **Step 3: `app.js` 를 고친다**

```diff
diff --git a/src/bullet_in/serve/static/app.js b/src/bullet_in/serve/static/app.js
index 155d200..fb4c0c0 100644
--- a/src/bullet_in/serve/static/app.js
+++ b/src/bullet_in/serve/static/app.js
@@ -2,7 +2,7 @@
 // DOM 계약: a.item[data-hash][data-stage][data-dir][data-tier][data-outlet][data-journalist][data-published][data-confidence][data-text]
 //   data-journalist 는 공저 저자 전원을 '|' 로 이은 다중 값이다 (단독 기사면 값 하나).
 //           사이드바 옵션 input[data-group][data-value][data-tier]
-// URL 계약: ?outlet=&journalist=&tier=&stage=&bucket=other&sort=confidence|views&q=  (다중 선택은 키 반복)
+// URL 계약: ?outlet=&journalist=&tier=&stage=&kind=transfer|team&sort=confidence|views&q=  (다중 선택은 키 반복 · 옛 bucket=other 는 kind=team 으로 읽음)
 // 결합 규칙 (§8): (소스 OR 기자) AND 공신력 AND 영입 단계 AND 검색어
 
 // ── 계측 (공개 준비 2026-08-23) ─────────────────────────────────────
@@ -285,53 +285,103 @@ if (gossipMore) gossipMore.onclick = () =>
   gossipHiddenCount() ? gossipReveal() : gossipCollapse();
 if (gossipMore) gossipSync();
 
-// ── 최신 소식 · 전체 기사 — 주 단위 더보기 · 접기 (spec §4) ─────────
-const latestWrap = document.querySelector('.latest');
-const latestMore = document.getElementById('latestMore');
-const dayGroups = latestWrap ? [...latestWrap.querySelectorAll('.daygroup')] : [];
-const LATEST_INIT = 3;
-function latestHiddenCount() {
-  if (latestWrap?.classList.contains('latestcut'))
-    return dayGroups.filter(g => g.classList.contains('dg-extra')).length;
-  return dayGroups.filter(g => g.classList.contains('wcut')).length;
-}
-function latestSync() {
-  if (!latestMore) return;
-  const n = latestHiddenCount();
-  latestMore.textContent = n
-    ? (latestWrap.classList.contains('latestcut')
-        ? `이전 날짜 더보기 · ${n}개 날짜` : `이전 7일 더보기 · ${n}개 날짜`)
-    : '접기';
-}
-function latestReveal() {
-  const hidden = dayGroups.filter(g => latestWrap.classList.contains('latestcut')
-    ? g.classList.contains('dg-extra') : g.classList.contains('wcut'));
-  if (!hidden.length) return;
-  const anchor = new Date(hidden[0].dataset.date);          // 가장 최신의 숨은 그룹부터 7일 창
-  anchor.setDate(anchor.getDate() - 6);
-  if (latestWrap.classList.contains('latestcut')) {
-    latestWrap.classList.remove('latestcut');
-    dayGroups.forEach((g, i) => { if (i >= LATEST_INIT) g.classList.add('wcut'); });
+// ── 최신 소식 · 전체 기사 — 날짜 더보기 · 접기 (spec §4) ──────────────
+// 홈은 구역이 둘이라 (설계 2026-10-20 §3) 날짜 목록 (.latest) 마다 따로 단다. 버튼은
+// 그 목록 뒤 형제 가운데 처음 만나는 것이다 (다음 .latest 앞까지만 본다).
+const nextSib = (el, cls) => {
+  for (let n = el.nextElementSibling; n && !n.classList.contains('latest'); n = n.nextElementSibling)
+    if (n.classList.contains(cls)) return n;
+  return null;
+};
+const dayCuts = [...document.querySelectorAll('.latest')].map(wrap => {
+  const more = nextSib(wrap, 'latestmore');
+  const groups = [...wrap.querySelectorAll('.daygroup')];
+  // 위쪽 띠 기사만 있는 날짜는 머리글도 숨으므로 세지 않는다 (render.mark_day_cut 과 같은 규칙)
+  const real = g => g.querySelector('.item:not(.dupcard)');
+  const hiddenCount = () => wrap.classList.contains('latestcut')
+    ? groups.filter(g => g.classList.contains('dg-extra') && real(g)).length
+    : groups.filter(g => g.classList.contains('wcut') && real(g)).length;
+  const sync = () => {
+    if (!more) return;
+    const n = hiddenCount();
+    more.textContent = n
+      ? (wrap.classList.contains('latestcut') ? `이전 날짜 더보기 · ${n}개 날짜` : `이전 7일 더보기 · ${n}개 날짜`)
+      : '접기';
+  };
+  const reveal = () => {
+    const hidden = groups.filter(g => wrap.classList.contains('latestcut')
+      ? g.classList.contains('dg-extra') : g.classList.contains('wcut'));
+    if (!hidden.length) return;
+    const anchor = new Date(hidden[0].dataset.date);          // 가장 최신의 숨은 그룹부터 7일 창
+    anchor.setDate(anchor.getDate() - 6);
+    if (wrap.classList.contains('latestcut')) {
+      wrap.classList.remove('latestcut');
+      groups.forEach(g => { if (g.classList.contains('dg-extra')) g.classList.add('wcut'); });
+    }
+    groups.forEach(g => { if (new Date(g.dataset.date) >= anchor) g.classList.remove('wcut'); });
+    sync();
+  };
+  const collapse = () => {
+    groups.forEach(g => g.classList.remove('wcut'));
+    wrap.classList.add('latestcut');
+    sync();
+    wrap.previousElementSibling?.scrollIntoView({ behavior: 'smooth', block: 'start' });  // 구역 상단 (sechead) 보정
+  };
+  if (more) more.onclick = () => hiddenCount() ? reveal() : collapse();
+  sync();
+  return {
+    expand() {                                             // 필터 활성 시 전체 전개 (기존 계약)
+      wrap.classList.remove('latestcut');
+      groups.forEach(g => g.classList.remove('wcut'));
+      if (more) more.hidden = true;
+    },
+    restore() { if (more) { more.hidden = false; sync(); } },
+  };
+});
+const expandLatest = () => dayCuts.forEach(c => c.expand());
+
+// ── 첫 화면 카드 상한 (설계 2026-10-20 §3.2) ───────────────────────
+// 펼친 날짜 안의 카드를 data-cap 장까지만 보이고 나머지는 「…더보기」 버튼 뒤로 둔다.
+// 상한을 풀어야 「이전 날짜 더보기」 가 나온다. 정렬 · 필터 해제 뒤에 다시 센다.
+const capWraps = [...document.querySelectorAll('.latest[data-cap]')];
+const shownBlocks = (scope) => [...scope.querySelectorAll('.block')]
+  .filter(b => b.style.display !== 'none' && !b.querySelector('.dupcard'));
+function capApply(wrap) {
+  const cap = parseInt(wrap.dataset.cap, 10);
+  const btn = nextSib(wrap, 'capmore');
+  const more = nextSib(wrap, 'latestmore');
+  wrap.querySelectorAll('.capcut').forEach(e => e.classList.remove('capcut'));
+  if (!btn || wrap.dataset.capOff) {
+    wrap.classList.remove('capon');
+    if (btn) btn.hidden = true;
+    return;
   }
-  dayGroups.forEach(g => { if (new Date(g.dataset.date) >= anchor) g.classList.remove('wcut'); });
-  latestSync();
-}
-function latestCollapse() {
-  dayGroups.forEach(g => g.classList.remove('wcut'));
-  latestWrap.classList.add('latestcut');
-  latestSync();
-  latestWrap.previousElementSibling?.scrollIntoView({ behavior: 'smooth', block: 'start' });  // 구역 상단 (sechead) 보정
+  const open = [...wrap.querySelectorAll('.daygroup:not(.dg-extra)')];
+  const rest = open.flatMap(g => shownBlocks(g)).slice(cap);
+  rest.forEach(b => b.classList.add('capcut'));
+  open.forEach(g => {
+    const bl = shownBlocks(g);
+    if (bl.length && bl.every(b => b.classList.contains('capcut'))) g.classList.add('capcut');
+  });
+  wrap.classList.toggle('capon', rest.length > 0);
+  btn.hidden = rest.length === 0;
+  if (more && rest.length) more.hidden = true;
+  const title = wrap.closest('.sect')?.querySelector('.sechead h2')?.textContent || '';
+  btn.textContent = `${title} 더보기 · ${rest.length}건`;
+  btn.onclick = () => {
+    wrap.dataset.capOff = '1';
+    capApply(wrap);
+    if (more) more.hidden = false;
+  };
 }
-function expandLatest() {                                  // 필터 활성 시 전체 전개 (기존 계약)
-  latestWrap?.classList.remove('latestcut');
-  dayGroups.forEach(g => g.classList.remove('wcut'));
-  if (latestMore) latestMore.hidden = true;
+let filtering = false;                                     // 필터가 걸려 있으면 상한을 걸지 않는다
+function capOff(wrap) {                                    // 필터 활성 — 상한 없이 전부
+  wrap.classList.remove('capon');
+  const btn = nextSib(wrap, 'capmore');
+  if (btn) btn.hidden = true;
 }
-if (latestMore) latestMore.onclick = () =>
-  latestHiddenCount() ? latestReveal() : latestCollapse();
-if (latestMore) latestSync();
 
-const URL_GROUPS = ['outlet', 'journalist', 'tier', 'stage', 'bucket'];
+const URL_GROUPS = ['outlet', 'journalist', 'tier', 'stage', 'kind'];
 const box = (g) => [...side.querySelectorAll(`input[data-group="${g}"]`)];
 const boxesOf = (g) => box(g).filter(c => !c.disabled);
 const checkedVals = (g) => boxesOf(g).filter(c => c.checked).map(c => c.dataset.value);
@@ -378,15 +428,15 @@ function trackFilterApply() {
   const journalists = checkedVals('journalist');
   const tiers = checkedVals('tier').filter(v => v !== 'all');
   const stages = checkedVals('stage');
-  const other = boxesOf('bucket').some(c => c.checked);
+  const kinds = checkedVals('kind');
   track('bi_filter_apply', {
     n_outlet: outlets.length, n_journalist: journalists.length,
     n_tier: tiers.length, n_stage: stages.length,
-    has_other: other ? 1 : 0, has_query: q ? 1 : 0,
+    n_kind: kinds.length, has_query: q ? 1 : 0,
     // 어느 축을 실제로 쓰는지 한 칸에 모아 둔다 — 조합을 세기 쉽게
     axes: [outlets.length && 'outlet', journalists.length && 'journalist',
            tiers.length && 'tier', stages.length && 'stage',
-           other && 'other', q && 'query'].filter(Boolean).join('+') || '(none)',
+           kinds.length && 'kind', q && 'query'].filter(Boolean).join('+') || '(none)',
   });
 }
 
@@ -401,20 +451,20 @@ function applyFilters() {
   const tiers = checkedVals('tier').filter(v => v !== 'all');
   const stageSel = checkedVals('stage');                 // 각 값은 콤마로 이은 enum 집합
   const stageEnums = new Set(stageSel.flatMap(v => v.split(',')));
-  const showOther = boxesOf('bucket').some(c => c.checked);
+  const kinds = checkedVals('kind');                     // 뉴스 종류 (설계 2026-10-20 §4.2)
   // 공신력을 고르면 그 등급의 소스 · 기자가 자동으로 체크되는데 (UI 스펙 07-21 §7.2) 그 체크는
   // 「무엇이 들어가는지 보여 주는 출발점」 이지 조건이 아니다. 조건으로 세면 등급은 최상인데
   // 체크된 기자가 없는 기사 (기자 미상 · 미등재 공저) 가 빠져 사이드바 건수 (125) 와 결과 (123) 가
   // 갈린다 (2026-09-19 실측). 사용자가 소스 · 기자를 직접 손댔을 때만 조건이 된다.
   const srcActive = userTouchedSrc && (outlets.length || journalists.length);
   const conds = (userTouchedSrc ? outlets.length + journalists.length : 0) + tiers.length
-    + stageSel.length + (showOther ? 1 : 0) + (q ? 1 : 0);
+    + stageSel.length + kinds.length + (q ? 1 : 0);
   const active = conds > 0;
   if (active) {
     expandGossip();                                      // 필터가 걸리면 가십 전체를 대상으로
     expandLatest();                                       // 이전 날짜 그룹도 필터 대상으로 편다
   } else {
-    if (latestMore) { latestMore.hidden = false; latestSync(); }
+    dayCuts.forEach(c => c.restore());
     if (gossipMore) { gossipMore.hidden = false; gossipSync(); }
   }
 
@@ -426,23 +476,18 @@ function applyFilters() {
       // 걸리면 참 (render.article_journalists 와 같은 계약).
       || (d.journalist || '').split('|').some(j => journalists.includes(j));
     const okTier = tiers.length === 0 || tiers.includes(d.tier);
-    // 링크 선수 배지 (data-ctx) 예외는 2026-08-27 에 배지와 함께 걷어냈다 —
-    // 서버 렌더 (_cards.html.j2) 와 같은 규칙을 여기서도 쓴다.
-    const isOther = (!d.stage || d.stage === 'other');
     // 단계 필터는 방향 in·out (아스날 주체) 한정 — 타 구단 딜 (none) 은 필터 체크 시
-    // 제외되고, 필터가 없을 때의 노출 · 기타 토글 분모는 그대로다 (단계 재정의 스펙 §8).
-    // 무산 (collapsed) 은 방향을 보지 않는다 (§8 개정) — 잔류 확정 · 재계약 체결이
-    // 방향 none 이라 걸러지면 무산 필터가 제 내용물을 잃는다. render.in_stage_filter 와 같은 규칙.
+    // 제외된다 (단계 재정의 스펙 §8). 무산 (collapsed) 은 방향을 보지 않는다 (§8 개정)
+    // — 잔류 확정 · 재계약 체결이 방향 none 이라 걸러지면 무산 필터가 제 내용물을 잃는다.
+    // render.in_stage_filter 와 같은 규칙.
     const dirOk = d.stage === 'collapsed' || d.dir === 'in' || d.dir === 'out';
-    // 언론사 · 기자 · 공신력으로 좁히면 기타도 함께 연다 — 사이드바가 적어 둔 건수에는
-    // 기타 기사가 들어 있는데 기타 토글 말고는 그것을 열 수단이 없었다 (사이드바 계수
-    // 설계 §5.1). 공신력 축은 그 예외에서 빠져 있어 사이드바 숫자와 필터 결과가 갈렸다
-    // (2026-08-28 실측 — 「최상 94」 를 누르면 91건 · 그 차이의 일부가 기타 6건이다).
-    // 단계를 함께 고른 경우는 그대로 뺀다 — 기타는 어느 단계에도 안 속한다.
-    const narrowed = srcActive || tiers.length > 0;
-    const okStage = isOther ? (showOther || (narrowed && stageEnums.size === 0))
+    // 단계가 없는 선수 · 팀 뉴스는 어느 단계에도 속하지 않는다 — 단계를 고르면 빠진다.
+    // 옛 「기타」 칸과 「좁히면 기타도 연다」 예외는 걷었다 (설계 2026-10-20 §4.3) — 선수 ·
+    // 팀 뉴스가 늘 보이므로 둘 다 할 일이 없다.
+    const okStage = d.kind === 'team' ? stageEnums.size === 0
       : (stageEnums.size === 0 || (stageEnums.has(d.stage) && dirOk));
-    return okText && okSrc && okTier && okStage;
+    const okKind = kinds.length === 0 || kinds.includes(d.kind);
+    return okText && okSrc && okTier && okStage && okKind;
   };
 
   let shown = 0;
@@ -455,8 +500,10 @@ function applyFilters() {
       it.style.display = vis ? '' : 'none';
       if (vis) shown++;
     } else if (!it.closest('.block')) {                  // 가십 등 낱개 카드
-      it.style.display = m ? '' : 'none';
-      if (m) shown++;
+      // 가십 구역은 이 설계 범위 밖 — 조건이 없을 때는 서버 렌더처럼 배지 없는 카드를 숨긴다
+      const vis = m && (active || it.dataset.kind !== 'team');
+      it.style.display = vis ? '' : 'none';
+      if (vis) shown++;
     }
   }
   for (const bl of document.querySelectorAll('.block')) {
@@ -482,6 +529,8 @@ function applyFilters() {
   if (bandwrap) bandwrap.style.display = active ? 'none' : '';
   sortBlocks();
   hideEmpty();
+  filtering = active;
+  capWraps.forEach(active ? capOff : capApply);
 
   const touched = userTouchedSrc ? ' · 직접 고름' : '';
   if (fstatus) fstatus.textContent = active
@@ -506,6 +555,11 @@ function soloWidth(list) {
 }
 
 function hideEmpty() {
+  // 구역 — 보이는 카드가 없으면 머리글 · 버튼까지 감춘다 (뉴스 종류 · 영입 단계 필터)
+  document.querySelectorAll('.sect').forEach(sec => {
+    const vis = [...sec.querySelectorAll('.item')].some(i => i.style.display !== 'none');
+    sec.style.display = vis ? '' : 'none';
+  });
   // 사건 블록 — 보이는 카드가 없으면 블록째 숨김
   document.querySelectorAll('.block').forEach(bl => {
     const vis = [...bl.querySelectorAll('.item')].some(i => i.style.display !== 'none');
@@ -562,7 +616,9 @@ function restoreFromQuery() {
   if (![...p.keys()].length) return false;
   const want = {};
   for (const g of URL_GROUPS) want[g] = p.getAll(g);
-  boxesOf('outlet').concat(boxesOf('journalist'), boxesOf('stage'), boxesOf('bucket'))
+  // 옛 「기타」 칸 주소 (?bucket=other) 는 「선수 · 팀 뉴스」 로 읽는다 (설계 2026-10-20 §4.3)
+  if (p.getAll('bucket').includes('other') && !want.kind.includes('team')) want.kind.push('team');
+  boxesOf('outlet').concat(boxesOf('journalist'), boxesOf('stage'), boxesOf('kind'))
     .forEach(c => { c.checked = want[c.dataset.group].includes(c.dataset.value); });
   // 주소에 적힌 소스 · 기자는 사용자가 고른 것이다 — 자동 체크와 구분해 조건으로 센다
   userTouchedSrc = want.outlet.length > 0 || want.journalist.length > 0;
@@ -577,7 +633,7 @@ function restoreFromQuery() {
 
 // ── 배선 ──────────────────────────────────────────────────────────
 function resetAll() {
-  boxesOf('outlet').concat(boxesOf('journalist'), boxesOf('stage'), boxesOf('bucket'))
+  boxesOf('outlet').concat(boxesOf('journalist'), boxesOf('stage'), boxesOf('kind'))
     .forEach(c => { c.checked = false; c.closest('.opt').classList.remove('auto'); });
   box('tier').forEach(c => { c.checked = c.dataset.value === 'all'; });
   box('team').forEach(c => { c.checked = c.dataset.value === 'arsenal'; });
@@ -605,7 +661,8 @@ if (items.length && side) {                               // 인덱스
   });
   if (applyBtn) applyBtn.onclick = () => { trackFilterApply(); applyFilters(); };
   if (resetBtn) resetBtn.onclick = () => { resetAll(); applyFilters(); };
-  if (sortSel) sortSel.onchange = () => { sortBlocks(); const qs = filterParams().toString();
+  if (sortSel) sortSel.onchange = () => { sortBlocks(); if (!filtering) capWraps.forEach(capApply);
+    const qs = filterParams().toString();
     history.replaceState(null, '', qs ? `?${qs}` : location.pathname); };
   if (searchInput) {
     // 입력할 때마다 목록이 튀지 않게 — 엔터 · 돋보기 버튼 · 「필터 적용」 에서만 반영한다.
@@ -623,7 +680,7 @@ if (items.length && side) {                               // 인덱스
     });
   }
   if (restoreFromQuery()) applyFilters();
-  else { sortBlocks(); hideEmpty(); }
+  else { sortBlocks(); hideEmpty(); capWraps.forEach(capApply); }
 } else if (side) {                                         // 상세 — 필터는 인덱스로 이동
   const indexHref = document.querySelector('.logo')?.getAttribute('href') || 'index.html';
   side.addEventListener('change', (e) => {
```

- [ ] **Step 4: 스타일을 더한다**

```diff
diff --git a/src/bullet_in/serve/static/style.css b/src/bullet_in/serve/static/style.css
index f873432..d0c0e65 100644
--- a/src/bullet_in/serve/static/style.css
+++ b/src/bullet_in/serve/static/style.css
@@ -232,6 +232,7 @@ html[data-theme="dark"] .ic-moon{display:none} html[data-theme="dark"] .ic-sun{d
 .seclink:hover{background:var(--red);color:#fff}
 .latest.latestcut .daygroup.dg-extra{display:none}   /* 최근 3일 그룹만 초기 노출 (7) */
 .daygroup.wcut{display:none}                     /* 주 단위 더보기 — JS 가 관리 */
+.latest.capon .block.capcut,.latest.capon .daygroup.capcut{display:none}   /* 첫 화면 카드 상한 (설계 2026-10-20 §3.2) — JS 관리 */
 
 /* 목록은 썸네일 칸을 두지 않는다 — 회색 상자 반복 방지 (spec2 §8, 밴드만 썸네일 유지) */
 .item{display:block;padding:11px 12px}
@@ -296,11 +297,11 @@ html[data-theme="dark"] .ic-moon{display:none} html[data-theme="dark"] .ic-sun{d
 .gossiplist .item{padding:10px 0 12px}
 .gossiplist.weekcut .item.gwk{display:none}      /* 초기 7일 컷 (서버 표식) */
 .gossiplist .item.wcut{display:none}              /* 주 단위 더보기 — JS 관리 */
-.gossipmore,.latestmore{display:block;width:100%;margin:14px 0 0;padding:10px;border:1px solid var(--hair);
+.gossipmore,.latestmore,.capmore{display:block;width:100%;margin:14px 0 0;padding:10px;border:1px solid var(--hair);
   border-radius:2px;background:none;color:var(--mut);font:inherit;font-size:13px;font-weight:600;cursor:pointer}
-.gossipmore:hover,.latestmore:hover{color:var(--ink);border-color:var(--mut)}
-.gossipmore[hidden],.latestmore[hidden]{display:none}
-.latestmore{margin:18px 0 0}
+.gossipmore:hover,.latestmore:hover,.capmore:hover{color:var(--ink);border-color:var(--mut)}
+.gossipmore[hidden],.latestmore[hidden],.capmore[hidden]{display:none}
+.latestmore,.capmore{margin:18px 0 0}
 .gossipnote{font-size:12px;color:var(--dim);margin:12px 0 0}
 /* 카드 상단 줄 (§ 리뷰) — 영입 단계 · 언론사 · 공신력 왼쪽, 시각 오른쪽 */
 .cardhead{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin:0 0 5px;font-size:12px}
```

- [ ] **Step 5: 통과를 확인한다** — `uv run --project . --extra dev pytest -q tests/test_team_news_filter.py tests/test_filter_autocheck.py tests/test_serve_render.py`

- [ ] **Step 6: 커밋** — `feat(serve): 구역마다 날짜 더보기 · 첫 화면 카드 상한 · 뉴스 종류 필터 · 옛 기타 주소 호환`

### Task 3: 문서 — README · 지난 설계의 틀린 문장

**Files:**
- `README.md`
- `docs/superpowers/specs/2026-10-07-offseason-collection-scope-design.md`

- [ ] **Step 1: 고친다**

```diff
diff --git a/README.md b/README.md
index 510ffae..4c76908 100644
--- a/README.md
+++ b/README.md
@@ -12,7 +12,7 @@
 ![Bullet-in 홈 (실데이터)](docs/assets/home-page-live.png)
 
 > 방문자가 처음 보는 홈 화면입니다.
-> 대표 기사와 주요 소식을 신문 레이아웃으로 배치하고, 그 아래에 최신 뉴스와 가십을 나눠 싣습니다.
+> 대표 기사와 주요 소식을 신문 레이아웃으로 배치하고, 그 아래에 이적 뉴스 · 선수 · 팀 뉴스 · 가십을 나눠 싣습니다.
 > 제목은 모두 원문을 한국어로 옮긴 것이며 매체명과 공신력 등급을 함께 표시합니다.
 
 ![Bullet-in 기사 상세 (실데이터)](docs/assets/article-detail-live.png)
@@ -111,7 +111,7 @@ systemd 는 파이프라인 외부의 부가 작업만 담당합니다: 선수 
 ![전체 기사 화면 (실데이터)](docs/assets/serving-page-live.png)
 
 > 전체 기사 화면 (`all.html`) 입니다.
-> 날짜별 시간순으로 정렬하고, 왼쪽 레일에서 영입 단계 · 공신력 · 소스 · 기자로 범위를 좁힐 수 있습니다.
+> 날짜별 시간순으로 정렬하고, 왼쪽 레일에서 뉴스 종류 · 공신력 · 소스 · 기자 · 영입 단계로 범위를 좁힐 수 있습니다.
 > facet 옆의 숫자는 현재 적재된 기사가 각 갈래에 몇 건씩 있는지 보여 줍니다.
 
 - **데이터 품질 게이트**: 실행 마지막 단계의 dbt 테스트 22종이 배포를 차단합니다 ([§6.1](#61-dbt-게이트)).
```

```diff
diff --git a/docs/superpowers/specs/2026-10-07-offseason-collection-scope-design.md b/docs/superpowers/specs/2026-10-07-offseason-collection-scope-design.md
index 347fdc1..f1fd1b0 100644
--- a/docs/superpowers/specs/2026-10-07-offseason-collection-scope-design.md
+++ b/docs/superpowers/specs/2026-10-07-offseason-collection-scope-design.md
@@ -163,7 +163,9 @@ DB 오류로 명단을 못 읽으면 이름 갈래만 빠진 채 나머지 갈
 
 후보 조건 · 같은 사건 중복 제거 · 주요 소식을 최신순으로 다시 세우는 것은 그대로다.
 최신 뉴스 목록 · 사이드바 필터 · 가십 절도 바꾸지 않는다.
-새로 받는 기사는 이적 단계 분류에서 대부분 「기타」 가 되어 최신 뉴스에 배지 없이 섞여 나온다.
+새로 받는 기사는 이적 단계 분류에서 대부분 「기타」 가 된다.
+이 문단은 처음에 「최신 뉴스에 배지 없이 섞여 나온다」 고 적었지만, 실제로는 「기타」 카드가 최신 뉴스에서 기본으로 숨어 화면에 거의 나오지 않았다 (2026-10-12 배포 뒤 확인).
+이 기사들을 보여 줄 자리는 설계 `2026-10-20-team-news-section-design.md` (홈의 「선수 · 팀 뉴스」 구역) 가 정한다.
 
 ## 5. 기록 — 무엇을 받고 무엇을 버렸나
 
```

- [ ] **Step 2: 서식 검사** — `python3 .claude/hooks/check-doc-format.py docs/superpowers/specs/2026-10-07-offseason-collection-scope-design.md`

- [ ] **Step 3: 커밋** — `docs: README 홈 · 전체 기사 설명을 두 구역 · 뉴스 종류 필터에 맞추고 비수기 설계의 틀린 문장 정정`

## 마무리 (컨트롤러가 직접)

1. **전체 테스트** — 로컬 MariaDB · Mongo 를 띄워 (`docker compose up -d`) 전체를 돌리고 수를 적는다 · 끝나면 컨테이너를 멈춘다
2. **운영 사본 화면 확인** — `docs/runbook/2026-08-11-premerge-screen-check-with-prod-copy.md` 로 지금 시점과 이적시장 마감 무렵 (2026-09-02 까지 적재된 기사 · 그날을 「오늘」) 을 데스크톱 · 모바일로 렌더해 본다 · 상한 6장을 사용자와 확정한다
3. **범위 검사** — `python3 .claude/tools/check-plan-scope.py --plan docs/superpowers/plans/2026-10-20-team-news-section.md`
4. **최종 리뷰** — 브랜치 전체를 Fable 로 본다
5. **PR** — 본문 검사기 · 문체 점검 · 게시 뒤 본문 재확인
6. **배포 뒤 확인** — 설계 §9.3 (첫 실행에서 두 구역 배치 · 필터 조합 · 옛 주소 · 전체 기사)
