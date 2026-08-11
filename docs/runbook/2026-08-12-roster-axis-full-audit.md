# 명단 이적 축 전수 감사 (2026-08-12)

링크 축으로 남아 있는 선수 중 이미 딜이 끝난 것을 주기적으로 훑는 절차다.
낡음 관측 알림 (`docs/superpowers/specs/2026-08-10-roster-axis-staleness-alert-design.md`) 이 못 잡는 자리를 메운다.

## 1. 왜 알림만으로는 부족한가

알림은 **이번 회차에 만진 기사**를 방아쇠로 삼고 7일 누적을 함께 본다.
그래서 두 가지를 놓친다.

- **창 밖** — 종결 기사가 7일보다 오래되면 영원히 방아쇠가 없다.
2026-08-11 실측에서 코네 (07-23 보도) · 고든이 이 경우였다.
- **임계 미달** — 발화 조건이 신규 ≥ 1 **및** 7일 누적 ≥ 2 라 종결 귀속이 1건뿐이면 조용하다.
2026-08-12 실측에서 콘사가 이 경우였다 (08-11 「아스날, 콘사 영입 실패 후 쥘 쿤데 주시」 1건).

전수 감사는 창도 임계도 없이 현재 상태만 본다.
알림과 감사는 어느 쪽도 다른 쪽을 대신하지 못한다 — 알림은 빠르고 감사는 빠짐없다.

## 2. 쿼리

운영 DB 에 읽기 전용으로 실행한다 (터널 사용 시 포트만 바꾼다).

```sql
SELECT p.id, p.ko_name, p.transfer_status,
       SUM(ap.stage='done')      AS done_n,
       SUM(ap.stage='collapsed') AS collapsed_n,
       MAX(a.published_at)       AS last_pub
FROM players p
JOIN article_players ap ON ap.player_id = p.id
JOIN articles a         ON a.content_hash = ap.content_hash
WHERE p.status = 'confirmed'
  AND p.transfer_status IN ('in_link', 'out_link')
  AND ap.stage IN ('done', 'collapsed')
GROUP BY p.id, p.ko_name, p.transfer_status
ORDER BY COUNT(*) DESC;
```

`ORDER BY` 에 별칭을 쓰면 MariaDB 가 그룹 함수 참조로 거부하므로 `COUNT(*)` 를 그대로 쓴다.

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

나온 행은 "링크 축인데 종결 보도가 붙어 있다" 는 뜻일 뿐 곧바로 오류는 아니다.
행마다 근거 기사를 열어 셋 중 무엇인지 가른다.

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

값 정정은 사용자 승인 후에만 하고 백업을 먼저 뜬다 (`docs/runbook/2026-07-31-player-roster-ops.md` §6).

## 5. 주기

- **이적 창 중에는 주 1회** — 값이 빠르게 낡는다.
- **창 종료 직후 1회** — 창 종료 정리 (같은 런북 §6.2) 와 함께 돌린다.
- **비수기에는 월 1회** — 링크 축 자체가 거의 움직이지 않는다.

## 6. 알려진 잡음

- 결과가 0행이어도 정상이다 — 2026-08-11 정리 직후가 그랬다.
- 사용자 판정으로 "유지" 가 된 선수는 다음 감사에도 다시 나온다.
판정 이력을 담는 칸이 없기 때문이다.
행 수가 한 자릿수라 눈으로 넘기면 되고, 상태를 저장하는 장치는 두지 않는다.
2026-08-12 기준 이 유형은 알바레스 (31) · 코네 (139) 둘이다.

## 7. role 조건은 아직 넣지 않는다

`article_players.role` 은 PR #251 로 컬럼만 생겼고 2026-08-12 기준 2,190행 전부 NULL 이다.
지금 `role != 'mention'` 을 넣으면 전건이 걸러진다.

추출 개정 트랙의 소급 재추출로 값이 채워진 뒤에 조건을 얹는다.
그때는 단순 언급 기사가 빠져 결과가 더 정확해진다.

## 8. 실행 기록

| 날짜 | 결과 | 처리 |
| --- | --- | --- |
| 2026-08-12 | 3명 — 콘사 (29) · 알바레스 (31) · 코네 (139) | 콘사는 신규 발견으로 보고 · 나머지 둘은 기존 유지 판정 |
