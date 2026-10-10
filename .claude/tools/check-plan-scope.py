#!/usr/bin/env python3
"""범위 검사 — 브랜치에서 바뀐 파일을 계획서의 `**Files:**` 목록과 대조한다.

훅이 아니라 손으로 돌리는 도구다 — SDD 마무리 (최종 리뷰 전) 와 PR 생성 전에 부른다.

## 왜 있나

2026-10-07 감사에서 CLAUDE.md 행동 가이드라인 원칙 3 (수술적 변경) 이 「부분」 판정을 벗어나지 못했다.
#528 의 최종 수정에 설계 밖 변경이 둘 들어갔고, 리뷰는 그것을 사람 눈으로만 봤다.
바뀐 파일 목록과 계획서 목록을 기계로 대 보는 자리가 없었다.

## 쓰는 법

    python3 .claude/tools/check-plan-scope.py --plan docs/superpowers/plans/<계획서>.md
    python3 .claude/tools/check-plan-scope.py --plan <계획서> --base origin/main   # 기본값

바뀐 파일 = `git merge-base <base> HEAD` 와 작업 트리의 차이 (커밋 · 미커밋 모두) + 추적 안 된 새 파일.
목록 = 계획서의 `**Files:**` 블록 불릿마다 첫 백틱 경로 (`:40-52` · `::test_x` 꼬리는 뗀다 ·
`/` 로 끝나면 그 아래 전부 · `*` 가 있으면 glob) + 계획서 자신.

종료 코드: 0 = 범위 밖 없음 · 1 = 범위 밖 있음 · 2 = 계획서가 없거나 Files 목록이 비었거나 git 이 실패했다 (기준을 못 찾음 등).

## 이 검사가 안 보는 것

- 목록 안 파일에서 고친 내용이 계획 범위인지 (같은 파일 안의 설계 밖 변경은 리뷰의 몫)
- 백틱 없이 적은 경로 (2026-10-11 까지 계획서 65편의 Files 불릿 922줄 가운데 28줄 · 대부분 「변경 없음」 · 백틱은 있으나 경로가 아닌 줄 3줄 별도)
- 목록에 있는데 안 바뀐 파일은 실패로 치지 않고 출력만 한다 (빠뜨린 작업일 수도, 확인만 하는 파일일 수도 있다)

**통과했다고 범위를 지킨 것은 아니다** — 파일 단위로만 본다.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys

TICK = re.compile(r"`([^`]+)`")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
TAIL = re.compile(r"(::.*|:\d+(-\d+)?)$")


def looks_like_path(tok: str) -> bool:
    return "/" in tok or bool(re.search(r"\.[A-Za-z0-9]+$", tok))


def files_block_lines(lines: list[str], start: int) -> list[str]:
    """`**Files:**` 다음 줄부터 이어지는 불릿 줄 — 첫 불릿 앞 빈 줄은 건너뛰고, 그 뒤 빈 줄이나 불릿 아닌 줄에서 끝난다.

    절 검사기 (.claude/hooks/check-plan-sections.py) 의 같은 이름 함수와 같은 규칙이다.
    블록이 빈 줄 뒤로 이어진다고 읽으면 바로 뒤 `- [ ] **Step 1**` 불릿의 백틱이 허용 목록에 들어간다.
    """
    out = []
    for ln in lines[start:]:
        s = ln.strip()
        if not s:
            if out:
                break
            continue
        if not s.startswith(("- ", "* ")):
            break
        out.append(s)
    return out


def listed_paths(plan: str) -> list[str]:
    lines = open(plan, encoding="utf-8").read().splitlines()
    out, fence = [], None
    for i, ln in enumerate(lines):
        m = FENCE.match(ln)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not ln.strip()[len(mark):]:
                fence = None
            continue
        if fence is None and ln.strip() in ("**Files:**", "**Files**"):
            for b in files_block_lines(lines, i + 1):
                tok = next((t for t in TICK.findall(b) if looks_like_path(t)), None)
                if tok:
                    out.append(TAIL.sub("", tok.strip()))
    return out


def git(top: str, *args: str) -> list[str]:
    """저장소 루트에 고정해 부른다 — `ls-files --others` 는 현재 디렉터리 기준 상대 경로 · 그 아래 파일만 낸다."""
    r = subprocess.run(["git", "-C", top, *args], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"git {' '.join(args)} 실패: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return [ln for ln in r.stdout.splitlines() if ln]


def changed_files(top: str, base: str) -> list[str]:
    """`--no-renames` — rename 이면 `--name-only` 가 새 이름만 내서, 범위 밖 파일을 옮겨 지운 것이 안 보인다."""
    mb = git(top, "merge-base", base, "HEAD")[0]
    return sorted(set(git(top, "diff", "--no-renames", "--name-only", mb))
                  | set(git(top, "ls-files", "--others", "--exclude-standard")))


def covered(path: str, entry: str) -> bool:
    if "*" in entry:
        return fnmatch.fnmatch(path, entry)
    if entry.endswith("/"):
        return path.startswith(entry)
    return path == entry


def main() -> int:
    ap = argparse.ArgumentParser(description="바뀐 파일을 계획서 Files 목록과 대조")
    ap.add_argument("--plan", required=True, help="계획서 경로")
    ap.add_argument("--base", default="origin/main", help="비교 기준 (기본 origin/main)")
    a = ap.parse_args()

    if not os.path.isfile(a.plan):
        print(f"{a.plan}: 파일이 없다", file=sys.stderr)
        return 2
    entries = listed_paths(a.plan)
    if not entries:
        print(f"{a.plan}: `**Files:**` 블록에 백틱 경로가 하나도 없다 — 대조할 목록이 없다", file=sys.stderr)
        return 2
    top = git(".", "rev-parse", "--show-toplevel")[0]
    entries.append(os.path.relpath(os.path.abspath(a.plan), top).replace(os.sep, "/"))

    changed = changed_files(top, a.base)
    outside = [p for p in changed if not any(covered(p, e) for e in entries)]
    untouched = [e for e in dict.fromkeys(entries) if not any(covered(p, e) for p in changed)]

    print(f"기준 {a.base} · 바뀐 파일 {len(changed)} · 목록 {len(set(entries))}")
    print(f"\n범위 밖 {len(outside)}")
    for p in outside:
        print(f"  {p}")
    print(f"\n목록에 있는데 안 바뀜 {len(untouched)} (참고 · 실패 아님)")
    for e in untouched:
        print(f"  {e}")
    print("\n이 검사가 안 보는 것은 파일 머리 주석에 있다.")
    return 1 if outside else 0


if __name__ == "__main__":
    sys.exit(main())
