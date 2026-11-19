"""The fixed tool set. The AI may only pick a tool and fill its typed args."""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

CFG = {}
TG_FILE_LIMIT = 50 * 2**20  # Telegram bots can upload up to 50 MB


class Upload(NamedTuple):
    path: Path
    kind: str   # "photo" or "document"
    temp: bool  # delete after sending


def init(cfg):
    CFG.clear()
    CFG.update(cfg)


def sh(*args, timeout=30):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[-500:] or f"exit {p.returncode}")
    return p.stdout.strip()


def status():
    lines = sh("pmset", "-g", "batt").splitlines()
    batt = lines[1].split("\t")[-1].split(" present")[0] if len(lines) > 1 else "no battery"
    ram = sh("memory_pressure").splitlines()[-1].split(":")[-1].strip()
    disk = shutil.disk_usage("/")
    boot = int(sh("sysctl", "-n", "kern.boottime").split("sec = ")[1].split(",")[0])
    up = int(time.time()) - boot
    return (f"Battery  {batt}\n"
            f"Memory  {ram} free\n"
            f"CPU load  {os.getloadavg()[0]:.1f} on {os.cpu_count()} cores\n"
            f"Disk  {disk.free / 2**30:.0f} GB free of {disk.total / 2**30:.0f} GB\n"
            f"Uptime  {up // 86400}d {up % 86400 // 3600}h")


def screenshot():
    subprocess.Popen(["caffeinate", "-u", "-t", "3"])  # a sleeping display captures black
    time.sleep(1)
    fd, path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    sh("screencapture", "-x", "-t", "jpg", path)
    return Upload(Path(path), "photo", True)


def open_url(url):
    if not re.match(r"https?://", url):
        raise RuntimeError("only http(s) links")
    sh("open", url)
    return "Opened the link"


def _file_roots():
    return [Path(p).expanduser().resolve() for p in CFG.get("files", [])]


def file_allowed(p, roots):
    p = p.resolve()
    for r in roots:
        if p.is_relative_to(r):
            return not any(s.startswith(".") for s in p.relative_to(r).parts)  # never .env, .git, .ssh
    return False


def send_file(path):
    roots = _file_roots()
    p = Path(path).expanduser()
    if not (p.is_absolute() and p.is_file()):  # a bare name: search the allowed folders with Spotlight
        hits = {Path(h) for r in roots for h in sh("mdfind", "-onlyin", str(r), "-name", p.name).splitlines()}
        hits = sorted(h for h in hits if h.is_file() and file_allowed(h, roots))
        if not hits:
            raise RuntimeError(f"not found: {path}")
        if len(hits) > 1:
            return "Which one? Send /file with the full path:\n" + "\n".join(map(str, hits[:10]))
        p = hits[0]
    if not file_allowed(p, roots):
        raise RuntimeError("not allowed: hidden, or outside the folders in config.toml")
    if p.stat().st_size > TG_FILE_LIMIT:
        raise RuntimeError("over Telegram's 50 MB limit")
    return Upload(p.resolve(), "document", False)


def _locked():
    return "CGSSessionScreenIsLocked" in sh("ioreg", "-n", "Root", "-d1")  # the key only exists while locked


def _keys(script):
    sh("osascript", "-e", f'tell application "System Events" to {script}')  # needs Accessibility


def _paste(text):
    # paste instead of typing: keystroke garbles ç, ş, ğ on some keyboard layouts
    subprocess.run(["pbcopy"], input=text, text=True, check=True)
    _keys('keystroke "v" using command down')


def slack_message(to, text):
    """Open the DM via Slack's quick switcher and paste the text, without sending. slack_send sends it."""
    if _locked():
        raise RuntimeError("the screen is locked, unlock the Mac first")
    old = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout  # shortcut: text clipboard only, images are lost
    was_running = subprocess.run(["pgrep", "-x", "Slack"], capture_output=True).returncode == 0
    sh("open", "-a", "Slack")
    time.sleep(1.5 if was_running else 8)
    try:
        _keys('keystroke "k" using command down')
        time.sleep(1)
        _paste(to)
        time.sleep(1.5)
        _keys("key code 36")  # Return: jump to the top match
        time.sleep(2)
        _paste(text)
        time.sleep(0.5)
    finally:
        subprocess.run(["pbcopy"], input=old, text=True)
    return screenshot()


def slack_send():
    sh("open", "-a", "Slack")
    time.sleep(1)
    _keys("key code 36")
    return "Sent"


ASK_RULES = "Answer briefly, in the user's language. Never mention tools, connectors or their setup."


def ask_claude(question):
    """Answer from the user's connected apps with Claude Code. No built-in tools, only the read-only tools in [ask]."""
    c = CFG["ask"]
    # shortcut: runs in the poll loop, so other messages wait 10-30 s; move to a thread if that starts to hurt
    p = subprocess.run(["claude", "-p", "--model", c.get("model", "sonnet"), "--tools", "", "--no-session-persistence",
                        "--output-format", "json", "--append-system-prompt", ASK_RULES,
                        "--allowedTools", ",".join(c["allowed_tools"])],
                       input=question, capture_output=True, text=True, timeout=300, cwd=tempfile.gettempdir())
    try:
        d = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError((p.stderr or p.stdout).strip()[-300:] or "claude failed") from None
    if d.get("is_error"):
        raise RuntimeError(str(d.get("result"))[:300])
    denied = sorted({x.get("tool_name") for x in d.get("permission_denials", [])})
    if denied:  # a read tool missing from [ask] allowed_tools makes answers vague
        logging.getLogger("mac-remote").warning("ask denied tools: %s", ", ".join(denied))
    return d.get("result") or "(no answer)"


TRANSCRIBER = Path(__file__).resolve().parent / ".venv" / "bin" / "transcribe"  # built by install.sh


def transcribe(path, language=""):
    if not TRANSCRIBER.exists():
        raise RuntimeError("voice messages need macOS 26 or later and ./install.sh to build the transcriber")
    return sh(str(TRANSCRIBER), path, language, timeout=180)


def parse_power(out):
    m = re.search(r"(\d+)%", out)
    return "AC Power" in out, int(m.group(1)) if m else None


def power():
    return parse_power(sh("pmset", "-g", "batt"))


def set_volume(level):
    level = max(0, min(100, level))
    sh("osascript", "-e", f"set volume output volume {level}")  # level is an int
    return f"Volume {level}"


def open_app(name):
    sh("open", "-a", name)
    return f"Opened {name}"


def quit_app(name):
    # name goes in as argv, never into the script text
    sh("osascript", "-e", "on run argv", "-e", "set n to item 1 of argv",
       "-e", "if application n is running then tell application n to quit", "-e", "end run", name)
    return f"Quit {name}"


def lock_screen():
    sh("pmset", "displaysleepnow")
    return "Display off"


def run_shortcut(name):
    return sh("shortcuts", "run", name, timeout=120)[:3500] or f"Ran shortcut {name}"


def run_command(name):
    return sh(*CFG["commands"][name]["run"], timeout=120)[:3500] or "Done"


TOOLS = {
    "status": (status, {}, "battery, RAM, CPU load, disk, uptime"),
    "screenshot": (screenshot, {}, "send a screenshot of the screen"),
    "set_volume": (set_volume, {"level": int}, "output volume 0-100, 0 = mute"),
    "open_url": (open_url, {"url": str}, "open a link in the browser"),
    "send_file": (send_file, {"path": str}, "send the user a file, by full path or file name"),
    "open_app": (open_app, {"name": str}, "open or focus an app"),
    "quit_app": (quit_app, {"name": str}, "quit an app"),
    "lock_screen": (lock_screen, {}, "turn the display off (locks if a password is required on wake)"),
    "run_shortcut": (run_shortcut, {"name": str}, "run an Apple Shortcut"),
    "run_command": (run_command, {"name": str}, "run a predefined command"),
    "ask_claude": (ask_claude, {"question": str}, "answer questions that need reading the user's Slack, email or calendar, "
                   "like summaries or what's next; pass the user's request as the question"),
    "slack_message": (slack_message, {"to": str, "text": str}, "write a Slack DM or channel message; the user confirms before it is sent"),
    "slack_send": (slack_send, {}, "internal"),
}
FOLLOWUP = {"slack_message": "slack_send"}  # after the first succeeds, ask to confirm the second
INTERNAL = set(FOLLOWUP.values())           # never offered to the AI
CONFIRM_LABEL = {"slack_send": "send the Slack message in the screenshot"}


def allowed_names(tool):
    """None = any name; a list = only these (an empty list hides the tool)."""
    if tool == "run_shortcut":
        return CFG.get("shortcuts", [])
    if tool == "run_command":
        return list(CFG.get("commands", {}))
    return None


def available():
    return [t for t in TOOLS if t not in INTERNAL and allowed_names(t) != []
            and (t != "send_file" or CFG.get("files"))
            and (t != "ask_claude" or CFG.get("ask", {}).get("allowed_tools"))
            and (t != "slack_message" or Path("/Applications/Slack.app").exists())]


def describe():
    lines = []
    for name in available():
        _, params, desc = TOOLS[name]
        sig = ", ".join(f"{p}: {t.__name__}" for p, t in params.items())
        names = allowed_names(name)
        extra = f" (name is one of: {', '.join(names)})" if names else ""
        if name == "send_file":
            extra = f" (folders: {', '.join(CFG['files'])})"
        lines.append(f"- {name}({sig}): {desc}{extra}")
    return "\n".join(lines)


def validate(raw):
    """Turn [{"tool", "args"}] from the AI or a slash command into checked (name, args) pairs."""
    calls = []
    for c in raw:
        name, args = c.get("tool"), c.get("args") or {}
        if name not in available():
            raise ValueError(f"unknown tool: {name}")
        clean = {}
        for p, t in TOOLS[name][1].items():
            try:
                clean[p] = t(args[p])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"{name}: missing or bad {p}") from None
            if t is str and not clean[p].strip():
                raise ValueError(f"{name}: empty {p}")
        names = allowed_names(name)
        if names is not None and clean["name"] not in names:
            raise ValueError(f"{name}: '{clean['name']}' is not in config.toml")
        calls.append((name, clean))
    return calls


def needs_confirm(name, args):
    if name in INTERNAL:
        return True
    return name == "run_command" and CFG["commands"][args["name"]].get("confirm", False)


def call(name, args):
    return TOOLS[name][0](**args)
