# 명단 이적 축 전수 감사 (2026-08-12)

링크 축으로 남아 있는 선수 중 이미 딜이 끝난 것을 주기적으로 훑는 절차다.
낡음 관측 알림 (`docs/superpowers/specs/2026-08-10-roster-axis-staleness-alert-design.md`) 이 못 잡는 자리를 메운다.

## 1. 왜 알림만으로는 부족한가

알림은 **이번 회차에 만진 기사**를 방아쇠로 삼고 7일 누적을 함께 본다.
그래서 회차가 지나간 뒤에 남는 어긋남은 알림의 시야 밖이다.

- **창 밖** — 종결 기사가 7일보다 오래되면 방아쇠가 다시 오지 않는다.
2026-08-11 실측에서 코네 (07-23 보도) · 고든이 이 경우였고, 둘 다 사람이 쿼리로 훑어서 찾았다.
- **놓친 회차** — 알림 발송이 실패했거나 사람이 Discord 를 못 본 회차의 건은 그대로 묻힌다.
알림은 한 번 울리고 끝이지만 감사는 상태가 남아 있는 한 계속 잡는다.

전수 감사는 창도 임계도 없이 현재 상태만 본다.

**다만 감사가 알림의 상위 집합은 아니다.**
2026-08-12 실측에서 감사가 잡은 루이스-스켈리는 같은 회차 (08-11 18:03) 에 알림도 발화한 건이었다
— 판정을 재현해 확인했다 (`이번회차={'collapsed': 3}` · `7일누적=3`).
임계 미달로 알림만 놓치는 경우는 이론상 가능하나 아직 실측 사례가 없다.

둘의 관계는 이렇게 보는 것이 정확하다.
알림은 새로 생긴 어긋남을 즉시 알리고, 감사는 **어떤 이유로든 처리되지 않고 남은 것**을 회수한다.

## 2. 쿼리

운영 DB 에 읽기 전용으로 실행한다 (터널 사용 시 포트만 바꾼다).

```sql
SELECT p.id, p.ko_name, p.transfer_status,
       SUM(ap.stage IN ('done','collapsed')) AS end_n,
       MAX(CASE WHEN ap.stage IN ('done','collapsed')
                THEN a.published_at END) AS last_end,
       MAX(CASE WHEN ap.stage IN ('rumour','interest','negotiating',
                                  'personal_terms','agreed','medical')
                THEN a.published_at END) AS last_live
FROM players p
JOIN article_players ap ON ap.player_id = p.id
JOIN articles a         ON a.content_hash = ap.content_hash
WHERE p.status = 'confirmed'
  AND p.transfer_status IN ('in_link', 'out_link')
GROUP BY p.id, p.ko_name, p.transfer_status
HAVING end_n > 0
ORDER BY end_n DESC;
```

핵심은 마지막 두 열이다.
`last_live` 가 `last_end` 보다 나중이면 종결 보도 뒤에도 사가가 이어지고 있다는 뜻이라 명단을 그대로 두면 된다.
이 비교가 없으면 종결 귀속이 하나만 붙어도 전부 후보로 올라와 사람이 매번 기사를 열어 봐야 한다.

종결 단계를 `WHERE` 가 아니라 `HAVING` 으로 거르는 이유도 여기 있다.
`WHERE` 에서 종결만 남기면 같은 선수의 진행 단계 기사가 집계에서 사라져 `last_live` 를 잴 수 없다.

`ORDER BY` 에서 별칭끼리 연산하면 (`ORDER BY done_n + collapsed_n`) MariaDB 가 그룹 함수 참조로 거부한다.
별칭 하나만 쓰는 형태는 그대로 동작한다.

## 3. 실행

```bash
uv run python - <<'PY'
from sqlalchemy import create_engine, text
e = create_engine("mysql+pymysql://root:bulletin@127.0.0.1:3310/bulletin")   # 터널 포트
with e.connect() as c:
    for r in c.execute(text(open("/tmp/roster_audit.sql").read())):
        print(r)
PY
```

쿼리만 돌리므로 DB 쓰기 · Gemini 호출 · 웹훅이 없다.
정기 회차 중에 돌려도 무방하다.

## 4. 판독

### 4.1 먼저 사가가 끝났는지 본다

`last_live` 가 `last_end` 보다 나중인 행은 **명단을 그대로 둔다.**
종결 보도 뒤에 다시 관심 · 협상 기사가 붙었다면 딜이 살아 있다는 뜻이다.

2026-08-12 첫 실행에서 이 규칙이 세 건을 걸러냈고 셋 다 사용자가 이미 유지로 판정한 선수였다.

- **콘사** — 08-11 13:19 「아스날, 콘사 영입 실패 후 쥘 쿤데 주시」 가 `collapsed` 로 붙었으나 3시간 뒤 「쿤데 영입설 재점화」 가 `interest` 로 이어졌다.
원문은 `after being priced out of a deal` 로 이적료에서 밀렸다는 보도이지 무산 확정이 아니다.
- **알바레스** — 08-03 철수 시사 뒤 08-10 까지 관심 보도가 이어졌다.
- **코네** — 07-23 합의 보도 뒤 08-03 까지 보도가 이어졌고, 실제 이적도 성사되지 않았다.

### 4.2 남은 행을 셋으로 가른다

여기까지 남은 행은 종결 뒤 진행 보도가 없다는 뜻이다.
근거 기사를 열어 셋 중 무엇인지 가른다.

- **명단이 낡음** — 딜이 실제로 끝났는데 축을 안 내렸다.
축을 갱신한다 (`in_done` · `out_done` · `other_club` + `archived` · `link_dropped`).
- **추출 오분류** — 기사가 그 선수의 종결을 말하지 않는데 종결로 붙었다.
명단은 그대로 두고 추출 개정 트랙에 소표본 후보로 넘긴다.
- **보도가 사실과 다름** — 합의 보도가 났지만 이적이 성사되지 않은 경우다.
2026-08-11 코네가 이 사례였다 (「맨유, 아스날 제치고 코네 영입 합의」 보도 후 실제 이적 없음).
명단을 그대로 두고 이 문서에 기록만 남긴다.

근거 기사는 이렇게 뽑는다.

```sql
SELECT a.content_hash, a.published_at, ap.stage, a.transfer_stage, a.source_id, a.title_ko
FROM article_players ap JOIN articles a ON a.content_hash = ap.content_hash
WHERE ap.player_id = :pid AND ap.stage IN ('done', 'collapsed');
```

값 정정은 사용자 승인 후에만 하고 백업을 먼저 뜬다 (`docs/runbook/2026-07-31-player-roster-ops.md` §5.0).
값을 바꾸기 전에 운영 사본으로 렌더해 화면 변화를 확인하면 더 안전하다 (`docs/runbook/2026-07-22-mockup-rerender-from-vm.md` §2.1).

## 5. 주기

- **이적 창 중에는 주 1회** — 값이 빠르게 낡는다.
- **창 종료 직후 1회** — 창 종료 정리 (같은 런북 §6.2) 와 함께 돌린다.
- **비수기에는 월 1회** — 링크 축 자체가 거의 움직이지 않는다.

## 6. 알려진 잡음

- 결과가 0행이어도 정상이다 — 2026-08-11 정리 직후가 그랬다.
- 사가 판별 (§4.1) 을 통과해 §4.2 까지 올라온 선수 중 사용자가 "유지" 로 판정한 것은 다음 감사에도 다시 나온다.
판정 이력을 담는 칸이 없기 때문이다.
행 수가 한 자릿수라 눈으로 넘기면 되고, 상태를 저장하는 장치는 두지 않는다.
- **한 기사 안에서 선수마다 단계가 갈리는 것은 정상이다.**
기사 `eeb04231` 에는 다섯 명이 귀속돼 있고 쿤데는 `interest` · 콘사는 `collapsed` · 아르테타 · 살리바 · 팀버는 `other` 다.
감사는 그중 링크 축 선수의 종결 단계만 본다.

## 7. role 조건은 지금 넣을 수 없다

`article_players.role` 은 PR #251 로 컬럼만 생겼고 2026-08-12 기준 2,190행 전부 NULL 이다.
지금 `role != 'mention'` 을 넣으면 전건이 걸러진다.

값이 채워진 뒤에 얹을지는 그때 판단한다.
지금 판단을 미루는 이유는 §4.1 의 사가 판별과 역할이 겹칠 수 있어서다.

- 콘사 사례는 역할 판정상 `mention` 이 되기 쉬운 구조인데 (주어가 쿤데) 이미 사가 판별이 걸러 냈다.
- 반대로 루이스-스켈리 사례는 기사 주어가 본인이라 `subject` 일 것이고 사가 판별에서도 남는다.

두 장치가 같은 것을 거른다면 하나로 충분하고, 다른 것을 거른다면 둘 다 필요하다.
값이 들어온 뒤 실측으로 가른다.

그때까지는 조건이 아니라 **판독을 돕는 표시 열**로만 뽑아 본다.

```sql
SELECT ap.role, COUNT(*) FROM article_players ap
WHERE ap.player_id = :pid AND ap.stage IN ('done', 'collapsed')
GROUP BY ap.role;
```

## 8. 실행 기록

| 날짜 | 결과 | 처리 |
| --- | --- | --- |
| 2026-08-12 | 4명 중 사가 판별 통과 1명 — 루이스-스켈리 (125) | `out_link` → `link_dropped` 반영 완료 · 같은 건을 알림도 잡았음 |

루이스-스켈리 처리 기록 (2026-08-12 · 사용자 승인).

- 백업 = `~/backups/players_backup_20260812_034026.sql` (77K).
- `category='squad'` · `status='confirmed'` 는 유지했다 — 아스날 소속 선수라 `archived` 하면 색인에서 사라진다.
비니시우스 (118) 를 `archived` 한 것은 그쪽이 영입 대상 (`external`) 이었기 때문이며 같은 처리를 하면 안 된다.
- 운영 사본 렌더로 미리 확인한 화면 변화는 「방출 링크」 그룹에서 「이적 무산」 그룹으로 이동하는 것 하나였고 선수 페이지는 유지됐다.
- 반영 후 감사 재실행 = 사가 판별 통과 0명 (남은 3명은 전부 사가 지속).

- **걸러진 3명** — 콘사 (29) · 알바레스 (31) · 코네 (139) 는 종결 보도 뒤 진행 보도가 이어져 §4.1 에서 제외됐다.
셋 다 사용자가 이전에 유지로 판정한 선수라 판별 규칙이 사람 판단과 일치했다.
- **남은 1명** — 루이스-스켈리는 명단이 `out_link` 인데 08-11 에 「방출 계획 없다」 · 「잔류 의지 확고」 · 「잔류 의지 피력」 이 `collapsed` 로 세 건 붙었다.
방출 딜 자체가 끝났다는 뜻이라 `collapsed` 판정이 적절하고, 명단 축을 내릴 후보다.
- **판별 규칙을 넣기 전에는 콘사가 신규 후보로 올라왔다.**
사가 판별을 추가하자 오탐 3건이 자동으로 빠지고 참 후보 1건이 드러났다.
