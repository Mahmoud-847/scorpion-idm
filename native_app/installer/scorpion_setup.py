# -*- coding: utf-8 -*-
"""Scorpion Download Manager - Setup wizard (per-user install, no admin rights needed)."""
import os
import sys
import json
import time
import zipfile
import threading
import subprocess
import urllib.request
import ctypes
from ctypes import wintypes
import winreg
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "Scorpion Download Manager"
APP_VERSION = "2.0.0"
EXE_NAME = "ScorpionIDM.exe"
INSTALL_DIR = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "ScorpionIDM")
DATA_DIR = os.path.join(os.environ["LOCALAPPDATA"], "ScorpionIDM")
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ScorpionIDM"
DESKTOP_LNK = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
STARTMENU_LNK = os.path.join(
    os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", f"{APP_NAME}.lnk"
)


def resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def make_shortcut(lnk_path: str, target_path: str, work_dir: str, icon_path: str):
    """Creates a Windows .lnk shortcut in pure Python via Win32 COM (IShellLinkW + IPersistFile)."""
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    try:
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8),
            ]

            def __init__(self, d1, d2, d3, d4):
                super().__init__(d1, d2, d3, (wintypes.BYTE * 8)(*d4))

        CLSID_ShellLink = GUID(0x00021401, 0x0000, 0x0000, [0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46])
        IID_IShellLinkW = GUID(0x000214F9, 0x0000, 0x0000, [0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46])
        IID_IPersistFile = GUID(0x0000010B, 0x0000, 0x0000, [0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46])

        psl = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_ShellLink), None, 1, ctypes.byref(IID_IShellLinkW), ctypes.byref(psl)
        )
        if hr != 0 or not psl:
            return False

        vtbl = ctypes.cast(ctypes.cast(psl, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        WSTRING_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        ICON_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int)
        QI_FN = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
        )
        REL_FN = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)

        WSTRING_FN(vtbl[20])(psl, target_path)
        WSTRING_FN(vtbl[9])(psl, work_dir)
        WSTRING_FN(vtbl[7])(psl, APP_NAME)
        ICON_FN(vtbl[17])(psl, icon_path, 0)

        ppf = ctypes.c_void_p()
        hr = QI_FN(vtbl[0])(psl, ctypes.byref(IID_IPersistFile), ctypes.byref(ppf))
        if hr == 0 and ppf:
            ppf_vtbl = ctypes.cast(
                ctypes.cast(ppf, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p)
            )
            SAVE_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.BOOL)
            os.makedirs(os.path.dirname(lnk_path), exist_ok=True)
            SAVE_FN(ppf_vtbl[6])(ppf, lnk_path, True)
            REL_FN(ppf_vtbl[2])(ppf)

        REL_FN(vtbl[2])(psl)
        return os.path.exists(lnk_path)
    except Exception:
        return False
    finally:
        ole32.CoUninitialize()


def _terminate_processes_by_name(names: tuple):
    """Uses Win32 Toolhelp32 API in memory (no taskkill.exe subprocess) to close remaining processes."""
    try:
        k32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002
        PROCESS_TERMINATE = 0x0001
        SYNCHRONIZE = 0x00100000

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == wintypes.HANDLE(-1).value:
            return
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        my_pid = os.getpid()
        targets = {n.lower() for n in names}
        handles = []
        if k32.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                if pe.th32ProcessID != my_pid and pe.szExeFile.lower() in targets:
                    h = k32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pe.th32ProcessID)
                    if h:
                        k32.TerminateProcess(h, 0)
                        handles.append(h)
                if not k32.Process32NextW(snap, ctypes.byref(pe)):
                    break
        k32.CloseHandle(snap)
        for h in handles:
            k32.WaitForSingleObject(h, 3000)
            k32.CloseHandle(h)
    except Exception:
        pass


def stop_running_app_and_wait():
    """Closes any running Scorpion instance and waits until its files are 100% unlocked."""
    try:
        # The app's local bridge only accepts /quit with the trusted-client header
        req = urllib.request.Request("http://127.0.0.1:19615/quit", headers={"X-Scorpion-Client": "1"})
        urllib.request.urlopen(req, timeout=1.2).read()
    except Exception:
        pass

    exe_path = os.path.join(INSTALL_DIR, EXE_NAME)
    for attempt in range(12):
        if not os.path.exists(exe_path):
            break
        try:
            with open(exe_path, "r+b"):
                break
        except OSError:
            if attempt == 3:
                _terminate_processes_by_name((EXE_NAME, "aria2c.exe"))
            time.sleep(0.3)

    # Clean up any leftover .old_ files from a previous update
    if os.path.isdir(INSTALL_DIR):
        for root, _, files in os.walk(INSTALL_DIR):
            for fn in files:
                if ".old_" in fn:
                    try:
                        os.remove(os.path.join(root, fn))
                    except Exception:
                        pass


def extract_member_safely(zf: zipfile.ZipFile, member: zipfile.ZipInfo, dest_dir: str):
    """Extracts a zip member, renaming any locked existing file first so extraction never skips a file."""
    target_path = os.path.normpath(os.path.join(dest_dir, member.filename))
    for attempt in range(8):
        try:
            zf.extract(member, dest_dir)
            return
        except PermissionError:
            if os.path.isfile(target_path):
                try:
                    old_path = f"{target_path}.old_{int(time.time() * 1000)}_{attempt}"
                    os.replace(target_path, old_path)
                except Exception:
                    pass
            _terminate_processes_by_name((EXE_NAME, "aria2c.exe"))
            time.sleep(0.25)
    # Final attempt (raises if still blocked so the user is never left with a partial install)
    zf.extract(member, dest_dir)


def register_uninstall(exe: str, size_kb: int):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "Scorpion")
        winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, exe)
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, INSTALL_DIR)
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, f'"{exe}" --uninstall')
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


class SetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION} Setup")
        self.geometry("580x450")
        self.resizable(False, False)
        self.configure(bg="#f1f5f9")
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass

        header = tk.Frame(self, bg="#1e293b", height=90)
        header.pack(fill="x")
        tk.Label(header, text="🦂 Scorpion Download Manager", fg="#f8fafc", bg="#1e293b",
                 font=("Segoe UI", 18, "bold")).pack(pady=(18, 0))
        tk.Label(header, text=f"Version {APP_VERSION} — High-Speed Multi-Connection Download Manager", fg="#94a3b8",
                 bg="#1e293b", font=("Segoe UI", 10)).pack(pady=(2, 14))

        body = tk.Frame(self, bg="#f1f5f9")
        body.pack(fill="both", expand=True, padx=24, pady=16)

        tk.Label(body, text="Destination Folder:", bg="#f1f5f9",
                 font=("Segoe UI", 10, "bold"), anchor="w", justify="left").pack(fill="x")
        path_entry = tk.Entry(body, font=("Consolas", 10), relief="solid", bd=1)
        path_entry.insert(0, INSTALL_DIR)
        path_entry.configure(state="readonly")
        path_entry.pack(fill="x", pady=(4, 12), ipady=4)

        self.var_desktop = tk.BooleanVar(value=True)
        self.var_launch = tk.BooleanVar(value=True)
        self.var_startup = tk.BooleanVar(value=True)
        self.var_assoc = tk.BooleanVar(value=True)
        tk.Checkbutton(body, text="Create a Desktop shortcut", variable=self.var_desktop,
                       bg="#f1f5f9", font=("Segoe UI", 10), anchor="w").pack(fill="x")
        tk.Checkbutton(body, text="Start with Windows (runs in the tray to catch browser downloads)", variable=self.var_startup,
                       bg="#f1f5f9", font=("Segoe UI", 10), anchor="w").pack(fill="x")
        tk.Checkbutton(body, text="Open .torrent files and Magnet links with Scorpion", variable=self.var_assoc,
                       bg="#f1f5f9", font=("Segoe UI", 10), anchor="w").pack(fill="x")
        tk.Checkbutton(body, text="Launch Scorpion Download Manager after installation", variable=self.var_launch,
                       bg="#f1f5f9", font=("Segoe UI", 10), anchor="w").pack(fill="x")

        self.progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(14, 4))
        self.lbl_status = tk.Label(body, text="Ready to install", bg="#f1f5f9", fg="#475569",
                                   font=("Segoe UI", 9), anchor="w")
        self.lbl_status.pack(fill="x")

        btns = tk.Frame(self, bg="#f1f5f9")
        btns.pack(fill="x", padx=24, pady=(0, 16))
        self.btn_install = tk.Button(btns, text="Install", width=14, bg="#2563eb", fg="white",
                                     activebackground="#1d4ed8", activeforeground="white",
                                     font=("Segoe UI", 10, "bold"), relief="flat", command=self.start)
        self.btn_install.pack(side="right")
        self.btn_cancel = tk.Button(btns, text="Cancel", width=10, font=("Segoe UI", 10),
                                    relief="flat", command=self.destroy)
        self.btn_cancel.pack(side="right", padx=8)

    def set_status(self, text: str, pct: float):
        self.after(0, lambda: (self.lbl_status.configure(text=text), self.progress.configure(value=pct)))

    def start(self):
        self.btn_install.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")
        threading.Thread(target=self.do_install, daemon=True).start()

    def do_install(self):
        try:
            self.set_status("Closing running instance if any...", 3)
            stop_running_app_and_wait()

            os.makedirs(INSTALL_DIR, exist_ok=True)

            total_size = 0
            with zipfile.ZipFile(resource("payload.zip")) as zf:
                members = zf.infolist()
                n = max(1, len(members))
                for i, m in enumerate(members, 1):
                    extract_member_safely(zf, m, INSTALL_DIR)
                    total_size += m.file_size
                    if i % 25 == 0 or i == n:
                        self.set_status(f"Extracting files... ({i}/{n})", 8 + 80 * i / n)

            exe = os.path.join(INSTALL_DIR, EXE_NAME)
            icon = os.path.join(INSTALL_DIR, "build", "icon.ico")
            self.set_status("Creating shortcuts...", 92)
            make_shortcut(STARTMENU_LNK, exe, INSTALL_DIR, icon)
            if self.var_desktop.get():
                make_shortcut(DESKTOP_LNK, exe, INSTALL_DIR, icon)

            self.set_status("Registering application in Windows...", 97)
            register_uninstall(exe, total_size // 1024)
            self.write_prefs()

            self.set_status("Installation completed successfully!", 100)
            self.after(0, self.finish)
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror("Installation Error", err))
            self.after(0, lambda: (self.btn_install.configure(state="normal"),
                                   self.btn_cancel.configure(state="normal")))

    def write_prefs(self):
        """Save user choices so ScorpionIDM.exe applies shell integration cleanly on launch."""
        os.makedirs(DATA_DIR, exist_ok=True)
        old_bat = os.path.join(DATA_DIR, "uninstall.bat")
        if os.path.exists(old_bat):
            try:
                os.remove(old_bat)
            except Exception:
                pass
        with open(os.path.join(DATA_DIR, "install_prefs.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "startWithWindows": bool(self.var_startup.get()),
                    "associateTorrents": bool(self.var_assoc.get()),
                    "desktopShortcut": bool(self.var_desktop.get()),
                },
                f,
            )

    def finish(self):
        messagebox.showinfo("Setup Complete", f"{APP_NAME} has been installed successfully!")
        if self.var_launch.get():
            subprocess.Popen([os.path.join(INSTALL_DIR, EXE_NAME)], cwd=INSTALL_DIR)
        self.destroy()


def run_silent_update():
    """Applies an update without wizard prompts and restarts ScorpionIDM.exe."""
    stop_running_app_and_wait()
    os.makedirs(INSTALL_DIR, exist_ok=True)
    total_size = 0
    with zipfile.ZipFile(resource("payload.zip")) as zf:
        for m in zf.infolist():
            extract_member_safely(zf, m, INSTALL_DIR)
            total_size += m.file_size
    exe = os.path.join(INSTALL_DIR, EXE_NAME)
    icon = os.path.join(INSTALL_DIR, "build", "icon.ico")
    make_shortcut(STARTMENU_LNK, exe, INSTALL_DIR, icon)
    if os.path.exists(DESKTOP_LNK):
        make_shortcut(DESKTOP_LNK, exe, INSTALL_DIR, icon)
    register_uninstall(exe, total_size // 1024)
    if os.path.exists(exe):
        subprocess.Popen([exe], cwd=INSTALL_DIR)


if __name__ == "__main__":
    if "--silent-update" in sys.argv:
        run_silent_update()
    else:
        SetupWizard().mainloop()
