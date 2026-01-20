import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest


def _copy_fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[1]
    fixture_dir = root / "tests" / "fixtures" / "minimal_project"
    project_dir = tmp_path / "minimal_project"
    shutil.copytree(fixture_dir, project_dir)
    return root, project_dir


@pytest.mark.integration
def test_cli_test_command(tmp_path):
    root, project_dir = _copy_fixture(tmp_path)

    result = subprocess.run(
        [sys.executable, str(root / "main.py"), "test"],
        cwd=project_dir,
        check=False,
    )

    assert result.returncode == 0


@pytest.mark.integration
def test_cli_build_command(tmp_path):
    root, project_dir = _copy_fixture(tmp_path)

    result = subprocess.run(
        [sys.executable, str(root / "main.py"), "build"],
        cwd=project_dir,
        check=False,
    )

    exe_name = "main.exe" if os.name == "nt" else "main"
    exe_path = project_dir / "build" / exe_name
    assert result.returncode == 0
    assert exe_path.exists()


@pytest.mark.integration
def test_cli_run_command(tmp_path):
    root, project_dir = _copy_fixture(tmp_path)

    result = subprocess.run(
        [sys.executable, str(root / "main.py"), "run"],
        cwd=project_dir,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Hello from MinimalProject." in result.stdout


@pytest.mark.integration
def test_cli_all_command(tmp_path):
    root, project_dir = _copy_fixture(tmp_path)

    result = subprocess.run(
        [sys.executable, str(root / "main.py"), "all"],
        cwd=project_dir,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Hello from MinimalProject." in result.stdout
