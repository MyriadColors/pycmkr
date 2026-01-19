#!/usr/bin/env python3
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def info(message):
  print(f"[pycmkr] {message}")


def error(message):
  print(f"error: {message}", file=sys.stderr)


def run_cmd(cmd, cwd=None, env=None):
  print("+", " ".join(shlex.quote(part) for part in cmd))
  try:
    subprocess.run(cmd, cwd=cwd, check=True, env=env)
  except subprocess.CalledProcessError as exc:
    error(f"command failed with exit code {exc.returncode}")
    return exc.returncode
  return 0


def _normalize_path_spelling(path):
  return os.path.normcase(os.path.normpath(str(path)))


def _realpath_with_missing(path):
  path = Path(path)
  missing_parts = []
  current = path
  while not current.exists():
    missing_parts.append(current.name)
    parent = current.parent
    if parent == current:
      break
    current = parent
  try:
    real_parent = current.resolve()
  except OSError:
    real_parent = current.absolute()
  for name in reversed(missing_parts):
    real_parent = real_parent / name
  return real_parent


def _path_is_within(child, parent):
  try:
    child.relative_to(parent)
    return True
  except ValueError:
    return False


def _cmake_path(path):
  return path.as_posix()


# Project configuration defaults.
BUILD_CONFIG = {
    "build_dir": Path("build"),
    "default_test_target": None,
    "test_targets": [],
    "dependency_file": Path("dependencies.cmake"),
    "dependency_local_function": "project_add_local_dependency",
    "dependency_fetch_function": "project_add_fetch_dependency",
    "project": {},
    "project_root": None,
    "build_dir_resolved": None,
    "dependency_file_resolved": None,
    "dependency_file_cmake": None,
    "dependency_file_cmake_abs": False,
    "config_path": None,
}


def _sanitize_project_name(name):
  cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
  return cleaned or "Project"


def _default_project_config():
  return {
      "name": "Project",
      "languages": ["C"],
      "min_cmake": "3.10",
      "c_standard": "23",
      "cxx_standard": None,
      "main_target": "main",
      "main_sources": ["main.c"],
      "test_targets": [],
      "include_dirs": [],
      "definitions": [],
      "compile_options": [],
      "link_libraries": [],
      "extra_cmake_lines": [],
  }


def _resolve_project_config():
  defaults = _default_project_config()
  project = BUILD_CONFIG.get("project") or {}
  merged = {**defaults, **project}
  if not project.get("name"):
    merged["name"] = _sanitize_project_name(Path.cwd().name)
  if not project.get("main_sources"):
    merged["main_sources"] = defaults["main_sources"]
  if not project.get("languages"):
    merged["languages"] = defaults["languages"]
  return merged


def _resolve_config():
  project = _resolve_project_config()
  return {
      "project_root": BUILD_CONFIG["project_root"],
      "build_dir": BUILD_CONFIG["build_dir_resolved"] or BUILD_CONFIG["build_dir"],
      "default_test_target": BUILD_CONFIG["default_test_target"],
      "test_targets": BUILD_CONFIG["test_targets"],
      "dependency_file": BUILD_CONFIG["dependency_file_resolved"]
      or BUILD_CONFIG["dependency_file"],
      "dependency_file_cmake": BUILD_CONFIG["dependency_file_cmake"],
      "dependency_file_cmake_abs": BUILD_CONFIG["dependency_file_cmake_abs"],
      "dependency_local_function": BUILD_CONFIG["dependency_local_function"],
      "dependency_fetch_function": BUILD_CONFIG["dependency_fetch_function"],
      "project": project,
  }


def _apply_config_file(path):
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
  if build_dir is not None:
    if not isinstance(build_dir, str) or not build_dir.strip():
      error("config build_dir must be a non-empty string")
      return 1
    BUILD_CONFIG["build_dir"] = Path(build_dir)

  test_target = data.get("default_test_target")
  if test_target is not None:
    if not isinstance(test_target, str) or not test_target.strip():
      error("config default_test_target must be a non-empty string")
      return 1
    BUILD_CONFIG["default_test_target"] = test_target

  test_targets = data.get("test_targets")
  if test_targets is not None:
    if not isinstance(test_targets, list):
      error("config test_targets must be a list of strings")
      return 1
    normalized = []
    for entry in test_targets:
      if not isinstance(entry, str) or not entry.strip():
        error("config test_targets must be a list of non-empty strings")
        return 1
      normalized.append(entry)
    BUILD_CONFIG["test_targets"] = normalized

  dependency_file = data.get("dependency_file")
  if dependency_file is not None:
    if not isinstance(dependency_file, str) or not dependency_file.strip():
      error("config dependency_file must be a non-empty string")
      return 1
    BUILD_CONFIG["dependency_file"] = Path(dependency_file)

  local_fn = data.get("dependency_local_function")
  if local_fn is not None:
    if not isinstance(local_fn, str) or not local_fn.strip():
      error("config dependency_local_function must be a non-empty string")
      return 1
    BUILD_CONFIG["dependency_local_function"] = local_fn

  fetch_fn = data.get("dependency_fetch_function")
  if fetch_fn is not None:
    if not isinstance(fetch_fn, str) or not fetch_fn.strip():
      error("config dependency_fetch_function must be a non-empty string")
      return 1
    BUILD_CONFIG["dependency_fetch_function"] = fetch_fn

  project = data.get("project")
  if project is not None:
    if not isinstance(project, dict):
      error("config project must be a JSON object")
      return 1
    normalized = {}

    name = project.get("name")
    if name is not None:
      if not isinstance(name, str) or not name.strip():
        error("config project.name must be a non-empty string")
        return 1
      normalized["name"] = name

    languages = project.get("languages")
    if languages is not None:
      if not isinstance(languages, list):
        error("config project.languages must be a list of strings")
        return 1
      normalized_languages = []
      for entry in languages:
        if not isinstance(entry, str) or not entry.strip():
          error("config project.languages must be a list of non-empty strings")
          return 1
        normalized_languages.append(entry)
      if not normalized_languages:
        error("config project.languages must not be empty")
        return 1
      normalized["languages"] = normalized_languages

    min_cmake = project.get("min_cmake")
    if min_cmake is not None:
      if isinstance(min_cmake, int):
        normalized["min_cmake"] = str(min_cmake)
      elif isinstance(min_cmake, str) and min_cmake.strip():
        normalized["min_cmake"] = min_cmake.strip()
      else:
        error("config project.min_cmake must be a string or integer")
        return 1

    c_standard = project.get("c_standard")
    if c_standard is not None:
      if isinstance(c_standard, int):
        normalized["c_standard"] = str(c_standard)
      elif isinstance(c_standard, str) and c_standard.strip():
        normalized["c_standard"] = c_standard.strip()
      else:
        error("config project.c_standard must be a string, integer, or null")
        return 1

    cxx_standard = project.get("cxx_standard")
    if "cxx_standard" in project:
      if cxx_standard is None:
        normalized["cxx_standard"] = None
      elif isinstance(cxx_standard, int):
        normalized["cxx_standard"] = str(cxx_standard)
      elif isinstance(cxx_standard, str) and cxx_standard.strip():
        normalized["cxx_standard"] = cxx_standard.strip()
      else:
        error("config project.cxx_standard must be a string, integer, or null")
        return 1

    main_target = project.get("main_target")
    if main_target is not None:
      if not isinstance(main_target, str) or not main_target.strip():
        error("config project.main_target must be a non-empty string")
        return 1
      normalized["main_target"] = main_target

    main_sources = project.get("main_sources")
    if main_sources is not None:
      if not isinstance(main_sources, list):
        error("config project.main_sources must be a list of strings")
        return 1
      normalized_sources = []
      for entry in main_sources:
        if not isinstance(entry, str) or not entry.strip():
          error("config project.main_sources must be a list of non-empty strings")
          return 1
        normalized_sources.append(entry)
      if not normalized_sources:
        error("config project.main_sources must not be empty")
        return 1
      normalized["main_sources"] = normalized_sources

    test_targets = project.get("test_targets")
    if test_targets is not None:
      if not isinstance(test_targets, list):
        error("config project.test_targets must be a list of objects")
        return 1
      normalized_tests = []
      for entry in test_targets:
        if not isinstance(entry, dict):
          error("config project.test_targets entries must be objects")
          return 1
        target_name = entry.get("name")
        if not isinstance(target_name, str) or not target_name.strip():
          error("config project.test_targets.name must be a non-empty string")
          return 1
        sources = entry.get("sources")
        if not isinstance(sources, list):
          error("config project.test_targets.sources must be a list of strings")
          return 1
        normalized_sources = []
        for source in sources:
          if not isinstance(source, str) or not source.strip():
            error("config project.test_targets.sources must be a list of non-empty strings")
            return 1
          normalized_sources.append(source)
        if not normalized_sources:
          error("config project.test_targets.sources must not be empty")
          return 1
        normalized_tests.append(
            {
                "name": target_name,
                "sources": normalized_sources,
            }
        )
      normalized["test_targets"] = normalized_tests

    include_dirs = project.get("include_dirs")
    if include_dirs is not None:
      if not isinstance(include_dirs, list):
        error("config project.include_dirs must be a list of strings")
        return 1
      normalized_dirs = []
      for entry in include_dirs:
        if not isinstance(entry, str) or not entry.strip():
          error("config project.include_dirs must be a list of non-empty strings")
          return 1
        normalized_dirs.append(entry)
      normalized["include_dirs"] = normalized_dirs

    definitions = project.get("definitions")
    if definitions is not None:
      if not isinstance(definitions, list):
        error("config project.definitions must be a list of strings")
        return 1
      normalized_defs = []
      for entry in definitions:
        if not isinstance(entry, str) or not entry.strip():
          error("config project.definitions must be a list of non-empty strings")
          return 1
        normalized_defs.append(entry)
      normalized["definitions"] = normalized_defs

    compile_options = project.get("compile_options")
    if compile_options is not None:
      if not isinstance(compile_options, list):
        error("config project.compile_options must be a list of strings")
        return 1
      normalized_options = []
      for entry in compile_options:
        if not isinstance(entry, str) or not entry.strip():
          error("config project.compile_options must be a list of non-empty strings")
          return 1
        normalized_options.append(entry)
      normalized["compile_options"] = normalized_options

    link_libraries = project.get("link_libraries")
    if link_libraries is not None:
      if not isinstance(link_libraries, list):
        error("config project.link_libraries must be a list of strings")
        return 1
      normalized_libs = []
      for entry in link_libraries:
        if not isinstance(entry, str) or not entry.strip():
          error("config project.link_libraries must be a list of non-empty strings")
          return 1
        normalized_libs.append(entry)
      normalized["link_libraries"] = normalized_libs

    extra_lines = project.get("extra_cmake_lines")
    if extra_lines is not None:
      if not isinstance(extra_lines, list):
        error("config project.extra_cmake_lines must be a list of strings")
        return 1
      normalized_lines = []
      for entry in extra_lines:
        if not isinstance(entry, str):
          error("config project.extra_cmake_lines must be a list of strings")
          return 1
        normalized_lines.append(entry)
      normalized["extra_cmake_lines"] = normalized_lines

    if normalized:
      current = BUILD_CONFIG.get("project") or {}
      current.update(normalized)
      BUILD_CONFIG["project"] = current

  return 0


def _apply_env_overrides():
  build_dir_override = os.environ.get("BUILD_DIR")
  if build_dir_override:
    BUILD_CONFIG["build_dir"] = Path(build_dir_override)
  main_target_override = os.environ.get("MAIN_TARGET")
  if main_target_override:
    current = BUILD_CONFIG.get("project") or {}
    current["main_target"] = main_target_override
    BUILD_CONFIG["project"] = current
  test_target_override = os.environ.get("TEST_TARGET")
  if test_target_override:
    BUILD_CONFIG["default_test_target"] = test_target_override
  test_targets_override = os.environ.get("TEST_TARGETS")
  if test_targets_override:
    BUILD_CONFIG["test_targets"] = [
        entry.strip()
        for entry in test_targets_override.split(",")
        if entry.strip()
    ]
  dependency_file_override = os.environ.get("DEPENDENCY_FILE")
  if dependency_file_override:
    BUILD_CONFIG["dependency_file"] = Path(dependency_file_override)
  local_fn_override = os.environ.get("DEPENDENCY_LOCAL_FUNCTION")
  if local_fn_override:
    BUILD_CONFIG["dependency_local_function"] = local_fn_override
  fetch_fn_override = os.environ.get("DEPENDENCY_FETCH_FUNCTION")
  if fetch_fn_override:
    BUILD_CONFIG["dependency_fetch_function"] = fetch_fn_override


def _discover_config_path(start_dir, names):
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


def _resolve_project_root(config_path):
  config_path = Path(config_path)
  if not config_path.is_absolute():
    config_path = (Path.cwd() / config_path)
  return _realpath_with_missing(config_path.parent)


def _resolve_dependency_file(project_root, dependency_file):
  dependency_file = Path(dependency_file).expanduser()
  if dependency_file.is_absolute():
    candidate = dependency_file
    cmake_path = None
    cmake_is_abs = True
  else:
    candidate = project_root / dependency_file
    cmake_path = None
    cmake_is_abs = False

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


def _resolve_config_paths(project_root):
  BUILD_CONFIG["project_root"] = project_root

  build_dir = BUILD_CONFIG["build_dir"].expanduser()
  if not build_dir.is_absolute():
    build_dir = project_root / build_dir
  BUILD_CONFIG["build_dir_resolved"] = build_dir

  resolved = _resolve_dependency_file(project_root, BUILD_CONFIG["dependency_file"])
  if not resolved:
    return 1
  dependency_file, cmake_path, cmake_is_abs = resolved
  BUILD_CONFIG["dependency_file_resolved"] = dependency_file
  BUILD_CONFIG["dependency_file_cmake"] = cmake_path
  BUILD_CONFIG["dependency_file_cmake_abs"] = cmake_is_abs
  return 0


def _config_for_write(project_override=None):
  project = _resolve_project_config()
  if project_override:
    project.update(project_override)
  return {
      "build_dir": BUILD_CONFIG["build_dir"],
      "default_test_target": BUILD_CONFIG["default_test_target"],
      "test_targets": BUILD_CONFIG["test_targets"],
      "dependency_file": BUILD_CONFIG["dependency_file"],
      "dependency_local_function": BUILD_CONFIG["dependency_local_function"],
      "dependency_fetch_function": BUILD_CONFIG["dependency_fetch_function"],
      "project": project,
  }


def build_dir():
  return BUILD_CONFIG["build_dir_resolved"] or BUILD_CONFIG["build_dir"]


def clean_build_dir():
  path = build_dir()
  if path.exists():
    info(f"removing {path}")
    shutil.rmtree(path)
  else:
    info(f"nothing to clean at {path}")


# CMake/Ninja backend adapter.
def cmake_configure(compiler=None):
  info("configuring build directory")
  env = None
  if compiler:
    info(f"using compiler {compiler}")
    env = os.environ.copy()
    env["CC"] = compiler
  return run_cmd(
      [
          "cmake",
          "-S",
          str(BUILD_CONFIG["project_root"] or Path.cwd()),
          "-B",
          str(build_dir()),
          "-G",
          "Ninja",
      ],
      env=env,
  )


def cmake_build():
  info("building")
  return run_cmd(["cmake", "--build", str(build_dir())])


def cmake_build_target(target):
  info(f"building target {target}")
  return run_cmd(["cmake", "--build", str(build_dir()), "--target", target])


# Runner helpers (backend-agnostic).
def run_executable(config, args):
  exe_name = config["project"]["main_target"]
  if os.name == "nt":
    exe_name = f"{exe_name}.exe"
  exe_path = config["build_dir"] / exe_name
  if not exe_path.exists():
    error(f"missing executable at {exe_path}")
    sys.exit(1)
  info(f"running {exe_path}")
  return run_cmd([str(exe_path), *args])


def run_tests(config, targets):
  for target in targets:
    test_name = f"{target}.exe" if os.name == "nt" else target
    test_path = config["build_dir"] / test_name
    result = cmake_build_target(target)
    if result != 0:
      return result
    if not test_path.exists():
      error(f"missing test executable at {test_path}")
      return 1
    info(f"running {test_path}")
    result = run_cmd([str(test_path)])
    if result != 0:
      return result
  return 0


def _normalize_compiler_path(compiler):
  if not compiler:
    return None, False
  resolved = shutil.which(compiler) if os.sep not in compiler else compiler
  if not resolved:
    return _normalize_path_spelling(compiler), False
  if os.path.exists(resolved):
    return os.path.realpath(resolved), True
  return _normalize_path_spelling(resolved), False


def _read_configured_compiler():
  cache_path = build_dir() / "CMakeCache.txt"
  if not cache_path.exists():
    return None, False
  try:
    with cache_path.open("r", encoding="utf-8") as handle:
      for line in handle:
        if line.startswith("CMAKE_C_COMPILER:"):
          value = line.split("=", 1)[1].strip()
          if not value:
            return None, False
          return value, os.path.exists(value)
  except OSError:
    return None, False
  return None, False


def _clean_if_compiler_mismatch(compiler):
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


def _append_cmake_list(lines, name, entries):
  lines.append(f"set({name}")
  for entry in entries:
    lines.append(f"  {entry}")
  lines.append(")")
  lines.append("")


def _render_cmakelists(
    project, dependency_file, dependency_file_abs, local_fn, fetch_fn
):
  lines = []
  min_cmake = project["min_cmake"]
  name = project["name"]
  languages = project["languages"]
  lines.append(f"cmake_minimum_required(VERSION {min_cmake})")
  lines.append("")
  lines.append(f"project({name} LANGUAGES {' '.join(languages)})")
  lines.append("")

  if "C" in languages and project.get("c_standard"):
    lines.append(f"set(CMAKE_C_STANDARD {project['c_standard']})")
  if "CXX" in languages and project.get("cxx_standard"):
    lines.append(f"set(CMAKE_CXX_STANDARD {project['cxx_standard']})")
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
          "    message(FATAL_ERROR \"Local dependency lookup is Linux-only. Provide a git URL instead.\")",
          "  endif()",
          "",
          "  string(REGEX REPLACE \"[^A-Za-z0-9_]\" \"_\" dep_id \"${name}\")",
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
          "    if(DEFINED ENV{${var_name}} AND NOT \"$ENV{${var_name}}\" STREQUAL \"\")",
          "      string(REPLACE \":\" \";\" paths \"$ENV{${var_name}}\")",
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
          "    if(DEFINED ENV{${var_name}} AND NOT \"$ENV{${var_name}}\" STREQUAL \"\")",
          "      string(REPLACE \":\" \";\" paths \"$ENV{${var_name}}\")",
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
          "  set(header_candidates \"${name}.h\" \"${name}/${name}.h\")",
          "  find_library(${dep_id}_LIBRARY NAMES ${name} PATHS ${lib_paths})",
          "  find_path(${dep_id}_INCLUDE_DIR NAMES ${header_candidates} PATHS ${include_paths})",
          "",
          "  if(NOT (DEFINED ${dep_id}_INCLUDE_DIR AND ${dep_id}_INCLUDE_DIR))",
          "    foreach(base_path IN LISTS include_paths)",
          "      if(IS_DIRECTORY \"${base_path}/${name}\")",
          "        file(GLOB dep_headers \"${base_path}/${name}/*.h\")",
          "        if(dep_headers)",
          "          set(${dep_id}_INCLUDE_DIR \"${base_path}\")",
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
          f"function({fetch_fn} name git_url)",
          "  string(REGEX REPLACE \"[^A-Za-z0-9_]\" \"_\" dep_id \"${name}\")",
          "  include(FetchContent)",
          "  FetchContent_Declare(",
          "    ${dep_id}",
          "    GIT_REPOSITORY ${git_url}",
          "    GIT_TAG HEAD",
          "  )",
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
    lines.append(f"include(\"{include_path}\" OPTIONAL)")
  else:
    include_path = _cmake_path(dependency_file)
    lines.append(f"include(\"${{CMAKE_SOURCE_DIR}}/{include_path}\" OPTIONAL)")
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


def _render_main_source(project, path):
  name = project.get("name", "Project").replace("\"", "\\\"")
  suffix = path.suffix.lower()
  if suffix in {".cpp", ".cc", ".cxx", ".c++"}:
    return (
        "#include <iostream>\n\n"
        "int main() {\n"
        f"  std::cout << \"Hello from {name}.\" << std::endl;\n"
        "  return 0;\n"
        "}\n"
    )
  return (
      "#include <stdio.h>\n\n"
      "int main(void) {\n"
      f"  puts(\"Hello from {name}.\");\n"
      "  return 0;\n"
      "}\n"
  )


def _write_text_file(path, contents):
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
  except OSError as exc:
    error(f"failed to write {path}: {exc}")
    return 1
  return 0


def _write_default_build_config(path, config):
  data = {
      "build_dir": str(config["build_dir"]),
      "dependency_file": str(config["dependency_file"]),
      "dependency_local_function": config["dependency_local_function"],
      "dependency_fetch_function": config["dependency_fetch_function"],
      "project": config["project"],
  }
  if config.get("default_test_target"):
    data["default_test_target"] = config["default_test_target"]
  if config.get("test_targets"):
    data["test_targets"] = config["test_targets"]
  contents = json.dumps(data, indent=2)
  return _write_text_file(path, f"{contents}\n")


def _maybe_copy_self(base_dir):
  if shutil.which("build"):
    return 0
  source = Path(__file__).resolve()
  destination = base_dir / "pycmkr"
  if destination.exists():
    return 0
  try:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
  except OSError as exc:
    error(f"failed to copy pycmkr to {destination}: {exc}")
    return 1
  info(f"copied pycmkr to {destination}")
  return 0


def _confirm_init_root(root_dir):
  prompt = f"Initialize in current directory ({root_dir})? [y/N]: "
  try:
    response = input(prompt).strip().lower()
  except EOFError:
    return False
  return response in {"y", "yes"}


def _infer_project_name(base_dir):
  name = base_dir.name or "Project"
  return name


def init_project(config, config_write_path, base_dir, project_name):
  project = dict(config["project"])
  if project_name:
    project["name"] = project_name
  config = {**config, "project": project}
  created_any = False

  result = _maybe_copy_self(base_dir)
  if result != 0:
    return result

  if config_write_path and not config_write_path.exists():
    project_override = {}
    if project_name:
      project_override["name"] = project_name
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

  main_sources = project.get("main_sources") or ["main.c"]
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


def usage():
  print("usage: python pycmkr <command> [args...]")
  print("")
  print("commands:")
  print("  clean (cl)       remove the build directory")
  print("  configure (c)    generate build files")
  print("  build (b)        configure (if needed) and build")
  print("  run (r)          build (if needed) and run the main binary")
  print("  test (t)         build (if needed) and run configured tests")
  print("  all (a)          configure, build, and run")
  print(
      "  init (i) [path]  create a starter CMakeLists.txt and config if missing"
  )
  print("  adddep (--ad)    add a dependency (local on Linux or FetchContent)")
  print("  help (h)         show this help text")
  print("")
  print("options:")
  print("  --cc <path>      use a specific C compiler for configuration")
  print("  --config <path>  load build defaults from a JSON file")
  print("")
  print("examples:")
  print("  python pycmkr build")
  print("  python pycmkr build --cc gcc")
  print("  python pycmkr run -- --config app_config.json")
  print("  python pycmkr test")
  print("  python pycmkr test --target unit_tests")
  print("  python pycmkr init")
  print("  python pycmkr init MyProject")
  print("  python pycmkr init ~/new_proj")
  print("  python pycmkr init ~/coding/clang/new_proj")
  print("  python pycmkr build --config build_config.json")
  print("  python pycmkr adddep raylib")
  print("  python pycmkr --ad raylib https://github.com/raysan5/raylib.git")


def _dependency_file_path():
  return BUILD_CONFIG["dependency_file_resolved"] or BUILD_CONFIG["dependency_file"]


def _ensure_dependency_file():
  path = _dependency_file_path()
  if path.exists():
    return
  header = [
      "# This file is managed by pycmkr -adddep.",
      "# Add custom dependencies with the helpers below.",
      "#",
      "# Examples:",
      f"#   {BUILD_CONFIG['dependency_local_function']}(\"raylib\")",
      f"#   {BUILD_CONFIG['dependency_fetch_function']}(\"raylib\" \"https://github.com/raysan5/raylib.git\")",
      "",
  ]
  _write_text_file(path, "\n".join(header) + "\n")


def _dependency_exists(name):
  path = _dependency_file_path()
  if not path.exists():
    return False
  try:
    contents = path.read_text(encoding="utf-8")
  except OSError:
    return False
  local_line = f"{BUILD_CONFIG['dependency_local_function']}(\"{name}\")"
  fetch_line = f"{BUILD_CONFIG['dependency_fetch_function']}(\"{name}\""
  for line in contents.splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
      continue
    if local_line in stripped or fetch_line in stripped:
      return True
  return False


def _pkg_config_exists(name):
  if not shutil.which("pkg-config"):
    return False
  result = subprocess.run(
      ["pkg-config", "--exists", name],
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
  )
  return result.returncode == 0


def _parse_env_paths(var_names):
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


def _fallback_paths(env_vars, default_paths, glob_patterns):
  env_paths = _parse_env_paths(env_vars)
  if env_paths:
    return env_paths
  paths = [Path(item) for item in default_paths]
  for pattern in glob_patterns:
    paths.extend(Path(match) for match in glob.glob(pattern))
  return paths


def _local_dependency_found(name):
  if _pkg_config_exists(name):
    return True

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
  for lib_dir in lib_paths:
    if not lib_dir.is_dir():
      continue
    for pattern in lib_patterns:
      if list(lib_dir.glob(pattern)):
        return True

  header_patterns = [
      f"{name}.h",
      os.path.join(name, f"{name}.h"),
      os.path.join(name, "*.h"),
  ]
  for include_dir in include_paths:
    if not include_dir.is_dir():
      continue
    for pattern in header_patterns:
      if list((include_dir).glob(pattern)):
        return True

  return False


def _add_dependency(name, git_url):
  name = name.strip()
  if not name:
    error("usage: python pycmkr adddep <name> [git_url]")
    return 2

  if _dependency_exists(name):
    info(f"dependency '{name}' already exists in {_dependency_file_path()}")
    return 0

  is_linux = sys.platform.startswith("linux")
  if not git_url:
    if not is_linux:
      error(
          f"dependency '{name}' not found: local lookup is Linux-only. "
          "Provide a git URL or check the name (e.g., 'ryalib' vs 'raylib')."
      )
      return 2
    if not _local_dependency_found(name):
      error(
          f"dependency '{name}' not found locally. "
          "Provide a git URL or check the name (e.g., 'ryalib' vs 'raylib')."
      )
      return 2

  _ensure_dependency_file()
  path = _dependency_file_path()
  try:
    with path.open("a", encoding="utf-8") as handle:
      if git_url:
        handle.write(
            f"{BUILD_CONFIG['dependency_fetch_function']}(\"{name}\" \"{git_url}\")\n"
        )
      else:
        handle.write(f"{BUILD_CONFIG['dependency_local_function']}(\"{name}\")\n")
  except OSError as exc:
    error(f"failed to update {path}: {exc}")
    return 1

  info(f"added dependency '{name}' to {path}")
  return 0


def ensure_configured(compiler=None):
  _clean_if_compiler_mismatch(compiler)
  if compiler or not build_dir().exists():
    return cmake_configure(compiler)
  return 0


def ensure_built(compiler=None):
  result = ensure_configured(compiler)
  if result != 0:
    return result
  return cmake_build()


def main():
  if len(sys.argv) < 2:
    usage()
    return 2

  command = sys.argv[1]
  if command in {"adddep", "--ad"}:
    args = sys.argv[2:]
    if not args or len(args) > 2:
      error("usage: python pycmkr adddep <name> [git_url]")
      return 2
    name = args[0]
    git_url = args[1] if len(args) == 2 else None
    return _add_dependency(name, git_url)
  args = sys.argv[2:]

  aliases = {
      "cl": "clean",
      "c": "configure",
      "b": "build",
      "r": "run",
      "t": "test",
      "a": "all",
      "i": "init",
      "h": "help",
  }
  command = aliases.get(command, command)

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
  if command == "init":
    if len(args) > 1:
      error("usage: python pycmkr init [path]")
      return 2
    if args:
      path_arg = args[0].strip()
      if not path_arg:
        error("usage: python pycmkr init [path]")
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
  known_configs = ["build_config.json"]
  if config_path:
    config_candidate = Path(config_path).expanduser()
    if allow_missing_config and base_dir and not config_candidate.is_absolute():
      config_candidate = base_dir / config_candidate
    elif not config_candidate.is_absolute():
      config_candidate = Path.cwd() / config_candidate
  elif config_env:
    config_candidate = Path(config_env).expanduser()
    if not config_candidate.is_absolute():
      config_candidate = Path.cwd() / config_candidate
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
    BUILD_CONFIG["config_path"] = config_candidate
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
    if base_dir and not base_dir.exists():
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
    clean_build_dir()
    return 0
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
        error("usage: python pycmkr test [--target name]")
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
