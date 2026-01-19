import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _integration_ready():
    return (
        os.environ.get("PYCEMKR_INTEGRATION") == "1"
        and shutil.which("cmake")
        and shutil.which("ninja")
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not _integration_ready(),
    reason="set PYCEMKR_INTEGRATION=1 and install cmake+ninja to run integration tests",
)
def test_cli_test_command(tmp_path):
    root = Path(__file__).resolve().parents[1]
    fixture_dir = root / "tests" / "fixtures" / "minimal_project"
    project_dir = tmp_path / "minimal_project"
    shutil.copytree(fixture_dir, project_dir)

    result = subprocess.run(
        [sys.executable, str(root / "main.py"), "test"],
        cwd=project_dir,
        check=False,
    )

    assert result.returncode == 0
