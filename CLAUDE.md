# CLAUDE.md — bullet-in

아스날 FC 뉴스 수집 파이프라인. 다중 소스(RSS/HTML/Playwright/X)를 asyncio 병렬 수집 →
MongoDB(raw) → MariaDB(mart, content_hash·URL UNIQUE dedup) → Gemini 번역/요약 →
dbt 품질 게이트(DuckDB) → 정적 HTML 서빙. 스케줄은 Airflow.

스택: Python 3.11, uv, pydantic v2, httpx+BeautifulSoup, Playwright, twikit, google-genai, SQLAlchemy.

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
- 요청하지 않은 "유연성"·"설정성" 없음.
- 일어날 수 없는 시나리오용 에러 처리 없음.
- 200줄로 짠 게 50줄이면 될 것 같으면 다시 쓴다.

자문: "시니어 엔지니어가 과하게 복잡하다고 할까?" 그렇다면 단순화한다.

### 3. 수술적 변경 (Surgical Changes)
**꼭 필요한 것만 건드린다. 네가 만든 것만 치운다.**

기존 코드를 고칠 때:
- 인접 코드·주석·포맷을 "개선"하지 않는다.
- 안 깨진 것을 리팩터하지 않는다.
- 다르게 하고 싶어도 기존 스타일에 맞춘다.
- 무관한 죽은 코드는 **언급만** 하고 삭제하지 않는다.
- 네 변경이 만든 고아(import·변수·함수)만 제거한다. 기존 죽은 코드는 요청 없으면 두라.

테스트: 바뀐 모든 줄이 사용자 요청에 직접 추적돼야 한다.

### 4. 목표 주도 실행 (Goal-Driven Execution)
**성공 기준을 정의하고, 검증될 때까지 루프한다.**

작업을 검증 가능한 목표로 바꾼다:
- "검증 추가" → "잘못된 입력 테스트를 쓰고 통과시킨다"
- "버그 수정" → "재현 테스트를 쓰고 통과시킨다"
- "X 리팩터" → "전후로 테스트가 통과하도록 한다"

다단계 작업은 간단한 계획을 명시한다(`단계 → 검증: 체크`).
강한 성공 기준은 독립적으로 루프하게 해준다. 약한 기준("그냥 되게")은 계속 되묻게 만든다.

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
첫 라이브 실행 절차·제약: `docs/runbook/live-e2e-bootstrap.md`.

## 커밋 & PR 컨벤션 (필독)
SoT: `docs/conventions/2026-06-11-commit-pr-convention.md`. 핵심:
- 커밋: `<type>(<scope>): 한국어 제목` + 본문(왜) + `Refs:` + 트레일러. type/scope는 영어.
- **트레일러 이메일은 반드시 소유자 GitHub noreply**:
  `Co-Authored-By: Claude Opus <버전> (1M context) <94089198+benidjor@users.noreply.github.com>`
  공용 `noreply@anthropic.com`을 쓰면 그 주소를 선점한 제3자에게 co-author로 귀속됨(금지).
- PR 본문: 7섹션 한국어 구조, `--body-file`로 전달, **Claude 서명 금지**(§2.7).
- GitHub Flow + squash merge, PR = Task.

## 공개 저장소 주의
- 공개되는 글(README·PR·커밋)에 Claude 서명, '포트폴리오/이직/취업' 프레이밍, 회사 실명 금지.
- 동기는 실제 제품 관점(아스날 팬, 흩어진 현지 언론·ITK 한곳 모으기)으로 서술.

## 설계·계획·상태
- 스펙: `docs/superpowers/specs/`, 계획: `docs/superpowers/plans/`.
- 트러블슈팅: `docs/troubleshooting/`, 런북: `docs/runbook/`.
- 산출물 본문은 한국어로 작성.

## 자주 밟는 함정
- **소스 셀렉터 드리프트**: `config/sources.yaml`의 selector/feed_url은 외부 사이트에 의존해 깨진다.
  신규/변경 소스는 머지 전 어댑터 단독 `fetch()`로 라이브 검증할 것(단위 테스트는 모킹이라 못 잡음).
  사례: `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`.
- **Gemini 무료 티어 429**: ~15 RPM이라 회당 ~15건만 번역됨. enrich는 429를 조용히 삼킴(로그 개선 TODO).
- **스키마 수동 적용**: `run.py`는 테이블을 안 만든다. 첫 실행 전 `src/bullet_in/storage/schema.sql` 적용(런북 참조).
- **git 신원**: `benidjor <94089198+benidjor@users.noreply.github.com>`로 커밋(다른 이메일 금지).
