# SP2 역추적 승격 tier · 라우팅 함정 (2026-07-03)

afcstuff 기자 역추적 승격 (SP2-a) 구현 · 리뷰에서 드러난 비자명한 결합 · 진단 함정 3종.

## 배경

- **대상** — afcstuff 인용 트윗을 기자 타임라인 역추적으로 무료 아웃렛 원 기사에 연결해 1순위로 승격하는 경로 (`x_backtrack.py` · `x_playwright.py`).
- **성격** — 아래 3종은 크래시가 아니라 조용히 잘못된 tier · 미승격으로 새는 함정이라 로그 · 값 확인 없이는 발견이 어려움.

## 함정 1 — 승격 항목 tier가 기자-먼저가 아니라 아웃렛 · fallback으로 강등

승격 항목의 tier가 설계 (기자 먼저)와 다르게 나오는 결합.

- **증상** — Simon Collings (기자 tier 3)의 The Sun 기사가 tier 4 (The Sun 아웃렛)로 표기.
- **원인** — `resolve_tier`의 `x_mentions` 분기는 기자 핸들을 `raw_payload["text"]`에서 `_HANDLE_RE`로 읽음.
  - 승격 항목이 `text`를 안 담으면 핸들을 못 찾아 기자 tier 단계를 건너뜀.
  - 결과로 아웃렛 폴백 (아웃렛 tier) · 최종 `fallback_tier`로 강등.
- **해결** — `promote_cited_item`이 원 트윗 `text` (핸들 포함)를 승격 `raw_payload`에 보존.
  - `title`은 og:title이 우선하므로 `text` 보존이 제목을 덮지 않음 (`to_articles`는 `title or text`).
- **진단** — 승격 항목 1건에 `resolve_tier`를 직접 호출해 확인.

```python
from bullet_in.credibility import load_registry, resolve_tier
reg = load_registry("config/credibility.yaml")
src = {"x_afcstuff": {"credibility": "x_mentions", "fallback_tier": 4}}
# 승격 RawItem을 promoted 라 할 때
print(resolve_tier(promoted, src, reg))   # 기자 tier가 나와야 정상, 아웃렛/4면 text 누락 의심
print("text" in promoted.raw_payload)     # False면 함정 1
```

## 함정 2 — 무료 아웃렛 기사가 tier 4로 표기 (도메인 맵 · 레지스트리 불일치)

known 무료 아웃렛인데 tier가 fallback으로 떨어지는 결합.

- **증상** — Goal.com · arseblog 승격 기사가 아웃렛 tier가 아니라 fallback 4 (미등록 기자 인용일 때).
- **원인** — `resolve_tier`의 아웃렛 조회는 `outlet.lower()`를 `registry.outlets` 키와 대조.
  - `registry.outlets` 키는 `credibility.yaml`의 **alias** 소문자뿐, 아웃렛 **name**은 키가 아님.
  - `backtrack.yaml`의 도메인 값이 alias와 안 맞으면 조회 실패 → fallback.
  - 사례 — `goal.com: Goal.com` (name) ↔ credibility alias는 `"Goal"`뿐 → `"goal.com"` 키 부재.
  - 사례 — `arseblog`가 credibility outlets에 아예 없음.
- **해결** — 도메인 맵 값을 credibility alias와 일치시키거나 credibility에 등록.
  - `goal.com: Goal` (alias `"Goal"` 사용).
  - `credibility.yaml` outlets에 `{name: arseblog, tier: 2, aliases: ["arseblog"]}` 추가.
- **예방** — `backtrack.yaml`에 도메인 추가 시 값이 `credibility.yaml`의 alias (name 아님)와 소문자 일치하는지 확인.

## 함정 3 — "승격 0건"이 결함이 아닌 경우 진단

승격이 안 나올 때 코드 결함과 정상 (데이터 · 외부 요인)을 가르는 순서.

로그 (`INFO bullet_in.adapters.x_backtrack`)를 먼저 읽고 아래로 분기.

```
승격 0 · 로그 확인
  ├─ near-miss (카드 없음) 다수      → 텍스트 특종 기자 (정상, 2순위 유지)
  ├─ 페이월 (Athletic) 다수          → 슬라이스 A 밖 (정상, SP2-b 대상)
  ├─ 미등록 도메인 다수              → backtrack.yaml domains에 추가 (함정 2 주의)
  ├─ 매칭 실패 다수                  → timeline_depth 늘리거나 overlap_min 낮춤
  └─ 인용 자체가 적음                → 월드컵 · 시즌 볼륨 (외부 요인, 코드 무관)
```

- **핵심 전제** — afcstuff 자체 트윗은 link-card가 0 (스샷 · 인용만).
  - 승격은 반드시 *기자* 타임라인 역추적으로만 발생, afcstuff 트윗에서 직접 링크 추출은 불가.
- **아웃렛 fetchability가 승격 여부를 가름** — 무료 (BBC · The Sun · arseblog)는 카드 有, Athletic은 페이월.
  - 특정 기자의 낮은 승격률은 그 기자가 아니라 아웃렛 특성일 수 있음.

## 함정 4 — 트윗의 `outlet` 컬럼이 비어 있는 것은 결함이 아니다 (2026-07-22)

트윗 40행의 `outlet` 이 전부 NULL 인 것을 보고 매핑이 덜 된 줄 알고 채우려 했다.
소스 전체를 세어 보니 **243행 중 25행만 채워져 있었다** — fmkorea 뿐이고 나머지 소스도 전부 NULL 이었다.

`outlet` 컬럼은 **원문 자체가 매체명을 들고 있을 때만** 채운다.
fmkorea 는 제목 말머리 (`[디 애슬레틱]`) 를 파싱할 수 있지만 다른 소스에는 그런 표기가 없다.
`pipeline.py` 가 `raw_payload.get("outlet")` 을 그대로 넣고 없으면 NULL 이다.

화면 표시는 `render.outlet_display` 가 아래 순서로 대체 값을 찾는다.

1. `outlet` 컬럼 값 (fmkorea)
2. X 소스면 `journalist` 핸들 → `credibility.yaml` → 소속 매체 (`@garyjacob` → The Times)
3. 소스 설정의 `display_name`

트윗이 화면에서 `Gary Jacob (The Times)` 로 보이는 것은 임시 대체가 아니라 이 소스를 위해 일부러 만든 표시 경로다.
dbt 모델 · 운영 뷰 어디도 `outlet` 컬럼을 직접 집계하지 않는다.

**컬럼을 채우면 오히려 손해다.**
지금은 `credibility.yaml` 을 고치면 과거 기사의 매체 표기가 즉시 따라오는데, 값을 컬럼에 저장해 두면 사전을 고칠 때마다 백필을 돌려야 한다.

교훈은 진단 방법에 있다 — **컬럼 채움률은 한 소스만 보고 판단하지 말고 전체 분포를 먼저 센다.**
비어 있는 값이 결함인지 의도한 설계인지는 화면 표시 코드의 대체 순서를 읽어야 알 수 있다.

## 참고

- 어댑터 · 로직 — `src/bullet_in/adapters/x_backtrack.py` · `src/bullet_in/adapters/x_playwright.py`.
- tier 산출 — `src/bullet_in/credibility.py` (`resolve_tier` x_mentions 분기).
- 설정 — `config/backtrack.yaml` · `config/credibility.yaml`.
- 운영 절차 — `docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md` (SP2 역추적 승격 운영).
- 설계 — `docs/superpowers/specs/2026-07-03-sp2a-afcstuff-backtrack-design.md`.
