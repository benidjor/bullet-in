# 달력 날짜에 고정한 테스트가 그날이 오자 만료됐다 (2026-09-08)

- **영역**: 테스트 / 레이크하우스 유지보수 (고아 파일 청소)
- **관련 PR**: #476 (수정) · #475 (문서만 바꿨는데 이 테스트로 CI 가 떨어진 PR)
- **관련 안건**: 없음

## 증상

문서 세 파일만 바꾼 PR #475 의 CI 에서 `tests/test_warehouse.py::test_고아_청소가_참조_없는_옛_파일만_지운다` 하나가 떨어졌다.

```
assert result == {"listed": 4, "live": 1, "young": 0, "deleted": 3}
AssertionError: assert {'deleted': 0, ..., 'young': 3} == {'deleted': 3, ..., 'young': 0}
1 failed, 1771 passed, 1 skipped
```

같은 테스트가 2026-09-05 의 `main` CI 에서는 통과했고 그 사이에 코드는 한 줄도 안 바뀌었다.
바뀐 것은 날짜뿐이다.

## 원인

고아 청소 (`sweep_orphans`) 는 파일의 실제 mtime 과 기준 시각 `now` 의 차이가 `ORPHAN_MIN_AGE` (3일) 보다 작으면 「아직 어린 파일」 로 두고 지우지 않는다.
테스트는 고아 파일을 **테스트를 돌리는 실제 시각**에 만들면서 기준 시각은 **`2026-09-10` 으로 고정**했다.

| 테스트를 돌린 날 | 파일 mtime 과 기준 시각의 차이 | 판정 |
| --- | --- | --- |
| 09-05 (통과) | 약 5일 | 옛 파일 → 삭제 3 |
| 09-08 (실패) | 약 2일 | 어린 파일 → 삭제 0 |
| 09-13 이후 | 음수 | 영영 어린 파일 |

테스트를 쓴 날 (09-03) 에는 기준 시각이 일주일 뒤라 「문턱을 넉넉히 넘긴 시점」 으로 보였다.
그 넉넉함은 달력이 지나면서 매일 하루씩 줄었고 09-07 부터는 항상 실패한다.

## 수정

기준 시각을 달력이 아니라 실제 시각에서 잰다.
그러면서 문턱의 양쪽을 한 번씩 확인하도록 단언을 둘로 늘렸다.

```python
fresh = datetime.now(timezone.utc)
# 방금 만든 파일은 어리다 — 지우면 안 된다
assert warehouse.sweep_orphans(t, fresh) == {"listed": 4, "live": 1, "young": 3, "deleted": 0}
# 문턱을 넘긴 시점 — 참조 없는 셋만 지운다
result = warehouse.sweep_orphans(t, fresh + warehouse.ORPHAN_MIN_AGE + timedelta(days=1))
assert result == {"listed": 4, "live": 1, "young": 0, "deleted": 3}
```

같은 파일의 다른 `_t(2026, 9, 2)` 들은 손대지 않았다.
그것들은 함수의 순수 입력이라 실제 시계와 비교되지 않는다.

## 왜 그동안 안 걸렸나

- 테스트가 실제 시계와 고정 날짜를 **한 자리에서만** 섞어서 다른 테스트들의 고정 날짜 습관이 그대로 옮겨 왔다.
- 실패가 코드 변경이 아니라 **달력**에서 오므로 마지막으로 코드를 만진 PR 의 CI 는 전부 초록이었다.
문서만 바꾼 PR 이 처음으로 그날을 지나 CI 를 돌렸다.

## 교훈

- 테스트 안에서 **실제 시계로 만든 것** (파일 mtime · `datetime.now()`) 과 **고정한 날짜**를 비교하면 그 테스트는 유효 기간이 있다.
둘 중 하나로 통일한다 — 파일의 mtime 을 `os.utime` 으로 고정하거나 기준 시각을 실제 시계에서 만든다.
- 고정 날짜가 「미래」 라서 안전해 보이는 것은 오늘 시점의 판단이다.
`grep -n "_t(20" tests/` 로 고정 날짜를 쓰는 테스트를 찾아 그 값이 실제 시계와 비교되는지 한 번 본다.
- 문서만 바꾼 PR 의 CI 가 실패하면 곧바로 「달력 · 외부 상태」 를 의심한다.

## 관련

- 픽스처가 이름을 검증하지 못한 회차 = `docs/troubleshooting/2026-09-05-what-only-showed-up-when-the-plan-was-run.md`
- 날짜만 준 `git log --since` 의 함정 (같은 뿌리 · 달력을 잘못 읽는다) = 세션 메모리 `git-since-with-a-bare-date-starts-at-now`
- 고아 파일 청소가 생긴 경위 = `docs/troubleshooting/2026-09-03-the-catalog-that-keeps-only-one-snapshot.md`
