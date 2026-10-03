"""
vscode_panel.py  -  small always-on-top control panel for your VS Code windows (Windows only, stdlib only)

Buttons:
    Tile / Max all / Hide all
    Max: <project>   one per open VS Code window, maximises it and brings it to front.
                     The whole row is tinted by claude_hook.py's status:
                     plain idle / amber Claude working / green Claude finished / red Claude needs you

Row colours, all steady - nothing in the panel blinks:
    amber   Claude is working
    green   Claude has stopped and you have not looked at that window yet
    red     Claude is waiting on you (a permission prompt or similar)
    none    nothing to report, or you have opened that window since it finished
Clicking a Max button opens the window and clears its colour.  A sound also plays when a
window turns green or red; see the NOTIFY_* knobs below.

Tile also raises all windows and (optionally) wheel-scrolls the chat panel in each to the bottom,
with a progress bar while it does so.  The button list refreshes every 2 s as windows open/close.
Run with pythonw.exe (or rename to .pyw) to avoid a console window.
"""

import array
import base64
import ctypes
import json
import ctypes.wintypes as wt
import hashlib
import http.server
import math
import os
import platform
import re
import socket
import subprocess
import tempfile
import threading
import time
import wave
import tkinter as tk
import winsound
from tkinter import ttk

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ---- config ----------------------------------------------------------------
TITLE_SUFFIX = "Visual Studio Code"      # "Visual Studio Code - Insiders" for Insiders builds
WINDOW_CLASS = "Chrome_WidgetWin_1"
MONITOR = 0                              # 0 = primary
REFRESH_MS = 1000
STATUS_DIR = os.path.join(tempfile.gettempdir(), "vscode_panel_status")   # written by claude_hook.py
# per-project preferences.  Not in %TEMP% with the status files: those are disposable,
# these are meant to outlive a reboot or a temp sweep.
PREFS_PATH = os.path.join(os.environ.get("APPDATA") or tempfile.gettempdir(),
                          "vscode_panel", "prefs.json")
LOG_PATH = os.path.join(os.path.dirname(PREFS_PATH), "panel.log")
THIS_HOST = platform.node()
LISTEN_PORT = 8765                       # where hooks on other machines POST their status
LISTEN_HOST = ""                         # "" = this machine's Tailscale address if it has
                                         # one, else every interface.  Set to None to not listen.
REMOTE_SSH = ["hal-daw"]                 # ssh targets to PULL status from, for a machine that
                                         # cannot reach us - see pull_from() for why
REMOTE_POLL_S = 2                        # how often the remote end re-reads its own files
REMOTE_RETRY_S = 20                      # wait before reconnecting to a target that dropped
SOUND_ON, SOUND_OFF = "🔊", "🔇"     # speaker / muted speaker
SOUND_ON_BG, SOUND_OFF_BG = "#1f6feb", "#e5484d"      # blue when sounding, red when muted
SOUND_FONT = ("Segoe UI Emoji", 12)      # speaker on a card
EAR_FONT = ("Segoe UI Emoji", 12)        # the preview button, which has room to be bigger
FIELD_FONT = ("Segoe UI", 9)             # card text: Max button and both boxes.
                                         # 9 is the Windows default - do not go below it,
                                         # a shorter card is not worth unreadable text
GRIP_SCALE = 1.6                         # drag bar height, as a multiple of its natural one
RESTART_GLYPH = "\U0001F501"              # the restart toggle, beside the app path
RESTART_FONT = ("Segoe UI Emoji", 9)     # smaller, so it sits level with the path box
RESTART_ON_BG = "#f0862b"                # orange when the restart is armed
RESTART_OFF_BG = "#b0b0b0"               # grey when it is off - nothing is wrong, it is idle
CARET_DOWN, CARET_UP = "\u25be", "\u25b4"
# (frequency Hz, milliseconds) per alert.  Rising = finished, falling = wants you.
SOUND_TONES = {"done": [(660, 90), (880, 150)], "waiting": [(760, 90), (570, 170)]}
SOUND_PEAK = 0.6                         # tone amplitude at slider 100, of full scale
VOLUME_DEFAULT = 60                      # slider 0-100; 60 matches the old fixed level
VOLUME_SAVE_MS = 500                     # idle after dragging before saving and re-rendering
SPEAK_VOICE = ""                         # "" = Windows default; e.g. "Microsoft Zira Desktop"
SPEAK_RATE = 0                           # SAPI rate, -10 (slow) to 10 (fast)
SAY_WIDTH = 14                           # minimum width of the spoken-text box, in characters
RESTART_GRACE_MS = 1500                  # how long an app gets to close itself before being killed
RESTART_DELAY_MS = 4000                  # settle time after a conversation stops, before restarting
LOG_MAX_BYTES = 1000000                  # panel.log is rolled to panel.log.1 past this
BAD_PATH_BG = "#ffd7d5"                  # restart box tint when the path does not exist
SAY_SAVE_MS = 800                        # idle time after typing before the phrase is saved
EAR = "👂"                        # preview button
# row background per state; "idle" means the panel's normal background
STATUS_COLORS = {"idle": None, "working": "#f0b429", "done": "#3ad35a", "waiting": "#ff5a4d"}
NOTIFY_ON = ("done", "waiting")          # states that raise an alert; set to () to stay silent
NOTIFY_SOUND = True                      # master switch; each row also has its own speaker toggle
NOTIFY_TOAST = False                     # Windows tray notification popup; off - the row and the sound are enough
NOTIFY_FLASH_TASKBAR = False             # flash the panel's taskbar button; off - nothing here should blink
SCROLL_TO_BOTTOM = True                  # after tiling, wheel-scroll the chat panel in each window to the end
SCROLL_POINTS = [(0.80, 0.50)]           # (x, y) as fraction of window size: where the chat panel lives
SCROLL_NOTCHES = 40                      # wheel clicks per point; more = reaches the bottom of longer chats
SCROLL_STEP_MS = 15                      # gap between wheel clicks; too fast and the webview coalesces them
SETTLE_MS = 300                          # wait after resizing before scrolling, so VS Code has re-laid out
SHOW_TITLEBAR = True                     # False = frameless; drag with the hand bar, right-click it to quit
# ----------------------------------------------------------------------------

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
GW_OWNER = 4
MOUSEEVENTF_MOVE, MOUSEEVENTF_WHEEL = 0x0001, 0x0800
CREATE_NO_WINDOW = 0x08000000            # keep PowerShell from flashing a console
DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP = 0x00000008, 0x00000200
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE = 0x1000, 0x0001
WM_CLOSE = 0x0010
FLASHW_STOP, FLASHW_ALL, FLASHW_TIMERNOFG = 0x0, 0x3, 0xC
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_ICON, NIF_TIP, NIF_INFO = 0x02, 0x04, 0x10
NIIF_INFO, IDI_APPLICATION = 0x1, 32512
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x0010, 0x0040

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


# ---- win32 structs ---------------------------------------------------------
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                ("ptMinPosition", POINT), ("ptMaxPosition", POINT),
                ("rcNormalPosition", wt.RECT)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT), ("_pad", ctypes.c_byte * 8)]


def send_mouse(flags, data=0, dx=0, dy=0):
    inp = INPUT(type=0, mi=MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, None))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", wt.WCHAR * 260)]


class FLASHWINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("hwnd", wt.HWND), ("dwFlags", wt.DWORD),
                ("uCount", wt.UINT), ("dwTimeout", wt.DWORD)]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wt.HICON)]


# HANDLE-returning calls must say so, or the value is truncated on 64-bit
user32.LoadImageW.restype = wt.HANDLE
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CreateMutexW.restype = wt.HANDLE
user32.LoadIconW.restype = wt.HICON

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
SPLIT = re.compile(r"\s[-\u2013\u2014]\s")   # " - ", " – ", " — "


# ---- window discovery ------------------------------------------------------
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
    """SetForegroundWindow that works on other processes' windows (AttachThreadInput trick)."""
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    if fg_thread and fg_thread != me:
        user32.AttachThreadInput(me, fg_thread, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if fg_thread and fg_thread != me:
        user32.AttachThreadInput(me, fg_thread, False)


def place(hwnd, x, y, w, h):
    """Restore (if minimised/maximised) and move/resize in one atomic call."""
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
    wp.showCmd = SW_RESTORE
    wp.rcNormalPosition = wt.RECT(x, y, x + w, y + h)
    user32.SetWindowPlacement(hwnd, ctypes.byref(wp))


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
        bring_to_front(prev)


def maximize(hwnd):
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    bring_to_front(hwnd)


def tile():
    """Grid the windows and raise them all. Returns the window list for the scroll phase."""
    wins = vscode_windows()
    if not wins:
        return []
    n = len(wins)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    x0, y0, W, H = work_area()
    cw, ch = W // cols, H // rows
    for i, (h, _) in enumerate(wins):
        r, c = divmod(i, cols)
        place(h, x0 + c * cw, y0 + r * ch, cw, ch)
    for h, _ in wins:                      # raise each in turn; last one ends up focused
        bring_to_front(h)
    return wins


def scroll_steps(wins):
    """Generator: one wheel click per step, moving the cursor into each window's chat panel first."""
    for h, _ in wins:
        rc = wt.RECT()
        user32.GetWindowRect(h, ctypes.byref(rc))
        for fx, fy in SCROLL_POINTS:
            x = rc.left + int((rc.right - rc.left) * fx)
            y = rc.top + int((rc.bottom - rc.top) * fy)
            user32.SetCursorPos(x, y)
            send_mouse(MOUSEEVENTF_MOVE, dx=1, dy=0)    # real move event so the webview sees a hover
            send_mouse(MOUSEEVENTF_MOVE, dx=-1, dy=0)
            yield
            for _ in range(SCROLL_NOTCHES):
                send_mouse(MOUSEEVENTF_WHEEL, data=-120)
                yield


def read_statuses():
    """{label: record} from the files claude_hook.py writes, locally or over HTTP.

    The label is the bare project name for a session on this machine, and
    "<host>: <project>" for one on another, so two machines running a project of the
    same name cannot overwrite each other in the UI or in your saved phrases.

    Each record keeps its timestamp, which matters: two Stops in a row write the same
    state, and comparing states alone would see no change and fire nothing.  That
    happens whenever the "working" in between is not caught by the poll - any turn
    shorter than REFRESH_MS - and silently skipped the phrase and the app restart."""
    out = {}
    if not os.path.isdir(STATUS_DIR):
        return out
    for fn in os.listdir(STATUS_DIR):
        path = os.path.join(STATUS_DIR, fn)
        try:
            with open(path) as f:
                d = json.load(f)
            host = d.get("host") or THIS_HOST       # files from before hosts were stamped
            remote = host.lower() != THIS_HOST.lower()
            project = d["project"]
            label = "%s: %s" % (host, project) if remote else project
            when = d.get("time", 0)
            # Two files can map to one label - a pre-host-stamp file and its replacement
            # both read as local - and the newest has to win.  Letting the last one seen
            # win meant a frozen old record could shadow the live one: its (state, time)
            # never changes, so no transition is ever detected and nothing fires at all.
            if label in out and out[label]["time"] >= when:
                continue
            out[label] = {"state": d["state"], "time": when, "host": host,
                          "project": project, "remote": remote, "path": path}
        except Exception:
            pass
    return out


def stamps(states):
    """Just the (state, time) of each label, which is what a transition compares."""
    return {label: (r["state"], r["time"]) for label, r in states.items()}


def status_name(host, project):
    """The file name a record lands under.  Shared with claude_hook.py, and with the
    remote cleanup in ack_remote(), which has to name a file on another machine."""
    return re.sub(r"[^\w.-]", "_", "%s~%s" % (host, project)) + ".json"


ACKED = {}                      # (host, project) -> newest record time acknowledged


def save_status(record):
    """Store a record that arrived from elsewhere exactly where a local one would go, so
    everything downstream - colours, phrases, transitions - needs no special case.

    A record no newer than the one you acknowledged is dropped: the pull prints every
    file every couple of seconds, so a line already in flight would otherwise revive a
    card the moment after you cleared it."""
    key = (record.get("host", "?"), record["project"])
    if record.get("time", 0) <= ACKED.get(key, 0):
        return
    os.makedirs(STATUS_DIR, exist_ok=True)
    path = os.path.join(STATUS_DIR, status_name(record.get("host", "?"), record["project"]))
    with open(path, "w") as f:
        json.dump(record, f)


LOG_LOCK = threading.Lock()


def log(msg):
    """Append a line to panel.log.  Never raises - logging must not break the panel."""
    try:
        with LOG_LOCK:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
                os.replace(LOG_PATH, LOG_PATH + ".1")
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def read_prefs():
    """Everything the panel remembers between runs, as one dict.  A dict rather than a
    tuple because every new setting was changing the signature and all five call sites."""
    d = {"muted": set(), "say": {}, "run": {}, "run_off": set(),
         "volume": VOLUME_DEFAULT, "vol_open": False}
    try:
        with open(PREFS_PATH) as f:
            raw = json.load(f)
        d["muted"] = set(raw.get("muted", []))
        d["say"] = dict(raw.get("say", {}))
        d["run"] = dict(raw.get("run", {}))
        d["run_off"] = set(raw.get("run_off", []))
        d["volume"] = max(0, min(100, int(raw.get("volume", VOLUME_DEFAULT))))
        d["vol_open"] = bool(raw.get("vol_open", False))
    except Exception:
        pass                        # first run, or an unreadable file: use the defaults
    return d


def write_prefs(d):
    try:
        os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
        with open(PREFS_PATH, "w") as f:
            json.dump({"muted": sorted(d["muted"]), "say": d["say"], "run": d["run"],
                       "run_off": sorted(d["run_off"]), "volume": d["volume"],
                       "vol_open": d["vol_open"]}, f)
    except Exception:
        pass                        # a preference is not worth crashing the panel over


def clear_status(label, states=None):
    """Delete whichever file backs this label.  Looked up rather than recomputed from
    the name: the file is named by host and project, which the label alone does not give."""
    record = (states if states is not None else read_statuses()).get(label)
    if not record:
        return
    try:
        os.remove(record["path"])
    except OSError:
        pass


# ---- status from other machines --------------------------------------------
PANEL = None                    # the running Panel, so the web view can read its phrases
ACK_QUEUE = []                  # labels the web view asked to clear, drained on the UI thread


def web_cards():
    """What the page renders.  Window actions and the app restart are deliberately not
    exposed: raising a window on this machine is meaningless from a browser elsewhere,
    and restarting an app from a phone is a good way to kill something by accident."""
    now = time.time()
    cards = []
    for label, r in sorted(read_statuses().items()):
        cards.append({"label": label, "project": r["project"], "host": r["host"],
                      "state": r["state"], "remote": r["remote"],
                      "age": max(0, int(now - r["time"])),
                      "phrase": (PANEL.say.get(label, "") if PANEL else "")})
    return {"host": THIS_HOST, "cards": cards}


SINGLE_INSTANCE = None          # the mutex handle, held for the life of the process


def claim_single_instance():
    """False if a panel is already running.

    Worth enforcing: Windows lets a second process bind the listener port that the first
    one already holds, so two panels do not fail loudly - they quietly split incoming
    requests between them, and both act on every finish, restarting the app twice.  With
    the panel starting automatically and a shortcut on the Desktop, running two became
    easy to do by accident."""
    global SINGLE_INSTANCE
    SINGLE_INSTANCE = kernel32.CreateMutexW(None, False, "vscode_panel_single_instance")
    return kernel32.GetLastError() != 183            # ERROR_ALREADY_EXISTS


def tailscale_ip():
    """This machine's Tailscale address, if it has one.  Binding to that rather than to
    every interface keeps the listener off the LAN and off anything public."""
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            octets = ip.split(".")
            if octets[0] == "100" and 64 <= int(octets[1]) <= 127:  # Tailscale's CGNAT range
                return ip
    except Exception:
        pass
    return ""


WEB_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude sessions</title>
<style>
 :root { --bg:#f4f4f5; --fg:#18181b; --card:#ffffff; --line:#d4d4d8; --dim:#71717a; }
 @media (prefers-color-scheme: dark) {
   :root { --bg:#18181b; --fg:#f4f4f5; --card:#27272a; --line:#3f3f46; --dim:#a1a1aa; }
 }
 * { box-sizing:border-box; }
 body { margin:0; padding:16px; background:var(--bg); color:var(--fg);
        font:15px/1.4 "Segoe UI",system-ui,sans-serif; }
 h1 { font-size:17px; margin:0 0 4px; font-weight:600; }
 .sub { color:var(--dim); font-size:12px; margin:0 0 16px; }
 .card { background:var(--card); border:1px solid var(--line); border-radius:8px;
         padding:10px 12px; margin-bottom:8px; cursor:pointer; -webkit-tap-highlight-color:transparent; }
 .card:active { transform:scale(.995); }
 .working { background:#f0b429; color:#18181b; border-color:#d9a21f; }
 .done    { background:#3ad35a; color:#18181b; border-color:#2fb84c; }
 .waiting { background:#ff5a4d; color:#18181b; border-color:#e5484d; }
 .name { font-weight:600; }
 .meta { font-size:12px; opacity:.8; margin-top:2px; }
 .empty { color:var(--dim); font-style:italic; }
 .tag { font-size:11px; border:1px solid currentColor; border-radius:4px;
        padding:0 4px; margin-left:6px; opacity:.75; }
</style></head><body>
<h1>Claude sessions</h1>
<p class="sub" id="sub">connecting...</p>
<div id="cards"></div>
<script>
const AGO = s => s < 60 ? s + "s ago" : s < 3600 ? Math.floor(s/60) + "m ago"
                 : Math.floor(s/3600) + "h ago";
async function ack(label) {
  await fetch("api/ack", {method:"POST", headers:{"Content-Type":"application/json"},
                          body: JSON.stringify({label})});
  tick();
}
async function tick() {
  let d;
  try { d = await (await fetch("api/cards", {cache:"no-store"})).json(); }
  catch (e) { document.getElementById("sub").textContent = "panel unreachable"; return; }
  document.getElementById("sub").textContent =
    "on " + d.host + " \\u00b7 " + d.cards.length + " session" +
    (d.cards.length === 1 ? "" : "s") + " \\u00b7 tap a card to clear it";
  const box = document.getElementById("cards");
  if (!d.cards.length) { box.innerHTML = '<p class="empty">nothing reporting</p>'; return; }
  box.innerHTML = d.cards.map(c =>
    '<div class="card ' + c.state + '" onclick="ack(' + JSON.stringify(c.label).replace(/"/g,"&quot;") + ')">' +
      '<div class="name">' + esc(c.project) +
        (c.remote ? '<span class="tag">' + esc(c.host) + '</span>' : '') + '</div>' +
      '<div class="meta">' + c.state + " \\u00b7 " + AGO(c.age) +
        (c.phrase ? " \\u00b7 \\u201c" + esc(c.phrase) + "\\u201d" : "") + '</div>' +
    '</div>').join("");
}
function esc(t) { const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }
tick(); setInterval(tick, 2000);
</script></body></html>
"""


class StatusHandler(http.server.BaseHTTPRequestHandler):
    """Accepts one POST per hook event from a panel-less machine."""

    def _send(self, code, ctype, body=b""):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        route = self.path.split("?")[0].rstrip("/") or "/"
        if route in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", WEB_PAGE.encode("utf-8"))
        elif route == "/api/cards":
            self._send(200, "application/json",
                       json.dumps(web_cards()).encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self):
        route = self.path.split("?")[0].rstrip("/") or "/"
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if route == "/api/ack":
                label = body.get("label", "")
                if label:
                    # queued rather than acted on here: this runs on an HTTP thread and
                    # acknowledging touches Tk widgets, which only the UI thread may do
                    ACK_QUEUE.append(label)
                    log("web view cleared %s" % label)
                self._send(204, "text/plain")
                return
            record = body
            if not record.get("project") or not record.get("state"):
                raise ValueError("missing project or state")
            record.setdefault("host", self.client_address[0])
            record.setdefault("time", time.time())
            save_status(record)
            log("received from %s: %s = %s"
                % (record["host"], record["project"], record["state"]))
            self._send(204, "text/plain")
        except Exception as exc:
            log("rejected a POST from %s: %r" % (self.client_address[0], exc))
            self._send(400, "text/plain; charset=utf-8", b"bad request")

    def log_message(self, *args):
        pass                        # the panel has its own log; keep http.server quiet


def start_listener():
    """Serve on a daemon thread.  Returns the address it bound to, or "" if it could not."""
    if LISTEN_HOST is None:
        return ""
    host = LISTEN_HOST or tailscale_ip()
    try:
        server = http.server.ThreadingHTTPServer((host, LISTEN_PORT), StatusHandler)
    except OSError as exc:
        log("could not listen on %s:%d - %s" % (host or "*", LISTEN_PORT, exc))
        return ""
    threading.Thread(target=server.serve_forever, daemon=True).start()
    where = "%s:%d" % (host or "*", LISTEN_PORT)
    log("listening for remote status on %s" % where)
    return where


# the remote end just prints each of its status files, once per REMOTE_POLL_S
REMOTE_STREAM = (
    "while ($true) { "
    "Get-ChildItem \"$env:TEMP\\vscode_panel_status\\*.json\" -ErrorAction SilentlyContinue | "
    "ForEach-Object { (Get-Content $_.FullName -Raw) -replace '\\s+',' ' }; "
    "Start-Sleep -Seconds %d }"
)


def pull_from(target):
    """Stream another machine's status files in over SSH, forever.

    A machine on a different Tailscale account cannot open connections to us - sharing
    grants traffic one way only - so it cannot POST.  SSH from here to it does work, so
    its records are pulled rather than pushed.  One long-lived connection that prints a
    line per file, rather than a process per poll, and it is re-established if the
    machine sleeps or reboots."""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30",
           "-o", "StrictHostKeyChecking=accept-new", target, REMOTE_STREAM % REMOTE_POLL_S]
    while True:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW, text=True,
                                    encoding="utf-8", errors="replace")
            log("pulling status from %s over ssh" % target)
            for line in proc.stdout:
                line = line.strip()
                if not line.startswith("{"):
                    continue                    # ssh banners and the like
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if record.get("project") and record.get("state"):
                    save_status(record)
            proc.wait()
            log("ssh pull from %s ended" % target)
        except Exception as exc:
            log("ssh pull from %s failed: %r" % (target, exc))
        time.sleep(REMOTE_RETRY_S)


def forget_remote(target, host, project):
    """Delete the status file on the machine it came from, so the pull stops restoring it.
    Acknowledging a remote card has to reach across, or it would turn green again in
    REMOTE_POLL_S seconds and never clear."""
    remote = "Remove-Item -Force -ErrorAction SilentlyContinue " \
             "\"$env:TEMP\\vscode_panel_status\\%s\"" % status_name(host, project)
    try:
        subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, remote],
                       creationflags=CREATE_NO_WINDOW, timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("cleared %s on %s" % (project, host))
    except Exception as exc:
        log("could not clear %s on %s: %r" % (project, host, exc))


# ---- close and reopen an app ------------------------------------------------
def process_path(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None                 # protected or already gone
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wt.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(h)
    return None


ALIAS_IMAGE = {}                # configured path -> what it really runs as, learned on launch
LAUNCHED = {}                   # configured path -> PIDs we started, so we can always find them


def stale_image(full, base):
    """True when a process named `base` is running from an image that is no longer the
    file it was started from - it has been deleted, renamed, or moved to the Recycle Bin.

    That is what a rebuild does: replacing the exe while it runs leaves the process with
    an image path under $Recycle.Bin with a mangled name.  Strict path matching then
    stops recognising it, so the old build is never closed and a second instance is
    launched beside it - every rebuild, forever.  It stays safe because a genuinely
    different program of the same name has an image that still exists where it is."""
    if full is None:
        return True                         # cannot be inspected at all
    if os.path.normcase(os.path.basename(full)) != base:
        return True                         # renamed out from under the process
    try:
        return not os.path.isfile(full)
    except OSError:
        return True


def scan_for(path):
    """[(pid, image, why)] for every running instance of `path`.

    Matched on the full image path rather than the file name: matching a target like
    python.exe by name would kill unrelated processes machine-wide.  Also matched are
    the image a Windows execution alias resolved to, and same-named processes whose own
    image has gone (see stale_image)."""
    target = os.path.normcase(os.path.abspath(path))
    wanted = {target, ALIAS_IMAGE.get(target)} - {None}
    base = os.path.normcase(os.path.basename(target))
    me, found = os.getpid(), []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wt.HANDLE(-1).value:
        return found
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = entry.th32ProcessID
            # compare the cheap name first; only then open the process for its full path
            if pid != me and os.path.normcase(entry.szExeFile) == base:
                full = process_path(pid)
                if full and os.path.normcase(full) in wanted:
                    found.append((pid, full, "path"))
                elif pid in LAUNCHED.get(target, ()):
                    found.append((pid, full, "we launched it"))
                elif stale_image(full, base):
                    found.append((pid, full, "image gone - rebuilt?"))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return found


def pids_of(path):
    return [pid for pid, _image, _why in scan_for(path)]


def windows_of(pid):
    out = []

    @EnumWindowsProc
    def each(hwnd, _):
        got = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(got))
        if got.value == pid and user32.IsWindowVisible(hwnd):
            out.append(hwnd)
        return True

    user32.EnumWindows(each, 0)
    return out


def close_app(path, rounds=3):
    """Ask every instance to close, terminate any that ignored it, then check again.

    One pass is not enough to be reliable: an app can spawn a replacement as it exits,
    a launcher can start the real process a moment later, and an instance still opening
    when the first sweep ran would be missed entirely."""
    closed = 0
    for round_no in range(1, rounds + 1):
        found = scan_for(path)
        if not found:
            log("   round %d: nothing running" % round_no)
            break
        closed = max(closed, len(found))
        for pid, image, why in found:
            log("   round %d: pid %-7s matched by %-20s image=%s"
                % (round_no, pid, why, image))
        for pid, _image, _why in found:
            wins = windows_of(pid)
            for hwnd in wins:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)   # let it shut down tidily
            log("      pid %-7s sent WM_CLOSE to %d window(s)" % (pid, len(wins)))
        deadline = time.time() + RESTART_GRACE_MS / 1000    # no longer than it needs
        while time.time() < deadline and pids_of(path):
            time.sleep(0.1)
        for pid in pids_of(path):                           # whatever is still standing
            h = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if h:
                ok = kernel32.TerminateProcess(h, 0)
                kernel32.CloseHandle(h)
                log("      pid %-7s terminated (ok=%s)" % (pid, bool(ok)))
            else:
                log("      pid %-7s COULD NOT OPEN to terminate - error %d%s"
                    % (pid, ctypes.get_last_error(),
                       "; it is probably elevated, so the panel would have to be too"))
        time.sleep(0.25)                                    # let the kernel reap them
    return closed


def launch_app(path):
    """Start it, remembering the PID - so a later rebuild that moves the exe out from
    under it cannot stop us recognising our own instance - and note what it actually
    runs as, for when the path given is an execution alias pointing elsewhere."""
    proc = subprocess.Popen([path], cwd=os.path.dirname(path) or None, close_fds=True,
                            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    key = os.path.normcase(os.path.abspath(path))
    LAUNCHED.setdefault(key, set()).add(proc.pid)
    for _ in range(20):
        image = process_path(proc.pid)
        if image:
            if os.path.normcase(image) != key:
                ALIAS_IMAGE[key] = os.path.normcase(image)
                log("      alias: runs as %s" % image)
            log("      launched pid %d" % proc.pid)
            return
        time.sleep(0.1)
    log("      launched pid %d (image not readable yet)" % proc.pid)


RESTART_LOCK = threading.Lock()


def restart_app(path, project=""):
    """Close every instance of `path`, then start it again.  Runs on a worker thread:
    it sleeps through the settle delay and grace period and must not block the UI.

    Serialised, because two finishes close together would otherwise interleave - one
    thread's sweep killing the instance the other had just launched."""
    if not os.path.isfile(path):
        log("restart %s: SKIPPED, not a file: %s" % (project, path))
        return
    time.sleep(RESTART_DELAY_MS / 1000)     # let the app settle before touching it
    with RESTART_LOCK:
        log("restart %s: %s" % (project, path))
        try:
            closed = close_app(path)
            launch_app(path)
            time.sleep(1.0)
            after = scan_for(path)
            log("   done: closed %d, now running %d -> %s"
                % (closed, len(after), [pid for pid, _i, _w in after]))
            if len(after) > 1:
                log("   WARNING: more than one instance is running")
        except Exception as exc:
            log("   FAILED: %r" % (exc,))


# ---- notifications ---------------------------------------------------------
def flash_taskbar(hwnd, on=True):
    """Flash the panel's taskbar button; FLASHW_TIMERNOFG stops once it is foreground."""
    fw = FLASHWINFO(ctypes.sizeof(FLASHWINFO), wt.HWND(hwnd),
                    (FLASHW_ALL | FLASHW_TIMERNOFG) if on else FLASHW_STOP, 0, 0)
    user32.FlashWindowEx(ctypes.byref(fw))


def write_tone(path, tones, volume, rate=44100):
    """A small WAV of (freq, ms) tones, each under a raised-cosine envelope so the
    edges do not click.  Generated rather than shipped, like the icon."""
    frames = array.array("h")
    for freq, ms in tones:
        n = int(rate * ms / 1000)
        for i in range(n):
            env = 0.5 - 0.5 * math.cos(2 * math.pi * min(i, n - i) / n)
            frames.append(int(32767 * SOUND_PEAK * volume / 100 * env
                              * math.sin(2 * math.pi * freq * i / rate)))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames.tobytes())


def alert_wav(state, volume):
    path = os.path.join(tempfile.gettempdir(), "vscode_panel_%s_%d.wav" % (state, volume))
    if not os.path.exists(path):
        write_tone(path, SOUND_TONES.get(state, SOUND_TONES["done"]), volume)
    return path


def ps_quote(text):
    """Quote for a PowerShell single-quoted string: only ' needs escaping."""
    return "'" + str(text).replace("'", "''") + "'"


def say_wav(text, volume):
    """Where this phrase at this volume lives.  Keyed by both: PlaySound has no volume
    control, so level must be baked in at synthesis, and keying the cache this way keeps
    playback a plain PlaySound rather than rewriting the file on every play."""
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), "vscode_panel_say_%s_%d.wav" % (digest, volume))


def render_speech(text, volume):
    """Synthesise `text` to a cached WAV with SAPI, via PowerShell so the panel keeps
    to the standard library.  Done once when you edit the text - never at alert time,
    where it would add a second of latency - so speaking then costs no more than a beep."""
    path = say_wav(text, volume)
    if os.path.exists(path):
        return path
    script = ("Add-Type -AssemblyName System.Speech;"
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              + ("$s.SelectVoice(%s);" % ps_quote(SPEAK_VOICE) if SPEAK_VOICE else "")
              + "$s.Rate = %d;" % SPEAK_RATE
              + "$s.Volume = %d;" % volume
              + "$s.SetOutputToWaveFile(%s);" % ps_quote(path)
              + "$s.Speak(%s);" % ps_quote(text)
              + "$s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       creationflags=CREATE_NO_WINDOW, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    return path if os.path.exists(path) else None


def speak(text, volume):
    """Play the cached rendering of `text`.  If this volume has not been rendered yet,
    start it in the background and report failure, so the caller beeps this once and
    speaks from then on."""
    path = say_wav(text, volume)
    if not os.path.exists(path):
        threading.Thread(target=render_speech, args=(text, volume), daemon=True).start()
        return False
    try:
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return True
    except Exception:
        return False


def play_alert(state, volume):
    """Play our own WAV rather than MessageBeep.  MessageBeep plays whatever the
    Windows sound scheme maps to SystemAsterisk / SystemExclamation, so on a machine
    set to "No Sounds" - normal on an audio workstation - it is silent."""
    try:
        winsound.PlaySound(alert_wav(state, volume),
                           winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        winsound.MessageBeep()


class Tray:
    """A tray icon, used only as somewhere for balloon/toast notifications to come from."""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.added = False

    def _nid(self, flags):
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = wt.HWND(self.hwnd)
        nid.uID = 1
        nid.uFlags = flags
        return nid

    def _add(self):
        nid = self._nid(NIF_ICON | NIF_TIP)
        nid.szTip = "VS Code panel"
        try:
            nid.hIcon = user32.LoadImageW(None, icon_path(), IMAGE_ICON, 0, 0,
                                          LR_LOADFROMFILE | LR_DEFAULTSIZE)
        except Exception:
            nid.hIcon = user32.LoadIconW(None, IDI_APPLICATION)
        self.added = bool(ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        return self.added

    def notify(self, title, text):
        if not self.added and not self._add():
            return
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_INFO
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def remove(self):
        if self.added:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
            self.added = False


def logo_image(size=16, gap=2):
    """The four-black-squares mark as a PhotoImage, drawn pixel-wise so it needs no file.
    Unpainted pixels stay transparent, so the button's background shows through."""
    img = tk.PhotoImage(width=size, height=size)
    cell = (size - gap) // 2
    for x in (0, cell + gap):
        for y in (0, cell + gap):
            img.put("#000000", to=(x, y, x + cell, y + cell))
    return img


# ---- UI --------------------------------------------------------------------
class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VS Code")
        try:
            self.iconbitmap(icon_path())
        except Exception:
            pass
        # prefs first: the volume slider below is built from them
        prefs = read_prefs()
        self.muted, self.say, self.run = prefs["muted"], prefs["say"], prefs["run"]
        self.run_off, self.volume = prefs["run_off"], prefs["volume"]
        self.vol_open = prefs["vol_open"]
        self._vol_job = None                # pending debounced save of the volume
        self._jobs = {}                     # pending debounced saves, per text field

        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(padx=6, pady=6)
        if not SHOW_TITLEBAR:
            self.overrideredirect(True)

        # drag bar
        grip = tk.Label(self, text="\u270b", font=("Segoe UI Emoji", 12),
                        cursor="fleur", bg="#d9d9d9")
        grip.pack(fill="x", pady=(0, 6))
        # GRIP_SCALE times its natural height, so it stays an easy target.  Derived from
        # reqheight rather than a pixel constant so it scales at any DPI or font size.
        self.update_idletasks()
        grip.pack_configure(ipady=int(grip.winfo_reqheight() * (GRIP_SCALE - 1) / 2))
        grip.bind("<ButtonPress-1>", self._drag_start)
        grip.bind("<B1-Motion>", self._drag_move)
        grip.bind("<Button-3>", lambda e: self.close())

        top = tk.Frame(self)
        top.pack(fill="x")
        self.buttons = []
        self.logo = logo_image()            # keep a reference or Tk garbage-collects it
        for text, fn, img in (("Tile", self.tile, self.logo),
                              ("Max all", max_all, None),
                              ("Hide all", hide_all, None)):
            b = tk.Button(top, text=text, image=img, compound="right", padx=6, command=fn)
            # expand rather than a fixed width: with an image, width would mean pixels
            b.pack(side="left", padx=2, fill="x", expand=True)
            self.buttons.append(b)

        # the caret rides with the three buttons, fixed width so they keep the rest
        self.more_btn = tk.Button(top, text=CARET_DOWN, width=2, padx=0,
                                  command=self.toggle_extras)
        self.more_btn.pack(side="left", padx=(2, 0))
        self.buttons.append(self.more_btn)

        # everything the caret reveals: preview and volume, hidden until asked for
        self.extras = tk.Frame(self)
        self.ear = tk.Button(self.extras, text=EAR, font=EAR_FONT, width=2,
                             command=self.preview)
        self.ear.pack(side="left", padx=2)
        self.buttons.append(self.ear)
        self.vol_scale = tk.Scale(self.extras, from_=0, to=100, orient="horizontal",
                                  showvalue=True, label="Voice volume",
                                  font=("Segoe UI", 7), command=self.volume_changed)
        self.vol_scale.set(self.volume)
        self.vol_scale.pack(side="left", fill="x", expand=True, padx=2)

        # not packed: it is only meaningful during a tile, and sitting there the rest of
        # the time put an empty bar and its padding between the buttons and the first card
        self.progress = ttk.Progressbar(self, mode="determinate")

        self.list = tk.Frame(self)
        self.list.pack(fill="x")
        self.show_extras(self.vol_open)     # needs list to exist, to pack before it
        self._sig = None
        self._busy = False

        # notifications: seed from what is already on disk so a status file left
        # over from a previous run does not fire the moment the panel starts
        self._states = stamps(read_statuses())
        self._bg = self.cget("bg")          # what an idle row looks like
        self._hwnd = self.panel_hwnd()
        self._tray = Tray(self._hwnd)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<FocusIn>", lambda e: self.stop_flash())

        log("--- panel started: pid %d, host %s, elevated=%s ---"
            % (os.getpid(), THIS_HOST, bool(ctypes.windll.shell32.IsUserAnAdmin())))
        global PANEL
        PANEL = self                    # so the web view can read the phrases
        self.listening = start_listener()
        for target in REMOTE_SSH:
            threading.Thread(target=pull_from, args=(target,), daemon=True).start()
        self.refresh()

    def save(self):
        """Write every remembered setting.  One place, so a new one needs no new callers."""
        write_prefs({"muted": self.muted, "say": self.say, "run": self.run,
                     "run_off": self.run_off, "volume": self.volume,
                     "vol_open": self.vol_open})

    def panel_hwnd(self):
        self.update_idletasks()
        try:
            return int(self.wm_frame(), 16)     # the top-level frame, not Tk's client window
        except Exception:
            return user32.GetParent(self.winfo_id()) or self.winfo_id()

    def close(self):
        self.save()                             # flush anything mid-debounce
        self._tray.remove()
        self.destroy()

    # -- tile with scroll-to-bottom phase
    def tile(self):
        if self._busy:
            return
        wins = tile()
        if not wins or not SCROLL_TO_BOTTOM:
            return
        self._busy = True
        self.progress.pack(fill="x", pady=(4, 0), before=self.list)
        self._set_buttons("disabled")
        self._saved = POINT()
        user32.GetCursorPos(ctypes.byref(self._saved))
        total = len(wins) * len(SCROLL_POINTS) * (SCROLL_NOTCHES + 1)
        self.progress.configure(maximum=total, value=0)
        self._steps = scroll_steps(wins)
        self.after(SETTLE_MS, self._scroll_tick)

    def _scroll_tick(self):
        try:
            next(self._steps)
            self.progress.step(1)
            self.after(SCROLL_STEP_MS, self._scroll_tick)
        except StopIteration:
            user32.SetCursorPos(self._saved.x, self._saved.y)
            self.progress.configure(value=0)
            self.progress.pack_forget()
            self._set_buttons("normal")
            self._busy = False

    def _set_buttons(self, state):
        def buttons(w):                     # the row buttons sit inside a head frame now
            for c in w.winfo_children():
                if isinstance(c, tk.Button):
                    yield c
                yield from buttons(c)
        for b in self.buttons + list(buttons(self.list)):
            b.configure(state=state)

    # -- drag bar
    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    # -- per-window buttons
    def refresh(self):
        wins = vscode_windows()
        states = read_statuses()
        # a remote session has no window here, so the signature has to notice it
        # appearing or going away, or its card would never be built
        remotes = sorted(l for l, r in states.items() if r["remote"])
        sig = (tuple((h, project_name(t)) for h, t in wins), tuple(remotes))
        if sig != self._sig and not self._busy:
            self._sig = sig
            for w in self.list.winfo_children():
                w.destroy()
            self.rows = {}                      # label -> [{widget name: widget}, ...]
            seen = {}
            for h, t in wins:
                proj = project_name(t)
                name = proj
                seen[name] = seen.get(name, 0) + 1
                if seen[name] > 1:
                    name = f"{name} ({seen[name]})"
                row = tk.Frame(self.list)
                row.pack(fill="x", pady=1)
                head = tk.Frame(row)            # speaker + Max button
                head.pack(fill="x")
                mute = tk.Button(head, font=SOUND_FONT, width=2, relief="flat", bd=1,
                                 padx=0, pady=0,
                                 command=lambda p=proj: self.toggle_sound(p))
                mute.pack(side="left", padx=(1, 0))
                btn = tk.Button(head, text=f"Max: {name}", anchor="w", relief="flat", bd=1,
                                font=FIELD_FONT, pady=0,
                                command=lambda h=h, p=proj: self.focus_window(h, p))
                btn.pack(side="left", fill="x", expand=True, padx=1)
                say = tk.Entry(row, width=SAY_WIDTH, font=FIELD_FONT)   # phrase, underneath
                say.insert(0, self.say.get(proj, ""))
                say.pack(fill="x", padx=1, pady=(1, 0))
                self._bind_field("say", proj, say)
                run_row = tk.Frame(row)                 # toggle + app to restart
                run_row.pack(fill="x", pady=(1, 1))
                rbtn = tk.Button(run_row, text=RESTART_GLYPH, font=RESTART_FONT, width=2,
                                 relief="flat", bd=1, padx=0, pady=0,
                                 command=lambda p=proj: self.toggle_restart(p))
                rbtn.pack(side="left", padx=(1, 0))
                run = tk.Entry(run_row, width=SAY_WIDTH, font=FIELD_FONT)
                run.insert(0, self.run.get(proj, ""))
                run.pack(side="left", fill="x", expand=True, padx=1)
                self._bind_field("run", proj, run)
                # a list: two windows can share a folder name, and the hook writes one
                # status file per name, so both rows must show that same state
                self.rows.setdefault(proj, []).append(
                    {"row": row, "head": head, "btn": btn, "mute": mute,
                     "say": say, "run": run, "rbtn": rbtn})
            for label in remotes:
                self.rows.setdefault(label, []).append(self._remote_card(label))
            if not wins and not remotes:
                tk.Label(self.list, text="no VS Code windows").pack()
        self.update_lights()
        self.after(REFRESH_MS, self.refresh)

    def _remote_card(self, label):
        """A session on another machine: colour, sound and phrase, but no window
        controls.  There is nothing here to raise, and no app here to restart - firing
        the restart would close and relaunch something on the wrong computer."""
        row = tk.Frame(self.list)
        row.pack(fill="x", pady=1)
        head = tk.Frame(row)
        head.pack(fill="x")
        mute = tk.Button(head, font=SOUND_FONT, width=2, relief="flat", bd=1,
                         padx=0, pady=0, command=lambda l=label: self.toggle_sound(l))
        mute.pack(side="left", padx=(1, 0))
        # a button, but it acknowledges rather than raising a window: there is no
        # window here to raise, and a remote card needs some way to be cleared
        name = tk.Button(head, text=label, anchor="w", relief="flat", bd=1,
                         font=FIELD_FONT, pady=0,
                         command=lambda l=label: self.ack_remote(l))
        name.pack(side="left", fill="x", expand=True, padx=1)
        say = tk.Entry(row, width=SAY_WIDTH, font=FIELD_FONT)
        say.insert(0, self.say.get(label, ""))
        say.pack(fill="x", padx=1, pady=(1, 1))
        self._bind_field("say", label, say)
        return {"row": row, "head": head, "btn": name, "mute": mute, "say": say}

    def web_ack(self, label):
        """Clear a card on behalf of the web view, local or remote."""
        record = read_statuses().get(label)
        if record and record["remote"]:
            self.ack_remote(label)
        else:
            clear_status(label)
            self._states.pop(label, None)

    def ack_remote(self, label):
        """Clear a remote card: locally, and on the machine that reported it."""
        states = read_statuses()
        record = states.get(label)
        clear_status(label, states)
        if record:
            ACKED[(record["host"], record["project"])] = record["time"]
        if record and REMOTE_SSH:
            threading.Thread(target=forget_remote,
                             args=(REMOTE_SSH[0], record["host"], record["project"]),
                             daemon=True).start()
        self._states.pop(label, None)
        self.update_lights()

    def focus_window(self, hwnd, project):
        maximize(hwnd)
        # Opening a window only settles a state that has stopped changing.  "working"
        # is still in progress, so it stays amber until the hook says otherwise -
        # clearing it would blank the row while Claude is still going.
        states = read_statuses()
        if states.get(project, {}).get("state") != "working":
            clear_status(project, states)   # you've looked at it; the row goes back to plain
            self._states.pop(project, None)
        self.stop_flash()
        self.update_lights()

    def update_lights(self):
        while ACK_QUEUE:                # cleared from the web view, on this thread
            self.web_ack(ACK_QUEUE.pop(0))
        states = read_statuses()
        for label, record in states.items():
            if (record["state"] in NOTIFY_ON
                    and self._states.get(label) != (record["state"], record["time"])):
                self.alert(label, record["state"], record)
        self._states = stamps(states)
        for label, widgets in getattr(self, "rows", {}).items():
            record = states.get(label)
            colour = STATUS_COLORS.get(record["state"] if record else "idle") or self._bg
            muted = label in self.muted
            icon = SOUND_OFF if muted else SOUND_ON
            sound_bg = SOUND_OFF_BG if muted else SOUND_ON_BG
            path = self.run.get(label, "").strip()
            bad = bool(path) and not os.path.isfile(path)   # say so, rather than silently no-op
            run_bg = RESTART_OFF_BG if label in self.run_off else RESTART_ON_BG
            for w in widgets:
                w["row"].configure(bg=colour)
                w["head"].configure(bg=colour)
                w["btn"].configure(bg=colour)
                if isinstance(w["btn"], tk.Button):
                    w["btn"].configure(activebackground=colour)
                w["mute"].configure(text=icon, bg=sound_bg, activebackground=sound_bg)
                if "run" in w:                  # a remote card has no restart controls
                    w["run"].configure(bg=BAD_PATH_BG if bad else "white")
                    w["rbtn"].configure(bg=run_bg, activebackground=run_bg)

    def show_extras(self, open_):
        """Preview and volume are wanted rarely, so they stay collapsed behind the caret
        and the panel stays compact.  They pack before the progress bar rather than at
        the end, which is where pack would otherwise put them - below the project rows."""
        self.vol_open = open_
        if open_:
            self.extras.pack(fill="x", pady=(4, 0), before=self.list)
        else:
            self.extras.pack_forget()
        self.more_btn.configure(text=CARET_UP if open_ else CARET_DOWN)

    def toggle_extras(self):
        self.show_extras(not self.vol_open)
        self.save()

    def volume_changed(self, value):
        """Fires on every pixel of the drag, so the real work is debounced."""
        self.volume = int(float(value))
        if self._vol_job:
            self.after_cancel(self._vol_job)
        self._vol_job = self.after(VOLUME_SAVE_MS, self.volume_settled)

    def volume_settled(self):
        """Save, and re-render every phrase at the new level in the background - so the
        next alert speaks straight away instead of falling back to a beep once."""
        self._vol_job = None
        self.save()
        for text in set(self.say.values()):
            text = text.strip()
            if text and not os.path.exists(say_wav(text, self.volume)):
                threading.Thread(target=render_speech, args=(text, self.volume), daemon=True).start()

    def preview(self):
        """Speak the name of the top project, so you can set the level by ear."""
        if not self.rows:
            return
        name = next(iter(self.rows))
        threading.Thread(target=self._preview, args=(name, self.volume), daemon=True).start()

    def _preview(self, name, volume):
        render_speech(name, volume)         # usually already cached; cheap when not
        speak(name, volume)

    def _bind_field(self, which, project, entry):
        """Both boxes behave alike: saved as you type, Enter leaves the box."""
        entry.bind("<KeyRelease>", lambda e: self.field_typed(which, project, entry))
        entry.bind("<Return>",     lambda e: self.field_done(which, project, entry, leave=True))
        entry.bind("<FocusOut>",   lambda e: self.field_done(which, project, entry))

    def field_typed(self, which, project, entry):
        """Mirror each keystroke into memory - so a row rebuild mid-sentence restores
        what you had - and queue a save.  Debounced rather than tied to Enter or
        focus-out: typing and then shutting down used to lose it."""
        getattr(self, which)[project] = entry.get()
        job = self._jobs.get(which)
        if job:
            self.after_cancel(job)
        self._jobs[which] = self.after(SAY_SAVE_MS, lambda: self.field_store(which, project))

    def field_done(self, which, project, entry, leave=False):
        """Enter or clicking away: save now rather than waiting out the debounce."""
        getattr(self, which)[project] = entry.get()
        self.field_store(which, project)
        if leave:
            entry.selection_clear()
            self.focus_set()            # Enter drops you out of the box
            return "break"

    def field_store(self, which, project):
        """Persist, and for a phrase render it once, off the UI thread."""
        job = self._jobs.pop(which, None)
        if job:
            self.after_cancel(job)
        store = getattr(self, which)
        text = store.get(project, "").strip()
        if which == "run":
            text = text.strip(chr(34))  # Explorer's "Copy as path" wraps it in quotes
        if text:
            store[project] = text
        else:
            store.pop(project, None)
        self.save()
        if which == "say" and text and not os.path.exists(say_wav(text, self.volume)):
            threading.Thread(target=render_speech, args=(text, self.volume), daemon=True).start()

    def toggle_restart(self, project):
        """Switch the close-and-reopen off for this project, leaving the path in place
        so it is still there when you want it back."""
        self.run_off.symmetric_difference_update({project})
        log("%s: restart-on-finish %s"
            % (project, "OFF" if project in self.run_off else "on"))
        self.save()
        self.update_lights()

    def toggle_sound(self, project):
        """Switch this project's green/red sound on or off, and remember it."""
        self.muted.symmetric_difference_update({project})
        self.save()
        self.update_lights()

    def alert(self, project, state, record=None):
        """A window just changed to a state worth interrupting you for."""
        if NOTIFY_SOUND and project not in self.muted:
            text = self.say.get(project, "").strip()
            # the phrase is for "it has stopped"; red keeps its own falling tone
            if not (state == "done" and text and speak(text, self.volume)):
                play_alert(state, self.volume)
        if (record or {}).get("remote"):
            return                      # the app, if any, lives on the other machine
        if state == "done" and project not in self.run_off:
            path = self.run.get(project, "").strip()
            if path:                    # threaded: it sleeps out the settle delay
                log("%s finished; restart queued in %.0fs" % (project, RESTART_DELAY_MS / 1000))
                threading.Thread(target=restart_app, args=(path, project), daemon=True).start()
        if NOTIFY_TOAST:
            self._tray.notify("Claude Code",
                              "%s: %s" % (project, "finished" if state == "done" else "needs you"))
        if NOTIFY_FLASH_TASKBAR:
            flash_taskbar(self._hwnd, True)

    def stop_flash(self):
        if NOTIFY_FLASH_TASKBAR:
            flash_taskbar(self._hwnd, False)



if __name__ == "__main__":
    if not claim_single_instance():
        log("a panel is already running; this one is exiting")
    else:
        Panel().mainloop()
