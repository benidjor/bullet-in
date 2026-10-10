"""범위 검사 도구가 계획서 Files 목록 밖의 변경을 잡는지 본다.

리뷰는 「요청 밖 변경」 을 사람 눈으로만 봤고 (2026-10-07 감사 · #528 최종 수정의 설계 밖 변경 둘)
바뀐 파일과 계획서 목록을 기계로 대 보는 자리는 없었다.
"""
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / ".claude" / "tools" / "check-plan-scope.py"

PLAN = """# 계획

### Task 1: 판정 모듈

**Files:**
- Create: `src/app/scope.py`
- Modify: `src/app/run.py:40-52` (배선)
- Test: `tests/test_scope.py::test_names`
- Modify: `README.md` 소스 표

### Task 2: 문서

**Files:**
- 변경 없음 (검증 전용)
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    for rel in ("src/app/run.py", "README.md", "src/app/other.py"):
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "tag", "base")
    plan = repo / "docs" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(PLAN, encoding="utf-8")
    return repo, plan


def _run(repo, plan):
    return subprocess.run([sys.executable, str(TOOL), "--plan", str(plan), "--base", "base"],
                          cwd=repo, capture_output=True, text=True)


def _touch(repo, rel, text="y\n"):
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def test_changes_inside_the_list_pass(tmp_path):
    repo, plan = _repo(tmp_path)
    _touch(repo, "src/app/scope.py")
    _touch(repo, "src/app/run.py")
    _touch(repo, "tests/test_scope.py")
    r = _run(repo, plan)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "범위 밖 0" in r.stdout


def test_a_file_outside_the_list_fails_and_is_named(tmp_path):
    repo, plan = _repo(tmp_path)
    _touch(repo, "src/app/scope.py")
    _touch(repo, "src/app/other.py")             # 목록에 없다
    r = _run(repo, plan)
    assert r.returncode == 1
    assert "src/app/other.py" in r.stdout


def test_committed_changes_are_seen_too(tmp_path):
    repo, plan = _repo(tmp_path)
    _touch(repo, "src/app/other.py")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "work")
    assert _run(repo, plan).returncode == 1


def test_the_plan_itself_is_in_scope(tmp_path):
    repo, plan = _repo(tmp_path)                 # 계획서는 아직 추적 안 된 새 파일이다
    r = _run(repo, plan)
    assert r.returncode == 0, r.stdout


def test_listed_but_untouched_files_are_reported_not_failed(tmp_path):
    repo, plan = _repo(tmp_path)
    _touch(repo, "src/app/scope.py")
    r = _run(repo, plan)
    assert r.returncode == 0
    assert "README.md" in r.stdout and "안 바뀜" in r.stdout


def test_a_plan_without_files_blocks_is_a_failure_not_a_pass(tmp_path):
    """목록이 비면 모든 변경이 범위 밖인지 판단할 근거가 없다 — 통과로 읽히면 안 된다."""
    repo, plan = _repo(tmp_path)
    plan.write_text("# 계획\n\n### Task 1\n", encoding="utf-8")
    r = _run(repo, plan)
    assert r.returncode == 2
    assert "Files" in r.stderr


def test_a_missing_plan_is_a_failure(tmp_path):
    repo, _ = _repo(tmp_path)
    r = _run(repo, repo / "docs" / "없는계획.md")
    assert r.returncode == 2
    assert "파일이 없다" in r.stderr


def test_running_from_a_subdirectory_sees_the_whole_repo(tmp_path):
    repo, plan = _repo(tmp_path)
    _touch(repo, "src/app/scope.py")
    _touch(repo, "top_stray.py")                 # 루트의 범위 밖 새 파일
    r = subprocess.run([sys.executable, str(TOOL), "--plan", str(plan), "--base", "base"],
                       cwd=repo / "src", capture_output=True, text=True)
    assert r.returncode == 1
    assert "top_stray.py" in r.stdout and "src/app/scope.py" not in r.stdout.split("목록에 있는데")[0].split("범위 밖")[1]


def test_a_rename_shows_the_old_path_too(tmp_path):
    repo, plan = _repo(tmp_path)
    _git(repo, "mv", "src/app/other.py", "src/app/scope.py")   # 목록에 있는 이름으로 옮긴다
    r = _run(repo, plan)
    assert r.returncode == 1
    assert "src/app/other.py" in r.stdout


def test_a_step_bullet_after_the_files_block_is_not_a_listed_path(tmp_path):
    repo, plan = _repo(tmp_path)
    plan.write_text(PLAN + "\n### Task 3\n\n**Files:**\n- Modify: `src/app/run.py`\n\n"
                    "- [ ] **Step 1** `src/app/other.py` 를 읽는다\n", encoding="utf-8")
    _touch(repo, "src/app/other.py")
    assert _run(repo, plan).returncode == 1


def test_an_unknown_base_is_exit_2_not_1(tmp_path):
    repo, plan = _repo(tmp_path)
    r = subprocess.run([sys.executable, str(TOOL), "--plan", str(plan), "--base", "nope"],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 2
