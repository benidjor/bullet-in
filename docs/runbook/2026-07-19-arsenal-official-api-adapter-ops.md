# arsenal_official GraphQL API 어댑터 운영

- 날짜: 2026-07-19 (복구 PR #68 라이브 실행 기준)
- 대상: `src/bullet_in/adapters/arsenal_api.py` (source_id `arsenal_official`)
- 설계 근거: `docs/superpowers/specs/2026-07-19-arsenal-official-api-recovery-design.md`
- 발굴 함정: `docs/troubleshooting/2026-07-19-unofficial-graphql-api-probe-traps.md`

## 1. 평시 구성

- 비공식 GraphQL API `https://afc-prd.graph.arsenal.com/graphql` 를 httpx 로 직접 호출한다
  (인증 불요 · `bullet-in/0.1` UA — 2026-07-19 실측).
- 필터 · 쿼리 전문의 SoT 는 어댑터 코드다 — 이 런북은 절차만 다루고 규칙을 미러하지 않는다
  (스니펫 드리프트 예방: `docs/troubleshooting/2026-07-19-runbook-snippet-logic-drift.md`).
- **발견 경로는 sitemap 이다** (2026-07-24 개정 · spec `2026-07-24-arsenal-official-sitemap-recovery-design.md`).
목록 피드가 동결돼 `https://www.arsenal.com/sitemaps/articles/1/sitemap.xml` 에서 창 안 `/news/` URL 을 뽑고 건별로 `GetArticle` 을 부른다.
- **config 에 노출된 항목이 없다** (`config: {}`).
창 크기는 어댑터 상수 `WINDOW_HOURS` (48시간) 이고 생성자 인자 `window_hours` 로만 바꾼다.
개정 전의 `pages` 인자는 없어졌으므로 옛 스니펫을 그대로 쓰면 `TypeError` 가 난다.
- `freshness_hours: 0` 으로 신선도 감시에서 제외돼 있다 — 이벤트 구동 소스라 유한 임계가 오발화를 낳는다 (스펙 `2026-08-07-alert-f2-unit-attribution-and-observability-design.md` §3.2).
- 수집 기사는 전건 규칙 경로로 `transfer_stage = official` 태깅된다.
  재계약 기사가 official 배지를 받는 것은 **의도된 동작**이다
  — 근거는 분류 런북 알려진 한계 (`docs/runbook/2026-06-30-transfer-stage-classification-ops.md`).

## 2. 라이브 단독 fetch 검증 (어댑터 · config 변경 시 머지 전 필수)

단위 테스트는 모킹이라 API 계약 변화를 못 잡는다 — 셀렉터 드리프트 함정과 같은 원칙.

```bash
uv run python - <<'EOF'
import asyncio
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter
a = ArsenalApiAdapter("arsenal_official", window_hours=168)   # 기본 48 · 검증은 넓게
items = asyncio.run(a.fetch())
print(f"퍼널 {a.coverage}")            # 후보 · Men · accept
for it in items:
    p = it.raw_payload
    print(f"- {p['published'][:10]} | {p['title'][:60]} | body {len(p.get('body') or '')}자")
for r in a.men_news_rejects:           # Men + News 인데 비채택 (관측용)
    print(f"  비채택: {r['title'][:60]} | {r['taxonomies']}")
EOF
```

판독:

- 이적창 기간인데 accept 가 0이면 §3 실패 모드를 순서대로 점검한다 (비이적창 0건은 정상일 수 있음).
- 후보가 0이면 sitemap 축이 깨진 것이고, 후보는 있는데 accept 가 0이면 채택 조건 축을 본다 — 퍼널 세 숫자로 갈린다.
- 수집건의 body 가 전부 0자면 본문 쿼리 (`GetArticle`) 축만 깨진 것 — 목록 축과 분리 진단.
- **body 가 0은 아닌데 원문보다 짧으면 §3.4 를 본다** — 길이만 보고 "본문 정상" 으로 넘기지 않는다.

### 2.1. 본문 길이 대조 (파서 축 점검)

블록 파싱이 문단을 통째로 흘리는 결함은 위 출력만으로는 드러나지 않는다 (§3.4).
어댑터 파서를 건드렸거나 응답 구조 변경이 의심되면 같은 기사에서 두 방식의 길이를 나란히 잰다.

```bash
uv run python - <<'EOF'
import asyncio, re, httpx
from bullet_in.adapters.arsenal_api import ARTICLE_QUERY, GRAPHQL_URL
GID = "a7fZT9g6dECY"        # 점검할 기사의 glideId (URL 끝 토큰)
TAG = re.compile(r"<[^>]+>")

async def main():
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "bullet-in/0.1"}) as c:
        r = await c.post(GRAPHQL_URL, json={"operationName": "GetArticle", "query": ARTICLE_QUERY,
            "variables": {"articleId": "", "glideId": GID, "glidePath": ""}})
        blocks = r.json()["data"]["getArticle"]["articleBody"] or []
    for b in blocks:
        if b.get("type") != "TEXT":
            continue
        inner = (b.get("innerText") or "").strip()
        html = TAG.sub("", b.get("html") or "").strip()
        mark = "  ← 어댑터가 흘림" if html and not inner else ""
        print(f"[{(b.get('tagName') or '?'):3s}] innerText {len(inner):4d}자 · html {len(html):4d}자{mark}")
asyncio.run(main())
EOF
```

`innerText` 가 0인데 `html` 에 내용이 있는 블록이 나오면 그 문단이 본문에서 빠지고 있다는 뜻이다.

## 3. 실패 모드 4종 (드러나는 방식이 서로 다름)

### 3.1 쿼리 필드 드리프트 — 에러로 드러남

- API 가 쿼리의 필드를 없애면 validation 에러 → `fetch()` 예외 → 회차 에러 카운트 · 알림 경로.
- 대응: 사이트에서 신규 번들을 받아 쿼리 전문을 재추출해 어댑터 상수를 갱신한다
  (절차는 발굴 함정 문서 §1).

### 3.2 taxonomy 명칭 · 부여 정책 변경 — 조용한 0건

- 채택 조건이 참조하는 taxonomy 명칭 (예: "Transfer news") 이 바뀌면 필터가 전건 걸러
  **에러 없이 0건**이 된다 — 평시 0건 소스 감시 사각과 같은 형태
  (`docs/troubleshooting/2026-07-19-silent-zero-collection-blindspot.md`).
- 대응: 이적창 기간에 §2 단독 프로브를 정기 점검에 포함하고,
  0건이면 무필터 목록 (어댑터 `_accept` 우회) 으로 최근 기사들의 `taxonomies` 실값을 눈으로 대조한다.
- 목록 응답 자체가 null 이면 어댑터가 "목록 응답 비어 있음" WARNING 을 남긴다
  — 인자 계약 드리프트 의심 (조용한 null 함정, 발굴 함정 문서 §2).

### 3.3 인증 도입 · 엔드포인트 폐쇄 — 4xx 로 드러남

- 401 · 403 · 429 류가 지속되면 비공식 API 접근이 막힌 것.
- 대응: 헤더 요구 (Origin · Referer) 재실측부터 시도하고, 막혔으면 Playwright 갈래 재검토
  (spec 의 기각 대안 — goal 복구 선례 규모로 회귀).

### 3.4 블록 구조 변경 — 본문 일부만 조용히 사라짐

앞의 셋과 달리 **에러도 0건도 아니다.** 기사는 정상 수집되고 본문도 비지 않는데 문단 몇 개가 빠진다.

- 2026-08-12 실측 — 어댑터가 `innerText` 만 읽는데 링크 (`<a>`) 나 볼드 (`<strong>`) 가 든 문단은 그 값이 비고 내용이 `html` · `childNodes` 에만 있었다.
구단 발표문이 첫 문단을 볼드로 강조하는 편집 관행 탓에 **이적 사실을 진술하는 리드 문장이 매번 빠졌다** (채택 기사 12건 중 11건).
- **왜 안 보이나** — 둘째 문단부터는 정상이라 본문이 비지 않고, 번역 · 요약도 성공하며, 단위 테스트의 가짜 블록은 `innerText` 를 늘 채워 둔다.
- **점검** — §2.1 의 길이 대조를 돌린다.
- **대응** — 파서가 `innerText` 가 빈 블록의 `html` 을 읽도록 고치고, 이미 수집된 기사는 본문이 바뀌므로 재번역한다.
- 상세 = `docs/troubleshooting/2026-08-12-arsenal-official-body-first-paragraph-dropped.md`.

## 4. 소급 (백필) 절차

**지금은 전용 모듈이 있다** — `src/bullet_in/backfill_arsenal.py` 를 쓴다 (2026-07-24 신설).

```bash
set -a; source .env; set +a
uv run python -m bullet_in.backfill_arsenal --phase reverify           # dry-run
uv run python -m bullet_in.backfill_arsenal --phase reverify --apply
```

- **run.py 종단 실행을 쓰지 않는 이유**
→ 전 소스를 fetch 해 fmkorea 2h 규칙 등 타 소스 접촉 제약과 충돌한다.
- 창은 모듈 상수 `REVERIFY_SINCE` 로 정한다 — 그 시각부터 지금까지를 `window_hours` 로 환산해 어댑터에 넘긴다.
더 과거를 훑으려면 이 상수를 바꾼다 (개정 전의 `pages` 상향은 더 이상 쓰지 않는다).
- 적재는 표준 경로를 그대로 탄다 (content_hash → RawStore → to_articles → upsert).
**단계는 이 경로에서 채우지 않는다** — 여기서 stage 만 넣으면 그 행이 분류 대상에서 빠져 방향이 NULL 로 남고, 단계 필터가 방향 한정이 된 뒤로는 오피셜 배지를 달고도 화면에서 사라진다 (모듈 주석 참조).
- **채택 조건을 통과하는 기사만 적재된다** — 태그가 빠진 기사는 창을 아무리 넓혀도 들어오지 않는다.
2026-08-05 뇌르고르 발표가 그 사례이고, 대응은 스펙 `2026-08-12-arsenal-official-collection-revision-design.md` 에 있다.
- 멱등: mart 의 URL UNIQUE · content_hash dedup 으로 재실행 안전.
  번역 (title_ko NULL) 은 하루 8회 정규 스케줄이 누적 처리 — 백필에서 enrich 를 돌리지 않는다.
- 실행 기록 (2026-07-19 · **개정 전 `pages` 기반 절차로 수행**): `pages=30` (약 1,500건 목록 = 5/23 도달) · 컷오프 6/1
→ 5건 적재 · 전건 official · tier 0
  (트로사르 방출 · 합의 · Meslier · Kiwior · Hincapie — 방출 2건은 구 'sign' 필터 누락분).

## 5. 롤백

- 어댑터 · config 는 `git revert` 로 원복 (구 html 셀렉터 경로는 사이트 개편으로 이미 무효
  — revert 는 수집 중단과 같다).
- 백필 적재분은 실제 공홈 기사라 정합 — 제거 불요.
  제거가 필요하면 `DELETE FROM articles WHERE source_id='arsenal_official'` 후
  raw (mongo) 는 보존해도 무해하다 (mart 재적재 시 dedup).

