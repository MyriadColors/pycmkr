import sys
from pathlib import Path

import pytest  # type: ignore[import-not-found]

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pycmkr import cli as main  # noqa: E402


@pytest.fixture(autouse=True)
def reset_build_config():
    original_manager = main.BuildConfigManager.from_dict(main.config_manager.to_dict())
    main.config_manager = main.BuildConfigManager()
    yield
    main.config_manager = original_manager


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--type",
        action="store",
        default="all",
        choices=("unit", "integration", "all"),
        help="Select which tests to run: unit, integration, or all.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    selected = config.getoption("--type")
    if selected == "all":
        return

    skip_integration = pytest.mark.skip(reason="skipped by --type unit")
    skip_unit = pytest.mark.skip(reason="skipped by --type integration")

    for item in items:
        is_integration = item.get_closest_marker("integration") is not None
        if selected == "unit" and is_integration:
            item.add_marker(skip_integration)
        elif selected == "integration" and not is_integration:
            item.add_marker(skip_unit)
