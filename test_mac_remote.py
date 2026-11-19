"""Run: .venv/bin/python test_mac_remote.py"""
import tools
from code_runner import _step

tools.init({
    "shortcuts": [],
    "commands": {"wifi_ip": {"run": ["true"]}, "restart": {"run": ["true"], "confirm": True}},
})


def raises(raw):
    try:
        tools.validate(raw)
    except ValueError:
        return True
    return False


# good calls, AI-style string numbers are coerced
assert tools.validate([{"tool": "set_volume", "args": {"level": "30"}}]) == [("set_volume", {"level": 30})]
assert tools.validate([{"tool": "run_command", "args": {"name": "wifi_ip"}}]) == [("run_command", {"name": "wifi_ip"})]
# rejected: unknown tool, bad/missing arg, empty name, command not in config, hidden tool
assert raises([{"tool": "rm_rf", "args": {}}])
assert raises([{"tool": "set_volume", "args": {"level": "loud"}}])
assert raises([{"tool": "set_volume", "args": {}}])
assert raises([{"tool": "open_app", "args": {"name": " "}}])
assert raises([{"tool": "run_command", "args": {"name": "rm -rf /"}}])
assert raises([{"tool": "run_shortcut", "args": {"name": "x"}}])  # no shortcuts configured
assert "run_shortcut" not in tools.available() and "run_shortcut" not in tools.describe()
# confirm only where config says so
assert tools.needs_confirm("run_command", {"name": "restart"})
assert not tools.needs_confirm("run_command", {"name": "wifi_ip"})
assert not tools.needs_confirm("set_volume", {"level": 0})
# /code progress label
ev = {"type": "assistant", "message": {"content": [{"type": "text"}, {"type": "tool_use", "name": "Edit", "input": {"file_path": "/p/src/a.ts"}}]}}
assert _step(ev, "/p") == "Edit src/a.ts"
assert _step({"type": "user"}, "/p") is None
print("ok")

# /file: only inside allowed folders, never hidden paths
import tempfile
from pathlib import Path
root = Path(tempfile.mkdtemp()).resolve()
(root / "a.pdf").write_text("x"); (root / ".env").write_text("x")
assert tools.file_allowed(root / "a.pdf", [root])
assert not tools.file_allowed(root / ".env", [root])
assert not tools.file_allowed(root / ".." / "x", [root])
assert not tools.file_allowed(Path("/etc/hosts"), [root])
tools.CFG["files"] = [str(root)]
assert tools.send_file(str(root / "a.pdf")).kind == "document"
assert "send_file" in tools.available()
# links: http(s) only
try:
    tools.open_url("file:///etc/passwd"); assert False
except RuntimeError:
    pass
# power
assert tools.parse_power("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t19%; discharging") == (False, 19)
assert tools.parse_power("Now drawing from 'AC Power'") == (True, None)
# /rc link out of the redrawn, escape-coded status output
from code_runner import ANSI, RC_URL
raw = "\x1b[2K·✔︎· Connected\r\n\x1b]8;;https://claude.ai/code/session_X?from=cli\x07Attached\x1b]8;;\x07\nContinue in https://claude.ai/code?environment=env_1\n"
assert RC_URL.search(ANSI.sub("", raw)).group(0) == "https://claude.ai/code?environment=env_1"
print("ok 2")
# Slack: the AI can only draft; sending is internal and always confirmed
assert "slack_send" not in tools.available()
assert raises([{"tool": "slack_send", "args": {}}])
assert tools.needs_confirm("slack_send", {})
assert tools.FOLLOWUP["slack_message"] == "slack_send"
print("ok 3")
# ask_claude only exists when read-only tools are configured
assert "ask_claude" not in tools.available()
tools.CFG["ask"] = {"allowed_tools": ["mcp__x__read"]}
assert "ask_claude" in tools.available()
print("ok 4")
