# v1 마감 트랙 ③ — 문서 · 캡처 마감 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** README SLO 실측 4칸 기입 + 실데이터 캡처 2장 배치 + README 정합 + 로드맵 v1 완성 선언으로 v1 을 마감한다.

**Architecture:** 코드 변경 없는 docs 트랙.
신규 회차 1회를 돌려 실측 · 캡처의 최신 근거를 만들고, 지표별 자연 창으로 4칸을 실측한 뒤, Playwright 헤드리스로 캡처 2장을 촬영해 README 상단에 배치하고, 로드맵에 완성 선언을 남긴다.

**Tech Stack:** MariaDB (SQLAlchemy) · dbt + DuckDB · Playwright · 정적 사이트 (site/).

**Spec:** `docs/superpowers/specs/2026-07-19-v1-docs-capture-closeout-design.md`

## Global Constraints

- 실측값만 기입한다 — 추정 금지, 미달이면 그대로 적고 각주, 목표 재조정은 사용자 게이트.
- fmkorea 2h 규칙: 마지막 fetch 후 2시간 이내에 회차를 돌리지 않는다.
- 파이프라인 · 서빙 코드 변경 없음 — 측정 · 캡처 스크립트는 일회성 (커밋 안 함).
- 이 프로젝트는 dotenv 미사용 — 매 셸에서 `set -a; source .env; set +a` 선행.
- `docs/` 아래 .md 는 서식 훅 (`check-doc-format.py`) 이 §2.2 를 자동 검사한다.
- 커밋: `<type>(<scope>): 한국어 제목` + 도입 1–2문장 + 명사형 불릿 + `Refs:` + 실제 작업 모델 co-author 트레일러.
- football.london · bbc_gossip 수집 정책 서술은 변경하지 않는다 (트랙 ② 몫).

---

### Task 1: 사전 점검 + 신규 회차 실행

**Files:** 없음 (repo 변경 없음 — 라이브 DB · site/ 만 갱신됨).

**Interfaces:**
- Consumes: `.env` (MARIADB_URL · MONGO_URL · GEMINI_API_KEY · GUARDIAN_API_KEY · X 쿠키), docker compose (mongo · mariadb).
- Produces: 최신 회차가 반영된 `pipeline_runs` 1행 · `articles` 신규 행 · 재생성된 `site/` — Task 2 (실측) · Task 3 (캡처) 의 데이터 근거.

- [ ] **Step 1: Docker 헬스 · env 확인**

```bash
docker compose up -d && docker compose ps
set -a; source .env; set +a
echo "${MARIADB_URL:+MARIADB_URL ok} ${GEMINI_API_KEY:+GEMINI ok} ${GUARDIAN_API_KEY:+GUARDIAN ok}"
```

Expected: mongo · mariadb 컨테이너 `running`, 세 변수 모두 `ok` 출력.

- [ ] **Step 2: fmkorea 2h 규칙 확인**

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    last = c.execute(text("SELECT MAX(started_at) FROM pipeline_runs")).scalar()
print("마지막 회차 (UTC):", last)
EOF
```

Expected: 마지막 회차가 2시간 이전 (2026-07-15 경으로 추정).
2시간 이내라면 경과할 때까지 대기.

- [ ] **Step 3: 종단 회차 실행**

```bash
uv run python -m bullet_in.run --concurrency 8
```

Expected: 수집 → 적재 → enrich (번역 · 요약 · 분류) → dbt 게이트 → 서빙 완료 로그, 에러 0.
Gemini 429 · 503 으로 enrich 가 중단되면 잠시 후 `run` 재실행 (멱등 — 신규분만 처리).

- [ ] **Step 4: 회차 결과 · 번역 완료 검증**

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    run = c.execute(text(
        "SELECT run_id, new_count, error_count, success_rate FROM pipeline_runs "
        "ORDER BY started_at DESC LIMIT 1")).one()
    pending = c.execute(text(
        "SELECT COUNT(*) FROM articles WHERE title_ko IS NULL AND source_id NOT IN "
        "(SELECT source_id FROM sources WHERE source_id LIKE 'fmkorea%')")).scalar()
print("최신 회차:", run)
print("미번역 잔존:", pending)
EOF
```

Expected: 최신 회차 `error_count 0` · `success_rate 1.0` 근방, 미번역 잔존 0.
잔존 > 0 이면 Step 3 재실행으로 수렴시킨 뒤 진행.

---

### Task 2: SLO 실측 + README §4 기입 + 실측 런북

**Files:**
- Modify: `README.md` §4 표 (실측 컬럼 4칸)
- Create: `docs/runbook/2026-07-19-slo-measurement.md`

**Interfaces:**
- Consumes: Task 1 의 최신 회차 상태 (articles · pipeline_runs).
- Produces: 실측값 4개 (런북에 로그 포함) — Task 5 의 선언 근거.

- [ ] **Step 1: dbt 품질 게이트 실행 (중복 · 완전성의 dbt 근거)**

```bash
cd dbt && uv run dbt build --profiles-dir . && cd ..
```

Expected: `Completed successfully`, unique (content_hash · url) · not_null (content_hash · url · title_original) 전부 PASS.

- [ ] **Step 2: SQL 실측 (교차 확인 · 비율 산출)**

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    total = c.execute(text("SELECT COUNT(*) FROM articles")).scalar()
    dup_hash = c.execute(text(
        "SELECT COUNT(*) FROM (SELECT content_hash FROM articles "
        "GROUP BY content_hash HAVING COUNT(*) > 1) d")).scalar()
    dup_url = c.execute(text(
        "SELECT COUNT(*) FROM (SELECT url FROM articles "
        "GROUP BY url HAVING COUNT(*) > 1) d")).scalar()
    incomplete = c.execute(text(
        "SELECT COUNT(*) FROM articles WHERE content_hash IS NULL "
        "OR url IS NULL OR title_original IS NULL")).scalar()
    n_runs, avg_sr = c.execute(text(
        "SELECT COUNT(*), AVG(success_rate) FROM pipeline_runs")).one()
print(f"mart 전체        : {total}건")
print(f"중복 (hash/url)  : {dup_hash}/{dup_url} → 중복 적재율 {(dup_hash + dup_url) / total * 100:.1f}%")
print(f"필수 필드 위반   : {incomplete}건 → 완전성 {(total - incomplete) / total * 100:.2f}%")
print(f"성공률           : {n_runs}회 평균 {avg_sr * 100:.2f}%")
EOF
```

Expected: 중복 0 · 완전성 ~100% · 성공률 ≥ 99% (실제 출력값을 그대로 기록).
목표 미달 값이 나오면 그 값을 그대로 쓰고 각주로 사유를 단다 (재조정은 사용자 확인 후).

- [ ] **Step 3: README §4 실측 4칸 기입**

`README.md` §4 표의 `—` 4칸을 Step 1 · 2 실측값으로 교체한다 (N · xx.x 는 실제 출력값).

```markdown
| 중복 적재율 | 0% | content_hash UNIQUE + dbt `unique` 테스트 | 0% (2026-07-19, mart N건 dbt PASS + SQL 교차) |
| 일일 수집 성공률 | ≥ 99% | `pipeline_runs.success_rate` (재시도 · 소스 격리 포함) | xx.x% (2026-07-19, N회 평균) |
| 필수 필드 완전성 | ≥ 99% | dbt `not_null` 테스트 통과율 | xx.x% (2026-07-19, mart N건) |
| 수집량 이상 감지 | 전일 대비 ±2σ 알림 | `quality.volume_anomaly` | 가동 (실발송 검증 2026-07-13) |
```

- [ ] **Step 4: 실측 런북 작성**

`docs/runbook/2026-07-19-slo-measurement.md` 를 생성한다.
구성: ① 측정 창 정의 (지표별 자연 창 · 왜 그 창인가) ② Step 1 · 2 의 명령 원문 ③ 이번 실행 로그 (실제 출력 붙여넣기) ④ 판독 기준 (중복 0행 = 0% · 완전성 산식 · 성공률 평균 · 이상 감지 = 가동 실적 서술 이유) ⑤ 재측정 절차 (신규 회차 후 동일 명령).
§2.2 서식 (한 줄 한 문장 · `→` `—` 줄 시작) 준수 — 훅이 검사한다.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/runbook/2026-07-19-slo-measurement.md
git commit  # docs(readme): SLO 실측 4칸 기입 · 측정 런북 — 본문에 실측값 요약, Refs: 런북 경로
```

---

### Task 3: 실데이터 캡처 2장 + README 상단 교체

**Files:**
- Create: `docs/assets/serving-page-live.png` · `docs/assets/article-detail-live.png`
- Delete: `docs/assets/serving-page-sample.png`
- Modify: `README.md` 상단 캡처 블록 (7~11행)

**Interfaces:**
- Consumes: Task 1 이 재생성한 `site/` (index.html · article/<content_hash>.html).
- Produces: README 가 참조하는 실데이터 캡처 2장 — Task 6 완료 기준의 "캡처 주석 해제" 충족.

- [ ] **Step 1: 상세 대상 기사 선별 + 캡처 촬영**

기자 바이라인 · 인라인 이미지 · 3줄 요약이 모두 있는 최신 기사를 고르고, 뷰포트 1440×900 라이트 테마로 두 페이지를 촬영한다.

```bash
uv run python - <<'EOF'
import functools, http.server, os, pathlib, socketserver, threading
from sqlalchemy import create_engine, text
from playwright.sync_api import sync_playwright

eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    cands = c.execute(text(
        "SELECT content_hash, title_ko, journalist FROM articles "
        "WHERE journalist IS NOT NULL AND images_json IS NOT NULL "
        "AND summary3_ko IS NOT NULL AND body_ko IS NOT NULL "
        "ORDER BY published_at DESC LIMIT 5")).all()
for h, t, j in cands:
    print(h[:8], j, (t or "")[:40])
target = cands[0][0]

socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(
    ("127.0.0.1", 8731),
    functools.partial(http.server.SimpleHTTPRequestHandler, directory="site"))
threading.Thread(target=srv.serve_forever, daemon=True).start()
with sync_playwright() as p:
    pg = p.chromium.launch().new_page(
        viewport={"width": 1440, "height": 900}, color_scheme="light")
    pg.goto("http://127.0.0.1:8731/index.html")
    pg.wait_for_load_state("networkidle")
    pg.screenshot(path="docs/assets/serving-page-live.png")
    pg.goto(f"http://127.0.0.1:8731/article/{target}.html")
    pg.wait_for_load_state("networkidle")
    pg.screenshot(path="docs/assets/article-detail-live.png")
srv.shutdown()
print("캡처 완료:", target)
EOF
```

Expected: 후보 5건 출력 후 PNG 2장 생성.
http 로 띄우는 이유 · `uv run python` 사용은 브라우저 검증 런북 (`docs/runbook/2026-07-19-serve-browser-verification.md` §2.3) 의 계약.

- [ ] **Step 2: 캡처 눈검수**

두 PNG 를 열어 확인한다 — 인덱스: 사이드바 (tier 그룹 헤더 · 기자 facet) + 카드 그리드가 보이는가.
상세: 히어로 · 3줄 요약 · 기자 바이라인이 보이는가, 인라인 이미지가 로드됐는가 (핫링크 실패 시 다른 후보로 교체).
구도가 미달이면 후보를 바꾸거나 (target = 다른 hash) 스크롤 위치를 조정해 재촬영.

- [ ] **Step 3: README 상단 블록 교체 + 구 샘플 제거**

README 7~11행 (샘플 이미지 · 캡션 · 주석 2줄) 을 아래로 교체한다.

```markdown
![Bullet-in 인덱스 — 실데이터](docs/assets/serving-page-live.png)

> 실데이터 인덱스. 신뢰도 (tier) 순 정렬 · 언론사 · 기자 facet 필터 · 한국어 번역 · 요약.

![Bullet-in 기사 상세 — 실데이터](docs/assets/article-detail-live.png)

> 기사 상세. 3줄 요약 · 본문 전문 번역 · 인라인 이미지 · 기자 바이라인.
```

```bash
git rm docs/assets/serving-page-sample.png
grep -rn "serving-page-sample" README.md docs/ || echo "참조 0"
```

Expected: `참조 0` (다른 문서가 샘플을 참조하면 해당 참조는 dated 문서이므로 삭제 대신 유지 여부를 확인하고, 참조가 남는 경우 파일 삭제를 보류하고 보고).

- [ ] **Step 4: Commit**

```bash
git add docs/assets/serving-page-live.png docs/assets/article-detail-live.png README.md
git commit  # docs(readme): 실데이터 캡처 2장 배치 — 인덱스 · 상세, 구 샘플 제거
```

---

### Task 4: README · CLAUDE.md 정합 정정

**Files:**
- Modify: `README.md` §2 · §3 · §5 · §7
- Modify: `CLAUDE.md` 상단 스택 줄

**Interfaces:**
- Consumes: `config/sources.yaml` · `config/credibility.yaml` 현재 상태.
- Produces: 코드 · config 와 일치하는 README — Task 6 완료 기준의 "README 정합" 충족.

- [ ] **Step 1: twikit 표기 정정 (확정 stale — PR #24 에서 대체됨)**

- README §2 도식 28행: `RSS · Guardian API · httpx+파서 · Playwright · twikit`
→ `RSS · Guardian API · httpx+파서 · Playwright · X 쿠키 Playwright`
- README §3 52행: `X=twikit` → `X=쿠키 주입 Playwright`
- README §5 103행: `Playwright/httpx/twikit` → `Playwright/httpx` (X 는 쿠키 주입 Playwright 라는 설명이 유지되게 이유 칸도 함께 손봄)
- CLAUDE.md 3행 스택 줄: `Playwright, twikit, google-genai` → `Playwright, google-genai`

- [ ] **Step 2: §3 소스 표 · 기자 표를 config 와 대조**

```bash
uv run python - <<'EOF'
import yaml
src = yaml.safe_load(open("config/sources.yaml"))
for s in src["sources"]:
    print(f'{s["source_id"]:20} tier={s.get("tier", "동적")} adapter={s["adapter"]} enabled={s.get("enabled", True)}')
cred = yaml.safe_load(open("config/credibility.yaml"))
for j in cred["journalists"]:
    print(f'{j["name"]:25} tier={j["tier"]} outlet={j.get("outlet", "-")}')
EOF
```

출력과 README §3 두 표를 행 단위로 대조해 어긋난 칸만 고친다 (tier · 어댑터 · 비고 · 기자 명단).
yaml 키 이름이 실제 구조와 다르면 스크립트를 파일 실물에 맞게 조정한다.

- [ ] **Step 3: 나머지 섹션 훑기**

- §7 실행 방법: 명령 4단계가 현재도 유효한지 (특히 `open site/index.html` · dbt 경로).
- §6 데이터 모델: `source_freshness` 테이블 (SLO-5) 언급 누락 확인 — 한 줄 추가.
- §8 한계 & 향후: 완료된 항목 (모니터링 대시보드는 ops 뷰로 일부 해소) 이 "향후" 로 남아 있으면 표현 조정.
- 수집 정책 서술 (football.london 등) 은 건드리지 않는다.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit  # docs(readme): 코드 · config 정합 정정 — twikit 표기 · 소스 표 · 데이터 모델
```

---

### Task 5: 로드맵 갱신 + v1 완성 선언

**Files:**
- Modify: `docs/superpowers/2026-06-28-v1-completion-roadmap.md`

**Interfaces:**
- Consumes: Task 2 실측값 · Task 3 캡처 · 요약 말투 백필 잔존 재확인 결과.
- Produces: v1 완성 선언 섹션 — 트랙 종결의 SoT 기록.

- [ ] **Step 1: 백필 잔존 0 재확인 (선언 조건 ②)**

tone 백필 런북 §1 스크립트를 그대로 실행한다.

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine
from bullet_in.storage.mariadb import MartStore
from bullet_in.tone import has_polite_ending
mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
rows = mart.rows_enriched_summaries()
bad = [r for r in rows
       if has_polite_ending(r.get("summary_ko")) or has_polite_ending(r.get("summary3_ko"))]
print(f"잔존 {len(bad)} / 전체 {len(rows)}")
EOF
```

Expected: `잔존 0 / 전체 N`.
잔존 > 0 이면 오검출 여부를 런북 §1 판독 기준으로 확인하고, 진짜 잔존이면 다음 회차 백필 수렴 후 재확인 (선언 보류).

- [ ] **Step 2: 로드맵 갱신**

`docs/superpowers/2026-06-28-v1-completion-roadmap.md` 를 수정한다.

- 제목 줄 갱신 이력에 `2026-07-19 갱신` 추가.
- 진행 현황 표: Tier 2 `✅ 완료 · 100 %` · Tier 5 `✅ 완료 · 100 %`, 종합 `100 % — v1 완성`.
- "v1 마감 범위" 3트랙 표에 완료 표시: ① PR #47 · #48 · #49 ② PR #50 ③ 본 트랙 PR.
- Tier 5 섹션 항목 12 를 `[✅ 완료]` 로.

- [ ] **Step 3: "v1 완성 선언" 섹션 신설**

로드맵 문서에 아래 뼈대로 추가한다 (실측값 · SHA · PR 번호는 실제 값).

```markdown
## v1 완성 선언 (2026-07-19)

완성 선언 조건 3개를 모두 충족해 v1 을 완성으로 선언한다.

| 조건 | 근거 |
|---|---|
| 마감 3트랙 머지 | ① 요약 말투 #47 `47144c2` · #48 `54d96a8` · #49 `8eefd4f` / ② 인라인 이미지 #50 `37606ee` / ③ 문서 · 캡처 본 트랙 PR #NN |
| ① 백필 잔존 0 | 2026-07-19 재확인 — 잔존 0 / N (tone 런북 §1 스크립트) |
| ③ README 공란 0 | §4 실측 4칸 기입 (측정 런북 `docs/runbook/2026-07-19-slo-measurement.md`) · 캡처 2장 배치 |

이후 작업 (기자 후속 트랙 ② · ③, SP2 재측정, 백로그) 은 v1 이후 트랙으로 진행한다.
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/2026-06-28-v1-completion-roadmap.md
git commit  # docs(superpowers): 로드맵 v1 완성 선언 — 3조건 근거 · 진행률 100%
```

---

### Task 6: 최종 검증 + PR 생성

**Files:** 없음 (검증 · PR 만).

**Interfaces:**
- Consumes: Task 1~5 의 커밋 전부.
- Produces: PR (squash merge 대기) — spec §8 완료 기준 충족 보고.

- [ ] **Step 1: 완료 기준 일괄 검증**

```bash
grep -n "| — |" README.md || echo "SLO 공란 0"
grep -c "live.png" README.md          # 2 이상 (인덱스 · 상세 참조)
ls docs/assets/serving-page-live.png docs/assets/article-detail-live.png
git ls-files docs/assets/serving-page-sample.png || echo "샘플 제거됨"
grep -n "v1 완성 선언" docs/superpowers/2026-06-28-v1-completion-roadmap.md
uv run pytest -q   # 코드 무변경 확인용 회귀 (기존 passed 수 유지)
```

Expected: SLO 공란 0 · 캡처 2장 존재 · 샘플 제거 · 선언 섹션 존재 · pytest 기존과 동일 (신규 실패 0).

- [ ] **Step 2: PR 생성**

`.github/pull_request_template.md` 의 7섹션 · 주석 세칙 (명사형 불릿 · **핵심어** — 설명 · LOC 기준) 을 그대로 따라 본문을 작성한다.

```bash
git push -u origin docs/v1-closeout
gh pr create --title "docs: v1 마감 — SLO 실측 · 실데이터 캡처 · README 정합 · 완성 선언" --body-file /tmp/pr-body.md
```

본문에 Claude 서명 금지 (§2.7).
머지는 사용자 확인 후 squash.

- [ ] **Step 3: 트랙 ③ 완료 보고**

실측 4값 · 캡처 대상 기사 · 선언 섹션 위치 · PR 링크를 사용자에게 보고하고, v1 완성 선언 확정 (머지) 판단을 넘긴다.
