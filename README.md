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

### Per-project sound toggle
Each row carries a speaker button — **blue 🔊 when the sound is on, red 🔇 when muted** — that switches the sound off for that project alone, useful when one window is chatty and the others are not. It mutes only the sound; the row still turns green or red.

The speaker keeps its own blue/red background rather than taking the row's status tint, so on/off stays readable whatever the row is doing. Its colour has to be set on the *background*: `Segoe UI Emoji` is a colour font, so `fg` would not repaint the glyph. Size comes from `SOUND_FONT`; at 14pt it makes the row 65px tall against 44px with the original 9pt.

Preferences are read and written as a **single dict** (`read_prefs` / `write_prefs`, assembled by `Panel.save()`), not as a positional tuple. Each new setting was otherwise changing the function signature and all five call sites. The muted set cannot live on the widgets, because `refresh()` destroys and rebuilds every row whenever a window opens or closes. It lives in `Panel.muted` and is written to `%APPDATA%\vscode_panel\prefs.json` on each click — deliberately *not* alongside the status files in `%TEMP%`, which are disposable, while a preference should outlive a reboot or a temp sweep. A failed read or write is swallowed: a preference is not worth crashing the panel over.

### Volume and preview
A narrow **▾** sits at the right-hand end of the Tile / Max all / Hide all row and reveals the **ear** button and the **voice volume** slider together. Both are wanted rarely, so they stay collapsed and the panel stays compact — 71px shorter. The caret keeps a fixed width while the three buttons expand, so it never steals room from them. The revealed strip packs *before* the progress bar rather than at the end, which is where `pack` would otherwise put it, below the project rows; open or closed is remembered in `vol_open`. The ear speaks the name of the top project in the list, so you can set the level by ear without waiting for a conversation to finish.

`PlaySound` has no volume control, so the level has to be baked in at synthesis: `$s.Volume` for speech, and the sample amplitude for the tones. Both caches are therefore keyed by *(content, volume)* rather than content alone, which keeps playback a plain `PlaySound` on a cached file instead of rewriting a WAV on every play. Tone amplitude is `SOUND_PEAK * volume / 100`, so the default 60 reproduces the old fixed 0.35 of full scale and there is headroom above it.

Dragging fires the callback on every pixel, so saving and re-rendering are debounced by `VOLUME_SAVE_MS`. When the drag settles, every stored phrase is re-rendered at the new level in the background — otherwise the next alert would find no cached file and fall back to a beep once before catching up.

### Spoken phrase per project
Under each row is a text box, spanning its full width. Whatever you type there is **spoken when that project turns green**; leave it empty and you get the plain rising tone instead. Red keeps its falling tone either way, so "finished" and "needs you" never sound alike.

Speech is Windows SAPI (`System.Speech.Synthesis`) driven through PowerShell, so the panel still needs nothing outside the standard library. The cost is paid **once, when you commit the text** (Enter or clicking away), not when it speaks: `render_speech()` synthesises to a WAV in `%TEMP%` keyed by an MD5 of the phrase, on a background thread so the UI never blocks. Speaking is then just `PlaySound` on a cached file — no more expensive than the beep, and with no synthesis latency at the moment you want to hear it. Editing the text renders a new file; the old one stays cached harmlessly. `SPEAK_VOICE` and `SPEAK_RATE` pick the voice and speed.

Pressing **Enter** saves the phrase and drops focus out of the box (the binding returns `"break"` so Tk does not also insert a newline). You do not have to press it, though: every keystroke is mirrored into `Panel.say` and queues a save `SAY_SAVE_MS` after you stop typing. That debounce matters — the phrase used to reach disk *only* on Enter or focus-out, so typing one and then shutting the machine down lost it. `close()` also flushes, in case you quit inside the debounce window.

A related fix was needed to make the box usable at all: `refresh()` rebuilt every row whenever the window *signature* changed, and the signature was the full window titles — which churn constantly as you work, since the title carries the open filename. A rebuild mid-sentence would have destroyed the box you were typing in. The signature is now `(hwnd, project name)`, so rows are rebuilt only when a window actually opens or closes. Keystrokes are also mirrored into `Panel.say` as you type, so even a genuine rebuild restores what you had.

### Restart an app when a project finishes
Under the spoken-phrase box is a second box: put the **full path to an executable** in it and, when that project turns green, every instance of it is closed and one is started again. Useful for a test build you want relaunched on each pass. The box turns pink while the path does not point at a file, so a typo says so instead of silently doing nothing. Quotes are stripped, so Explorer's *Copy as path* can be pasted straight in.

Beside that box is a 🔁 toggle, **orange on / red off** — orange rather than the speaker's blue, so the two are not mistaken for each other at a glance. Switching it off suspends the close-and-reopen for that project while leaving the path in place, so it is still there when you want it back; the setting persists in `run_off`.

The restart waits `RESTART_DELAY_MS` (4s) after the conversation stops before touching anything, so the app is not closed while it is still settling.

**Why two instances kept appearing.** Rebuilding the app while it is running does not stop the old process — Windows lets the exe be renamed out from under it, and the build moves it to the Recycle Bin. The running process then reports an image path like `C:\$Recycle.Bin\S-1-5-21-…\.<mangled>`, which no longer equals the configured path, so a strict comparison stopped recognising it. The old build was never closed and a fresh one was launched beside it — every rebuild, forever. `scan_for()` now matches three ways: the configured path, any PID the panel launched itself (`LAUNCHED`), and a same-named process whose own image has gone (`stale_image()` — unreadable, renamed, or no longer on disk). The third is what catches an instance you started yourself before a rebuild.

Instances are otherwise matched on the **full image path**, never on the file name. That distinction is the whole safety story: matching `python.exe` or `node.exe` by name would kill unrelated processes across the machine, whereas a full-path match cannot touch another copy of the same-named exe living elsewhere. The panel's own process is skipped too.

Closing is `WM_CLOSE` to each visible window first, so the app can shut down tidily, then `TerminateProcess` for anything that ignored it — and then the whole sweep repeats, up to `rounds` times, because one pass is not reliable: an app can spawn a replacement as it exits, a launcher can start the real process a moment later, and an instance still opening when the first sweep ran would be missed. The wait ends as soon as everything has gone rather than always sitting out `RESTART_GRACE_MS`. Restarts are serialised on a lock, so two finishes close together cannot interleave, one thread's sweep killing the instance the other just launched. **It is a force-kill in the end — do not point this at something holding unsaved work.** All of it runs on a worker thread, since it sleeps out the grace period.

Two limits worth knowing:

- **Path only, no arguments.** The whole string is taken as the executable.
- **Windows execution aliases** (Store apps, winget stubs) run from a different image path than the one you launch: the `notepad.exe` in System32 actually runs from `WindowsApps`. A strict comparison cannot match those, so the first restart of such an app closes nothing. `launch_app()` records what the alias really resolved to, so every restart after that works. Ordinary installed applications and build outputs are unaffected — their launch path *is* their image path.

### The log
`%APPDATA%\vscode_panel\panel.log` records panel startup (with PID and whether it is elevated), every finish that queues a restart, and then each round of the sweep: every candidate process, *why* it matched, how many windows it was asked to close, and whether terminating it succeeded. A process that cannot be opened is called out explicitly, with the likely reason — an elevated app cannot be managed by a panel that is not. It rolls to `panel.log.1` past `LOG_MAX_BYTES`, and every logging failure is swallowed: logging must never break the panel.

### Notifications
The light alone is passive — you still have to look at the panel. So `update_lights()` also watches for *transitions*: when a project's state changes into one of `NOTIFY_ON` (default `done` and `waiting`), `alert()` fires four ways, each independently switchable:

| Knob | What it does |
|---|---|
| `NOTIFY_SOUND` | A short generated two-tone WAV — rising for *finished*, falling for *needs you*. A master switch: each row also has its own speaker toggle (above). |
| `NOTIFY_TOAST` | A Windows notification via `Shell_NotifyIconW` (`NIM_MODIFY` + `NIF_INFO`), reading `Claude Code — <project>: finished`. **Off by default** — the popup in the corner is intrusive, and the tinted row already says the same thing. No tray icon is registered while it is off. |
| `NOTIFY_FLASH_TASKBAR` | `FlashWindowEx` with `FLASHW_TIMERNOFG`, so the panel's taskbar button flashes until you bring it to the foreground. **Off by default** — nothing about the panel should blink. |

Details that matter:

- The sound is **not** `MessageBeep`. `MessageBeep` plays whatever the Windows sound scheme maps to `SystemAsterisk` / `SystemExclamation`, and on a machine whose scheme is set to *No Sounds* — normal on an audio workstation — it returns silently having played nothing. `write_tone()` generates a small WAV into `%TEMP%` on first use (like the icon) and `PlaySound(SND_FILENAME)` plays it, which ignores the scheme entirely. Tones and level are `SOUND_TONES` and `SOUND_VOLUME`.
- Each tone sits under a raised-cosine envelope so it starts and ends at exactly zero and does not click.
- It plays through the Windows **default playback device**, so on a machine with several interfaces the sound may be going somewhere you are not monitoring.

- The toast needs a tray icon to come from, so `Tray` registers one lazily on the first alert (using the same embedded `.ico`) and removes it on quit — closing via the window's X or right-clicking the drag bar both go through `close()`, so no ghost icon is left behind.
- `_states` is seeded from disk in `__init__`, so a status file left over from a previous run doesn't fire an alert the moment the panel starts.
- An event is identified by **(state, timestamp)**, not by state alone. Two Stops in a row write the same state, and comparing states would see no change and fire nothing — which happened whenever the `working` in between was not caught by the poll, i.e. any turn shorter than `REFRESH_MS`. That silently skipped the phrase *and* the app restart, and was the cause of restarts being unreliable. The hook stamps every event, so the timestamp settles it.
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
- The spoken-text box is a plain `Entry` and deliberately keeps its normal background rather than the row's status tint, which would hurt readability of the text.
- Both text boxes share one implementation (`_bind_field` / `field_typed` / `field_done` / `field_store`), keyed by which dict they write to, so the debounced-save behaviour cannot drift between them.
- Drag bar: the `✋` row at the top moves the panel. `GRIP_SCALE` sets its height as a multiple of its natural one, derived from the label's `reqheight` rather than a pixel constant so it holds at any DPI or font size.
- The progress bar is **packed only while tiling**. Left packed, an empty bar and its padding sat permanently between the buttons and the first card. It packs `before=self.list` so it appears above the cards rather than below them, which is where `pack` would put it, and that survives the row rebuilds `refresh()` does.
- Card metrics are driven by `FIELD_FONT`, `SOUND_FONT` and `RESTART_FONT`. The `head` row's height follows whichever of the Max button and the speaker is taller, so shrinking only the speaker does nothing — the Max button carries `FIELD_FONT` for that reason.
- `FIELD_FONT` is **Segoe UI 9, the Windows default**, and should not go below it. Shrinking it does buy a shorter card — 6pt halved the card to 67px — but the result is unreadable, which is a bad trade for a panel meant to be read at a glance. Height comes from the padding and the icon fonts instead. `SHOW_TITLEBAR = False` makes it frameless (right-click the hand to quit).

## Config knobs (top of `vscode_panel.py`)
`TITLE_SUFFIX`, `MONITOR`, `REFRESH_MS`, `SCROLL_TO_BOTTOM`, `SCROLL_POINTS`, `SCROLL_NOTCHES`, `SCROLL_STEP_MS`, `SETTLE_MS`, `SHOW_TITLEBAR`, `STATUS_COLORS`, `NOTIFY_ON`, `NOTIFY_SOUND`, `NOTIFY_TOAST`, `NOTIFY_FLASH_TASKBAR`.

## Status / open issues

- Tiling, Hide all, Max all, per-window Max: working.
- Scroll-to-bottom: **not yet verified** after the rewrite to `SendInput` + spaced notches. Earlier version (SetCursorPos + rapid `mouse_event`) did not work — likely because no hover event reached the webview and the events were coalesced. If still failing, check that `SCROLL_POINTS` actually lands on the chat panel in a tiled window, and consider raising `SCROLL_NOTCHES`.
- Tile sometimes only raised one window in the earlier version; the `SetWindowPlacement` + `AttachThreadInput` rewrite is intended to fix this — **verify**.
- Status lights: **not yet tested** end-to-end. Matching is by folder name; multi-root workspaces show the workspace name in the title, so they won't match — would need keying by something else (e.g. the hook's `cwd` vs. the window's workspace path via the VS Code extension API, or session_id).
- Notifications (sound / toast / taskbar flash / blinking dot): the plumbing is tested — transitions fire correctly, the tray icon registers and is removed on quit, a pre-existing status file does not alert at startup — but only with a synthetic status file. **Not yet confirmed end-to-end from a real Claude Code hook**, which depends on the hook config above being live.
- Possible extension: hide status files older than N hours; a "mute" toggle on the panel itself.
