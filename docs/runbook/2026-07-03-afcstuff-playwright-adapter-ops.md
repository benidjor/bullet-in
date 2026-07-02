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
- **DOM 가상화로 인한 저수율**: X 타임라인은 스크롤 시 화면 밖 옛 트윗을 DOM에서 제거한다 (virtualization).
  `eval_on_selector_all`은 그 순간 렌더된 트윗만 반환하므로 `len(raw_tweets)`가 단조 증가하지 않고 정체할 수 있고, 스크롤 루프의 `len == seen` 조기 종료가 `max_tweets`에 못 미쳐 걸릴 수 있다.
  → **수율이 기대보다 낮으면 여기부터 의심.** 근본 개선은 스크롤마다 DOM 스냅샷을 다시 읽지 말고 `status_id`로 dedup하며 누적하는 방식 (추후 처리).
- **셀렉터 드리프트**: X가 `data-testid` (`tweet` · `tweetText` 등)를 바꾸면 수집 0건.
  → 위 라이브 검증으로 조기 발견하고 셀렉터를 갱신.

## journalist 표시 vs tier 산출 핸들 차이

- `journalist` (표시)는 `_CITE_RE` (마지막 `[ @X ]`)로, tier는 credibility `_HANDLE_RE` (본문 전체 `@멘션`의 `min`)로 산출된다.
- 즉 표시 기자와 tier 산출 핸들이 갈릴 수 있다 (비인용 `@멘션`이 더 높은 tier면 그쪽이 tier에 반영).
- 이는 기존 `x_mentions` 설계 (tier는 전체 인용 중 `min`)에 따른 의도된 동작이다. 코드 결함이 아니다.

## 롤백

- `config/sources.yaml`에서 `x_afcstuff.enabled: false`로 즉시 비활성.
- DB 스키마 변경이 없어 되돌림에 마이그레이션이 불필요하다.

## 참고

- 어댑터: `src/bullet_in/adapters/x_playwright.py`
- 비호환 배경: `docs/troubleshooting/2026-07-03-twikit-x-transaction-id-incompatibility.md`
- 설계: `docs/superpowers/specs/2026-07-01-sp1-afcstuff-playwright-reader-design.md`
