# mac-remote

Control your Mac from your phone through a Telegram bot. Type what you want ("open Spotify and set volume to 30"), tap a button, or send `/code fix the failing test` to run Claude Code in a project folder.

- **Cheap.** An AI only picks one of a fixed set of tools. No screenshots go to a model, no clicking around. Buttons and slash commands use no AI at all.
- **No extra keys.** It uses your local [Claude Code](https://claude.com/claude-code) CLI and your existing Claude login. Any OpenAI-compatible API works too.
- **No open ports.** The bot long-polls Telegram, so it only makes outgoing connections.
- **Small.** About 550 lines of Python with one dependency (`httpx`).

## What it can do

| Tool | How |
|---|---|
| Status (battery, RAM, CPU load, disk, uptime) | `/status`, 📊 button |
| Screenshot, sent to you | `/screenshot`, 📸 button |
| Volume / mute | `/volume 30`, 🔇 button |
| Open / quit an app | `/open Spotify`, `/quit Spotify` |
| Display off / lock | `/lock`, 🔒 button |
| Run an Apple Shortcut you listed | `/shortcut Play Pause` |
| Run a command you defined in config | `/run wifi_ip` |
| Open a link on the Mac | send the link (or share it to the bot) |
| Send you a file from allowed folders | `/file report.pdf` or a full path |
| Alert when the Mac goes on battery, power returns, or battery is low | automatic |
| Claude Code in a chosen folder, result in Telegram | `/code <task>`, `/new`, `/stop` |
| Claude Code Remote Control in a chosen folder, continue in the Claude app | `/rc`, `/rc stop` |

Anything you type without a slash goes to the AI, which turns it into one or more of these calls. For voice, use your phone keyboard's dictation mic.

**`/code` or `/rc`?** `/code` is for quick questions: it runs headless and can only use the tools in `[code].allowed_tools`, because it can't ask you mid-run. For real work (a ticket, a long task), use `/rc`. It starts `claude remote-control` in the folder, and you work in the Claude mobile app or claude.ai/code with the full UI, permission prompts and your MCP connectors. The session's code goes through Anthropic, not Telegram. The folder must be trusted first: run `claude` in it once on the Mac.

The power alert has a limit: in a power cut your router is usually down too, so the message arrives when the power and internet come back.

Apple Shortcuts are the easy way to add more: build a shortcut (play/pause music, Focus mode, Home scenes), add its name to `shortcuts` in `config.toml`, and the bot can run it.

## Setup

Needs macOS, [uv](https://docs.astral.sh/uv/) (`brew install uv`) and, for the default AI and `/code`, Claude Code installed and logged in.

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token.
2. Install:
   ```sh
   git clone https://github.com/huseyinhobek/mac-remote && cd mac-remote
   ./install.sh
   ```
3. Put the token in `.env`.
4. Run `.venv/bin/python bot.py`, then message your bot. It replies with your chat id. Add the id to `allowed_chat_ids` in `config.toml` and restart.
5. Edit `config.toml`: your `/code` folders, shortcuts and commands.
6. Once it works, run it as a service that starts at login and restarts if it crashes:
   ```sh
   ./install.sh service
   ```

## macOS permissions

| Feature | Permission |
|---|---|
| Screenshot | Screen Recording |
| Quit app, `restart` / `shutdown` commands | Automation, asked once per target app |
| Everything else | none |

When you run the bot from Terminal, macOS grants these permissions to Terminal. The service runs the Python binary directly, so give the permissions to that binary. `./install.sh service` prints its path. Without Screen Recording, screenshots show only the wallpaper.

`/lock` only turns the display off. To make that a real lock, set System Settings > Lock Screen > "Require password after screen saver begins or display is turned off" to **Immediately**.

## Keeping the Mac reachable

- The bot keeps the Mac from idle-sleeping while it runs (`caffeinate -i`).
- **A closed MacBook lid** still puts it to sleep. Either leave the lid open or run `sudo pmset -a disablesleep 1` (undo with `0`).
- **FileVault:** after a restart, the Mac waits at the disk password screen with no network until you log in. Remote restarts and overnight automatic updates can lock you out until you get home. Consider turning off automatic macOS update installs.

## Security

- Only chat ids in `allowed_chat_ids` are served. Messages from anyone else are ignored.
- The AI never writes commands. It can only pick a tool name and fill typed arguments, and the code validates them. Commands are predefined lists of arguments, never run through a shell.
- Commands with `confirm = true` need a Yes tap. Each button works once and expires after 2 minutes.
- Messages older than 5 minutes are skipped, so nothing queued while the bot was down runs later.
- Logs go to `logs/` and rotate at 1 MB × 3. The bot token is redacted.
- **If your Telegram account is taken over, the attacker controls whatever this bot can do**, including `/code`. So turn on Telegram's two-step verification (cloud password), keep `[code].allowed_tools` narrow, and keep in mind that your own Claude Code permission settings also apply.
- Bot messages, screenshots and `/code` output pass through Telegram's servers. Bot chats are not end-to-end encrypted.

## Config

See [`config.example.toml`](config.example.toml). To use an API instead of the Claude CLI:

```toml
[ai]
provider = "openai"
base_url = "https://api.groq.com/openai/v1"   # or OpenAI, Gemini, OpenRouter, ...
model = "llama-3.3-70b-versatile"
api_key_env = "AI_API_KEY"                    # set AI_API_KEY in .env
```

## Tests

```sh
.venv/bin/python test_mac_remote.py
```

## License

MIT
