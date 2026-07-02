#!/usr/bin/env python3
"""PostToolUse(Write|Edit) 훅 — docs/ 아래 .md 서식 검사.

검사: 줄끝 →/— · '·' 양옆 공백 · 여는 괄호 앞 공백.
제외: 코드펜스(```) · 인라인코드(`...`) · URL · 마크다운 링크 타깃.
위반 시 stderr 출력 + exit 2 (모델에 피드백). 근거: 컨벤션 §2.2 / memory symbol-spacing-in-docs.
주의: 백틱 안 씌운 코드/템플릿 표현은 오탐할 수 있음 → 대개 인라인코드로 감싸면 해소.
"""
import json, re, sys


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


def main() -> int:
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
