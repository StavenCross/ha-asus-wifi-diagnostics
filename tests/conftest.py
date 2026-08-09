"""Load pure integration modules without installing Home Assistant."""

import sys
from pathlib import Path
from types import ModuleType

PACKAGE = "custom_components.asus_wifi_diagnostics"
package = ModuleType(PACKAGE)
package.__path__ = [
    str(Path(__file__).parents[1] / "custom_components" / "asus_wifi_diagnostics")
]
sys.modules[PACKAGE] = package
