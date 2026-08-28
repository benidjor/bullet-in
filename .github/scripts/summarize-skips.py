#!/usr/bin/env python3
"""pytest 결과 (JUnit XML) 를 GitHub 요약에 적고, 건너뛴 테스트가 허용치를 넘으면 실패시킨다.

## 왜 있나

통합 테스트는 MariaDB 가 없으면 `pytest.skip` 으로 빠진다 — 그리고 초록불이 난다.
러너에서 DB 컨테이너가 죽거나 접속이 막히면 69건이 조용히 안 돌면서 CI 는 통과로 보인다.
건너뛴 수를 허용치와 대 봐서, 안 돈 것이 늘면 빨간불이 되게 한다.

## 쓰는 법

    python3 .github/scripts/summarize-skips.py report.xml --max-skips 1

## 이 검사가 안 보는 것

- 건너뛴 테스트의 **정체가 바뀐 경우** — 수가 같으면 통과한다 (요약 표에는 이름이 그대로 찍히므로 눈으로는 보인다)
- 테스트의 통과 · 실패 자체 — 그것은 pytest 의 종료 코드가 본다
- 수집조차 안 된 테스트 — XML 에 안 실리므로 총계가 줄어드는 모양으로만 드러난다
"""
from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET


def reason(el: ET.Element) -> str:
    """건너뛴 사유 — 수집 단계 건너뜀은 message 가 「collection skipped」 뿐이라 본문에서 캔다."""
    body = (el.text or "")
    if "Skipped:" in body:
        return body.split("Skipped:")[-1].strip(" \"')\n")
    return (el.get("message") or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="pytest 건너뜀 요약 · 허용치 검사")
    ap.add_argument("report", help="JUnit XML 경로")
    ap.add_argument("--max-skips", type=int, required=True, help="허용 건너뜀 수")
    a = ap.parse_args()

    suite = ET.parse(a.report).getroot().find("testsuite")
    total = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = [
        (f"{c.get('classname')}::{c.get('name')}".lstrip(":"), reason(c.find("skipped")))
        for c in suite.iter("testcase") if c.find("skipped") is not None
    ]
    over = len(skipped) > a.max_skips

    lines = [
        "## 테스트 요약",
        "",
        f"- 수집 {total}건 · 실패 {failures}건 · 오류 {errors}건 · **건너뜀 {len(skipped)}건** "
        f"(허용치 {a.max_skips}건)",
        "",
    ]
    if skipped:
        lines += ["### 건너뛴 테스트", "", "| 테스트 | 사유 |", "| --- | --- |"]
        lines += [f"| `{name}` | {msg} |" for name, msg in skipped]
        lines.append("")
    if over:
        lines += [
            f"> **건너뜀이 허용치를 넘었다** — 러너에 MariaDB 가 안 떴거나 새 건너뜀이 들어왔다. "
            f"의도한 변화면 워크플로의 `--max-skips` 를 함께 올린다.",
            "",
        ]
    out = "\n".join(lines)
    print(out)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(out + "\n")
    if over:
        print(f"::error::건너뛴 테스트 {len(skipped)}건 > 허용치 {a.max_skips}건", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
