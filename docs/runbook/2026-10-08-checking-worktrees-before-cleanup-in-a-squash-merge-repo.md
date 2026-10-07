# squash 머지 저장소에서 워크트리를 지우기 전에 남은 작업을 가려내는 절차 (2026-10-08)

머지가 끝난 워크트리 · 브랜치를 정리할 때, 지워도 되는 것과 아직 원격에 사본이 없는 작업을 가르는 절차다.
관련 안건은 j (저장소정리) 다.

## 1. 왜 따로 절차가 필요한가

이 저장소는 PR 을 squash 로 머지한다.
squash 는 main 에 새 커밋을 하나 만들기 때문에, 브랜치에 있던 원래 커밋은 main 의 조상이 되지 않는다.
그래서 「main 에 들어갔나」 를 조상 관계로 묻는 명령은 머지가 끝난 브랜치도 「안 들어갔다」 고 답한다.

| 명령 · 화면 | squash 저장소에서의 답 |
| --- | --- |
| `git branch --merged` | 머지된 브랜치도 목록에서 빠진다 |
| `git rev-list HEAD --not --remotes=origin` | 머지된 커밋도 「미푸시」 로 센다 |
| `ExitWorktree` remove · `git branch -d` 의 미머지 경고 | 거짓 경보다 |

이 답을 믿으면 영원히 못 지우고 반대로 경고를 무시하는 습관이 들면 진짜 미푸시 작업을 지운다.

## 2. 절차

### 2.1 워크트리마다 세 값을 센다

```bash
# 메인 체크아웃에서 실행 · 워크트리마다 미커밋 파일 수 · 원격에 없는 커밋 수 · 같은 이름 원격 브랜치 유무
git fetch -q --prune origin
git worktree list --porcelain | awk '/^worktree /{p=$2} /^branch /{b=$2} /^$/{if(p ~ /worktrees/) print p" "b; b=""}' |
while read -r p b; do
  br=${b#refs/heads/}
  dirty=$(git -C "$p" status --porcelain | wc -l | tr -d ' ')
  unp=$(git -C "$p" rev-list HEAD --not --remotes=origin | wc -l | tr -d ' ')
  rem=$(git show-ref -q --verify "refs/remotes/origin/$br" && echo yes || echo no)
  echo "$(basename "$p") $br dirty=$dirty unpushed=$unp remote=$rem"
done
```

미커밋이 있으면 그 워크트리는 「쓰는 중」 이다.
미푸시가 0 이고 미커밋도 0 이면 지워도 된다.

### 2.2 미푸시 커밋이 있으면 제목으로 후보 PR 을 찾는다

```bash
# 커밋 제목으로 main 의 squash 커밋을 찾는다 (본문에 원래 커밋 제목이 남는 경우도 걸린다)
git -C <워크트리> log --format='%h %s' HEAD --not --remotes=origin
git log origin/main --format='%h %s' --fixed-strings --grep="<커밋 제목>" | head -1
```

제목 일치는 후보일 뿐이다.
여러 커밋이 PR 하나로 묶이기도 하고 다른 제목의 PR 에 들어가기도 한다.
2026-10-08 에는 기자 13명의 로마자 이름을 등재한 커밋이 「표기 통일 회차가 밟은 함정과 화면 규칙 검증 절차」 (#309) 에 들어 있었다.

### 2.3 파일 내용으로 확정한다

```bash
# 미푸시 커밋이 건드린 파일만 골라, 워크트리 HEAD 와 squash 커밋 사이의 차이를 본다
files=$(git -C <워크트리> rev-list HEAD --not --remotes=origin | xargs -I{} git -C <워크트리> show --format= --name-only {} | sort -u)
git -C <워크트리> diff --stat HEAD <squash 커밋> -- $files
```

출력이 비면 내용이 main 에 들어간 것이다.
차이가 나오면 「확인 필요」 로 둔다.

### 2.4 셋으로 나눈다

| 분류 | 조건 | 할 일 |
| --- | --- | --- |
| 지워도 됨 | 미커밋 0 · 미푸시 0, 또는 2.3 에서 차이 없음 | 4절대로 지운다 |
| 쓰는 중 | 미커밋 파일이 있거나 원격에 사본이 없는 커밋이 main 과 다르다 | 남긴다 · 백업이 필요하면 3절을 먼저 본다 |
| 확인 필요 | 2.3 에서 차이가 나왔다 | 사람이 diff 를 읽고 정한다 |

## 3. 원격에 올려 백업하기 전에

이 저장소는 공개다.
백업용으로 브랜치만 push 해도 PR 없이 누구나 볼 수 있다.
push 전에 추가된 줄을 한 번 훑는다.

```bash
# 공개되면 안 되는 낱말 · 비밀값이 새 줄에 있는지 본다
git -C <워크트리> diff origin/main...HEAD | grep '^+' | grep -n -i -E '<금지 낱말>|api[_-]?key|secret|password|token='
```

2026-10-08 에는 계획서 한 줄이 공개하지 않기로 한 낱말을 담고 있어 push 를 PR 때로 미뤘다.

## 4. 지울 때

| 워크트리를 만든 방법 | 지우는 명령 |
| --- | --- |
| `claude --worktree` · `EnterWorktree` | 세션 종료 화면 또는 `ExitWorktree` remove (로컬 브랜치까지 지운다) |
| `git worktree add` | `git worktree remove <경로>` → `git branch -D <브랜치>` → `git push origin --delete <브랜치>` |

머지 뒤 원격 브랜치 자동 삭제는 꺼져 있다 (`delete_branch_on_merge: false` · 2026-10-08 조회).
원격 브랜치는 따로 지워야 남지 않는다.

지운 뒤에는 세 곳을 확인한다.

```bash
git worktree list
git branch --list '<브랜치>'
git ls-remote --heads origin '<브랜치>'
```

## 5. 2026-10-08 실측

| 항목 | 값 |
| --- | --- |
| 워크트리 (메인 체크아웃 제외) | 31개 |
| 미푸시 커밋이 있던 워크트리 | 7개 · 커밋 12개 |
| 그 12개와 파일 내용이 일치한 squash PR | #308 · #309 · #310 · #316 · #317 · #318 · #332 |
| 쓰는 중 (원격 사본 없음) | 2개 |
| 지워도 되는 것 | 29개 (정리는 사용자 결정 대기) |

## 6. 관련

- 트러블슈팅 `docs/troubleshooting/2026-10-08-reported-absence-where-my-tool-had-dropped-the-input.md` — 같은 세션에서 도구 결과를 그대로 「없다」 로 옮긴 네 자리
- 런북 `docs/runbook/2026-08-22-auditing-a-stale-backlog-index.md` — 남은 일 목록을 실물과 대조하는 절차 (살아 있는 세션의 워크트리는 잔여물이 아니라는 주의 포함)
