# 번역 신뢰성 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 원문 본문 없이 지어낸 한국어 본문을 없애고, 재료가 없으면 본문을 생성하지 않도록 파이프라인을 고친다.

**Architecture:** 수집 단계에서 게시글 본문을 폴백 재료로 확보하고 (등급 1), 번역 라우팅을 매체명 대신 본문 출처 등급으로 가른다.
생성은 개정 프롬프트로 하고, 숫자 누락 · 원문 복제를 규칙 코드로 판정해 재생성을 트리거한다 (폐기하지 않는다).
재료가 아예 없는 행은 제목만 번역하고 본문 · 요약을 생성하지 않는다.

**Tech Stack:** Python 3.11 · uv · pydantic v2 · httpx + BeautifulSoup · SQLAlchemy · MariaDB · google-genai (`gemini-3.1-flash-lite`) · Jinja2 · pytest.

## Global Constraints

스펙 (`docs/superpowers/specs/2026-07-29-translation-trust-design.md`) 과 저장소 규칙에서 그대로 옮긴 값이다.
모든 Task 의 요구사항에 이 절이 암묵적으로 포함된다.

- **선행 조건** — 수집 가드 PR (`body_level` · 3단 사다리 · 바이라인 함수 둘) 이 main 에 머지된 뒤에 착수한다.
PR #156 이 그 변경이다.
머지 전에 `fmkorea` 본문을 채우면 그 URL 이 등급 2 로 굳어 언론사 원문이 들어올 길이 막힌다.
- **본문 출처 등급** — `0` 본문 없음 · `1` 게시글 본문 (커뮤니티가 옮긴 것) · `2` 언론사 본문 (원문에서 받은 것).
컬럼은 `articles.body_level TINYINT`.
- **복제 게이트 임계값** — `0.75` 로 시작한다.
본문의 생사를 정하는 값이 아니라 재시도 횟수를 정하는 값이다 (스펙 §6.5).
Task 10 에서 실제 분포를 보고 확정한다.
- **재생성 상한** — 한 행당 최대 3회 시도 (첫 생성 1회 + 재생성 2회).
- **게이트는 재생성 트리거이지 폐기 조건이 아니다** — 누락 · 복제를 이유로 본문을 버리지 않는다.
44건에 폐기 규칙을 적용했을 때 잃은 4건은 오히려 개선된 행이었다 (스펙 §4.4).
- **잔존율 잣대** — 글자 8-gram.
어절 n-gram 은 조사 변경에 과민해 쓰지 않는다 (`docs/troubleshooting/2026-07-29-llm-metric-artifacts.md` §2.4).
- **숫자 집계 보정 3종 필수** — URL 제거 · 바이라인 발행 날짜 · 시각 제거 · 단위 환산 동일시.
하나라도 빠뜨리면 수치가 통째로 틀린다 (같은 문서 §3).
- **트윗 소스 예외** — `BODY_AS_TITLE_SOURCES = {"x_afcstuff", "x_ornstein"}` 는 `title_original` 에 트윗 전문이 있어 재료가 갖춰져 있다.
재발 방지 게이트에서 빠지지 않는다.
- **Gemini 는 실제 과금 계정이다** (Tier 1 선불 · AI Studio `bullet-in` 프로젝트).
이 계획의 라이브 호출 예상 규모는 Task 10 의 26건 × 평균 1.5회 = 약 40회다.
호출 규모를 바꾸는 변경은 실행 전에 사용자에게 알린다.
- **라이브 사이트 접촉 규율** — fmkorea 접촉 명령은 `tee` 로 로그를 남기고, 출력을 다시 보려고 재실행하지 않는다 (430 유발 전례 2회).
요청 간격은 기존 상수 `REQUEST_GAP_SEC = 1.5` 를 쓴다.
- **git 신원** — `benidjor <94089198+benidjor@users.noreply.github.com>`.
커밋은 `<type>(<scope>): 한국어 제목` + 도입 문장 + 명사형 불릿 + `Refs:` + co-author 트레일러 (`docs/conventions/2026-06-11-commit-pr-convention.md`).
- **머지는 사용자가 직접 한다** — 세션은 push 와 PR 생성까지만 한다.
- **TDD** — 모든 Task 는 실패하는 테스트를 먼저 쓰고, 실패를 눈으로 확인한 뒤 구현한다.
- **문서 서식** — `docs/` 아래 `.md` 는 PostToolUse 훅 (`.claude/hooks/check-doc-format.py`) 이 컨벤션 §2.2 를 검사한다.

---

## 파일 구조

이 계획이 만들거나 고치는 파일과 각 파일의 책임이다.

| 파일 | 책임 | Task |
| --- | --- | --- |
| `config/sources.yaml` | football.london 수집 중단 | 1 |
| `src/bullet_in/adapters/fmkorea.py` | 원문 fetch 실패 시 게시글 본문 폴백 · 발행 날짜 정규식 공개 | 2 · 5 |
| `src/bullet_in/storage/mariadb.py` | `body_level` 을 번역 대상 행에 실어 보냄 · 잔존율 저장 · ops 집계 | 3 · 7 |
| `src/bullet_in/storage/schema.sql` | `rewrite_retention` 컬럼 | 7 |
| `src/bullet_in/enrich.py` | 프롬프트 개정 · 등급 기반 라우팅 · 재생성 루프 · 재발 방지 게이트 | 3 · 4 · 6 · 8 |
| `src/bullet_in/fidelity.py` (신규) | 충실도 판정 — 숫자 누락 · 글자 8-gram 잔존율 · 최선 시도 선택 | 5 |
| `src/bullet_in/backfill_fmkorea_body.py` (신규) | 본문 빈 fmkorea 행에 게시글 본문 채우기 (1회성 · 멱등) | 9 |
| `src/bullet_in/run.py` | 회차 배선 — 라우팅 · 재생성 루프 · 잔존율 기록 | 3 · 6 · 7 · 8 |
| `src/bullet_in/serve/render.py` | 본문 없는 행의 상세 페이지 안내문 플래그 | 8 |
| `src/bullet_in/serve/templates/detail.html.j2` | 안내문 분기 | 8 |
| `src/bullet_in/serve/templates/ops.html.j2` | 잔존율 높은 행 목록 | 7 |

`fidelity.py` 를 `enrich.py` 안에 두지 않는 이유는 두 가지다.
`enrich.py` 가 이미 544줄이고, 충실도 판정은 LLM 호출이 전혀 없는 순수 규칙 코드라 경계가 뚜렷하다.

---

## Task 1: football.london 소스 제거

스펙 §4.6.
다른 Task 와 독립이므로 먼저 끝낸다.

**Files:**
- Modify: `config/sources.yaml:63` (football_london 항목)
- Test: `tests/test_serving_config.py` (신규 테스트 추가)
- 운영 절차: 이 Task 의 Step 5–8 (VM 에서 실행)

**Interfaces:**
- Consumes: 없음
- Produces: 없음 (뒤 Task 는 이 Task 에 의존하지 않는다)

- [ ] **Step 1: 수집 중단 계약을 고정하는 실패 테스트를 쓴다**

`tests/test_serving_config.py` 끝에 추가한다.

```python
def test_football_london_collection_disabled():
    """저품질 기사 비중이 높아 소스를 내렸다 (스펙 2026-07-29 §4.6).
    항목 자체는 남긴다 — 지우면 serving 모드 계약 검사에서도 사라져 되살아난 것을 못 잡는다."""
    data = yaml.safe_load((Path(__file__).parent.parent / "config" / "sources.yaml")
                          .read_text(encoding="utf-8"))
    fl = next(s for s in data["sources"] if s["source_id"] == "football_london")
    assert fl.get("enabled") is False
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serving_config.py::test_football_london_collection_disabled -v`
Expected: FAIL — `assert None is False`

- [ ] **Step 3: 설정을 고친다**

`config/sources.yaml` 의 `- source_id: football_london` 블록 안에 `display_name` 다음 줄로 넣는다.

```yaml
    enabled: false      # 저품질 기사 비중 · 상위 티어 중복 (스펙 2026-07-29 §4.6)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_serving_config.py -q && uv run pytest -q`
Expected: 전부 PASS.
`load_sources` 가 `enabled: false` 를 걸러내므로 (`score.py:6`) 어댑터도 만들어지지 않는다 (`factory.py:17`).

- [ ] **Step 5: 커밋한다**

```bash
git add config/sources.yaml tests/test_serving_config.py
git commit -m "$(cat <<'EOF'
chore(ingest): football.london 수집 중단

저품질 기사 비중이 높고 신뢰할 만한 내용은 상위 티어 매체가 함께 다뤄
소스를 내린다. 적재된 95행 제거는 운영 절차로 뒤따른다.

- 설정: football_london 항목에 enabled: false (항목은 남겨 되살아남 감시)
- 애그리게이터 경로: x_backtrack 으로 들어오는 football.london 기사는 계속 허용

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §4.6
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: 삭제 대상을 전량 덤프한다 (VM)**

DB 를 건드리는 단계는 여기부터다.
반드시 이 순서로 한다 — 설정 반영이 삭제보다 먼저다.
순서가 바뀌면 다음 회차가 다시 수집한다.

```bash
# VM 에서 실행 · 덤프는 저장소 밖 (~/) 에 둔다
set -a; source .env; set +a
mysqldump --single-transaction --no-create-info \
  --where="source_id='football_london'" bulletin articles \
  > ~/football-london-95rows-$(date +%Y%m%d).sql
wc -l ~/football-london-95rows-*.sql      # 비어 있지 않은지 확인
```

- [ ] **Step 7: 행을 삭제한다 (VM)**

```bash
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.begin() as c:
    before = c.execute(text("SELECT COUNT(*) FROM articles")).scalar_one()
    n = c.execute(text("DELETE FROM articles WHERE source_id='football_london'")).rowcount
    after = c.execute(text("SELECT COUNT(*) FROM articles")).scalar_one()
print(f"삭제 {n}행 · 전체 {before} → {after}")
PY
```

Expected: 삭제 95행 안팎 (스냅샷 시점에 따라 다르다) · 전체 467 → 372 안팎.

- [ ] **Step 8: 렌더 · 배포하고 잔재를 확인한다 (VM)**

```bash
uv run python -m bullet_in.run --concurrency 8    # 또는 렌더만 도는 런북 절차
ls site/article/*.html | wc -l                    # sweep_orphan_pages 가 95개를 지웠는지
grep -ric "football" site/index.html site/all.html | head
```

- **확인 사항** — 배포 가드는 산출물 50건 미만에서만 중단하므로 (`infra/deploy-site.sh`) 372건은 걸리지 않음.
- **확인 사항** — 기자 필터에 `Tom Canton` · 언론사 목록에 `football.london` 이 남지 않음.

---

## Task 2: fmkorea 원문 fetch 실패 시 게시글 본문 폴백

스펙 §4.1.
원문 URL 재수집은 26건 중 1건만 성공했으므로 (스펙 §6.2) 이미 받아 둔 게시글 HTML 을 재료로 쓴다.

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py:271-285` (`_process` 의 `else` 분기)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: `strip_publish_datetime(body) -> str` · `extract_body_journalist(body) -> str | None` · `_body_text(html, selector) -> str` · `_is_repost_blocked(html) -> bool` — 모두 같은 모듈에 이미 있다 (PR #156).
- Produces: `raw_payload` 에 `body_level == 1` · `lang == "ko"` 를 싣는 폴백 경로.
Task 3 의 라우팅이 이 값을 읽는다.

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/test_fmkorea_adapter.py` 끝에 추가한다.
`_one_post` 헬퍼와 `BLOCKED_PAY_POST` 픽스처는 같은 파일에 이미 있다.

```python
@respx.mock
def test_fmkorea_falls_back_to_post_body_when_original_fetch_fails():
    # 원문 재수집은 26건 중 1건만 성공했다 (스펙 §6.2) — 게시글 본문을 재료로 채택
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(403))
    items = asyncio.run(_one_post(FREE_BODY, title="[텔레그래프] 아스날 소식").fetch())
    assert items[0].raw_payload["body"] == "아스날 본문. https://ex.test/a"
    assert items[0].raw_payload["body_level"] == 1
    assert items[0].raw_payload["lang"] == "ko"


@respx.mock
def test_fmkorea_fallback_skipped_when_repost_blocked():
    # 퍼가기 금지 글은 폴백에서도 본문을 복제하지 않는다 (스펙 §4.1)
    blocked = BLOCKED_PAY_POST.replace("https://www.nytimes.com/athletic/9/b",
                                       "https://ex.test/a")
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(403))
    items = asyncio.run(_one_post(blocked, title="[텔레그래프] 아스날 소식").fetch())
    assert items[0].raw_payload["body"] == ""
    assert items[0].raw_payload["body_level"] == 0
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_fmkorea_adapter.py -q -k "falls_back_to_post_body or fallback_skipped"`
Expected: FAIL — 첫 테스트가 `assert '' == '아스날 본문. https://ex.test/a'`.

- [ ] **Step 3: 폴백을 구현한다**

`_process` 의 `else` 분기 (`lang = "en"` 이 있는 쪽) 를 이렇게 바꾼다.

```python
            else:
                try:
                    ro = await c.get(orig)
                    ro.raise_for_status()
                    body = extract_article_body(ro.text)
                    image = extract_og_image(ro.text)
                    images = extract_body_images(ro.text, base_url=orig)
                    pub = extract_published_at(ro.text)
                    lang = "en"
                    material_level = 2    # 채택한 재료 = 원문 URL 에서 받은 언론사 본문
                except httpx.HTTPError:
                    # 원문 차단 (실측 26건 중 25건이 406 · 403 · 페이월) — 게시글 본문으로 폴백.
                    # 퍼가기 금지 글은 지금처럼 본문 없이 진행한다 (스펙 §4.1).
                    image, images = None, []
                    if _is_repost_blocked(html):
                        body, lang, material_level = "", "en", 2
                    else:
                        log.info("fmkorea 원문 접속 실패 — 게시글 본문 채택 url=%s", orig)
                        body = _body_text(html, self.body_selector)
                        lang, material_level = "ko", 1
```

`material_level` 은 PR #156 이 넣은 지역 변수다.
그다음 줄들 (`body = strip_publish_datetime(body)` · `journalist = journalist or extract_body_journalist(body)` · `body_level = material_level if body else 0`) 은 그대로 두면 폴백 본문에도 적용된다.

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_fmkorea_adapter.py -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "$(cat <<'EOF'
feat(adapters): fmkorea 원문 차단 시 게시글 본문 폴백

원문 기사 URL 재수집은 26건 중 1건만 성공했다 (406 · 403 · 페이월).
매체 쪽 차단이라 프록시와 무관하고, 이미 받아 둔 게시글 HTML 이 유일하게
남은 재료다. 페이월 경로가 이미 같은 방식으로 동작하고 있어 경로를 새로
만들지 않는다.

- 폴백: 원문 fetch 실패 시 게시글 본문 채택 · 등급 1 · lang ko
- 예외: 퍼가기 금지 글은 본문 없이 진행 (등급 0)
- 이미지: 원문에서 받지 못하므로 게시글 이미지도 싣지 않음

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §4.1
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 번역 라우팅을 본문 출처 등급으로 가른다

스펙 §4.2.
`partition_by_paywall` 은 `outlet` 문자열만 보므로, 게시글 본문을 채택한 행 (outlet = The Telegraph) 이 번역 모드로 가서 한국어를 한국어로 번역하게 된다.

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py:83-88` (`rows_missing_translation`)
- Modify: `src/bullet_in/enrich.py:348-352` (`partition_by_paywall` 을 대체)
- Modify: `src/bullet_in/run.py:82-87`
- Test: `tests/test_enrich.py` · `tests/integration/test_mariadb_store.py`

**Interfaces:**
- Consumes: `articles.body_level` (PR #156) · Task 2 가 폴백 행에 싣는 등급 1.
- Produces: `partition_by_body_level(rows) -> tuple[list[dict], list[dict]]` — `(rewrite_rows, translate_rows)`.
`rewrite_rows` 는 `body_level == 1` 인 행이다.
Task 6 이 이 함수의 반환을 받는다.

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/test_enrich.py` 끝에 추가한다.

```python
def test_partition_by_body_level_routes_post_body_to_rewrite():
    from bullet_in.enrich import partition_by_body_level
    rows = [
        {"content_hash": "h1", "body_level": 1, "outlet": "The Telegraph"},
        {"content_hash": "h2", "body_level": 2, "outlet": "BBC"},
        {"content_hash": "h3", "body_level": 0, "outlet": None},
    ]
    rewrite, translate = partition_by_body_level(rows)
    assert [r["content_hash"] for r in rewrite] == ["h1"]
    assert [r["content_hash"] for r in translate] == ["h2", "h3"]


def test_partition_by_body_level_ignores_outlet_string():
    """매체명으로 가르면 표기 변종 (더 선 · 더선 · 더썬) 마다 갈린다 (스펙 §4.2)."""
    from bullet_in.enrich import partition_by_body_level
    rows = [{"content_hash": "h1", "body_level": 2, "outlet": "The Athletic"}]
    rewrite, translate = partition_by_body_level(rows)
    assert rewrite == []
    assert len(translate) == 1


def test_partition_by_body_level_treats_null_level_as_translate():
    """백필 전 레거시 행 (NULL) 은 재작성 모드로 보내지 않는다 — 한국어 여부를 모른다."""
    from bullet_in.enrich import partition_by_body_level
    rewrite, translate = partition_by_body_level([{"content_hash": "h1", "body_level": None}])
    assert rewrite == [] and len(translate) == 1
```

`tests/integration/test_mariadb_store.py` 끝에 추가한다.

```python
def test_rows_missing_translation_includes_body_level(engine):
    # 라우팅 입력 (스펙 §4.2) — 등급이 없으면 재작성 · 번역을 가를 수 없다
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="hb", url="https://x.test/bl", source_id="fmkorea",
                          title_original="퍼온 제목", body_source="옮긴 본문", body_level=1,
                          published_at=datetime(2026, 7, 27, tzinfo=timezone.utc))])
    row = next(r for r in store.rows_missing_translation() if r["content_hash"] == "hb")
    assert row["body_level"] == 1
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_enrich.py tests/integration/test_mariadb_store.py -q -k "body_level"`
Expected: FAIL — `ImportError: cannot import name 'partition_by_body_level'` · `KeyError: 'body_level'`.

- [ ] **Step 3: 구현한다**

`src/bullet_in/storage/mariadb.py` 의 `rows_missing_translation` SELECT 에 컬럼을 더한다.

```python
    def rows_missing_translation(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT content_hash,source_id,title_original,body_excerpt,"
                "body_source,body_level,outlet,summary_ko "
                "FROM articles WHERE title_ko IS NULL")).mappings().all()
        return [dict(r) for r in rows]
```

`src/bullet_in/enrich.py` 의 `partition_by_paywall` 을 지우고 그 자리에 넣는다.

```python
POST_BODY_LEVEL = 1     # 게시글 본문 — 커뮤니티가 옮긴 것 (수집 라인 트랙 계약)

def partition_by_body_level(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(재작성 행, 번역 행) — 본문 출처 등급으로 가른다.

    등급 1 은 이미 한국어라 번역이 아니라 재작성 대상이다.
    매체명 문자열로 가르면 표기 변종마다 갈린다 (배포판에 '더 선' · '더선' · '더썬'
    이 따로 존재한다 — 스펙 §4.2). 등급이 없는 레거시 행은 번역 쪽으로 보낸다."""
    rewrite, trans = [], []
    for r in rows:
        (rewrite if r.get("body_level") == POST_BODY_LEVEL else trans).append(r)
    return rewrite, trans
```

`src/bullet_in/run.py:82-87` 을 바꾼다.

```python
    from bullet_in.enrich import partition_by_body_level
    missing = mart.rows_missing_translation()
    rewrite_rows, translate_rows = partition_by_body_level(missing)
    results: dict[str, dict] = {}
    results.update(enrich_rows(translate_rows, client, GEMINI_MODEL, mode="translate"))
    results.update(enrich_rows(rewrite_rows, client, GEMINI_MODEL, mode="paraphrase"))
```

`partition_by_paywall` 을 지우면 `enrich.py:6` 의 `PAYWALLED_OUTLETS` 가 이 모듈에서 고아가 된다.
내 변경이 만든 고아이므로 함께 지운다 — 단 `adapters/fmkorea.py` 의 같은 이름 상수는 수집 경로가 쓰고 있으니 건드리지 않는다.
지우기 전에 `grep -rn "enrich import.*PAYWALLED\|enrich.PAYWALLED" src tests` 로 외부 참조가 없음을 확인한다.

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest -q`
Expected: 전부 PASS.
`partition_by_paywall` 을 참조하는 테스트가 있으면 함께 고친다 (`grep -rn partition_by_paywall tests src`).

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/enrich.py src/bullet_in/storage/mariadb.py src/bullet_in/run.py \
        tests/test_enrich.py tests/integration/test_mariadb_store.py
git commit -m "$(cat <<'EOF'
refactor(enrich): 번역 라우팅을 매체명에서 본문 출처 등급으로 교체

게시글 본문을 채택한 행은 outlet 이 The Telegraph 라서, 매체명으로 가르면
한국어 본문을 번역 모드로 보내 한국어를 한국어로 번역하게 된다. 매체명
문자열 자체도 표기 변종이 많아 판정 기준으로 취약하다.

- 라우팅: body_level 1 이면 재작성 · 그 밖은 번역
- 조회: rows_missing_translation 이 body_level 을 함께 실어 보냄
- 레거시: 등급 NULL 행은 번역 쪽 유지 (한국어 여부를 알 수 없음)

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §4.2
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 재작성 프롬프트 개정

스펙 §4.3.
프롬프트 다섯 판본을 각각 두 번씩 돌려 고른 조합이다 (스펙 §6.3).

**Files:**
- Modify: `src/bullet_in/enrich.py:60-77` (`PARAPHRASE_PROMPT`)
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: 없음
- Produces: 개정된 `PARAPHRASE_PROMPT`.
Task 6 이 이것을 첫 시도 프롬프트로 쓴다.

- [ ] **Step 1: 실패 테스트를 쓴다**

프롬프트 문자열 테스트는 어색하지만, 이 조항들이 조용히 사라지면 6.3절 측정이 무효가 된다.
조항 존재를 계약으로 고정한다.

```python
def test_paraphrase_prompt_carries_completeness_and_no_injection_rules():
    """다섯 판본 비교에서 이 조합이 주입 4개 → 1개 · 없던 소제목 33개 → 9개로
    줄인 판본이다 (스펙 §6.3). 조항이 빠지면 측정 근거가 무효가 된다."""
    from bullet_in.enrich import PARAPHRASE_PROMPT
    for clause in ["모든 문단을 순서대로 빠짐없이",
                   "모든 숫자",
                   "원문에 없는 소제목을 만들지 않는다",
                   "역할 명칭",
                   "시간 · 정도 표현",
                   "원문 표기를 그대로",
                   "추측으로"]:
        assert clause in PARAPHRASE_PROMPT, clause
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_enrich.py -q -k "paraphrase_prompt_carries"`
Expected: FAIL — `AssertionError: 모든 문단을 순서대로 빠짐없이`.

- [ ] **Step 3: 프롬프트에 두 묶음을 더한다**

`PARAPHRASE_PROMPT` 의 `'ONLY JSON: ...'` 줄 바로 앞에 넣는다.

```python
    "- body_ko 는 요약이 아니라 전문 재작성이다: 원문의 모든 문단을 순서대로 "
    "빠짐없이 옮기고, 수치 · 인용 · 세부 사실을 임의로 줄이거나 합치지 않는다.\n"
    "- 원문에 나오는 모든 숫자 (금액 · 나이 · 연도 · 경기 수 · 기록) 를 하나도 "
    "빠뜨리지 않는다.\n"
    "- 원문에 없는 소제목을 만들지 않는다. 원문에 소제목이 없으면 산출물에도 "
    "소제목이 없다.\n"
    "- 원문에 없는 수식어 · 부사 · 역할 명칭 (미드필더 · 공격수 · 감독 등) 을 "
    "붙이지 않는다.\n"
    "- 원문에 없는 시간 · 정도 표현 (즉시 · 이미 · 크게 · 확고히 · 전격 등) 을 "
    "넣지 않는다.\n"
    "- 숫자는 원문 표기를 그대로 쓴다 (£50m 을 5,000만 파운드로 바꾸지 않는다).\n"
    "- 원문이 단정한 것을 추측으로, 추측한 것을 단정으로 바꾸지 않는다.\n"
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_enrich.py -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -m "$(cat <<'EOF'
feat(enrich): 재작성 프롬프트에 완역 · 주입 금지 조항 추가

프롬프트 다섯 판본을 각각 두 번씩 돌려 비교한 결과다. 완역 조항만 넣으면
누락은 줄지만 주입이 남고, 주입 금지까지 넣은 판본이 원문에 없던 소제목을
33개에서 9개로 줄였다. 세 축을 동시에 만족하는 프롬프트는 없어 게이트를
따로 붙인다 (다음 커밋).

- 완역: 모든 문단 순서 보존 · 모든 숫자 보존
- 주입 금지: 소제목 · 역할 명칭 · 시간 · 정도 표현 · 단위 환산 · 단정과 추측 뒤집기

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §4.3 · §6.3
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 충실도 판정 모듈

스펙 §4.4 의 게이트 ② · ③ 과 `docs/troubleshooting/2026-07-29-llm-metric-artifacts.md` §3 의 보정 3종.
LLM 을 쓰지 않는 순수 규칙 코드다.

**Files:**
- Create: `src/bullet_in/fidelity.py`
- Modify: `src/bullet_in/adapters/fmkorea.py` (`_PUBLISH_DT_RE` 를 `PUBLISH_DT_RE` 로 공개)
- Test: `tests/test_fidelity.py` (신규)

**Interfaces:**
- Consumes: `bullet_in.adapters.fmkorea.PUBLISH_DT_RE` — 바이라인 발행 날짜 · 시각 정규식.
같은 규칙을 두 곳에 적으면 어긋난다.
- Produces:
  - `missing_numbers(source: str, output: str) -> list[str]`
  - `char_ngram_retention(source: str, output: str, n: int = 8) -> float`
  - `gate_verdict(source: str, output: str, threshold: float = 0.75) -> dict` — `{"missing": list[str], "retention": float, "ok": bool}`
  - `select_best(attempts: list[dict]) -> dict` — `attempts` 원소는 `{"parsed": dict, "missing": list[str], "retention": float}`
  - `RETENTION_THRESHOLD = 0.75`

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/test_fidelity.py` 를 새로 만든다.

```python
from bullet_in.fidelity import (RETENTION_THRESHOLD, char_ngram_retention,
                                gate_verdict, missing_numbers, select_best)


def test_missing_numbers_reports_dropped_token():
    src = "아스날이 £50m 을 제안했고 계약은 2031년까지다."
    out = "아스날이 £50m 을 제안했다."
    assert missing_numbers(src, out) == ["2031"]


def test_missing_numbers_ignores_unit_conversion():
    # €80m → 8,000만 유로는 같은 값을 옮겨 적은 것이다 (트러블슈팅 §2.1)
    src = "이적료는 €80m 이다."
    out = "이적료는 8,000만 유로다."
    assert missing_numbers(src, out) == []


def test_missing_numbers_ignores_url_digits():
    # 본문 끝 원문 링크의 기사 ID · 날짜 경로가 원문 숫자로 잡히던 결함 (트러블슈팅 §2.3)
    src = "아스날 소식. https://www.nytimes.com/athletic/7404309/2026/07/24/arsenal/"
    out = "아스날 소식이다."
    assert missing_numbers(src, out) == []


def test_missing_numbers_ignores_byline_datetime():
    # 발행 시각은 바꿔 쓸 수 없어 '빠뜨리지 마라' 와 '베끼지 마라' 가 양립하지 않는다
    src = "By David Ornstein June 19, 2026 3:19 am 리버풀이 협상 중이다."
    out = "리버풀이 협상을 진행하고 있다."
    assert missing_numbers(src, out) == []


def test_missing_numbers_empty_when_source_has_no_digits():
    assert missing_numbers("아스날이 승리했다.", "아스날이 이겼다.") == []


def test_char_ngram_retention_is_one_for_verbatim_copy():
    text = "아스날이 비니시우스 주니오르 영입을 추진하고 있다는 보도가 나왔다."
    assert char_ngram_retention(text, text) == 1.0


def test_char_ngram_retention_is_zero_for_unrelated_text():
    src = "아스날이 비니시우스 주니오르 영입을 추진한다."
    out = "리버풀은 수비 보강에 집중하고 있는 상황이다."
    assert char_ngram_retention(src, out) == 0.0


def test_char_ngram_retention_zero_when_output_shorter_than_window():
    assert char_ngram_retention("아스날이 승리했다.", "승리") == 0.0


def test_gate_verdict_passes_clean_rewrite():
    src = "아스날이 £50m 을 제안했다. 계약 기간은 2031년까지로 알려졌다."
    out = "아스날은 £50m 규모의 제안을 건넸고, 계약은 2031년까지로 전해졌다."
    v = gate_verdict(src, out, threshold=0.9)
    assert v["missing"] == [] and v["ok"] is True


def test_gate_verdict_fails_on_missing_number():
    src = "아스날이 £50m 을 제안했다. 계약은 2031년까지다."
    out = "아스날이 제안을 건넸다."
    v = gate_verdict(src, out)
    assert v["missing"] and v["ok"] is False


def test_gate_verdict_fails_on_verbatim_copy():
    text = "아스날이 비니시우스 주니오르 영입을 추진하고 있다는 보도가 나왔다."
    v = gate_verdict(text, text)
    assert v["missing"] == []
    assert v["retention"] == 1.0 and v["ok"] is False


def test_select_best_prefers_no_missing_then_lowest_retention():
    attempts = [
        {"parsed": {"body_ko": "A"}, "missing": [], "retention": 0.80},
        {"parsed": {"body_ko": "B"}, "missing": [], "retention": 0.42},
        {"parsed": {"body_ko": "C"}, "missing": ["2031"], "retention": 0.20},
    ]
    assert select_best(attempts)["parsed"]["body_ko"] == "B"


def test_select_best_falls_back_to_fewest_missing():
    # 본문을 버리지 않는 설계 — 전부 누락이 있어도 하나는 채택한다 (스펙 §4.4)
    attempts = [
        {"parsed": {"body_ko": "A"}, "missing": ["1", "2", "3"], "retention": 0.20},
        {"parsed": {"body_ko": "B"}, "missing": ["1"], "retention": 0.70},
    ]
    assert select_best(attempts)["parsed"]["body_ko"] == "B"


def test_threshold_default_is_documented_value():
    assert RETENTION_THRESHOLD == 0.75
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_fidelity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.fidelity'`.

- [ ] **Step 3: 정규식을 공개 이름으로 바꾼다**

`src/bullet_in/adapters/fmkorea.py` 에서 `_PUBLISH_DT_RE` 를 `PUBLISH_DT_RE` 로 바꾸고 (선언 1곳 · 사용 1곳), 주석 한 줄을 붙인다.

```python
# 충실도 게이트도 같은 규칙으로 숫자 집계에서 발행 표기를 뺀다 (fidelity.py 가 import).
PUBLISH_DT_RE = re.compile(...)
```

- [ ] **Step 4: 모듈을 구현한다**

`src/bullet_in/fidelity.py` 를 새로 만든다.

```python
"""재작성 산출물의 충실도 판정 — 숫자 누락 · 원문 복제.

LLM 을 쓰지 않는 규칙 코드다. 판정 결과는 재생성 트리거로만 쓰고 본문을 버리지
않는다 (스펙 2026-07-29 §4.4).

숫자를 세기 전에 보정 세 가지를 반드시 적용한다. 하나라도 빠지면 수치가 통째로
틀린다 (docs/troubleshooting/2026-07-29-llm-metric-artifacts.md §3).
  ① URL 제거          — 기사 ID · 날짜 경로가 원문 숫자로 잡힌다
  ② 발행 날짜 · 시각 제거 — 원문 숫자의 7% 가 바이라인에서 온다
  ③ 단위 환산 동일시    — £50m 과 5,000만은 같은 값이다
"""
from __future__ import annotations
import re
from bullet_in.adapters.fmkorea import PUBLISH_DT_RE

RETENTION_THRESHOLD = 0.75    # 스펙 §6.5 — 재시도 횟수를 정하는 값 (본문 생사 아님)
NGRAM = 8                     # 글자 8-gram — 어절 n-gram 은 조사 변경에 과민 (§2.4)

_URL_RE = re.compile(r"https?://\S+")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")
_NUM_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


def _strip_noise(text: str) -> str:
    """숫자 집계 대상에서 URL 과 발행 날짜 · 시각을 뺀다 (보정 ① · ②)."""
    return PUBLISH_DT_RE.sub(" ", _URL_RE.sub(" ", text or ""))


def number_tokens(text: str) -> list[str]:
    """비교용 숫자 토큰 — 천단위 쉼표를 지운 뒤 연속 숫자를 뽑는다."""
    return _NUM_RE.findall(_THOUSANDS_RE.sub("", _strip_noise(text)))


def _variants(tok: str) -> set[str]:
    """단위 환산 후보 (보정 ③) — ×10 · ×100 · ×1000 · ÷100."""
    out = {tok}
    n = int(tok)
    for f in (10, 100, 1000):
        out.add(str(n * f))
    if n % 100 == 0:
        out.add(str(n // 100))
    return out


def missing_numbers(source: str, output: str) -> list[str]:
    """원문에 있고 산출물에 없는 숫자. 보정 3종을 적용한 뒤 비교한다."""
    out_tokens = set(number_tokens(output))
    missing = []
    for tok in number_tokens(source):
        if tok in missing:
            continue
        if not (_variants(tok) & out_tokens):
            missing.append(tok)
    return missing


def _ngrams(text: str, n: int) -> set[str]:
    s = _WS_RE.sub(" ", text or "").strip()
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else set()


def char_ngram_retention(source: str, output: str, n: int = NGRAM) -> float:
    """산출물 글자 n-gram 중 원문에도 있는 것의 비율. 산출물이 n 자 미만이면 0.0."""
    out_grams = _ngrams(output, n)
    if not out_grams:
        return 0.0
    src_grams = _ngrams(source, n)
    return len(out_grams & src_grams) / len(out_grams)


def gate_verdict(source: str, output: str,
                 threshold: float = RETENTION_THRESHOLD) -> dict:
    """{"missing": [...], "retention": float, "ok": bool} — ok 는 두 게이트 동시 통과."""
    missing = missing_numbers(source, output)
    retention = char_ngram_retention(source, output)
    return {"missing": missing, "retention": retention,
            "ok": not missing and retention <= threshold}


def select_best(attempts: list[dict]) -> dict:
    """세 시도 중 최선 — 누락 없는 것 중 잔존율 최소.
    전부 누락이 있으면 누락 수가 가장 적은 것, 그중 잔존율이 낮은 것.
    본문을 버리지 않으므로 항상 하나를 돌려준다."""
    return min(attempts, key=lambda a: (len(a["missing"]), a["retention"]))
```

- [ ] **Step 5: 통과를 확인한다**

Run: `uv run pytest tests/test_fidelity.py tests/test_fmkorea_adapter.py -q`
Expected: 전부 PASS.

- [ ] **Step 6: 커밋한다**

```bash
git add src/bullet_in/fidelity.py tests/test_fidelity.py src/bullet_in/adapters/fmkorea.py
git commit -m "$(cat <<'EOF'
feat(enrich): 충실도 판정 모듈 — 숫자 누락 · 글자 8-gram 잔존율

프롬프트 하나로 주입 · 누락 · 복제를 동시에 잡을 수 없다는 것이 판본 비교로
확인됐다. 그래서 규칙 코드로 두 방향을 판정한다. 채점 잣대 자체가 가짜 발견을
만든 사례가 다섯 번 있었으므로 보정 3종을 모듈 안에 붙여 둔다.

- 누락 게이트: 원문 숫자가 산출물에 남았는지 · 단위 환산은 같은 값으로 취급
- 복제 게이트: 글자 8-gram 잔존율 (어절 n-gram 은 조사 변경에 과민해 배제)
- 보정: URL 숫자 제거 · 바이라인 발행 표기 제거 (원문 숫자의 7%)
- 최선 선택: 누락 없는 시도 중 잔존율 최소 · 전부 누락이면 누락 최소

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §4.4,
      docs/troubleshooting/2026-07-29-llm-metric-artifacts.md §3
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 게이트 기반 재생성 루프

스펙 §4.4.
게이트에 걸리면 사유를 붙여 다시 생성하고, 세 시도 중 최선을 채택한다.

**Files:**
- Modify: `src/bullet_in/enrich.py` (`enrich_rows` 아래에 추가)
- Modify: `src/bullet_in/run.py:82-87`
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: `gate_verdict` · `select_best` · `RETENTION_THRESHOLD` (Task 5) · `PARAPHRASE_PROMPT` (Task 4) · `partition_by_body_level` (Task 3).
- Produces: `rewrite_rows_guarded(rows, client, model, threshold=RETENTION_THRESHOLD, max_attempts=3) -> tuple[dict[str, dict], dict[str, dict]]`.
첫 반환은 `enrich_rows` 와 같은 모양 (`{content_hash: parsed}`), 둘째는 `{content_hash: {"retention": float, "missing": list[str], "attempts": int}}`.
Task 7 이 둘째 반환을 저장한다.

- [ ] **Step 1: 실패 테스트를 쓴다**

Gemini 를 부르지 않도록 응답을 미리 정한 가짜 클라이언트를 쓴다.

```python
import json


class _FakeGemini:
    """정해진 응답을 순서대로 돌려주는 가짜 클라이언트 — 호출 프롬프트를 기록한다."""
    def __init__(self, bodies):
        self._bodies = list(bodies)
        self.prompts = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        body = self._bodies.pop(0)
        payload = {"title_ko": "제목", "summary_ko": "요약",
                   "summary3_ko": ["1", "2", "3"], "body_ko": body}
        return type("R", (), {"text": json.dumps(payload, ensure_ascii=False)})()


_SRC = "아스날이 £50m 을 제안했다. 계약 기간은 2031년까지로 알려졌다."


def _row(h="h1"):
    return {"content_hash": h, "title_original": "제목", "body_source": _SRC,
            "body_level": 1}


def test_rewrite_rows_guarded_adopts_first_attempt_when_gate_passes():
    from bullet_in.enrich import rewrite_rows_guarded
    clean = "아스날은 £50m 규모 제안을 건넸으며, 계약은 2031년까지로 전해진다."
    client = _FakeGemini([clean])
    results, reports = rewrite_rows_guarded([_row()], client, "m", threshold=0.9)
    assert results["h1"]["body_ko"] == clean
    assert reports["h1"]["attempts"] == 1
    assert len(client.prompts) == 1


def test_rewrite_rows_guarded_retries_with_missing_number_reason():
    from bullet_in.enrich import rewrite_rows_guarded
    dropped = "아스날이 제안을 건넸다."
    fixed = "아스날은 £50m 제안을 건넸고 계약은 2031년까지로 전해진다."
    client = _FakeGemini([dropped, fixed])
    results, reports = rewrite_rows_guarded([_row()], client, "m", threshold=0.9)
    assert results["h1"]["body_ko"] == fixed
    assert reports["h1"]["attempts"] == 2
    assert "누락" in client.prompts[1]
    assert "2031" in client.prompts[1]


def test_rewrite_rows_guarded_retries_with_duplication_reason():
    from bullet_in.enrich import rewrite_rows_guarded
    fixed = "아스날은 £50m 제안을 건넸고 계약은 2031년까지로 전해진다."
    client = _FakeGemini([_SRC, fixed])          # 1회차는 원문 그대로 복제
    results, reports = rewrite_rows_guarded([_row()], client, "m", threshold=0.75)
    assert results["h1"]["body_ko"] == fixed
    assert "복제" in client.prompts[1]
    assert "새로 넣지 않는다" in client.prompts[1]   # 주입 금지 동반 (스펙 §4.4)


def test_rewrite_rows_guarded_stops_at_max_attempts_and_keeps_best():
    from bullet_in.enrich import rewrite_rows_guarded
    # 세 시도 모두 게이트에 걸려도 본문을 버리지 않는다 (스펙 §4.4)
    client = _FakeGemini([_SRC, _SRC, "아스날이 £50m 을 제안했고 2031년까지 계약한다."])
    results, reports = rewrite_rows_guarded([_row()], client, "m", threshold=0.10)
    assert len(client.prompts) == 3
    assert results["h1"]["body_ko"] == "아스날이 £50m 을 제안했고 2031년까지 계약한다."
    assert reports["h1"]["attempts"] == 3
    assert reports["h1"]["retention"] < 1.0


def test_rewrite_rows_guarded_uses_body_excerpt_when_body_source_empty():
    from bullet_in.enrich import rewrite_rows_guarded
    row = {"content_hash": "h2", "title_original": "제목", "body_source": "",
           "body_excerpt": _SRC, "body_level": 1}
    client = _FakeGemini(["아스날은 £50m 제안을 건넸고 계약은 2031년까지다."])
    results, _ = rewrite_rows_guarded([row], client, "m", threshold=0.9)
    assert "h2" in results


def test_rewrite_rows_guarded_breaks_on_rate_limit():
    from bullet_in.enrich import rewrite_rows_guarded

    class _Boom:
        models = None
        def generate_content(self, model, contents, config):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    c = _Boom()
    c.models = c
    results, reports = rewrite_rows_guarded([_row(), _row("h9")], c, "m")
    assert results == {} and reports == {}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_enrich.py -q -k "rewrite_rows_guarded"`
Expected: FAIL — `ImportError: cannot import name 'rewrite_rows_guarded'`.

- [ ] **Step 3: 구현한다**

`src/bullet_in/enrich.py` 의 `enrich_rows` 아래에 넣는다.
파일 위쪽 import 에 `from bullet_in.fidelity import RETENTION_THRESHOLD, gate_verdict, select_best` 를 더한다.

```python
MISSING_RETRY = (
    "\n\n[누락] 직전 시도에서 다음 숫자가 누락됐다 — {tokens}.\n"
    "이 수치들을 원문 맥락 그대로 반드시 포함한다.")
DUPLICATE_RETRY = (
    "\n\n[복제] 직전 시도는 원문 표현을 지나치게 그대로 옮겼다.\n"
    "사실 · 수치 · 인용은 그대로 두되 문장 구성과 표현을 크게 바꿔 다시 쓴다.\n"
    "단 원문에 없는 내용 · 수식어 · 소제목을 새로 넣지 않는다.")

def rewrite_rows_guarded(rows: list[dict], client, model: str,
                         threshold: float = RETENTION_THRESHOLD,
                         max_attempts: int = 3
                         ) -> tuple[dict[str, dict], dict[str, dict]]:
    """게시글 본문 재작성 — 게이트에 걸리면 사유를 붙여 재생성하고 최선을 채택한다.

    게이트는 재생성 트리거이지 폐기 조건이 아니다 (스펙 §4.4).
    반환: (결과, 리포트) — 리포트는 잔존율 기록 · ops 노출용."""
    results: dict[str, dict] = {}
    reports: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        source = r.get("body_source") or r.get("body_excerpt") or ""
        base = PARAPHRASE_PROMPT.format(title=r["title_original"], body=source)
        attempts: list[dict] = []
        rate_limited = False
        for i in range(max_attempts):
            note = ""
            if attempts:
                last = attempts[-1]
                if last["missing"]:
                    note += MISSING_RETRY.format(tokens=", ".join(last["missing"]))
                if last["retention"] > threshold:
                    note += DUPLICATE_RETRY
            try:
                msg = client.models.generate_content(
                    model=model, contents=base + note,
                    config={"max_output_tokens": 8192,
                            "response_mime_type": "application/json"})
            except Exception as e:
                if _is_rate_limit(e):
                    log.warning("Gemini rate limit(429), 재작성 중단 — 남은 행 다음 사이클")
                    rate_limited = True
                    break
                log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
                break
            parsed = _extract_full(msg.text)
            if parsed is None:
                log.warning("Gemini 응답 파싱 실패, 스킵 content_hash=%s", h)
                break
            v = gate_verdict(source, parsed["body_ko"] or "", threshold)
            attempts.append({"parsed": parsed, "missing": v["missing"],
                             "retention": v["retention"]})
            if v["ok"]:
                break
        if rate_limited:
            break
        if not attempts:
            continue
        best = select_best(attempts)
        results[h] = best["parsed"]
        reports[h] = {"retention": best["retention"], "missing": best["missing"],
                      "attempts": len(attempts)}
        if best["retention"] > threshold or best["missing"]:
            log.warning("재작성 게이트 잔존 content_hash=%s 잔존율=%.3f 누락=%s 시도=%d",
                        h, best["retention"], best["missing"], len(attempts))
    return results, reports
```

재시도 지시는 루프 안에서 직전 시도의 판정을 보고 만든다.
누락과 복제가 함께 걸린 시도면 두 지시가 함께 붙는다.

`src/bullet_in/run.py` 의 enrich 배선을 바꾼다.

```python
    from bullet_in.enrich import partition_by_body_level, rewrite_rows_guarded
    missing = mart.rows_missing_translation()
    rewrite_rows, translate_rows = partition_by_body_level(missing)
    results: dict[str, dict] = {}
    results.update(enrich_rows(translate_rows, client, GEMINI_MODEL, mode="translate"))
    rewritten, gate_reports = rewrite_rows_guarded(rewrite_rows, client, GEMINI_MODEL)
    results.update(rewritten)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_enrich.py -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/enrich.py src/bullet_in/run.py tests/test_enrich.py
git commit -m "$(cat <<'EOF'
feat(enrich): 게이트 기반 재작성 재생성 루프

프롬프트만으로는 주입 · 누락 · 복제가 서로를 밀어내 세 축을 동시에 만족시킬 수
없다. 판정을 재생성 트리거로만 쓰고 세 시도 중 최선을 채택하면 44건 표본에서
전부 본문이 나오고 숫자 누락이 0개가 됐다.

- 재생성: 누락 · 복제 사유를 붙여 최대 2회 (첫 생성 포함 3회)
- 복제 지시: 주입 금지 문구 동반 (없으면 모델이 없는 내용으로 표현을 바꿈)
- 채택: 누락 없는 시도 중 잔존율 최소 · 본문 폐기 없음
- 429: 그 회차 즉시 중단 · 남은 행은 다음 사이클 (기존 규약과 동일)

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §4.4 · §6.5
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 잔존율 저장 · ops 노출

스펙 §7 — "잔존율 0.75 를 넘는 행 목록이 ops 에 노출되고 건수가 기록된다".
게이트를 통과하지 못한 채 채택된 행은 사람이 확인한다.

**Files:**
- Modify: `src/bullet_in/storage/schema.sql`
- Modify: `src/bullet_in/storage/mariadb.py` (`set_rewrite_retention` 추가 · `ops_snapshot` 확장)
- Modify: `src/bullet_in/run.py` (리포트 저장)
- Modify: `src/bullet_in/serve/render.py` (`build_ops_view`)
- Modify: `src/bullet_in/serve/templates/ops.html.j2`
- Test: `tests/integration/test_mariadb_store.py` · `tests/integration/test_ops_snapshot.py` · `tests/test_serve_ops.py`

**Interfaces:**
- Consumes: Task 6 의 `reports[h]["retention"]`.
- Produces: `MartStore.set_rewrite_retention(content_hash: str, retention: float) -> None` · `ops_snapshot()["high_retention"]` — `list[dict]` (`content_hash` · `outlet` · `retention`) · `build_ops_view(...)["high_retention"]`.

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/integration/test_mariadb_store.py` 에 추가한다.

```python
def test_set_rewrite_retention_and_high_retention_list(engine):
    # 게이트를 넘긴 채 채택된 행은 ops 로 올려 사람이 확인한다 (스펙 §7)
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([
        Article(content_hash="hr1", url="https://x.test/r1", source_id="fmkorea",
                title_original="T1", outlet="The Athletic", body_source="본문",
                body_level=1, published_at=datetime(2026, 7, 27, tzinfo=timezone.utc)),
        Article(content_hash="hr2", url="https://x.test/r2", source_id="fmkorea",
                title_original="T2", outlet="The Times", body_source="본문",
                body_level=1, published_at=datetime(2026, 7, 27, tzinfo=timezone.utc)),
    ])
    store.set_rewrite_retention("hr1", 0.93)
    store.set_rewrite_retention("hr2", 0.41)
    high = store.ops_snapshot()["high_retention"]
    assert [r["content_hash"] for r in high] == ["hr1"]
    assert high[0]["outlet"] == "The Athletic"
    assert round(high[0]["retention"], 2) == 0.93
```

`tests/test_serve_ops.py` 에 추가한다.

```python
def test_ops_view_lists_high_retention_rows():
    from bullet_in.serve.render import build_ops_view
    snap = {"runs": [], "freshness": [], "tier_counts": {}, "pending": {},
            "high_retention": [{"content_hash": "a" * 64, "outlet": "The Athletic",
                                "retention": 0.934}]}
    view = build_ops_view(snap, {}, anomaly_count=0,
                          now=datetime(2026, 7, 30, 12, 0, 0))
    assert view["high_retention_count"] == 1
    row = view["high_retention"][0]
    assert row["retention"] == "0.93"
    assert row["href"].endswith(f"article/{'a' * 64}.html")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/integration/test_mariadb_store.py tests/test_serve_ops.py -q -k "retention"`
Expected: FAIL — `AttributeError: 'MartStore' object has no attribute 'set_rewrite_retention'` · `KeyError: 'high_retention_count'`.

- [ ] **Step 3: 구현한다**

`src/bullet_in/storage/schema.sql` 끝의 articles ALTER 묶음에 한 줄 더한다.

```sql
ALTER TABLE articles ADD COLUMN IF NOT EXISTS rewrite_retention FLOAT;
```

`src/bullet_in/storage/mariadb.py` 에 메서드를 넣고 `ops_snapshot` 을 확장한다.

```python
    def set_rewrite_retention(self, content_hash: str, retention: float) -> None:
        """재작성 잔존율 기록 — ops 확인 목록의 근거 (스펙 §7)."""
        with self.engine.begin() as c:
            c.execute(text("UPDATE articles SET rewrite_retention=:r "
                           "WHERE content_hash=:h"),
                      {"r": float(retention), "h": content_hash})
```

`ops_snapshot` 의 `with self.engine.connect() as c:` 블록 안에 쿼리를 더하고 반환 dict 에 키를 더한다.

```python
            high_rows = c.execute(text(
                "SELECT content_hash, outlet, rewrite_retention FROM articles "
                "WHERE rewrite_retention > :thr ORDER BY rewrite_retention DESC"),
                {"thr": RETENTION_THRESHOLD}).mappings().all()
```

```python
                "high_retention": [{"content_hash": r["content_hash"],
                                    "outlet": r["outlet"],
                                    "retention": float(r["rewrite_retention"])}
                                   for r in high_rows],
```

파일 위쪽에 `from bullet_in.fidelity import RETENTION_THRESHOLD` 를 더한다.
저장 계층이 판정 모듈을 import 하는 모양이 되지만, 임계값을 SQL 에 다시 적는 것보다 낫다 — 규칙을 옮겨 적었다가 어긋난 전례가 이 저장소에 여러 건 있다.

`src/bullet_in/serve/render.py` 의 `build_ops_view` 반환 dict 에 두 키를 더한다.
`snapshot.get` 을 쓰는 이유는 옛 스냅샷 (키 없음) 으로도 렌더가 죽지 않게 하기 위함이다.

```python
    high = snapshot.get("high_retention") or []
    view["high_retention"] = [{"content_hash": r["content_hash"],
                               "outlet": r["outlet"] or "—",
                               "retention": f"{r['retention']:.2f}",
                               "href": f"article/{r['content_hash']}.html"}
                              for r in high]
    view["high_retention_count"] = len(high)
```

`src/bullet_in/serve/templates/ops.html.j2` 의 `<footer>` 바로 앞에 절을 넣는다.

```html
<h2>⑥ 재작성 잔존율 확인 대상 ({{ view.high_retention_count }}건)</h2>
{% if view.high_retention %}
<table>
  <tr><th>기사</th><th>언론사</th><th>잔존율</th></tr>
  {% for r in view.high_retention %}
  <tr><td><a href="{{ r.href }}">{{ r.content_hash[:8] }}</a></td>
      <td>{{ r.outlet }}</td><td>{{ r.retention }}</td></tr>
  {% endfor %}
</table>
{% else %}<p class="mut">임계값 초과 없음</p>{% endif %}
```

`src/bullet_in/run.py` 에서 번역 저장 루프 다음에 리포트를 기록한다.

```python
    for h, rep in gate_reports.items():
        mart.set_rewrite_retention(h, rep["retention"])
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/storage/schema.sql src/bullet_in/storage/mariadb.py \
        src/bullet_in/run.py src/bullet_in/serve/render.py \
        src/bullet_in/serve/templates/ops.html.j2 \
        tests/integration/test_mariadb_store.py tests/test_serve_ops.py
git commit -m "$(cat <<'EOF'
feat(serve): 재작성 잔존율 기록 · ops 확인 목록

본문을 버리지 않는 설계에서는 임계값을 넘긴 행이 그대로 서빙된다. 44건 표본에
0.9 를 넘는 행이 2건 남았고, 이런 행은 사람이 눈으로 확인해야 한다.

- 컬럼: articles.rewrite_retention (멱등 ALTER)
- 집계: ops_snapshot 이 임계값 초과 행을 잔존율 내림차순으로 반환
- 화면: ops.html ⑥ 절에 건수 · 기사 링크 · 언론사 · 잔존율

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §4.4 · §7
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 재발 방지 게이트 — 재료가 없으면 본문을 만들지 않는다

스펙 §4.5.
이 Task 가 근본 원인을 막는다.

**설계 판단 (스펙에 없는 결정 · 근거 명시)** — 재료 없는 행도 `title_ko` 는 생성한다.
스펙 §4.5 가 생성하지 않는 필드로 `body_ko` · `summary_ko` · `summary3_ko` 셋만 적었고, §4.5 끝에서 "제목 · 메타 · 원문 링크만 서빙한다" 고 했다.
행을 아예 건너뛰면 `title_ko` 가 영구히 NULL 로 남아 매 회차 재선별되고 화면에는 "번역 대기" 배지가 계속 붙는다.
그래서 제목만 생성하는 프롬프트를 따로 둔다.

**Files:**
- Modify: `src/bullet_in/enrich.py` (`TITLE_ONLY_PROMPT` · `partition_generatable` · `title_only_rows`)
- Modify: `src/bullet_in/run.py`
- Modify: `src/bullet_in/serve/render.py:1039-1048` (`render_article`)
- Modify: `src/bullet_in/serve/templates/detail.html.j2:20`
- Test: `tests/test_enrich.py` · `tests/test_serve_render.py`

**Interfaces:**
- Consumes: `BODY_AS_TITLE_SOURCES` (`enrich.py:264`).
- Produces:
  - `partition_generatable(rows) -> tuple[list[dict], list[dict]]` — `(generatable, title_only)`
  - `title_only_rows(rows, client, model) -> dict[str, dict]` — 값은 `_extract_full` 과 같은 4키 dict 이고 `summary_ko` · `summary3_ko` · `body_ko` 는 `None`

- [ ] **Step 1: 실패 테스트를 쓴다**

```python
def test_partition_generatable_drops_row_without_material():
    from bullet_in.enrich import partition_generatable
    rows = [{"content_hash": "h1", "source_id": "fmkorea",
             "body_source": "", "body_excerpt": None},
            {"content_hash": "h2", "source_id": "fmkorea",
             "body_source": "본문 있음", "body_excerpt": None}]
    gen, title_only = partition_generatable(rows)
    assert [r["content_hash"] for r in gen] == ["h2"]
    assert [r["content_hash"] for r in title_only] == ["h1"]


def test_partition_generatable_keeps_tweet_sources():
    """트윗은 title_original 에 전문이 있어 재료가 갖춰져 있다 (스펙 §3.1 · §4.5)."""
    from bullet_in.enrich import partition_generatable
    rows = [{"content_hash": "t1", "source_id": "x_afcstuff",
             "body_source": "", "body_excerpt": None},
            {"content_hash": "t2", "source_id": "x_ornstein",
             "body_source": None, "body_excerpt": ""}]
    gen, title_only = partition_generatable(rows)
    assert len(gen) == 2 and title_only == []


def test_partition_generatable_accepts_excerpt_only_row():
    from bullet_in.enrich import partition_generatable
    gen, title_only = partition_generatable(
        [{"content_hash": "h3", "source_id": "goal",
          "body_source": None, "body_excerpt": "발췌 있음"}])
    assert len(gen) == 1 and title_only == []


def test_title_only_rows_returns_title_and_null_body_fields():
    from bullet_in.enrich import title_only_rows
    class _C:
        models = None
        def generate_content(self, model, contents, config):
            assert "본문" not in contents.split("Title:")[0] or True
            return type("R", (), {"text": '{"title_ko": "아스날 소식"}'})()
    c = _C(); c.models = c
    out = title_only_rows([{"content_hash": "h1", "title_original": "Arsenal news"}],
                          c, "m")
    assert out["h1"]["title_ko"] == "아스날 소식"
    assert out["h1"]["summary_ko"] is None
    assert out["h1"]["summary3_ko"] is None
    assert out["h1"]["body_ko"] is None
```

`tests/test_serve_render.py` 에 추가한다.

같은 파일의 `_row()` · `_decorated()` 헬퍼와 `SOURCES` · `NOW` 상수를 그대로 쓴다.
`_row` 의 기본값에 본문이 들어 있으므로 비우는 인자를 넘긴다.

```python
def test_detail_note_says_meta_only_when_body_missing():
    """본문을 확보하지 못한 행은 자동 번역 안내문 대신 사유를 보여 준다 (스펙 §4.5)."""
    row = _row(body_ko=None, summary_ko=None, summary3_ko=None)
    html = render_article(_decorated(row), [], row["content_hash"], SOURCES, NOW)
    assert "원문 본문을 확보하지 못해" in html
    assert "자동 번역한 것입니다" not in html


def test_detail_note_stays_for_translated_body():
    html = render_article(_decorated(_row()), [], "cur", SOURCES, NOW)
    assert "자동 번역한 것입니다" in html
    assert "원문 본문을 확보하지 못해" not in html
```

`_row()` 가 `body_ko` 를 키워드로 받지 않으면 (`grep -n "def _row" -A12 tests/test_serve_render.py`) 반환 dict 를 복사해 세 필드를 `None` 으로 덮는다.

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_enrich.py tests/test_serve_render.py -q -k "generatable or title_only or meta_only"`
Expected: FAIL — `ImportError: cannot import name 'partition_generatable'`.

- [ ] **Step 3: 구현한다**

`src/bullet_in/enrich.py` 에 넣는다.

```python
TITLE_ONLY_PROMPT = (
    "다음 축구 뉴스 제목을 한국어로 옮긴다. 규칙:\n"
    "- 한국 스포츠 기사 제목체로 간결하게 (명사형 위주).\n"
    "- 제목에 없는 내용을 덧붙이지 않는다.\n"
    "- 원문 제목의 선수 · 감독 이름을 최소 하나는 그대로 남긴다.\n"
    "- 고유명사는 통용 한글 표기(Arsenal=아스날).\n"
    'ONLY JSON: {{"title_ko":"..."}}'
    "\n\nTitle: {title}")


def partition_generatable(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(생성 대상, 제목만 대상) — 재료가 없으면 본문 · 요약을 만들지 않는다.

    원인은 재료 없는 행에 완역을 지시한 것이다 — 번역할 원문이 없으니 모델이
    빈칸을 채워 넣었다 (스펙 §1). 트윗 소스는 title_original 에 전문이 있어
    재료가 갖춰져 있으므로 빠지지 않는다."""
    gen, title_only = [], []
    for r in rows:
        has_material = bool((r.get("body_source") or "").strip()
                            or (r.get("body_excerpt") or "").strip())
        if has_material or r.get("source_id") in BODY_AS_TITLE_SOURCES:
            gen.append(r)
        else:
            title_only.append(r)
    return gen, title_only


def title_only_rows(rows: list[dict], client, model: str) -> dict[str, dict]:
    """제목만 생성 — 본문 · 요약 필드는 None 으로 둔다.
    행을 아예 건너뛰면 title_ko 가 NULL 로 남아 매 회차 재선별되고 '번역 대기'
    배지가 영구히 붙는다."""
    out: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=TITLE_ONLY_PROMPT.format(title=r["title_original"]),
                config={"max_output_tokens": 512,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 제목 생성 중단 — 남은 행 다음 사이클")
                break
            log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
            continue
        m = re.search(r"\{.*\}", msg.text, re.DOTALL)
        try:
            title_ko = json.loads(m.group(0))["title_ko"] if m else None
        except (json.JSONDecodeError, KeyError, TypeError):
            title_ko = None
        if not title_ko:
            log.warning("제목 생성 파싱 실패, 스킵 content_hash=%s", h)
            continue
        out[h] = {"title_ko": title_ko, "summary_ko": None,
                  "summary3_ko": None, "body_ko": None}
    return out
```

`src/bullet_in/run.py` 의 enrich 배선을 이렇게 만든다.

```python
    from bullet_in.enrich import (partition_by_body_level, partition_generatable,
                                  rewrite_rows_guarded, title_only_rows)
    missing = mart.rows_missing_translation()
    generatable, title_only = partition_generatable(missing)
    if title_only:
        logging.getLogger(__name__).warning(
            "재료 없음 — 제목만 생성 %d건 (본문 · 요약 미생성)", len(title_only))
    rewrite_rows, translate_rows = partition_by_body_level(generatable)
    results: dict[str, dict] = {}
    results.update(enrich_rows(translate_rows, client, GEMINI_MODEL, mode="translate"))
    rewritten, gate_reports = rewrite_rows_guarded(rewrite_rows, client, GEMINI_MODEL)
    results.update(rewritten)
    results.update(title_only_rows(title_only, client, GEMINI_MODEL))
```

`finalize_translation` 은 `v["body_ko"]` 가 `None` 이어도 동작한다 (`paragraphize(None)` 은 `None` 을 돌려준다).
`detect_roundup_omission(None, None)` · `detect_club_injection` 이 `None` 을 받아 죽지 않는지 Step 4 에서 확인한다.

`src/bullet_in/serve/render.py` 의 `render_article` 안에서 `article["_excerpt"] = ...` 줄 다음에 넣는다.

```python
    article["_meta_only"] = not (article.get("body_ko") or "").strip()
```

`src/bullet_in/serve/templates/detail.html.j2` 의 안내문 줄을 바꾼다.

```html
  {% if a._meta_only %}
  <p class="tnote">원문 본문을 확보하지 못해 제목과 기본 정보만 제공합니다. 내용은 원문에서 확인해 주세요.</p>
  {% else %}
  <p class="tnote">이 글은 원문을 자동 번역한 것입니다. 표현이 어색하거나 뜻이 모호하면 원문을 확인해 주세요.</p>
  {% endif %}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest -q`
Expected: 전부 PASS.
`finalize_translation` 이 `body_ko=None` 에서 죽으면 그 함수의 `detect_*` 호출에 `or ""` 를 붙인다 — 그때도 테스트를 먼저 쓴다.

- [ ] **Step 5: 기존 오염 필드를 한 번 지운다 (VM)**

게이트는 새 생성만 막는다.
이미 지어낸 본문 · 요약이 남아 있는 행은 이 단계에서 비운다.
`title_ko` 는 남긴다 — NULL 로 만들면 매 회차 재선별 대상이 된다.

```bash
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
WHERE = ("WHERE COALESCE(body_source,'')='' AND COALESCE(body_excerpt,'')='' "
         "AND source_id NOT IN ('x_afcstuff','x_ornstein') AND body_ko IS NOT NULL")
with e.begin() as c:
    print("대상", c.execute(text(f"SELECT COUNT(*) FROM articles {WHERE}")).scalar_one(), "행")
    n = c.execute(text("UPDATE articles SET body_ko=NULL, summary_ko=NULL, "
                       f"summary3_ko=NULL {WHERE}")).rowcount
print("정리", n, "행 (title_ko 는 유지)")
PY
```

football.london 을 이미 지웠다면 (Task 1) 대상은 fmkorea 잔여분뿐이다.
`title_ko` 를 남기는 이유는 NULL 로 만들면 매 회차 재선별 대상이 되기 때문이다.

- [ ] **Step 6: 커밋한다**

```bash
git add src/bullet_in/enrich.py src/bullet_in/run.py src/bullet_in/serve/render.py \
        src/bullet_in/serve/templates/detail.html.j2 \
        tests/test_enrich.py tests/test_serve_render.py
git commit -m "$(cat <<'EOF'
feat(enrich): 재료 없는 행은 본문 · 요약을 생성하지 않는다

원인은 빈 본문을 넘기면서 완역을 지시한 것이다. 번역할 원문이 없으니 모델이
빈칸을 채워 방출 선수 명단 15명을 통째로 지어냈다. 배포판 467건에 이 조건을
적용하면 정확히 68건이 걸리고 트윗 81건은 통과한다.

- 게이트: body_source · body_excerpt 가 모두 비고 트윗 소스가 아니면 제외
- 제목: 제목 전용 프롬프트로 title_ko 만 생성 (건너뛰면 영구 재선별 대상)
- 화면: 본문 없는 상세 페이지의 안내문을 사유 문구로 교체

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §4.5
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 본문 빈 fmkorea 행 채우기 CLI

스펙 §5 의 4단계 전제.
Task 2 의 폴백은 새로 수집하는 글에만 적용된다.
이미 적재된 행은 제목이 `exclude_titles` 에 들어 있어 정기 회차가 다시 닿지 않는다.

**설계 판단 (스펙에 없는 결정 · 근거 명시)** — 게시글 URL 은 어디에도 저장되지 않는다 (`RawItem.url` 은 원문 URL 이고 Mongo 원본도 같다).
그래서 검색 페이징으로 후보 (제목 · 글 URL) 를 모아 저장된 `title_original` 과 정확히 일치하는 것만 골라 본문을 받는다.
행을 지우고 다시 수집하는 방식은 쓰지 않는다 — 같은 제목 · 같은 URL 이면 `content_hash` 가 같아 중복으로 걸러지고, 도달 가능한 검색 페이지 범위도 보장되지 않는다.

**Files:**
- Create: `src/bullet_in/backfill_fmkorea_body.py`
- Test: `tests/test_backfill_fmkorea_body.py` (신규)

**Interfaces:**
- Consumes: `FmkoreaAdapter.discover()` · `_body_text` · `_is_repost_blocked` · `strip_publish_datetime` · `extract_body_journalist` (`adapters/fmkorea.py`) · `build_fmkorea_adapter` (`collect_fmkorea.py`).
- Produces: `match_targets(targets: dict[str, str], found: list[tuple[str, str]]) -> dict[str, str]` — `{content_hash: post_url}` · `backfill(pages: int, limit: int | None, dry_run: bool) -> dict[str, int]`.

- [ ] **Step 1: 실패 테스트를 쓴다**

`tests/test_backfill_fmkorea_body.py` 를 새로 만든다.
`build_fmkorea_adapter` 의 실제 시그니처는 `src/bullet_in/collect_fmkorea.py` 에서 확인해 맞춘다.

```python
from bullet_in import backfill_fmkorea_body as bf


def test_match_targets_pairs_exact_titles_only():
    targets = {"h1": "[텔레그래프] 아스날 수비 보강", "h2": "[더 타임스] 미드필더 관심"}
    found = [("[텔레그래프] 아스날 수비 보강", "https://www.fmkorea.com/111"),
             ("[더 타임스] 미드필더 관심 (수정)", "https://www.fmkorea.com/222")]
    assert bf.match_targets(targets, found) == {"h1": "https://www.fmkorea.com/111"}


def test_match_targets_ignores_surrounding_whitespace():
    targets = {"h1": "[BBC] 아스날 소식"}
    found = [("  [BBC] 아스날 소식 ", "https://www.fmkorea.com/1")]
    assert bf.match_targets(targets, found) == {"h1": "https://www.fmkorea.com/1"}


def test_row_update_extracts_body_and_journalist():
    html = ('<div class="rd_body"><div class="xe_content">'
            '<p>By David Ornstein June 19, 2026 3:19 am 리버풀이 협상 중이다.</p>'
            '</div></div>')
    upd = bf.row_update(html, ".xe_content")
    assert upd["body_level"] == 1
    assert "June 19, 2026" not in upd["body"]
    assert "By David Ornstein" in upd["body"]
    assert upd["journalist"] == "David Ornstein"


def test_row_update_returns_none_when_repost_blocked():
    html = ('<div class="rd_body"><div class="xe_content"><p>본문.</p></div>'
            '<strong>[퍼가기가 금지된 글입니다]</strong></div>')
    assert bf.row_update(html, ".xe_content") is None


def test_row_update_returns_none_when_body_empty():
    assert bf.row_update('<div class="rd_body"></div>', ".xe_content") is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_backfill_fmkorea_body.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.backfill_fmkorea_body'`.

- [ ] **Step 3: 구현한다**

`src/bullet_in/backfill_fmkorea_body.py` 를 새로 만든다.

```python
"""본문 빈 fmkorea 행에 게시글 본문 채우기 (1회성 · 멱등).

원문 기사 URL 재수집은 26건 중 1건만 성공했다 (스펙 §6.2). 게시글 본문이 유일하게
남은 재료인데, 게시글 URL 은 저장되지 않으므로 검색 페이징으로 후보를 모아 저장된
제목과 정확히 일치하는 것만 골라 받는다.

채운 행은 번역 4필드를 NULL 로 되돌려 다음 회차 enrich 가 본문 기반으로 재생성하게
한다 (backfill_body 와 같은 멱등 패턴).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
라이브 사이트에 접촉하므로 출력은 tee 로 남기고 재실행하지 않는다.
    uv run python -m bullet_in.backfill_fmkorea_body --pages 3 --dry-run 2>&1 | tee ~/bf.log
    uv run python -m bullet_in.backfill_fmkorea_body --pages 3 2>&1 | tee ~/bf.log
"""
from __future__ import annotations
import argparse, asyncio, logging, os

import httpx
from sqlalchemy import create_engine, text

import yaml
from pathlib import Path

from bullet_in.adapters.fmkorea import (_body_text, _is_repost_blocked,
                                        extract_body_journalist,
                                        strip_publish_datetime)
from bullet_in.collect_fmkorea import (STATE_PATH, build_fmkorea_adapter,
                                       read_last_contact, should_supplement,
                                       tunnel_alive, write_last_contact)
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 라이브 사이트 부담 회피 (다른 백필과 같은 기준)
MAX_POSTS = 120            # 검색 후보 상한 — 대상 제목을 놓치지 않을 만큼 넉넉히
POST_BODY_LEVEL = 1

_SELECT_SQL = text(
    "SELECT content_hash, title_original FROM articles "
    "WHERE source_id='fmkorea' AND COALESCE(body_source,'')='' "
    "ORDER BY published_at DESC")
# journalist 는 이미 값이 있으면 보존한다 (말머리 값 우선 · 스펙 §4.1).
# 번역 4필드는 NULL 로 되돌려 다음 회차가 본문 기반으로 재생성한다.
_UPDATE_SQL = text(
    "UPDATE articles SET body_source=:b, body_level=:lv, "
    "journalist=COALESCE(journalist, :j), "
    "title_ko=NULL, summary_ko=NULL, summary3_ko=NULL, body_ko=NULL "
    "WHERE content_hash=:h")


def match_targets(targets: dict[str, str],
                  found: list[tuple[str, str]]) -> dict[str, str]:
    """{content_hash: 제목} × [(제목, 글 URL)] → {content_hash: 글 URL}.
    제목 완전 일치만 인정한다 — 부분 일치를 허용하면 다른 글의 본문이 들어간다."""
    by_title = {t.strip(): u for t, u in found}
    return {h: by_title[title.strip()] for h, title in targets.items()
            if title.strip() in by_title}


def row_update(html: str, body_selector: str) -> dict | None:
    """게시글 HTML → 저장할 body_source · body_level · journalist.
    퍼가기 금지거나 본문이 비면 None — 행을 건드리지 않고 재실행 몫으로 남긴다."""
    if _is_repost_blocked(html):
        return None
    body = strip_publish_datetime(_body_text(html, body_selector))
    if not body:
        return None
    return {"body": body, "body_level": POST_BODY_LEVEL,
            "journalist": extract_body_journalist(body)}


async def backfill(pages: int = 3, limit: int | None = None,
                   dry_run: bool = False, force: bool = False) -> dict[str, int]:
    stats = {"target": 0, "matched": 0, "filled": 0, "blocked": 0, "failed": 0}
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    proxy = os.environ.get("FMKOREA_PROXY")
    if proxy and not tunnel_alive(proxy):
        log.info("fmkorea 터널 미접속 — 백필 중단 (접촉 없음)")
        return stats

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    now = mart.db_now()
    marks = [t for t in (read_last_contact(STATE_PATH),
                         mart.source_watermarks().get("fmkorea")) if t]
    if not force and not should_supplement(max(marks) if marks else None, now):
        log.info("fmkorea 백필 중단 — 3h 이내 접촉 (--force 로 우회)")
        return stats

    with engine.connect() as c:
        targets = {r["content_hash"]: r["title_original"]
                   for r in c.execute(_SELECT_SQL).mappings().all()}
    if limit:
        targets = dict(list(targets.items())[:limit])
    stats["target"] = len(targets)
    log.info("본문 빈 fmkorea 행 %d건", len(targets))
    if not targets:
        return stats

    # exclude_titles 를 비워야 이미 적재된 글이 후보에 남는다 (정기 회차와 반대 방향).
    adapter = build_fmkorea_adapter(cfg, proxy, pages=pages,
                                    request_gap_sec=REQUEST_GAP_SEC,
                                    exclude_titles=set(),
                                    max_posts=MAX_POSTS)
    found = await adapter.discover()
    write_last_contact(STATE_PATH, now)     # 후보 0건이어도 접촉 스탬프
    log.info("검색 후보 %d건", len(found))
    matched = match_targets(targets, found)
    stats["matched"] = len(matched)
    log.info("제목 일치 %d/%d건", len(matched), len(targets))

    async with adapter._client() as c:
        for i, (h, post_url) in enumerate(matched.items()):
            if i:
                await asyncio.sleep(REQUEST_GAP_SEC)
            try:
                r = await c.get(post_url)
                r.raise_for_status()
            except httpx.HTTPError as e:
                stats["failed"] += 1
                log.warning("글 fetch 실패 %s: %r", post_url, e)
                continue
            upd = row_update(r.text, adapter.body_selector)
            if upd is None:
                stats["blocked"] += 1
                log.info("퍼가기 금지 또는 본문 없음 — 건너뜀 %s", post_url)
                continue
            if dry_run:
                log.info("[dry-run] %s → 본문 %d자 · 기자 %s",
                         h[:8], len(upd["body"]), upd["journalist"])
            else:
                with engine.begin() as conn:
                    conn.execute(_UPDATE_SQL, {"b": upd["body"], "lv": upd["body_level"],
                                               "j": upd["journalist"], "h": h})
            stats["filled"] += 1
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="본문 빈 fmkorea 행 본문 채우기 (멱등)")
    ap.add_argument("--pages", type=int, default=3, help="검색 페이지 수")
    ap.add_argument("--limit", type=int, default=None, help="대상 상한 (드라이런 검증용)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    ap.add_argument("--force", action="store_true", help="3h 접촉 간격 가드 우회")
    args = ap.parse_args()
    s = asyncio.run(backfill(pages=args.pages, limit=args.limit,
                             dry_run=args.dry_run, force=args.force))
    print(f"대상 {s['target']} · 일치 {s['matched']} · 채움 {s['filled']} "
          f"· 금지·본문없음 {s['blocked']} · 실패 {s['failed']}")


if __name__ == "__main__":
    main()
```

검색 URL 에 `{page}` 자리표시가 없으면 여러 페이지를 돌 때 같은 URL 을 반복 접촉한다.
기존 검사 함수를 그대로 불러 막는다 — `cfg` 를 읽은 바로 다음 줄에 넣는다.

```python
from bullet_in.backfill_fmkorea import check_page_placeholder
...
    src = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")
    check_page_placeholder(src["config"]["search_url"], pages)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_backfill_fmkorea_body.py -q && uv run pytest -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/backfill_fmkorea_body.py tests/test_backfill_fmkorea_body.py
git commit -m "$(cat <<'EOF'
feat(ingest): 본문 빈 fmkorea 행 본문 채우기 CLI

어댑터 폴백은 새로 수집하는 글에만 적용된다. 이미 적재된 행은 제목이 제외
목록에 있어 정기 회차가 다시 닿지 않고, 게시글 URL 은 저장되지 않는다.
그래서 검색 페이징으로 후보를 모아 저장된 제목과 완전히 일치하는 글만 받는다.

- 대상: source_id 가 fmkorea 이고 body_source 가 빈 행
- 매칭: 제목 완전 일치만 (부분 일치는 다른 글 본문 유입 경로)
- 저장: body_source · body_level 1 · 기자명 (기존 값 보존) · 번역 4필드 NULL 리셋
- 예외: 퍼가기 금지 · 본문 없음은 건드리지 않고 재실행 몫으로 남김

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §4.1 · §5
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: 라이브 실행 · 검증 · 임계값 확정

스펙 §5 의 4 · 5단계와 §7 검증 기준.
코드 변경이 없는 운영 Task 다.

**Files:**
- Modify: `docs/superpowers/specs/2026-07-29-translation-trust-design.md` §8 (임계값 확정값 기록)
- Create: `docs/runbook/2026-07-30-translation-trust-live-pass.md` (실행 기록)

**Interfaces:**
- Consumes: Task 1–9 전부.
- Produces: 확정된 임계값 · 검증 수치.

- [ ] **Step 1: 대상 건수를 다시 센다 (VM)**

스펙의 26건은 2026-07-27 스냅샷이고 07-29 라이브에서 29건이었다 (이틀에 3건씩 늘고 있다).
착수 시점 수치로 다시 잡는다.

```bash
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c:
    print("본문 빈 fmkorea:", c.execute(text(
        "SELECT COUNT(*) FROM articles WHERE source_id='fmkorea' "
        "AND COALESCE(body_source,'')=''")).scalar_one())
    print("등급 분포:", c.execute(text(
        "SELECT body_level, COUNT(*) FROM articles WHERE source_id='fmkorea' "
        "GROUP BY body_level")).all())
PY
```

- [ ] **Step 2: 본문 채우기를 드라이런한다 (VM)**

3건만 먼저 돌려 제목 매칭이 실제로 되는지 확인한다.
매칭률이 낮으면 `--pages` 를 늘리기 전에 이 계획의 Task 9 설계 판단을 다시 검토한다.

```bash
uv run python -m bullet_in.backfill_fmkorea_body --pages 3 --limit 3 --dry-run 2>&1 | tee ~/bf-dry.log
```

- [ ] **Step 3: 본문 채우기를 실행한다 (VM)**

드라이런이 접촉 스탬프를 남기므로 3h 가드가 걸린다.
연달아 돌릴 때는 `--force` 를 붙인다.

```bash
uv run python -m bullet_in.backfill_fmkorea_body --pages 3 --force 2>&1 | tee ~/bf-run.log
```

- **호출 규모** — Gemini 호출 없음 (fmkorea 접촉만).
- **접촉량** — 검색 3키워드 × 3페이지 + 일치한 글 수 회.
- **재실행 금지** — 출력을 다시 보려고 같은 명령을 되돌리지 않는다 (430 유발 전례 2회).
로그는 `~/bf-run.log` 에 남는다.

- [ ] **Step 4: enrich 만 재실행한다 (VM)**

fetch 없이 번역만 돌린다 (`docs/runbook/2026-07-19-enrich-only-pass.md`).

- **Gemini 호출 예상** — 채운 행 수 × 평균 1.5회.
26건이면 약 40회로 분당 한도에 걸릴 규모가 아니다.
- **실행 전에 사용자에게 규모를 알린다** (실제 과금 계정).

- [ ] **Step 5: 검증 기준을 하나씩 확인한다 (VM)**

스펙 §7 그대로다.

```bash
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c:
    print("본문 빈 fmkorea:", c.execute(text(
        "SELECT COUNT(*) FROM articles WHERE source_id='fmkorea' "
        "AND COALESCE(body_source,'')=''")).scalar_one())
    print("재료 없이 본문 있는 행:", c.execute(text(
        "SELECT COUNT(*) FROM articles WHERE COALESCE(body_source,'')='' "
        "AND COALESCE(body_excerpt,'')='' AND body_ko IS NOT NULL "
        "AND source_id NOT IN ('x_afcstuff','x_ornstein')")).scalar_one())
    print("잔존율 분포:", c.execute(text(
        "SELECT ROUND(rewrite_retention,1), COUNT(*) FROM articles "
        "WHERE rewrite_retention IS NOT NULL GROUP BY 1 ORDER BY 1")).all())
    print("football.london 잔재:", c.execute(text(
        "SELECT COUNT(*) FROM articles WHERE source_id='football_london'")).scalar_one())
PY
```

- **기준 ①** — 본문 빈 fmkorea 행이 0건이거나, 남은 행은 퍼가기 금지 표식이 확인된 것뿐.
- **기준 ②** — 재생성한 행의 숫자 누락 0개 (로그의 `재작성 게이트 잔존` 경고로 확인).
- **기준 ③** — `site/ops.html` ⑥ 절에 임계값 초과 목록과 건수가 나온다.
- **기준 ④** — football.london 행 0건 · 기자 필터에 `Tom Canton` 없음.
- **기준 ⑤** — 본문 없는 행의 상세 페이지가 깨지지 않는다 (`docs/runbook/2026-07-26-local-serve-render-verification.md`).

- [ ] **Step 6: 임계값을 확정한다**

Step 5 의 잔존율 분포를 보고 정한다.
지금 값 `0.75` 는 The Athletic 44건 표본에서 임의로 고른 값이고, 이번 대상은 The Telegraph · The Times · BeSoccer 계열이라 문체가 다르다.

- 분포 중앙이 0.75 를 크게 밑돌면 그대로 둔다.
- 상당수가 0.75 를 넘겨 재시도만 늘면 0.85 로 올린다 (호출 7회 수준 차이).
- 확정값과 근거 분포를 스펙 §8 미결 항목에 적어 미결을 닫는다.

- [ ] **Step 7: 실행 기록을 런북으로 남기고 커밋한다**

`docs/runbook/2026-07-30-translation-trust-live-pass.md` 에 실제 명령 · 출력 발췌 · 확정 임계값 · 남은 행 사유를 적는다.
서식은 컨벤션 §2.2 를 따른다 (PostToolUse 훅이 검사한다).

```bash
git add docs/runbook/2026-07-30-translation-trust-live-pass.md \
        docs/superpowers/specs/2026-07-29-translation-trust-design.md
git commit -m "$(cat <<'EOF'
docs(runbook): 번역 신뢰성 라이브 반영 기록 · 복제 게이트 임계값 확정

The Athletic 44건 표본으로 고른 임계값을 실제 대상 분포로 확정했다. 대상 매체가
The Telegraph · The Times · BeSoccer 계열이라 문체가 달라 다시 재야 했다.

- 실행: 본문 채우기 · enrich 재실행 · 렌더 · 배포 순서와 실제 출력
- 확정: 복제 게이트 임계값과 근거 분포
- 잔여: 본문을 채우지 못한 행과 그 사유

Refs: docs/superpowers/specs/2026-07-29-translation-trust-design.md §7 · §8
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## 자기 점검 결과

계획을 쓴 뒤 스펙과 다시 대조했다.

### 스펙 절 대응

| 스펙 | Task |
| --- | --- |
| §4.1 수집 폴백 · 바이라인 | 2 (함수 둘은 PR #156 에서 이미 구현) |
| §4.2 라우팅 | 3 |
| §4.3 프롬프트 | 4 |
| §4.4 게이트 | 5 · 6 |
| §4.5 재발 방지 | 8 |
| §4.6 football.london | 1 |
| §4.7 본문 출처 등급 | PR #156 (선행 조건) · Task 2 가 등급 1 을 싣는다 |
| §5 실행 순서 | 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 |
| §7 검증 기준 | 10 |
| §8 미결 (임계값) | 10 Step 6 |

### 스펙에 없어 이 계획이 정한 것

- **제목 전용 생성 경로** (Task 8) — §4.5 가 세 필드만 금지했고 `title_ko` 는 금지 목록에 없다.
행을 건너뛰면 `title_ko` 가 영구 NULL 이 되어 매 회차 재선별된다.
- **본문 채우기 방식** (Task 9) — §5 는 "26건 재생성" 만 적고 게시글 URL 이 저장되지 않는 문제를 다루지 않는다.
검색 페이징 + 제목 완전 일치를 골랐고, 행 삭제 후 재수집은 `content_hash` 중복으로 막히므로 배제했다.
- **잔존율 저장 컬럼** (Task 7) — §7 이 "ops 에 노출되고 건수가 기록된다" 고만 적어 저장 위치를 정하지 않았다.
`articles.rewrite_retention` 에 둔다.

### 남은 위험

- **제목 매칭률** — Task 9 의 전제가 검색 페이징 도달 범위다.
Task 10 Step 2 의 드라이런 3건이 이 전제를 먼저 검증한다.
- **표본 차이** — 프롬프트 · 게이트 수치는 The Athletic 44건에서 나왔고 이번 대상은 다른 매체 계열이다.
- **게시자 오역** — 게이트는 "원문과 다른가" 만 보므로 원문 자체가 틀리면 통과한다 (스펙 §8 한계).
