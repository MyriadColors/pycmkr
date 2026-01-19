import json
import os
import sys
from pathlib import Path

import pytest

import main


def test_apply_config_file_sets_fields(tmp_path):
    config = {
        "build_dir": "out",
        "default_test_target": "unit",
        "test_targets": ["unit", "integration"],
        "dependency_file": "deps.cmake",
        "dependency_local_function": "local_dep",
        "dependency_fetch_function": "fetch_dep",
        "project": {
            "name": "Demo",
            "main_target": "demo",
            "languages": ["CXX"],
            "main_sources": ["main.cpp"],
        },
    }
    path = tmp_path / "build_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    result = main._apply_config_file(path)

    assert result == 0
    assert main.BUILD_CONFIG["build_dir"] == Path("out")
    assert main.BUILD_CONFIG["default_test_target"] == "unit"
    assert main.BUILD_CONFIG["test_targets"] == ["unit", "integration"]
    assert main.BUILD_CONFIG["dependency_file"] == Path("deps.cmake")
    assert main.BUILD_CONFIG["dependency_local_function"] == "local_dep"
    assert main.BUILD_CONFIG["dependency_fetch_function"] == "fetch_dep"
    assert main.BUILD_CONFIG["project"]["name"] == "Demo"
    assert main.BUILD_CONFIG["project"]["main_target"] == "demo"
    assert main.BUILD_CONFIG["project"]["languages"] == ["CXX"]
    assert main.BUILD_CONFIG["project"]["main_sources"] == ["main.cpp"]


def test_apply_config_file_rejects_invalid_test_targets(tmp_path):
    path = tmp_path / "build_config.json"
    path.write_text(json.dumps({"test_targets": "nope"}), encoding="utf-8")

    result = main._apply_config_file(path)

    assert result == 1


def test_apply_env_overrides(monkeypatch):
    monkeypatch.setenv("BUILD_DIR", "custom_build")
    monkeypatch.setenv("MAIN_TARGET", "app")
    monkeypatch.setenv("TEST_TARGET", "unit_tests")
    monkeypatch.setenv("TEST_TARGETS", "unit_tests, integration_tests")
    monkeypatch.setenv("DEPENDENCY_FILE", "deps.cmake")
    monkeypatch.setenv("DEPENDENCY_LOCAL_FUNCTION", "local_dep")
    monkeypatch.setenv("DEPENDENCY_FETCH_FUNCTION", "fetch_dep")

    main._apply_env_overrides()

    assert main.BUILD_CONFIG["build_dir"] == Path("custom_build")
    assert main.BUILD_CONFIG["default_test_target"] == "unit_tests"
    assert main.BUILD_CONFIG["test_targets"] == ["unit_tests", "integration_tests"]
    assert main.BUILD_CONFIG["dependency_file"] == Path("deps.cmake")
    assert main.BUILD_CONFIG["dependency_local_function"] == "local_dep"
    assert main.BUILD_CONFIG["dependency_fetch_function"] == "fetch_dep"
    assert main.BUILD_CONFIG["project"]["main_target"] == "app"


def test_discover_config_path(tmp_path):
    root = tmp_path / "root"
    child = root / "child"
    grandchild = child / "grandchild"
    grandchild.mkdir(parents=True)
    config_path = root / "build_config.json"
    config_path.write_text("{}", encoding="utf-8")

    result = main._discover_config_path(grandchild, ["build_config.json"])

    assert result == config_path


def test_resolve_dependency_file_relative(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    resolved = main._resolve_dependency_file(project_root, Path("deps.cmake"))

    assert resolved is not None
    candidate, cmake_path, cmake_is_abs = resolved
    expected_root = main._realpath_with_missing(project_root)
    expected_candidate = main._realpath_with_missing(project_root / "deps.cmake")
    assert candidate == expected_candidate
    assert cmake_path == expected_candidate.relative_to(expected_root)
    assert cmake_is_abs is False


def test_resolve_dependency_file_rejects_outside(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    resolved = main._resolve_dependency_file(project_root, Path("../deps.cmake"))

    assert resolved is None


def test_run_tests_build_and_execute(tmp_path, monkeypatch):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    target = "unit_tests"
    test_name = f"{target}.exe" if os.name == "nt" else target
    test_path = build_dir / test_name
    test_path.write_text("", encoding="utf-8")

    calls = {"build": [], "run": []}

    def fake_build(target_name):
        calls["build"].append(target_name)
        return 0

    def fake_run(cmd, cwd=None, env=None):
        calls["run"].append(cmd)
        return 0

    monkeypatch.setattr(main, "cmake_build_target", fake_build)
    monkeypatch.setattr(main, "run_cmd", fake_run)

    config = {
        "build_dir": build_dir,
        "project": {"main_target": "app"},
    }

    result = main.run_tests(config, [target])

    assert result == 0
    assert calls["build"] == [target]
    assert calls["run"] == [[str(test_path)]]


def test_run_executable_missing_exits(tmp_path):
    config = {
        "build_dir": tmp_path,
        "project": {"main_target": "app"},
    }

    with pytest.raises(SystemExit):
        main.run_executable(config, [])


def test_main_parses_test_target(tmp_path, monkeypatch):
    config = {
        "build_dir": "build",
        "default_test_target": "unit_tests",
        "test_targets": ["unit_tests"],
        "dependency_file": "dependencies.cmake",
        "dependency_local_function": "project_add_local_dependency",
        "dependency_fetch_function": "project_add_fetch_dependency",
        "project": {
            "name": "Demo",
            "languages": ["C"],
            "min_cmake": "3.10",
            "c_standard": "23",
            "main_target": "main",
            "main_sources": ["main.c"],
            "test_targets": [{"name": "unit_tests", "sources": ["unit_tests.c"]}],
        },
    }
    config_path = tmp_path / "build_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    targets = {}

    def fake_ensure_configured(compiler=None):
        return 0

    def fake_run_tests(resolved_config, target_list):
        targets["value"] = target_list
        return 0

    monkeypatch.setattr(main, "ensure_configured", fake_ensure_configured)
    monkeypatch.setattr(main, "run_tests", fake_run_tests)
    monkeypatch.setattr(sys, "argv", ["pycmkr", "test", "--target", "unit_tests"])

    result = main.main()

    assert result == 0
    assert targets["value"] == ["unit_tests"]
