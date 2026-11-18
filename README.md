<h1 align="center">mac-remote</h1>

<p align="center">
  <b>Control your Mac from your phone with a Telegram bot.</b><br>
  Type what you want in plain language, tap a button, or start a Claude Code session on your Mac from anywhere.
</p>

<p align="center">
  <img alt="macOS" src="https://img.shields.io/badge/platform-macOS-black?logo=apple">
  <img alt="Python" src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="Telegram" src="https://img.shields.io/badge/Telegram-bot-26A5E4?logo=telegram&logoColor=white">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

You're out, your Mac is at home, and you need it for one thing: send a file, check whether the build finished, mute the music someone left on, message a colleague, or start a coding task. **mac-remote** turns a private Telegram chat into a remote control for your Mac. You get remote access from your iPhone or Android with no open ports, no VPN and no screen sharing.

```text
You:  open Slack and set the volume to 30
Mac:  Opened Slack
      🔊 Volume 30

You:  /file report.pdf
Mac:  📎 report.pdf

You:  message Alex on Slack: running 10 minutes late
Mac:  [screenshot of the drafted message]  Send the Slack message in the screenshot?  ✅ Yes  ✖️ No
```

## Why mac-remote

- **Cheap to run.** The AI only reads your message and picks one of a fixed set of tools. It never looks at your screen. By default it uses the Claude Code CLI you already have, so there's no extra API key or bill. Buttons and slash commands skip the AI entirely.
- **Safe by design.** The AI can't write shell commands. It can only choose a tool and fill in typed arguments, and the code checks them. Risky actions wait for your tap.
- **Nothing exposed.** The bot connects out to Telegram. Your router and firewall stay closed, and there's no server to rent.
- **Small enough to read.** About 550 lines of Python with one dependency. Fork it and add your own tools in a few lines.

| | mac-remote | Screen-reading AI agents | SSH / VNC from your phone |
|---|---|---|---|
| Works without opening ports or a VPN | ✅ | depends | ❌ |
| Cost per command | one short text call, or none | a screenshot to the model at every step | free |
| Plain-language commands | ✅ | ✅ | ❌ |
| Easy to use on a phone | ✅ chat + buttons | ✅ | ❌ tiny terminal or screen |
| Can't run arbitrary commands | ✅ fixed tool set | ❌ | ❌ |

## Features

**Everyday control**
- 📊 Battery, RAM, CPU load, disk and uptime at a glance
- 📸 Screenshots sent straight to your chat (they never go to the AI)
- 🔊 Volume and mute, 🔒 display off / lock
- 🚀 Open or quit any app
- ⚡ Run your Apple Shortcuts by name. Anything Shortcuts can do (music, Focus modes, Home scenes, scripts), the bot can do too
- 🛠 Your own named commands, defined in config, with optional confirmation

**Files and links**
- 🌐 Send a link, or share one to the bot, and it opens on your Mac
- 📎 `/file report.pdf` finds a file in the folders you allow and sends it to you. Hidden files like `.env` are never sent

**Messages**
- 💬 Write a Slack message from your phone. The bot opens the DM, drafts the text and shows you a screenshot. Nothing is sent until you tap Yes

**Coding from your phone**
- 🧑‍💻 `/code <task>` runs Claude Code headless in a project folder. It updates one progress message as it works (`Edit src/app.ts`) and continues the same session with your follow-ups
- 📱 `/rc` starts Claude Code **Remote Control** in a folder, so you can keep going in the Claude mobile app or at claude.ai/code with the full interface, permission prompts and your connectors. Your Mac never gets stuck because you forgot to turn Remote Control on before you left

**Peace of mind**
- 🔌 A message when your Mac switches to battery, when power comes back, and when the battery runs low

## Quick start

You need macOS, [uv](https://docs.astral.sh/uv/) (`brew install uv`) and, for the default AI and the coding commands, [Claude Code](https://claude.com/claude-code) installed and logged in.

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token.
2. Install:
   ```sh
   git clone https://github.com/huseyinhobek/mac-remote && cd mac-remote
   ./install.sh
   ```
3. Paste the token into `.env`.
4. Run `.venv/bin/python bot.py` and message your bot. It replies with your chat id. Put that id in `allowed_chat_ids` in `config.toml` and restart.
5. Edit `config.toml` to add your project folders, shortcuts and commands.
6. Once it works, install it as a login service that also restarts after a crash:
   ```sh
   ./install.sh service
   ```

## Commands

| Command | What it does |
|---|---|
| *any text* | The AI turns it into one or more tool calls |
| a link | Opens it on the Mac |
| `/status` `/screenshot` `/lock` | Same as the buttons |
| `/volume 30` | Set volume (no number shows 0–100 buttons) |
| `/open Safari` `/quit Safari` | Open or quit an app |
| `/shortcut Name` | Run an Apple Shortcut listed in config |
| `/run name` | Run a command defined in config |
| `/file name-or-path` | Send yourself a file |
| `/code task` · `/new` · `/stop` | Headless Claude Code in a folder |
| `/rc` · `/rc stop` | Claude Code Remote Control in a folder |

**`/code` or `/rc`?** Use `/code` for quick questions like "where is X in this repo?". It can't stop to ask you anything mid-run, so it only uses the tools in `[code].allowed_tools`. Use `/rc` for real work such as a ticket or a long task. That session's code goes through Anthropic, not Telegram. The folder must be trusted first: run `claude` in it once on the Mac.

## Configuration

Everything personal lives in `config.toml`, which git ignores. A short excerpt:

```toml
allowed_chat_ids = [123456789]
shortcuts = ["Play Pause", "Focus Work"]
files = ["~/Desktop", "~/Downloads"]
battery_alert = 20

[code.folders]
website = "~/Projects/website"

[commands]
wifi_ip = { run = ["ipconfig", "getifaddr", "en0"] }
restart = { run = ["osascript", "-e", 'tell application "System Events" to restart'], confirm = true }
```

See [`config.example.toml`](config.example.toml) for every option.

**Prefer an API to the Claude CLI?** Any OpenAI-compatible endpoint works (OpenAI, Groq, Gemini, OpenRouter, ...):

```toml
[ai]
provider = "openai"
base_url = "https://api.groq.com/openai/v1"
model = "llama-3.3-70b-versatile"
api_key_env = "AI_API_KEY"   # set AI_API_KEY in .env
```

## macOS permissions

| Feature | Permission |
|---|---|
| Bot or `/code` / `/rc` / `/file` folders inside Desktop, Documents or Downloads | Files and Folders for that folder |
| Screenshot | Screen Recording |
| Slack messages (typed with the keyboard) | Accessibility |
| Quit app, `restart` / `shutdown` commands | Automation, asked once per target app |
| Everything else | none |

When you run the bot from Terminal, macOS applies Terminal's permissions. The service runs its own Python binary, so give the permissions to that binary. `./install.sh service` prints its path; in the file picker press Cmd+Shift+G and paste it. Without Screen Recording, screenshots show only the wallpaper. If the service starts but never logs "started", it is waiting on a folder-access prompt: allow it, or turn it on under Files and Folders.

`/lock` turns the display off. To make that a real lock, set System Settings > Lock Screen > "Require password after screen saver begins or display is turned off" to **Immediately**.

## Keeping your Mac reachable

- While it runs, the bot keeps the Mac from idle-sleeping (`caffeinate -i`).
- **A closed MacBook lid** still puts it to sleep. Keep the lid open, or run `sudo pmset -a disablesleep 1` (undo with `0`).
- **FileVault:** after a restart, the Mac waits at the disk password screen with no network until someone logs in. Remote restarts and overnight automatic updates can lock you out until you get home. Consider turning off automatic macOS update installs.
- **Power alerts in a power cut:** your router is usually down too, so the alert arrives once power and internet come back.

## Security

- Only chat ids listed in `allowed_chat_ids` get a response. Messages from anyone else are ignored.
- The AI picks from a fixed tool list. Commands are predefined argument lists that never go through a shell.
- Commands marked `confirm = true` and every Slack send need a Yes tap. Each button works once and expires after 2 minutes.
- Messages older than 5 minutes are skipped, so nothing queued while the bot was offline runs later.
- Logs rotate at 1 MB × 3, and the bot token is redacted from them.
- **Whoever controls your Telegram account controls this bot**, `/code` included. Turn on Telegram's two-step verification (cloud password) and keep `[code].allowed_tools` narrow. Your own Claude Code permission settings also apply.
- Bot chats are not end-to-end encrypted. Screenshots, files and `/code` output pass through Telegram's servers.

## FAQ

**Can I control my Mac with my voice?**
Yes. Tap your phone keyboard's dictation mic and talk. The bot receives text, so there's no speech-to-text service to pay for.

**Do I need to open a port, set up port forwarding or run a VPN?**
No. The bot long-polls Telegram over an outgoing connection.

**Does it work on Intel Macs?**
It should. Nothing in it depends on Apple Silicon, but it has been tested on Apple Silicon.

**How do I add my own tool?**
For most things, build an Apple Shortcut and list its name in `shortcuts`, or add a named command to `[commands]`. For anything else, write one function in `tools.py` and add one line to `TOOLS`.

## Tests

```sh
.venv/bin/python test_mac_remote.py
```

## License

[MIT](LICENSE)
