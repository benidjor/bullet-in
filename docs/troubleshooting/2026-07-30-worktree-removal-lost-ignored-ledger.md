# 워크트리를 지우다 gitignore 된 SDD 원장을 함께 잃음 (2026-07-30)

세션이 쌓여 워크트리 세 개를 정리하다가 그중 하나의 SDD 진행 원장을 지웠다.
제거 전에 "커밋하지 않은 작업이 있는가" 를 확인했는데, **그 검사로는 원장을 볼 수 없었다.**

## 증상

정리 직후에는 아무 경고도 없었다.
나중에 원장을 찾을 때가 되어서야 없어진 것을 안다.

```
$ ls .claude/worktrees/
(디렉터리 자체가 없음)
```

`git worktree remove` 는 휴지통을 거치지 않고 지운다.
되돌릴 방법이 없다.

## 원인

제거 전 검사로 이것을 썼다.

```bash
git -C .claude/worktrees/serve-filter-fix status --porcelain
# 출력 없음 → "미커밋 0개" 로 판단
```

**`--porcelain` 은 gitignore 대상을 출력하지 않는다.**
이 저장소는 `.gitignore:15` 에서 `.superpowers/` 를 무시하는데, SDD 진행 원장이 바로 그 아래 있다.

```
.superpowers/sdd/progress.md
```

즉 원장이 통째로 검사 범위 밖이었다.
"미커밋 0개" 는 **추적 대상 파일에 한해서만** 참이었다.

## 잃은 것과 남은 것

지운 것은 선수 페이지 트랙 (PR #144) 의 원장이다.

| 남음 | 잃음 |
| --- | --- |
| `feat/serve-player-pages` 커밋 7개 — Task 6~10 구현 전부 | 태스크별 리뷰 트리아지 기록 |
| 계획서의 Task 1~10 명세 (main 에 있음) | 어떤 리뷰 지적을 왜 넘겼는지 |
| 세션 메모리의 "Task 6~10 완료" 기록 | 태스크 경계 커밋 SHA 대응표 |

구현과 완료 상태는 남았고 **판정의 근거만 사라졌다.**
같은 트랙을 다시 열면 "이 지적은 이미 검토했다" 를 증명할 수 없다.

## 해결

복구는 하지 못했다.
남은 것으로 재구성할 수는 있다.

- 커밋 메시지가 태스크와 1:1로 대응해 어느 태스크가 어디까지 갔는지는 복원된다.
- 계획서에 각 태스크의 완료 조건이 있어 검증 기준은 남아 있다.
- 리뷰 트리아지만 복원할 수 없다.

## 예방

### 1. 제거 전 검사에 `--ignored` 를 붙인다

```bash
git -C <워크트리> status --porcelain --ignored
```

무시 대상은 `!!` 로 나온다.
`.superpowers/` · `.env` · `.venv/` 같은 것이 걸리는데, 이 중 **`.superpowers/` 만 사람이 만든 기록**이고 나머지는 재생성된다.

### 2. 원장을 먼저 본체로 옮긴다

```bash
cp -r <워크트리>/.superpowers/sdd/progress.md \
      .superpowers/sdd/progress-<트랙명>.md
```

본체의 원장은 여러 계획을 이어 붙인 한 파일이라 워크트리에 있던 것을 그대로 덧붙여도 형식이 맞는다.

### 3. 세션 종료 시 Keep 을 고르는 것과는 다른 상황이다

`/exit` 에서 Remove 를 고르지 말라는 경고는 이미 있다
(`docs/troubleshooting/2026-07-28-worktree-locked-by-idle-session.md` 4절).
그 문서는 **살아 있는 세션에 진입하려다 잠금에 걸린 경우**를 다룬다.

이번은 반대로 종료된 세션의 워크트리를 **의도적으로 정리하는** 경우인데, 그때도 같은 파일이 사라진다.
정리 절차는 `docs/runbook/2026-07-30-repo-hygiene-cleanup.md` 에 있다.

## 함정

- **`git status` 계열은 기본적으로 무시 대상을 숨긴다.**
"깨끗하다" 는 판정이 "지워도 된다" 를 뜻하지 않는다.
- **`git worktree remove` 는 휴지통을 거치지 않는다.**
macOS 에서도 `~/.Trash` 에 남지 않는다.
- **메모리가 워크트리 안의 경로를 가리키면 특히 위험하다.**
이번에도 세션 메모리에 "SDD 원장은 워크트리 `serve-filter-fix` 안에 있다" 고 적혀 있었는데, 그 경로를 지우면서 메모리는 그대로 남아 존재하지 않는 파일을 가리키게 됐다.
정리 후 메모리의 경로 참조를 함께 갱신한다.

## 참고

- 정리 절차 — `docs/runbook/2026-07-30-repo-hygiene-cleanup.md`.
- 잠긴 워크트리 진입 — `docs/troubleshooting/2026-07-28-worktree-locked-by-idle-session.md`.
- 워크트리 커밋 오염 — `docs/troubleshooting/2026-07-27-parallel-session-branch-contamination.md`.
