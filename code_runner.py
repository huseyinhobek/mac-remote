"""/code: run headless Claude Code in a chosen folder, report progress, keep the session per folder."""
import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path

ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]")
RC_URL = re.compile(r"https://claude\.ai/code\S*")
RC_LOGS = Path(__file__).resolve().parent / "logs"


def _mmss(t0):
    s = int(time.time() - t0)
    return f"{s // 60}:{s % 60:02d}"


def _step(ev, root):
    """Short label for the latest tool call in a stream-json event, e.g. 'Edit src/app.ts'."""
    if ev.get("type") != "assistant":
        return None
    for c in reversed(ev.get("message", {}).get("content", [])):
        if c.get("type") == "tool_use":
            inp = c.get("input", {})
            target = str(inp.get("file_path") or inp.get("command") or inp.get("pattern") or inp.get("description") or "")
            return f"{c['name']} {target.replace(str(root) + '/', '')}".strip()[:80]
    return None


class CodeRunner:
    def __init__(self, cfg, tg):
        c = cfg.get("code", {})
        self.folders = {k: Path(v).expanduser() for k, v in c.get("folders", {}).items()}
        self.tools = c.get("allowed_tools", [])
        self.model = c.get("model")
        self.timeout = c.get("timeout_minutes", 20) * 60
        self.tg = tg
        self.folder = next(iter(self.folders)) if len(self.folders) == 1 else None
        self.sessions = {}   # folder alias -> Claude session id, so follow-ups continue
        self.waiting = None  # task sent before a folder was picked
        self.proc = None

    def code(self, chat, task):
        if not self.folders:
            return self.tg.send(chat, "No folders in config.toml [code.folders].")
        if task and self.folder:
            return self.start(chat, task)
        self.waiting = task or None
        rows = [[{"text": a, "callback_data": f"dir:{a}"}] for a in self.folders]
        self.tg.send(chat, "Pick a folder:", reply_markup={"inline_keyboard": rows})

    def pick(self, chat, alias, msg_id):
        if alias not in self.folders:
            return
        self.folder = alias
        self.tg("editMessageText", chat_id=chat, message_id=msg_id, text=f"📁 {alias}")
        task, self.waiting = self.waiting, None
        if task:
            self.start(chat, task)
        else:
            self.tg.send(chat, "Folder set. Send /code <task>.")

    def new(self, chat):
        self.sessions.pop(self.folder, None)
        self.tg.send(chat, "Next /code starts a fresh session.")

    def stop(self, chat):
        if self.proc and self.proc.poll() is None:
            self._kill(self.proc)
            self.tg.send(chat, "Stopping…")
        else:
            self.tg.send(chat, "Nothing running.")

    def start(self, chat, task):
        if self.proc and self.proc.poll() is None:
            return self.tg.send(chat, "A job is already running. /stop it first.")
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose"]
        if self.tools:
            cmd += ["--allowedTools", ",".join(self.tools)]
        if self.model:
            cmd += ["--model", self.model]
        if self.folder in self.sessions:
            cmd += ["--resume", self.sessions[self.folder]]
        # task goes in on stdin so text starting with "-" is never read as a flag
        self.proc = subprocess.Popen(cmd, cwd=self.folders[self.folder], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, start_new_session=True)
        self.proc.stdin.write(task)
        self.proc.stdin.close()
        threading.Thread(target=self._watch, args=(chat, self.proc, self.folder), daemon=True).start()

    def _kill(self, proc):
        try:
            os.killpg(proc.pid, signal.SIGTERM)  # the whole group: claude and the shells it started
        except ProcessLookupError:
            pass

    def _watch(self, chat, proc, folder):
        t0 = time.time()
        msg = self.tg.send(chat, f"⏳ {folder}: started")["message_id"]
        timer = threading.Timer(self.timeout, self._kill, [proc])
        timer.start()
        last_edit, result, noise = 0.0, None, []
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                noise = (noise + [line.strip()])[-5:]
                continue
            if ev.get("session_id"):
                self.sessions[folder] = ev["session_id"]
            if ev.get("type") == "result":
                result = ev
            step = _step(ev, self.folders[folder])
            if step and time.time() - last_edit > 5:
                last_edit = time.time()
                try:
                    self.tg("editMessageText", chat_id=chat, message_id=msg, text=f"⏳ {folder} · {_mmss(t0)} · {step}")
                except Exception:
                    pass  # progress is best-effort
        proc.wait()
        timer.cancel()
        if result:
            head, text = ("❌" if result.get("is_error") else "✅"), (result.get("result") or "(no output)")
        else:
            head, text = "⏹", "\n".join(noise) or f"Stopped (exit {proc.returncode})."
        try:
            self.tg("editMessageText", chat_id=chat, message_id=msg, text=f"{head} {folder} · {_mmss(t0)}")
        except Exception:
            pass
        self.tg.send(chat, text)


class RemoteControl:
    """/rc: start `claude remote-control` in a folder, then drive it from the Claude app.
    Servers are found by name with pgrep, so they survive bot restarts and /rc stop still finds them."""

    def __init__(self, cfg, tg):
        self.folders = {k: Path(v).expanduser() for k, v in cfg.get("code", {}).get("folders", {}).items()}
        self.mode = cfg.get("code", {}).get("rc_permission_mode")
        self.tg = tg

    def _pids(self, alias=""):
        pattern = f"remote-control --name mac-remote:{re.escape(alias)}" + ("( |$)" if alias else "")
        p = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        return [int(x) for x in p.stdout.split()]

    def menu(self, chat, arg):
        if arg == "stop":
            return self.stop(chat)
        if not self.folders:
            return self.tg.send(chat, "No folders in config.toml [code.folders].")
        rows = [[{"text": ("🟢 " if self._pids(a) else "") + a, "callback_data": f"rc:{a}"}] for a in self.folders]
        self.tg.send(chat, "Start Remote Control in:", reply_markup={"inline_keyboard": rows})

    def start(self, chat, alias, msg_id):
        if alias not in self.folders:
            return
        self.tg("editMessageText", chat_id=chat, message_id=msg_id, text=f"📁 {alias}")
        if self._pids(alias):
            return self.tg.send(chat, f"🟢 {alias} is already on. Open the Claude app, or /rc stop.")
        cmd = ["claude", "remote-control", "--name", f"mac-remote:{alias}"]
        if self.mode:
            cmd += ["--permission-mode", self.mode]
        out = RC_LOGS / f"rc-{alias}.log"
        RC_LOGS.mkdir(exist_ok=True)
        # Output goes to a file, not to us, so the server outlives a bot restart. It redraws its status
        # line forever (~50 MB/day), so keep the first 20 KB (has the link) and drop the rest.
        sh = f"{shlex.join(cmd)} 2>&1 | {{ head -c 20000 > {shlex.quote(str(out))}; cat > /dev/null; }}"
        proc = subprocess.Popen(["/bin/sh", "-c", sh], cwd=self.folders[alias], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        threading.Thread(target=self._report, args=(chat, alias, proc, out), daemon=True).start()

    def _report(self, chat, alias, proc, out):
        for _ in range(90):
            time.sleep(1)
            text = ANSI.sub("", out.read_text(errors="replace")) if out.exists() else ""
            m = RC_URL.search(text)
            if m:
                self.tg.send(chat, f"🟢 {alias}: Remote Control is on. Open it in the Claude app or {m.group(0)}")
                proc.wait()
                return self.tg.send(chat, f"⏹ {alias}: Remote Control stopped.")
            if proc.poll() is not None:
                tail = [l.strip() for l in text.replace("\r", "\n").splitlines() if l.strip()][-5:]
                return self.tg.send(chat, f"❌ {alias}: " + ("\n".join(tail) or "exited"))
        self.tg.send(chat, f"⚠️ {alias}: no link after 90 s, see {out}")

    def stop(self, chat):
        pids = self._pids()
        for pid in pids:
            try:
                os.killpg(pid, signal.SIGTERM)  # its own group: the server and the sessions it spawned
            except ProcessLookupError:
                pass
        self.tg.send(chat, f"Stopping {len(pids)} process(es)…" if pids else "No Remote Control running.")
