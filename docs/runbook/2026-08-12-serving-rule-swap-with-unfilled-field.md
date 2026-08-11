# 값이 아직 없는 새 필드로 서빙 판정을 바꾸는 절차 (2026-08-12)

서빙이 쓰는 판정 기준을 새 필드로 옮기는데, 그 값을 채우는 작업이 다른 회차에 있어 **배포 시점에는 필드가 비어 있는** 경우의 절차다.
선수 페이지의 기사 선별을 `article_players.stage` 에서 `role` 로 옮긴 작업 (PR #251) 에서 실행한 것을 일반화했다.

값을 만드는 쪽과 값을 쓰는 쪽이 다른 트랙일 때 쓴다.
같은 회차에서 값까지 채운다면 이 절차가 필요 없다 — 그냥 바뀐 화면을 검증하면 된다.

## 1. 전환 규칙을 먼저 설계한다

새 필드가 비어 있는 동안 옛 규칙이 그대로 돌게 만든다.

```python
새_판정 if 값이_있음 else 옛_판정
```

- **기본값을 정하는 문제가 아니다.** "미기입을 A 로 읽자" 가 아니라 "미기입 행이 옛 규칙과 같은 결과를 내는가" 를 묻는다.
- 어휘 밖 값도 미기입과 같이 취급한다 — 값을 만드는 쪽이 오타나 모르는 낱말을 낼 수 있다.
- 걷어내는 시점을 함께 등재한다 (값이 다 채워진 뒤).
남겨 두면 두 규칙이 영구히 공존한다.

이 설계를 빼먹으면 배포 즉시 화면이 바뀐다 — 실제로 588건이 노출될 뻔했다 (`docs/troubleshooting/2026-08-12-new-field-empty-window-changes-the-screen.md`).

## 2. 빈 값 상태에서 집합을 대조한다 — 이 절차의 핵심

운영 사본을 뜨되 **새 컬럼만 만들고 값은 채우지 않는다.**
그 상태에서 새 코드의 출력과 옛 규칙의 계산 결과가 **완전히 같은지** 본다.

```bash
# 사본에 컬럼만 추가 (값은 비운 채로)
docker exec bullet-in-mariadb-1 mariadb -uroot -p<pw> <사본> \
  -e "ALTER TABLE <표> ADD COLUMN IF NOT EXISTS <필드> VARCHAR(16);"
```

```python
# 새 코드로 만든 집합
entries = R.build_player_entries(rows, R.load_page_players(engine))
new = {(e["id"], a["content_hash"]) for e in entries for a in e["articles"]}

# 옛 규칙을 손으로 계산한 집합
old = {(p["id"], l["content_hash"]) for p in players for l in p["links"]
       if l["stage"] != "other" and l["content_hash"] in by_hash}

print(len(new), len(old), new ^ old)      # 차집합이 비어야 한다
```

- **판정 기준은 차집합 0건이다.** 건수만 같고 구성이 다를 수 있으므로 집합으로 본다.
- 실측: 806쌍 대 806쌍 · 차집합 0.
- 여기서 차이가 나오면 전환 규칙이 잘못된 것이고, **배포하면 안 된다.**

## 3. 모의값을 채워 새 규칙의 화면을 미리 본다

빈 값 검사는 "안 바뀐다" 만 증명한다.
값이 채워졌을 때 무엇이 어떻게 바뀔지는 별도로 봐야 한다.

- 사본에 값을 **근사로** 채운다 (실측에서는 제목의 한글 이름 대조를 썼다).
- 옛 규칙 · 새 규칙의 건수를 대조하고 **사라지는 대상 · 새로 생기는 대상 목록**을 뽑는다.
- 로컬 렌더 후 사람이 본다 (`docs/runbook/2026-08-11-premerge-screen-check-with-prod-copy.md` §2.3).

**근사의 오차를 반드시 함께 적는다.**
이번 근사 (제목 이름 대조) 는 제목에 이름이 있어도 언급인 행 6건, 이름이 없어도 본인 기사인 행이 표본 48건 중 1건 있었다.
따라서 이 화면으로 판정하는 것은 **표시 규칙이 맞는가**이고, **어느 항목이 걸러질까**가 아니다.
이 구분을 안 하면 근사값이 만든 목록을 정답으로 착각하고 다음 회차의 기준선으로 쓰게 된다.

## 4. 배포 후 판정은 무변화 확인이다

- **정상 = 화면이 지금과 같음.** 달라지면 전환 규칙이 잘못된 것이다.
- 확인 항목 셋
→ 정기 회차 성공 (`pipeline_runs` 최신 행의 `error_count` · `success_rate`)
→ 컬럼 생성 · **전 행 미기입** (신규 적재분 포함 — 값을 만드는 쪽이 아직 없으므로)
→ 화면 건수 대조 — **줄어든 것이 있으면 회귀**다.

배포 전에 기준선을 떠 둔다.

```bash
ssh <vm> 'cd ~/bullet-in && for f in site/player/*.html; do \
  printf "%s\t%s\n" "$(basename $f)" "$(grep -oE "기사 [0-9]+건" $f | head -1)"; done' > before.tsv
```

- 회차가 신규 항목을 수집하므로 **증가는 정상**이다.
판정에서 보는 것은 **감소와 소실**이다.
- 실측: 선수 페이지 54개 유지 · 소실 0 · 감소 0 · 증가 6페이지 (신규 7건 반영).

## 5. 컬럼 생성 전 단독 재렌더 금지

조회 쿼리가 새 컬럼을 SELECT 하므로, `ensure_schema()` 가 한 번도 돌지 않은 DB 에 재렌더 스니펫만 단독 실행하면 `Unknown column` 으로 실패한다.

- 정기 회차는 `ensure_schema()` → `write_site()` 순서라 안전하다.
- **첫 정기 회차 전에는 재렌더를 단독 실행하지 않는다.**
- 급하면 `ensure_schema()` 를 먼저 부른다 (`vm-manual-ops-gotchas` 메모리의 "새 컬럼이면 ensure_schema 먼저" 와 같은 함정).

## 6. 곁들여 — 귀속 표본을 유형별로 분류할 때

이 작업의 착수 근거는 "어떤 귀속이 화면에 잘못 올라와 있는가" 의 실측이었다.
그 분류에서 얻은 것이다.

- **제목만 보고 판정하면 틀린다.** 제목과 요약문 (`summary_ko`) 을 함께 뽑아 하나씩 보면 결과가 달라진다.
실측: 오분류 집계가 **5건에서 27건으로** 바뀌었고, 제목에 이름이 있는데도 배경으로만 나오는 행이 6건 있었다.
- **문자열 매칭은 규모를 가늠하는 근사로만 쓴다.** 판정의 근거로 쓰지 않고, 근사로 쓸 때는 표본을 본문까지 확인해 **오차율을 함께 기록**한다.
- 한 줄에 제목과 요약문을 붙여 뽑으면 한 번에 훑기 좋다.

```sql
SELECT CONCAT(p.name,' ',LEFT(ap.content_hash,8),
              '\n  T: ',COALESCE(a.title_ko,a.title_original),
              '\n  S: ',COALESCE(a.summary_ko,LEFT(a.body_excerpt,180)))
  FROM ...
```

## 7. 참조

- 이번 회차의 결함과 경위: `docs/troubleshooting/2026-08-12-new-field-empty-window-changes-the-screen.md`
- 화면 검증 절차 원본: `docs/runbook/2026-08-11-premerge-screen-check-with-prod-copy.md`
- 설계 정본: `docs/superpowers/specs/2026-08-12-player-role-field-design.md`
- 재생성 스니펫 정본: `docs/runbook/2026-07-19-enrich-only-pass.md` §4
