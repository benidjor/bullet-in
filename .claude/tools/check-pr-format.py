#!/usr/bin/env python3
"""PR · 커밋의 제목 · 본문 형식 검사 (컨벤션 §1.1 · §2.2).

훅이 아니라 손으로 돌리는 도구다 — PR 본문은 파일에 쓰고 게시하므로 PostToolUse 가 못 본다.

## 왜 있나

같은 위반이 다섯 번 재발했고 (#39 · #125 · #128 · #242 · 2026-08-23), 매번 눈으로만 훑었다.
템플릿 주석은 「산문 문단 금지 · 명사형 불릿」 을 §1.1 · §1.2 아래에만 달아 두는데
컨벤션 §2.2 는 같은 규칙을 모든 섹션 본문에 건다 — 주석만 대조하면 두 절만 맞는다.

## 쓰는 법

    python3 .claude/tools/check-pr-format.py --body pr_body.md --title "fix(x): 제목"
    python3 .claude/tools/check-pr-format.py --open-prs      # 열린 PR 제목 (아직 고칠 수 있다)
    python3 .claude/tools/check-pr-format.py --unpushed      # 푸시 전 커밋 제목 (가장 이른 자리)
    python3 .claude/tools/check-pr-format.py --merged 12     # 머지된 제목 (참고 · 못 고친다)

## 이 검사가 안 보는 것

- 내용의 정확성 · 근거 · 수치
- 헤더 번호 체계 · 섹션 누락 · 체크리스트 고정 문구
- 백틱 · 엔대시 · 기호 간격 (docs 는 .claude/hooks/check-doc-format.py 가 본다)
- 문체의 자연스러움 (humanize 스킬의 몫이고, 그쪽은 반대로 이 형식을 안 본다)

**통과했다고 다 된 것이 아니다** — 검사 범위를 넓히지 않으면 통과 자체가 안심의 근거가 된다.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

# 서술형 종결 — 명사형 불릿 · 명사형 도입 문장 규칙 (§2.2)
NARRATIVE = re.compile(r"(다|한다|했다|된다|이다|않다|없다|있다)[.。]?$")
# 라벨 없는 평불릿 — 예외는 라벨 자리에 코드 서식이 온 경우 (`- `경로` — 설명`)
BARE_BULLET = re.compile(r"^\s*- (?!\*\*)(?!`)")
# 범위 물결표 — GitHub 이 취소선으로 읽는다
TILDE_RANGE = re.compile(r"\d\s*~\s*\d")
# 단어 + 임 종결 — 동사의 명사형과 기계로 못 가르므로 소프트 경고
IM_ENDING = re.compile(r"[가-힣]임[.]?$")
# 제목의 서술형 종결 (§1.1) — type(scope): 와 (#NN) 을 벗기고 본다
TITLE_TAIL = re.compile(r"[가-힣]다$")
TITLE_STRIP = (re.compile(r"\s*\(#\d+\)$"), re.compile(r"^[a-z]+(\([a-z_.-]+\))?:\s*"))


def check_body(path: str) -> list[tuple[str, str, str]]:
    """본문 한 파일 — 코드 블록 · 표 · 헤더 · 체크리스트는 대상 밖."""
    out, fence = [], False
    for i, raw in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        ln = raw.rstrip()
        if ln.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence or not ln.strip():
            continue
        if ln.startswith(("#", "|", "- [x]", "- [ ]")):
            continue
        text = re.sub(r"^[-*]\s+", "", ln.strip())
        text = re.sub(r"\s*\([^)]*\)\s*$", "", text)
        if NARRATIVE.search(text):
            out.append((f"{path}:{i}", "서술형 종결", ln[:70]))
        if IM_ENDING.search(text):
            out.append((f"{path}:{i}", "임 종결 (동사 명사형이면 정상 · 눈으로 확인)",
                        ln[:70]))
        if BARE_BULLET.match(ln):
            out.append((f"{path}:{i}", "라벨 없는 불릿", ln[:70]))
        if TILDE_RANGE.search(ln):
            out.append((f"{path}:{i}", "범위 물결표", ln[:70]))
    return out


def check_title(title: str, where: str) -> list[tuple[str, str, str]]:
    """제목 하나 — 명사형 종결만 본다 (§1.1)."""
    body = title
    for pat in TITLE_STRIP:
        body = pat.sub("", body)
    if TITLE_TAIL.search(body.strip()):
        return [(where, "제목 서술형 종결", title[:70])]
    return []


def run(*args: str) -> list[str]:
    r = subprocess.run(args, capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def main() -> int:
    ap = argparse.ArgumentParser(description="PR · 커밋 형식 검사")
    ap.add_argument("--body", action="append", default=[], help="본문 파일")
    ap.add_argument("--title", action="append", default=[], help="제목 문자열")
    ap.add_argument("--open-prs", action="store_true", help="열린 PR 제목")
    ap.add_argument("--unpushed", action="store_true", help="푸시 전 커밋 제목")
    ap.add_argument("--merged", type=int, metavar="N", help="머지된 제목 N개 (참고)")
    a = ap.parse_args()

    hits: list[tuple[str, str, str]] = []
    for path in a.body:
        hits += check_body(path)
    for t in a.title:
        hits += check_title(t, "--title")
    if a.open_prs:
        for ln in run("gh", "pr", "list", "--state", "open",
                      "--json", "number,title", "-q",
                      '.[] | "\\(.number)\\t\\(.title)"'):
            num, _, title = ln.partition("\t")
            hits += check_title(title, f"PR #{num}")
    if a.unpushed:
        for s in run("git", "log", "--format=%s", "origin/main..HEAD"):
            hits += check_title(s, "푸시 전 커밋")
    if a.merged:
        print(f"# 머지된 제목 {a.merged}개는 참고용이다 — 커밋 제목은 굳어 못 고친다.")
        for s in run("git", "log", "--format=%s", f"-{a.merged}", "origin/main"):
            hits += check_title(s, "머지됨 (못 고침)")

    if not any([a.body, a.title, a.open_prs, a.unpushed, a.merged]):
        ap.print_help()
        return 2
    for where, kind, text in hits:
        print(f"{where}  {kind}: {text}")
    print(f"\n{len(hits)}건 — 이 검사가 안 보는 것은 파일 머리 주석에 있다.")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
