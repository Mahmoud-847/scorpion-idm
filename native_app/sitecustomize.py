"""
Starts Scorpion when ScorpionIDM.exe (the signed Python runtime) receives application arguments or
no arguments. Explicit Python diagnostic invocations (a script, -c, ...) are left to Python.
Copied next to scorpion_qt.py in <install>/app, which python314._pth puts on the import path.
"""
import os
import sys

_runtime_args = list(getattr(sys, "orig_argv", ())[1:])
if "--native-messaging" in _runtime_args:
    import json
    import secrets
    import struct

    _base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ScorpionIDM")
    _tok_path = os.path.join(_base, "bridge_token")
    _tok = ""
    try:
        if os.path.isfile(_tok_path):
            with open(_tok_path, "r", encoding="utf-8") as _tf:
                _val = _tf.read().strip()
            if len(_val) >= 32:
                _tok = _val
    except OSError:
        pass
    if not _tok:
        _tok = secrets.token_hex(32)
        try:
            os.makedirs(_base, exist_ok=True)
            _tmp = f"{_tok_path}.{os.getpid()}.tmp"
            with open(_tmp, "w", encoding="utf-8") as _tf:
                _tf.write(_tok)
            os.replace(_tmp, _tok_path)
        except OSError:
            pass
    try:
        with os.fdopen(0, "rb", closefd=False) as _in_f:
            _raw_len = _in_f.read(4)
            if len(_raw_len) == 4:
                _msg_len = struct.unpack("<I", _raw_len)[0]
                if 0 < _msg_len <= 65536:
                    _in_f.read(_msg_len)
    except Exception:
        pass
    _resp = json.dumps({"ok": True, "token": _tok}).encode("utf-8")
    try:
        with os.fdopen(1, "wb", buffering=0, closefd=False) as _out_f:
            _out_f.write(struct.pack("<I", len(_resp)))
            _out_f.write(_resp)
            _out_f.flush()
    except Exception:
        pass
    os._exit(0)

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
