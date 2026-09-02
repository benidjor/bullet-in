"""문서 서식 훅이 조용히 통과하지 않는지 본다.

이 훅은 stdin 의 JSON 만 읽던 동안, 파일 경로를 인자로 주면 그것을 무시하고 0 을 돌려주었다.
「검사가 안 돈 것」 이 「위반 없음」 으로 읽혀 같은 실수가 2026-08-24 와 2026-09-02 두 번 났다
(정본 docs/troubleshooting/2026-08-15-verification-that-silently-passes.md).
"""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "check-doc-format.py"

BAD = "# 시험\n\n줄끝에 화살표 →\n항목·항목\n괄호를(붙여) 쓴다\n"
OK = "# 시험\n\n정상 문장이다.\n항목 · 항목\n괄호를 (띄워) 쓴다\n"


def _run(args, stdin=""):
    return subprocess.run([sys.executable, str(HOOK), *args],
                          input=stdin, capture_output=True, text=True)


def _write(tmp_path, name, body):
    p = tmp_path / "docs"
    p.mkdir(exist_ok=True)
    f = p / name
    f.write_text(body, encoding="utf-8")
    return f


def test_path_argument_actually_checks_the_file(tmp_path):
    r = _run([str(_write(tmp_path, "bad.md", BAD))])
    assert r.returncode == 2
    assert "줄끝" in r.stderr and "· 양옆 공백" in r.stderr and "( 앞 공백" in r.stderr


def test_a_clean_file_passes_with_a_visible_line(tmp_path):
    r = _run([str(_write(tmp_path, "ok.md", OK))])
    assert r.returncode == 0
    assert "위반 없음" in r.stdout          # 침묵이 아니라 통과했다고 말한다


def test_a_missing_file_is_a_failure_not_a_pass(tmp_path):
    r = _run([str(tmp_path / "docs" / "없는파일.md")])
    assert r.returncode == 2                # violations() 는 못 읽으면 빈 목록을 준다


def test_flag_style_argument_is_treated_as_a_path(tmp_path):
    """2026-09-02 에 실제로 친 형태 — 그때는 조용히 0 이 나왔다."""
    r = _run(["--file", str(_write(tmp_path, "bad2.md", BAD))])
    assert r.returncode == 2


def test_hook_path_still_reads_stdin_json(tmp_path):
    f = _write(tmp_path, "bad3.md", BAD)
    payload = json.dumps({"tool_input": {"file_path": str(f)}})
    assert _run([], stdin=payload).returncode == 2
    clean = json.dumps({"tool_input": {"file_path": str(_write(tmp_path, "ok3.md", OK))}})
    assert _run([], stdin=clean).returncode == 0


def test_hook_path_ignores_files_outside_docs(tmp_path):
    """훅으로 돌 때만 경로 필터가 걸린다 — 손으로 부르면 어디든 검사한다."""
    outside = tmp_path / "bad.md"
    outside.write_text(BAD, encoding="utf-8")
    payload = json.dumps({"tool_input": {"file_path": str(outside)}})
    assert _run([], stdin=payload).returncode == 0
    assert _run([str(outside)]).returncode == 2
