# 저장된 주소를 고치는 절차 — 신원 이전 (2026-08-29)

`articles.url` 을 고치는 일은 값 하나를 바꾸는 일이 아니라 **그 행의 신원을 옮기는 일**이다.
`content_hash` 가 주소에서 파생되고 (`canonical.py:37` · `sha256(원문 제목 | canonical_url(url))`), 그 해시를 네 자리가 참조하기 때문이다.

이 절차는 2026-08-29 에 세 번 돌렸다 — 병합 17묶음 · 신원 이전 107행 · 스카이 8행.
세 번 다 귀속을 하나도 안 잃었고 고아 증가가 0 이었다.

## 1. 왜 손으로 `UPDATE` 하면 안 되나

```sql
UPDATE articles SET url = 'https://…' WHERE content_hash = '…';
```

**이 문장은 그 자리에서 아무 문제도 안 낸다.**
문제는 **다음 회차**에 난다 — 같은 기사가 재수집되면 새 주소로 해시가 다시 계산되고, upsert 의 마지막 줄이 그것을 덮어쓴다.

```sql
ON DUPLICATE KEY UPDATE
   title_ko = IF(articles.content_hash = VALUES(content_hash), articles.title_ko, NULL),
   …
   content_hash = VALUES(content_hash)     -- SET 목록의 맨 끝
```

**해시가 바뀌면 넷이 함께 떨어진다.**

| 자리 | 무슨 일이 나나 |
| --- | --- |
| `article_players` | 옛 해시를 가리킨 채 고아가 된다 (PK 의 한 축) |
| `players.first_seen` | 없는 기사를 가리킨다 |
| `site/article/<해시>.html` | 다음 렌더에서 잔여 페이지로 지워진다 |
| 번역 4필드 | 위 `IF()` 가 NULL 로 지우고 다시 번역한다 (**Gemini 호출**) |

2026-08-29 04:35 에 주소 110행을 손으로 고쳤더니 회차 두 번 만에 8행의 해시가 갈렸고, 고아 귀속이 213 → 256 이 됐다.

## 2. 선행 조건 — 규칙이 맞는지 먼저 본다

**배치는 `canonical_url` 을 그대로 믿는다.**
규칙이 틀린 채로 돌리면 **틀린 주소를 저장값으로 굳힌다.**

같은 날 dry-run 이 스카이 46행을 기사에 못 가는 주소로 쓸 계획을 냈다.

```bash
# 정규화 결과가 실제로 열리는지 — 대상 호스트마다 한 번씩만 받는다
curl -sS -L -A "Mozilla/5.0 bullet-in/0.1" --max-time 25 \
  -w "\nstatus=%{http_code} final=%{url_effective}\n" "<정규화된 주소>" \
  | grep -Eo "<title>[^<]*</title>|status=[0-9]+ final=\S*"
```

- **제목이 기사 제목이면 통과** · 섹션 · 목록 첫 화면이면 그 규칙을 먼저 고친다.
- **상태 코드로는 못 가른다** — 죽은 주소도 200 을 내고 목록 화면으로 넘긴다.
- 규칙을 고쳐야 하면 **규칙 배포가 먼저**이고 배치는 그다음이다.

## 3. 절차

### 3.1. 회차를 피한다

```bash
ssh <vm> 'systemctl list-timers bullet-in.timer --no-pager | head -2'
```

정기 회차는 KST 3시간 간격 (00 · 03 · … · 21시) 이고 한 회차가 2 ~ 4분이다.
**쓰기와 재렌더에 5분쯤 걸리므로 회차 10분 전이면 미룬다.**

### 3.2. 백업

VM 자신의 `.env` 에서 비밀번호를 읽어 셸 이력에 안 남긴다.

```bash
ssh <vm> 'bash -s' <<'REMOTE'
cd ~/bullet-in && set -a && source .env && set +a
PW=$(python3 -c "import os,re;print(re.search(r'://[^:]+:([^@]+)@',os.environ['MARIADB_URL']).group(1))")
TS=$(date +%Y%m%d_%H%M%S)
docker exec bullet-in-mariadb-1 mariadb-dump -uroot -p"$PW" bulletin \
  articles article_players players > ~/backups/identity_backup_${TS}.sql
ls -l ~/backups/identity_backup_${TS}.sql
REMOTE
```

### 3.3. before 스냅샷 세 벌

**없어진 것은 없어지기 전 목록에서만 셀 수 있다.**
덤프를 파싱하는 것보다 조회가 빠르고 대조가 쉽다.

```sql
SELECT content_hash, player_id FROM article_players ORDER BY 1,2;   -- 01_pairs
SELECT content_hash, url        FROM articles        ORDER BY 1;    -- 02_urls
SELECT id, COALESCE(first_seen,'') FROM players      ORDER BY 1;    -- 03_seeds
```

**주소를 잇는 축으로 쓴다** — 이 작업에서 주소가 안 바뀌는 경우 `url` 이 옛 해시와 새 해시를 잇는 유일한 안전한 키다.

### 3.4. dry-run

```bash
ssh -i ~/.ssh/seoulnow_deploy -o ExitOnForwardFailure=yes -f -N \
  -L 3421:127.0.0.1:3306 ubuntu@<vm>
set -a; source .env; set +a
MARIADB_URL="mysql+pymysql://root:<pw>@127.0.0.1:3421/bulletin" \
  uv run python -m bullet_in.migrate_url_identity --dry-run
```

- **포트는 세션마다 다르게 잡는다** — 남의 터널에 붙으면 그 세션이 닫힐 때 끊긴다.
- **`plan()` 은 DB 를 안 만지는 순수 함수다** — 목록을 전수로 찍어 눈으로 읽을 수 있다.
- **「주소가 바뀌는 행」 과 「해시만 바뀌는 행」 을 갈라 센다** — 앞쪽이 0 이면 표시는 안 건드리고 신원만 옮기는 것이다.

### 3.5. 실행 · 멱등 확인

```bash
… uv run python -m bullet_in.migrate_url_identity --apply
… uv run python -m bullet_in.migrate_url_identity --dry-run   # 대상 0 이어야 한다
```

**실행 직전에 계획을 다시 센다** — 백업과 실행 사이에 회차가 돌면 대상이 늘어난다.
2026-08-29 에 dry-run 과 실행 사이 한 회차에 병합 묶음이 16 → 17 이 됐다.

### 3.6. 전후 대조

**총량이 아니라 자리를 본다.**
총량은 6 이 나가고 6 이 들어와도 같은 값을 낸다.

| 잣대 | 통과 조건 |
| --- | --- |
| `articles` 행 수 | 병합 계획의 삭제분만큼만 줄어든다 |
| 귀속 쌍 총수 | 병합에서 흡수된 중복분만큼만 줄어든다 |
| **묶음별 합집합** | 남긴 해시의 선수 집합 = 전 (남긴 + 지운) 의 합집합 |
| **병합과 무관한 행** | 귀속이 움직인 행 **0** |
| **고아 귀속** | **증가 0** — 총수가 아니라 증가분으로 본다 |
| `first_seen` dangling | 증가 0 |

**「고아 0」 을 잣대로 쓰지 않는다** — 작업 전부터 200건대가 있었고, 그것을 0 으로 적으면 통과할 수 없는 검사가 된다.

### 3.7. 재렌더 · 배포

`write_site` 는 `run.py` 서빙 경로와 1:1 이어야 한다 — 인자를 옮겨 적지 말고 `import` 한다.
`serving_rows` 는 **세 값**을 돌려준다 (남길 행 · 무관 제외 · 옛 글 제외).

배포 뒤 확인은 **보이는 자리에서** 한다.

```bash
ls site/article | wc -l                       # 서빙 행 수와 같아야 한다
ls site/article/ | grep -c "^<지운 해시>"      # 0
ls site/article/ | grep -c "^<새 해시>"        # 1
```

### 3.8. 다음 회차 확인

**여기까지 하지 않으면 끝난 것이 아니다.**
회차가 한 번 돌고도 `--dry-run` 대상이 0 이면 신원이 굳은 것이다.

```bash
sudo journalctl -u bullet-in.service --since "<회차 시각>" --no-pager \
  | grep -E "success_rate|잔여 페이지"
```

- **잔여 페이지 삭제 줄에 파일명이 함께 남는다** (PR #377) — 개수만 있으면 무엇이 사라졌는지 못 묻는다.
- 고아가 새로 생겼다면 **이 절차의 재발이 아닐 수 있다** — 제목이 바뀌어도 해시가 갈린다 (§5).

## 4. 잃어버린 주소를 되찾는 법

주소를 고쳐야 하는데 **온전한 주소가 없을 때** 찾는 순서다.
아래로 갈수록 비용이 크다.

**① Mongo `raw_items`** — 어댑터가 긁은 원래 주소가 그대로 있다.

```python
col.find({"url": {"$regex": "<호스트>"}}, {"url": 1, "source_id": 1, "fetched_at": 1})
```

외부 접촉이 0 이고, **소스가 그 모양으로 준 것인지 우리가 만든 것인지도 함께 갈린다.**
2026-08-29 에 스카이 원본 67건 중 섹션 없는 주소가 0건이라 「전부 우리가 만든 것」 이 확정됐다.

**② 소급 직전 백업** — 합치기 전 상태가 남아 있다.

```bash
python3 -c "…" backup.sql   # INSERT INTO \`articles\` 구간만 잘라 정규식으로 뽑는다
```

**병합이 증거를 지우므로 백업이 유일한 before 목록인 경우가 있다.**

**③ 소스 재수집** — 목록 페이지를 한 번 받아 기사 번호로 찾는다.

```bash
curl -sS "<목록 URL>" | grep -o "/path/[0-9]*/<기사번호>[^\"']*" | sort -u
```

**옛 기사는 목록에서 빠져 있을 수 있다** — ①  ② 를 먼저 본다.

**되찾은 주소는 넣기 전에 열리는지 확인한다** (§2 의 `curl`).

## 5. 이 절차가 안 보는 것

- **제목이 바뀌어 해시가 갈리는 경우는 못 막는다.**
`content_hash` 의 재료에 원문 제목이 들어가므로 소스 텍스트가 달라지면 같은 일이 난다 (2026-08-29 18:02 회차 실물).
`title_original` 을 바꾸는 백필 · 파서 개정도 같은 자리를 건드린다.
- **고아 청소는 기본이 아니다.**
`--purge-orphans` 를 줄 때만 지우고, 그 판단은 「이 회차가 만든 것인가」 와 별개다.
- **규칙이 틀리면 틀린 값을 굳힌다** (§2).
- **병렬 세션이 옆에서 번역 필드를 만지고 있으면 재번역이 그 작업을 덮어쓸 수 있다.**
해시를 가는 작업이 도는 동안 표기 소급 같은 것을 하면 헛일이 된다 — **먼저 서로 알린다.**

## 관련

- `docs/troubleshooting/2026-08-29-the-rule-moved-but-the-stored-addresses-did-not.md` — 왜 이 절차가 생겼나 · §7 정정 · §8 번역 소실 · §8.1 제목 방아쇠
- `docs/runbook/2026-08-08-onetime-db-batch-via-tunnel.md` — 터널 · 백업 · 실행 창의 일반 절차
- `docs/superpowers/specs/2026-08-14-tweet-article-absorption-design.md` §4.1 — 정규화 변경에 재계산이 따라야 한다는 최초 기록
- `src/bullet_in/migrate_url_identity.py` — 이 절차를 코드로 옮긴 자리
