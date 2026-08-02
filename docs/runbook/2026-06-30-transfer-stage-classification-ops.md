# 런북 — 영입 단계 분류 운영 (마이그레이션 · backfill · 재태깅)

Tier 2-b (PR #18) 로 도입된 영입 단계 분류 (`articles.transfer_stage`) 의 운영 절차.

단계는 번역과 **분리된 전용 패스** (`enrich.classify_stage_rows`) 가 부여한다.
트리거는 `transfer_stage IS NULL` 이며, 신규 · 기존 기사를 한 경로로 균일 처리한다.
설계 상세는 `docs/superpowers/specs/2026-06-30-tier2b-transfer-stage-design.md`.

## 언제 쓰나

- 새 환경/DB에 분류를 처음 적용할 때 (스키마 마이그레이션 + backfill).
- 프롬프트 · taxonomy 를 바꿔 **전건 재분류**가 필요할 때.
- 분류가 안 채워지거나 분포가 이상할 때 진단.

## 비자명한 함정 (먼저 읽기)

- **한 번 태깅되면 자동 재분류 안 됨.** 트리거가 `transfer_stage IS NULL` 이라, 값이 채워진 행은 다음 사이클에 건드리지 않는다. 프롬프트 · 단계 정의를 개선해 **전건을 다시 분류**하려면 컬럼을 NULL 로 되돌려야 한다 (아래 3절).
- **revision 변경은 재태깅하지 않는다 (설계상 단계 보존).** url 이 같고 content_hash 가 바뀌는 (본문 개정) 경우, upsert 의 `ON DUPLICATE KEY UPDATE` 에 `transfer_stage` 가 일부러 빠져 있어 기존 단계가 유지된다. "본문이 바뀌었는데 단계가 그대로"는 버그가 아니라 의도된 동작이다.
- **타깃 분류 패스만 단독 실행하려면 `ensure_schema()` 선행.** 통합 테스트는 `bulletin_test` 에 스키마를 적용하지만, 실 `bulletin` DB 의 `transfer_stage` 컬럼은 `run.py` 의 `ensure_schema()` (또는 수동 호출) 로만 적용된다. 전체 파이프라인 없이 분류만 돌릴 때는 먼저 스키마를 보장해야 `transfer_stage IS NULL` 조회가 동작한다.
- **이 프로젝트는 dotenv 미사용** → 모든 실행 전에 `set -a; source .env; set +a`.

## 오피셜 규칙 분리 (2026-07-19)

'이적 합의' (agreed) 신설과 함께 official 부여 방식이 LLM 판정에서 소스 규칙으로 바뀌었다.
설계 배경은 `docs/superpowers/specs/2026-07-19-transfer-stage-overhaul-design.md` §2 · §4 참고.

- **규칙 경로만 official 을 생성한다.** `transfer_stage.rule_stage(source_id)` 는 공홈 (`arsenal_official`) 행에만 `official` 을 부여한다 (2026-08-02 방향 축 이후 반환값은 `("official", None)` 형태의 쌍이다 — §3.1 참고). `run.py` 의 분류 패스가 미태깅 행을 규칙 대상 / LLM 대상으로 나눠, 규칙 대상은 LLM 호출 없이 바로 `set_stage` 한다.
- **LLM enum 에서 official 이 제거됐다.** `STAGE_PROMPT` 는 더 이상 official 을 제시하지 않는다 — 공홈이 아닌 소스는 구조적으로 official 이 될 수 없다.
- **모델이 그래도 official 을 반환하면 agreed 로 강등한다.** `enrich.classify_stage_rows` 가 `stage == "official"` 응답을 agreed 로 낮추고 `WARNING` 로그를 남긴다 — 정상 흐름에서는 뜨지 않아야 하는 신호다.
- **진단: 비공홈 official 불변량.** 아래 SQL 은 항상 0 을 반환해야 한다. 0 이 아니면 규칙 분리가 깨졌거나 강등 방어를 우회한 경로가 있다는 뜻이다.

```sql
SELECT COUNT(*) FROM articles WHERE transfer_stage = 'official' AND source_id != 'arsenal_official';
```

## 1. 스키마 마이그레이션 (멱등)

전체 파이프라인 (`python -m bullet_in.run`) 은 시작 시 `ensure_schema()` 로 컬럼을 자동 적용하므로 별도 작업이 불필요하다.
분류 패스만 단독으로 돌리려면 먼저 한 번 적용한다.

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
from bullet_in.storage.mariadb import MartStore
e = create_engine(os.environ["MARIADB_URL"])
MartStore(e).ensure_schema()   # ALTER ... ADD COLUMN IF NOT EXISTS (멱등)
with e.connect() as c:
    cols = [r[0] for r in c.execute(text("SHOW COLUMNS FROM articles")).all()]
print("transfer_stage present:", "transfer_stage" in cols)
PY
```

## 2. backfill (미태깅 행 분류)

전체 파이프라인을 돌리면 번역 패스 뒤에 분류 패스가 자동 실행된다.
이미 적재된 행만 분류하려면 (수집 없이) 분류 패스만 돌린다.
`run.py` 분류 패스와 동일하게, 공홈 (`arsenal_official`) 행은 `rule_stage` 로 LLM 없이 직접 태깅하고 나머지만 `classify_stage_rows` 에 넘긴다.
미태깅 행 전체를 그대로 LLM 에 넘기면 공홈 행이 official 을 받지 못하고 agreed 등으로 오분류되며, `transfer_stage IS NULL` 트리거 특성상 재분류 전까지 그 값이 고착된다 — 아래 스니펫은 이 분기를 반드시 포함한다.
상세는 "오피셜 규칙 분리 (2026-07-19)" 절을 참고한다.

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from sqlalchemy import create_engine
from google import genai
from bullet_in.storage.mariadb import MartStore
from bullet_in.enrich import classify_stage_rows
from bullet_in.run import GEMINI_MODEL
from bullet_in import transfer_stage

engine = create_engine(os.environ["MARIADB_URL"])
mart = MartStore(engine)
mart.ensure_schema()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

rows = mart.rows_missing_stage()
print(f"미태깅: {len(rows)}")

llm_rows = []
stage_ruled = {}
for r in rows:
    stage_fixed, direction_fixed = transfer_stage.rule_stage(r["source_id"])
    if stage_fixed and direction_fixed:      # 가십 — 단계 · 방향 둘 다 고정 (LLM 제외)
        mart.set_stage(r["content_hash"], stage_fixed, direction_fixed)
        continue
    if stage_fixed:                          # 공홈 — 단계만 고정 · 방향은 LLM 판정
        stage_ruled[r["content_hash"]] = stage_fixed
    llm_rows.append(r)

out = classify_stage_rows(llm_rows, client, GEMINI_MODEL)
print(f"이번 회차 LLM 분류: {len(out)}")
for h, (stage, direction) in out.items():
    mart.set_stage(h, stage_ruled.get(h, stage), direction)
PY
```

- **429 동작**: Gemini 무료 티어는 분당 *요청 수* 한도다. 429 를 만나면 그 회차는 **즉시 중단** 하고 남은 배치는 다음 실행에 누적된다 (멱등). 한 번에 다 안 되면 같은 명령을 다시 돌리면 된다.
- **부분 실패**: 응답 누락 · 파싱 실패 배치의 행은 NULL 로 남아 다음 회차에 재시도된다. 손상 없음.

## 3. 전건 재분류 (taxonomy · 프롬프트 개선 후)

`transfer_stage` 가 이미 채워져 있으면 트리거가 건너뛰므로, 재분류 대상을 NULL 로 되돌린 뒤 2절을 다시 돌린다.

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.begin() as c:
    n = c.execute(text("UPDATE articles SET transfer_stage = NULL")).rowcount
print(f"NULL 복원: {n}건 → 이제 2절 backfill 재실행")
PY
```

특정 단계만 다시 보려면 `WHERE transfer_stage = 'other'` (또는 `'agreed'`) 등으로 범위를 좁힌다.

**2026-07-19 실측**: 201건 NULL 복원 → LLM 분류 1패스로 수렴 (잔존 0). 규칙 경로는 0건 (공홈 적재 0건). 재분류 후 official 0건은 공홈 적재가 없는 동안 정상이다 ("오피셜 규칙 분리" 절 참고).

### 3.1. 방향 축 반영 (2026-08-02)

2026-08-02 방향 축 스펙 이후로는 재분류할 때 `transfer_stage` 뿐 아니라 `transfer_direction` (in · out · none) 도 함께 부여한다.
설계 배경은 `docs/superpowers/specs/2026-08-02-transfer-stage-direction-design.md` 참고.

사전 덤프에도 `transfer_direction` 을 포함한다.
다만 이 컬럼이 신설되는 첫 소급 재분류에서는 전건이 NULL 이므로, 실질적인 복원 대상은 여전히 `transfer_stage` 뿐이다.

이 컬럼은 코드 반영 후 정기 회차 (또는 enrich 전용 재실행) 가 한 번 지나야 `ensure_schema()` 로 생성된다.
VM 에서 pull 직후 회차가 아직 한 번도 돌지 않았다면 아래 덤프는 `Unknown column 'transfer_direction'` 오류로 실패하므로, 회차가 한 번 지난 뒤에 실행할 것.

```bash
uv run python - <<'PY'
import csv, os, sys
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c, open("stage_dump.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["content_hash", "transfer_stage", "transfer_direction"])
    for row in c.execute(text(
            "SELECT content_hash, transfer_stage, transfer_direction FROM articles")):
        w.writerow(row)
print("덤프 완료: stage_dump.csv")
PY
```

방향 축이 들어오면서 규칙 경로가 2형태로 갈라졌다.
bbc_gossip 소스는 `rumour` + `none` 으로 고정돼 LLM 을 거치지 않는다.
arsenal_official 소스는 `official` 고정은 그대로이되, 방향만 LLM 이 판정하므로 이 소스는 배치에 포함된다.

재분류 후에는 아래 쿼리 3종으로 수렴을 확인한다.

```sql
SELECT COUNT(*) FROM articles WHERE transfer_stage IS NULL;      -- 0 이어야 수렴
SELECT COUNT(*) FROM articles WHERE transfer_direction IS NULL;  -- 0 이어야 수렴
SELECT transfer_stage, COUNT(*) FROM articles
 WHERE source_id = 'bbc_gossip' GROUP BY transfer_stage;         -- rumour 단일이어야 정상
```

마지막으로 스팟 체크를 한다.
`docs/superpowers/2026-07-28-content-trust-audit-handoff.md` §3.5 에서 방출 어휘로 지목된 기사 3건 (content_hash 가 `096b26b9` · `cb0894b7` · `b38deb05` 로 시작) 의 `transfer_direction` 이 `out` 으로 들어갔는지 확인한다.
스팟 대상이 조회에 안 나오면 그 기사가 이후 정리에서 삭제됐을 수 있으니 실패로 단정하지 말고 행 존재부터 확인한다 (2026-08-02 실측에서 `096b26b9` 가 실제로 삭제 행이었다).

**2026-08-02 실측** — 방향 축 도입 소급 (459건) 을 이 절차로 실행했다.
정기 회차를 기다리지 않고 앞당길 때는 두 가지 표준 경로 우회가 가능하다.
컬럼 생성은 `MartStore(engine).ensure_schema()` 를 직접 호출하면 된다 (schema.sql 멱등 적용 · run.py 회차와 같은 경로라 안전).
재분류는 enrich 전용 런북 (`docs/runbook/2026-07-19-enrich-only-pass.md`) §3 의 분류 블록만 떼어 즉시 실행하면 된다.
결과는 1패스 수렴 — 규칙 경로 59건 (가십 전행 rumour) · LLM 400건 · 잔존 0.
재측정 (감사 스크립트 2회 실행) 은 단계 재현 불일치 24% → 6.6% · 방향 4.6% 로, 목표 (모델 흔들림 수준 약 9% 이하) 를 충족했다.

### 3.2. 표적 재분류 (일부 버킷만 다시 매길 때)

전건이 아니라 특정 버킷만 다시 볼 때가 있다 — 프롬프트를 좁게 고쳤거나, 한 단계에 오분류가 몰려 있을 때다.
전건 재분류보다 싸지만 (2026-08-02 실측: 59건 · LLM 3배치) 대상을 고르는 방식에 함정이 하나 있다.

**대상은 조건이 아니라 해시 목록으로 고정한다.**
`WHERE transfer_stage = 'other'` 로 되돌리면 그 회차에는 맞지만, 재분류로 값이 바뀐 행은 다음번에 같은 조건으로 잡히지 않는다.
프롬프트를 한 번 더 고쳐 다시 돌려야 할 때 대상 집합이 이미 흩어져 있는 것이다.
그래서 되돌리기 전에 대상 해시를 파일로 떠 두고, 재실행은 그 파일을 기준으로 한다.

```bash
uv run python - <<'PY'
import csv, os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c, open("stage_dump_other.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["content_hash", "transfer_stage", "transfer_direction"])
    rows = c.execute(text("SELECT content_hash, transfer_stage, transfer_direction "
                          "FROM articles WHERE transfer_stage = 'other'")).all()
    for r in rows:
        w.writerow(r)
print("대상 덤프:", len(rows), "행")
PY
```

되돌릴 때는 이 파일의 해시를 그대로 쓴다 (재실행에도 같은 파일을 쓴다).

```python
from sqlalchemy import bindparam, text
hashes = [r["content_hash"] for r in csv.DictReader(open("stage_dump_other.csv"))]
with eng.begin() as c:
    n = c.execute(text("UPDATE articles SET transfer_stage = NULL WHERE content_hash IN :hs")
                  .bindparams(bindparam("hs", expanding=True)), {"hs": hashes}).rowcount
```

이후 분류는 §2 스니펫과 같다.

**프롬프트를 바꿨다면 되돌리기 전에 dry-run 한다.**
배포판에서 대상 행을 읽기 전용으로 뽑아 로컬에서 한 배치만 분류하면, DB 를 건드리지 않고 새 프롬프트의 효과를 볼 수 있다 (Gemini 1회 호출).
고치려는 행만 넣지 말고 **이미 잘 분류된 행 몇 건을 대조군으로 함께** 넣는다 — 새 규칙이 정상 판정까지 되돌리는 과소 · 과대 교정을 그때 잡는다.

```bash
# VM 에서 대상 행을 JSON 으로 뽑아 로컬에 저장한 뒤, 로컬 체크아웃에서 분류만 돌린다
uv run python - <<'PY'
import json, os
from google import genai
from bullet_in.enrich import classify_stage_rows
from bullet_in.run import GEMINI_MODEL
rows = json.load(open("target_rows.json"))
out = classify_stage_rows(rows, genai.Client(api_key=os.environ["GEMINI_API_KEY"]), GEMINI_MODEL)
for r in rows:
    new, direction = out.get(r["content_hash"], ("(누락)", "-"))
    mark = "  " if r["transfer_stage"] == new else "→ "
    print(f'{mark}{r["content_hash"][:8]} {r["transfer_stage"]:13s} {new:13s} {(r["title_ko"] or "")[:38]}')
PY
```

**끝났다고 판단하는 기준은 잔존 0 이 아니다.**
분류 패스는 모델이 답을 돌려주기만 하면 오류 없이 수렴한다.
반드시 이동 내역을 유형별로 훑어 과교정을 확인한다 — 2026-08-02 에는 이 검사에서 스폰서십 계약 · 재계약 기사가 `agreed` 를 받은 것을 발견해 프롬프트를 한 번 더 고쳤다
(`docs/troubleshooting/2026-08-02-prompt-boundary-loosening-overcorrects.md`).

**2026-08-02 실측**: `other` 59건 표적 재분류 → 1패스 수렴 · 이동 22 · 유지 37 → 과교정 4건 발견 → 프롬프트 정정 후 같은 59건 재실행 (2패스 수렴) → 이동 17 · 유지 42.

## 4. 분포 검증

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c:
    total = c.execute(text("SELECT COUNT(*) FROM articles")).scalar()
    miss = c.execute(text("SELECT COUNT(*) FROM articles WHERE transfer_stage IS NULL")).scalar()
    print(f"total={total} 미태깅={miss}")
    for r in c.execute(text("SELECT COALESCE(transfer_stage,'<NULL>'), COUNT(*) "
                            "FROM articles GROUP BY transfer_stage ORDER BY 2 DESC")).all():
        print(f"  {r[0]:14s} {r[1]}")
PY
```

- `other` 가 비정상적으로 많으면 (이적 무관 기사 과다) 수집 단계 문제다 — 아래 참고.

## 알려진 한계

- **비-기사 링크가 `rumour` 등으로 오분류될 수 있다.** 라이브에서 "Want more transfer stories? Read Thursday's full gossip column" 같은 football.london 네비게이션 · teaser 링크가 `rumour` 로 태깅됐다. 근본 원인은 분류기가 아니라 **수집 단계의 이적 키워드 필터 미착수 (로드맵 Tier 1-3)** 로 비-기사 링크까지 적재되는 것이다. Tier 1-3 + 기존 데이터 정리가 들어오면 이 잡음이 줄어든다. 메모리 `tier1-cleanup-track` 참조.
- **재계약 기사도 공홈 official 배지를 받는다 — 의도된 동작 (2026-07-19 재검토 종결).** 공홈 수집이 taxonomy 판별 (Transfer news · Contract news + Men) 로 전환되며 1군 재계약 포함이 사용자 결정으로 확정됐다. 단계 enum 에 재계약이 없어 LLM 경로로 보내면 `other` (서빙 숨김) 로 떨어지므로, 규칙 경로의 official 태깅이 재계약을 노출하는 유일한 경로이기도 하다. 배경: `docs/superpowers/specs/2026-07-19-arsenal-official-api-recovery-design.md` §4.3.

- **타 구단 이적에 붙은 방향 값은 기준 구단이 없다 — 결정 보류 (2026-08-02 사용자 확정).**
프롬프트는 방향을 아스날 기준으로 정의하지만 (`in` = 아스날로 오는 이적), 모델은 타 구단 기사에서 그 이적 자체의 영입 · 방출로 답한다.
실측하면 `transfer_direction` 이 `in` · `out` 인 333건 중 35건이 아스날이 제목 · 요약 · 원제 어디에도 없는 타 구단 이적이고 (첼시 · PSG · 바르셀로나 등), 그중 28건이 `in` 이다.
기준 구단을 적는 칸이 없어 값만으로는 누구 기준인지 알 수 없다
— `articles.team` 은 전건 `arsenal` (여자팀 분리용 잔재) 이고 `players.club` 은 선수의 현재 소속이며 절반이 NULL 이다.
선택지는 셋이다: 아스날 기준을 고정해 타 구단 이적을 `none` 으로 되돌리거나, 주체 구단 기준으로 정의하고 기준 구단 컬럼을 신설하거나, 현행 값을 "영입성 · 방출성 주제 표지" 로 정의해 문서만 고치는 것이다.
결정은 방향을 처음 소비할 #144 (선수 페이지) 착수 때로 미뤘다
— 지금은 방향을 화면에 노출하지 않아 피해가 없고, 아스날 기준 축은 `players.transfer_status` (`in_link` · `out_link`) 가 선수 단위로 이미 들고 있어 선수 페이지가 그 값을 쓸 수 있기 때문이다.

## 참조

- spec: `docs/superpowers/specs/2026-06-30-tier2b-transfer-stage-design.md`
- 계획: `docs/superpowers/plans/2026-06-30-tier2b-transfer-stage.md`
- 단계 정의 단일 출처: `src/bullet_in/transfer_stage.py`
- 분류 패스: `src/bullet_in/enrich.py` (`classify_stage_rows`)
- 후속 트랙 (이적 키워드 필터 · 데이터 정리): 로드맵 `docs/superpowers/2026-06-28-v1-completion-roadmap.md` Tier 1
