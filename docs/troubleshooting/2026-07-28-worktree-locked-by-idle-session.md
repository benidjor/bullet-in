# 워크트리가 유휴 세션에 잠겨 진입이 막힐 때 (2026-07-28)

병렬 2줄 운용에서 기존 워크트리에 진입하려다 잠금에 걸린 사례.
잠근 것이 무엇인지 찾는 데 시간이 걸려 절차로 남긴다.

## 증상

```
Cannot enter worktree: .../.claude/worktrees/serve-filter-fix belongs to another
running Claude Code session (locked: claude session serve-filter-fix (pid 84119
start Sat Jul 25 05:24:32 2026)). Wait for that session to finish or choose a
different worktree.
```

- 이전 세션을 끝냈다고 생각했는데도 잠금이 남아 있다.
- 메시지가 pid 와 시작 시각만 주므로, **어느 창에서 도는 세션인지** 알 수 없다.

## 1. 프로세스가 실제로 살아 있는지 확인

```bash
ps -p 84119 -o pid,lstart,etime,%cpu,command
#   PID STARTED                      ELAPSED  %CPU COMMAND
# 84119 Sat Jul 25 14:24:32 2026  01-02:55:14   0.0 claude
```

CPU 0% 에 경과 시간이 길면 유휴 상태다 (작업 중이 아니라 그냥 열려 있는 것).

## 2. 어느 창인지 부모 프로세스로 추적

터미널 앱마다 프로세스 계보가 다르므로 부모를 따라 올라간다.

```bash
ps -p 84119 -o ppid=          # 84050
ps -p 84050 -o command=       # /bin/zsh -l
ps -p <그 부모> -o command=    # /usr/bin/login -flpq ...
ps -p <또 그 부모> -o command= # /Applications/Orca.app/.../daemon-entry.js
```

여기서는 **Orca 앱 안에서 띄운 세션**이었다.
일반 터미널 탭이 아니라 앱 내부라 눈에 안 띄어 종료를 놓친 것이다.

## 3. 떠 있는 세션 전체를 작업 디렉터리와 함께 보기

가장 실용적인 한 줄이다.
어느 세션이 어느 워크트리를 점유 중인지 한눈에 나온다.

```bash
ps -ef | grep -E "claude$" | grep -v grep | awk '{print $2}' | \
  while read p; do echo "pid=$p tty=$(ps -p $p -o tty=) cwd=$(lsof -a -p $p -d cwd -Fn 2>/dev/null | grep '^n' | cut -c2-)"; done
```

```
pid=84119 tty=ttys019 cwd=.../.claude/worktrees/serve-filter-fix   ← 잠금 원인
pid=86332 tty=ttys001 cwd=.../.claude/worktrees/ornstein-x         ← 종료된 트랙에 잔존
pid=22944 tty=ttys004 cwd=.../bullet-in
```

`tty=??` 인 것은 터미널이 아닌 곳에서 뜬 세션이다 (앱 내부 · 데몬).

## 4. 해제 — 잠근 세션에서 `/exit` 하되 반드시 Keep 을 고른다

해당 창을 찾아 `/exit` 를 입력하면 이런 선택이 나온다.

```
Exiting worktree session
You have 8 commits on worktree-serve-filter-fix. The branch will be deleted if you remove the worktree.
 1. Keep worktree    Stays at .../.claude/worktrees/serve-filter-fix
 2. Remove worktree  All changes and commits will be lost.
```

**Keep 을 고른다.**
Remove 를 고르면 워크트리가 통째로 지워지는데, 그 안에는 커밋되지 않는 파일이 있다
— SDD 원장 (`.superpowers/sdd/<계획>/progress.md`) 이 대표적이다.
원장이 사라지면 완료된 태스크 기록이 없어져 다음 세션이 이미 끝난 작업을 다시 파견할 수 있다.

경고에 적힌 "8 commits" 는 대개 이미 PR 로 머지된 것이라 유실 걱정이 없지만,
**커밋 밖 파일은 그 경고에 포함되지 않는다** — 그것이 Keep 을 골라야 하는 이유다.

해제 후 `ps -p <pid>` 로 사라진 것을 확인하고 진입한다.

## 함정

- **잠금 메시지의 시각을 믿고 "오래됐으니 죽은 프로세스" 라고 단정하지 말 것.**
이번 사례는 28시간 전에 시작됐지만 멀쩡히 살아 있었다.
- **`kill` 은 마지막 수단.**
그 세션의 대화 맥락이 저장 전이면 유실된다.
워크트리 파일과 git 상태에는 영향이 없지만, 진행 중 판단이 사라진다.
- **종료된 트랙의 세션도 워크트리를 점유한 채 남는다.**
작업이 끝나면 세션도 닫는 습관이 필요하다.
`ps` 한 줄로 주기적으로 확인하면 잔존 세션이 쌓이지 않는다.

## 참고

- 워크트리 자체의 커밋 오염 문제는 별건이다
— `docs/troubleshooting/2026-07-27-parallel-session-branch-contamination.md` ·
`docs/troubleshooting/2026-07-15-subagent-cross-checkout-contamination.md`.
