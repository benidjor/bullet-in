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
        "SELECT source_id, body_level, COUNT(*) FROM articles "
        "WHERE title_ko IS NULL GROUP BY source_id, body_level")).all()
print("미번역 잔존:", rows or 0)
EOF
```

**잔존 확인과 실행 사이에 회차가 끼면 대상이 새로 생긴다 (2026-08-13 사고).**
15분 전 확인에서 잔존이 0 이었는데 그사이 정기 회차가 번역 실패 행을 하나 남겼고, 스니펫이 도는지만 보려고 붙인 §3 을 그대로 실행해 **승인 없이 Gemini 1회 · 운영 쓰기 1행**이 나갔다.

- §3 을 붙이기 **직전에** 이 절을 다시 돌린다 — 확인 목적이어도 운영에 붙는 순간 부작용은 실제다.
- 회차 시각 (KST 00 · 03 · … · 21시) 근처면 특히 그렇다.
- 의도치 않게 번역된 행은 선수 귀속이 빈 채로 남는다 (§3 의 한계) — 재추출로 따로 채워야 한다.

fmkorea 도 세어야 한다 (2026-07-30 개정).
전에는 ko 소스라 번역 대상이 아니라고 보고 제외했지만, 지금은 등급 1 (게시글 본문) 행이 재작성 경로로 처리된다.
`body_level` 을 함께 세면 그 회차가 어느 경로로 갈지 미리 보인다
— 등급 1 은 재작성 · 그 밖은 번역 · 재료가 아예 없으면 제목만 생성.

## 3. 수렴 패스 (최대 3회 반복)

`run.py` 의 enrich 블록과 같은 함수 · 순서를 재사용한다 — 규칙이 두 벌로 갈라지지 않게 새 로직을 만들지 않는다.
저장 직전 후처리 (표기 사전 · 환각 게이트 4축 · 문단 보정) 는 `enrich.finalize_translation` 한 벌뿐이므로 그것을 import 해서 쓴다.
여기에 `set_translation` 을 직접 부르면 게이트 경고 로그가 안 남고 400자 초과 문단이 안 쪼개져, 가십 단신 카드가 조용히 깨진다.
마지막 분류 블록도 run.py 의 현행 분류 패스와 동일한 형태를 유지한다 (규칙 경로 2형태 · 방향 축 스펙 §4).
**`rule_stage` 에 채택 경로를 함께 넘긴다** (2026-08-12 개정) — 빠뜨리면 공홈에서 제목으로 주워 온 기사까지 `official` 로 굳어, 구단이 이적 뉴스라고 표시하지 않은 기사에 오피셜 배지가 붙는다.

**생성 함수에 넘기는 재료도 run.py 와 같아야 한다 (2026-08-13 개정).**
확정 링크 명단 (`confirmed_link_roster`) 은 아스날이 이름으로 안 나오는 기사를 판단하는 근거이고, 이름 사전 (`gate_name_map`) 과 구단 사전은 재작성 게이트가 지어낸 인명 · 구단을 잡는 축이다.
빠뜨리면 같은 기사가 회차 경로와 이 패스에서 다르게 판정된다
— 명단 없이 번역된 행은 아스날 관련 기사인데도 무관 글로 읽히고, 사전 없이 재작성된 행은 인명 게이트가 꺼진 채 통과한다.

**이 패스는 선수 귀속 (`article_players`) 을 만들지 않는다.**
회차 경로는 번역 직후 같은 블록에서 추출 쌍을 저장하는데 이 스니펫에는 그 단계가 없고, 한 번 번역된 행은 `title_ko IS NULL` 조건에서 빠져 다음 회차가 다시 만지지 않는다.
그래서 이 패스로 수렴시킨 행의 귀속은 재추출 (`reextract_article_players`) 로 따로 채워야 한다.

```bash
uv run python - <<'EOF'
import os, yaml
from pathlib import Path
from google import genai
from sqlalchemy import create_engine
from bullet_in.enrich import (classify_stage_rows, enrich_rows,
                              finalize_translation, partition_by_body_level,
                              partition_generatable, rewrite_rows_guarded,
                              title_only_rows)
from bullet_in.run import GEMINI_MODEL
from bullet_in import transfer_stage
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.players import PlayerStore

def _cfg(path, key):
    return (yaml.safe_load(Path(path).read_text()) or {}).get(key, {})

mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
glossary = _cfg("config/glossary.yaml", "replacements")
pstore = PlayerStore(mart.engine)
name_map = pstore.gate_name_map()
club_map = _cfg("config/club_map.yaml", "clubs")
roster_material = pstore.confirmed_link_roster()
for attempt in range(3):
    missing = mart.rows_missing_translation()
    if not missing:
        break
    by_hash = {r["content_hash"]: r for r in missing}
    generatable, title_only = partition_generatable(missing)
    rewrite_rows, translate_rows = partition_by_body_level(generatable)
    results = {}
    results.update(enrich_rows(translate_rows, client, GEMINI_MODEL,
                               mode="translate", roster=roster_material))
    rewritten, gate_reports = rewrite_rows_guarded(
        rewrite_rows, client, GEMINI_MODEL, name_map=name_map, club_map=club_map,
        roster=roster_material)
    results.update(rewritten)
    results.update(title_only_rows(title_only, client, GEMINI_MODEL))
    for h, v in results.items():
        title_ko, s_ko, s3_ko, body_ko, _ = finalize_translation(
            v, by_hash.get(h, {}), glossary, name_map, club_map)
        mart.set_translation(h, title_ko, s_ko, s3_ko, body_ko)
    for h, rep in gate_reports.items():
        mart.set_rewrite_retention(h, rep["retention"])
    print(f"패스 {attempt + 1}: {len(results)} / {len(missing)} 성공 "
          f"· 재작성 {len(rewritten)} · 제목만 {len(title_only)}")
print("최종 미번역 잔존:", len(mart.rows_missing_translation()))
llm_rows = []
stage_ruled = {}
for r in mart.rows_missing_stage():
    stage_fixed, direction_fixed = transfer_stage.rule_stage(
        r["source_id"], r.get("accept_path"))
    if stage_fixed and direction_fixed:
        mart.set_stage(r["content_hash"], stage_fixed, direction_fixed)
        continue
    if stage_fixed:
        stage_ruled[r["content_hash"]] = stage_fixed
    llm_rows.append(r)
for h, (stage, direction) in classify_stage_rows(llm_rows, client, GEMINI_MODEL).items():
    mart.set_stage(h, stage_ruled.get(h, stage), direction)
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

**이 스니펫은 `ops.html` 을 다시 만들지 않는다.**
운영 뷰는 `write_ops` 가 만드는데 그것은 `run.py` 안에서만 돌기 때문이다.
그래서 재생성 뒤 `site/` 를 보면 `index.html` · `players.html` 은 방금 시각인데 `ops.html` 만 직전 정기 회차 시각으로 남는다.
**이것을 "VM 에 코드가 안 올라갔다" 로 오해하기 쉽다** — 2026-08-03 에 실제로 그 오진이 나왔다.
운영 뷰의 변경까지 확인하려면 다음 정기 회차를 기다리거나 `write_ops` 를 따로 호출한다.

```bash
ls -l --time-style=+%H:%M site/index.html site/players.html site/ops.html
# ops.html 만 낡았다면 정상 — 코드 반영 여부는 git log 로 확인한다
```

**실행 전 점검 (2026-08-02 사고 이후 필수)** — 다른 트랙의 배치가 도는 중에 렌더하면 중간 상태가 그대로 배포된다.
소급 재분류처럼 값을 비웠다 채우는 작업과 겹치면 전 기사가 "기타" 로 집계된 페이지가 공개된다
(`docs/troubleshooting/2026-08-02-rerender-during-reclassification.md`).

```bash
git log --oneline -3                       # pull 로 새로 들어온 커밋의 성격 확인
ps aux | grep -E '[b]ullet_in|[b]ackfill' | grep -v "bash -c"  # 돌고 있는 배치가 없는지 확인
```

두 번째 grep (`-v "bash -c"`) 은 자기 오탐 방지다.
이 점검을 `ssh <호스트> '<명령 모음>'` 으로 실행하면 감싼 bash 의 명령줄에 "bullet_in" 문자열 (뒤따르는 재생성 스니펫의 import) 이 들어 있어, `[b]` 트릭으로 grep 자신은 제외해도 그 bash 가 걸린다.
2026-08-07 사다리 배포에서 실제로 이 오탐으로 반영이 한 번 중단됐다.

새 커밋이 스키마 · 분류 체계를 바꾸는 것이면 그 트랙의 롤아웃 (소급 배치) 이 끝났는지 먼저 확인한다.
확인 목적의 배포라면 아예 미뤄도 된다 — 다음 정기 회차가 렌더 · 배포까지 한다.

**fmkorea 무관 글 필터를 빼먹으면 안 된다 (2026-08-07 정정).**
PR #225 부터 run.py 서빙 경로는 `write_site` 전에 `serving_rows` 로 fmkorea 무관 글을 거른다.
필터 없는 옛 스니펫으로 재생성하면 서빙에서 감춰 둔 타 구단 기사 (2026-08-07 실측 12건) 가 목록 · 상세 · 선수 페이지에 다시 노출된다.
아래 스니펫은 그 필터까지 포함해 run.py 서빙 경로와 1:1 이다 (2026-08-07 사다리 배포에서 실사용).

**반환값이 셋이다 (2026-08-29 정정).**
`serving_rows` 는 `(남길 행, 무관 제외 수, 옛 글 제외 수)` 를 돌려주는데 이 스니펫이 오래 두 값으로 받고 있었다.
두 회차에서 각각 걸렸다 — **스니펫을 옮겨 적는 쪽이 매번 고쳐 쓰고 런북은 안 고쳐져 같은 자리가 반복됐다.**
**손으로 옮겨 적지 말고 `bullet_in.confirm_player._render` 를 부르는 편이 안전하다** — 그 함수는 run.py 서빙 경로와 1:1 로 유지된다.

```python
from bullet_in.confirm_player import _render
_render(create_engine(os.environ["MARIADB_URL"]))     # site/ 에 재생성
```

```bash
uv run python - <<'EOF'
import os, yaml
from sqlalchemy import create_engine, text
from bullet_in.run import SERVING_SELECT_SQL, LINKED_HASHES_SQL, serving_rows
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry, journalist_directory, outlet_directory
from bullet_in.serve.render import write_site
from bullet_in.storage.players import PlayerStore

engine = create_engine(os.environ["MARIADB_URL"])
with engine.connect() as c:
    rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
    linked = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())
# 단계가 빈 행은 표시 · 집계가 전부 "기타" 로 쏠린다 — 중간 상태면 여기서 멈춘다
blank = sum(1 for r in rows if not r["transfer_stage"])
assert blank == 0, f"stage 빈 행 {blank} — 재분류 수렴 후 다시 실행"
# fmkorea 무관 글 서빙 제외 (PR #225) — 어댑터 생성 없이 config 에서 같은 인정 집합을 만든다
cfg = yaml.safe_load(open("config/sources.yaml", encoding="utf-8"))
fm_cfg = next(s for s in cfg["sources"] if s.get("adapter") == "fmkorea")
rows, hidden, stale = serving_rows(rows,
    relevance_terms=fm_cfg.get("config", {}).get("relevance_terms", []),
    player_names=PlayerStore(engine).confirmed_ko_names(),
    linked=linked)
print(f"서빙 제외 — 무관 {hidden}건 · 옛 글 {stale}건")
write_site(rows, load_sources("config/sources.yaml"), "site",
           directory=journalist_directory("config/credibility.yaml"),
           registry=load_registry("config/credibility.yaml"),
           outlet_dir=outlet_directory("config/credibility.yaml"))
print("site 재생성:", len(rows), "행")
EOF
```

**배포 후 확인은 보이는 자리에서 한다** — 배지 · 카드 요소는 `index.html` · `all.html` 에서,
본문 · 원문 링크는 `article/<hash>.html` 에서 grep 한다.

**소급 뒤 옛 값이 남아도 정상인 자리가 둘 있다 (2026-08-29 추가).**
모르고 보면 「소급이 덜 됐다」 로 읽힌다.

- **`title_original`** — 원문 제목은 게이트의 근거라 바꾸지 않는다. 표기 소급은 번역 4필드 (`title_ko` · `summary_ko` · `summary3_ko` · `body_ko`) 만 만진다.
- **`ops.html`** — 회차 스냅숏이라 소급 이전에 찍힌 제목이 그대로 남는다.

**본문에만 나오는 값은 목록 페이지에서 안 잡힌다** — `all.html` 에 0 이 나와도 상세 페이지에서 따로 센다.
상세 페이지에서 카드 요소를 찾으면 항상 빈 결과가 나와 이상을 놓친다
(`docs/troubleshooting/2026-08-02-badge-condition-collides-with-hide-policy.md`).

## 5. 전건 백필 — 번역 모델을 바꿨을 때

§2~§4 는 번역이 빠진 채 남아 있는 행 (**잔존**) 을 메우는 절차다.
번역 모델을 바꾸면 이미 번역된 행은 그대로 남아 표기가 두 모델로 섞이므로, 기존 행을 지우고 다시 번역해야 한다.
대상 선정이 `WHERE title_ko IS NULL` 이라 그냥 두면 신규 행만 새 모델로 번역된다.

되돌릴 수 없는 조작이다 — §5.1 스냅샷을 반드시 먼저 뜬다.
모델 교체 판단 자체의 절차는 `docs/runbook/2026-07-21-translation-model-ab.md` 에 있다.

**선행 조건**
- 회차 시각 (3시간 간격 하루 8회 · KST 00 · 03 · 06 · 09 · 12 · 15 · 18 · 21) 을 피한다 — 정기 실행과 API 키 · 속도 한도를 함께 쓰기 때문이다 (8회 실측 정정 2026-08-01).
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

## 5.5. 소급 재작성 — 재작성 프롬프트를 바꿨을 때

fmkorea 게시글 본문 (등급 1) 은 번역이 아니라 재작성 경로를 탄다.
재작성 프롬프트를 고치면, §5 의 번역 모델 교체와 마찬가지로 이미 처리된 행은 옛 프롬프트 결과 그대로 남는다.

§5 와 다른 점은 번역 4필드를 비우지 않는다는 것이다.
비우는 창에 재렌더가 겹치면 그 사이 빈 페이지가 그대로 공개된다 (2026-08-02 실사고, `docs/troubleshooting/2026-08-02-rerender-during-reclassification.md`).
그래서 소급 재작성은 필드를 지웠다 채우는 2단계가 아니라, CLI 한 번으로 옛 값을 새 값으로 바로 덮어쓴다.

```bash
uv run python -m bullet_in.backfill_rewrite --dry-run --limit 3          # 표본 확인
uv run python -m bullet_in.backfill_rewrite --limit 20 --offset 0        # 1구간
uv run python -m bullet_in.backfill_rewrite --limit 20 --offset 20       # 2구간
```

- 재작성은 멱등이 아니다.
같은 입력이어도 표현이 매번 달라지므로, 중단 후 재실행하면 처리된 행부터 이어가는 것이 아니라 대상 전체가 처음부터 다시 돈다.
- 대상 선정 조건 (`body_level=1 AND title_ko IS NOT NULL`) 은 저장 뒤에도 그대로 참이라 처리한 행이 대상에서 빠지지 않는다.
그래서 `--limit` 만 반복하면 같은 앞쪽 구간을 계속 다시 재작성한다 — 구간을 옮기려면 `--offset` 을 함께 써야 한다.
- 429 를 만나면 그 실행이 통째로 중단된다.
남은 행은 다시 실행하면 된다 — 데이터가 깨지지는 않는다.
- 스냅샷은 §5.1 을 그대로 쓴다.
번역 4필드를 뜨는 절차이므로 대상이 재작성이어도 같은 덤프로 대조 · 롤백할 수 있다.
- 끝나면 §4 로 사이트를 다시 만든다.

## 5.6. 재작성 게이트 잔존 판독 — 경고를 어디까지 손봐야 하나

재작성 패스를 돌리면 게이트에 걸린 행마다 경고가 한 줄씩 남는다.
전부 손봐야 하는 것은 아니다 — 축마다 뜻이 다르고, 구조적으로 걸릴 수밖에 없는 유형이 있다.

```
재작성 게이트 잔존 content_hash=678f0cde… 잔존율=0.765 누락=['19'] 신규수치=[] 인용훼손=['…'] 인명=[] 구단=[] 시도=3
```

### 5.6.1. 기준값 (2026-08-03 · 82행 전건 소급)

| 축 | 잔존 행 | 뜻 |
| --- | --- | --- |
| 인명 주입 | 0 | 원문에 없는 사람 이름 — **0 이 정상** |
| 구단 주입 | 0 | 원문에 없는 구단 — **0 이 정상** |
| 신규 수치 | 2 | 원문에 없는 숫자를 만듦 |
| 숫자 누락 | 15 | 원문 숫자가 산출물에서 빠짐 |
| 인용 훼손 | 5 | 따옴표 안 발화가 원형이 아님 |

- 잔존 행은 19 / 82 (23%) 였고 전부 시도 3회를 소진했다.
- **잔존 비율이 곧 비용이다** — 잔존 행은 통과 행의 세 배를 호출한다.
비율이 크게 오르면 프롬프트나 게이트 임계를 의심한다.
- 잔존율은 최대 0.765 · 임계 (0.75) 초과가 1행이었다.

### 5.6.2. 인용이 많은 기사는 잔존율이 높은 것이 정상이다

인용문은 재작성 대상이 아니라 원형 보존이 계약이다.
그래서 인용 비중이 큰 기사는 복제 게이트에 구조적으로 걸린다 — **인용 원형 보존과 복제 게이트가 서로 반대되는 것을 요구하는 셈이다.**

구조적으로 걸린 것인지 실제 문제인지는 인용을 뺀 지문만 다시 재면 가려진다.

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
from bullet_in.fidelity import quote_spans, char_ngram_retention
eng = create_engine(os.environ["MARIADB_URL"])
r = eng.connect().execute(text(
    "SELECT body_source, body_ko FROM articles WHERE content_hash LIKE '678f0cde%'")).one()
src, out = r[0] or "", r[1] or ""
qs = quote_spans(src)
for q in qs:
    out = out.replace(q, " ")
print("인용", len(qs), "개 ·", sum(len(q) for q in qs), "자 / 원문", len(src), "자")
print("인용 제외 지문 잔존율:", round(char_ngram_retention(src, out), 3))
EOF
```

실측 — 인터뷰 기사 하나가 원문 1992자 중 인용이 854자 (43%) 였고, 잔존율 0.765 가 인용을 빼면 0.566 으로 내려갔다.
이런 행은 손댈 것이 없다.

### 5.6.3. 인용 훼손은 눈으로 대조한 뒤 판단한다

경고가 곧 훼손은 아니다.
중첩 따옴표가 있는 발화에서 경계가 밀릴 수 있으므로 원문과 산출물을 직접 대조한다.

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
from bullet_in.fidelity import missing_quotes
eng = create_engine(os.environ["MARIADB_URL"])
r = eng.connect().execute(text(
    "SELECT body_source, body_ko FROM articles WHERE content_hash LIKE '678f0cde%'")).one()
for q in missing_quotes(r[0] or "", r[1] or ""):
    print("원문 발화:", q[:60])
    print("  산출물에 존재:", q[:30] in (r[1] or ""))
EOF
```

산출물에 그 발언이 없으면 실제 훼손이다.
모델이 세 번 재시도에도 따르지 않은 경우이고, 최선안이 채택된 채 경고만 남는다 (본문을 버리지 않는 설계).
수동 정정 대상은 발언 내용이 바뀐 것뿐이다 — 조사나 공백 차이는 게이트가 이미 무시한다.

### 5.6.4. 조치 우선순위

1. **인명 · 구단 주입** — 하나라도 나오면 즉시 확인한다.
지어낸 인물 · 구단은 이 파이프라인이 가장 경계하는 유형이고, 실측 기준값이 0 이다.
2. **인용 훼손** — §5.6.3 으로 대조한 뒤 실제면 수동 정정.
3. **신규 수치** — 원문에 그 숫자가 있는지 확인한다.
단위 환산 관용 때문에 배수 관계인 표기 변경은 통과하므로, 값이 맞아도 표기가 바뀐 경우가 있다.
4. **숫자 누락** — 단발 토큰 (나이 · 등번호 · 경기 수) 이면 대개 부차적이다.
금액 · 이적료 · 연도가 빠졌으면 확인한다.
5. **잔존율 초과** — §5.6.2 로 인용 비중을 먼저 본다.

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
