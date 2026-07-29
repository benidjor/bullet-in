# 저장소 정리 런북 — 브랜치 · 워크트리 (2026-07-30)

세션이 쌓이면 로컬 브랜치와 워크트리가 남는다.
2026-07-30 정리 시점에 로컬 브랜치가 44개 · 워크트리가 4개였다.

정리 자체는 간단하지만 **판정을 잘못하면 지우면 안 될 것을 지운다.**
실제로 이번 정리에서 SDD 진행 원장 하나를 잃었다 (`docs/troubleshooting/2026-07-30-worktree-removal-lost-ignored-ledger.md`).
그래서 절차보다 판정 기준을 먼저 둔다.

## 1. 브랜치 — `git branch --merged` 를 쓰면 안 된다

이 저장소는 squash merge 를 쓴다.
squash 는 브랜치 커밋을 main 의 조상으로 만들지 않으므로, 내용이 전부 들어갔어도 `--merged` 에는 나오지 않는다.

```bash
git branch --no-merged origin/main | wc -l
# 42  ← 전부 미머지처럼 보이지만 대부분 이미 머지된 것
```

**PR 상태로 판정한다.**

```bash
gh pr list --state all --limit 200 --json number,headRefName,state > /tmp/prs.json
python3 - <<'PY'
import json, subprocess
prs = {p['headRefName']: (p['number'], p['state']) for p in json.load(open('/tmp/prs.json'))}
branches = [b.strip() for b in subprocess.check_output(
    ['git', 'branch', '--format=%(refname:short)'], text=True).splitlines() if b.strip() != 'main']
for state in ('MERGED', 'OPEN'):
    hit = [b for b in branches if prs.get(b, ('', ''))[1] == state]
    print(f'{state:7} {len(hit)}개', [ (b, prs[b][0]) for b in hit ][:5] if state == 'OPEN' else '')
print('PR 없음', [b for b in branches if b not in prs])
PY
```

`PR 없음` 으로 나온 것은 손대지 않는다 — 아직 PR 을 만들지 않은 작업이거나 워크트리 보조 브랜치다.

삭제.

```bash
git branch -D <머지 완료 브랜치들>
```

`-D` 를 쓰는 이유도 같다.
`-d` 는 `--merged` 와 같은 판정을 하므로 squash 머지분을 거부한다.

## 2. 워크트리 — 지우기 전에 `--ignored` 로 본다

```bash
git -C <워크트리> status --porcelain --ignored
```

`--ignored` 없이 보면 **gitignore 대상이 숨는다.**
이 저장소에서는 그 안에 사람이 만든 기록이 들어 있다.

| 경로 | 성격 |
| --- | --- |
| `.superpowers/sdd/progress.md` | SDD 진행 원장 — **잃으면 복구 불가** |
| `.superpowers/next-track/` · `brainstorm/` | 세션 산출물 |
| `.env` · `.venv/` · `__pycache__/` | 재생성되므로 무관 |

원장이 있으면 먼저 옮긴다.

```bash
cp <워크트리>/.superpowers/sdd/progress.md .superpowers/sdd/progress-<트랙명>.md
```

그다음 제거한다.

```bash
git worktree unlock <워크트리>   # 잠겨 있으면
git worktree remove <워크트리>
git worktree prune
```

**`git worktree remove` 는 휴지통을 거치지 않는다.** 되돌릴 수 없다.

### 2.1. 잠금이 남아 있을 때

잠금 사유에 pid 와 시작 시각이 적혀 있다.

```bash
cat .git/worktrees/<이름>/locked
# claude session ornstein-x (pid 86332 start Sat Jul 25 18:14:16 2026)
ps -p 86332 -o pid,lstart,command
```

프로세스가 살아 있으면 그 세션에서 `/exit` 하고 **Keep 을 고른다** — 절차는 `docs/troubleshooting/2026-07-28-worktree-locked-by-idle-session.md` 에 있다.
죽어 있으면 `git worktree unlock` 후 제거한다.

## 3. 원격 브랜치

로컬과 별개로 쌓인다.
2026-07-30 시점에 118개였고 그중 115개가 머지가 끝난 것이었다.

원격 삭제는 저장소 밖으로 나가는 작업이라 **확인을 받고 한다.**
근본 해결책은 GitHub 저장소 설정의 **Automatically delete head branches** 를 켜는 것이다.
켜 두면 머지할 때마다 자동으로 정리돼 이 절이 필요 없어진다.

## 4. 정리 후

- **메모리의 경로 참조를 갱신한다.**
워크트리 안의 파일을 가리키던 메모리는 존재하지 않는 경로를 가리키게 된다.
이번에도 "SDD 원장은 워크트리 `serve-filter-fix` 안에 있다" 는 기록이 남아 있었다.
- **트랙 현황판에 정리 시점을 적는다** — `docs/superpowers/2026-07-30-track-board.md` 5절.

## 5. 언제 하나

- 트랙 하나가 끝나 PR 이 여럿 머지된 뒤.
- 병렬 세션을 정리하고 하나로 수렴할 때.
- 워크트리 진입이 잠금으로 막힐 때 (그때는 잠긴 것만 처리해도 된다).

정기 일정으로 둘 필요는 없다.
브랜치가 쌓여도 동작에 영향이 없고 잘못 지우는 쪽이 손해가 크다.

## 6. 참고

- 이번 정리에서 잃은 것 — `docs/troubleshooting/2026-07-30-worktree-removal-lost-ignored-ledger.md`.
- 잠긴 워크트리 진입 — `docs/troubleshooting/2026-07-28-worktree-locked-by-idle-session.md`.
- 병렬 세션 브랜치 오염 — `docs/troubleshooting/2026-07-27-parallel-session-branch-contamination.md`.
- 트랙 현황판 — `docs/superpowers/2026-07-30-track-board.md`.
