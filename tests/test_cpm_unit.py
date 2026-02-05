import json
import os
from pathlib import Path
import pytest
from pycmkr.cli import (
    BuildConfigManager,
    _validate_dependencies,
    _render_cmakelists,
    _add_cpm_dependency,
    DEFAULT_DEPENDENCY_FILE,
)

def test_validate_dependencies_basic():
    deps = {
        "mylib": {
            "git_url": "https://github.com/user/mylib.git",
            "git_tag": "v1.0",
            "type": "static"
        }
    }
    res, validated = _validate_dependencies(deps)
    assert res == 0
    assert validated == deps

def test_validate_dependencies_complex():
    deps = {
        "mylib": {
            "git_url": "https://github.com/user/mylib.git",
            "include_dirs": ["include", "src"],
            "compile_options": ["-Wall"],
            "binary_urls": {"linux": "url1"}
        }
    }
    res, validated = _validate_dependencies(deps)
    assert res == 0
    assert validated["mylib"]["include_dirs"] == ["include", "src"]
    assert validated["mylib"]["binary_urls"] == {"linux": "url1"}

def test_validate_dependencies_invalid():
    deps = {
        "mylib": {
            "include_dirs": "not a list"
        }
    }
    res, validated = _validate_dependencies(deps)
    assert res == 1
    assert validated is None

def test_render_cmakelists_cpm(tmp_path):
    project = {
        "name": "TestProj",
        "languages": ["C"],
        "min_cmake": "3.20",
        "c_standard": "11",
        "main_target": "main",
        "main_sources": ["main.c"],
        "test_targets": [],
        "dependencies": {
            "fmt": {
                "git_url": "https://github.com/fmtlib/fmt.git",
                "git_tag": "10.0.0"
            }
        }
    }
    output = _render_cmakelists(
        project,
        Path("deps.cmake"),
        False,
        "local_fn",
        "fetch_fn",
        "cpm_fn"
    )
    assert 'include("${CPM_SOURCE_LOCATION}")' in output
    assert 'function(cpm_fn name git_url)' in output
    assert 'cpm_fn("fmt" "https://github.com/fmtlib/fmt.git" GIT_TAG "10.0.0" )' in output

def test_add_cpm_dependency_file_update(tmp_path, monkeypatch):
    dep_file = tmp_path / "dependencies.cmake"
    
    # Mock config_manager
    class MockManager:
        dependency_file_resolved = dep_file
        dependency_file = dep_file
        dependency_local_function = "project_add_local_dependency"
        dependency_fetch_function = "project_add_fetch_dependency"
        dependency_cpm_function = "project_add_cpm_dependency"
    
    monkeypatch.setattr("pycmkr.cli.config_manager", MockManager())
    monkeypatch.setattr("pycmkr.cli._dependency_file_path", lambda: dep_file)
    
    res = _add_cpm_dependency("mylib", "https://github.com/user/mylib.git", git_tag="v1.0")
    assert res == 0
    
    contents = dep_file.read_text()
    assert 'project_add_cpm_dependency("mylib" "https://github.com/user/mylib.git" GIT_TAG "v1.0" )' in contents
