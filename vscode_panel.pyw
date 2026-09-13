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
import math
import os
import re
import subprocess
import tempfile
import threading
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
SOUND_ON, SOUND_OFF = "🔊", "🔇"     # speaker / muted speaker
SOUND_ON_BG, SOUND_OFF_BG = "#1f6feb", "#e5484d"      # blue when sounding, red when muted
SOUND_FONT = ("Segoe UI Emoji", 14)
# (frequency Hz, milliseconds) per alert.  Rising = finished, falling = wants you.
SOUND_TONES = {"done": [(660, 90), (880, 150)], "waiting": [(760, 90), (570, 170)]}
SOUND_VOLUME = 0.35                      # 0-1, of full scale
SPEAK_VOICE = ""                         # "" = Windows default; e.g. "Microsoft Zira Desktop"
SPEAK_RATE = 0                           # SAPI rate, -10 (slow) to 10 (fast)
SAY_WIDTH = 14                           # width of each row's spoken-text box, in characters
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


def read_prefs():
    """(projects you have muted, {project: phrase to speak when it finishes})"""
    try:
        with open(PREFS_PATH) as f:
            d = json.load(f)
        return set(d.get("muted", [])), dict(d.get("say", {}))
    except Exception:
        return set(), {}


def write_prefs(muted, say):
    try:
        os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
        with open(PREFS_PATH, "w") as f:
            json.dump({"muted": sorted(muted), "say": say}, f)
    except Exception:
        pass                        # a preference is not worth crashing the panel over


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


def write_tone(path, tones, rate=44100):
    """A small WAV of (freq, ms) tones, each under a raised-cosine envelope so the
    edges do not click.  Generated rather than shipped, like the icon."""
    frames = array.array("h")
    for freq, ms in tones:
        n = int(rate * ms / 1000)
        for i in range(n):
            env = 0.5 - 0.5 * math.cos(2 * math.pi * min(i, n - i) / n)
            frames.append(int(32767 * SOUND_VOLUME * env * math.sin(2 * math.pi * freq * i / rate)))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames.tobytes())


def alert_wav(state):
    path = os.path.join(tempfile.gettempdir(), "vscode_panel_%s.wav" % state)
    if not os.path.exists(path):
        write_tone(path, SOUND_TONES.get(state, SOUND_TONES["done"]))
    return path


def ps_quote(text):
    """Quote for a PowerShell single-quoted string: only ' needs escaping."""
    return "'" + str(text).replace("'", "''") + "'"


def say_wav(text):
    """Where the rendering of this phrase lives.  Keyed by content, so editing the
    text renders a new file and leaves the old one harmlessly cached."""
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), "vscode_panel_say_%s.wav" % digest)


def render_speech(text):
    """Synthesise `text` to a cached WAV with SAPI, via PowerShell so the panel keeps
    to the standard library.  Done once when you edit the text - never at alert time,
    where it would add a second of latency - so speaking then costs no more than a beep."""
    path = say_wav(text)
    if os.path.exists(path):
        return path
    script = ("Add-Type -AssemblyName System.Speech;"
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              + ("$s.SelectVoice(%s);" % ps_quote(SPEAK_VOICE) if SPEAK_VOICE else "")
              + "$s.Rate = %d;" % SPEAK_RATE
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


def speak(text):
    """Play the cached rendering of `text`.  Falls back to the beep if it is missing."""
    path = say_wav(text)
    if not os.path.exists(path):
        return False
    try:
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return True
    except Exception:
        return False


def play_alert(state):
    """Play our own WAV rather than MessageBeep.  MessageBeep plays whatever the
    Windows sound scheme maps to SystemAsterisk / SystemExclamation, so on a machine
    set to "No Sounds" - normal on an audio workstation - it is silent."""
    try:
        winsound.PlaySound(alert_wav(state),
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
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(padx=6, pady=6)
        if not SHOW_TITLEBAR:
            self.overrideredirect(True)

        # drag bar
        grip = tk.Label(self, text="\u270b", font=("Segoe UI Emoji", 12),
                        cursor="fleur", bg="#d9d9d9")
        grip.pack(fill="x", pady=(0, 6))
        # twice the natural height, so it is an easy target to grab.  Derived from
        # reqheight rather than a pixel constant so it still doubles at any DPI or font size.
        self.update_idletasks()
        grip.pack_configure(ipady=grip.winfo_reqheight() // 2)
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
        self._bg = self.cget("bg")          # what an idle row looks like
        self.muted, self.say = read_prefs()  # muted projects, and what to speak for each
        self._hwnd = self.panel_hwnd()
        self._tray = Tray(self._hwnd)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<FocusIn>", lambda e: self.stop_flash())

        self.refresh()

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
        sig = tuple((h, project_name(t)) for h, t in wins)
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
                mute = tk.Button(row, font=SOUND_FONT, width=2, relief="flat", bd=1,
                                 command=lambda p=proj: self.toggle_sound(p))
                mute.pack(side="left", padx=(1, 0), pady=1)
                say = tk.Entry(row, width=SAY_WIDTH)
                say.insert(0, self.say.get(proj, ""))
                say.pack(side="right", padx=(2, 1), pady=1)
                say.bind("<KeyRelease>", lambda e, p=proj, w=say: self.say_typed(p, w))
                say.bind("<Return>",     lambda e, p=proj, w=say: self.say_commit(p, w))
                say.bind("<FocusOut>",   lambda e, p=proj, w=say: self.say_commit(p, w))
                btn = tk.Button(row, text=f"Max: {name}", anchor="w", relief="flat", bd=1,
                                command=lambda h=h, p=proj: self.focus_window(h, p))
                btn.pack(side="left", fill="x", expand=True, padx=1, pady=1)
                # a list: two windows can share a folder name, and the hook writes one
                # status file per name, so both rows must show that same state
                self.rows.setdefault(proj, []).append((row, btn, mute, say))
            if not wins:
                tk.Label(self.list, text="no VS Code windows").pack()
        self.update_lights()
        self.after(REFRESH_MS, self.refresh)

    def focus_window(self, hwnd, project):
        maximize(hwnd)
        # Opening a window only settles a state that has stopped changing.  "working"
        # is still in progress, so it stays amber until the hook says otherwise -
        # clearing it would blank the row while Claude is still going.
        if read_statuses().get(project) != "working":
            clear_status(project)       # you've looked at it; the row goes back to plain
            self._states.pop(project, None)
        self.stop_flash()
        self.update_lights()

    def update_lights(self):
        states = read_statuses()
        for proj, state in states.items():
            if state in NOTIFY_ON and self._states.get(proj) != state:
                self.alert(proj, state)
        self._states = states
        for proj, widgets in getattr(self, "rows", {}).items():
            colour = STATUS_COLORS.get(states.get(proj, "idle")) or self._bg
            muted = proj in self.muted
            icon = SOUND_OFF if muted else SOUND_ON
            sound_bg = SOUND_OFF_BG if muted else SOUND_ON_BG
            for row, btn, mute, _say in widgets:
                row.configure(bg=colour)
                btn.configure(bg=colour, activebackground=colour)
                mute.configure(text=icon, bg=sound_bg, activebackground=sound_bg)

    def say_typed(self, project, entry):
        """Keep the in-memory copy current on every keystroke, so a row rebuild
        mid-sentence restores what you had typed.  Disk and synthesis wait for commit."""
        self.say[project] = entry.get()

    def say_commit(self, project, entry):
        """Persist the phrase and render it, once, off the UI thread."""
        text = entry.get().strip()
        if text:
            self.say[project] = text
        else:
            self.say.pop(project, None)
        write_prefs(self.muted, self.say)
        if text and not os.path.exists(say_wav(text)):
            threading.Thread(target=render_speech, args=(text,), daemon=True).start()

    def toggle_sound(self, project):
        """Switch this project's green/red sound on or off, and remember it."""
        self.muted.symmetric_difference_update({project})
        write_prefs(self.muted, self.say)
        self.update_lights()

    def alert(self, project, state):
        """A window just changed to a state worth interrupting you for."""
        if NOTIFY_SOUND and project not in self.muted:
            text = self.say.get(project, "").strip()
            # the phrase is for "it has stopped"; red keeps its own falling tone
            if not (state == "done" and text and speak(text)):
                play_alert(state)
        if NOTIFY_TOAST:
            self._tray.notify("Claude Code",
                              "%s: %s" % (project, "finished" if state == "done" else "needs you"))
        if NOTIFY_FLASH_TASKBAR:
            flash_taskbar(self._hwnd, True)

    def stop_flash(self):
        if NOTIFY_FLASH_TASKBAR:
            flash_taskbar(self._hwnd, False)



if __name__ == "__main__":
    Panel().mainloop()
