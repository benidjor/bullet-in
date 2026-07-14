import subprocess, sys


def test_benchmark_module_help_exits_zero():
    # 진입점 스모크: 임포트 + argparse 배선만 검증 (라이브 fetch 없음)
    proc = subprocess.run(
        [sys.executable, "-m", "bullet_in.benchmark", "--help"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert "--gap" in proc.stdout
