# squash 머지 후 로컬 main 갈라짐 — 앞선 로컬 main 에서 분기한 기능 브랜치

- **날짜**: 2026-07-01
- **영역**: git / GitHub Flow / squash merge
- **심각도**: 낮음 (기능 영향 없음, 로컬 히스토리 정리 이슈)

## 증상

- 서빙 코드만 약 50줄 바꾼 PR 인데 GitHub 이 6커밋 · 469줄 변경으로 표기.
- 초과분은 이 작업의 spec · plan 마크다운 + `.gitignore` 한 줄.
- squash 머지 완료 후 로컬 `main` 이 `origin/main` 과 갈라짐.
  `origin/main` 앞 1커밋 (squash) · 로컬 `main` 앞 7커밋.

## 핵심 메커니즘

- 기능 브랜치를 `origin/main` 이 아니라 **그보다 앞선 로컬 `main` 의 tip 에서 분기**한 것이 원인.
- 로컬 `main` 에 아직 push 안 된 커밋 (이 작업의 spec · plan · `.gitignore` chore) 이 쌓여 있었고, 브랜치가 그 tip 에서 갈라짐.
- PR 의 base 는 `origin/main` 이므로, 그 기반 커밋들이 브랜치와 base 의 차이 (`origin/main..branch`) 에 함께 포함.
- squash 머지는 그 차이 전체를 **한 커밋으로 묶음** → spec · plan · gitignore + 코드가 하나의 squash 커밋에 합쳐짐.
- 결과적으로 그 세 커밋의 내용이 `origin/main` 의 squash 와 로컬 `main` 의 개별 커밋 양쪽에 **중복 존재** → 두 ref 가 갈라짐.

## 진단 (왜 이렇게 판단했는가)

- 브랜치가 base 대비 몇 커밋인지 확인 → 기능 3커밋 외에 spec · plan · gitignore 3커밋이 더 잡힘.

```bash
git fetch origin
git log --oneline origin/main..<feature-branch>   # 기능 3 + 기반 3 = 6커밋
```

- squash 커밋이 실제로 무엇을 묶었는지 확인 → 코드뿐 아니라 spec · plan · gitignore 포함.

```bash
git show --stat <squash-sha>   # docs/... spec · plan + .gitignore + serve/*
```

- 로컬 `main` 과 `origin/main` 의 양방향 격차 확인.

```bash
git rev-list --count origin/main ^main   # origin에만: 1 (squash)
git rev-list --count main ^origin/main   # 로컬에만: 7 (중복 3 + 진짜 새것 4)
```

## 처리 (로컬 main 정리)

- 로컬 `main` 을 머지된 `origin/main` 위로 재정렬하되, squash 에 이미 포함된 중복 커밋은 버리고 나머지만 이식.
- 분기점 (기능 브랜치가 갈라져 나온 커밋) 을 기준으로 `--onto` 를 쓰면 그 이전 커밋은 버려짐.

```bash
# 분기점 이후 커밋만 origin/main 위로 재이식 (중복 커밋 제거)
git rebase --onto origin/main <분기점-sha> main
```

- **실행 위치 주의**: 대상 브랜치가 다른 worktree 에 체크아웃돼 있으면 그 worktree 에서만 rebase 가능.
  `main` 은 대개 메인 체크아웃에 있으므로 거기서 실행.
- **SHA 재작성 주의**: rebase 는 재이식되는 커밋의 SHA 를 다시 씀.
  다른 세션 · worktree 가 그 커밋들 위에서 작업 중이면 안전한 지점에서 조율 후 실행.

## 예방

- spec · plan 을 로컬 `main` 에 직접 커밋하지 말 것.
  대안은 두 가지.
  - 기능 브랜치에 spec · plan 을 함께 커밋 → 태스크 단위로 한 PR 에 묶여 squash (이전 태스크들이 쓴 방식).
  - 굳이 main 계열에 두려면 분기 전에 `origin/main` 으로 push → 브랜치가 최신 origin tip 에서 갈라짐.
- 분기 직전 로컬 `main` 이 origin 보다 앞서 있지 않은지 확인.

```bash
git fetch origin
git log --oneline origin/main..main   # 비어 있어야 깨끗한 분기
```

## 참고

- 커밋 · PR 컨벤션 (GitHub Flow · squash · PR = Task): `docs/conventions/2026-06-11-commit-pr-convention.md`
- 관련 git 워크플로 트러블슈팅: `docs/troubleshooting/2026-06-28-github-contributor-misattribution.md`
