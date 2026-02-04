import json
import os
import sys
from pathlib import Path

import pytest

from pycmkr import cli as main


@pytest.fixture
def reset_config_manager():
    """Reset config_manager to defaults before each test."""
    original = main.config_manager
    main.config_manager = main.BuildConfigManager()
    yield
    main.config_manager = original


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
    assert main.config_manager.build_dir == Path("out")
    assert main.config_manager.default_test_target == "unit"
    assert main.config_manager.test_targets == ["unit", "integration"]
    assert main.config_manager.dependency_file == Path("deps.cmake")
    assert main.config_manager.dependency_local_function == "local_dep"
    assert main.config_manager.dependency_fetch_function == "fetch_dep"
    assert main.config_manager.project["name"] == "Demo"
    assert main.config_manager.project["main_target"] == "demo"
    assert main.config_manager.project["languages"] == ["CXX"]
    assert main.config_manager.project["main_sources"] == ["main.cpp"]


def test_apply_config_file_rejects_invalid_test_targets(tmp_path):
    path = tmp_path / "build_config.json"
    path.write_text(json.dumps({"test_targets": "nope"}), encoding="utf-8")

    result = main._apply_config_file(path)

    assert result == 1


def test_apply_config_file_rejects_top_level_main_target(tmp_path):
    path = tmp_path / "build_config.json"
    path.write_text(json.dumps({"main_target": "app"}), encoding="utf-8")

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

    assert main.config_manager.build_dir == Path("custom_build")
    assert main.config_manager.default_test_target == "unit_tests"
    assert main.config_manager.test_targets == ["unit_tests", "integration_tests"]
    assert main.config_manager.dependency_file == Path("deps.cmake")
    assert main.config_manager.dependency_local_function == "local_dep"
    assert main.config_manager.dependency_fetch_function == "fetch_dep"
    assert main.config_manager.project["main_target"] == "app"


def test_discover_config_path(tmp_path):
    root = tmp_path / "root"
    child = root / "child"
    grandchild = child / "grandchild"
    grandchild.mkdir(parents=True)
    config_path = root / "build_config.json"
    config_path.write_text("{}", encoding="utf-8")

    result = main._discover_config_path(grandchild, ["build_config.json"])

    assert result == config_path


def test_resolve_project_config_defaults_and_sanitizes_name(tmp_path, monkeypatch):
    project_root = tmp_path / "My Project!"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    main.config_manager.set_project({"name": "", "languages": [], "main_sources": []})

    result = main._resolve_project_config()

    assert result["name"] == "My_Project_"
    assert result["languages"] == ["C"]
    assert result["main_sources"] == ["main.c"]


def test_resolve_project_config_sanitizes_explicit_name():
    main.config_manager.set_project(
        {
            "name": "My Project!",
            "languages": ["C"],
            "main_sources": ["main.c"],
        }
    )

    result = main._resolve_project_config()

    assert result["name"] == "My_Project_"


def test_init_project_sanitizes_project_name(tmp_path):
    project_root = tmp_path / "root"
    project_root.mkdir()
    assert main._resolve_config_paths(project_root) == 0
    config = main._resolve_config()

    config_path = project_root / "build_config.json"
    result = main.init_project(config, config_path, project_root, "My Project!")

    assert result == 0
    assert json.loads(config_path.read_text(encoding="utf-8"))["project"]["name"] == (
        "My_Project_"
    )
    assert "project(My_Project_" in (project_root / "CMakeLists.txt").read_text(
        encoding="utf-8"
    )


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


def test_resolve_dependency_file_absolute_inside_root(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    dependency = project_root / "deps.cmake"

    resolved = main._resolve_dependency_file(project_root, dependency)

    assert resolved is not None
    candidate, cmake_path, cmake_is_abs = resolved
    expected_candidate = main._realpath_with_missing(dependency)
    assert candidate == expected_candidate
    assert cmake_path == expected_candidate
    assert cmake_is_abs is True


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

    result = main.run_executable(config, [])

    assert result == 1


def test_dependency_exists_ignores_comments_and_matches(tmp_path):
    deps_path = tmp_path / "dependencies.cmake"
    main.config_manager.set_dependency_file(deps_path)
    main.config_manager.set_dependency_local_function("local_dep")
    main.config_manager.set_dependency_fetch_function("fetch_dep")

    deps_path.write_text('# local_dep("raylib")\n', encoding="utf-8")

    assert main._dependency_exists("raylib") is False

    deps_path.write_text('local_dep("raylib")\n', encoding="utf-8")

    assert main._dependency_exists("raylib") is True

    deps_path.write_text(
        'fetch_dep("raylib", "https://example.com/raylib.git")\n', encoding="utf-8"
    )

    assert main._dependency_exists("raylib") is True


def test_add_dependency_rejects_newlines():
    assert main._add_dependency("bad\nname", None) == 2
    assert main._add_dependency("raylib", "https://example.com/\nraylib.git") == 2


def test_render_cmakelists_includes_dependency_and_project_options():
    project = {
        "name": "Demo",
        "languages": ["C", "CXX"],
        "min_cmake": "3.10",
        "c_standard": "23",
        "cxx_standard": "20",
        "main_target": "app",
        "main_sources": ["main.c"],
        "test_targets": [{"name": "unit_tests", "sources": ["unit_tests.c"]}],
        "include_dirs": ["include"],
        "definitions": ["USE_DEMO"],
        "compile_options": ["-Wall"],
        "link_libraries": ["m"],
        "extra_cmake_lines": ["# extra"],
    }

    rendered = main._render_cmakelists(
        project,
        Path("deps.cmake"),
        False,
        "local_dep",
        "fetch_dep",
    )

    assert "add_executable(app" in rendered
    assert "add_executable(unit_tests" in rendered
    assert 'include("${CMAKE_SOURCE_DIR}/deps.cmake" OPTIONAL)' in rendered
    assert "set(PROJECT_INCLUDE_DIRS" in rendered
    assert "set(PROJECT_DEFINITIONS" in rendered
    assert "set(PROJECT_COMPILE_OPTIONS" in rendered
    assert "set(PROJECT_LINK_LIBRARIES" in rendered
    assert "# extra" in rendered


def test_render_main_source_cpp():
    project = {"name": "Demo"}
    result = main._render_main_source(project, Path("main.cpp"))

    assert "#include <iostream>" in result
    assert "Hello from Demo." in result


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


def test_validate_non_empty_string_valid_string(reset_config_manager):
    code, value = main._validate_non_empty_string("test", "field")
    assert code == 0
    assert value == "test"


def test_validate_non_empty_string_strips_whitespace(reset_config_manager):
    code, value = main._validate_non_empty_string("  test  ", "field")
    assert code == 0
    assert value == "test"


def test_validate_non_empty_string_none_value(reset_config_manager):
    code, value = main._validate_non_empty_string(None, "field")
    assert code == 0
    assert value is None


def test_validate_non_empty_string_empty_string(reset_config_manager):
    code, value = main._validate_non_empty_string("", "field")
    assert code == 1
    assert value is None


def test_validate_non_empty_string_whitespace_only(reset_config_manager):
    code, value = main._validate_non_empty_string("  ", "field")
    assert code == 1
    assert value is None


def test_validate_non_empty_string_wrong_type_int(reset_config_manager):
    code, value = main._validate_non_empty_string(123, "field")
    assert code == 1
    assert value is None


def test_validate_non_empty_string_wrong_type_list(reset_config_manager):
    code, value = main._validate_non_empty_string(["test"], "field")
    assert code == 1
    assert value is None


def test_validate_string_list_valid(reset_config_manager):
    code, value = main._validate_string_list(["a", "b", "c"], "field")
    assert code == 0
    assert value == ["a", "b", "c"]


def test_validate_string_list_none_value(reset_config_manager):
    code, value = main._validate_string_list(None, "field")
    assert code == 0
    assert value is None


def test_validate_string_list_empty_allowed(reset_config_manager):
    code, value = main._validate_string_list([], "field", allow_empty=True)
    assert code == 0
    assert value == []


def test_validate_string_list_empty_not_allowed(reset_config_manager):
    code, value = main._validate_string_list([], "field", allow_empty=False)
    assert code == 1
    assert value is None


def test_validate_string_list_contains_empty_string(reset_config_manager):
    code, value = main._validate_string_list(["", "a"], "field")
    assert code == 1
    assert value is None


def test_validate_string_list_contains_whitespace_string(reset_config_manager):
    code, value = main._validate_string_list(["  "], "field")
    assert code == 1
    assert value is None


def test_validate_string_list_wrong_type_not_list(reset_config_manager):
    code, value = main._validate_string_list("not a list", "field")
    assert code == 1
    assert value is None


def test_validate_string_list_contains_int(reset_config_manager):
    code, value = main._validate_string_list(["a", 1], "field")
    assert code == 1
    assert value is None


def test_validate_standard_string_valid(reset_config_manager):
    code, value = main._validate_standard("23", "field")
    assert code == 0
    assert value == "23"


def test_validate_standard_int_valid(reset_config_manager):
    code, value = main._validate_standard(23, "field")
    assert code == 0
    assert value == "23"


def test_validate_standard_whitespace_string(reset_config_manager):
    code, value = main._validate_standard(" 23 ", "field")
    assert code == 0
    assert value == "23"


def test_validate_standard_none_not_allowed(reset_config_manager):
    code, value = main._validate_standard(None, "field", allow_none=False)
    assert code == 1
    assert value is None


def test_validate_standard_none_allowed(reset_config_manager):
    code, value = main._validate_standard(None, "field", allow_none=True)
    assert code == 0
    assert value is None


def test_validate_standard_empty_string(reset_config_manager):
    code, value = main._validate_standard("", "field")
    assert code == 1
    assert value is None


def test_validate_standard_wrong_type_list(reset_config_manager):
    code, value = main._validate_standard([], "field")
    assert code == 1
    assert value is None


def test_validate_standard_int_conversion_17(reset_config_manager):
    code, value = main._validate_standard(17, "field")
    assert code == 0
    assert value == "17"


def test_validate_optional_string_valid(reset_config_manager):
    code, value = main._validate_optional_string("foo", "field")
    assert code == 0
    assert value == "foo"


def test_validate_optional_string_none_value(reset_config_manager):
    code, value = main._validate_optional_string(None, "field")
    assert code == 0
    assert value is None


def test_validate_optional_string_empty_allowed(reset_config_manager):
    code, value = main._validate_optional_string("", "field")
    assert code == 0
    assert value == ""


def test_validate_optional_string_whitespace_allowed(reset_config_manager):
    code, value = main._validate_optional_string("  ", "field")
    assert code == 0
    assert value == "  "


def test_validate_optional_string_wrong_type(reset_config_manager):
    code, value = main._validate_optional_string(123, "field")
    assert code == 1
    assert value is None


def test_validate_test_target_valid(reset_config_manager):
    code, value = main._validate_test_target({"name": "test", "sources": ["test.c"]}, 0)
    assert code == 0
    assert value == {"name": "test", "sources": ["test.c"]}


def test_validate_test_target_missing_name(reset_config_manager):
    code, value = main._validate_test_target({"sources": ["test.c"]}, 0)
    assert code == 1
    assert value is None


def test_validate_test_target_missing_sources(reset_config_manager):
    code, value = main._validate_test_target({"name": "test"}, 0)
    assert code == 1
    assert value is None


def test_validate_test_target_invalid_name_type(reset_config_manager):
    code, value = main._validate_test_target({"name": 123, "sources": ["test.c"]}, 0)
    assert code == 1
    assert value is None


def test_validate_test_target_empty_name(reset_config_manager):
    code, value = main._validate_test_target({"name": "", "sources": ["test.c"]}, 0)
    assert code == 1
    assert value is None


def test_validate_test_target_empty_sources(reset_config_manager):
    code, value = main._validate_test_target({"name": "test", "sources": []}, 0)
    assert code == 1
    assert value is None


def test_validate_test_target_sources_contains_empty(reset_config_manager, capsys):
    code, value = main._validate_test_target({"name": "test", "sources": [""]}, 5)
    assert code == 1
    assert value is None
    captured = capsys.readouterr()
    assert "[5]" in captured.err


def test_validate_test_target_error_includes_index(reset_config_manager, capsys):
    code, value = main._validate_test_target({"name": "", "sources": ["test.c"]}, 2)
    assert code == 1
    assert value is None
    captured = capsys.readouterr()
    assert "[2]" in captured.err


def test_apply_build_level_config_valid_all_fields(reset_config_manager):
    data = {
        "build_dir": "out",
        "default_test_target": "unit",
        "test_targets": ["unit", "integration"],
        "dependency_file": "deps.cmake",
        "dependency_local_function": "local_dep",
        "dependency_fetch_function": "fetch_dep",
    }
    result = main._apply_build_level_config(data, main.config_manager)
    assert result == 0
    assert main.config_manager.build_dir == Path("out")
    assert main.config_manager.default_test_target == "unit"
    assert main.config_manager.test_targets == ["unit", "integration"]
    assert main.config_manager.dependency_file == Path("deps.cmake")
    assert main.config_manager.dependency_local_function == "local_dep"
    assert main.config_manager.dependency_fetch_function == "fetch_dep"


def test_apply_build_level_config_partial_fields(reset_config_manager):
    data = {"build_dir": "build"}
    result = main._apply_build_level_config(data, main.config_manager)
    assert result == 0
    assert main.config_manager.build_dir == Path("build")


def test_apply_build_level_config_invalid_build_dir(reset_config_manager):
    data = {"build_dir": ""}
    result = main._apply_build_level_config(data, main.config_manager)
    assert result == 1


def test_apply_build_level_config_invalid_test_targets_list(reset_config_manager):
    data = {"test_targets": "not a list"}
    result = main._apply_build_level_config(data, main.config_manager)
    assert result == 1


def test_apply_build_level_config_deprecated_main_target(reset_config_manager):
    data = {"main_target": "app"}
    result = main._apply_build_level_config(data, main.config_manager)
    assert result == 1


def test_validate_and_normalize_project_valid_all_fields(reset_config_manager):
    project = {
        "name": "Demo",
        "main_target": "demo",
        "languages": ["CXX"],
        "main_sources": ["main.cpp"],
        "include_dirs": ["include"],
        "definitions": ["DEBUG"],
        "compile_options": ["-Wall"],
        "link_libraries": ["m"],
        "min_cmake": "3.10",
        "c_standard": "23",
        "cxx_standard": "20",
        "extra_cmake_lines": ["# extra"],
        "test_targets": [{"name": "unit", "sources": ["unit.c"]}],
    }
    code, normalized = main._validate_and_normalize_project(project)
    assert code == 0
    assert normalized["name"] == "Demo"
    assert normalized["main_target"] == "demo"
    assert normalized["languages"] == ["CXX"]
    assert normalized["main_sources"] == ["main.cpp"]
    assert normalized["include_dirs"] == ["include"]
    assert normalized["definitions"] == ["DEBUG"]
    assert normalized["compile_options"] == ["-Wall"]
    assert normalized["link_libraries"] == ["m"]
    assert normalized["min_cmake"] == "3.10"
    assert normalized["c_standard"] == "23"
    assert normalized["cxx_standard"] == "20"
    assert normalized["extra_cmake_lines"] == ["# extra"]
    assert normalized["test_targets"] == [{"name": "unit", "sources": ["unit.c"]}]


def test_validate_and_normalize_project_partial_fields(reset_config_manager):
    project = {
        "name": "Demo",
        "main_target": "demo",
        "languages": ["CXX"],
        "main_sources": ["main.cpp"],
    }
    code, normalized = main._validate_and_normalize_project(project)
    assert code == 0
    assert normalized["name"] == "Demo"
    assert normalized["main_target"] == "demo"
    assert normalized["languages"] == ["CXX"]
    assert normalized["main_sources"] == ["main.cpp"]
    assert "include_dirs" not in normalized or normalized.get("include_dirs") is None


def test_validate_and_normalize_project_invalid_name(reset_config_manager):
    project = {
        "name": "",
        "main_target": "demo",
        "languages": ["CXX"],
        "main_sources": ["main.cpp"],
    }
    code, normalized = main._validate_and_normalize_project(project)
    assert code == 1
    assert normalized == {}


def test_validate_and_normalize_project_empty_languages(reset_config_manager):
    project = {
        "name": "Demo",
        "main_target": "demo",
        "languages": [],
        "main_sources": ["main.cpp"],
    }
    code, normalized = main._validate_and_normalize_project(project)
    assert code == 1
    assert normalized == {}


def test_validate_and_normalize_project_invalid_test_target_entry(reset_config_manager):
    project = {
        "name": "Demo",
        "main_target": "demo",
        "languages": ["CXX"],
        "main_sources": ["main.cpp"],
        "test_targets": [{"name": "", "sources": ["unit.c"]}],
    }
    code, normalized = main._validate_and_normalize_project(project)
    assert code == 1
    assert normalized == {}


def test_validate_and_normalize_project_extra_cmake_lines_allow_empty(
    reset_config_manager,
):
    project = {
        "name": "Demo",
        "main_target": "demo",
        "languages": ["CXX"],
        "main_sources": ["main.cpp"],
        "extra_cmake_lines": [""],
    }
    code, normalized = main._validate_and_normalize_project(project)
    assert code == 0
    assert normalized["extra_cmake_lines"] == [""]


def test_cmake_escape_escapes_dangerous_characters():
    assert main._cmake_escape('test"quote') == 'test\\"quote'
    assert main._cmake_escape("test\\slash") == "test\\\\slash"
    assert main._cmake_escape("test$dollar") == "test\\$dollar"
    assert main._cmake_escape("test;semicolon") == "test\\;semicolon"
    assert main._cmake_escape("test#hash") == "test\\#hash"


def test_cmake_escape_combines_multiple_escapes():
    result = main._cmake_escape('test\\"$;#')
    expected = 'test\\\\\\"\\$\\;\\#'
    assert result == expected


def test_validate_git_url_accepts_valid_https():
    is_valid, error_msg = main._validate_git_url("https://github.com/user/repo.git")
    assert is_valid is True
    assert error_msg is None


def test_validate_git_url_accepts_valid_ssh():
    is_valid, error_msg = main._validate_git_url("git@github.com:user/repo.git")
    assert is_valid is True
    assert error_msg is None


def test_validate_git_url_rejects_http():
    is_valid, error_msg = main._validate_git_url("http://github.com/user/repo.git")
    assert is_valid is False
    assert "HTTPS" in error_msg


def test_validate_git_url_rejects_semicolon():
    is_valid, error_msg = main._validate_git_url(
        "https://github.com/user/repo.git;rm -rf /"
    )
    assert is_valid is False
    assert ";" in error_msg


def test_validate_git_url_rejects_hash():
    is_valid, error_msg = main._validate_git_url(
        "https://github.com/user/repo.git#evil"
    )
    assert is_valid is False
    assert "#" in error_msg


def test_validate_git_url_rejects_braces():
    is_valid, error_msg = main._validate_git_url(
        "https://github.com/user/repo.git${CMD}"
    )
    assert is_valid is False
    assert "{" in error_msg or "variable expansion" in error_msg


def test_validate_git_url_rejects_backticks():
    is_valid, error_msg = main._validate_git_url(
        "https://github.com/user/repo.git`cmd`"
    )
    assert is_valid is False
    assert "`" in error_msg


def test_validate_git_url_rejects_pipe():
    is_valid, error_msg = main._validate_git_url("https://github.com/user/repo.git|cmd")
    assert is_valid is False
    assert "|" in error_msg


def test_validate_git_url_rejects_github_url_without_git():
    is_valid, error_msg = main._validate_git_url("https://github.com/user/repo")
    assert is_valid is False
    assert "format" in error_msg.lower()


def test_add_dependency_rejects_malformed_url(tmp_path):
    main.config_manager.set_project_root(tmp_path)
    main.config_manager.set_build_dir(tmp_path / "build")
    main.config_manager.set_dependency_file(tmp_path / "dependencies.cmake")
    main.config_manager.set_dependency_fetch_function("fetch_dep")

    result = main._add_dependency("test", "https://github.com/user/repo")
    assert result == 2


def test_add_dependency_with_tag_parameter(tmp_path):
    main.config_manager.set_project_root(tmp_path)
    main.config_manager.set_build_dir(tmp_path / "build")
    main.config_manager.set_dependency_file(tmp_path / "dependencies.cmake")
    main.config_manager.set_dependency_fetch_function("fetch_dep")

    result = main._add_dependency(
        "test", "https://github.com/user/repo.git", git_tag="v1.0.0"
    )
    assert result == 0

    deps_file = tmp_path / "dependencies.cmake"
    assert deps_file.exists()
    content = deps_file.read_text(encoding="utf-8")
    assert 'fetch_dep("test" "https://github.com/user/repo.git" "v1.0.0")' in content


def test_add_dependency_rejects_tag_with_semicolon():
    result = main._add_dependency("test", "https://github.com/user/repo.git", "v1.0;rm")
    assert result == 2


def test_add_dependency_rejects_tag_with_hash():
    result = main._add_dependency(
        "test", "https://github.com/user/repo.git", "v1.0#evil"
    )
    assert result == 2


def test_add_dependency_rejects_tag_with_quote():
    result = main._add_dependency(
        "test", "https://github.com/user/repo.git", 'v1.0"evil'
    )
    assert result == 2


def test_render_cmakelists_fetch_function_with_tag():
    project = {
        "name": "Demo",
        "languages": ["C"],
        "min_cmake": "3.20",
        "main_target": "app",
        "main_sources": ["main.c"],
        "test_targets": [],
        "include_dirs": [],
        "definitions": [],
        "compile_options": [],
        "link_libraries": [],
        "extra_cmake_lines": [],
    }

    rendered = main._render_cmakelists(
        project, Path("deps.cmake"), False, "local_dep", "fetch_dep"
    )

    assert "function(fetch_dep name git_url [git_tag])" in rendered
    assert 'if(DEFINED git_tag AND NOT "${git_tag}" STREQUAL "")' in rendered
    assert "GIT_TAG ${git_tag}" in rendered
    assert "GIT_TAG HEAD" in rendered
