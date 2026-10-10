#!/usr/bin/env python3
"""PostToolUse(Write|Edit) 훅 — 계획서 · 스펙의 「가정과 확인」 · 「더 단순한 꼴」 절 검사.

## 왜 있나

2026-10-07 감사에서 CLAUDE.md 행동 가이드라인 원칙 1 (가정 · 미검증 단정) 이 매 기간 가장 많이 어겨졌다.
「가정은 확인 방법과 함께 적는다」 는 글 규칙은 재발을 못 막았고, 재발이 멈춘 것은 검사기를 만든 경우뿐이었다.
그래서 표의 근거 칸이 비면 실패하게 한다 (단정에 근거 주석이 없으면 오류를 내는 린트 규칙과 같은 꼴).

## 검사

- 계획서 (`docs/superpowers/plans/`) — `## 작업 원칙` · `## 가정과 확인` · `## 더 단순한 꼴과 버린 이유` 절과
  Task 머리글 (`### Task N`) 마다 백틱 경로가 든 `**Files:**` 블록 (범위 검사 `.claude/tools/check-plan-scope.py` 의 입력)
- 스펙 (`docs/superpowers/specs/`) — `## 가정과 확인` · `## 더 단순한 꼴과 버린 이유` 절 (`## 2. 가정과 확인` 처럼 번호가 붙어도 된다)
- 「가정과 확인」 · 「더 단순한 꼴」 은 표가 있어야 하고, 표의 데이터 행에 빈 칸 (`-` · `—` 만 있는 칸 포함) 이 없어야 한다
- 코드 블록 안의 `#` 줄은 머리글로 읽지 않는다

## 쓰는 법

    python3 .claude/hooks/check-plan-sections.py <계획서 또는 스펙 경로> ...   # 날짜와 관계없이 검사
    (인자 없이 부르면 stdin 의 훅 JSON 을 읽고, 파일 이름 날짜가 START 이후인 문서만 본다)

## 이 검사가 안 보는 것

- 확인 칸에 적은 방법이 실제로 돌았는지 · 결과가 맞는지 (「운영 DB 조회」 라고만 적어도 통과한다)
- 「추정」 표시가 필요한 행에 붙었는지
- 표 밖 산문의 단정 · Files 목록이 실제 변경과 맞는지 (그건 범위 검사의 몫)
- START 전 문서 — 2026-10-07 스펙까지는 이 절 없이 머지됐다

**통과했다고 근거가 맞는 것은 아니다** — 칸이 비지 않았다는 것만 안다.
"""
import json, os, re, sys

START = "2026-10-12"
PLAN_SECTIONS = ["작업 원칙", "가정과 확인", "더 단순한 꼴과 버린 이유"]
SPEC_SECTIONS = ["가정과 확인", "더 단순한 꼴과 버린 이유"]
TABLE_SECTIONS = {"가정과 확인", "더 단순한 꼴과 버린 이유"}
H2 = re.compile(r"^##\s+(?:\d+\.\s*)?(.+?)\s*$")
TASK = re.compile(r"^#{2,3}\s+(Task\s+\d+)")
EMPTY_CELL = {"", "-", "—"}


def kind_of(path: str):
    p = path.replace(os.sep, "/")
    if "/docs/superpowers/plans/" in p:
        return "plan"
    if "/docs/superpowers/specs/" in p:
        return "spec"
    return None


def headings(lines):
    """코드 블록 밖의 줄만 (번호, 줄) 로 — 계획서는 yaml · 마크다운 블록에 `#` 줄을 담는다."""
    fence = False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence:
            yield i, ln


def sections(lines):
    """`## 이름` → 그 절의 본문 줄 (다음 `#` · `##` 머리글 전까지 · 코드 블록 밖)."""
    out, cur = {}, None
    for _, ln in headings(lines):
        m = H2.match(ln)
        if m or re.match(r"^#\s", ln):
            cur = None
            if m:
                cur = next((s for s in PLAN_SECTIONS if m.group(1).startswith(s)), None)
                if cur:
                    out[cur] = []
            continue
        if cur:
            out[cur].append(ln)
    return out


def table_problems(name, body):
    rows = [ln.strip() for ln in body if ln.strip().startswith("|")]
    data = rows[2:]                                # 머리 행과 구분 행 다음
    if not data:
        return [f"「{name}」 에 표가 없다 (데이터 행 1개 이상)"]
    out = []
    for r in data:
        cells = [c.strip() for c in r.strip("|").split("|")]
        if any(c in EMPTY_CELL for c in cells):
            out.append(f"「{name}」 표에 빈 칸: {r[:60]}")
    return out


def task_problems(lines):
    out, tasks, cur = [], [], None
    for _, ln in headings(lines):
        m = TASK.match(ln)
        if m:
            cur = [m.group(1), False, False]       # 이름 · Files 블록 · 백틱 경로
            tasks.append(cur)
            continue
        if cur is None:
            continue
        if ln.strip() in ("**Files:**", "**Files**"):
            cur[1] = True
        elif cur[1] and ln.lstrip().startswith("- ") and "`" in ln:
            cur[2] = True
    if not tasks:
        out.append("Task 머리글 (`### Task N`) 이 없다")
    for name, has_block, has_path in tasks:
        if not has_block:
            out.append(f"{name} 에 `**Files:**` 블록이 없다")
        elif not has_path:
            out.append(f"{name} 의 Files 블록에 백틱 경로가 없다")
    return out


def violations(path: str, kind: str):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    found = sections(lines)
    out = []
    for name in (PLAN_SECTIONS if kind == "plan" else SPEC_SECTIONS):
        if name not in found:
            out.append(f"「## {name}」 절이 없다")
        elif name in TABLE_SECTIONS:
            out += table_problems(name, found[name])
        elif not any(ln.strip() for ln in found[name]):
            out.append(f"「{name}」 절이 비었다")
    if kind == "plan":
        out += task_problems(lines)
    return out


def report(path, v, stream=sys.stderr):
    print(f"{path}: 위반 {len(v)}건 (계획서 · 스펙 절 · CLAUDE.md 행동 가이드라인 1 · 2)", file=stream)
    for kind in v:
        print(f"  - {kind}", file=stream)


def check_files(paths):
    bad = 0
    for p in paths:
        if not os.path.isfile(p):
            print(f"{p}: 파일이 없다", file=sys.stderr)
            bad += 1
            continue
        kind = kind_of(os.path.abspath(p))
        if not kind:
            print(f"{p}: 계획서 · 스펙 경로가 아니다 (docs/superpowers/plans · specs)", file=sys.stderr)
            bad += 1
            continue
        v = violations(p, kind)
        if v:
            bad += 1
            report(p, v)
        else:
            print(f"{p}: 위반 없음")
    return 2 if bad else 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        return check_files(args)
    if sys.argv[1:]:
        print("사용법: check-plan-sections.py <문서 경로> ...  (인자 없이 부르면 stdin 의 훅 JSON 을 읽는다)",
              file=sys.stderr)
        return 2
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    f = data.get("tool_input", {}).get("file_path", "")
    kind = kind_of(f)
    m = re.match(r"(\d{4}-\d{2}-\d{2})-", os.path.basename(f))
    if not kind or not f.endswith(".md") or not m or m.group(1) < START or not os.path.isfile(f):
        return 0
    v = violations(f, kind)
    if not v:
        return 0
    report(f, v)
    return 2


if __name__ == "__main__":
    sys.exit(main())
