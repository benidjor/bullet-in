# 런북 — 개별 행 복구 · 삭제 정리 (2026-07-27)

오염된 행을 원문으로 되돌리거나, 잉여 행을 지우고 화면까지 반영하는 절차.
URL 정합 가드 (#143) 도입 후 BBC 오염 3행 복구와 온스테인 전환기 중복 2행 정리를 이 순서로 수행했다.

## 1. 언제 쓰나

- 다른 소스가 덮어써서 제목 · 기자 · 본문이 원문과 달라진 행을 되돌릴 때 (복구).
- 같은 기사를 가리키는 행이 둘 이상 남았을 때 하나만 남기고 지울 때 (정리).
- 정기 회차는 이런 행을 고치지 않는다 — 재분류 · 재번역 대상이 "비어 있는 행" 뿐이라 값이 채워진 채 틀린 행은 그대로 남는다.

## 2. VM DB 접속 — 비밀번호를 옮겨 적지 않는다

기존 스니펫은 `-uroot -pbulletin` 을 직접 적지만, 계정 · 비밀번호가 바뀌면 조용히 실패한다.
`.env` 의 `MARIADB_URL` 에서 뽑아 쓰면 한 곳만 보면 된다.

```bash
cd /home/ubuntu/bullet-in
U=$(grep '^MARIADB_URL=' .env | sed -E 's#.*://([^:]+):([^@]+)@[^/]+/([^?]+).*#\1|\2|\3#')
USER="${U%%|*}"; REST="${U#*|}"; PASS="${REST%%|*}"; DB="${REST##*|}"
docker exec -i bullet-in-mariadb-1 mariadb -u"$USER" -p"$PASS" "$DB" <<'SQL'
SELECT ...;
SQL
```

- `docker exec` 에 `-i` 를 쓰되 **heredoc 과 함께만** 쓴다 (`-e` 단문에 `-i` 를 붙이면 뒤따르는 스크립트를 stdin 으로 삼킨다 — `docs/troubleshooting/2026-07-26-remote-render-silent-pitfalls.md`).
- 원격 스크립트 서두에는 `export PATH="$HOME/.local/bin:$PATH"` 를 고정한다 (비대화형 SSH 는 `uv` 를 못 찾는다).

## 3. 복구 — 단건 URL 재수집

같은 소스로 다시 수집하면 가드가 "같은 소스의 갱신" 으로 통과시킨다.
번역 4필드는 자동으로 비워져 다음 enrich 가 다시 채운다.

```bash
# ① 드라이런 — 무엇이 들어갈지만 확인 (DB 무변경)
uv run python -m bullet_in.refetch_urls --source-id bbc_sport \
  --url "https://www.bbc.com/sport/football/articles/<id1>" \
  --url "https://www.bbc.com/sport/football/articles/<id2>" \
  --dry-run 2>&1 | tee /tmp/refetch-dry.log
# 기대: [dry-run] 검증 N건 (미적재) · 각 줄에 영문 제목 · body 길이 · authors

# ② 실행 — --dry-run 만 뺀다
uv run python -m bullet_in.refetch_urls --source-id bbc_sport \
  --url "..." --url "..." 2>&1 | tee /tmp/refetch-run.log
# 기대: 적재 N · 동일 내용 생략 0 · 기존 기사 유지 0
```

- `기존 기사 유지` 가 0 이 아니면 가드가 막은 것이다 — 대상 행의 `source_id` 가 지정한 값과 다른지 확인한다.
- 제목을 못 뽑으면 그 URL 은 건너뛴다 (불완전한 값으로 기존 행을 덮지 않는다).
- 라이브 사이트 접촉이므로 출력 확인 목적의 재실행은 하지 않는다 — `tee` 로 남긴다.

확인 쿼리.

```sql
SELECT SUBSTRING(url,-12) AS url_tail, revision, tier, journalist,
       LEFT(title_original,40) AS title, (title_ko IS NULL) AS ko_reset,
       LENGTH(body_source) AS body_len
FROM articles WHERE url LIKE '%<id1>' OR url LIKE '%<id2>';
```

- revision 이 1 올라가고 · 원문 제목 · 기자 · 본문이 돌아오고 · `ko_reset` 이 1 이면 정상이다.
- `transfer_stage` 는 **비워지지 않는다** — 오염 제목으로 정해진 값이 남는다.
  복원된 본문을 읽어 값이 맞는지 직접 확인하고, 틀렸을 때만 손댄다 (제목만 보고 판단하지 않는다).

## 4. 정리 — 잉여 행 삭제

지우기 전에 남길 행과 지울 행의 근거를 눈으로 확인한다.

```sql
-- 지우기 전 값 보존 (로그에 남긴다)
SELECT content_hash, url, source_id, title_original, title_ko, transfer_stage, fetched_at
FROM articles WHERE LEFT(content_hash,8)='<지울 해시 앞 8자>'\G

DELETE FROM articles
WHERE LEFT(content_hash,8)='<지울 해시 앞 8자>' AND source_id='<예상 소스>';
SELECT ROW_COUNT();
```

- `AND` 조건을 하나 더 걸어 오삭제를 막는다 (해시 앞 8자만으로 지우지 않는다).
- 본문이 있는 행 (완전체) 과 없는 행 (스텁) 이 같은 기사를 가리키면 **완전체를 남긴다**.
- 트윗 주소 행과 기사 주소 행이 같은 기사면 기사 주소 행을 남긴다.

## 5. 수렴 · 재렌더 · 배포

번역이 비워진 행이 있으면 먼저 채운다 (`docs/runbook/2026-07-19-enrich-only-pass.md` §2 · §3).
그다음 사이트를 다시 만들고, **게이트를 통과할 때만** 배포한다.

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

# 게이트 — 새 값이 들어갔고 옛 값이 사라졌을 때만 배포
d=$(grep -rl "<지운 해시>" site/ | wc -l); k=$(grep -rl "<남긴 해시>" site/ | wc -l)
[ "$d" -eq 0 ] && [ "$k" -ge 1 ] && ./infra/deploy-site.sh
```

SELECT 는 반드시 `bullet_in.run.SERVING_SELECT_SQL` 을 import 한다 (컬럼을 옮겨 적으면 서빙 코드와 어긋난다).

## 6. 라이브 검증

응답 코드가 아니라 **본문 제목**으로 판정하고, 무확장 경로의 캐시를 감안한다.
절차와 함정은 `docs/troubleshooting/2026-07-27-pages-deletion-verification-traps.md` 에 있다.

## 7. 실측 (2026-07-27)

- BBC 오염 3행 복구: `적재 3 · 동일 내용 생략 0 · 기존 기사 유지 0` → revision 3 · 영문 원제 · 기자 복원 · 본문 1.3k~4.2k 자 · enrich 4/4 수렴.
- 온스테인 전환기 정리: 트윗 주소 행 1건 · 기사 주소 중복 스텁 1건 삭제 → 재렌더 444행 · 배포.
- 정기 회차의 가드 실측: `drop 집계 — 동일 내용 생략 88 · 기존 기사 유지 3 · 여자팀 0 · 기자 allowlist 32`.
