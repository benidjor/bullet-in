# enrich 전용 패스 런북 — fetch 없이 미번역 · 미분류 잔존 수렴 (2026-07-19)

회차 실행 후 Gemini 파싱 실패 등으로 미번역 행이 남았을 때, 어댑터 fetch 없이 enrich 만 재실행해 즉시 수렴시키는 절차.
v1 마감 트랙 ③ 에서 실측 · 캡처 전 수렴용으로 처음 사용했다 (잔존 8 → 0).

## 1. 언제 이 절차를 쓰나 · 왜 run.py 재실행이 아닌가

- 미번역 · 미분류 잔존을 **지금** 없애야 할 때 — SLO 측정 직전 · README 캡처 직전 · 사용자 시연 직전.
- 급하지 않으면 이 절차는 불필요하다
— 하루 4회 스케줄의 다음 회차가 신규분과 함께 자연 수렴시킨다 (429 설계와 같은 철학).
- ⚠️ **단, 스케줄 미가동 기간 (가동 방식 미결정 · 수동 회차만 도는 현 상태) 엔 "다음 회차" 가 오지 않는다**
→ 파싱 실패로 스킵된 행이 무기한 미번역으로 남고, 그 상태로 site 를 렌더하면 상세 페이지가 무번역 (영문 제목 · 본문 없음) 으로 노출된다.
  실사례: 7-19 수동 회차의 stochastic 파싱 실패 1건 (skysports `9265641e…`) 이 스킵된 채 렌더돼 상세 페이지 무번역 노출.
→ **수동 회차 후 site 렌더 · 시연 전에는 §2 잔존 확인을 반드시 수행**하고, 잔존이 있으면 이 패스로 수렴 후 렌더한다.
- `run.py` 전체 재실행은 fetch 부터 다시 돌아 **fmkorea 를 재타격**한다
→ 직전 회차 후 2시간 이내면 430 차단 창을 밟는다 (벤치 자기 간섭 트러블슈팅 참조).
  이 패스는 DB 와 Gemini 만 만지므로 2h 규칙과 무관하다.

## 2. 잔존 확인 (읽기 전용)

```bash
set -a; source .env; set +a
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    rows = c.execute(text(
        "SELECT source_id, COUNT(*) FROM articles "
        "WHERE title_ko IS NULL AND source_id != 'fmkorea' GROUP BY source_id")).all()
print("미번역 잔존:", rows or 0)
EOF
```

fmkorea (ko 소스) 는 번역 대상이 아니라 제외한다.

## 3. 수렴 패스 (최대 3회 반복)

`run.py` 의 enrich 블록과 같은 함수 · 순서를 재사용한다 — 규칙이 두 벌로 갈라지지 않게 새 로직을 만들지 않는다.

```bash
uv run python - <<'EOF'
import os, yaml
from pathlib import Path
from google import genai
from sqlalchemy import create_engine
from bullet_in.enrich import (apply_glossary, classify_stage_rows, enrich_rows,
                              partition_by_paywall)
from bullet_in.run import GEMINI_MODEL
from bullet_in.storage.mariadb import MartStore

mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
glossary = (yaml.safe_load(Path("config/glossary.yaml").read_text()) or {}).get("replacements", {})
for attempt in range(3):
    missing = mart.rows_missing_translation()
    if not missing:
        break
    para, trans = partition_by_paywall(missing)
    results = {}
    results.update(enrich_rows(trans, client, GEMINI_MODEL, mode="translate"))
    results.update(enrich_rows(para, client, GEMINI_MODEL, mode="paraphrase"))
    for h, v in results.items():
        v = apply_glossary(v, glossary)
        mart.set_translation(h, v["title_ko"], v["summary_ko"], v["summary3_ko"], v["body_ko"])
    print(f"패스 {attempt + 1}: {len(results)} / {len(missing)} 성공")
print("최종 미번역 잔존:", len(mart.rows_missing_translation()))
staged = mart.rows_missing_stage()
if staged:
    for h, s in classify_stage_rows(staged, client, GEMINI_MODEL).items():
        mart.set_stage(h, s)
print("미분류 잔존:", len(mart.rows_missing_stage()))
EOF
```

## 4. 사이트 재생성 (수렴분 반영)

번역은 DB 에만 반영되므로, 서빙 화면에 실리려면 `write_site` 를 다시 돌린다.
SELECT 는 `bullet_in.run.SERVING_SELECT_SQL` 을 import 해서 쓴다
— 컬럼을 여기 옮겨 적으면 서빙 코드에 컬럼이 추가될 때 어긋나고, 구버전 목록으로 사이트를 다시 만들면
정렬 보간 · 아웃렛 표시 · 가십 단신 카드가 조용히 깨진다 (실제 4회 재발,
`docs/troubleshooting/2026-07-19-runbook-snippet-logic-drift.md`).
`write_site` 의 인자는 여전히 run.py 서빙 경로와 1:1 로 유지할 것.

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
from bullet_in.run import SERVING_SELECT_SQL
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry, journalist_directory, outlet_directory
from bullet_in.serve.render import write_site

engine = create_engine(os.environ["MARIADB_URL"])
with engine.connect() as c:
    rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
write_site(rows, load_sources("config/sources.yaml"), "site",
           directory=journalist_directory("config/credibility.yaml"),
           registry=load_registry("config/credibility.yaml"),
           outlet_dir=outlet_directory("config/credibility.yaml"))
print("site 재생성:", len(rows), "행")
EOF
```

## 5. 실패 모드

| 증상 | 판단 | 대응 |
|---|---|---|
| 3패스 후에도 같은 행 잔존 | 확률적 vs 구조적 판별 필요 | 동일 입력 프로브 — 트러블슈팅 `2026-07-19-gemini-stochastic-json-parse-failure.md` §4 |
| `Gemini rate limit(429)` 로그 후 중단 | 분당 속도 한도 | 기존 규칙 — 수 분 대기 후 재실행 또는 다음 회차 위임 |
| 잔존 0 인데 화면에 원문 노출 | §4 미실행 (DB 만 갱신) | `write_site` 재실행 |

## 6. 참고

- 유사 패턴: `docs/runbook/2026-07-15-tone-backfill-ops.md` (재요약 전용 enrich 패스 — fetch 없음 동일)
- 2h 규칙 근거: `docs/troubleshooting/2026-07-15-benchmark-rate-limit-self-interference.md`
- 최초 사용: v1 마감 트랙 ③ (PR #58) — 실측 · 캡처 전 잔존 8 → 0 수렴
