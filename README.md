# VS Code Window Panel

A small always-on-top control panel for managing several VS Code windows that each run a Claude Code conversation. Windows only, Python standard library only (ctypes + tkinter).

## Goal

Darius works with four (or more) separate VS Code windows open at once, each a different project with its own Claude Code session. He wants to:

1. **Tile** all VS Code windows into a grid on the primary monitor with one click, bringing them all in front of everything else.
2. **Hide all** (minimise) and **Max all** (maximise every window without changing what's currently in front).
3. Have one **"Max: <project>"** button per open window, named after the project folder, that maximises that window and brings it to front.
4. After tiling, have the Claude Code chat panel in each window **scrolled to the bottom**, so the latest output is visible.
5. See at a glance, from the corner of his eye, whether Claude Code is working, has finished, or is waiting for input — so he can glance at the panel instead of checking each window.

## Files

- `vscode_panel.py` — the panel. Run with `pythonw` (or rename to `.pyw`) to avoid a console window. Put a shortcut in `shell:startup` to start with Windows.
- `claude_hook.py` — Claude Code hook script. Writes per-project status files that the panel reads.
- `vscode_tiler.py` — earlier hotkey-only version (Ctrl+Alt+T tile, Ctrl+Alt+H hide/show). Superseded by the panel; kept for reference.

## How it works

### Window discovery
`vscode_windows()` enumerates top-level windows with class `Chrome_WidgetWin_1` (Electron) whose title ends in `TITLE_SUFFIX` (`"Visual Studio Code"`; change for Insiders). Owned windows (tooltips, popups) are skipped.

`project_name()` parses the title `file - Folder - Visual Studio Code` and takes the second-to-last segment as the project name. Handles `-`, `–`, `—` separators and the `●` unsaved marker.

### Tiling
`tile()` computes a `ceil(sqrt(n)) × ceil(n/cols)` grid over the primary monitor's work area and uses `SetWindowPlacement` per window (restore + move + resize atomically — a plain `ShowWindow(SW_RESTORE)` followed by `SetWindowPos` was unreliable because the restore is async across processes). Each window is then raised with `bring_to_front()`, which uses the `AttachThreadInput` trick so Windows allows raising another process's windows.

### Scroll to bottom (hack)
There is no API to tell the Claude Code webview to scroll. Instead, after `SETTLE_MS`, the cursor is moved to `SCROLL_POINTS` (fractions of window size, default `(0.80, 0.50)` = right-side panel) in each window, a real mouse-move is sent via `SendInput` so the webview registers hover, then `SCROLL_NOTCHES` wheel-down events are sent `SCROLL_STEP_MS` apart. The sequence is a generator stepped by `tk.after`, so a progress bar shows and the buttons are disabled while it runs; the cursor is restored afterwards.

### Status lights
`claude_hook.py` is registered in `~/.claude/settings.json` for three events:

| Event | State written | Light |
|---|---|---|
| `UserPromptSubmit` | `working` | amber |
| `Stop` | `done` | green |
| `Notification` | `waiting` | red |

The event name comes from `argv[1]` when the registration passes one, falling back to the payload's `hook_event_name`, so a payload without that field still writes a status file instead of silently doing nothing. It reads the hook JSON from stdin, takes `basename(cwd)` as the project, and writes `%TEMP%\vscode_panel_status\<project>.json`. The panel polls that directory every `REFRESH_MS` and tints the **whole row** of the matching Max button — the frame and the button itself, not a small indicator — so it is visible peripherally. Clicking the Max button deletes the status file (row back to plain).

### Notifications
The light alone is passive — you still have to look at the panel. So `update_lights()` also watches for *transitions*: when a project's state changes into one of `NOTIFY_ON` (default `done` and `waiting`), `alert()` fires four ways, each independently switchable:

| Knob | What it does |
|---|---|
| `NOTIFY_SOUND` | `winsound.MessageBeep` — asterisk for *finished*, exclamation for *needs you* |
| `NOTIFY_TOAST` | A Windows notification via `Shell_NotifyIconW` (`NIM_MODIFY` + `NIF_INFO`), reading `Claude Code — <project>: finished`. **Off by default** — the popup in the corner is intrusive, and the tinted row already says the same thing. No tray icon is registered while it is off. |
| `NOTIFY_FLASH_TASKBAR` | `FlashWindowEx` with `FLASHW_TIMERNOFG`, so the panel's taskbar button flashes until you bring it to the foreground. **Off by default** — nothing about the panel should blink. |

Details that matter:

- The toast needs a tray icon to come from, so `Tray` registers one lazily on the first alert (using the same embedded `.ico`) and removes it on quit — closing via the window's X or right-clicking the drag bar both go through `close()`, so no ghost icon is left behind.
- `_states` is seeded from disk in `__init__`, so a status file left over from a previous run doesn't fire an alert the moment the panel starts.
- Only changes *into* an alert state fire; `working` → `working` is silent, and re-reading the same `done` doesn't re-alert.
- **Nothing blinks.** Every row colour is steady; the panel is meant to be read out of the corner of your eye, and movement there pulls focus rather than informing. The four states are amber (working), green (stopped, not yet looked at), red (waiting on you) and unfilled (nothing to report, or you have opened it since).
- "Not yet looked at" needs no extra bookkeeping: the status file *is* that state. Clicking Max deletes it, which is what returns the row to unfilled.
- Clicking Max only clears a state that has *settled*. `working` is still in progress, so opening that window leaves it amber — it stays amber until the hook reports the window finished. Only `done` and `waiting` are cleared by a click.
- `rows` maps a project to a *list* of rows. Two windows can share a folder name, and the hook writes one status file per name, so both rows must show that one state.
- `user32.LoadImageW.restype` / `LoadIconW.restype` are set explicitly — without that the returned `HICON` is truncated to 32 bits on 64-bit Python and the tray icon silently fails to register.

Hook config in `~/.claude/settings.json`. Use the exec form (`command` + `args`) rather than one
shell string: the arguments go straight to the process, so the Windows paths need no quoting or
backslash-doubling, and each registration passes its own event name.
```json
{
  "hooks": {
    "Stop": [ { "hooks": [ {
      "type": "command",
      "command": "C:/Python314/python.exe",
      "args": ["C:/0_CODE/Tile_VS_Widows/claude_hook.py", "Stop"],
      "timeout": 5
    } ] } ]
  }
}
```
— and the same for `UserPromptSubmit` and `Notification`, each with its own event name.
Restart the VS Code windows after editing settings so the extension picks the hooks up.

### Misc
- Top row order is **Tile / Max all / Hide all**, Tile first because it is the one used most. The buttons `pack` with `expand=True` rather than a fixed `width`: on a button carrying an image, Tk reads `width` as pixels rather than characters, so an explicit width would size the three inconsistently.
- The Tile button carries the four-black-squares logo to the right of its label (`compound="right"`). `logo_image()` draws it into a `PhotoImage` with `put()` rather than loading a file, so the panel stays a single script; unpainted pixels stay transparent, letting the button background through.
- Icon: a 2×2 black-squares `.ico` is embedded as base64 and written to `%TEMP%` on first run. `SetCurrentProcessExplicitAppUserModelID` is called so the taskbar shows it instead of the Python icon.
- Drag bar: the `✋` row at the top moves the panel. `SHOW_TITLEBAR = False` makes it frameless (right-click the hand to quit).

## Config knobs (top of `vscode_panel.py`)
`TITLE_SUFFIX`, `MONITOR`, `REFRESH_MS`, `SCROLL_TO_BOTTOM`, `SCROLL_POINTS`, `SCROLL_NOTCHES`, `SCROLL_STEP_MS`, `SETTLE_MS`, `SHOW_TITLEBAR`, `STATUS_COLORS`, `NOTIFY_ON`, `NOTIFY_SOUND`, `NOTIFY_TOAST`, `NOTIFY_FLASH_TASKBAR`.

## Status / open issues

- Tiling, Hide all, Max all, per-window Max: working.
- Scroll-to-bottom: **not yet verified** after the rewrite to `SendInput` + spaced notches. Earlier version (SetCursorPos + rapid `mouse_event`) did not work — likely because no hover event reached the webview and the events were coalesced. If still failing, check that `SCROLL_POINTS` actually lands on the chat panel in a tiled window, and consider raising `SCROLL_NOTCHES`.
- Tile sometimes only raised one window in the earlier version; the `SetWindowPlacement` + `AttachThreadInput` rewrite is intended to fix this — **verify**.
- Status lights: **not yet tested** end-to-end. Matching is by folder name; multi-root workspaces show the workspace name in the title, so they won't match — would need keying by something else (e.g. the hook's `cwd` vs. the window's workspace path via the VS Code extension API, or session_id).
- Notifications (sound / toast / taskbar flash / blinking dot): the plumbing is tested — transitions fire correctly, the tray icon registers and is removed on quit, a pre-existing status file does not alert at startup — but only with a synthetic status file. **Not yet confirmed end-to-end from a real Claude Code hook**, which depends on the hook config above being live.
- Possible extension: hide status files older than N hours; a "mute" toggle on the panel itself.
