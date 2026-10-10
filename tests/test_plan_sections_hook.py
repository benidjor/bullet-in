"""계획서 · 스펙 절 검사기가 근거 칸이 빈 문서를 막고, 조용히 통과하지 않는지 본다.

글로 적은 규칙 (「가정은 확인 방법과 함께」) 은 재발을 못 막았고 검사기를 만든 경우만 막았다.
그래서 「가정과 확인」 · 「더 단순한 꼴과 버린 이유」 표의 칸이 비면 실패하게 한다.
"""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "check-plan-sections.py"

PRINCIPLES = "## 작업 원칙 (Karpathy 4원칙)\n\n- **요청 밖 변경 금지** — 보고만 한다.\n\n"
ASSUMPTIONS = ("## 가정과 확인\n\n| 가정 | 확인 방법 · 결과 |\n| --- | --- |\n"
               "| 명단은 41명이다 | 운영 DB 조회 |\n\n")
SIMPLER = ("## 더 단순한 꼴과 버린 이유\n\n| 더 단순한 꼴 | 버린 이유 |\n| --- | --- |\n"
           "| 키워드만 늘리기 | 이름 갈래가 대부분이다 |\n\n")
TASK = ("### Task 1: 판정 모듈\n\n**Files:**\n- Create: `src/bullet_in/scope.py`\n"
        "- Test: `tests/test_scope.py`\n\n- [ ] **Step 1**\n\n```python\n# 주석은 머리글이 아니다\n```\n\n")
PLAN_OK = "# 계획\n\n" + PRINCIPLES + ASSUMPTIONS + SIMPLER + TASK
SPEC_OK = "# 설계\n\n## 1. 배경\n\n배경이다.\n\n" + ASSUMPTIONS.replace("## ", "## 2. ") + SIMPLER.replace("## ", "## 3. ")


def _run(args, stdin=""):
    return subprocess.run([sys.executable, str(HOOK), *args],
                          input=stdin, capture_output=True, text=True)


def _write(tmp_path, kind, name, body):
    d = tmp_path / "docs" / "superpowers" / kind
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(body, encoding="utf-8")
    return f


def test_a_complete_plan_passes_with_a_visible_line(tmp_path):
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", PLAN_OK))])
    assert r.returncode == 0, r.stderr
    assert "위반 없음" in r.stdout


def test_a_complete_spec_passes_numbered_headings_included(tmp_path):
    r = _run([str(_write(tmp_path, "specs", "2026-10-12-x-design.md", SPEC_OK))])
    assert r.returncode == 0, r.stderr


def test_missing_sections_are_named(tmp_path):
    body = "# 계획\n\n" + TASK
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2
    for name in ("작업 원칙", "가정과 확인", "더 단순한 꼴과 버린 이유"):
        assert name in r.stderr


def test_spec_does_not_need_working_principles(tmp_path):
    body = SPEC_OK.replace(SIMPLER.replace("## ", "## 3. "), "")
    r = _run([str(_write(tmp_path, "specs", "2026-10-12-x-design.md", body))])
    assert r.returncode == 2 and "더 단순한 꼴" in r.stderr
    assert "작업 원칙" not in r.stderr


def test_an_empty_evidence_cell_fails(tmp_path):
    """근거 칸이 비면 실패 — 가정만 적고 확인을 안 적은 꼴."""
    body = PLAN_OK.replace("| 명단은 41명이다 | 운영 DB 조회 |", "| 명단은 41명이다 |  |")
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2
    assert "빈 칸" in r.stderr and "가정과 확인" in r.stderr


def test_a_section_without_a_table_fails(tmp_path):
    body = PLAN_OK.replace(SIMPLER, "## 더 단순한 꼴과 버린 이유\n\n없다.\n\n")
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2
    assert "표" in r.stderr


def test_a_task_without_files_fails(tmp_path):
    body = PLAN_OK + "### Task 2: 화면\n\n- [ ] **Step 1**\n"
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2
    assert "Task 2" in r.stderr and "Files" in r.stderr


def test_headings_inside_code_fences_are_ignored(tmp_path):
    """계획서는 yaml · 마크다운 코드 블록에 `#` · `##` 줄을 담는다 — 머리글로 읽으면 절이 끊긴다."""
    fence = "```markdown\n## 가정과 확인\n```\n\n"
    body = "# 계획\n\n" + PRINCIPLES + fence + SIMPLER + TASK
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2
    assert "가정과 확인" in r.stderr


def test_a_missing_file_is_a_failure_not_a_pass(tmp_path):
    r = _run([str(tmp_path / "docs" / "superpowers" / "plans" / "없는파일.md")])
    assert r.returncode == 2
    assert "파일이 없다" in r.stderr          # 파이썬이 스크립트를 못 찾아도 2 가 난다


def test_hook_checks_new_plans_and_skips_older_ones(tmp_path):
    bad = "# 계획\n\n" + TASK
    new = _write(tmp_path, "plans", "2026-10-12-new.md", bad)
    old = _write(tmp_path, "plans", "2026-10-07-old.md", bad)
    as_hook = lambda f: _run([], stdin=json.dumps({"tool_input": {"file_path": str(f)}}))
    assert as_hook(new).returncode == 2
    assert as_hook(old).returncode == 0            # 시작일 전 문서는 훅이 안 본다


def test_hook_ignores_other_docs(tmp_path):
    d = tmp_path / "docs" / "runbook"
    d.mkdir(parents=True)
    f = d / "2026-10-12-x.md"
    f.write_text("# 런북\n", encoding="utf-8")
    assert _run([], stdin=json.dumps({"tool_input": {"file_path": str(f)}})).returncode == 0


def test_backticks_outside_the_files_block_do_not_count(tmp_path):
    """Files 블록이 비었는데 뒤 Step 불릿의 백틱으로 통과하던 꼴 (리뷰 2026-10-11)."""
    task = ("### Task 1: 판정 모듈\n\n**Files:**\n- Modify: 없음\n\n"
            "- [ ] **Step 1** run `pytest tests/x.py`\n")
    body = "# 계획\n\n" + PRINCIPLES + ASSUMPTIONS + SIMPLER + task
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2
    assert "백틱 경로" in r.stderr


def test_symbol_backticks_are_not_paths(tmp_path):
    task = "### Task 1: 판정\n\n**Files:**\n- Modify: `__init__` 한 줄\n"
    body = "# 계획\n\n" + PRINCIPLES + ASSUMPTIONS + SIMPLER + task
    assert _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))]).returncode == 2


def test_tilde_fences_are_code_too(tmp_path):
    body = "# 계획\n\n" + PRINCIPLES + "~~~markdown\n" + ASSUMPTIONS + "~~~\n\n" + SIMPLER + TASK
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2 and "가정과 확인" in r.stderr


def test_a_longer_fence_can_hold_a_shorter_one(tmp_path):
    """네 백틱 블록 안의 세 백틱 줄을 닫는 줄로 읽으면, 블록 안 예시 절이 진짜 절이 된다."""
    inner = "````markdown\n```\n" + ASSUMPTIONS + "```\n````\n\n"
    body = "# 계획\n\n" + PRINCIPLES + inner + SIMPLER + TASK
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2 and "가정과 확인" in r.stderr


def test_a_table_without_a_separator_row_fails(tmp_path):
    body = PLAN_OK.replace("| --- | --- |\n| 명단은", "| 명단은")
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2 and "구분 행" in r.stderr


def test_a_trailing_empty_cell_is_caught(tmp_path):
    body = PLAN_OK.replace("| 명단은 41명이다 | 운영 DB 조회 |", "| 명단은 41명이다 | 운영 DB 조회 ||")
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 2 and "빈 칸" in r.stderr


def test_a_repeated_section_adds_rather_than_replaces(tmp_path):
    body = PLAN_OK + "## 가정과 확인 (추가)\n\n"
    r = _run([str(_write(tmp_path, "plans", "2026-10-12-x.md", body))])
    assert r.returncode == 0, r.stderr


def test_hook_accepts_a_relative_path(tmp_path, monkeypatch):
    _write(tmp_path, "plans", "2026-10-12-x.md", "# 계획\n")
    payload = json.dumps({"tool_input": {"file_path": "docs/superpowers/plans/2026-10-12-x.md"}})
    r = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 2
