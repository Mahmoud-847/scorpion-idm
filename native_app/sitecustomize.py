"""
Starts Scorpion when ScorpionIDM.exe (the signed Python runtime) is launched without arguments, as
shortcuts and the in-app updater do. Every other launch (with a script, -c, ...) is left to Python.
Copied next to scorpion_qt.py in <install>/app, which python314._pth puts on the import path.
"""
import os
import sys

if len(getattr(sys, "orig_argv", ())) == 1 and os.path.basename(sys.executable).lower() == "scorpionidm.exe":
    import runpy

    _script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scorpion_qt.py")
    sys.argv = [_script]
    _code = 0
    try:
        runpy.run_path(_script, run_name="__main__")
    except SystemExit as exc:
        _code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    # Leave here: returning would let Python continue into its (invisible) interactive mode
    os._exit(_code)
