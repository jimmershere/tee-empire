"""Shim so `python -m empire.cli` works.

It ensures the source root is on sys.path, registers the 'empire' namespace,
then executes the real cli.py at the checkout root as the empire.cli module.
"""
import sys
from pathlib import Path
import runpy
import types as _types

_here = Path(__file__).resolve().parent
_root = _here.parent

if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Register empire package
if "empire" not in sys.modules:
    _emp = _types.ModuleType("empire")
    _emp.__path__ = [str(_here)]
    _emp.__package__ = "empire"
    sys.modules["empire"] = _emp

# Register empire.core to point at the real core/ dir so "from empire.core import ..." works
_real_core_dir = _root / "core"
if _real_core_dir.is_dir() and "empire.core" not in sys.modules:
    _core_pkg = _types.ModuleType("empire.core")
    _core_pkg.__path__ = [str(_real_core_dir)]
    _core_pkg.__package__ = "empire.core"
    sys.modules["empire.core"] = _core_pkg

# Execute the real cli.py (the one with the full argument parser and cmd_* functions)
# under the name "empire.cli" so relative behavior inside it is preserved.
runpy.run_path(str(_root / "cli.py"), run_name="empire.cli")
