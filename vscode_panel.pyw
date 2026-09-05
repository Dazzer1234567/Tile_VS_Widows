"""
vscode_panel.py  -  small always-on-top control panel for your VS Code windows (Windows only, stdlib only)

Buttons:
    Tile / Max all / Hide all
    Max: <project>   one per open VS Code window, maximises it and brings it to front.
                     The whole row is tinted by claude_hook.py's status:
                     plain idle / amber Claude working / green Claude finished / red Claude needs you

When a window turns green (Claude finished) or red (Claude needs you) the panel notifies you:
a system sound, a tray notification, a flashing taskbar button, and a blinking dot until you
click that window's Max button.  See the NOTIFY_* knobs below.

Tile also raises all windows and (optionally) wheel-scrolls the chat panel in each to the bottom,
with a progress bar while it does so.  The button list refreshes every 2 s as windows open/close.
Run with pythonw.exe (or rename to .pyw) to avoid a console window.
"""

import base64
import ctypes
import json
import ctypes.wintypes as wt
import math
import os
import re
import tempfile
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
# row background per state; "idle" means the panel's normal background
STATUS_COLORS = {"idle": None, "working": "#f0b429", "done": "#3ad35a", "waiting": "#ff5a4d"}
NOTIFY_ON = ("done", "waiting")          # states that raise an alert; set to () to stay silent
NOTIFY_SOUND = True                      # play a system sound
NOTIFY_TOAST = False                     # Windows tray notification popup; off - the row and the sound are enough
NOTIFY_FLASH_TASKBAR = True              # flash the panel's taskbar button until you look at the panel
NOTIFY_BLINK_ROW = True                  # flash that window's whole row until you click its Max button
BLINK_MS = 450                           # blink half-period
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
    "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"
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
    """{project name: state} from the files claude_hook.py writes."""
    out = {}
    if not os.path.isdir(STATUS_DIR):
        return out
    for fn in os.listdir(STATUS_DIR):
        try:
            with open(os.path.join(STATUS_DIR, fn)) as f:
                d = json.load(f)
            out[d["project"]] = d["state"]
        except Exception:
            pass
    return out


def clear_status(project):
    safe = re.sub(r"[^\w.-]", "_", project)
    try:
        os.remove(os.path.join(STATUS_DIR, safe + ".json"))
    except OSError:
        pass


# ---- notifications ---------------------------------------------------------
def flash_taskbar(hwnd, on=True):
    """Flash the panel's taskbar button; FLASHW_TIMERNOFG stops once it is foreground."""
    fw = FLASHWINFO(ctypes.sizeof(FLASHWINFO), wt.HWND(hwnd),
                    (FLASHW_ALL | FLASHW_TIMERNOFG) if on else FLASHW_STOP, 0, 0)
    user32.FlashWindowEx(ctypes.byref(fw))


def play_alert(state):
    winsound.MessageBeep(winsound.MB_ICONASTERISK if state == "done"
                         else winsound.MB_ICONEXCLAMATION)


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

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", pady=(6, 0))

        self.list = tk.Frame(self)
        self.list.pack(fill="x", pady=(6, 0))
        self._sig = None
        self._busy = False

        # notifications: seed from what is already on disk so a status file left
        # over from a previous run does not fire the moment the panel starts
        self._states = read_statuses()
        self._alerted = set()               # projects with an alert you have not acknowledged
        self._blink = False
        self._bg = self.cget("bg")          # what an idle row looks like
        self._hwnd = self.panel_hwnd()
        self._tray = Tray(self._hwnd)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<FocusIn>", lambda e: self.stop_flash())

        self.refresh()
        self._blink_tick()

    def panel_hwnd(self):
        self.update_idletasks()
        try:
            return int(self.wm_frame(), 16)     # the top-level frame, not Tk's client window
        except Exception:
            return user32.GetParent(self.winfo_id()) or self.winfo_id()

    def close(self):
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
            self._set_buttons("normal")
            self._busy = False

    def _set_buttons(self, state):
        rows = [b for f in self.list.winfo_children() for b in f.winfo_children()]
        for b in self.buttons + rows:
            if isinstance(b, tk.Button):
                b.configure(state=state)

    # -- drag bar
    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    # -- per-window buttons
    def refresh(self):
        wins = vscode_windows()
        sig = tuple(wins)
        if sig != self._sig and not self._busy:
            self._sig = sig
            for w in self.list.winfo_children():
                w.destroy()
            self.rows = {}                      # project -> [(row frame, button), ...]
            seen = {}
            for h, t in wins:
                proj = project_name(t)
                name = proj
                seen[name] = seen.get(name, 0) + 1
                if seen[name] > 1:
                    name = f"{name} ({seen[name]})"
                row = tk.Frame(self.list)
                row.pack(fill="x", pady=1)
                btn = tk.Button(row, text=f"Max: {name}", anchor="w", relief="flat", bd=1,
                                command=lambda h=h, p=proj: self.focus_window(h, p))
                btn.pack(fill="x", padx=1, pady=1)
                # a list: two windows can share a folder name, and the hook writes one
                # status file per name, so both rows must show that same state
                self.rows.setdefault(proj, []).append((row, btn))
            if not wins:
                tk.Label(self.list, text="no VS Code windows").pack()
        self.update_lights()
        self.after(REFRESH_MS, self.refresh)

    def focus_window(self, hwnd, project):
        maximize(hwnd)
        clear_status(project)           # you've looked at it; the row goes back to plain
        self._states.pop(project, None)
        self._alerted.discard(project)
        self.stop_flash()
        self.update_lights()

    def update_lights(self):
        states = read_statuses()
        for proj, state in states.items():
            if state in NOTIFY_ON and self._states.get(proj) != state:
                self.alert(proj, state)
        self._states = states
        self._alerted &= set(states)            # a cleared status cancels its alert
        for proj, widgets in getattr(self, "rows", {}).items():
            colour = STATUS_COLORS.get(states.get(proj, "idle")) or self._bg
            if NOTIFY_BLINK_ROW and self._blink and proj in self._alerted:
                colour = self._bg                       # the off half of the flash
            for row, btn in widgets:
                row.configure(bg=colour)
                btn.configure(bg=colour, activebackground=colour)

    def alert(self, project, state):
        """A window just changed to a state worth interrupting you for."""
        self._alerted.add(project)
        if NOTIFY_SOUND:
            play_alert(state)
        if NOTIFY_TOAST:
            self._tray.notify("Claude Code",
                              "%s: %s" % (project, "finished" if state == "done" else "needs you"))
        if NOTIFY_FLASH_TASKBAR:
            flash_taskbar(self._hwnd, True)

    def stop_flash(self):
        if NOTIFY_FLASH_TASKBAR:
            flash_taskbar(self._hwnd, False)

    def _blink_tick(self):
        """Flash the rows of unacknowledged alerts on and off."""
        if self._alerted or self._blink:
            self._blink = bool(self._alerted) and not self._blink
            self.update_lights()
        self.after(BLINK_MS, self._blink_tick)


if __name__ == "__main__":
    Panel().mainloop()
