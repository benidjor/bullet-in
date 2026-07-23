# config 값 변경 후 tier 재계산이 무관한 과거 드리프트까지 건드리는 함정 (2026-07-23)

`config/credibility.yaml` 값을 고친 뒤 저장된 tier 를 재계산할 때, 대상 행을 새 레지스트리로 그냥 다시 resolve 하면 이번 변경과 무관한 행까지 바뀐다.
트랙 B PR-A (B1) 에서 Gary Jacob · Ben Jacobs 두 기자만 고치려다 실제로는 12 행이 바뀌어 발견했다.

## 증상

- B1 은 credibility.yaml 에서 Gary Jacob tier 3 → 2 · Ben Jacobs 신규 등재 두 건만 의도했다.
- 그런데 x_afcstuff · fmkorea 행을 새 레지스트리로 전량 재 resolve 하니 **12 행이 바뀜** — 그중 의도한 건 Ben 한 건뿐.
- 나머지는 `@gunnerblog` 2.0 → 1.5 · `@MiguelDelaney` 4.0 → 3.0 · fmkorea 1.0 → 1.5 등 **이번 변경과 무관한 값들**.

## 원인

- 저장된 `tier` 는 그 행을 **수집한 시점의 레지스트리** 로 계산된 값이다.
- 레지스트리 (credibility.yaml) 는 그동안 여러 번 바뀌었으므로, 오래된 행의 저장 tier 는 현재 레지스트리 기준값과 이미 어긋나 있다 (stale).
- 새 레지스트리로 전체를 다시 계산하면 **이번 값 변경의 결과 + 과거 누적 드리프트의 교정** 이 한꺼번에 섞여 나온다.
- 즉 "저장값과 다르면 update" 라는 조건은 이번 변경분을 격리하지 못한다 — 저장값 자체가 낡았기 때문이다.

## 해결

- **old 레지스트리 (git HEAD) 와 new 레지스트리 (작업 트리) 로 각 행을 두 번 resolve** 해서, `old_tier != new_tier` 인 행만 update 한다.
- 이렇게 하면 이번 config 변경이 실제로 바꾼 행만 남는다 (Ben 4.0 → 3.0 한 건) — gunnerblog · MiguelDelaney 처럼 old 와 new 가 같은 행은 손대지 않는다.
- 절차 요약:

```python
reg_old = load_registry(git_show_head_credibility)   # 변경 전
reg_new = load_registry("config/credibility.yaml")   # 변경 후
for row in 대상_행:                                   # x_mentions · fmkorea 만 (레지스트리 델타 영향 범위)
    t_old = resolve_tier(item, sources, reg_old, journalist=row.journalist)
    t_new = resolve_tier(item, sources, reg_new, journalist=row.journalist)
    if t_old != t_new:                                # 이번 변경의 델타만
        update(row, tier=t_new)
```

- 재계산 전 스냅샷은 필수다 (되돌릴 수 없음) — 이 저장소 mariadb 컨테이너에는 `mysqldump` · `mariadb-dump` 가 없어, articles 테이블을 Python 으로 읽어 pickle 로 떠 두고 실패 시 그 값으로 복원했다.

## 예방

- config (레지스트리 · 사전 등) 값 변경에 따른 tier 재계산 백필은 **항상 old vs new 델타로 스코프** 한다.
- 새 레지스트리로 전건을 다시 resolve 해서 "저장값과 다른 행" 을 고치지 않는다 — 그건 이번 변경이 아니라 과거 드리프트까지 건드린다.
- 과거 드리프트 자체를 정리하고 싶다면 그것은 별도 트랙으로 분리한다 (이번 변경의 리뷰 · 롤백 단위와 섞지 않는다).

## 참고

- 로컬 검증 절차 (스냅샷 · 재계산 · 렌더 대조 · 롤백): `docs/runbook/2026-07-23-config-tier-backfill-local-verify.md`.
- tier 해석 규칙: `src/bullet_in/credibility.py` `resolve_tier`.
- 관련 계획: `docs/superpowers/plans/2026-07-22-classification-relevance-track.md` (B1).
