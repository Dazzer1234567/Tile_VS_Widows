"""
claude_hook.py  -  Claude Code hook: record per-project status for vscode_panel.py

Reads the hook JSON from stdin and writes %TEMP%\\vscode_panel_status\\<project>.json
so the panel can show a light next to the matching "Max: <project>" button.

Add to ~/.claude/settings.json (use double backslashes in the path):

{
  "hooks": {
    "UserPromptSubmit": [ { "hooks": [ { "type": "command", "command": "python C:\\\\tools\\\\claude_hook.py" } ] } ],
    "Stop":             [ { "hooks": [ { "type": "command", "command": "python C:\\\\tools\\\\claude_hook.py" } ] } ],
    "Notification":     [ { "hooks": [ { "type": "command", "command": "python C:\\\\tools\\\\claude_hook.py" } ] } ]
  }
}
"""

import json
import os
import re
import sys
import tempfile
import time

STATUS_DIR = os.path.join(tempfile.gettempdir(), "vscode_panel_status")

STATE_FOR_EVENT = {
    "UserPromptSubmit": "working",   # you sent a prompt, Claude is busy
    "Stop": "done",                  # Claude finished its turn
    "Notification": "waiting",       # Claude needs you (permission prompt etc.)
}


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    event = data.get("hook_event_name", "")
    state = STATE_FOR_EVENT.get(event)
    if not state:
        return
    cwd = data.get("cwd") or os.getcwd()
    project = os.path.basename(os.path.normpath(cwd)) or "root"
    safe = re.sub(r"[^\w.-]", "_", project)
    os.makedirs(STATUS_DIR, exist_ok=True)
    with open(os.path.join(STATUS_DIR, safe + ".json"), "w") as f:
        json.dump({"project": project, "state": state, "event": event,
                   "notification": data.get("notification_type", ""),
                   "time": time.time()}, f)


if __name__ == "__main__":
    main()
