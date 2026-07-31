# 선수 명단 DB 운영 절차 — 등재 · 확정 · 백필 (2026-07-31)

링크 선수 명단이 YAML (`name_map.yaml`) 에서 DB (`players` · `article_players`) 로 옮겨진 뒤의 운영 동선.
후보 인지 (알림 · 대기 목록 조회) 부터 확정 명령, 소급 백필, 생애주기 수동 전이까지를 다룬다.
설계 스펙: `docs/superpowers/specs/2026-07-31-player-roster-db-design.md`.
구현 계획: `docs/superpowers/plans/2026-07-31-player-roster-db-impl.md`.

## 1. 이관 반영 (VM)

PR 1~4 를 머지해도 VM 은 자동으로 최신 커밋을 받지 않는다 (근거: `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` §6.1).
머지된 코드가 실제 회차에 반영되려면 아래 순서를 그대로 밟는다.

```bash
cd ~/bullet-in && git log --oneline -1     # VM 이 어느 커밋인지 먼저 확인
git pull --ff-only
set -a; source .env; set +a
uv run python -m bullet_in.migrate_roster
```

`migrate_roster` 는 멱등이라 몇 번 돌려도 안전하다.
정상 출력은 최초 1회 `이관: 신규 39 / 명단 39 · 사전 39명`, 이후는 `신규 0 / 명단 39 · 사전 39명` 이다 (2026-07-31 PR 1 반영 시 실측).
사전 인원이 39명이 아니면 이관이 아직 안 된 DB 이거나 명단 상수 (`roster_seed.ROSTER`) 가 갱신된 것이니, 백필 · 확정 CLI 를 돌리기 전에 원인부터 확인한다.

## 2. 회차 관측

### 2.1. 후보 알림 (Discord)

회차 중 enrich 가 명단 밖 선수를 발견하면 `article_players` 에 후보 (`status='candidate'`) 로 등재하고, 신규 후보가 있으면 Discord 웹훅으로 알림을 보낸다 (`notify.build_candidate_alert`).
알림 제목은 `🆕 링크 선수 후보 N명 등재`, 본문은 `확정 전에는 게이트 · 서빙 사전에 실리지 않는다 — 확정 CLI 로 승격` 이다.
선수별 필드에 한글 표기 후보 · 원문 풀네임 · 추출 단계 · 근거 기사 제목 (200자 절단) · 기사 링크가 붙고, 10명을 넘으면 나머지는 건수로 접힌다.

### 2.2. article_players 적재 확인

```sql
SELECT COUNT(*) FROM article_players;
SELECT ap.content_hash, p.full_name, ap.stage, ap.extracted_at
FROM article_players ap JOIN players p ON p.id = ap.player_id
ORDER BY ap.extracted_at DESC LIMIT 10;
```

회차 직후 건수가 늘지 않으면 그 회차의 기사가 아직 `article_players` 에 안 걸린 것이다.
enrich 응답 파싱 실패 경고부터 확인한다 — players 필드가 추가돼 출력 토큰이 늘면서, 8192 상한에 인접한 기사에서 파싱 실패가 소폭 늘 수 있다는 관찰이 PR 3 반영 시 남아 있다.

### 2.3. 후보 대기 목록 조회 — 상비 절차

```sql
SELECT id, full_name, ko_candidate, transfer_status, first_seen, added_at
FROM players WHERE status='candidate' ORDER BY added_at DESC;
```

알림은 유실될 수 있다.
Discord 웹훅 발송 실패, 또는 `backfill_article_players` 의 `record_article_players` 가 여러 쌍을 처리하는 도중 일부만 커밋한 채 예외로 끊기는 경우 등이 가능 경로로 알려져 있다 (부분 커밋은 실제 발생 사례가 아니라 코드 리뷰가 지목한 경로다).
이 조회는 알림 채널과 무관하게 DB 를 직접 보므로, 알림이 안 왔더라도 후보를 놓치지 않는 안전망이다.
회차 관측을 할 때마다 습관적으로 함께 돌린다.

VM 에 접속한 상태에서 아래 한 줄을 그대로 붙여넣으면 된다.
위 SQL 에 선수별 등장 기사 수를 붙여, 어느 후보부터 볼지 우선순위가 바로 보이게 한 형태다.

```bash
docker exec -i bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin -e "SELECT p.id, p.ko_candidate AS 표기, p.full_name AS 영문명, p.transfer_status AS 이적축, COUNT(ap.content_hash) AS 기사수 FROM players p LEFT JOIN article_players ap ON ap.player_id = p.id WHERE p.status = 'candidate' GROUP BY p.id ORDER BY 기사수 DESC, p.added_at DESC;"
```

`-p` 뒤 비밀번호는 `docker-compose.yml` 의 `MARIADB_ROOT_PASSWORD` 값이다.
출력의 `id` 는 생애주기 전이 (§6) 에서 대상 선수를 지정할 때 쓰는 번호다.

한 줄로 둔 이유가 있다.
여러 줄 Python 스크립트를 셸에 붙여넣으면 마지막 `EOF` 앞에 공백이 섞이는 순간 종료 표시로 인식되지 않아, 셸이 입력을 계속 기다린 채 멈춘다 (2026-07-31 실제로 겪음).
여러 줄 스크립트를 꼭 써야 하면 `cat > /tmp/q.py` 로 파일을 먼저 만든 뒤 `uv run python /tmp/q.py` 로 실행한다.

## 3. 확정

### 3.1. 백필 선행 의존 — 먼저 확인할 것

확정 CLI 는 `article_players` 조회 (`PlayerStore.articles_for`) 로 그 선수가 등장한 기사를 찾아 소급 재검사한다.
`article_players` 는 PR 3 반영 (2026-07-31 이후 회차) 부터 쌓이기 시작했고, 그 이전에 실린 기사는 §4 백필을 실행하기 전까지 이 테이블에 채워지지 않는다.
그래서 백필 전에 확정한 선수의 `[dry-run] 등장 기사 0` 은 "과거 기사에 안 나왔다" 가 아니라 "과거 기사가 아직 안 걸렸다" 는 뜻일 수 있다.
백필을 먼저 끝내고 나서 확정을 진행해야 소급 재검사가 실제 과거 기사까지 훑는다.

### 3.2. confirm_player 사용법

```bash
set -a; source .env; set +a
uv run python -m bullet_in.confirm_player --name "Nico Williams" --ko "니코 윌리엄스" --dry-run
```

dry-run 은 DB 를 바꾸지 않고 등장 기사 수와 재번역 대상 수만 보여준다.
`--name` 은 `players.full_name` 과 정확히 일치해야 한다 — §2.3 대기 목록에서 확인한 `full_name` 값을 그대로 옮겨 쓴다.

문제 없으면 실제 확정을 돌린다.

```bash
uv run python -m bullet_in.confirm_player --name "Nico Williams" --ko "니코 윌리엄스" \
  --category external --transfer-status in_link
```

`--category` (squad · manager · director · external) 와 `--transfer-status` (none · in_link · in_done · out_link · out_done · link_dropped · other_club · loan_in · loan_out) 는 생략하면 기존 값을 유지한다.
신규 후보는 자동 등재 시점에 이미 category=external · transfer_status=in_link 로 채워져 있으니, 그 값이 맞으면 두 옵션 다 생략해도 된다.
이미 다른 선수가 확정한 `--ko` 값을 다시 쓰면 `ko_name 충돌: '...' 는 이미 다른 선수 (id=…) 의 확정 표기` 를 출력하고 중단한다 — 표기를 바꾸거나 대상 선수를 다시 확인한다.

실행 순서는 승격 (status → confirmed · ko_name 기입) → 등장 기사 게이트 재검사 → 의심 행 재번역 → site 재생성이다.
site 재생성은 로컬 산출물만 갱신한다 — 실제 배포까지 하려면 이어서 `./infra/deploy-site.sh` 를 실행한다.

**`--ko` 에 무엇을 넣을 것인가**

기준은 한국 기사가 실제로 쓰는 짧은 호칭이다.
원칙은 성 단독이다 — 확정된 41명이 전부 그렇다.
예외도 있다 — 브라질 선수처럼 이름으로 불리면 그 형태 (비니시우스) 를 쓰고, 일본 선수처럼 성이 앞에 오면 그 순서를 따른다.

짧게 넣는 이유가 있다.
소비처 세 곳 — 인명 환각 검출 (`detect_title_hallucination`) · 인명 누락 검출 (`detect_title_mistranslation`) · 서빙 사건 묶음 (`load_player_names`) — 이 모두 한글 표기를 부분 문자열로 대조한다.
짧은 표기는 긴 표기가 쓰인 제목까지 함께 잡지만, 긴 표기로 확정하면 짧게 쓴 제목을 놓친다.

너무 짧으면 다른 이름 · 일반 단어 안에 들어간다.
실측 겹침 2건이 있다 — `사카` 가 `아론 완-비사카` 안에, `화이트` 가 `모건 깁스-화이트` 안에 들어간다.
이 둘은 게이트가 원문의 영문 철자도 함께 보기 때문에 오탐으로 이어지지는 않지만, 검출 관점에서 두 선수가 구분되지 않는다는 뜻이다.

영문명이 `Jr` 로 끝나면 한글에도 주니어를 붙인다 (예: Charles Sagoe Jr → `세이고 주니어`).

**확정 전 영문 성 확인**

사전은 `{한글 표기 → 영문 성}` 쌍이고, 영문 쪽은 `players.surname` 컬럼에서 온다.
이 컬럼은 후보 등재 때 영문명의 마지막 토막으로 자동 추출되므로 (`roster.record_article_players`), 접미어가 붙은 이름에서 어긋난다.

실사례 2건이 있다 (2026-07-31).
`Charles Sagoe Jr` 의 성이 `Jr` 로, `Vinicius Junior` 의 성이 `Junior` 로 잡혀 있었다.
후자는 확정된 상태라, `Eli Junior Kroupi` 처럼 Junior 가 들어간 다른 선수의 기사 제목을 "비니시우스가 원문에 있는데 번역에서 빠졌다" 로 잘못 판정해 불필요한 재번역을 유발했다 (실측 1건).

확정 전에 아래로 확인하고, 어긋나면 먼저 고친다.

```bash
docker exec -i bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin -e "SELECT id, full_name, first_name, surname FROM players WHERE id=?;"
```

```sql
UPDATE players SET first_name='Charles', surname='Sagoe' WHERE id=186;
```

### 3.3. 두 단어 성 경고

성이 두 단어인 선수 (예: Van Dijk 류) 를 확정하면 CLI 가 아래 경고를 낸다.

```
surname '...' 이 두 단어 — _has_name_context 가드가 근거를 못 찾아 이 축의 보호 없이 등재된다 (가드의 두 단어 성 지원은 범위 밖)
```

경고가 떠도 확정 자체는 그대로 진행된다.
의미는, 이 선수의 기사가 역방향 인명 누락 게이트 (원문 제목의 매핑 인명이 전부 소실됐는지 보는 축) 의 보호를 못 받는다는 것이다.
가드 자체에 두 단어 성 지원을 넣는 일은 이번 트랙 범위 밖으로 남아 있다 (스펙 §3.3).
오역이 걱정되면 `docs/runbook/2026-07-19-translation-quality-gates-ops.md` §5 코퍼스 스윕으로 수동 대조한다.

### 3.4. 회차 시각 회피

확정 CLI 는 내부적으로 재번역 (`_converge`) 을 돌려 Gemini 를 호출한다.
정기 회차는 3시간 간격 하루 8회 (KST 00 · 03 · 06 · 09 · 12 · 15 · 18 · 21) 다 — systemd 타이머 · `pipeline_runs` 실측 (2026-08-01), 이전 서술의 4회 (09 · 15 · 21 · 03) 는 부정확했다.
회차와 겹치면 15 RPM 속도 한도를 양쪽이 나눠 쓰게 돼 회차 · 확정 둘 다 429 를 더 자주 만난다 — `docs/runbook/2026-07-19-enrich-only-pass.md` 가 잡는 이유와 같다.
확정은 회차 시각을 피해서 실행한다.
429 로 중단돼도 데이터는 안전하다 — 의심 행만 `title_ko IS NULL` 상태로 남고, 확정 CLI 재실행이나 다음 정기 회차가 이어서 수렴시킨다.

### 3.5. 일괄 확정 — 배치 실행 형태

후보를 수십 명 단위로 확정할 때의 실행 형태다 (2026-07-31 ~ 08-01 확정 48명 실측).

- dry-run 을 전 대상에 먼저 돌려 재번역 합계부터 잰다.
  실측에서는 48명 중 재번역 4건 · 나머지 전부 0 이었다 — 확정 자체는 대부분 무비용이다.
- 합계가 크면 실행 전에 사용자 확인을 받는다 (§4.1 과 같은 과금 고지 원칙).
- 확정은 8 ~ 9건 단위 배치 스크립트로 나눠 `ssh 'bash -s' < 스크립트 | tee 로그` 로 실행한다.
  스크립트에는 stdin · PATH 가드가 필수다 — 함정 2건과 템플릿은 `docs/troubleshooting/2026-08-01-vm-batch-exec-stdin-traps.md`.
- 배치 후 검증 3종: `players` status 집계 · 후보 잔존 목록 (§2.3) · `SELECT COUNT(*) FROM articles WHERE title_ko IS NULL`.
- 확정 표기가 늘면 `제목 의심 잔존 — 수동 확인` 경고가 구조적 오탐으로 나올 수 있다.
  판정 절차는 `docs/troubleshooting/2026-08-01-roster-gate-structural-false-positives.md`.

## 4. 백필

`backfill_article_players` 는 기존 기사에 소급으로 `article_players` 를 채우는 1회성 스크립트다.
2026-07-31 VM 실행 실측 대상은 419행이었다 (로컬 dry-run 추정치 205행보다 많았다 — 실행 전 dry-run 으로 실측한다).
`--limit 100` 5회로 분할 실행했고 429 중단은 0회였다.
처리 후 `article_players` 는 1031행, 그중 추출 결과가 0명이라 state 에만 남은 행이 76건이었다.
신규 후보는 90명 등재됐다.

### 4.1. 과금 고지 (실행 전 필수)

전건이 Gemini 호출이다.
운영 키가 물린 AI Studio 프로젝트는 Tier 1 선불이고 실제로 과금되고 있다 — 무료 티어가 아니다.
15 RPM 속도 한도 기준으로 대상 200~500행이면 20~35분 걸린다.
**사용자 확인 없이 인자 없는 전체 실행을 하지 않는다** — 먼저 dry-run 으로 대상 건수를 보여주고, 진행 여부를 물은 뒤에만 본 실행으로 넘어간다.

### 4.2. 무인 실행 안전 — tmux · tee · 분할 실행

`extract_players_rows` 는 대상 행 전체를 한 루프로 순회하며 Gemini 를 호출하고, 반환값을 다 모은 뒤에야 `backfill_article_players` 가 등재 (`record_article_players`) 와 state 기록을 시작한다.
그래서 SSH 접속 끊김 · Ctrl-C 같은 하드 중단이 이 루프 도중 일어나면, 그때까지 호출해 받은 응답이 전량 유실된다.
state 에는 아무것도 안 남아 있으니 재실행하면 이미 호출했던 행을 처음부터 다시 부르게 되고, 그만큼 다시 과금된다.
대응은 두 가지다.

- tmux (또는 nohup) 안에서 실행한다 — 터미널 · SSH 세션이 끊겨도 프로세스는 살아남는다.
  출력은 다른 외부 접촉 명령과 동일하게 `tee` 로 파일에 남긴다.
- 한 번에 전량을 부르는 대신 `--limit 100` 씩 나눠 실행한다.
  중단이 나도 유실 폭이 그 배치 (최대 100행) 로 한정된다.

```bash
tmux new -s roster-backfill
set -a; source .env; set +a
uv run python -m bullet_in.backfill_article_players --limit 100 2>&1 | tee backfill_run1.log
```

### 4.3. 실행

```bash
set -a; source .env; set +a
uv run python -m bullet_in.backfill_article_players --dry-run             # 대상 건수만 확인
uv run python -m bullet_in.backfill_article_players --limit 5             # 소량 실행 (본 실행 전 점검)
```

회차 시각은 §3.4 와 같은 이유로 피한다.
본 실행은 §4.2 방식 (tmux · tee · `--limit 100` 분할) 을 따른다.

### 4.4. state 파일

진행 상태는 기본 경로 `backfill_players_state.txt` (`.gitignore` 등재 · 커밋 대상 아님) 에 처리 완료 `content_hash` 를 한 줄씩 쌓는다.
추출 결과가 0명인 행도 state 에 남아야 재실행 시 다시 과금되지 않는다 — 대상 판별이 `article_players` 존재 여부만으로는, 처리했지만 0명이었던 행과 아직 처리 안 한 행을 구분하지 못하기 때문이다.
파싱 실패 행은 state 에 안 남아 다음 실행에서 자동 재시도된다.

### 4.5. 429 재실행

429 로 중단돼도 이미 처리된 행은 state 에 남아 있어 안전하다.
그대로 재실행하면 `filter_targets` 가 state 에 있는 행을 걸러내고 남은 것만 이어서 처리한다.
같은 `--state` 경로를 유지해야 이어서 처리된다 — 경로를 바꾸면 처음부터 다시 과금된다.

## 5. 값 정정 — 잘못 넣었을 때

운영 중 표기 오류나 잘못된 연결이 나오면 아래 절차로 되돌린다.
원인마다 손대는 지점이 다르니 증상에 맞는 항목을 먼저 찾는다.

**후보 (`status='candidate'`) 의 표기가 이상할 때** — 고칠 필요가 없다.
모델이 채워 넣은 `ko_candidate` 는 사람이 대기 목록을 볼 때 참고하는 값일 뿐이다.
게이트 사전 (`PlayerStore.gate_name_map`) 은 조회 조건에서 후보 상태를 아예 빼므로 이 값이 실제 검출에 쓰이는 일은 없다 (`_DICT_WHERE = "status IN ('confirmed','archived')"`).
실제로 쓰이는 표기는 확정할 때 `--ko` 로 주는 값 (`ko_name`) 이다.
표기가 틀린 후보는 올바른 `--ko` 로 확정하거나, 확정할 생각이 없으면 아래 (같은 사람이 두 행으로 갈렸을 때) 항목의 방식으로 보관 처리한다.
다만 §2.3 대기 목록을 사람이 검토하기 좋게 하려고 `ko_candidate` 를 미리 손봐 두는 것은 가능하다.

```sql
UPDATE players SET ko_candidate='...' WHERE id=?;
```

**이미 확정한 선수의 표기가 잘못됐을 때** — 확정 명령을 올바른 `--ko` 로 다시 실행한다.
같은 선수를 다시 확정해도 충돌 검사에 걸리지 않는다 — `ko_name_holder` 가 찾은 보유자가 자기 자신이면 통과한다 (`confirm_player.main` 의 `holder != player["id"]` 분기).
재실행하면 표기 교체 → 그 선수가 등장한 기사 재검사 → 필요한 기사만 재번역 → site 재생성까지 한 번에 다시 돈다.
`--dry-run` 을 먼저 붙여 재번역이 몇 건 걸릴지 확인한다.

**신분 · 이적 상태가 틀렸을 때** — 고치는 방법이 두 가지인데 뒤따라 도는 작업이 서로 다르다.
확정 명령의 `--category` · `--transfer-status` · `--club` 로 주면 그 값만 갱신되고, 등장 기사 재검사 · site 재렌더가 함께 돈다.
DB 를 직접 `UPDATE` 하면 site 는 자동으로 다시 만들어지지 않으므로, 필요하면 재렌더 절차를 따로 밟는다 (§6 생애주기 절 참조).

**영문 이름 (`full_name`) 이 오타일 때** — 확정 명령은 `full_name` 으로 선수를 찾으므로 (`PlayerStore.get_player`), 먼저 DB 에서 고친 뒤 확정한다.

```sql
UPDATE players SET full_name='...' WHERE id=?;
```

`full_name` 은 `UNIQUE` 제약이라 이미 있는 이름으로는 바꿀 수 없다 — 그 경우는 아래 항목 (같은 사람이 두 행으로 갈린 경우) 으로 처리한다.
기사 연결 (`article_players`) 은 `player_id` 기준이라 이름을 고쳐도 그대로 유지된다.

**같은 사람이 두 행으로 갈렸을 때 (표기 · 철자 변형)** — 남길 행 하나를 정하고, 없앨 행의 기사 연결을 옮긴 뒤 보관 처리한다.
연결 이동은 같은 기사에 두 행이 모두 붙어 있을 수 있으므로 중복을 무시하는 형태로 한다.

```sql
-- 남길 id = KEEP · 없앨 id = DROP
UPDATE IGNORE article_players SET player_id=KEEP WHERE player_id=DROP;
DELETE FROM article_players WHERE player_id=DROP;
UPDATE players SET status='archived', archived_at=UTC_TIMESTAMP() WHERE id=DROP;
```

`article_players` 의 기본 키는 `(content_hash, player_id)` 조합이라, 같은 기사에 두 행이 모두 붙어 있으면 옮기는 과정에서 키가 충돌한다.
`UPDATE IGNORE` 는 그 충돌을 건너뛰고, 남은 중복 연결은 그다음 `DELETE` 가 치운다.

**기사 · 선수 연결이 잘못됐을 때** — 그 연결만 지운다.

```sql
DELETE FROM article_players WHERE content_hash='...' AND player_id=?;
```

주의할 점이 있다 — 그 기사의 연결이 하나도 남지 않으면 백필 대상 조건 (`NOT EXISTS (article_players)`) 에 다시 걸려 그 기사를 다시 추출하고 그만큼 다시 과금된다.
지우기 전에 그 기사에 남은 연결이 있는지 먼저 확인한다.

## 6. 생애주기 수동 전이

자동 만료는 없다 (스펙 §6).
시장 상황이 바뀌면 사람이 아래 `UPDATE` 를 직접 돌린다.
대상 `id` 는 §2.3 대기 목록이나 `SELECT id, full_name, category, transfer_status FROM players WHERE status != 'candidate'` 로 먼저 확인한다.

```sql
-- 영입 성사 (external · in_link → squad · in_done)
UPDATE players SET category='squad', transfer_status='in_done' WHERE id=?;

-- 임대 영입 성사 (external · in_link → squad · loan_in)
UPDATE players SET category='squad', transfer_status='loan_in' WHERE id=?;

-- 임대 복귀 — 스쿼드 잔류
UPDATE players SET transfer_status='none' WHERE id=?;

-- 임대 복귀 — 처분 재검토 (방출 링크로 전환)
UPDATE players SET transfer_status='out_link' WHERE id=?;

-- 방출 성사 (squad · out_link → external · out_done)
UPDATE players SET category='external', transfer_status='out_done' WHERE id=?;

-- 타 클럽행 이적 성사 (보존 · archived)
UPDATE players SET category='external', transfer_status='other_club',
                    status='archived', archived_at=UTC_TIMESTAMP() WHERE id=?;

-- 성사 없는 링크 소멸 (보존 · archived)
UPDATE players SET transfer_status='link_dropped',
                    status='archived', archived_at=UTC_TIMESTAMP() WHERE id=?;

-- 이적 시장 종료 — 남은 영입 링크 선수 일괄 archived
UPDATE players SET status='archived', archived_at=UTC_TIMESTAMP()
  WHERE category='external' AND transfer_status='in_link'
    AND status != 'archived';
```

일괄 archived 대상은 영입 링크 (`category='external' AND transfer_status='in_link'`) 뿐이다.
방출 링크 (`category='squad' AND transfer_status='out_link'`) 는 스쿼드 소속 선수라 archived 대상이 아니다 — 시장이 닫혀도 그 선수는 여전히 아스날 소속이므로 명단에서 빼는 게 아니라 방출 이야기가 없던 일이 됐을 뿐이다.
시장 종료로 방출 링크가 소멸하면 선수마다 아래처럼 `none` 으로 개별 복귀시킨다 (이적 성사 여부가 선수마다 달라 일괄 처리를 하지 않는다).

```sql
-- 방출 링크 소멸 — 스쿼드 복귀 (선수별로 확인 후 개별 실행)
UPDATE players SET transfer_status='none'
  WHERE category='squad' AND transfer_status='out_link' AND id=?;
```

`archived` 는 물리 삭제가 아니라 보존이다.
게이트 검출 사전 (`PlayerStore.gate_name_map`) 의 조회 조건은 `status IN ('confirmed','archived')` 라서, archived 행도 계속 잡힌다 — 과거 기사를 나중에 재번역해도 인명 보호가 유지된다.
전이 후에는 §3.2 방식대로 site 를 다시 만들고 배포한다 (`_render` 를 직접 부르거나, `docs/runbook/2026-07-19-enrich-only-pass.md` §4 스니펫 재사용).

## 7. 게이트 런북 §4.2 갱신

`docs/runbook/2026-07-19-translation-quality-gates-ops.md` §4.2 (name_map 검출 사전 등재 절차) 는 YAML `name_map.yaml` 시절 서술이 그대로 남아 있었다.
이 런북 도입에 맞춰, 등재 방법을 설명하는 1번 항목만 확정 CLI 참조로 갱신했다.
판정 원칙 (시드 표기가 판정 기준 · 영문 값은 단어 경계로 매치) 은 DB 로 옮긴 뒤에도 동일해 나머지 항목은 그대로 뒀다.

## 8. 참고

- 설계 스펙: `docs/superpowers/specs/2026-07-31-player-roster-db-design.md`
- 구현 계획: `docs/superpowers/plans/2026-07-31-player-roster-db-impl.md`
- enrich 전용 재번역 패스 (확정 CLI 가 내부에서 같은 함수 조합을 재사용): `docs/runbook/2026-07-19-enrich-only-pass.md`
- 게이트 4축 · 사전 3종 운영: `docs/runbook/2026-07-19-translation-quality-gates-ops.md`
- VM 반영 절차 일반: `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` §6.1
