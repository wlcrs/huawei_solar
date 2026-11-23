"""Make the integration importable as custom_components.huawei_solar for the tests."""

import sys
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="huawei_solar_tests_"))
(_ROOT / "custom_components").mkdir()
(_ROOT / "custom_components" / "__init__.py").touch()
(_ROOT / "custom_components" / "huawei_solar").symlink_to(
    Path(__file__).resolve().parent.parent
)
sys.path.insert(0, str(_ROOT))
