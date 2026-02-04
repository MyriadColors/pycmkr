#!/usr/bin/env python3
"""Build orchestration helper for simple C/C++ CMake projects."""

import glob
import importlib.metadata
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import (
    Any,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
)


DEFAULT_BUILD_DIR = Path("build")
DEFAULT_DEPENDENCY_FILE = Path("dependencies.cmake")
DEFAULT_DEPENDENCY_LOCAL_FUNCTION = "project_add_local_dependency"
DEFAULT_DEPENDENCY_FETCH_FUNCTION = "project_add_fetch_dependency"
DEFAULT_PROJECT_NAME = "Project"
DEFAULT_PROJECT_LANGUAGES = ["C"]
DEFAULT_MIN_CMAKE = "3.20"
DEFAULT_C_STANDARD = "23"
DEFAULT_MAIN_TARGET = "main"
DEFAULT_MAIN_SOURCE = "main.c"
DEFAULT_CONFIG_FILE_NAME = "build_config.json"
DEFAULT_CMAKE_GENERATOR = "Ninja"
CMAKE_C_STANDARD_VAR = "CMAKE_C_STANDARD"
CMAKE_CXX_STANDARD_VAR = "CMAKE_CXX_STANDARD"
CMAKE_CACHE_FILE_NAME = "CMakeCache.txt"
CMAKE_C_COMPILER_PREFIX = "CMAKE_C_COMPILER:"
DEFAULT_EXECUTABLE_SUFFIX = ".exe"
WINDOWS_BUILD_CONFIG_DIRS = ("Debug", "Release", "RelWithDebInfo", "MinSizeRel")


def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def exe_suffix() -> str:
    suffix = sysconfig.get_config_var("EXE_SUFFIX")
    if suffix:
        return suffix
    return DEFAULT_EXECUTABLE_SUFFIX if is_windows() else ""


def exe_name(target: str) -> str:
    suffix = exe_suffix()
    return f"{target}{suffix}" if suffix else target


class ProjectTestTarget(TypedDict):
    name: str
    sources: list[str]


class ProjectConfig(TypedDict):
    name: str
    languages: list[str]
    min_cmake: str
    c_standard: Optional[str]
    cxx_standard: Optional[str]
    main_target: str
    main_sources: list[str]
    test_targets: list[ProjectTestTarget]
    include_dirs: list[str]
    definitions: list[str]
    compile_options: list[str]
    link_libraries: list[str]
    extra_cmake_lines: list[str]


class ProjectConfigOverrides(TypedDict, total=False):
    name: str
    languages: list[str]
    min_cmake: str
    c_standard: Optional[str]
    cxx_standard: Optional[str]
    main_target: str
    main_sources: list[str]
    test_targets: list[ProjectTestTarget]
    include_dirs: list[str]
    definitions: list[str]
    compile_options: list[str]
    link_libraries: list[str]
    extra_cmake_lines: list[str]


class BuildConfig(TypedDict):
    build_dir: Path
    default_test_target: Optional[str]
    test_targets: list[str]
    dependency_file: Path
    dependency_local_function: str
    dependency_fetch_function: str
    project: Optional[ProjectConfigOverrides]
    project_root: Optional[Path]
    build_dir_resolved: Optional[Path]
    dependency_file_resolved: Optional[Path]
    dependency_file_cmake: Optional[Path]
    dependency_file_cmake_abs: bool
    config_path: Optional[Path]


class WriteConfig(TypedDict):
    build_dir: Path
    default_test_target: Optional[str]
    test_targets: list[str]
    dependency_file: Path
    dependency_local_function: str
    dependency_fetch_function: str
    project: ProjectConfig


class ResolvedBuildConfig(TypedDict):
    project_root: Path
    build_dir: Path
    default_test_target: Optional[str]
    test_targets: list[str]
    dependency_file: Path
    dependency_file_cmake: Path
    dependency_file_cmake_abs: bool
    dependency_local_function: str
    dependency_fetch_function: str
    project: ProjectConfig


type ValidationResult[T] = tuple[int, Optional[T]]
type StringValidationResult = tuple[int, Optional[str]]
type ListValidationResult = tuple[int, Optional[list[str]]]
type ProjectValidationResult = tuple[int, ProjectConfigOverrides]
type TestTargetValidationResult = tuple[int, Optional[ProjectTestTarget]]
type PathLike = Path | str
type OptionalPathLike = PathLike | None


class BuildConfigManager:
    def __init__(
        self,
        build_dir: Path = DEFAULT_BUILD_DIR,
        default_test_target: Optional[str] = None,
        test_targets: Optional[list[str]] = None,
        dependency_file: Path = DEFAULT_DEPENDENCY_FILE,
        dependency_local_function: str = DEFAULT_DEPENDENCY_LOCAL_FUNCTION,
        dependency_fetch_function: str = DEFAULT_DEPENDENCY_FETCH_FUNCTION,
        project: Optional[ProjectConfigOverrides] = None,
        project_root: Optional[Path] = None,
        build_dir_resolved: Optional[Path] = None,
        dependency_file_resolved: Optional[Path] = None,
        dependency_file_cmake: Optional[Path] = None,
        dependency_file_cmake_abs: bool = False,
        config_path: Optional[Path] = None,
    ):
        self._build_dir = build_dir
        self._default_test_target = default_test_target
        self._test_targets = test_targets if test_targets is not None else []
        self._dependency_file = dependency_file
        self._dependency_local_function = dependency_local_function
        self._dependency_fetch_function = dependency_fetch_function
        self._project: ProjectConfigOverrides = project if project is not None else {}
        self._project_root = project_root
        self._build_dir_resolved = build_dir_resolved
        self._dependency_file_resolved = dependency_file_resolved
        self._dependency_file_cmake = dependency_file_cmake
        self._dependency_file_cmake_abs = dependency_file_cmake_abs
        self._config_path = config_path

    @property
    def build_dir(self) -> Path:
        return self._build_dir

    @property
    def default_test_target(self) -> Optional[str]:
        return self._default_test_target

    @property
    def test_targets(self) -> list[str]:
        return self._test_targets

    @property
    def dependency_file(self) -> Path:
        return self._dependency_file

    @property
    def dependency_local_function(self) -> str:
        return self._dependency_local_function

    @property
    def dependency_fetch_function(self) -> str:
        return self._dependency_fetch_function

    @property
    def project(self) -> ProjectConfigOverrides:
        return self._project

    @property
    def project_root(self) -> Optional[Path]:
        return self._project_root

    @property
    def build_dir_resolved(self) -> Optional[Path]:
        return self._build_dir_resolved

    @property
    def dependency_file_resolved(self) -> Optional[Path]:
        return self._dependency_file_resolved

    @property
    def dependency_file_cmake(self) -> Optional[Path]:
        return self._dependency_file_cmake

    @property
    def dependency_file_cmake_abs(self) -> bool:
        return self._dependency_file_cmake_abs

    @property
    def config_path(self) -> Optional[Path]:
        return self._config_path

    def set_build_dir(self, value: Path) -> None:
        self._build_dir = value

    def set_default_test_target(self, value: Optional[str]) -> None:
        self._default_test_target = value

    def set_test_targets(self, value: list[str]) -> None:
        self._test_targets = value

    def set_dependency_file(self, value: Path) -> None:
        self._dependency_file = value

    def set_dependency_local_function(self, value: str) -> None:
        self._dependency_local_function = value

    def set_dependency_fetch_function(self, value: str) -> None:
        self._dependency_fetch_function = value

    def set_project(self, value: ProjectConfigOverrides) -> None:
        self._project = value

    def set_project_root(self, value: Path) -> None:
        self._project_root = value

    def set_build_dir_resolved(self, value: Optional[Path]) -> None:
        self._build_dir_resolved = value

    def set_dependency_file_resolved(self, value: Optional[Path]) -> None:
        self._dependency_file_resolved = value

    def set_dependency_file_cmake(self, value: Optional[Path]) -> None:
        self._dependency_file_cmake = value

    def set_dependency_file_cmake_abs(self, value: bool) -> None:
        self._dependency_file_cmake_abs = value

    def set_config_path(self, value: Optional[Path]) -> None:
        self._config_path = value

    def to_dict(self) -> BuildConfig:
        data: BuildConfig = {
            "build_dir": self._build_dir,
            "default_test_target": self._default_test_target,
            "test_targets": self._test_targets,
            "dependency_file": self._dependency_file,
            "dependency_local_function": self._dependency_local_function,
            "dependency_fetch_function": self._dependency_fetch_function,
            "project": self._project,
            "project_root": self._project_root,
            "build_dir_resolved": self._build_dir_resolved,
            "dependency_file_resolved": self._dependency_file_resolved,
            "dependency_file_cmake": self._dependency_file_cmake,
            "dependency_file_cmake_abs": self._dependency_file_cmake_abs,
            "config_path": self._config_path,
        }
        return data

    @classmethod
    def from_dict(cls, config: BuildConfig) -> "BuildConfigManager":
        return cls(
            build_dir=config["build_dir"],
            default_test_target=config["default_test_target"],
            test_targets=config["test_targets"],
            dependency_file=config["dependency_file"],
            dependency_local_function=config["dependency_local_function"],
            dependency_fetch_function=config["dependency_fetch_function"],
            project=config["project"],
            project_root=config["project_root"],
            build_dir_resolved=config["build_dir_resolved"],
            dependency_file_resolved=config["dependency_file_resolved"],
            dependency_file_cmake=config["dependency_file_cmake"],
            dependency_file_cmake_abs=config["dependency_file_cmake_abs"],
            config_path=config["config_path"],
        )


def info(message: str) -> None:
    """Print a standard informational message."""
    print(f"[pycmkr] {message}")


def error(message: str) -> None:
    """Print a standardized error message to stderr."""
    print(f"error: {message}", file=sys.stderr)


def run_cmd(
    cmd: Sequence[str],
    cwd: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """Run a subprocess command and return the exit code."""
    print("+", " ".join(shlex.quote(part) for part in cmd))
    try:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        error(f"command failed with exit code {exc.returncode}")
        return exc.returncode
    return 0


def _normalize_path_spelling(path: PathLike) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _resolve_path(path: PathLike) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path).absolute()


def _expand_and_normalize(path: PathLike, base_dir: Path) -> Tuple[Path, bool]:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate, True
    return base_dir / candidate, False


def _realpath_with_missing(path: PathLike) -> Path:
    path = Path(path)
    missing_parts = []
    current = path
    while not current.exists():
        missing_parts.append(current.name)
        parent = current.parent
        if parent == current:
            break
        current = parent
    real_parent = _resolve_path(current)
    for name in reversed(missing_parts):
        real_parent = real_parent / name
    return real_parent


def _path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _cmake_path(path: Path) -> str:
    return path.as_posix()


# Project configuration manager
config_manager = BuildConfigManager()


def _sanitize_project_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    return cleaned or DEFAULT_PROJECT_NAME


def _default_project_config() -> ProjectConfig:
    return {
        "name": DEFAULT_PROJECT_NAME,
        "languages": list(DEFAULT_PROJECT_LANGUAGES),
        "min_cmake": DEFAULT_MIN_CMAKE,
        "c_standard": DEFAULT_C_STANDARD,
        "cxx_standard": None,
        "main_target": DEFAULT_MAIN_TARGET,
        "main_sources": [DEFAULT_MAIN_SOURCE],
        "test_targets": [],
        "include_dirs": [],
        "definitions": [],
        "compile_options": [],
        "link_libraries": [],
        "extra_cmake_lines": [],
    }


def _resolve_project_config(
    config_manager: Optional[BuildConfigManager] = None,
) -> ProjectConfig:
    manager = (
        config_manager if config_manager is not None else globals()["config_manager"]
    )
    defaults = _default_project_config()
    project = manager.project
    merged: ProjectConfig = {
        "name": project.get("name", defaults["name"]),
        "languages": project.get("languages", defaults["languages"]),
        "min_cmake": project.get("min_cmake", defaults["min_cmake"]),
        "c_standard": project.get("c_standard", defaults["c_standard"]),
        "cxx_standard": project.get("cxx_standard", defaults["cxx_standard"]),
        "main_target": project.get("main_target", defaults["main_target"]),
        "main_sources": project.get("main_sources", defaults["main_sources"]),
        "test_targets": project.get("test_targets", defaults["test_targets"]),
        "include_dirs": project.get("include_dirs", defaults["include_dirs"]),
        "definitions": project.get("definitions", defaults["definitions"]),
        "compile_options": project.get("compile_options", defaults["compile_options"]),
        "link_libraries": project.get("link_libraries", defaults["link_libraries"]),
        "extra_cmake_lines": project.get(
            "extra_cmake_lines", defaults["extra_cmake_lines"]
        ),
    }
    if not project.get("name"):
        merged["name"] = _sanitize_project_name(Path.cwd().name)
    else:
        merged["name"] = _sanitize_project_name(merged["name"])
    if not project.get("main_sources"):
        merged["main_sources"] = defaults["main_sources"]
    if not project.get("languages"):
        merged["languages"] = defaults["languages"]
    return merged


def _resolve_config(
    config_manager: Optional[BuildConfigManager] = None,
) -> ResolvedBuildConfig:
    manager = (
        config_manager if config_manager is not None else globals()["config_manager"]
    )
    project = _resolve_project_config(manager)
    if manager.project_root is None:
        raise RuntimeError("project root is not set; call _resolve_config_paths first")
    if manager.dependency_file_cmake is None:
        raise RuntimeError(
            "dependency file path is not set; call _resolve_config_paths first"
        )
    return {
        "project_root": manager.project_root,
        "build_dir": manager.build_dir_resolved or manager.build_dir,
        "default_test_target": manager.default_test_target,
        "test_targets": manager.test_targets,
        "dependency_file": manager.dependency_file_resolved or manager.dependency_file,
        "dependency_file_cmake": manager.dependency_file_cmake,
        "dependency_file_cmake_abs": manager.dependency_file_cmake_abs,
        "dependency_local_function": manager.dependency_local_function,
        "dependency_fetch_function": manager.dependency_fetch_function,
        "project": project,
    }


def _validate_non_empty_string(value: Any, field_name: str) -> StringValidationResult:
    """Validate value is a non-empty string.

    Returns (0, stripped_string) if valid, (0, None) if value is None,
    or (1, None) if invalid with error message printed.
    Strips whitespace (Option A).
    """
    if value is None:
        return (0, None)
    if isinstance(value, str) and value.strip():
        return (0, value.strip())
    error(f"config {field_name} must be a non-empty string")
    return (1, None)


def _validate_string_list(
    value: Any, field_name: str, allow_empty: bool = True
) -> ListValidationResult:
    """Validate value is a list of non-empty strings.

    Returns (0, list) if valid, (0, None) if value is None,
    or (1, None) if invalid. Does NOT strip strings (Option C).
    """
    if value is None:
        return (0, None)
    if not isinstance(value, list):
        error(f"config {field_name} must be a list of strings")
        return (1, None)
    normalized = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            error(f"config {field_name} must be a list of non-empty strings")
            return (1, None)
        normalized.append(entry)
    if not normalized and not allow_empty:
        error(f"config {field_name} must not be empty")
        return (1, None)
    return (0, normalized)


def _validate_standard(
    value: Any, field_name: str, allow_none: bool = False
) -> StringValidationResult:
    """Validate C/C++ standard (string, int, or None).

    Converts int to string, strips whitespace (Option C - normalize standards).
    Returns (0, string) or (0, None) if valid, (1, None) if invalid.
    """
    if value is None:
        if allow_none:
            return (0, None)
        error(f"config {field_name} must be a string or integer")
        return (1, None)
    if isinstance(value, int):
        return (0, str(value))
    if isinstance(value, str) and value.strip():
        return (0, value.strip())
    error(f"config {field_name} must be a string or integer")
    return (1, None)


def _validate_optional_string(value: Any, field_name: str) -> StringValidationResult:
    """Validate value is a string (may be empty).

    Returns (0, string) if valid, (0, None) if value is None,
    or (1, None) if invalid. Does NOT strip (Option C).
    """
    if value is None:
        return (0, None)
    if isinstance(value, str):
        return (0, value)
    error(f"config {field_name} must be a string")
    return (1, None)


def _validate_test_target(entry: Any, index: int) -> TestTargetValidationResult:
    """Validate a single test target entry from config.

    Validates entry is dict with 'name' and 'sources' fields.
    Uses _validate_non_empty_string and _validate_string_list.
    Returns (0, test_target_dict) if valid, (1, None) if invalid.
    Error messages include index number.
    """
    if not isinstance(entry, dict):
        error("config project.test_targets entries must be objects")
        return (1, None)
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        error(f"config project.test_targets[{index}].name must be a non-empty string")
        return (1, None)
    sources = entry.get("sources")
    if sources is None:
        error(f"config project.test_targets[{index}].sources is required")
        return (1, None)
    result, validated_sources = _validate_string_list(
        sources, f"project.test_targets[{index}].sources", allow_empty=False
    )
    if result or validated_sources is None:
        return (1, None)
    return (0, {"name": name, "sources": validated_sources})


def _apply_string_list_field(
    project: dict,
    normalized: ProjectConfigOverrides,
    key: str,
    field_name: str,
    allow_empty: bool = True,
) -> int:
    value = project.get(key)
    result, validated_list = _validate_string_list(
        value, field_name, allow_empty=allow_empty
    )
    if result:
        return 1
    if validated_list is not None:
        normalized[key] = validated_list
    return 0


def _apply_optional_string_list_field(
    project: dict,
    normalized: ProjectConfigOverrides,
    key: str,
    field_name: str,
) -> int:
    value = project.get(key)
    if value is None:
        return 0
    if not isinstance(value, list):
        error(f"config {field_name} must be a list of strings")
        return 1
    normalized_list = []
    for entry in value:
        result, validated = _validate_optional_string(entry, field_name)
        if result:
            return 1
        if validated is not None:
            normalized_list.append(validated)
    normalized[key] = normalized_list
    return 0


def _apply_build_level_config(data: dict, manager: BuildConfigManager) -> int:
    """Validate and apply top-level build configuration fields.

    Handles: build_dir, default_test_target, test_targets,
             dependency_file, dependency_local_function,
             dependency_fetch_function, deprecated main_target.

    Returns 0 on success, 1 on validation error.
    """
    if "main_target" in data:
        project = data.get("project")
        if isinstance(project, dict) and "main_target" in project:
            error(
                "config has both main_target and project.main_target; "
                "keep only project.main_target"
            )
            return 1
        error("config main_target is not supported; use project.main_target")
        return 1

    build_dir = data.get("build_dir")
    result, validated = _validate_non_empty_string(build_dir, "build_dir")
    if result:
        return 1
    if validated is not None:
        manager.set_build_dir(Path(validated))

    test_target = data.get("default_test_target")
    result, validated = _validate_non_empty_string(test_target, "default_test_target")
    if result:
        return 1
    if validated is not None:
        manager.set_default_test_target(validated)

    test_targets = data.get("test_targets")
    result, validated_list = _validate_string_list(test_targets, "test_targets")
    if result:
        return 1
    if validated_list is not None:
        manager.set_test_targets(validated_list)

    dependency_file = data.get("dependency_file")
    result, validated = _validate_non_empty_string(dependency_file, "dependency_file")
    if result:
        return 1
    if validated is not None:
        manager.set_dependency_file(Path(validated))

    local_fn = data.get("dependency_local_function")
    result, validated = _validate_non_empty_string(
        local_fn, "dependency_local_function"
    )
    if result:
        return 1
    if validated is not None:
        manager.set_dependency_local_function(validated)

    fetch_fn = data.get("dependency_fetch_function")
    result, validated = _validate_non_empty_string(
        fetch_fn, "dependency_fetch_function"
    )
    if result:
        return 1
    if validated is not None:
        manager.set_dependency_fetch_function(validated)

    return 0


def _validate_and_normalize_project(project: dict) -> ProjectValidationResult:
    """Validate and normalize project configuration.

    Validates all project fields using helper functions.
    Returns (0, normalized_dict) on success, (1, {}) on error.
    """
    normalized: ProjectConfigOverrides = {}

    name = project.get("name")
    result, validated = _validate_non_empty_string(name, "project.name")
    if result:
        return (1, {})
    if validated is not None:
        normalized["name"] = validated

    languages = project.get("languages")
    result, validated_list = _validate_string_list(
        languages, "project.languages", allow_empty=False
    )
    if result:
        return (1, {})
    if validated_list is not None:
        normalized["languages"] = validated_list

    min_cmake = project.get("min_cmake")
    if min_cmake is not None:
        result, validated = _validate_standard(
            min_cmake, "project.min_cmake", allow_none=False
        )
        if result or validated is None:
            return (1, {})
        normalized["min_cmake"] = validated

    c_standard = project.get("c_standard")
    if "c_standard" in project:
        result, validated = _validate_standard(
            c_standard, "project.c_standard", allow_none=True
        )
        if result:
            return (1, {})
        normalized["c_standard"] = validated

    cxx_standard = project.get("cxx_standard")
    if "cxx_standard" in project:
        result, validated = _validate_standard(
            cxx_standard, "project.cxx_standard", allow_none=True
        )
        if result:
            return (1, {})
        normalized["cxx_standard"] = validated

    main_target = project.get("main_target")
    result, validated = _validate_non_empty_string(main_target, "project.main_target")
    if result:
        return (1, {})
    if validated is not None:
        normalized["main_target"] = validated

    result = _apply_string_list_field(
        project,
        normalized,
        "main_sources",
        "project.main_sources",
        allow_empty=False,
    )
    if result:
        return (1, {})

    test_targets = project.get("test_targets")
    if test_targets is not None:
        if not isinstance(test_targets, list):
            error("config project.test_targets must be a list of objects")
            return (1, {})
        normalized_tests: list[ProjectTestTarget] = []
        for index, entry in enumerate(test_targets):
            result, validated_target = _validate_test_target(entry, index)
            if result or validated_target is None:
                return (1, {})
            normalized_tests.append(validated_target)
        normalized["test_targets"] = normalized_tests

    result = _apply_string_list_field(
        project, normalized, "include_dirs", "project.include_dirs"
    )
    if result:
        return (1, {})

    result = _apply_string_list_field(
        project, normalized, "definitions", "project.definitions"
    )
    if result:
        return (1, {})

    result = _apply_string_list_field(
        project, normalized, "compile_options", "project.compile_options"
    )
    if result:
        return (1, {})

    result = _apply_string_list_field(
        project, normalized, "link_libraries", "project.link_libraries"
    )
    if result:
        return (1, {})

    result = _apply_optional_string_list_field(
        project, normalized, "extra_cmake_lines", "project.extra_cmake_lines"
    )
    if result:
        return (1, {})

    return (0, normalized)


def _apply_config_file(path: Path) -> int:
    """Load and validate a JSON config file into config_manager."""
    manager = globals()["config_manager"]
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        error(f"failed to read config file {path}: {exc}")
        return 1
    try:
        data = json.loads(contents)
    except json.JSONDecodeError as exc:
        error(f"invalid JSON in {path}: {exc}")
        return 1
    if not isinstance(data, dict):
        error(f"config file {path} must contain a JSON object")
        return 1

    result = _apply_build_level_config(data, manager)
    if result:
        return 1

    project = data.get("project")
    if project is not None:
        result, normalized = _validate_and_normalize_project(project)
        if result or not normalized:
            return 1
        current = manager.project or {}
        current.update(normalized)
        manager.set_project(current)

    return 0


def _apply_env_overrides() -> None:
    manager = globals()["config_manager"]
    build_dir_override = os.environ.get("BUILD_DIR")
    if build_dir_override:
        manager.set_build_dir(Path(build_dir_override))
    main_target_override = os.environ.get("MAIN_TARGET")
    if main_target_override:
        current = manager.project or {}
        current["main_target"] = main_target_override
        manager.set_project(current)
    test_target_override = os.environ.get("TEST_TARGET")
    if test_target_override:
        manager.set_default_test_target(test_target_override)
    test_targets_override = os.environ.get("TEST_TARGETS")
    if test_targets_override:
        manager.set_test_targets(
            [
                entry.strip()
                for entry in test_targets_override.split(",")
                if entry.strip()
            ]
        )
    dependency_file_override = os.environ.get("DEPENDENCY_FILE")
    if dependency_file_override:
        manager.set_dependency_file(Path(dependency_file_override))
    local_fn_override = os.environ.get("DEPENDENCY_LOCAL_FUNCTION")
    if local_fn_override:
        manager.set_dependency_local_function(local_fn_override)
    fetch_fn_override = os.environ.get("DEPENDENCY_FETCH_FUNCTION")
    if fetch_fn_override:
        manager.set_dependency_fetch_function(fetch_fn_override)


def _discover_config_path(start_dir: Path, names: Sequence[str]) -> Optional[Path]:
    current = Path(start_dir).resolve()
    while True:
        for name in names:
            candidate = current / name
            if candidate.exists():
                return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _resolve_project_root(config_path: OptionalPathLike) -> Path:
    if not config_path:
        return _realpath_with_missing(Path.cwd())
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    return _realpath_with_missing(config_path.parent)


def _resolve_dependency_file(
    project_root: Path, dependency_file: PathLike
) -> Optional[Tuple[Path, Path, bool]]:
    candidate, cmake_is_abs = _expand_and_normalize(dependency_file, project_root)
    cmake_path = None

    project_root_real = _realpath_with_missing(project_root)
    candidate_real = _realpath_with_missing(candidate)
    if not _path_is_within(candidate_real, project_root_real):
        error(
            f"dependency_file must resolve within {project_root_real}; got {candidate}"
        )
        return None

    if cmake_is_abs:
        cmake_path = candidate_real
    else:
        cmake_path = candidate_real.relative_to(project_root_real)

    return candidate_real, cmake_path, cmake_is_abs


def _resolve_config_paths(
    project_root: Path, config_manager: Optional[BuildConfigManager] = None
) -> int:
    """Populate resolved paths for the current configuration."""
    manager = (
        config_manager if config_manager is not None else globals()["config_manager"]
    )
    manager.set_project_root(project_root)

    build_dir, _ = _expand_and_normalize(manager.build_dir, project_root)
    manager.set_build_dir_resolved(build_dir)

    resolved = _resolve_dependency_file(project_root, manager.dependency_file)
    if not resolved:
        return 1
    dependency_file, cmake_path, cmake_is_abs = resolved
    manager.set_dependency_file_resolved(dependency_file)
    manager.set_dependency_file_cmake(cmake_path)
    manager.set_dependency_file_cmake_abs(cmake_is_abs)
    return 0


def _config_for_write(
    project_override: Optional[ProjectConfigOverrides] = None,
    config_manager: Optional[BuildConfigManager] = None,
) -> WriteConfig:
    manager = (
        config_manager if config_manager is not None else globals()["config_manager"]
    )
    project = _resolve_project_config(manager)
    if project_override:
        project.update(project_override)
    return {
        "build_dir": manager.build_dir,
        "default_test_target": manager.default_test_target,
        "test_targets": manager.test_targets,
        "dependency_file": manager.dependency_file,
        "dependency_local_function": manager.dependency_local_function,
        "dependency_fetch_function": manager.dependency_fetch_function,
        "project": project,
    }


def build_dir() -> Path:
    manager = globals()["config_manager"]
    return manager.build_dir_resolved or manager.build_dir


def _is_dangerous_delete_target(path: PathLike) -> bool:
    resolved = _resolve_path(path)
    if resolved == Path(resolved.anchor):
        return True
    if resolved == _resolve_path(Path.home()):
        return True
    project_root = globals()["config_manager"].project_root
    if project_root:
        if resolved == _resolve_path(project_root):
            return True
    return False


def clean_build_dir() -> int:
    """Remove the build directory if it is safe to do so."""
    path = build_dir()
    project_root = globals()["config_manager"].project_root
    if not project_root:
        error("project root is not set; refusing to remove build dir")
        return 1
    resolved_path = _realpath_with_missing(path)
    resolved_root = _realpath_with_missing(project_root)
    if not _path_is_within(resolved_path, resolved_root):
        error(f"refusing to remove build dir outside project root: {path}")
        return 1
    if path.exists():
        if _is_dangerous_delete_target(path):
            error(f"refusing to remove unsafe build dir at {path}")
            return 1
        if not path.is_dir():
            error(f"build dir path is not a directory: {path}")
            return 1
        info(f"removing {path}")
        shutil.rmtree(path)
        return 0
    else:
        info(f"nothing to clean at {path}")
    return 0


# CMake/Ninja backend adapter.
def cmake_configure(compiler: Optional[str] = None) -> int:
    """Run CMake configure for the current project."""
    info("configuring build directory")
    env = None
    if compiler:
        info(f"using compiler {compiler}")
        env = os.environ.copy()
        env["CC"] = compiler
    generator = _cmake_generator()
    command = [
        "cmake",
        "-S",
        str(globals()["config_manager"].project_root or Path.cwd()),
        "-B",
        str(build_dir()),
    ]
    if generator:
        command.extend(["-G", generator])
    return run_cmd(command, env=env)


def cmake_build() -> int:
    """Build the default target."""
    info("building")
    return run_cmd(["cmake", "--build", str(build_dir())])


def cmake_build_target(target: str) -> int:
    """Build a specific target."""
    info(f"building target {target}")
    return run_cmd(["cmake", "--build", str(build_dir()), "--target", target])


# Runner helpers (backend-agnostic).
def _cmake_generator() -> Optional[str]:
    if is_windows():
        return DEFAULT_CMAKE_GENERATOR if shutil.which("ninja") else None
    return DEFAULT_CMAKE_GENERATOR


def _candidate_executable_paths(build_dir: Path, target: str) -> list[Path]:
    name = exe_name(target)
    candidates = [build_dir / name]
    if is_windows():
        candidates.extend(
            build_dir / config / name for config in WINDOWS_BUILD_CONFIG_DIRS
        )
    return candidates


def _find_executable_path(build_dir: Path, target: str) -> Optional[Path]:
    for candidate in _candidate_executable_paths(build_dir, target):
        if candidate.exists():
            return candidate
    return None


def _missing_executable_message(build_dir: Path, target: str) -> str:
    candidates = _candidate_executable_paths(build_dir, target)
    search = ", ".join(str(path) for path in candidates)
    return f"missing executable for target '{target}' (searched: {search})"


def run_executable(config: ResolvedBuildConfig, args: Sequence[str]) -> int:
    """Run the configured main executable."""
    target = config["project"]["main_target"]
    exe_path = _find_executable_path(config["build_dir"], target)
    if not exe_path:
        error(_missing_executable_message(config["build_dir"], target))
        return 1
    info(f"running {exe_path}")
    return run_cmd([str(exe_path), *args])


def run_tests(config: ResolvedBuildConfig, targets: Sequence[str]) -> int:
    """Build and run the configured test targets."""
    for target in targets:
        result = cmake_build_target(target)
        if result != 0:
            return result
        test_path = _find_executable_path(config["build_dir"], target)
        if not test_path:
            error(_missing_executable_message(config["build_dir"], target))
            return 1
        info(f"running {test_path}")
        result = run_cmd([str(test_path)])
        if result != 0:
            return result
    return 0


def _normalize_compiler_path(
    compiler: Optional[str],
) -> Tuple[Optional[str], bool]:
    """Resolve a compiler string to a normalized path and existence flag."""
    if not compiler:
        return None, False
    resolved = shutil.which(compiler) if os.sep not in compiler else compiler
    if not resolved:
        return _normalize_path_spelling(compiler), False
    if os.path.exists(resolved):
        return os.path.realpath(resolved), True
    return _normalize_path_spelling(resolved), False


def _read_configured_compiler() -> Tuple[Optional[str], bool]:
    """Read the configured compiler from the CMake cache, if present."""
    cache_path = build_dir() / CMAKE_CACHE_FILE_NAME
    if not cache_path.exists():
        return None, False
    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(CMAKE_C_COMPILER_PREFIX):
                    value = line.split("=", 1)[1].strip()
                    if not value:
                        return None, False
                    return value, os.path.exists(value)
    except OSError:
        return None, False
    return None, False


def _clean_if_compiler_mismatch(compiler: Optional[str]) -> None:
    """Clean the build directory when configured and requested compilers differ."""
    if not compiler or not build_dir().exists():
        return
    configured, configured_exists = _read_configured_compiler()
    requested, requested_exists = _normalize_compiler_path(compiler)
    if not configured or not requested:
        return
    if not (configured_exists and requested_exists):
        info(
            "compiler path comparison uses normalized spelling because one or both paths do not exist"
        )
        configured = _normalize_path_spelling(configured)
        requested = _normalize_path_spelling(requested)
    if configured != requested:
        info("existing build uses a different compiler; cleaning build directory")
        clean_build_dir()


def _append_cmake_list(lines: list[str], name: str, entries: Iterable[str]) -> None:
    lines.append(f"set({name}")
    for entry in entries:
        lines.append(f"  {entry}")
    lines.append(")")
    lines.append("")


def _render_cmakelists(
    project: ProjectConfig,
    dependency_file: Path,
    dependency_file_abs: bool,
    local_fn: str,
    fetch_fn: str,
) -> str:
    lines = []
    min_cmake = project["min_cmake"]
    name = project["name"]
    languages = project["languages"]
    lines.append(f"cmake_minimum_required(VERSION {min_cmake})")
    lines.append("")
    lines.append(f"project({name} LANGUAGES {' '.join(languages)})")
    lines.append("")

    if "C" in languages and project.get("c_standard"):
        lines.append(f"set({CMAKE_C_STANDARD_VAR} {project['c_standard']})")
    if "CXX" in languages and project.get("cxx_standard"):
        lines.append(f"set({CMAKE_CXX_STANDARD_VAR} {project['cxx_standard']})")
    if "C" in languages or "CXX" in languages:
        lines.append("")

    main_target = project["main_target"]
    main_sources = project["main_sources"]
    lines.append(f"add_executable({main_target}")
    for source in main_sources:
        lines.append(f"  {source}")
    lines.append(")")
    lines.append("")

    for test_target in project["test_targets"]:
        lines.append(f"add_executable({test_target['name']}")
        for source in test_target["sources"]:
            lines.append(f"  {source}")
        lines.append(")")
        lines.append("")

    target_names = [main_target] + [entry["name"] for entry in project["test_targets"]]
    _append_cmake_list(lines, "PROJECT_TARGETS", target_names)
    lines.append("# Dependency helpers")
    lines.append("set(PROJECT_DEP_TARGETS ${PROJECT_TARGETS})")
    lines.append("")
    lines.extend(
        [
            "function(project_link_dep_includes include_dirs)",
            "  if(NOT include_dirs)",
            "    return()",
            "  endif()",
            "  foreach(target_name IN LISTS PROJECT_DEP_TARGETS)",
            "    if(TARGET ${target_name})",
            "      target_include_directories(${target_name} PRIVATE ${include_dirs})",
            "    endif()",
            "  endforeach()",
            "endfunction()",
            "",
            "function(project_link_dep_libs libs)",
            "  if(NOT libs)",
            "    return()",
            "  endif()",
            "  foreach(target_name IN LISTS PROJECT_DEP_TARGETS)",
            "    if(TARGET ${target_name})",
            "      target_link_libraries(${target_name} PRIVATE ${libs})",
            "    endif()",
            "  endforeach()",
            "endfunction()",
            "",
            f"function({local_fn} name)",
            "  if(WIN32)",
            '    message(FATAL_ERROR "Local dependency lookup is Linux-only. Provide a git URL instead.")',
            "  endif()",
            "",
            '  string(REGEX REPLACE "[^A-Za-z0-9_]" "_" dep_id "${name}")',
            "  find_package(PkgConfig QUIET)",
            "  if(PKG_CONFIG_FOUND)",
            "    pkg_check_modules(${dep_id} QUIET ${name})",
            "  endif()",
            "",
            "  if(${dep_id}_FOUND)",
            "    project_link_dep_includes(${${dep_id}_INCLUDE_DIRS})",
            "    project_link_dep_libs(${${dep_id}_LIBRARIES})",
            "    return()",
            "  endif()",
            "",
            "  set(env_lib_paths)",
            "  foreach(var_name IN ITEMS LIBRARY_PATH LD_LIBRARY_PATH)",
            '    if(DEFINED ENV{${var_name}} AND NOT "$ENV{${var_name}}" STREQUAL "")',
            '      string(REPLACE ":" ";" paths "$ENV{${var_name}}")',
            "      list(APPEND env_lib_paths ${paths})",
            "    endif()",
            "  endforeach()",
            "",
            "  if(env_lib_paths)",
            "    set(lib_paths ${env_lib_paths})",
            "  else()",
            "    set(lib_paths /usr/lib /usr/local/lib /usr/lib64 /usr/local/lib64 /opt/lib /opt/local/lib)",
            "    file(GLOB opt_lib_dirs LIST_DIRECTORIES true /opt/*/lib /opt/*/lib64)",
            "    list(APPEND lib_paths ${opt_lib_dirs})",
            "  endif()",
            "",
            "  set(env_include_paths)",
            "  foreach(var_name IN ITEMS CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH)",
            '    if(DEFINED ENV{${var_name}} AND NOT "$ENV{${var_name}}" STREQUAL "")',
            '      string(REPLACE ":" ";" paths "$ENV{${var_name}}")',
            "      list(APPEND env_include_paths ${paths})",
            "    endif()",
            "  endforeach()",
            "",
            "  if(env_include_paths)",
            "    set(include_paths ${env_include_paths})",
            "  else()",
            "    set(include_paths /usr/include /usr/local/include /opt/include /opt/local/include)",
            "    file(GLOB opt_include_dirs LIST_DIRECTORIES true /opt/*/include)",
            "    list(APPEND include_paths ${opt_include_dirs})",
            "  endif()",
            "",
            '  set(header_candidates "${name}.h" "${name}/${name}.h")',
            "  find_library(${dep_id}_LIBRARY NAMES ${name} PATHS ${lib_paths})",
            "  find_path(${dep_id}_INCLUDE_DIR NAMES ${header_candidates} PATHS ${include_paths})",
            "",
            "  if(NOT (DEFINED ${dep_id}_INCLUDE_DIR AND ${dep_id}_INCLUDE_DIR))",
            "    foreach(base_path IN LISTS include_paths)",
            '      if(IS_DIRECTORY "${base_path}/${name}")',
            '        file(GLOB dep_headers "${base_path}/${name}/*.h")',
            "        if(dep_headers)",
            '          set(${dep_id}_INCLUDE_DIR "${base_path}")',
            "          break()",
            "        endif()",
            "      endif()",
            "    endforeach()",
            "  endif()",
            "",
            "  if(DEFINED ${dep_id}_LIBRARY AND ${dep_id}_LIBRARY)",
            "    project_link_dep_libs(${${dep_id}_LIBRARY})",
            "  endif()",
            "  if(DEFINED ${dep_id}_INCLUDE_DIR AND ${dep_id}_INCLUDE_DIR)",
            "    project_link_dep_includes(${${dep_id}_INCLUDE_DIR})",
            "  endif()",
            "",
            "  if(NOT (DEFINED ${dep_id}_LIBRARY AND ${dep_id}_LIBRARY)",
            "          AND NOT (DEFINED ${dep_id}_INCLUDE_DIR AND ${dep_id}_INCLUDE_DIR))",
            "    message(FATAL_ERROR \"Dependency '${name}' not found. Provide a git URL or check the name (e.g., 'ryalib' vs 'raylib').\")",
            "  endif()",
            "endfunction()",
            "",
            f"function({fetch_fn} name git_url [git_tag])",
            '  string(REGEX REPLACE "[^A-Za-z0-9_]" "_" dep_id "${name}")',
            "  include(FetchContent)",
            '  if(DEFINED git_tag AND NOT "${git_tag}" STREQUAL "")',
            "    FetchContent_Declare(",
            "      ${dep_id}",
            "      GIT_REPOSITORY ${git_url}",
            "      GIT_TAG ${git_tag}",
            "    )",
            "  else()",
            "    FetchContent_Declare(",
            "      ${dep_id}",
            "      GIT_REPOSITORY ${git_url}",
            "      GIT_TAG HEAD",
            "    )",
            "  endif()",
            "  FetchContent_MakeAvailable(${dep_id})",
            "  if(TARGET ${name})",
            "    project_link_dep_libs(${name})",
            "  elseif(TARGET ${name}::${name})",
            "    project_link_dep_libs(${name}::${name})",
            "  else()",
            "    message(WARNING \"Fetched '${name}' but no CMake target named '${name}' or '${name}::${name}' was found; link it manually.\")",
            "  endif()",
            "endfunction()",
            "",
        ]
    )
    if dependency_file_abs:
        include_path = _cmake_path(dependency_file)
        lines.append(f'include("{include_path}" OPTIONAL)')
    else:
        include_path = _cmake_path(dependency_file)
        lines.append(f'include("${{CMAKE_SOURCE_DIR}}/{include_path}" OPTIONAL)')
    lines.append("")

    include_dirs = project.get("include_dirs") or []
    definitions = project.get("definitions") or []
    compile_options = project.get("compile_options") or []
    link_libraries = project.get("link_libraries") or []

    if include_dirs:
        _append_cmake_list(lines, "PROJECT_INCLUDE_DIRS", include_dirs)
    if definitions:
        _append_cmake_list(lines, "PROJECT_DEFINITIONS", definitions)
    if compile_options:
        _append_cmake_list(lines, "PROJECT_COMPILE_OPTIONS", compile_options)
    if link_libraries:
        _append_cmake_list(lines, "PROJECT_LINK_LIBRARIES", link_libraries)

    if include_dirs or definitions or compile_options or link_libraries:
        lines.extend(
            [
                "foreach(target_name IN LISTS PROJECT_TARGETS)",
                "  if(TARGET ${target_name})",
            ]
        )
        if include_dirs:
            lines.append(
                "    target_include_directories(${target_name} PRIVATE ${PROJECT_INCLUDE_DIRS})"
            )
        if definitions:
            lines.append(
                "    target_compile_definitions(${target_name} PRIVATE ${PROJECT_DEFINITIONS})"
            )
        if compile_options:
            lines.append(
                "    target_compile_options(${target_name} PRIVATE ${PROJECT_COMPILE_OPTIONS})"
            )
        if link_libraries:
            lines.append(
                "    target_link_libraries(${target_name} PRIVATE ${PROJECT_LINK_LIBRARIES})"
            )
        lines.extend(
            [
                "  endif()",
                "endforeach()",
                "",
            ]
        )

    for extra_line in project.get("extra_cmake_lines") or []:
        lines.append(extra_line)

    return "\n".join(lines).rstrip() + "\n"


def _render_main_source(project: ProjectConfig, path: Path) -> str:
    name = project.get("name", DEFAULT_PROJECT_NAME).replace('"', '\\"')
    suffix = path.suffix.lower()
    if suffix in {".cpp", ".cc", ".cxx", ".c++"}:
        return (
            "#include <iostream>\n\n"
            "int main() {\n"
            f'  std::cout << "Hello from {name}." << std::endl;\n'
            "  return 0;\n"
            "}\n"
        )
    return (
        "#include <stdio.h>\n\n"
        "int main(void) {\n"
        f'  puts("Hello from {name}.");\n'
        "  return 0;\n"
        "}\n"
    )


def _write_text_file(path: Path, contents: str) -> int:
    """Write UTF-8 text to a file, creating parent dirs as needed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    except OSError as exc:
        error(f"failed to write {path}: {exc}")
        return 1
    return 0


def _write_default_build_config(path: Path, config: WriteConfig) -> int:
    data: dict[str, object] = {
        "build_dir": str(config["build_dir"]),
        "dependency_file": str(config["dependency_file"]),
        "dependency_local_function": config["dependency_local_function"],
        "dependency_fetch_function": config["dependency_fetch_function"],
        "project": config["project"],
    }
    default_test_target = config["default_test_target"]
    if default_test_target:
        data["default_test_target"] = default_test_target
    test_targets = config["test_targets"]
    if test_targets:
        data["test_targets"] = test_targets
    contents = json.dumps(data, indent=2)
    return _write_text_file(path, f"{contents}\n")


def _confirm_init_root(root_dir: Path) -> bool:
    prompt = f"Initialize in current directory ({root_dir})? [y/N]: "
    try:
        response = input(prompt).strip().lower()
    except EOFError:
        return False
    return response in {"y", "yes"}


def _infer_project_name(base_dir: Path) -> str:
    name = base_dir.name or DEFAULT_PROJECT_NAME
    return name


def init_project(
    config: ResolvedBuildConfig,
    config_write_path: Optional[Path],
    base_dir: Path,
    project_name: Optional[str],
) -> int:
    """Create starter config and CMake files if they do not exist."""
    project = config["project"]
    sanitized_project_name = (
        _sanitize_project_name(project_name) if project_name else None
    )
    if sanitized_project_name:
        project["name"] = sanitized_project_name
    created_any = False

    if config_write_path and not config_write_path.exists():
        project_override: ProjectConfigOverrides = {}
        if sanitized_project_name:
            project_override["name"] = sanitized_project_name
        result = _write_default_build_config(
            config_write_path, _config_for_write(project_override)
        )
        if result != 0:
            return result
        info(f"created {config_write_path}")
        created_any = True

    cmake_path = base_dir / "CMakeLists.txt"
    if not cmake_path.exists():
        result = _write_text_file(
            cmake_path,
            _render_cmakelists(
                project,
                config["dependency_file_cmake"],
                config["dependency_file_cmake_abs"],
                config["dependency_local_function"],
                config["dependency_fetch_function"],
            ),
        )
        if result != 0:
            return result
        info(f"created {cmake_path}")
        created_any = True

    main_sources = project.get("main_sources") or [DEFAULT_MAIN_SOURCE]
    main_path = base_dir / main_sources[0]
    if not main_path.exists():
        result = _write_text_file(main_path, _render_main_source(project, main_path))
        if result != 0:
            return result
        info(f"created {main_path}")
        created_any = True

    if not created_any:
        info("nothing to initialize; files already exist")
    return 0


def usage() -> None:
    print("usage: pycmkr <command> [args...]")
    print("")
    print("commands:")
    print("  clean (cl)       remove the build directory")
    print("  configure (c)    generate build files")
    print("  build (b)        configure (if needed) and build")
    print("  run (r)          build (if needed) and run the main binary")
    print("  test (t)         build (if needed) and run configured tests")
    print("  all (a)          configure, build, and run")
    print("  init (i) [path]  create a starter CMakeLists.txt and config if missing")
    print("  adddep (d, ad)  add a dependency (local on Linux or FetchContent)")
    print("  help (h)         show this help text")
    print("")
    print("options:")
    print("  --cc <path>      use a specific C compiler for configuration")
    print("  --config <path>  load build defaults from a JSON file")
    print("  --tag <tag>      specify git tag or branch for adddep (overrides HEAD)")
    print("")
    print("examples:")
    print("  pycmkr build")
    print("  pycmkr build --cc gcc")
    print("  pycmkr run -- --config app_config.json")
    print("  pycmkr test")
    print("  pycmkr test --target unit_tests")
    print("  pycmkr init")
    print("  pycmkr init MyProject")
    print("  pycmkr init ~/new_proj")
    print("  pycmkr init ~/coding/clang/new_proj")
    print(f"  pycmkr build --config {DEFAULT_CONFIG_FILE_NAME}")
    print("  pycmkr adddep raylib")
    print("  pycmkr ad raylib https://github.com/raysan5/raylib.git")
    print("  pycmkr adddep raylib https://github.com/raysan5/raylib.git --tag 5.0")


def _dependency_file_path() -> Path:
    manager = globals()["config_manager"]
    return manager.dependency_file_resolved or manager.dependency_file


def _ensure_dependency_file() -> None:
    path = _dependency_file_path()
    if path.exists():
        return
    manager = globals()["config_manager"]
    header = [
        "# This file is managed by pycmkr -adddep.",
        "# Add custom dependencies with the helpers below.",
        "#",
        "# Examples:",
        f'#   {manager.dependency_local_function}("raylib")',
        f'#   {manager.dependency_fetch_function}("raylib" "https://github.com/raysan5/raylib.git")',
        "",
    ]
    _write_text_file(path, "\n".join(header) + "\n")


def _dependency_exists(name: str) -> bool:
    path = _dependency_file_path()
    if not path.exists():
        return False
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return False
    manager = globals()["config_manager"]
    escaped_name = _cmake_escape(name)
    local_pattern = re.compile(
        rf'^\s*{re.escape(manager.dependency_local_function)}\s*\(\s*"{re.escape(escaped_name)}"\s*\)'
    )
    fetch_pattern = re.compile(
        rf'^\s*{re.escape(manager.dependency_fetch_function)}\s*\(\s*"{re.escape(escaped_name)}"\s*(,|\))'
    )
    for line in contents.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if local_pattern.search(line) or fetch_pattern.search(line):
            return True
    return False


def _paths_have_pattern(paths: Iterable[Path], patterns: Iterable[str]) -> bool:
    for candidate in paths:
        if not candidate.is_dir():
            continue
        for pattern in patterns:
            if list(candidate.glob(pattern)):
                return True
    return False


def _headers_found(paths: Iterable[Path], name: str) -> bool:
    header_patterns = [
        f"{name}.h",
        os.path.join(name, f"{name}.h"),
        os.path.join(name, "*.h"),
    ]
    return _paths_have_pattern(paths, header_patterns)


def _pkg_config_exists(name: str) -> bool:
    if not shutil.which("pkg-config"):
        return False
    result = subprocess.run(
        ["pkg-config", "--exists", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _parse_env_paths(var_names: Iterable[str]) -> list[Path]:
    paths = []
    for var_name in var_names:
        value = os.environ.get(var_name)
        if not value:
            continue
        for entry in value.split(os.pathsep):
            entry = entry.strip()
            if entry:
                paths.append(Path(entry))
    return paths


def _fallback_paths(
    env_vars: Iterable[str],
    default_paths: Iterable[str],
    glob_patterns: Iterable[str],
) -> list[Path]:
    env_paths = _parse_env_paths(env_vars)
    if env_paths:
        return env_paths
    paths = [Path(item) for item in default_paths]
    for pattern in glob_patterns:
        paths.extend(Path(match) for match in glob.glob(pattern))
    return paths


def _local_dependency_found(name: str) -> bool:
    if _pkg_config_exists(name):
        return True
    if is_windows():
        return _windows_dependency_found(name)
    if is_macos():
        return _macos_dependency_found(name)
    return _linux_dependency_found(name)


def _windows_dependency_found(name: str) -> bool:
    lib_paths = _parse_env_paths(["LIB"])
    include_paths = _parse_env_paths(["INCLUDE"])
    bin_paths = _parse_env_paths(["PATH"])
    lib_patterns = [
        f"{name}.lib",
        f"lib{name}.lib",
        f"{name}.dll",
        f"lib{name}.a",
    ]
    if _paths_have_pattern(lib_paths, lib_patterns):
        return True
    if _paths_have_pattern(bin_paths, [f"{name}.dll"]):
        return True
    return _headers_found(include_paths, name)


def _macos_dependency_found(name: str) -> bool:
    lib_paths = _fallback_paths(
        ["LIBRARY_PATH", "DYLD_LIBRARY_PATH"],
        [
            "/usr/local/lib",
            "/opt/homebrew/lib",
            "/usr/lib",
            "/opt/local/lib",
        ],
        ["/opt/homebrew/*/lib", "/opt/local/*/lib"],
    )
    include_paths = _fallback_paths(
        ["CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"],
        [
            "/usr/local/include",
            "/opt/homebrew/include",
            "/usr/include",
            "/opt/local/include",
        ],
        ["/opt/homebrew/*/include", "/opt/local/*/include"],
    )
    lib_patterns = [f"lib{name}.dylib", f"lib{name}.a", f"{name}.dylib"]
    if _paths_have_pattern(lib_paths, lib_patterns):
        return True
    return _headers_found(include_paths, name)


def _linux_dependency_found(name: str) -> bool:
    lib_paths = _fallback_paths(
        ["LIBRARY_PATH", "LD_LIBRARY_PATH"],
        [
            "/usr/lib",
            "/usr/local/lib",
            "/usr/lib64",
            "/usr/local/lib64",
            "/opt/lib",
            "/opt/local/lib",
        ],
        ["/opt/*/lib", "/opt/*/lib64"],
    )
    include_paths = _fallback_paths(
        ["CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"],
        ["/usr/include", "/usr/local/include", "/opt/include", "/opt/local/include"],
        ["/opt/*/include"],
    )
    lib_patterns = [
        f"lib{name}.so*",
        f"lib{name}.a",
        f"{name}.so*",
        f"{name}.a",
    ]
    if _paths_have_pattern(lib_paths, lib_patterns):
        return True
    return _headers_found(include_paths, name)


def _cmake_escape(value: str) -> str:
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("$", "\\$")
    value = value.replace(";", "\\;")
    value = value.replace("#", "\\#")
    return value


def _validate_git_url(url: str) -> tuple[bool, Optional[str]]:
    """Validate git URL for security and format.

    Returns (is_valid, error_message). If is_valid is True, error_message is None.
    """
    dangerous_chars = [";", "#", "{", "}", "`", "&", "|", ">", "<", "\\"]
    for char in dangerous_chars:
        if char in url:
            return False, f"URL must not contain '{char}'"

    if "${" in url:
        return False, "URL must not contain variable expansion patterns"

    if "http://" in url:
        return False, "URL must use HTTPS, not HTTP"

    url_lower = url.lower()
    if not (url_lower.startswith("https://") or url_lower.startswith("git@")):
        return False, "URL must start with 'https://' or 'git@'"

    if url_lower.startswith("https://github.com/"):
        import re

        if not re.match(r"^https://github\.com/[^/]+/[^/]+\.git$", url_lower):
            return (
                False,
                "GitHub URL must be in format 'https://github.com/{owner}/{repo}.git'",
            )

    if url_lower.startswith("git@github.com:"):
        import re

        if not re.match(r"^git@github\.com:[^/]+/[^/]+\.git$", url_lower):
            return (
                False,
                "GitHub SSH URL must be in format 'git@github.com:{owner}/{repo}.git'",
            )

    return True, None


def _add_dependency(
    name: str, git_url: Optional[str], git_tag: Optional[str] = None
) -> int:
    name = name.strip()
    if not name:
        error("usage: pycmkr adddep <name> [git_url] [--tag <tag_or_branch>]")
        return 2
    if "\n" in name or "\r" in name:
        error("dependency name must not include newlines")
        return 2

    if git_url:
        if "\n" in git_url or "\r" in git_url:
            error("dependency URL must not include newlines")
            return 2
        is_valid, error_msg = _validate_git_url(git_url)
        if not is_valid:
            assert error_msg is not None, (
                "error_msg should be set when is_valid is False"
            )
            error(error_msg)
            return 2

    if git_tag:
        if "\n" in git_tag or "\r" in git_tag:
            error("tag/branch must not include newlines")
            return 2
        if ";" in git_tag or "#" in git_tag or '"' in git_tag:
            error("tag/branch contains invalid characters")
            return 2

    if _dependency_exists(name):
        info(f"dependency '{name}' already exists in {_dependency_file_path()}")
        return 0

    if not git_url:
        if not _local_dependency_found(name):
            error(
                f"dependency '{name}' not found locally. "
                "Provide a git URL or check the name (e.g., 'ryalib' vs 'raylib')."
            )
            return 2

    _ensure_dependency_file()
    path = _dependency_file_path()
    escaped_name = _cmake_escape(name)
    manager = globals()["config_manager"]
    try:
        with path.open("a", encoding="utf-8") as handle:
            if git_url:
                escaped_url = _cmake_escape(git_url)
                if git_tag:
                    escaped_tag = _cmake_escape(git_tag)
                    handle.write(
                        f'{manager.dependency_fetch_function}("{escaped_name}" "{escaped_url}" "{escaped_tag}")\n'
                    )
                else:
                    handle.write(
                        f'{manager.dependency_fetch_function}("{escaped_name}" "{escaped_url}")\n'
                    )
            else:
                handle.write(f'{manager.dependency_local_function}("{escaped_name}")\n')
    except OSError as exc:
        error(f"failed to update {path}: {exc}")
        return 1

    info(f"added dependency '{name}' to {path}")
    return 0


def ensure_configured(compiler: Optional[str] = None) -> int:
    _clean_if_compiler_mismatch(compiler)
    if compiler or not build_dir().exists():
        return cmake_configure(compiler)
    return 0


def ensure_built(compiler: Optional[str] = None) -> int:
    result = ensure_configured(compiler)
    if result != 0:
        return result
    return cmake_build()


def main() -> int:
    if len(sys.argv) < 2:
        usage()
        return 2

    command = sys.argv[1]
    if command in {"-v", "--version"}:
        try:
            version = importlib.metadata.version("pycmkr")
        except importlib.metadata.PackageNotFoundError:
            version = "0.1.0"
        print(f"pycmkr {version}")
        return 0
    args = sys.argv[2:]

    aliases = {
        "cl": "clean",
        "c": "configure",
        "b": "build",
        "r": "run",
        "t": "test",
        "a": "all",
        "i": "init",
        "d": "adddep",
        "ad": "adddep",
        "h": "help",
    }
    command = aliases.get(command, command)
    if command in {"help", "-h", "--help"}:
        usage()
        return 0
    if command == "adddep":
        if not args or len(args) > 4:
            error("usage: pycmkr adddep <name> [git_url] [--tag <tag_or_branch>]")
            return 2
        name = args[0]
        git_url = None
        git_tag = None

        i = 1
        while i < len(args):
            if args[i] == "--tag":
                if i + 1 >= len(args):
                    error("usage: --tag requires a value")
                    return 2
                git_tag = args[i + 1]
                i += 2
            else:
                if git_url is None:
                    git_url = args[i]
                    i += 1
                else:
                    error(
                        "usage: pycmkr adddep <name> [git_url] [--tag <tag_or_branch>]"
                    )
                    return 2

        return _add_dependency(name, git_url, git_tag)

    compiler = None
    config_path = None
    parsed_args = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            parsed_args.extend(args[index:])
            break
        if arg == "--config":
            if index + 1 >= len(args) or args[index + 1] == "--":
                error("usage: --config <path>")
                return 2
            config_path = args[index + 1]
            index += 2
            continue
        if arg.startswith("--config="):
            config_path = arg.split("=", 1)[1]
            if not config_path:
                error("usage: --config <path>")
                return 2
            index += 1
            continue
        if arg == "--cc":
            if index + 1 >= len(args) or args[index + 1] == "--":
                error("usage: --cc <compiler>")
                return 2
            compiler = args[index + 1]
            index += 2
            continue
        if arg.startswith("--cc="):
            compiler = arg.split("=", 1)[1]
            if not compiler:
                error("usage: --cc <compiler>")
                return 2
            index += 1
            continue
        parsed_args.append(arg)
        index += 1

    args = parsed_args
    if args and args[0] == "--":
        args = args[1:]

    base_dir = None
    project_name: Optional[str] = None
    if command == "init":
        if len(args) > 1:
            error("usage: pycmkr init [path]")
            return 2
        if args:
            path_arg = args[0].strip()
            if not path_arg:
                error("usage: pycmkr init [path]")
                return 2
            base_dir = Path(path_arg).expanduser()
            project_name = _infer_project_name(base_dir.resolve())
        else:
            base_dir = Path.cwd()
            if not _confirm_init_root(base_dir):
                info("init canceled")
                return 1
            project_name = _infer_project_name(base_dir)

    config_env = os.environ.get("BUILD_CONFIG_FILE")
    allow_missing_config = command == "init"
    config_write_path = None
    config_candidate = None
    known_configs = [DEFAULT_CONFIG_FILE_NAME]
    if command == "init" and base_dir and not config_path and not config_env:
        config_candidate = base_dir / known_configs[0]
        config_write_path = config_candidate
    elif config_path:
        base = base_dir if allow_missing_config and base_dir else Path.cwd()
        config_candidate, _ = _expand_and_normalize(config_path, base)
    elif config_env:
        config_candidate, _ = _expand_and_normalize(config_env, Path.cwd())
    else:
        config_candidate = _discover_config_path(Path.cwd(), known_configs)

    if not config_candidate:
        if allow_missing_config:
            if base_dir:
                config_candidate = base_dir / known_configs[0]
                config_write_path = config_candidate
        else:
            error("no build config found; pass --config or set BUILD_CONFIG_FILE")
            return 2

    if config_candidate:
        globals()["config_manager"].set_config_path(config_candidate)
        if config_candidate.exists():
            result = _apply_config_file(config_candidate)
            if result != 0:
                return result
        else:
            if allow_missing_config:
                config_write_path = config_candidate
            else:
                error(f"config file {config_candidate} not found")
                return 2

    _apply_env_overrides()
    project_root = _resolve_project_root(config_candidate)
    result = _resolve_config_paths(project_root)
    if result != 0:
        return result
    resolved_config = _resolve_config()

    if command in {"help", "-h", "--help"}:
        usage()
        return 0

    if command == "init":
        if base_dir is None:
            error("missing base directory for init")
            return 2
        if project_name is None:
            error("missing project name for init")
            return 2
        if not base_dir.exists():
            try:
                base_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                error(f"failed to create {base_dir}: {exc}")
                return 1
        return init_project(resolved_config, config_write_path, base_dir, project_name)

    if command == "configure":
        _clean_if_compiler_mismatch(compiler)
        return cmake_configure(compiler)
    if command == "clean":
        return clean_build_dir()
    if command == "build":
        return ensure_built(compiler)
    if command == "run":
        result = ensure_built(compiler)
        if result != 0:
            return result
        return run_executable(resolved_config, args)
    if command == "test":
        result = ensure_configured(compiler)
        if result != 0:
            return result
        target = resolved_config["default_test_target"]
        targets = resolved_config["test_targets"]
        if args:
            if len(args) == 2 and args[0] in {"--target", "-t"}:
                target = args[1]
                targets = [target]
            else:
                error("usage: pycmkr test [--target name]")
                return 2
        if not targets:
            if target:
                targets = [target]
            else:
                error("no test targets configured")
                return 2
        return run_tests(resolved_config, targets)
    if command == "all":
        result = cmake_configure(compiler)
        if result != 0:
            return result
        result = cmake_build()
        if result != 0:
            return result
        return run_executable(resolved_config, args)

    error(f"unknown command '{command}'")
    usage()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
