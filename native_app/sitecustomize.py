"""
Starts Scorpion when ScorpionIDM.exe (the signed Python runtime) receives application arguments or
no arguments. Explicit Python diagnostic invocations (a script, -c, ...) are left to Python.
Copied next to scorpion_qt.py in <install>/app, which python314._pth puts on the import path.
"""
import os
import sys

_runtime_args = list(getattr(sys, "orig_argv", ())[1:])
_app_request = not _runtime_args or _runtime_args[0] == "--tray" or (
    _runtime_args[0].lower().startswith(("magnet:?", "http://", "https://")) or _runtime_args[0].lower().endswith(".torrent")
)
if _app_request and os.path.basename(sys.executable).lower() == "scorpionidm.exe":
    import runpy

    _script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scorpion_qt.py")
    sys.argv = [_script, *_runtime_args]
    _code = 0
    try:
        runpy.run_path(_script, run_name="__main__")
    except SystemExit as exc:
        _code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException:
        import traceback
        _log_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ScorpionIDM")
        os.makedirs(_log_dir, exist_ok=True)
        with open(os.path.join(_log_dir, "startup_error.log"), "a", encoding="utf-8") as _log:
            traceback.print_exc(file=_log)
        _code = 1
    # Leave here: returning would let Python continue into its (invisible) interactive mode
    os._exit(_code)
