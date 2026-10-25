"""PR 형식 검사 도구가 본문의 Claude 서명 줄을 잡는지 본다.

컨벤션 §2.7 은 PR 본문에 Claude 서명을 금하지만 검사기에는 그 규칙이 없었다.
#552 부터 #558 까지 일곱 PR 본문 끝에 「🤖 Generated with Claude Code」 줄이 붙었고 CI 는 모두 통과했다.
"""
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / ".claude" / "tools" / "check-pr-format.py"
SIGNATURE = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"


def _run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


def _body(tmp_path, text):
    p = tmp_path / "body.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_signature_line_fails_the_signature_check(tmp_path):
    r = _run("--signature", _body(tmp_path, f"## 7. 레퍼런스\n\n- **설계** — 문서\n\n{SIGNATURE}\n"))
    assert r.returncode == 1
    assert "Claude 서명" in r.stdout


def test_signature_line_without_emoji_also_fails(tmp_path):
    r = _run("--signature", _body(tmp_path, "Generated with [Claude Code](https://claude.com/claude-code)\n"))
    assert r.returncode == 1


def test_inline_mention_of_the_rule_passes(tmp_path):
    """규칙을 설명하려고 문장 안에 인용한 것은 서명이 아니다."""
    text = f"- **서명** — 본문 끝의 `{SIGNATURE}` 줄을 지움\n"
    r = _run("--signature", _body(tmp_path, text))
    assert r.returncode == 0, r.stdout


def test_signature_quoted_in_a_code_block_passes(tmp_path):
    r = _run("--signature", _body(tmp_path, f"```\n{SIGNATURE}\n```\n"))
    assert r.returncode == 0, r.stdout


def test_body_check_also_reports_the_signature(tmp_path):
    r = _run("--body", _body(tmp_path, f"{SIGNATURE}\n"))
    assert "Claude 서명" in r.stdout
