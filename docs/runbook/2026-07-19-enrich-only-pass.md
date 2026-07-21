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
저장 직전 후처리 (표기 사전 · 환각 게이트 4축 · 문단 보정) 는 `enrich.finalize_translation` 한 벌뿐이므로 그것을 import 해서 쓴다.
여기에 `set_translation` 을 직접 부르면 게이트 경고 로그가 안 남고 400자 초과 문단이 안 쪼개져, 가십 단신 카드가 조용히 깨진다.

```bash
uv run python - <<'EOF'
import os, yaml
from pathlib import Path
from google import genai
from sqlalchemy import create_engine
from bullet_in.enrich import (classify_stage_rows, enrich_rows,
                              finalize_translation, partition_by_paywall)
from bullet_in.run import GEMINI_MODEL
from bullet_in.storage.mariadb import MartStore

def _cfg(path, key):
    return (yaml.safe_load(Path(path).read_text()) or {}).get(key, {})

mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
glossary = _cfg("config/glossary.yaml", "replacements")
name_map = _cfg("config/name_map.yaml", "names")
club_map = _cfg("config/club_map.yaml", "clubs")
for attempt in range(3):
    missing = mart.rows_missing_translation()
    if not missing:
        break
    by_hash = {r["content_hash"]: r for r in missing}
    para, trans = partition_by_paywall(missing)
    results = {}
    results.update(enrich_rows(trans, client, GEMINI_MODEL, mode="translate"))
    results.update(enrich_rows(para, client, GEMINI_MODEL, mode="paraphrase"))
    for h, v in results.items():
        mart.set_translation(h, *finalize_translation(
            v, by_hash.get(h, {}), glossary, name_map, club_map))
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

## 5. 전건 백필 — 번역 모델을 바꿨을 때

§2~§4 는 번역이 빠진 채 남아 있는 행 (**잔존**) 을 메우는 절차다.
번역 모델을 바꾸면 이미 번역된 행은 그대로 남아 표기가 두 모델로 섞이므로, 기존 행을 지우고 다시 번역해야 한다.
대상 선정이 `WHERE title_ko IS NULL` 이라 그냥 두면 신규 행만 새 모델로 번역된다.

되돌릴 수 없는 조작이다 — §5.1 스냅샷을 반드시 먼저 뜬다.
모델 교체 판단 자체의 절차는 `docs/runbook/2026-07-21-translation-model-ab.md` 에 있다.

**선행 조건**
- 회차 시각 (KST 09 · 15 · 21 · 03) 을 피한다 — 정기 실행과 API 키 · 속도 한도를 함께 쓰기 때문이다.
- 새 모델이 들어간 코드가 실제로 돌리는 서버에 반영돼 있어야 한다 (VM 이면 `git pull` 선행).
- 순차 루프라 걸리는 시간은 행당 평균 지연에 행 수를 곱한 값이다 — 224행 · 3.9초 기준 약 15분.

### 5.1. 스냅샷 (필수)

`content_hash` 를 키로 번역 4필드 (`title_ko` · `summary_ko` · `summary3_ko` · `body_ko`) 를 뜬다.
`title_original` · `source_id` 는 대조용이다.
번역 본문이 들어 있으니 **저장소 밖**에 두고 커밋하지 않는다 (공개 저장소).
재실행으로 복구된다고 보면 안 된다 — 되돌리려면 옛 모델이 그때도 살아 있어야 한다.

스키마까지 함께 뜬다 — 롤백할 때 이 덤프를 임시 테이블로 되살려 쓰기 때문이다 (§5.4).
`-p` 뒤 비밀번호는 `docker-compose.yml` 의 `MARIADB_ROOT_PASSWORD` 값이다.

```bash
mkdir -p ~/bullet-in-backups
docker exec bullet-in-mariadb-1 mariadb-dump -uroot -pbulletin \
  bulletin articles > ~/bullet-in-backups/$(date +%F)-articles-pre-backfill.sql
grep -c "INSERT INTO" ~/bullet-in-backups/*-articles-pre-backfill.sql
```

원격에서 돌렸으면 한 벌을 로컬로 내려 이중 보관한다.

```bash
scp -i ~/.ssh/seoulnow_deploy \
  ubuntu@155.248.164.17:'~/bullet-in-backups/*-articles-pre-backfill.sql' \
  ~/Documents/01_DE_project/.bullet-in-backups/
```

### 5.2. 번역 4필드 NULL

**`title_ko` 만 밀면 안 된다.**
`summary_ko` 가 남으면 `finalize_translation` 의 `retry = bool(row.get("summary_ko"))` 가 참이 되어 전 행이 재시도 행으로 판정된다.
그러면 게이트가 1차로 걸러 재번역 큐에 넣는 단계를 건너뛰고, 잘못 걸린 행은 곧바로 원문 제목으로 대체된다
— 새 모델이 멀쩡히 번역한 제목까지 영문 원문으로 굳는다.

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
with eng.begin() as c:
    n = c.execute(text("UPDATE articles SET title_ko=NULL, summary_ko=NULL, "
                       "summary3_ko=NULL, body_ko=NULL "
                       "WHERE title_ko IS NOT NULL")).rowcount
print("초기화:", n, "행")
EOF
```

### 5.3. 백필 실행 · 반영

- §3 수렴 패스를 그대로 돌린다 — 백필 전용 스크립트를 따로 만들지 않는다.
- §2 로 **잔존 0 을 확인한 뒤에만** §4 사이트 재생성 · 배포로 넘어간다.
중단된 상태에서 재생성하면 미번역 행이 원문으로 노출된다.
- 429 로 중단돼도 데이터는 안전하다 — 대상 선정이 `title_ko IS NULL` 이라 다시 돌리면 남은 것만 이어서 처리한다.

### 5.4. 롤백

덤프를 임시 테이블 `articles_restore` 로 되살린 뒤 `content_hash` 기준으로 번역 4필드만 되돌린다.
덤프를 직접 파싱하지 않는 이유는 본문에 따옴표 · 줄바꿈이 들어 있어 `INSERT` 문을 정규식으로 쪼개면 깨지기 때문이다.
MariaDB 가 자기 덤프를 읽게 두는 편이 안전하다.

```bash
DUMP=~/bullet-in-backups/2026-07-21-articles-pre-backfill.sql
sed 's/`articles`/`articles_restore`/g' "$DUMP" \
  | docker exec -i bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin

docker exec -i bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin <<'SQL'
UPDATE articles a JOIN articles_restore r ON a.content_hash = r.content_hash
   SET a.title_ko = r.title_ko, a.summary_ko = r.summary_ko,
       a.summary3_ko = r.summary3_ko, a.body_ko = r.body_ko;
SELECT ROW_COUNT() AS 복원행;
DROP TABLE articles_restore;
SQL
```

복원 후 §4 로 사이트를 다시 만든다.

## 6. 표기 사전 소급 적용 — 재번역 없이 표기만 고칠 때

`config/glossary.yaml` 에 교정 항목을 더해도 **이미 저장된 번역은 바뀌지 않는다.**
사전은 번역 직후 후처리로만 걸리기 때문이다.
그래서 사전을 늘린 뒤에는 저장된 행에 같은 치환을 한 번 더 돌려야 화면에 반영된다.

재번역 (§5) 과 혼동하지 말 것.
표기만 고치는 일이라면 API 를 부를 이유가 없고, 재번역하면 문장까지 달라져 비교 기준이 흔들린다.

- **비용** — API 호출 0회 · 수 초.
- **멱등** — 이미 정규형인 행은 치환이 걸리지 않아 몇 번 돌려도 같다.
- **주의** — 사전은 YAML 기재 순서대로 치환된다.
짧은 표기를 먼저 두면 긴 표기 규칙이 영영 안 걸린다 (`클럽 브뤼헤` 가 `클럽 브뤼허` 로 바뀌어 버리는 식).
순서 계약은 `tests/test_enrich.py` 가 실제 설정 파일을 읽어 고정하고 있다.
- **함께 볼 것** — 구단명은 `config/club_map.yaml` 의 등록 키도 정규형과 같아야 한다.
어긋나면 원문에 없는 구단명 게이트가 조용히 침묵한다.

```bash
uv run python - <<'EOF'
import os, yaml
from pathlib import Path
from sqlalchemy import create_engine, text
from bullet_in.enrich import apply_glossary

FIELDS = ("title_ko", "summary_ko", "summary3_ko", "body_ko")
glossary = (yaml.safe_load(Path("config/glossary.yaml").read_text())
            or {}).get("replacements", {})
eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    rows = [dict(r) for r in c.execute(text(
        "SELECT content_hash," + ",".join(FIELDS) +
        " FROM articles WHERE title_ko IS NOT NULL")).mappings()]

changed = 0
with eng.begin() as c:
    for r in rows:
        fixed = apply_glossary({f: r[f] for f in FIELDS}, glossary)
        if all(fixed[f] == r[f] for f in FIELDS):
            continue
        c.execute(text("UPDATE articles SET title_ko=:t, summary_ko=:s, "
                       "summary3_ko=:s3, body_ko=:b WHERE content_hash=:h"),
                  {"t": fixed["title_ko"], "s": fixed["summary_ko"],
                   "s3": fixed["summary3_ko"], "b": fixed["body_ko"],
                   "h": r["content_hash"]})
        changed += 1
print("표기 교정:", changed, "/", len(rows), "행")
EOF
```

반영이 끝나면 §4 로 사이트를 다시 만들고 배포한다.

## 7. 실패 모드

| 증상 | 판단 | 대응 |
|---|---|---|
| 3패스 후에도 같은 행 잔존 | 확률적 vs 구조적 판별 필요 | 동일 입력 프로브 — 트러블슈팅 `2026-07-19-gemini-stochastic-json-parse-failure.md` §4 |
| `Gemini rate limit(429)` 로그 후 중단 | 분당 속도 한도 | 기존 규칙 — 수 분 대기 후 재실행 또는 다음 회차 위임 |
| 잔존 0 인데 화면에 원문 노출 | §4 미실행 (DB 만 갱신) | `write_site` 재실행 |

## 8. 참고

- 모델 교체 판단 절차 · 채점 축: `docs/runbook/2026-07-21-translation-model-ab.md` (§8 이 이 런북 §5 를 가리킨다)
- 유사 패턴: `docs/runbook/2026-07-15-tone-backfill-ops.md` (재요약 전용 enrich 패스 — fetch 없음 동일)
- 2h 규칙 근거: `docs/troubleshooting/2026-07-15-benchmark-rate-limit-self-interference.md`
- 최초 사용: v1 마감 트랙 ③ (PR #58) — 실측 · 캡처 전 잔존 8 → 0 수렴
