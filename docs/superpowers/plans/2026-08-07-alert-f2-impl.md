# 알림 트랙 (F-2) 구현 계획 — 실패 유닛 특정 · 신선도 정비 · 채택 누락 관측

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스펙 `docs/superpowers/specs/2026-08-07-alert-f2-unit-attribution-and-observability-design.md` (PR #235) 의 확정 결정 4건을 PR 2건 (infra · 알림) 으로 구현한다.

**Architecture:** infra 는 systemd 템플릿 유닛 전환 (Python 무변경), 알림은 notify 문구 · quality 판정 · adapter 관측 속성 · run 배선의 기존 4층 구조를 그대로 따른다.

**Tech Stack:** systemd 템플릿 유닛 · Python 3.11 · pytest (respx 모킹) · uv

## Global Constraints

- 수집 동작 무변경 — adapter 는 관측용 속성만 추가하고 RawItem 산출 · 필터 판단을 바꾸지 않는다 (스펙 §3.3).
- 알림 문구는 원인 추정 금지 · 내부 용어 금지 (스펙 §3.2 · §3.3 — 워치리스트 · 슬라이스 · 커서 등 사용자에게 안 통하는 말 금지).
- 커밋은 `<type>(<scope>): 한국어 제목` + 본문 + 트레일러 `Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>` (실제 작업 모델로 교체 — 컨벤션 §1.3).
- 브랜치는 `git fetch origin` 후 `origin/main` 에서 딴다 (infra 용) — 알림 브랜치 `feat/alert-f2-observability` 는 이미 생성됨.
- docs 산문은 컨벤션 §2.2 서식 (한 줄 = 한 문장 · `·` `+` 여는 괄호 양옆 띄우기 · `→` `—` 줄 시작) — PostToolUse 훅이 자동 검사.
- 테스트 실행은 `uv run pytest -q` (DB · Airflow 없는 로컬에서 통합 테스트는 자동 skip).

---

### Task 1: systemd 템플릿 유닛 전환 (infra PR — 별도 브랜치)

**Files:**
- Create: `infra/systemd/bullet-in-fail-notify@.service`
- Delete: `infra/systemd/bullet-in-fail-notify.service`
- Modify: `infra/systemd/bullet-in.service:5` (OnFailure 줄)
- Modify: `infra/systemd/bullet-in-watchlist.service:5` (OnFailure 줄)
- Modify: `infra/systemd/install-units.sh` (전체 5 ~ 8행)

**Interfaces:**
- Consumes: 없음 (Python 무변경 · 독립 브랜치)
- Produces: OnFailure 인스턴스명 `%n` → 템플릿 `%i` 로 실패 유닛명이 알림 문구에 실림

- [ ] **Step 1: infra 브랜치 생성**

```bash
git fetch origin && git checkout -b infra/fail-notify-unit-attribution origin/main
```

- [ ] **Step 2: 템플릿 유닛 파일 신설**

`infra/systemd/bullet-in-fail-notify@.service` 를 아래 내용으로 만든다.
`%i` 는 systemd 가 인스턴스명 (실패한 유닛의 전체 이름, 예: `bullet-in-watchlist.service`) 으로 치환한다.

```ini
[Unit]
Description=bullet-in unit failure alert (Discord, instance %i)

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/bullet-in
EnvironmentFile=/home/ubuntu/bullet-in/.env
ExecStart=/home/ubuntu/.local/bin/uv run python -c "from bullet_in.notify import send_alert; send_alert('bullet-in 유닛 실패 (systemd)', '%i 실패 — VM 에서 journalctl -u %i -n 100 확인', color=0xE74C3C)"
```

- [ ] **Step 3: 구본 삭제 · OnFailure 교체**

```bash
git rm infra/systemd/bullet-in-fail-notify.service
```

`infra/systemd/bullet-in.service` 와 `infra/systemd/bullet-in-watchlist.service` 의 5행을 각각 교체한다.

```ini
OnFailure=bullet-in-fail-notify@%n.service
```

- [ ] **Step 4: install-units.sh 개정**

파일 전체를 아래로 교체한다 (5종 복사 · 구본 제거 · 두 타이머 enable).

```bash
#!/usr/bin/env bash
# systemd 유닛 설치 · 갱신 — VM 의 저장소에서 실행 (sudo 필요). seoulnow install-units.sh 패턴.
set -euo pipefail
cd "$(dirname "$0")"
sudo cp bullet-in.service bullet-in.timer \
        bullet-in-watchlist.service bullet-in-watchlist.timer \
        bullet-in-fail-notify@.service /etc/systemd/system/
sudo rm -f /etc/systemd/system/bullet-in-fail-notify.service   # 구본 (유닛명 하드코딩) 제거
sudo systemctl daemon-reload
sudo systemctl enable --now bullet-in.timer bullet-in-watchlist.timer
systemctl list-timers 'bullet-in*' --no-pager
```

- [ ] **Step 5: 구문 검증**

```bash
bash -n infra/systemd/install-units.sh && grep -c "OnFailure=bullet-in-fail-notify@%n.service" infra/systemd/bullet-in.service infra/systemd/bullet-in-watchlist.service
```

Expected: 오류 없음 · 두 파일 각각 `1`.

- [ ] **Step 6: 커밋**

```bash
git add -A infra/systemd && git commit -m "infra(systemd): 실패 알림을 템플릿 유닛으로 전환해 실패 유닛명 표기"
```

커밋 본문에 2026-08-06 오진 사례 (워치리스트 실패를 bullet-in.service 로 표기) 와 install-units.sh 의 워치리스트 유닛 누락 보완을 적는다.

### Task 2: 신선도 알림 원인 추정 문구 제거

**Files:**
- Modify: `src/bullet_in/notify.py:152`
- Test: `tests/test_notify.py:241-250`

**Interfaces:**
- Consumes: 없음
- Produces: `build_freshness_alert` 후보 0건 줄 = `"이번 회차 후보 0건"` (다른 알림 · 호출부 변경 없음)

- [ ] **Step 1: 기존 테스트를 새 문구로 갱신 (실패 확인용)**

`tests/test_notify.py` 의 `test_build_freshness_alert_zero_candidates_keeps_hint` (241 ~ 250행) 를 아래로 교체한다.

```python
def test_build_freshness_alert_zero_candidates_keeps_hint():
    # 후보 0건은 관측 사실만 적는다 — 원인 추정 (수집 끊김 의심) 은 스펙
    # 2026-08-07 §3.2 로 제거 (arsenal_official 오진 사례). 힌트 줄은 유지.
    checked, records = _stale_bbc()
    alert = notify.build_freshness_alert(records, 48, sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={}, fetch_errors={})
    field = alert["fields"][0]
    assert "- 이번 회차 후보 0건" in field["value"]
    assert "수집 끊김 의심" not in field["value"]
    assert "- 원인 후보: 셀렉터 드리프트 · 사이트 개편" in field["value"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_notify.py::test_build_freshness_alert_zero_candidates_keeps_hint -q`
Expected: FAIL (`수집 끊김 의심` 이 아직 문구에 있음)

- [ ] **Step 3: notify.py 문구 수정**

`src/bullet_in/notify.py` 152행을 교체한다.

```python
                lines.append("이번 회차 후보 0건")
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_notify.py -q`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/notify.py tests/test_notify.py
git commit -m "fix(notify): 신선도 알림에서 후보 0건 원인 추정 문구 제거"
```

### Task 3: freshness_hours 0 = 신선도 감시 제외 규약

**Files:**
- Modify: `src/bullet_in/quality.py:56-70` (`evaluate_freshness`)
- Modify: `config/sources.yaml:19` (arsenal_official `freshness_hours`)
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: `evaluate_freshness(watermarks, now, default_hours, overrides)` (기존 시그니처 유지)
- Produces: `overrides` 값이 0 이하인 소스는 반환 목록에서 제외 (판정 · 기록 · 알림 모두 대상 아님) — `run.py` 는 무변경

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_quality.py` 에 추가한다 (기존 import 활용 · 파일 상단 import 는 기존 것 유지).

```python
def test_evaluate_freshness_zero_override_excludes_source():
    # freshness_hours: 0 = 감시 제외 (스펙 2026-08-07 §3.2) — 이벤트 구동 소스는
    # 정상 공백 상한이 없어 유한 임계가 성립하지 않는다 (arsenal_official).
    from datetime import datetime, timedelta
    from bullet_in.quality import evaluate_freshness
    now = datetime(2026, 8, 7, 6, 0, 0)
    wm = {"arsenal_official": now - timedelta(hours=360), "bbc_sport": now}
    records = evaluate_freshness(wm, now, 48.0, {"arsenal_official": 0.0})
    assert [r.source_id for r in records] == ["bbc_sport"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_quality.py::test_evaluate_freshness_zero_override_excludes_source -q`
Expected: FAIL (arsenal_official 이 stale 로 포함됨)

- [ ] **Step 3: evaluate_freshness 에 제외 분기 추가**

`src/bullet_in/quality.py` 의 `evaluate_freshness` 루프에서 `thr` 계산 직후에 분기를 넣는다.

```python
    for sid in sorted(watermarks):
        wm = watermarks[sid]
        thr = float(overrides.get(sid, default_hours))
        if thr <= 0:
            continue   # 감시 제외 (freshness_hours: 0) — 이벤트 구동 소스 (스펙 2026-08-07 §3.2)
        if wm is None:
            out.append(SourceFreshness(sid, None, thr, None, False))
            continue
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_quality.py -q`
Expected: PASS (전체)

- [ ] **Step 5: sources.yaml 적용**

`config/sources.yaml` 19행을 교체한다.

```yaml
    freshness_hours: 0     # 신선도 감시 제외 — 이벤트 구동 (1군 발표에만 채택) · 스펙 2026-08-07 §3.2
```

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/quality.py config/sources.yaml tests/test_quality.py
git commit -m "feat(quality): freshness_hours 0 을 신선도 감시 제외로 해석"
```

### Task 4: 채택 누락 관측 알림 (adapter → quality → notify → run)

**Files:**
- Modify: `src/bullet_in/adapters/arsenal_api.py:77,89,111-114,121-122`
- Modify: `src/bullet_in/quality.py` (함수 추가)
- Modify: `src/bullet_in/notify.py` (빌더 추가)
- Modify: `src/bullet_in/run.py:184-189` 직후 (배선)
- Test: `tests/test_arsenal_api_adapter.py` · `tests/test_quality.py` · `tests/test_notify.py`

**Interfaces:**
- Consumes: adapter 의 창 후보 순회 (기존 fetch 루프) · `notify.send_alert`
- Produces:
  - adapter 속성 `men_news_rejects: list[dict]` — 항목 키 `title` · `url` · `published` (ISO 문자열 또는 None) · `taxonomies` (list)
  - `quality.filter_miss_suspects(rejects: list[dict], now: datetime, recent_hours: float = 6.0) -> list[dict]` (now 는 aware UTC)
  - `notify.build_filter_miss_alert(suspects: list[dict], *, run_id: str) -> dict`

- [ ] **Step 1: adapter 실패 테스트 작성**

`tests/test_arsenal_api_adapter.py` 의 `test_taxonomy_filter_rules_via_getarticle` (57 ~ 72행) 끝에 단언을 추가하지 말고, 별도 테스트를 새로 추가한다.

```python
@respx.mock
def test_men_news_rejects_records_unaccepted_men_articles():
    # 관측용: Men + News 인데 채택 안 된 기사만 남긴다 (수집 동작 무변경 · 스펙 §3.3)
    entries = [_sitemap_entry(f"a-{g}") for g in
               ["aOK1ok1ok1ok", "aNO2no2no2no", "aNO3no3no3no", "aNO4no4no4no"]]
    _mock_backend(_sitemap(entries), {
        "aOK1ok1ok1ok": _gql_article("Terms agreed", ["Transfer news", "Men", "News"]),
        "aNO2no2no2no": _gql_article("Women signing", ["Transfer news", "Women", "News"]),
        "aNO3no3no3no": _gql_article("Norgaard joins Everton", ["Men", "News"],
                                     published="2026-08-05T21:09:44.542Z"),
        "aNO4no4no4no": _gql_article("Transfer video", ["Transfer news", "Men", "Video"],
                                     article_type="Video")})
    adapter = ArsenalApiAdapter("arsenal_official", window_hours=24 * 365)
    items = asyncio.run(adapter.fetch())
    assert [i.raw_payload["title"] for i in items] == ["Terms agreed"]
    assert [r["title"] for r in adapter.men_news_rejects] == ["Norgaard joins Everton"]
    r = adapter.men_news_rejects[0]
    assert r["url"].endswith("-aNO3no3no3no")
    assert r["published"] == "2026-08-05T21:09:44.542Z"
    assert r["taxonomies"] == ["Men", "News"]
```

주의: `aNO4` (articleType Video) 는 News 가 아니므로 rejects 에 안 들어가야 한다.
`aNO2` (Women) 는 Men 이 없으므로 제외.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_arsenal_api_adapter.py::test_men_news_rejects_records_unaccepted_men_articles -q`
Expected: FAIL (`men_news_rejects` 속성 없음)

- [ ] **Step 3: adapter 구현**

`src/bullet_in/adapters/arsenal_api.py` 를 세 곳 수정한다.

`__init__` (77행 `self.coverage: dict = {}` 다음):

```python
        self.men_news_rejects: list[dict] = []   # 관측용 — Men + News 인데 비채택 (스펙 2026-08-07 §3.3)
```

`fetch` 시작부 (89행 `men = 0` 다음):

```python
        self.men_news_rejects = []
```

`fetch` 루프의 accept 분기 (111 ~ 114행) 를 아래로 교체한다.

```python
                if "Men" in (art.get("taxonomies") or []):
                    men += 1
                if not _accept(art):
                    tax = art.get("taxonomies") or []
                    if art.get("articleType") == "News" and "Men" in tax:
                        self.men_news_rejects.append({
                            "title": art.get("title"), "url": url,
                            "published": art.get("publicationDate"),
                            "taxonomies": tax})
                    continue
```

- [ ] **Step 4: adapter 테스트 통과 확인**

Run: `uv run pytest tests/test_arsenal_api_adapter.py -q`
Expected: PASS (전체 — 기존 테스트 포함)

- [ ] **Step 5: quality 판정 실패 테스트 작성**

`tests/test_quality.py` 에 추가한다.

```python
def test_filter_miss_suspects_pattern_and_recency():
    # 이적 관련 제목 + 발행 6시간 이내만 — 옛 기사 (lastmod 부활) 와 무관 제목 제외
    from datetime import datetime, timezone
    from bullet_in.quality import filter_miss_suspects
    now = datetime(2026, 8, 6, 0, 0, 0, tzinfo=timezone.utc)
    rejects = [
        {"title": "Christian Norgaard joins Everton", "url": "u1",
         "published": "2026-08-05T21:09:44.542Z", "taxonomies": ["Men", "News"]},
        {"title": "Match Categories", "url": "u2",
         "published": "2026-08-05T22:00:00.000Z", "taxonomies": ["Men", "News"]},
        {"title": "Old signs for Arsenal", "url": "u3",
         "published": "2019-05-20T13:25:27.000Z", "taxonomies": ["Men", "News"]},
        {"title": "Player signs new deal", "url": "u4",
         "published": None, "taxonomies": ["Men", "News"]},
    ]
    assert [s["url"] for s in filter_miss_suspects(rejects, now)] == ["u1"]
```

- [ ] **Step 6: 실패 확인**

Run: `uv run pytest tests/test_quality.py::test_filter_miss_suspects_pattern_and_recency -q`
Expected: FAIL (`filter_miss_suspects` 없음)

- [ ] **Step 7: quality 구현**

`src/bullet_in/quality.py` 상단 import 에 `re` · `timezone` 을 보강하고 파일 끝에 추가한다.

```python
# 이적성 제목 패턴 — 96h 창 47건 실측에서 오탐 0 (스펙 2026-08-07 §3.3)
_TRANSFER_TITLE_RE = re.compile(r"\b(joins|signs|transfer|loan)\b", re.IGNORECASE)


def filter_miss_suspects(rejects: list[dict], now: datetime,
                         recent_hours: float = 6.0) -> list[dict]:
    """Men + News 비채택 기사 중 이적 관련 제목 + 최근 발행만 추린다 (관측 전용).

    6시간 창은 3시간 회차 기준 기사당 최대 2회 발화로 도배를 막는 무상태 설계.
    발행 시각이 없거나 파싱 불가면 최근 여부를 알 수 없어 제외한다."""
    out: list[dict] = []
    for r in rejects:
        pub = r.get("published")
        if not pub:
            continue
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            continue
        if (now - dt).total_seconds() > recent_hours * 3600:
            continue
        if _TRANSFER_TITLE_RE.search(r.get("title") or ""):
            out.append(r)
    return out
```

import 줄은 아래처럼 바뀐다.

```python
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, pstdev
```

- [ ] **Step 8: 통과 확인**

Run: `uv run pytest tests/test_quality.py -q`
Expected: PASS (전체)

- [ ] **Step 9: notify 빌더 실패 테스트 작성**

`tests/test_notify.py` 끝에 추가한다.

```python
def test_build_filter_miss_alert_embed_shape():
    # 관측 사실만 싣는다 — 원인 추정 · 내부 용어 금지 (스펙 2026-08-07 §3.3)
    suspects = [{"title": "Christian Norgaard joins Everton",
                 "url": "https://www.arsenal.com/news/x-a7fZT9g6dECY",
                 "published": "2026-08-05T21:09:44.542Z",
                 "taxonomies": ["Men", "News", "Main"]}]
    alert = notify.build_filter_miss_alert(suspects, run_id="3f2a9c12abcd")
    assert "1건" in alert["title"]
    f = alert["fields"][0]
    assert f["name"] == "Christian Norgaard joins Everton"
    assert "- 태그: Men · News · Main" in f["value"]
    assert "[기사](https://www.arsenal.com/news/x-a7fZT9g6dECY)" in f["value"]
    assert "의심" not in alert["description"]   # 원인 추정 어휘 금지
    assert alert["fields"][-1]["value"] == "run 3f2a9c12"
```

- [ ] **Step 10: 실패 확인**

Run: `uv run pytest tests/test_notify.py::test_build_filter_miss_alert_embed_shape -q`
Expected: FAIL (`build_filter_miss_alert` 없음)

- [ ] **Step 11: notify 구현**

`src/bullet_in/notify.py` 의 `build_coverage_alert` 뒤에 추가한다.

```python
def build_filter_miss_alert(suspects: list[dict], *, run_id: str) -> dict:
    """공홈 창 후보 중 이적 관련 제목인데 수집되지 않은 기사 알림 (스펙 2026-08-07 §3.3).

    실측 사례 (2026-08-05 Norgaard): 이적 발표에 Transfer news 태그가 빠져
    태그 기준 수집에서 빠졌다. 원인 추정 없이 제목 · 태그 · 링크만 싣는다."""
    fields = []
    for s in suspects:
        lines = [f"- 태그: {' · '.join(s.get('taxonomies') or []) or '-'}"]
        pub = s.get("published")
        if pub:
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                lines.append(f"- 발행: {_discord_ts(dt.replace(tzinfo=None), 'R')}")
            except ValueError:
                pass
        if s.get("url"):
            lines.append(f"- [기사]({s['url']})")
        fields.append({"name": s.get("title") or "(제목 없음)",
                       "value": "\n".join(lines), "inline": False})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": (f"🔍 공홈 이적 관련 기사 미수집 — {len(suspects)}건"),
            "description": ("arsenal.com 새 기사 제목에 이적 관련 표현이 있는데 "
                            "이번 회차에 수집되지 않았습니다.\n"
                            "현재 수집 기준은 기사 태그 (Transfer news · Contract news) 입니다."),
            "color": COLOR_ANOMALY, "fields": fields, "url": RUNBOOK_ANOMALY}
```

주의: `_discord_ts` 는 naive UTC 를 받으므로 `dt.replace(tzinfo=None)` 로 벗겨서 넘긴다.

- [ ] **Step 12: 통과 확인**

Run: `uv run pytest tests/test_notify.py -q`
Expected: PASS (전체)

- [ ] **Step 13: run.py 배선**

`src/bullet_in/run.py` 의 공홈 커버리지 블록 (184 ~ 189행) 바로 뒤에 추가한다.

```python
    # 채택 누락 관측 (스펙 2026-08-07 §3.3): 이적 관련 제목인데 비채택이면 알림만 —
    # 수집 · 필터 판단은 바꾸지 않는다 (제품 결정 대기)
    for a in adapters:
        rejects = getattr(a, "men_news_rejects", None) or []
        suspects = filter_miss_suspects(rejects, datetime.now(timezone.utc))
        if suspects:
            notify.send_alert(**notify.build_filter_miss_alert(suspects, run_id=run_id))
```

`run.py` 상단의 quality import (26행) 에 `filter_miss_suspects` 를 추가한다.

```python
from bullet_in.quality import (success_rate, volume_anomalies, evaluate_freshness,
                               evaluate_coverage, candidate_cliffs, filter_miss_suspects)
```

주의: 26행의 기존 import 목록은 위와 다를 수 있다 — 실제 파일의 목록에 `filter_miss_suspects` 만 더한다.

- [ ] **Step 14: 전체 테스트 통과 확인**

Run: `uv run pytest -q`
Expected: PASS (통합 테스트는 skip)

- [ ] **Step 15: 커밋**

```bash
git add src/bullet_in/adapters/arsenal_api.py src/bullet_in/quality.py \
        src/bullet_in/notify.py src/bullet_in/run.py \
        tests/test_arsenal_api_adapter.py tests/test_quality.py tests/test_notify.py
git commit -m "feat(notify): 공홈 이적 관련 기사 미수집 관측 알림 추가"
```

### Task 5: 문서 — 트러블슈팅 신설 · 런북 2건 갱신 · 08-04 문서 정정 링크

**Files:**
- Create: `docs/troubleshooting/2026-08-07-arsenal-official-transfer-tag-omission.md`
- Modify: `docs/troubleshooting/2026-08-04-arsenal-official-accept-zero-not-a-fault.md` (후기 절 추가만)
- Modify: `docs/runbook/2026-07-13-freshness-watermark-ops.md` (문구 · 제외 규약)
- Modify: `docs/runbook/2026-07-13-collection-alerts-ops.md` (관측 알림 판독법 절)

**Interfaces:**
- Consumes: Task 2 ~ 4 의 최종 문구 (알림 제목 · 필드 구성)
- Produces: 없음 (문서)

- [ ] **Step 1: 트러블슈팅 신설**

`docs/troubleshooting/2026-08-07-arsenal-official-transfer-tag-omission.md` 를 작성한다.
스펙 §1.4 의 실측 (96시간 창 47건 전수 · 과거 채택 6건 재조회 · 뇌르고르 태그 목록) 을 본문으로 옮기고,
대응 (관측 알림 · 신선도 제외) 과 남은 제품 판단 (필터 수정 · Club 태그) 을 적는다.
서식은 §2.2 (훅 자동 검사).

- [ ] **Step 2: 08-04 문서에 후기 절 추가**

`docs/troubleshooting/2026-08-04-arsenal-official-accept-zero-not-a-fault.md` 끝에 짧은 절을 추가한다 (기존 본문 무수정).

```markdown
## 후기 (2026-08-07)

- "채택 0 은 산술적으로 맞다" 는 2026-08-05 부로 깨졌다 — 이적 발표에 Transfer news 태그가 빠진 실사례 발생.
- 상세 · 대응은 `2026-08-07-arsenal-official-transfer-tag-omission.md`.
```

- [ ] **Step 3: 런북 2건 갱신**

- `docs/runbook/2026-07-13-freshness-watermark-ops.md` — 후보 0건 문구 변경 반영 · `freshness_hours: 0 = 감시 제외` 규약과 arsenal_official 적용 사실을 적는다.
- `docs/runbook/2026-07-13-collection-alerts-ops.md` — "공홈 이적 관련 기사 미수집" 알림 판독법 절을 추가한다 (알림이 오면 무엇을 보고 · 수집할지는 제품 판단이라는 안내 포함).
- 두 파일 모두 기존 절 구조를 유지하고 관련 절만 더한다 (수술적 변경).

- [ ] **Step 4: 서식 훅 통과 확인 후 커밋**

```bash
git add docs/troubleshooting docs/runbook docs/superpowers/plans/2026-08-07-alert-f2-impl.md
git commit -m "docs: 공홈 태그 누락 실측 기록 · 알림 판독법 런북 갱신"
```

---

## 검증 (PR 이후 — 세션 컨트롤러 수행)

- 알림 PR: `uv run pytest -q` 전체 통과를 PR 본문 §4 에 증거로 싣는다.
- infra PR 머지 후 VM 반영 (스펙 §3.1 절차): git pull → install-units.sh → OnFailure 확인 → `bullet-in-fail-notify@test.service` 시험 발화 → 다음 정기 회차 정상 확인.
- 알림 PR 머지 후 VM git pull → 다음 회차에서 신선도 알림 침묵 (arsenal_official) 확인.
