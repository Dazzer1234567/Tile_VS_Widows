# VS Code Window Panel

A small always-on-top control panel for managing several VS Code windows that each run a Claude Code conversation. Windows only, Python standard library only (ctypes + tkinter).

## Goal

Darius works with four (or more) separate VS Code windows open at once, each a different project with its own Claude Code session. He wants to:

1. **Tile** all VS Code windows into a grid on the primary monitor with one click, bringing them all in front of everything else.
2. **Hide all** (minimise) and **Max all** (maximise every window without changing what's currently in front).
3. Have one **"Max: <project>"** button per open window, named after the project folder, that maximises that window and brings it to front.
4. After tiling, have the Claude Code chat panel in each window **scrolled to the bottom**, so the latest output is visible.
5. See a **status light** per window showing whether Claude Code is working, has finished, or is waiting for input — so he can glance at the panel instead of checking each window.

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

It reads the hook JSON from stdin, takes `basename(cwd)` as the project, and writes `%TEMP%\vscode_panel_status\<project>.json`. The panel polls that directory every `REFRESH_MS` and colours the `●` next to the matching Max button. Clicking the Max button deletes the status file (light back to grey).

Hook config (double the backslashes in JSON):
```json
{
  "hooks": {
    "UserPromptSubmit": [ { "hooks": [ { "type": "command", "command": "python C:\\tools\\claude_hook.py" } ] } ],
    "Stop":             [ { "hooks": [ { "type": "command", "command": "python C:\\tools\\claude_hook.py" } ] } ],
    "Notification":     [ { "hooks": [ { "type": "command", "command": "python C:\\tools\\claude_hook.py" } ] } ]
  }
}
```
Restart the VS Code windows after editing settings so the extension picks the hooks up.

### Misc
- Icon: a 2×2 black-squares `.ico` is embedded as base64 and written to `%TEMP%` on first run. `SetCurrentProcessExplicitAppUserModelID` is called so the taskbar shows it instead of the Python icon.
- Drag bar: the `✋` row at the top moves the panel. `SHOW_TITLEBAR = False` makes it frameless (right-click the hand to quit).

## Config knobs (top of `vscode_panel.py`)
`TITLE_SUFFIX`, `MONITOR`, `REFRESH_MS`, `SCROLL_TO_BOTTOM`, `SCROLL_POINTS`, `SCROLL_NOTCHES`, `SCROLL_STEP_MS`, `SETTLE_MS`, `SHOW_TITLEBAR`, `STATUS_COLORS`.

## Status / open issues

- Tiling, Hide all, Max all, per-window Max: working.
- Scroll-to-bottom: **not yet verified** after the rewrite to `SendInput` + spaced notches. Earlier version (SetCursorPos + rapid `mouse_event`) did not work — likely because no hover event reached the webview and the events were coalesced. If still failing, check that `SCROLL_POINTS` actually lands on the chat panel in a tiled window, and consider raising `SCROLL_NOTCHES`.
- Tile sometimes only raised one window in the earlier version; the `SetWindowPlacement` + `AttachThreadInput` rewrite is intended to fix this — **verify**.
- Status lights: **not yet tested** end-to-end. Matching is by folder name; multi-root workspaces show the workspace name in the title, so they won't match — would need keying by something else (e.g. the hook's `cwd` vs. the window's workspace path via the VS Code extension API, or session_id).
- Possible extension: flash the light or the whole panel when a window turns green; hide status files older than N hours.
