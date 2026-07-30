# 새 컬럼 · 1회 백필을 머지 전에 검증하는 절차 (2026-07-30)

컬럼을 하나 더하고 기존 행을 채우는 변경은 VM 에서 한 번 돌리면 되돌리기가 번거롭다.
이 런북은 머지 전에 로컬에서 규칙과 CLI 를 확인하는 순서다.
본문 출처 등급 (`body_level`) 가드 (PR #156) 를 검증할 때 쓴 순서이고, 번역 신뢰성 계획서의 Task 9 · 10 도 같은 절차를 따른다.

기존 `docs/runbook/2026-07-23-config-tier-backfill-local-verify.md` 와는 성격이 다르다.
그쪽은 사본에 **쓰고** 렌더까지 해서 눈으로 보는 절차라 스냅샷과 롤백이 필수다.
이 절차의 1절은 쓰기가 없어 스냅샷이 필요 없고, 2절은 통합 테스트 DB 에만 쓴다.

## 전제

- 로컬 `bulletin_mock` — 배포판 사본 (`docs/runbook/2026-07-22-mockup-rerender-from-vm.md` 로 채운다).
- 로컬 `bulletin_test` — 통합 테스트가 쓰는 DB.
`tests/integration/conftest.py` 가 만들고 회차마다 비우므로 예행 무대로 써도 된다.
- `set -a; source .env; set +a` 후 실행 (이 프로젝트는 dotenv 미사용).

## 1. 규칙을 사본에 읽기 전용으로 걸어 본다

배정 규칙을 파이썬으로 import 해서 분포만 뽑는다.
**사본에 컬럼을 만들지 않는다** — 규칙 확인에는 쓰기가 필요 없고, 사본은 라이브 대조용으로 그대로 두는 편이 낫다.

```bash
uv run python - <<'PY'
import os
from collections import Counter
from sqlalchemy import create_engine, text
from bullet_in.backfill_body_level import level_for      # 백필과 같은 함수를 쓴다
e = create_engine(os.environ["MARIADB_URL"].replace("/bulletin", "/bulletin_mock"))
with e.connect() as c:
    rows = c.execute(text("SELECT source_id, outlet, body_source FROM articles")).all()
per = {}
for s, o, b in rows:
    per.setdefault(s, Counter())[level_for(s, o, b)] += 1
print("전체:", dict(sorted(Counter(level_for(*r) for r in rows).items())))
for s, c in sorted(per.items()):
    print(f"  {s:18} " + " · ".join(f"등급{lv} {c.get(lv, 0)}" for lv in (0, 1, 2)))
PY
```

- **규칙을 옮겨 적지 않는다** — 백필 모듈의 함수를 그대로 import 한다.
스니펫에 규칙을 다시 쓰면 어긋난다 (`docs/troubleshooting/2026-07-19-runbook-snippet-logic-drift.md`).
- **분포를 소스별로 본다** — 전체 합계는 이상을 가린다.
PR #156 검증에서는 등급 1 이 `fmkorea` 에만 나온다는 점이 규칙이 맞다는 근거였다.
- **스펙에 실측값이 있으면 대조한다** — 값이 다르면 규칙이 틀렸거나 사본이 낡았다.

순수 함수 (정규식 · 추출기) 도 같은 방식으로 실제 본문에 걸어 본다.
계약의 시험 사례가 실제 형식을 담았는지 이 단계에서 확인한다 (`docs/troubleshooting/2026-07-30-agreed-contract-vs-real-data.md`).

## 2. 통합 테스트 DB 에서 CLI 를 예행한다

`bulletin_test` 에 표본 몇 행을 넣고 스키마 적용과 백필을 실제로 돌린다.

```bash
export MARIADB_URL="mysql+pymysql://root:bulletin@localhost:3306/bulletin_test"

uv run python - <<'PY'
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from bullet_in.storage.mariadb import MartStore
e = create_engine(os.environ["MARIADB_URL"])
st = MartStore(e)
st.ensure_schema(); st.ensure_schema()      # 멱등 ALTER 확인 — 두 번 적용
with e.begin() as c:
    c.execute(text("DELETE FROM articles"))
    for h, sid, outlet, body in [("bl1", "fmkorea", "The Athletic", "커뮤니티가 옮긴 본문"),
                                 ("bl2", "fmkorea", "BBC", "Arsenal news."),
                                 ("bl3", "fmkorea", "The Telegraph", None),
                                 ("bl4", "bbc_gossip", None, "Gossip line.")]:
        c.execute(text("INSERT INTO articles (content_hash,url,source_id,outlet,"
                       "body_source,title_original,published_at) "
                       "VALUES (:h,:u,:s,:o,:b,'T',:p)"),
                  {"h": h, "u": f"https://x.test/{h}", "s": sid, "o": outlet, "b": body,
                   "p": datetime(2026, 7, 27, tzinfo=timezone.utc)})
PY

uv run python -m bullet_in.backfill_body_level --dry-run   # 집계만 · DB 쓰기 없음
uv run python -m bullet_in.backfill_body_level             # 실제 적용
uv run python -m bullet_in.backfill_body_level             # 재실행 → 대상 0건
```

확인할 것은 넷이다.

- **멱등 ALTER** — `ensure_schema()` 연속 호출이 오류 없이 통과.
- **드라이런 무쓰기** — 드라이런 뒤에도 컬럼이 NULL 로 남아 있다.
- **배정 결과** — 표본별 기대값과 일치 (위 표본은 `1` · `2` · `0` · `2`).
- **재실행 0건** — 두 번째 실행이 대상 0건을 보고한다 (멱등).

끝나면 `DELETE FROM articles` 로 정리한다.
통합 테스트 fixture 도 회차마다 비우지만, 다음 실행까지 남겨 두면 수동으로 확인할 때 헷갈린다.

## 3. 보고 형식

수치는 어떤 명령 · 쿼리로 얻었는지 함께 적는다.
사본을 썼으면 사본의 수집 시각을 함께 적는다 (`SELECT MAX(fetched_at)`).

## 4. 함정 — 건수는 실행 시점에 다시 센다

사본은 스냅샷이고 라이브는 계속 늘어난다.
`fmkorea` 의 본문 없는 행은 2026-07-27 사본에서 26건이었고 07-29 라이브에서 29건이었다 (이틀에 3건).

스펙이나 계획서에 적힌 건수는 그 문서를 쓴 날의 값이다.
VM 에서 실행하기 직전에 다시 세고, 차이가 크면 규칙부터 다시 확인한다.

## 참고

- 사본 채우기 · 드리프트 확인 — `docs/runbook/2026-07-22-mockup-rerender-from-vm.md`.
- 쓰기를 동반하는 로컬 재처리 — `docs/runbook/2026-07-23-config-tier-backfill-local-verify.md`.
- VM 반영 · 배포 — `docs/runbook/2026-07-24-vm-live-reprocess-deploy.md`.
- 행 복구 · 정리 — `docs/runbook/2026-07-27-row-recovery-cleanup.md`.
