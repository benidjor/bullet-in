#!/usr/bin/env python3
"""PostToolUse(Write|Edit) 훅 — docs/ 아래 .md 서식 검사.

검사: 줄끝 →/— · '·' 양옆 공백 · 여는 괄호 앞 공백.
제외: 코드펜스(```) · 인라인코드(`...`) · URL · 마크다운 링크 타깃.
위반 시 stderr 출력 + exit 2 (모델에 피드백). 근거: 컨벤션 §2.2 / memory symbol-spacing-in-docs.
주의: 백틱 안 씌운 코드/템플릿 표현은 오탐할 수 있음 → 대개 인라인코드로 감싸면 해소.
손으로 부를 때: check-doc-format.py <문서 경로> ... (인자 없이 부르면 stdin 의 훅 JSON 을 읽는다).
"""
import json, os, re, sys


def strip_code(line: str) -> str:
    line = re.sub(r"`[^`]*`", "CODE", line)      # 인라인코드 → 워드 자리표시
    line = re.sub(r"\]\([^)]*\)", "]", line)      # 마크다운 링크 타깃
    line = re.sub(r"https?://\S+", "", line)      # bare URL
    return line


def violations(path: str):
    out = []
    infence = False
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            infence = not infence
            continue
        if infence:
            continue
        if re.search(r"(→|—)[ \t]*$", line):
            out.append((i, "줄끝 →/—"))
        s = strip_code(line)
        for m in re.finditer(r"·", s):
            a = s[m.start() - 1] if m.start() > 0 else " "
            b = s[m.end()] if m.end() < len(s) else " "
            if a != " " or b != " ":
                out.append((i, "· 양옆 공백"))
                break
        if re.search(r"[0-9A-Za-z가-힣]\(", s):
            out.append((i, "( 앞 공백"))
    return out


def check_files(paths: list[str]) -> int:
    """손으로 부를 때 — 경로를 받아 검사하고 결과를 출력한다.

    훅은 stdin 의 JSON 을 읽는데 사람은 파일 경로로 부르려 한다.
    인자를 무시하고 0 을 돌려주던 동안 「검사가 안 돈 것」 을 「위반 없음」 으로 읽은 일이
    2026-08-24 와 2026-09-02 두 번 났다 (정본 2026-08-15-verification-that-silently-passes.md).
    없는 파일도 같은 이유로 막는다 — violations() 는 못 읽으면 빈 목록을 돌려준다.
    """
    bad = 0
    for p in paths:
        if not os.path.isfile(p):
            print(f"{p}: 파일이 없다", file=sys.stderr)
            bad += 1
            continue
        v = violations(p)
        if not v:
            print(f"{p}: 위반 없음")
            continue
        bad += 1
        print(f"{p}: 위반 {len(v)}건", file=sys.stderr)
        for i, kind in v:
            print(f"  line {i}: [{kind}]", file=sys.stderr)
    return 2 if bad else 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        return check_files(args)
    if sys.argv[1:]:
        print("사용법: check-doc-format.py <문서 경로> ...  (인자 없이 부르면 stdin 의 훅 JSON 을 읽는다)",
              file=sys.stderr)
        return 2
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    f = data.get("tool_input", {}).get("file_path", "")
    if "/docs/" not in f or not f.endswith(".md"):
        return 0
    v = violations(f)
    if not v:
        return 0
    print("문서 서식 위반(컨벤션 §2.2): → · —는 줄 시작 · '·' 양옆 공백 · 여는 괄호 앞 공백.",
          file=sys.stderr)
    for i, kind in v:
        print(f"  line {i}: [{kind}]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
