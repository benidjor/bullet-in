# CLAUDE.md — bullet-in

아스날 FC 뉴스 수집 파이프라인. 다중 소스 (RSS/HTML/Playwright/X)를 asyncio 병렬 수집 →
MongoDB (raw) → MariaDB (mart, content_hash · URL UNIQUE dedup) → Gemini 번역/요약 →
dbt 품질 게이트 (DuckDB) → 정적 HTML 서빙. 스케줄은 Airflow.

스택: Python 3.11, uv, pydantic v2, httpx+BeautifulSoup, Playwright, google-genai, SQLAlchemy.

---

## 행동 가이드라인 — LLM 코딩 실수 줄이기

출처: [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills).
프로젝트 지시와 병합해 적용한다. **트레이드오프**: 속도보다 신중을 택한다 — 사소한 작업엔 판단으로.

### 1. 코딩 전에 생각 (Think Before Coding)
**가정하지 말 것. 혼란을 숨기지 말 것. 트레이드오프를 드러낼 것.**

구현 전에:
- 가정을 명시한다. 불확실하면 질문한다.
- 여러 해석이 가능하면 제시한다 — 임의로 하나 고르지 않는다.
- 더 단순한 방법이 있으면 말한다. 필요하면 반대한다.
- 불명확하면 멈춘다. 무엇이 헷갈리는지 짚고 질문한다.

### 2. 단순함 우선 (Simplicity First)
**문제를 푸는 최소 코드. 투기적인 것은 없다.**

- 요청 범위 밖 기능 없음.
- 1회용 코드에 추상화 없음.
- 요청하지 않은 "유연성" · "설정성" 없음.
- 일어날 수 없는 시나리오용 에러 처리 없음.
- 200줄로 짠 게 50줄이면 될 것 같으면 다시 쓴다.

자문: "시니어 엔지니어가 과하게 복잡하다고 할까?" 그렇다면 단순화한다.

### 3. 수술적 변경 (Surgical Changes)
**꼭 필요한 것만 건드린다. 네가 만든 것만 치운다.**

기존 코드를 고칠 때:
- 인접 코드 · 주석 · 포맷을 "개선"하지 않는다.
- 안 깨진 것을 리팩터하지 않는다.
- 다르게 하고 싶어도 기존 스타일에 맞춘다.
- 무관한 죽은 코드는 **언급만** 하고 삭제하지 않는다.
- 네 변경이 만든 고아 (import · 변수 · 함수)만 제거한다. 기존 죽은 코드는 요청 없으면 두라.

테스트: 바뀐 모든 줄이 사용자 요청에 직접 추적돼야 한다.

### 4. 목표 주도 실행 (Goal-Driven Execution)
**성공 기준을 정의하고, 검증될 때까지 루프한다.**

작업을 검증 가능한 목표로 바꾼다:
- "검증 추가" → "잘못된 입력 테스트를 쓰고 통과시킨다"
- "버그 수정" → "재현 테스트를 쓰고 통과시킨다"
- "X 리팩터" → "전후로 테스트가 통과하도록 한다"

다단계 작업은 간단한 계획을 명시한다 (`단계 → 검증: 체크`).
강한 성공 기준은 독립적으로 루프하게 해준다. 약한 기준 ("그냥 되게")은 계속 되묻게 만든다.

> **작동 신호**: diff에 불필요한 변경 감소, 과복잡으로 인한 재작성 감소, 질문이 실수 후가 아니라 구현 전에 나옴.

---

## 명령어
```bash
uv sync --extra dev && uv run playwright install chromium   # 셋업
uv run pytest -q                                            # 테스트(통합은 DB/Airflow 없으면 skip)
docker compose up -d                                        # mongo, mariadb
set -a; source .env; set +a                                 # 이 프로젝트는 dotenv 미사용 → 셸 export 필요
uv run python -m bullet_in.run --concurrency 8              # 종단 실행
```
첫 라이브 실행 절차 · 제약: `docs/runbook/2026-06-12-live-e2e-bootstrap.md`.

## 커밋 & PR 컨벤션 (필독)
SoT: `docs/conventions/2026-06-11-commit-pr-convention.md`. 핵심:
- 커밋: `<type>(<scope>): 한국어 제목` + 본문 + `Refs:` + 트레일러. type/scope는 영어.
  본문은 도입 1–2문장 (맥락 · 왜) + 명사형 불릿 — 산문만 나열 금지 (§1.1).
- **co-author 트레일러는 실제 작업 모델 + Claude 공식 noreply** (§1.3 개정 2026-07-13):
  설계 · 구현 모델이 다르면 (subagent 위임) 역할 라벨로 두 줄 병기, 같으면 라벨 없이 한 줄.
  `Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>`
  `Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>`
  리뷰 전용 모델은 co-author 제외. 이메일 주소는 현재 GitHub "Claude" 계정으로 매핑돼 co-author 아바타가 정상 표시됨.
  (author/git 신원은 소유자 noreply 유지 — 아래 'git 신원' 참조. 과거 선점자 이슈 · 잔여 캐시는
  `docs/troubleshooting/2026-06-28-github-contributor-misattribution.md`.)
- PR 본문: 7섹션 한국어 구조, `--body-file`로 전달, **Claude 서명 금지** (§2.7).
- GitHub Flow + squash merge, PR = Task.
- **자연스러운 한국어 (2026-07-20 확정)**: 커밋 본문 · PR 본문 · docs 산문은 작업 중 만든 내부 용어 · 은유 · 압축 명사구 없이,
  처음 읽는 사람이 대화 맥락 없이 이해할 문장으로 쓴다 (누적 사례집은 세션 메모리 natural-korean-in-commits-prs).
  PR 본문 · 트러블슈팅 · 런북처럼 산문 비중이 큰 산출물은 게시 전에 humanize-korean 스킬 (fast) 문체 점검을 1회 통과시킨다
  — 무변경 판정이면 그대로 게시, 변경 제안은 반영. 한 줄 제목 · 표 · 코드 블록 · 몇 줄짜리 설정 PR 은 대상 아님.
  호출 시 서식 규칙 (§2.2) · 명사형 불릿 · 수치 · 경로를 변경 금지 목록으로 명시할 것.

## 병렬 세션 · 워크트리 (2026-08-20 확정)

여러 세션을 동시에 굴릴 때는 **각 세션을 자기 워크트리에서 시작한다.** 한 세션의 편집이 다른 세션 파일을 건드리지 않게 하는 장치다.

```bash
claude --worktree <이름>      # 예: claude --worktree facet-count
```

- 위치 `.claude/worktrees/<이름>/` · 브랜치 `worktree-<이름>` · 기준은 `origin/HEAD` (Claude Code 가 24시간 내 fetch 이력이 없으면 새로 받는다).
- **정리는 세션을 끝낼 때 자동이다** — 변경이 없으면 워크트리와 브랜치가 지워지고, 있으면 유지할지 묻는다.
  손으로 만든 워크트리는 이 자동 정리를 안 타서 주인 없이 남는다 (실제로 나흘 묵은 잔여물이 나왔다).
- `.env` · `x_cookies.json` 은 `.worktreeinclude` 에 적혀 있어 새 워크트리에 자동 복사된다.
  이 프로젝트는 dotenv 를 안 쓰므로 그 파일이 없으면 워크트리에서 운영 작업이 안 된다.
- **`git worktree add` 는 특정 기존 브랜치를 열거나 저장소 밖에 둘 때만 쓴다.**
  그때는 지울 것이 셋이다 — 디렉터리 · 로컬 브랜치 · 원격 브랜치.
- 메인 체크아웃의 브랜치는 바꾸지 않는다 (다른 세션이 그 자리를 기준선으로 본다).
- 워크트리 안에서 파이썬을 돌릴 때는 `uv run --project <워크트리>` 로 고정한다 — 셸 작업 디렉터리가 되돌아가 옛 브랜치 코드를 읽은 일이 있었다.

**세션 사이의 조정은 워크트리가 해 주지 않는다.** 파일 격리만 된다.
점유 파일 · 메모리 절 · 안건 이름은 세션끼리 알려야 하고, 그 규율은 세션 메모리에 있다.

## 공개 저장소 주의
- 공개되는 글 (README · PR · 커밋)에 Claude 서명, '포트폴리오/이직/취업' 프레이밍, 회사 실명 금지.
- 동기는 실제 제품 관점 (아스날 팬, 흩어진 현지 언론 · ITK 한곳 모으기)으로 서술.

## 설계 · 계획 · 상태
- 스펙: `docs/superpowers/specs/`, 계획: `docs/superpowers/plans/`.
- 트러블슈팅: `docs/troubleshooting/`, 런북: `docs/runbook/`.
- 산출물 본문은 한국어로 작성.
- **서식 (필독, 초안부터 적용)**: spec · plan · runbook · troubleshooting 등 모든 생성 문서에 컨벤션 §2.2를 적용한다.
  `→` · `—`는 줄 시작 (줄 끝 금지), 한 줄 = 한 문장 (마침표로 끊기면 줄 분리), `·` · `+` · 여는 괄호 양옆 띄우기 (코드 · URL · 경로 제외).
  `docs/` 아래 .md 저장 시 PostToolUse 훅 (`.claude/hooks/check-doc-format.py`)이 이 규칙을 자동 검사한다.

## 자주 밟는 함정
- **소스 셀렉터 드리프트**: `config/sources.yaml`의 selector/feed_url은 외부 사이트에 의존해 깨진다.
  신규/변경 소스는 머지 전 어댑터 단독 `fetch()`로 라이브 검증할 것 (단위 테스트는 모킹이라 못 잡음).
  사례: `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`.
- **Gemini 429 · 요금**: ~15 RPM은 분당 *속도* 한도 (총량 아님). enrich는 429 식별 시 그 회차를 즉시 중단 · `WARNING` 로깅 (파싱 실패와 구분), 남은 건은 다음 사이클 누적. per-row 백오프는 두지 않음 (스케줄이 재시도).
  **요금은 무료가 아니다** — 운영 키가 물린 AI Studio `bullet-in` 프로젝트는 Tier 1 · 선불이고 실제로 과금되고 있다. 비용 · 소요를 따질 때 무료 티어를 전제하지 말 것.
  **금액은 적어 두지 말고 조회한다** — 여기 적혀 있던 「2026-07 월 약 ₩700」 이 2026-08-24 확인에서 실제의 1/7 로 드러났다 (7월 약 ₩5,100 · 8월 예상 ₩6,470 · 입력 토큰 SKU 가 직전 기간 대비 +113%).
  조회 = GCP 결제 → 보고서 → 그룹화 기준을 **서비스** 와 **프로젝트** 로 각각 (두 잣대가 같은 값을 가리키는지 함께 본다). 등급은 AI Studio 프로젝트 화면에서 확인한다.
  잔존 수렴 경로도 하루 8회 스케줄만 있는 것이 아니다 — 급하면 fetch 없이 enrich만 재실행한다 (`docs/runbook/2026-07-19-enrich-only-pass.md`).
- **스키마 부트스트랩**: `run.py`가 `MartStore.ensure_schema()`로 `schema.sql`을 멱등 적용 (`CREATE TABLE IF NOT EXISTS`)한다. 수동 적용 불필요.
- **git 신원**: `benidjor <94089198+benidjor@users.noreply.github.com>`로 커밋 (다른 이메일 금지).
