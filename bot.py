"""mac-remote: control your Mac from Telegram. Outbound long polling only, no open ports."""
import json
import logging
import logging.handlers
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

import httpx

import ai
import tools
from code_runner import CodeRunner, RemoteControl

ROOT = Path(__file__).resolve().parent
MAX_AGE = 300      # skip messages that queued up while the bot was down
CONFIRM_TTL = 120  # seconds a confirm button stays valid

BUTTONS = {"Status": ("status", {}), "Screenshot": ("screenshot", {}),
           "Mute": ("set_volume", {"level": 0}), "Lock": ("lock_screen", {})}
KEYBOARD = {"keyboard": [["Status", "Screenshot"], ["Mute", "Lock"]],
            "resize_keyboard": True, "is_persistent": True}
SLASH = {"/status": ("status", None), "/screenshot": ("screenshot", None), "/lock": ("lock_screen", None),
         "/volume": ("set_volume", "level"), "/open": ("open_app", "name"), "/quit": ("quit_app", "name"),
         "/shortcut": ("run_shortcut", "name"), "/run": ("run_command", "name"), "/file": ("send_file", "path")}
HELP = """Control this Mac. Use the buttons, or just write what you want ("open Safari and set the volume to 30").

/status /screenshot /lock
/volume 0-100 · /open App · /quit App
/shortcut Name · /run name · /file name-or-path
Send a link: it opens on the Mac.
/code task: Claude Code in a folder (/code alone picks the folder)
/new: fresh Claude session · /stop: stop the running job
/rc: start Remote Control in a folder, continue in the Claude app · /rc stop

Voice: send a voice message. It is transcribed on this Mac."""

log = logging.getLogger("mac-remote")


class Redact(logging.Formatter):
    def format(self, record):
        return super().format(record).replace(os.environ.get("TELEGRAM_BOT_TOKEN") or "\0", "<token>")


def setup_logging():
    (ROOT / "logs").mkdir(exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(ROOT / "logs" / "mac-remote.log", maxBytes=1_000_000, backupCount=3)]
    if sys.stderr.isatty():
        handlers.append(logging.StreamHandler())
    for h in handlers:
        h.setFormatter(Redact("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    log.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines contain the token URL


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


class Telegram:
    def __init__(self, token):
        self.url = f"https://api.telegram.org/bot{token}/"
        self.file_url = f"https://api.telegram.org/file/bot{token}/"
        self.http = httpx.Client(timeout=70)

    def __call__(self, method, files=None, **params):
        if files:
            r = self.http.post(self.url + method, data=params, files=files, timeout=600)  # big uploads
        else:
            r = self.http.post(self.url + method, json=params)
        d = r.json()
        if not d.get("ok"):
            raise RuntimeError(f"{method}: {d.get('description')}")
        return d["result"]

    def download(self, file_id, dest):
        r = self.http.get(self.file_url + self("getFile", file_id=file_id)["file_path"])
        r.raise_for_status()
        Path(dest).write_bytes(r.content)

    def send(self, chat, text, ids=None, **kw):
        text = text or "(empty)"
        for i in range(0, len(text), 4000):  # Telegram caps a message at 4096 chars
            msg = self("sendMessage", chat_id=chat, text=text[i:i + 4000], **kw)
            if ids is not None:
                ids.append(msg["message_id"])
        return msg


class Janitor:
    """Deletes messages later. The queue lives in a file, so a restart doesn't forget it."""

    def __init__(self, tg, path):
        self.tg, self.path, self.lock = tg, path, threading.Lock()

    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []

    def add(self, chat, ids, minutes):
        with self.lock:
            q = self._load() + [{"chat": chat, "id": i, "at": time.time() + minutes * 60} for i in ids]
            self.path.write_text(json.dumps(q))

    def sweep(self):
        with self.lock:
            q, keep = self._load(), []
            for item in q:
                if item["at"] > time.time():
                    keep.append(item)
                    continue
                try:
                    self.tg("deleteMessage", chat_id=item["chat"], message_id=item["id"])
                except Exception as e:
                    if "not found" not in str(e) and "can't be deleted" not in str(e):
                        keep.append(item)  # network trouble: try again next sweep
            if len(keep) != len(q):
                self.path.write_text(json.dumps(keep))

    def loop(self):
        while True:
            time.sleep(30)
            try:
                self.sweep()
            except Exception as e:
                log.warning("cleanup failed: %s", e)


class Bot:
    def __init__(self, cfg, tg):
        self.cfg, self.tg = cfg, tg
        self.allowed = set(cfg.get("allowed_chat_ids", []))
        self.pending = {}  # nonce -> (calls, expires_at)
        self.runner = CodeRunner(cfg, tg)
        self.rc = RemoteControl(cfg, tg)
        self.janitor = Janitor(tg, ROOT / "logs" / "delete-queue.json")
        self.ask_ttl = cfg.get("ask", {}).get("delete_after_minutes", 60)
        self.trail = []  # ids of the current request's messages, deleted with an ask_claude answer

    def handle(self, u):
        if "callback_query" in u:
            self.on_callback(u["callback_query"])
        elif "message" in u:
            self.on_message(u["message"])

    def on_message(self, m):
        chat = m["chat"]["id"]
        if chat not in self.allowed:
            log.warning("ignored chat %s", chat)
            if not self.allowed:  # setup mode: tell the owner their id
                self.tg.send(chat, f"Your chat id is {chat}. Put it in config.toml allowed_chat_ids and restart.")
            return
        if time.time() - m["date"] > MAX_AGE:
            log.info("skipped stale message")
            return
        self.trail = [m["message_id"]]
        text = (m.get("text") or "").strip()
        voice = m.get("voice") or m.get("audio")
        if not text and voice:
            text = self.hear(chat, voice)
            if not text:
                return
        if not text:
            return self.tg.send(chat, "Send text or a voice message.")
        log.info("in: %s", text)
        if text in BUTTONS:
            return self.run(chat, [BUTTONS[text]])
        if text.startswith("/"):
            return self.command(chat, text)
        if re.fullmatch(r"https?://\S+", text):
            return self.run(chat, [("open_url", {"url": text})])
        self.tg("sendChatAction", chat_id=chat, action="typing")
        raw = ai.parse(self.cfg, text, tools.describe(), tools.available())
        log.info("ai: %s", raw)
        calls = tools.validate(raw.get("calls") or [])
        if calls:
            self.run(chat, calls)
        else:
            self.tg.send(chat, raw.get("reply") or "Nothing to do.")

    def hear(self, chat, voice):
        if voice.get("file_size", 0) > 20 * 2**20:  # the Bot API only downloads up to 20 MB
            self.tg.send(chat, "That recording is too long.")
            return None
        self.tg("sendChatAction", chat_id=chat, action="typing")
        fd, path = tempfile.mkstemp(suffix=".ogg")
        os.close(fd)
        try:
            self.tg.download(voice["file_id"], path)
            text = tools.transcribe(path, self.cfg.get("voice_language", ""))
        finally:
            os.unlink(path)
        log.info("heard: %s", text)
        self.tg.send(chat, f"Heard: {text}" if text else "I couldn't make out any words.", ids=self.trail)
        return text

    def command(self, chat, text):
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.split("@")[0].lower(), arg.strip()
        if cmd in ("/start", "/help"):
            self.tg.send(chat, HELP, reply_markup=KEYBOARD)
        elif cmd == "/volume" and not arg:  # tapped from the command menu
            self.tg.send(chat, "Volume:", reply_markup={"inline_keyboard": [
                [{"text": str(v), "callback_data": f"vol:{v}"} for v in (0, 25, 50, 75, 100)]]})
        elif cmd in SLASH and SLASH[cmd][1] and not arg:
            self.tg.send(chat, f"Usage: {cmd} <{SLASH[cmd][1]}>")
        elif cmd in SLASH:
            tool, param = SLASH[cmd]
            self.run(chat, tools.validate([{"tool": tool, "args": {param: arg} if param else {}}]))
        elif cmd == "/code":
            self.runner.code(chat, arg)
        elif cmd == "/new":
            self.runner.new(chat)
        elif cmd == "/stop":
            self.runner.stop(chat)
        elif cmd == "/rc":
            self.rc.menu(chat, arg)
        else:
            self.tg.send(chat, "Unknown command. /help")

    def run(self, chat, calls):
        risky = [tools.CONFIRM_LABEL.get(n) or " ".join([n, *map(str, a.values())])
                 for n, a in calls if tools.needs_confirm(n, a)]
        if not risky:
            return self.execute(chat, calls)
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v[1] > now}
        nonce = secrets.token_urlsafe(8)
        self.pending[nonce] = (calls, now + CONFIRM_TTL)
        self.tg.send(chat, f"Confirm: {', '.join(risky)}?", reply_markup={"inline_keyboard": [[
            {"text": "Yes", "callback_data": f"ok:{nonce}"}, {"text": "No", "callback_data": f"no:{nonce}"}]]})

    def execute(self, chat, calls):
        out, followups = [], []
        for name, args in calls:
            log.info("tool: %s %s", name, args)
            try:
                res = tools.call(name, args)
            except Exception as e:
                log.warning("tool failed: %s %s", name, e)
                out.append(f"{name} failed: {e}")
                continue
            if name == "ask_claude" and self.ask_ttl:
                ids = list(self.trail)
                self.tg.send(chat, res, ids=ids)
                self.janitor.add(chat, ids, self.ask_ttl)
                continue
            if isinstance(res, tools.Upload):
                try:
                    with res.path.open("rb") as f:
                        self.tg("sendPhoto" if res.kind == "photo" else "sendDocument", files={res.kind: f}, chat_id=chat)
                finally:
                    if res.temp:
                        res.path.unlink(missing_ok=True)
            else:
                out.append(res)
            if name in tools.FOLLOWUP:
                followups.append((tools.FOLLOWUP[name], {}))
        if out:
            self.tg.send(chat, "\n".join(out))
        if followups:
            self.run(chat, followups)  # e.g. the Slack draft is on screen, now ask before sending

    def on_callback(self, q):
        chat, msg = q["message"]["chat"]["id"], q["message"]["message_id"]
        self.tg("answerCallbackQuery", callback_query_id=q["id"])
        if chat not in self.allowed:
            return log.warning("ignored callback from chat %s", chat)
        kind, _, val = q.get("data", "").partition(":")
        log.info("button: %s %s", kind, val if kind in ("dir", "rc", "vol") else "")
        if kind == "dir":
            return self.runner.pick(chat, val, msg)
        if kind == "rc":
            return self.rc.start(chat, val, msg)
        if kind == "vol":
            return self.run(chat, tools.validate([{"tool": "set_volume", "args": {"level": val}}]))
        calls, expires = self.pending.pop(val, (None, 0))  # pop: each button works once
        ok = kind == "ok" and calls and time.time() < expires
        note = "Running…" if ok else "Cancelled." if kind == "no" else "Expired."
        self.tg("editMessageText", chat_id=chat, message_id=msg, text=f"{q['message'].get('text', '')}\n→ {note}")
        if ok:
            log.info("confirmed: %s", calls)
            self.execute(chat, calls)


def watch_power(tg, chats, low):
    """Message on battery/AC switches and low battery. Unsent alerts wait: in a power cut the router may be off too."""
    last, warned, outbox = None, False, []
    while True:
        try:
            ac, pct = tools.power()
            now = time.strftime("%H:%M")
            if last is not None and ac != last:
                outbox.append(f"Power is back ({now}). Battery {pct}%." if ac else
                              f"Running on battery since {now} ({pct}%). Power cut or unplugged?")
            if ac:
                warned = False
            elif low and pct is not None and pct <= low and not warned:
                outbox.append(f"Battery at {pct}%. The Mac will sleep when it runs out.")
                warned = True
            last = ac
        except Exception as e:
            log.warning("power check failed: %s", e)
        while outbox:
            try:
                for c in chats:
                    tg.send(c, outbox[0])
                outbox.pop(0)
            except Exception:
                break
        time.sleep(60)


def main():
    load_env(ROOT / ".env")
    setup_logging()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN missing in .env")
    cfg = tomllib.loads((ROOT / "config.toml").read_text())
    tools.init(cfg)
    tg = Telegram(token)
    bot = Bot(cfg, tg)
    subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])  # no idle sleep while the bot runs
    threading.Thread(target=bot.janitor.loop, daemon=True).start()
    if bot.allowed and cfg.get("battery_alert", 20):
        threading.Thread(target=watch_power, args=(tg, bot.allowed, cfg.get("battery_alert", 20)), daemon=True).start()
    tg("setMyCommands", commands=[{"command": c.strip("/"), "description": d} for c, d in [
        ("/status", "battery, RAM, disk"), ("/screenshot", "screenshot"), ("/lock", "display off"),
        ("/volume", "volume 0-100"), ("/file", "send me a file"), ("/code", "Claude Code task"), ("/stop", "stop the job"),
        ("/rc", "Remote Control in a folder"), ("/help", "help")]])
    log.info("started, allowed chats: %s", bot.allowed or "none (setup mode)")
    offset = None
    while True:
        try:
            updates = tg("getUpdates", timeout=50, offset=offset, allowed_updates=["message", "callback_query"])
        except Exception as e:
            log.warning("poll failed: %s", e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                bot.handle(u)
            except Exception as e:
                if isinstance(e, ValueError):  # rejected input, not a bug
                    log.warning("rejected: %s", e)
                else:
                    log.exception("handler failed")
                chat = (u.get("message") or u.get("callback_query", {}).get("message") or {}).get("chat", {}).get("id")
                if chat in bot.allowed:
                    try:
                        tg.send(chat, f"Error: {e}")
                    except Exception:
                        pass


if __name__ == "__main__":
    main()
