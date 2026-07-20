# afcstuff Playwright 어댑터 운영 (2026-07-03)

afcstuff (X) 인용 트윗을 수집하는 Playwright 어댑터 (`x_playwright`, SP1 · PR #24)의 운영 절차 · 실패 진단.

## 목적

- afcstuff 타임라인에서 `[ @handle ]` 인용 트윗을 2순위 항목으로 수집.
- twikit 비호환 (별도 트러블슈팅 문서)을 Playwright 실브라우저로 우회.

## 사전 준비 — X 쿠키

어댑터는 `x_cookies.json` (프로젝트 루트, gitignore됨)이 있어야 동작한다.
- 버너 (일회용) X 계정으로 브라우저에서 x.com 로그인.
- 개발자도구 → Application → Cookies → `x.com`에서 `auth_token` · `ct0` 값 복사.
- `x_cookies.json` 생성:
  ```json
  { "auth_token": "<값>", "ct0": "<값>" }
  ```
- 주의: 개인 계정 금지 (unofficial 접근은 정지 위험이라 반드시 버너). 쿠키는 수 주 ~ 수 개월 후 만료되니 만료 시 재추출.

## 라이브 검증 (머지 전 · 정기)

셀렉터 드리프트는 단위 테스트로 못 잡으므로 실제 `fetch()`를 돌려 확인한다.

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import asyncio, yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open("config/sources.yaml"))
adp = [a for a in build_adapters(cfg) if a.source_id == "x_afcstuff"][0]
items = asyncio.run(adp.fetch())
print("수집:", len(items))
for it in items[:8]:
    print(" ", it.raw_payload["journalist"], "|", it.raw_payload["text"][:70])
PY
```

- 기대: 인용 트윗이 수집되고 각 항목에 `journalist` (@핸들)가 붙는다. 무인용 (월드컵 반응 등)은 빠진다.

## 실패 모드 · 진단

- **쿠키 부재 · 만료**: `_x_cookies`가 `FileNotFoundError`, 로그인 만료는 로드 후 `TimeoutError`.
  `ingest.gather_all`의 소스별 격리로 `errors[x_afcstuff]`에 로깅되고 타 소스는 무영향.
  → 조치: 쿠키 재추출 (위 사전 준비).
- **DOM 가상화**: X 타임라인은 스크롤 시 화면 밖 옛 트윗을 DOM에서 제거한다 (virtualization).
  `eval_on_selector_all`은 그 순간 렌더된 트윗만 반환하므로 단일 스냅샷은 8건 안팎에서 정체한다.
  어댑터는 스크롤마다 `status_id`로 dedup · 누적 (`_accumulate_tweets`)하므로 수율이 단조 증가해 `max_tweets`에 근접한다.
  → 그래도 수율이 낮으면 아래 셀렉터 드리프트를 의심.
- **셀렉터 드리프트**: X가 `data-testid` (`tweet` · `tweetText` 등)를 바꾸면 수집 0건.
  → 위 라이브 검증으로 조기 발견하고 셀렉터를 갱신.
- **데이터센터 IP 운영 (2026-07-20 VM 동거 이후)**: 접촉 IP 가 가정 IP 에서 Oracle 고정 DC IP 로 바뀌어 차단 확률이 올라간 상태.
  첫 접촉 2회 (수동 종단 · 무인 회차) 는 정상 수집 — 차단되면 SLO-5 (X 24h) 알림이 감지하고, 폴백은 소스 비활성 (배포 spec §2.4).

## journalist 표시 vs tier 산출 핸들 차이

- `journalist` (표시)는 `_CITE_RE` (마지막 `[ @X ]`)로, tier는 credibility `_HANDLE_RE` (본문 전체 `@멘션`의 `min`)로 산출된다.
- 즉 표시 기자와 tier 산출 핸들이 갈릴 수 있다 (비인용 `@멘션`이 더 높은 tier면 그쪽이 tier에 반영).
- 이는 기존 `x_mentions` 설계 (tier는 전체 인용 중 `min`)에 따른 의도된 동작이다. 코드 결함이 아니다.

## SP2 역추적 승격 운영

afcstuff 인용을 무료 아웃렛 원 기사로 승격하는 backtrack 운영 (SP2-a).

### 활성 조건

feature flag로 켜지는 조건 정리.

- **`backtrack_config` 설정** — `config/sources.yaml`의 `x_afcstuff.config.backtrack_config`가 있으면 켜짐 (`config/backtrack.yaml`).
- **off면 SP1 동일** — 값을 빼면 2순위 트윗 수집만 동작 (하위 호환).

### 라이브 검증

셀렉터 · 카드 · t.co · 본문 추출은 모킹이 못 잡으므로 실 fetch로 확인.

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import asyncio, yaml, logging
logging.basicConfig(level=logging.INFO)
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open("config/sources.yaml"))
adp = [a for a in build_adapters(cfg) if a.source_id == "x_afcstuff"][0]
items = asyncio.run(adp.fetch())
promoted = [it for it in items if it.source_type == "html"]
print("승격(1순위):", len(promoted), "· 2순위:", len(items) - len(promoted))
for it in promoted:
    print(" ", it.raw_payload["outlet"], it.url, len(it.raw_payload.get("body") or ""), "자")
PY
```

- 기대 — 승격 항목은 `source_type="html"` · `url`=기사 URL · `body` 채움, 실패건은 `source_type="x"`로 2순위.

### 로그 해석 (INFO `bullet_in.adapters.x_backtrack`)

로그 문구별 의미 · 조치.

- **`near-miss (카드 없음)`** — 매칭 원본에 link-card 없음 (텍스트 특종). 정상 · 2순위 유지.
- **`매칭 실패`** — 시간창 · 겹침 임계 미달. 다수면 `timeline_depth` · `overlap_min` 튜닝.
- **`페이월 (Athletic)`** — 슬라이스 A 밖. 정상 (SP2-b 대상).
- **`미등록 도메인`** — 무료지만 도메인 맵 부재. domains에 추가 (아웃렛명은 credibility alias와 일치).
- **`기자 상한 초과`** — distinct 기자가 `max_journalists` 초과, 초과분 드롭 (무음 아님).

### 파라미터 튜닝

`config/backtrack.yaml` params, near-miss 로그로 조정.

- **`window_min`** — afcstuff가 기자 원본을 인용하기까지 시간창 (분). 넓히면 오탐 증가.
- **`overlap_min`** — 매칭 최소 토큰 겹침. 낮추면 억지 매칭 증가.
- **`timeline_depth`** — 기자당 스크레이프 트윗 수. 얕으면 원본이 창 밖으로 밀려 매칭 실패.
- **`max_journalists`** — 실행당 기자 스크레이프 상한 (X 읽기 예산).

### X 읽기 예산

backtrack은 실행당 X 스크레이프를 늘림.

- **스크레이프 횟수** — afcstuff 1회 + distinct 인용 기자 타임라인 각 1회 (최대 `max_journalists`).
- **버너 주의** — 계정 마모 · 쿠키 만료 주의 (쿠키 재추출은 위 사전 준비).
- **절약** — 트윗-only 핸들 (팟캐스트 등)은 `skip_handles`로 역추적 제외.

### 도메인 맵 성장

`config/backtrack.yaml` domains를 로그 근거로 확장.

- **추가 근거** — 미등록 도메인 로그를 빈도순으로 domains에 추가.
- **⚠️ 아웃렛명 정합** — 값은 `credibility.yaml`의 alias (소문자)와 일치해야 tier 정상.
  - 불일치 시 tier가 조용히 fallback 4로 강등 (트러블슈팅 함정 2).

## 롤백

- **backtrack만 끄기** — `config/sources.yaml`에서 `x_afcstuff.config.backtrack_config` 제거 (SP1 2순위만 유지).
- **소스 전체 끄기** — `x_afcstuff.enabled: false`로 즉시 비활성.
- **마이그레이션 불필요** — DB 스키마 변경이 없어 되돌림에 마이그레이션이 불필요하다.

## 참고

- 어댑터: `src/bullet_in/adapters/x_playwright.py` · `src/bullet_in/adapters/x_backtrack.py` (SP2)
- 비호환 배경: `docs/troubleshooting/2026-07-03-twikit-x-transaction-id-incompatibility.md`
- SP2 tier · 라우팅 함정: `docs/troubleshooting/2026-07-03-sp2-backtrack-tier-routing-traps.md`
- 설계: `docs/superpowers/specs/2026-07-01-sp1-afcstuff-playwright-reader-design.md` · `docs/superpowers/specs/2026-07-03-sp2a-afcstuff-backtrack-design.md`
