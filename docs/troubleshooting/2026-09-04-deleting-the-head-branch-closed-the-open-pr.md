# head 브랜치를 지우니 열린 PR 이 닫혔다 (2026-09-04)

「머지 완료」 라는 말을 듣고 머지 커밋을 확인하지 않은 채 원격 브랜치를 지웠다.
PR 은 아직 머지 전이었고, GitHub 은 열린 PR 의 head 브랜치가 사라지면 그 PR 을 닫는다.
커밋은 로컬에 남아 있어 브랜치를 되살리고 PR 을 다시 열어 복구했다.

## 1. 증상

1. 01:42 KST 에 PR #456 을 머지했다는 말을 듣고 `git pull` · 워크트리 제거 · 로컬 브랜치 삭제 · `git push origin --delete feat-deploy-alert-detail` 을 한 번에 쳤다.
2. `git log -1` 이 여전히 직전 머지 커밋 `0388c64` 를 가리켰다.
3. `gh pr view 456 --json state,mergeCommit` 이 `CLOSED` 와 빈 머지 커밋을 돌려줬다.

## 2. 원인

머지 버튼이 눌리기 전에 원격 브랜치가 지워졌다.
GitHub 은 열린 PR 의 head 브랜치가 지워지면 PR 을 자동으로 닫고 (머지가 아니라 close 다), 그 뒤 브랜치가 다시 생겨도 저절로 열리지 않는다.

「머지 완료했다」 는 말은 직접 확인한 사실이 아니었다.
앞의 PR 둘 (#454 · #455) 은 `gh pr view` 로 `MERGED` 와 머지 커밋을 본 뒤 지웠는데, 세 번째에서 그 확인을 건너뛰었다.

## 3. 해결

커밋 객체는 로컬 저장소에 남아 있었다 (`git cat-file -t 63b3c7a` 가 `commit`).

```bash
git branch feat-deploy-alert-detail 63b3c7a
git push -u origin feat-deploy-alert-detail
gh pr reopen 456
```

같은 커밋이라 CI 결과도 그대로였고, 다시 머지해 `8e41dfc` 가 됐다.

## 4. 예방

- **원격 브랜치를 지우기 전에 `gh pr view <N> --json state,mergeCommit` 을 본다.**
  `MERGED` 와 머지 커밋 해시가 함께 나와야 지운다.
- 「머지했다」 는 말은 명령 하나로 확인할 수 있다.
  들은 말을 확인한 사실로 취급하지 않는다.
- 지웠는데 PR 이 닫혔다면 커밋은 `git reflog` 나 `git cat-file` 로 찾을 수 있다.
  브랜치를 같은 이름으로 되살려 push 하고 `gh pr reopen` 을 하면 PR 번호와 리뷰 이력이 그대로 살아난다.

## 함께 볼 것

- `docs/conventions/2026-06-11-commit-pr-convention.md`
  — GitHub Flow · squash merge · PR = Task.
- `docs/troubleshooting/2026-09-02-a-worktree-session-cannot-run-git-on-the-vm.md`
  — 같은 작업에서 나온 다른 git 함정.
