"""
claude_hook.py  -  Claude Code hook: record per-project status for vscode_panel.py

Reads the hook JSON from stdin and writes %TEMP%\\vscode_panel_status\\<project>.json
so the panel can show a light next to the matching "Max: <project>" button.

The event name is taken from argv[1] when given, so the hook still works if the
payload ever omits "hook_event_name"; each registration passes its own event.

argv[2] (or VSCODE_PANEL_URL) may name a panel on another machine, e.g.
    python claude_hook.py Stop http://100.74.240.93:8765/status
in which case the record is POSTed there instead of written to this machine's
%TEMP%.  If that panel cannot be reached the record is written locally instead,
so nothing is lost.

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
import platform
import re
import sys
import tempfile
import time
import urllib.request

STATUS_DIR = os.path.join(tempfile.gettempdir(), "vscode_panel_status")
POST_TIMEOUT = 4                 # seconds; a hook must not hold up the session

STATE_FOR_EVENT = {
    "UserPromptSubmit": "working",   # you sent a prompt, Claude is busy
    "Stop": "done",                  # Claude finished its turn
    "Notification": "waiting",       # Claude needs you (permission prompt etc.)
}


def write_local(record):
    """Drop the record where a panel on this machine will find it."""
    safe = re.sub(r"[^\w.-]", "_", "%s~%s" % (record["host"], record["project"]))
    os.makedirs(STATUS_DIR, exist_ok=True)
    with open(os.path.join(STATUS_DIR, safe + ".json"), "w") as f:
        json.dump(record, f)


def post(url, record):
    """Send the record to a panel on another machine.  Falls back to writing locally,
    so a panel that is closed or unreachable loses nothing that a local one would see."""
    body = json.dumps(record).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=POST_TIMEOUT).close()
    except Exception:
        write_local(record)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    event = sys.argv[1] if len(sys.argv) > 1 else data.get("hook_event_name", "")
    state = STATE_FOR_EVENT.get(event)
    if not state:
        return
    cwd = data.get("cwd") or os.getcwd()
    project = os.path.basename(os.path.normpath(cwd)) or "root"
    record = {"project": project, "state": state, "event": event,
              "host": platform.node(),          # so two machines' projects cannot collide
              "notification": data.get("notification_type", ""),
              "time": time.time()}
    # argv[2], or VSCODE_PANEL_URL, names a panel on another machine
    url = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("VSCODE_PANEL_URL", "")
    if url:
        post(url, record)
    else:
        write_local(record)


if __name__ == "__main__":
    main()
