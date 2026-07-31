# 선수 명단 DB 운영 절차 — 등재 · 확정 · 백필 (2026-08-01)

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
Discord 웹훅 발송 실패, 또는 `backfill_article_players` 의 `record_article_players` 가 여러 쌍을 처리하는 도중 일부만 커밋한 채 예외로 끊기는 경우 (드문 케이스지만 코드 리뷰에서 지목됨) 등이 실사례로 남아 있다.
이 조회는 알림 채널과 무관하게 DB 를 직접 보므로, 알림이 안 왔더라도 후보를 놓치지 않는 안전망이다.
회차 관측을 할 때마다 습관적으로 함께 돌린다.

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

`--category` (squad · manager · external) 와 `--transfer-status` (none · in_link · in_done · out_link · out_done · link_dropped · other_club · loan_in · loan_out) 는 생략하면 기존 값을 유지한다.
신규 후보는 자동 등재 시점에 이미 category=external · transfer_status=in_link 로 채워져 있으니, 그 값이 맞으면 두 옵션 다 생략해도 된다.
이미 다른 선수가 확정한 `--ko` 값을 다시 쓰면 `ko_name 충돌: '...' 는 이미 다른 선수 (id=…) 의 확정 표기` 를 출력하고 중단한다 — 표기를 바꾸거나 대상 선수를 다시 확인한다.

실행 순서는 승격 (status → confirmed · ko_name 기입) → 등장 기사 게이트 재검사 → 의심 행 재번역 → site 재생성이다.
site 재생성은 로컬 산출물만 갱신한다 — 실제 배포까지 하려면 이어서 `./infra/deploy-site.sh` 를 실행한다.

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
정기 회차 (KST 09 · 15 · 21 · 03) 와 겹치면 15 RPM 속도 한도를 양쪽이 나눠 쓰게 돼 회차 · 확정 둘 다 429 를 더 자주 만난다 — `docs/runbook/2026-07-19-enrich-only-pass.md` 가 잡는 이유와 같다.
확정은 회차 시각을 피해서 실행한다.
429 로 중단돼도 데이터는 안전하다 — 의심 행만 `title_ko IS NULL` 상태로 남고, 확정 CLI 재실행이나 다음 정기 회차가 이어서 수렴시킨다.

## 4. 백필

`backfill_article_players` 는 기존 기사에 소급으로 `article_players` 를 채우는 1회성 스크립트다.
2026-07-31 로컬 dry-run 기준 대상 205행이다 (로컬 DB 는 낡아 있어 VM 대상은 더 많을 것으로 예상된다 — 실행 전 dry-run 으로 실측한다).

### 4.1. 과금 고지 (실행 전 필수)

전건이 Gemini 호출이다.
운영 키가 물린 AI Studio 프로젝트는 Tier 1 선불이고 실제로 과금되고 있다 — 무료 티어가 아니다.
15 RPM 속도 한도 기준으로 대상 200~500행이면 20~35분 걸린다.
**사용자 확인 없이 인자 없는 전체 실행을 하지 않는다** — 먼저 dry-run 으로 대상 건수를 보여주고, 진행 여부를 물은 뒤에만 본 실행으로 넘어간다.

### 4.2. 실행

```bash
set -a; source .env; set +a
uv run python -m bullet_in.backfill_article_players --limit 5 --dry-run   # 대상 건수만 확인
uv run python -m bullet_in.backfill_article_players                      # 본 실행 (사용자 확인 후)
```

회차 시각은 §3.4 와 같은 이유로 피한다.

### 4.3. state 파일

진행 상태는 기본 경로 `backfill_players_state.txt` (`.gitignore` 등재 · 커밋 대상 아님) 에 처리 완료 `content_hash` 를 한 줄씩 쌓는다.
추출 결과가 0명인 행도 state 에 남아야 재실행 시 다시 과금되지 않는다 — 대상 판별이 `article_players` 존재 여부만으로는, 처리했지만 0명이었던 행과 아직 처리 안 한 행을 구분하지 못하기 때문이다.
파싱 실패 행은 state 에 안 남아 다음 실행에서 자동 재시도된다.

### 4.4. 429 재실행

429 로 중단돼도 이미 처리된 행은 state 에 남아 있어 안전하다.
그대로 재실행하면 `filter_targets` 가 state 에 있는 행을 걸러내고 남은 것만 이어서 처리한다.
같은 `--state` 경로를 유지해야 이어서 처리된다 — 경로를 바꾸면 처음부터 다시 과금된다.

## 5. 생애주기 수동 전이

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

-- 이적 시장 종료 — 남은 링크 선수 일괄 archived (스쿼드 제외)
UPDATE players SET status='archived', archived_at=UTC_TIMESTAMP()
  WHERE category='external' AND transfer_status IN ('in_link','out_link')
    AND status != 'archived';
```

`archived` 는 물리 삭제가 아니라 보존이다.
게이트 검출 사전 (`PlayerStore.gate_name_map`) 의 조회 조건은 `status IN ('confirmed','archived')` 라서, archived 행도 계속 잡힌다 — 과거 기사를 나중에 재번역해도 인명 보호가 유지된다.
전이 후에는 §3.2 방식대로 site 를 다시 만들고 배포한다 (`_render` 를 직접 부르거나, `docs/runbook/2026-07-19-enrich-only-pass.md` §4 스니펫 재사용).

## 6. 게이트 런북 §4.2 갱신

`docs/runbook/2026-07-19-translation-quality-gates-ops.md` §4.2 (name_map 검출 사전 등재 절차) 는 YAML `name_map.yaml` 시절 서술이 그대로 남아 있었다.
이 런북 도입에 맞춰, 등재 방법을 설명하는 1번 항목만 확정 CLI 참조로 갱신했다.
판정 원칙 (시드 표기가 판정 기준 · 영문 값은 단어 경계로 매치) 은 DB 로 옮긴 뒤에도 동일해 나머지 항목은 그대로 뒀다.

## 7. 참고

- 설계 스펙: `docs/superpowers/specs/2026-07-31-player-roster-db-design.md`
- 구현 계획: `docs/superpowers/plans/2026-07-31-player-roster-db-impl.md`
- enrich 전용 재번역 패스 (확정 CLI 가 내부에서 같은 함수 조합을 재사용): `docs/runbook/2026-07-19-enrich-only-pass.md`
- 게이트 4축 · 사전 3종 운영: `docs/runbook/2026-07-19-translation-quality-gates-ops.md`
- VM 반영 절차 일반: `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` §6.1
