import copy
import sys
import pytest
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
