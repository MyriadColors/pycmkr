import copy
import sys
import pytest  # type: ignore[import-not-found]
import main
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def reset_build_config():
    original = copy.deepcopy(main.BUILD_CONFIG)
    yield
    main.BUILD_CONFIG.clear()
    main.BUILD_CONFIG.update(copy.deepcopy(original))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--type",
        action="store",
        default="all",
        choices=("unit", "integration", "all"),
        help="Select which tests to run: unit, integration, or all.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
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
