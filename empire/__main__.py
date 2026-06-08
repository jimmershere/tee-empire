"""Allow `python -m empire` to launch the CLI (delegates to real cli.py at checkout root)."""
import sys
from pathlib import Path
import runpy

_here = Path(__file__).resolve().parent          # .../tee-empire/empire
_root = _here.parent                             # .../tee-empire (real source root with cli.py, core/, etc.)

# Make the checkout root importable so "import cli", "import core", "from empire.core..." work
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Ensure "empire" and "empire.core" etc. are resolvable as the shim + real subpackages
import types as _types
import importlib.util as _util

# Register the empire package as this shim dir (so empire.cli, empire.core resolve here first)
if "empire" not in sys.modules:
    _emp = _types.ModuleType("empire")
    _emp.__path__ = [str(_here)]
    _emp.__package__ = "empire"
    sys.modules["empire"] = _emp

# Also register empire.core to point at the real core/ dir so "from empire.core import ..." succeeds
_real_core_dir = _root / "core"
if _real_core_dir.is_dir():
    if "empire.core" not in sys.modules:
        _core_pkg = _types.ModuleType("empire.core")
        _core_pkg.__path__ = [str(_real_core_dir)]
        _core_pkg.__package__ = "empire.core"
        sys.modules["empire.core"] = _core_pkg
    # For deeper empire.core.xxx we let normal import machinery find them once the parent is registered
    # and the root is on sys.path (the real core/*.py will be importable as "core.xxx" but we alias below).

# Run the real CLI entrypoint located at the checkout root (cli.py)
runpy.run_path(str(_root / "cli.py"), run_name="__main__")
