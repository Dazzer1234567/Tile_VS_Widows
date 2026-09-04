"""
vscode_panel.py  -  small always-on-top control panel for your VS Code windows (Windows only, stdlib only)

Buttons:
    Hide all / Max all / Tile
    Max: <project>   one per open VS Code window, maximises it and brings it to front

The button list refreshes itself every 2 s as windows open/close.
Run with pythonw.exe (or rename to .pyw) to avoid a console window.
"""

import base64
import ctypes
import ctypes.wintypes as wt
import math
import os
import re
import tempfile
import tkinter as tk

user32 = ctypes.windll.user32

# ---- config ----------------------------------------------------------------
TITLE_SUFFIX = "Visual Studio Code"      # "Visual Studio Code - Insiders" for Insiders builds
WINDOW_CLASS = "Chrome_WidgetWin_1"
MONITOR = 0                              # 0 = primary
REFRESH_MS = 2000
SHOW_TITLEBAR = True                     # False = frameless; drag with the hand bar, right-click it to quit
# ----------------------------------------------------------------------------

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
GW_OWNER = 4

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    user32.SetProcessDPIAware()

# tell Windows this is its own app, not "python", so the taskbar uses our icon
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("3vee.vscode_panel")
except Exception:
    pass

# four black squares, embedded as a .ico so the script stays a single file
ICON_B64 = (
    "AAABAAUAEBAAAAAAIAAEAQAAVgAAACAgAAAAACAAbAEAAFoBAAAwMAAAAAAgANcBAADGAgAAQEAA"
    "AAAAIAAeAgAAnQQAAAAAAAAAACAARQMAALsGAACJUE5HDQoaCgAAAA1JSERSAAAAEAAAABAIBgAA"
    "AB/z/2EAAADLSURBVHic3ZKxbsMwDER5sjx0cwF71mrk/3+hQP8iX+DN9uTwdagdpBYzZApQLgKP"
    "xxNxOPV9j9WFJLn7CHRN03wDbmbpDwmWFCy/VP9AIJtZaGLQE+FZkgKBAxaQ9qYJeB/Z3cdgG3fX"
    "NE3XUkqa53mUBKATzzPQVfcDZqZSSlrXNQPdgZ2oNw3DEHlgkmzbtgvw2bbt1+9+9ZHlPWHVbPfB"
    "zewGeJREM1tyAN4FHvp0eo8L0vuD9EwgykbETRlYgsGjib5zHKhM/AE1JHHrvplvmgAAAABJRU5E"
    "rkJggolQTkcNChoKAAAADUlIRFIAAAAgAAAAIAgGAAAAc3p69AAAATNJREFUeJztlk1KBDEQhb+X"
    "ziC4lNxHtx7DU7icOYpbl97BA8zWGwxkJw4i9OS5mDT0gD8dEAYkb9VUUq8+Kt2dUkrJtGmUFIG7"
    "nPMDQEppLWljewTiAg8Dsr0LjcX/XB2gA3SADtABIjA25kz753dIqfGlXgYk6RDrxdKiKAngYha7"
    "rD5NXqWUqwjcNQIU2wF4ngKSHm2/cOzEkmOdOvDeWPsfSimldWNOAYKkp5zzFiCldA3csPwIALD9"
    "FiVtGgEIIWB7B2xr6HYYhvtSSpOP7Y9Yx6gWjaWUCMxfoH0pZWwdySTl5k+nKnLa6jDzaZkJ49n/"
    "hB2gA3SAswNETgeLJfI3Of5h7au9AI6AGgFWAHUmYHrWcUpZLfSYaq5ivVQWS9LB9gDsZ+HX6jOt"
    "/SZXiPwJvH16Smd8qcYAAAAASUVORK5CYIKJUE5HDQoaCgAAAA1JSERSAAAAMAAAADAIBgAAAFcC"
    "+YcAAAGeSURBVHic7ZgxTuYwFIRnHAMNzUou9hrbIdFxIg5CQ0HNDfYGFBSc4i92mxUFSrHSiiqZ"
    "ofgd6RcEIZQnWWj9SSnsF83zJHaU91hKMeKYSGZJ1+M4XgLIAARApZQ7khe2ZwDDxjwmSUm7tHXF"
    "rekGWtMNtKYbaE030JpuoDXdQGu6gdZ0A6358gYygClQb9HSSmyu8RnA1jLWAEhyyiTzRrFDckoJ"
    "kk5XYt9SSllSSL6UEqZpKlnSdYRgZQYw2L6vY6E+bdu3kh4kCdu37vIGnjbqtIfYn4NohLfnYKj5"
    "Qln6NtGsHVK/M/9/w1LKXaDeTHKQ9HMcxxvst40AuJRyRfKH7YhDDJKw/SeTvNgq9lqY5G4Z1ssA"
    "zkmeReaR9JhrrzKKCUC2/bwS+2d7juqNYv8Z/ZsDxF4LD1jfIukgV4gB28OX/xfqBlrTDbSmG2hN"
    "N9CabqA13UBruoHWZMQW2sb7xbs/iH82DwA4k4xsdRzVWvXoTUb7OKUU1cZZln2SJe0+uvsTqhP2"
    "C3ysUz6I/bL9vZaVmyuylBJJ/n4BtlCcIEfplKEAAAAASUVORK5CYIKJUE5HDQoaCgAAAA1JSERS"
    "AAAAQAAAAEAIBgAAAKppcd4AAAHlSURBVHic7ZoxbuMwEEX/iJSxi8RRhPWJ9gA5bto0QSoDCbZY"
    "YIs9gV2ms62fwlTgIJbdhPMReF5nkcA8fUsUAY4tFgvCh52ZJZIP6/X6N4AGwADAALDrur5t2/8A"
    "egAs12sxmFlDctlULPItiADUAmoiALWAmghALaAmAlALqIkA1AJqIgC1gJoIQC2gJgJQC6iJANQC"
    "aiIAtYCaCEAtoCYCUAuoyQB2TrXGOsOZOTs4nAyVGkM2s1Sx0CHJzEDy+tggSQNw6+QzuswzyQeH"
    "gsD+n00kn8vvD2eSbdtuANyTnMPnCWgA/KtY43tg0CyEU+vAxS/K7hjqvmtTTPUkKFwuG+u6rneq"
    "RQA2m802q9Xq9ZhL3/c3wzA0qP8VIADLOW9zaUvxYGxLeQRwh88tMl1K6Tml1Dm40MyM5EvGvifH"
    "DZJTN2gAfgGYO7rcZkwvSF/NDvsd2PbEnE3xcdkImdk2Vy50iOH8V+dwvKbXu8vFbzwiALWAmghA"
    "LaAmAlALqIkA1AJqIgC1gJoIQC2gJgJQC6iJANQCaiIAtYCaCEAtoObiA8g43bLylbyfAp2ZM7av"
    "1D4XAEqLjNdT0JS2lB/HBkuLzJWTz+jyM5NcOhQEyskQgD/HBnPOWwBPJG/g1yLz9w3ls37X2Bei"
    "ZwAAAABJRU5ErkJggolQTkcNChoKAAAADUlIRFIAAAEAAAABAAgGAAAAXHKoZgAAAwxJREFUeJzt"
    "3UENxDAMAMHLYQh/hObQkmgVqTtDwH5Y+/Xae18/PmFm1tsz3Mt3zMz6n14COEcAIEwAIEwAIEwA"
    "IEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwA"
    "IEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwA"
    "IEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwA"
    "IEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwA"
    "IEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwA"
    "IEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAIEwAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAOBJa+99nV6CZ8zMenuGe/mOmVleg0GYAECYAECYAECYAECYAECYAECYAECYAECY"
    "AECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECY"
    "AECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECY"
    "AECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECY"
    "AECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECY"
    "AECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECYAECY"
    "AECYAECYAECYAECYAECYAECYAECYAECYAECYAABA0Q1F0RHLUEu7bAAAAABJRU5ErkJggg=="
)


def icon_path():
    path = os.path.join(tempfile.gettempdir(), "vscode_panel.ico")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(base64.b64decode(ICON_B64))
    return path


EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
SPLIT = re.compile(r"\s[-\u2013\u2014]\s")   # " - ", " – ", " — "


def vscode_windows():
    """[(hwnd, title)] for every top-level VS Code window."""
    found = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != WINDOW_CLASS:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value.endswith(TITLE_SUFFIX):
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    found.sort()
    return found


def project_name(title):
    """'file.py - Party_App - Visual Studio Code' -> 'Party_App'."""
    parts = [p.strip() for p in SPLIT.split(title)]
    if parts and parts[-1].startswith(TITLE_SUFFIX.split(" - ")[0]):
        parts.pop()
    parts = [p.lstrip("● ") for p in parts if p]     # strip unsaved-marker
    return parts[-1] if parts else "VS Code"


def work_area():
    rects = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HMONITOR, wt.HDC,
                                         ctypes.POINTER(wt.RECT), wt.LPARAM)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                    ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    def cb(hmon, hdc, lprc, _):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        rects.insert(0 if mi.dwFlags & 1 else len(rects), mi.rcWork)
        return True

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0)
    r = rects[min(MONITOR, len(rects) - 1)]
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def bring_to_front(hwnd):
    # our own button click gives this process foreground rights, so this normally succeeds
    user32.SetForegroundWindow(hwnd)


# ---- actions ---------------------------------------------------------------
def hide_all():
    for h, _ in vscode_windows():
        user32.ShowWindow(h, SW_MINIMIZE)


def max_all():
    """Maximise every VS Code window without changing what's in front."""
    prev = user32.GetForegroundWindow()
    for h, _ in vscode_windows():
        user32.ShowWindow(h, SW_MAXIMIZE)
    if prev:
        user32.SetForegroundWindow(prev)


def tile():
    wins = vscode_windows()
    if not wins:
        return
    n = len(wins)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    x0, y0, W, H = work_area()
    cw, ch = W // cols, H // rows
    for i, (h, _) in enumerate(wins):
        r, c = divmod(i, cols)
        user32.ShowWindow(h, SW_RESTORE)
        user32.SetWindowPos(h, 0, x0 + c * cw, y0 + r * ch, cw, ch,
                            SWP_NOZORDER | SWP_NOACTIVATE)


def maximize(hwnd):
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    bring_to_front(hwnd)


# ---- UI --------------------------------------------------------------------
class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VS Code")
        try:
            self.iconbitmap(icon_path())
        except Exception:
            pass
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(padx=6, pady=6)
        if not SHOW_TITLEBAR:
            self.overrideredirect(True)

        # drag bar
        grip = tk.Label(self, text="\u270b", font=("Segoe UI Emoji", 12),
                        cursor="fleur", bg="#d9d9d9")
        grip.pack(fill="x", pady=(0, 6))
        grip.bind("<ButtonPress-1>", self._drag_start)
        grip.bind("<B1-Motion>", self._drag_move)
        grip.bind("<Button-3>", lambda e: self.destroy())

        top = tk.Frame(self)
        top.pack(fill="x")
        for text, fn in (("Hide all", hide_all), ("Max all", max_all), ("Tile", tile)):
            tk.Button(top, text=text, width=9, command=fn).pack(side="left", padx=2)

        self.list = tk.Frame(self)
        self.list.pack(fill="x", pady=(6, 0))
        self._sig = None
        self.refresh()

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def refresh(self):
        wins = vscode_windows()
        sig = tuple(wins)
        if sig != self._sig:
            self._sig = sig
            for w in self.list.winfo_children():
                w.destroy()
            seen = {}
            for h, t in wins:
                name = project_name(t)
                seen[name] = seen.get(name, 0) + 1
                if seen[name] > 1:
                    name = f"{name} ({seen[name]})"
                tk.Button(self.list, text=f"Max: {name}", anchor="w",
                          command=lambda h=h: maximize(h)).pack(fill="x", pady=1)
            if not wins:
                tk.Label(self.list, text="no VS Code windows").pack()
        self.after(REFRESH_MS, self.refresh)


if __name__ == "__main__":
    Panel().mainloop()
