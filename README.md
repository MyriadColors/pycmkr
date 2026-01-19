# pycmkr: Python-based CMake/C++ Project Build Helper

This tool wraps common C/C++ build tasks behind a consistent CLI. It is intended
to work out of the box for many projects while allowing per-project defaults
via JSON config and environment overrides.

## Installation

### Using pipx (Recommended)

pipx installs the tool in an isolated environment while making it globally available:

```bash
# Install pipx (on Arch Linux)
sudo pacman -S python-pipx

# Install the build tool in editable mode for development
pipx install -e .

# Or install normally
pipx install .
```

### Using pip (Alternative)

Install to your user directory:

```bash
# Install to ~/.local/bin
pip install --user -e .

# Make sure ~/.local/bin is in your PATH
export PATH="$HOME/.local/bin:$PATH"
```

### Note for Arch Linux Users

On Arch and many modern Linux distributions, global pip installs are discouraged
to avoid conflicts with system packages. Use pipx or the `--user` flag as shown above.

## Quick Start

After installation, the `pycmkr` command is available globally:

```bash
pycmkr configure
pycmkr build
pycmkr run
pycmkr test
```

For development or if not installed, you can still run directly:

```bash
python main.py configure
python main.py build
python main.py run
python main.py test
```

## Commands

- `clean` (alias: `cl`) removes the build directory
- `configure` (alias: `c`) generates build files
- `build` (alias: `b`) configures (if needed) and builds
- `run` (alias: `r`) builds (if needed) and runs the main binary
- `test` (alias: `t`) builds (if needed) and runs all configured tests
- `all` (alias: `a`) configures, builds, and runs
- `init` (alias: `i`) creates a starter `CMakeLists.txt`, `build_config.json`, and main source if missing
- `adddep` (alias: `--ad`) adds a dependency (local on Linux or FetchContent)
- `help` (alias: `h`) shows help

## Options

- `--cc <path>`: force a C compiler for configuration
- `--config <path>`: load build defaults from a JSON file

To run a single test target instead of all configured tests, use:

```bash
pycmkr test --target unit_tests
```

## Usage Examples

```bash
# Initialize a new project in the current directory
pycmkr init

# Initialize a new project in a specific directory
pycmkr init ~/projects/my_new_project

# Build with a specific compiler
pycmkr build --cc gcc

# Run with arguments passed to your executable
pycmkr run -- --config app_config.json

# Add a dependency (local lookup on Linux)
pycmkr adddep raylib

# Add a dependency via FetchContent (git URL)
pycmkr adddep raylib https://github.com/raysan5/raylib.git

# Use a custom config file
pycmkr build --config custom_build.json
```

## Init Command

`init` is intended for empty or new C projects. It accepts an optional `path`
argument used for the destination directory; the project name is inferred from
the final path segment. If `path` is omitted, `init` prompts and then creates
the project in the current directory, using the current directory name as the
project name. It only creates files that do not already exist:

- `CMakeLists.txt` (generic template)
- `build_config.json` (defaults + project metadata)
- the first `main_sources` file (defaults to `main.c`)

If you want `init` to use a custom JSON file, pass `--config <path>` and the
project section from that file will be used to generate the CMake template.
If the file does not exist, `init` will create it.

## JSON Config

Example file:

```json
{
  "build_dir": "build",
  "default_test_target": "unit_tests",
  "test_targets": [
    "unit_tests"
  ],
  "dependency_file": "dependencies.cmake",
  "dependency_local_function": "project_add_local_dependency",
  "dependency_fetch_function": "project_add_fetch_dependency",
  "project": {
    "name": "MyProject",
    "languages": [
      "C"
    ],
    "min_cmake": "3.10",
    "c_standard": "23",
    "cxx_standard": null,
    "main_target": "main",
    "main_sources": [
      "main.c"
    ],
    "test_targets": [
      {
        "name": "unit_tests",
        "sources": [
          "unit_tests.c"
        ]
      }
    ],
    "include_dirs": [
      "includes"
    ],
    "definitions": [],
    "compile_options": [],
    "link_libraries": [],
    "extra_cmake_lines": []
  }
}
```

All fields are optional. If omitted, built-in defaults are used.

If `build_config.json` exists in the working directory and no config is
explicitly provided, main.py searches upward from the current directory and
uses the first `build_config.json` it finds. To override that behavior, set
`BUILD_CONFIG_FILE` or pass `--config`.

The directory containing the active config file is treated as the project root.
Relative paths like `build_dir` and `dependency_file` are resolved against that
root. The `dependency_file` path must resolve within the project root; absolute
paths are allowed only if they stay within the root after normalization.

### Project Fields Used by `init`

- `project.name`: CMake project name
- `project.languages`: list of languages (e.g., `["C"]`, `["C", "CXX"]`)
- `project.min_cmake`: minimum CMake version
- `project.c_standard`: C standard to set (or `null` to omit)
- `project.cxx_standard`: C++ standard to set (or `null` to omit)
- `project.main_target`: main executable target name
- `project.main_sources`: sources for the main target
- `project.test_targets`: list of `{ "name": "...", "sources": [...] }`
- `project.include_dirs`: include directories applied to all targets
- `project.definitions`: compile definitions applied to all targets
- `project.compile_options`: compile options applied to all targets
- `project.link_libraries`: link libraries applied to all targets
- `project.extra_cmake_lines`: raw CMake lines appended to the template

## Environment Overrides

- `BUILD_CONFIG_FILE`: load a JSON config without passing `--config`
- `BUILD_DIR`: override `build_dir`
- `MAIN_TARGET`: override `project.main_target`
- `TEST_TARGET`: override `default_test_target`
- `TEST_TARGETS`: override `test_targets` (comma-separated)
- `DEPENDENCY_FILE`: override `dependency_file`
- `DEPENDENCY_LOCAL_FUNCTION`: override `dependency_local_function`
- `DEPENDENCY_FETCH_FUNCTION`: override `dependency_fetch_function`

Environment overrides are applied after the config file.

## Uninstalling

```bash
# If installed with pipx
pipx uninstall pycmkr

# If installed with pip
pip uninstall pycmkr
```
