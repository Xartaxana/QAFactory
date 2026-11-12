"""The driver golden's hook installer (t-301 N0). Python imports a module named `sitecustomize` found on
PYTHONPATH at startup, so every process of a recorded test (the test, the driver, the scripts, the `claude`
stub) loads the recorder with no cooperation from the code under test.

Inert unless DRIVER_GOLDEN_SINK is set: a process started without it behaves exactly as without this file. A
sitecustomize that already exists elsewhere on sys.path is imported after ours (E15: the golden never changes
the interpreter's own startup silently); if that import fails, the failure is raised, not swallowed.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if os.environ.get("DRIVER_GOLDEN_SINK"):
    sys.dont_write_bytecode = True               # before the library is compiled: nothing lands in the package
    try:
        _load("driver_trace", os.path.join(os.path.dirname(_HERE), "driver_trace.py")).install()
    except Exception as exc:                      # a recorder that did not load must say so, never pass silently
        try:
            marker = os.path.join(os.environ["DRIVER_GOLDEN_SINK"],
                                  "hook-error-%s.txt" % os.environ.get("DRIVER_GOLDEN_SPAWN", "0"))
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("%s: %s" % (type(exc).__name__, exc))
        except OSError:
            pass
        raise

for _entry in sys.path:
    _candidate = os.path.join(_entry or ".", "sitecustomize.py")
    if os.path.isfile(_candidate) and os.path.abspath(os.path.dirname(_candidate)) != _HERE:
        _load("sitecustomize_shadowed", _candidate)
        break
