"""Load pure integration modules without installing Home Assistant."""

import sys
from importlib.util import find_spec
from pathlib import Path
from types import ModuleType

PACKAGE = "custom_components.asus_wifi_diagnostics"
package = ModuleType(PACKAGE)
package.__path__ = [
    str(Path(__file__).parents[1] / "custom_components" / "asus_wifi_diagnostics")
]
sys.modules[PACKAGE] = package

if find_spec("asyncssh") is None:
    asyncssh = ModuleType("asyncssh")

    class AsyncSshError(Exception):
        """Minimal asyncssh error used by pure unit tests."""

    asyncssh.Error = AsyncSshError
    asyncssh.PermissionDenied = AsyncSshError
    asyncssh.SSHClientConnection = object
    sys.modules["asyncssh"] = asyncssh
